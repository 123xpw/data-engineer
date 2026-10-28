"""Q1.2 独立审计：只用 CSV、Decimal、集合和计数器，不导入生产模块。"""

from collections import Counter, defaultdict
import csv
from decimal import Decimal
import re


def reference(path):
    """逐记录累计；金额精确十进制，完全独立于 pandas 分组和整数单位。"""
    buckets = {}
    country = defaultdict(lambda: defaultdict(lambda: [0, Decimal(0)]))
    product = defaultdict(lambda: defaultdict(lambda: [0, set(), Counter()]))
    identities, known_ids = defaultdict(set), defaultdict(set)
    extreme, negative = [], []
    counters = {k: {'rows': 0, 'examples': []} for k in ('c_nonnegative', 'numeric_invoice_negative', 'ordinary_stock_nonpositive')}
    precision = 0

    def add(key, r, q, p, record):
        if key not in buckets:
            buckets[key] = {'rows': 0, 'invoices': set(), 'net': Decimal(0), 'absolute': Decimal(0),
                            'quantity_sign': Counter({'negative':0, 'zero':0, 'positive':0}),
                            'price_sign': Counter({'negative':0, 'zero':0, 'positive':0}), 'descriptions': Counter(), 'examples': []}
        b = buckets[key]
        b['rows'] += 1
        b['invoices'].add(r['Invoice'])
        b['net'] += q * p
        b['absolute'] += abs(q * p)
        b['quantity_sign']['negative' if q < 0 else 'positive' if q > 0 else 'zero'] += 1
        b['price_sign']['negative' if p < 0 else 'positive' if p > 0 else 'zero'] += 1
        b['descriptions'][r['Description']] += 1
        if len(b['examples']) < 3:
            b['examples'].append(record)

    # 空组也须有明确的零记录和不适用均值。
    def empty(key):
        buckets[key] = {'rows': 0, 'invoices': set(), 'net': Decimal(0), 'absolute': Decimal(0),
                        'quantity_sign': Counter({'negative':0,'zero':0,'positive':0}), 'price_sign': Counter({'negative':0,'zero':0,'positive':0}),
                        'descriptions': Counter(), 'examples': []}
    for key in [('total',), ('special',), ('customer','missing'), ('customer','present'), ('candidate','missing'), ('candidate','present')]:
        empty(key)
    with open(path, newline='', encoding='utf-8-sig') as stream:
        for number, r in enumerate(csv.DictReader(stream), 1):
            q, p = Decimal(r['Quantity']), Decimal(r['Price'])
            precision = max(precision, -p.as_tuple().exponent)
            record = {'record': number, **r}
            numeric = bool(re.fullmatch('[0-9]+', r['Invoice']))
            match = re.match('[^0-9]+', r['Invoice'])
            prefix = match.group() if match else '' if numeric else '<无前导前缀的异常格式>'
            ordinary = bool(re.fullmatch('[0-9]+[A-Za-z]*', r['StockCode']))
            group = 'missing' if r['Customer ID'] == '' else 'present'
            add(('total',), r, q, p, record)
            add(('prefix',prefix), r, q, p, record)
            add(('customer',group), r, q, p, record)
            if not ordinary:
                add(('special',), r, q, p, record)
                add(('code',r['StockCode']), r, q, p, record)
            c = country[group][r['Country']]
            c[0] += 1; c[1] += q * p
            if numeric and ordinary and q > 0 and p > 0:
                add(('candidate',group), r, q, p, record)
                item = product[group][r['StockCode']]
                item[0] += 1; item[1].add(r['Invoice']); item[2][r['Description']] += 1
            identities[r['Invoice']].add(group)
            if r['Customer ID']:
                known_ids[r['Invoice']].add(r['Customer ID'])
            if abs(q) == 80995:
                extreme.append(record)
            if p < 0:
                negative.append(record)
            flags = {'c_nonnegative': prefix == 'C' and q >= 0, 'numeric_invoice_negative': numeric and q < 0,
                     'ordinary_stock_nonpositive': ordinary and (q <= 0 or p <= 0)}
            for key, hit in flags.items():
                if hit:
                    counters[key]['rows'] += 1
                    if len(counters[key]['examples']) < 3:
                        counters[key]['examples'].append(record)
    total = buckets[('total',)]
    money = lambda x: format(x, f'.{precision}f')
    ratio = lambda a,b: float(a/b) if b else None
    desc = lambda c: [{'value':k,'rows':v} for k,v in sorted(c.items(),key=lambda x:(-x[1],x[0]))]
    def stats(key):
        b = buckets[key]
        return {'rows': b['rows'], 'invoices':len(b['invoices']), 'net':money(b['net']), 'absolute':money(b['absolute']),
                'row_share':ratio(b['rows'], total['rows']), 'net_share':ratio(b['net'],total['net']),
                'absolute_share':ratio(b['absolute'],total['absolute']), 'invoice_mean':ratio(b['net'],len(b['invoices'])),
                'quantity_sign':dict(b['quantity_sign']), 'price_sign':dict(b['price_sign'])}
    prefixes, codes = {}, {}
    for key,b in buckets.items():
        if key[0] == 'prefix':
            prefixes[key[1]] = {**stats(key), 'descriptions':desc(b['descriptions'])[:5], 'examples':b['examples']}
        elif key[0] == 'code':
            codes[key[1]] = {**stats(key), 'descriptions':desc(b['descriptions'])}
    customers = {}
    for g in ('present','missing'):
        ranking = [{'code':c,'rows':v[0],'invoices':len(v[1]),'descriptions':desc(v[2])[:3]} for c,v in product[g].items()]
        ranking.sort(key=lambda x:(-x['invoices'],x['code']))
        customers[g] = {**stats(('customer',g)), 'candidate_sales':stats(('candidate',g)),
                        'countries': {c:{'rows':v[0], 'within_group_share':ratio(v[0],buckets[('customer',g)]['rows']), 'net':money(v[1])} for c,v in country[g].items()},
                        'top_products':ranking[:10]}
    return {'rows':total['rows'],'price_decimal_places':precision,'total':stats(('total',)), 'prefixes':prefixes,
            'special_codes':codes,'special_total':stats(('special',)), 'extremes':extreme,'negative_prices':negative,
            'customers':customers,'mixed_identity_invoices':sum(len(s)>1 for s in identities.values()),
            'multiple_known_customer_invoices':sum(len(s)>1 for s in known_ids.values()),'counterexamples':counters}


def compare(expected, actual, path='root'):
    """所有键、排序、记录、金额精确匹配；仅比率及均额容许浮点尾差。"""
    if isinstance(expected, dict):
        assert expected.keys() == actual.keys(), f'{path}: 字段不同'
        for key, value in expected.items():
            compare(value, actual[key], f'{path}.{key}')
    elif isinstance(expected, list):
        assert len(expected) == len(actual), f'{path}: 长度不同'
        for i,(e,a) in enumerate(zip(expected,actual)):
            compare(e,a,f'{path}[{i}]')
    elif isinstance(expected, float):
        assert abs(expected-actual) <= 1e-12, f'{path}: 数值不同 {expected} / {actual}'
    else:
        assert expected == actual, f'{path}: 不同 {expected!r} / {actual!r}'
