"""Q1.2：从原始数据产生可复核的业务探索，不修改输入。"""

import argparse
from decimal import Decimal
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from download_data import load_sources, verify_file

FIELDS = ['Invoice', 'StockCode', 'Description', 'Quantity', 'InvoiceDate', 'Price', 'Customer ID', 'Country']
UCI = 'https://archive.ics.uci.edu/dataset/502/online+retail+ii'


def analyze(frame):
    """按整数最小单位精确聚合；动态精度避免把三位小数强制变成分。"""
    if list(frame.columns) != FIELDS or frame.empty:
        raise ValueError('需要非空的八列原始数据')
    f = frame.copy().reset_index(drop=True)
    prices = {s: Decimal(s) for s in f.Price.unique()}
    if not all(x.is_finite() for x in prices.values()) or not f.Quantity.str.fullmatch(r'-?[0-9]+').all():
        raise ValueError('非有限价格或非整数数量需要先调查')
    precision = max(0, max(-x.as_tuple().exponent for x in prices.values()))
    scale = 10 ** precision
    f['_p'] = f.Price.map({s: int(x * scale) for s, x in prices.items()}).astype(object)
    f['_q'] = f.Quantity.map(int).astype(object)
    f['_amount'] = f['_p'] * f['_q']
    f['_missing'] = f['Customer ID'].eq('')
    f['_prefix'] = f.Invoice.str.extract(r'^([^0-9]+)', expand=False).fillna('')
    f.loc[~f.Invoice.str.fullmatch(r'[0-9]+') & f['_prefix'].eq(''), '_prefix'] = '<无前导前缀的异常格式>'
    f['_ordinary'] = f.StockCode.str.fullmatch(r'[0-9]+[A-Za-z]*')
    f['_candidate'] = f.Invoice.str.fullmatch(r'[0-9]+') & f['_ordinary'] & f['_q'].gt(0) & f['_p'].gt(0)
    f['_record'] = f.index + 1
    money = lambda n: format(Decimal(int(n)).scaleb(-precision), 'f')
    net, absolute = int(f['_amount'].sum()), int(f['_amount'].abs().sum())
    ratio = lambda a, b: a / b if b else None

    def stats(g):
        n, amount = len(g), int(g['_amount'].sum())
        invoices = int(g.Invoice.nunique())
        return {'rows': n, 'invoices': invoices, 'net': money(amount),
                'absolute': money(g['_amount'].abs().sum()), 'row_share': ratio(n, len(f)),
                'net_share': ratio(amount, net), 'absolute_share': ratio(int(g['_amount'].abs().sum()), absolute),
                'invoice_mean': ratio(amount, scale * invoices),
                'quantity_sign': {k: int(op(g['_q'], 0).sum()) for k, op in [('negative', pd.Series.lt), ('zero', pd.Series.eq), ('positive', pd.Series.gt)]},
                'price_sign': {k: int(op(g['_p'], 0).sum()) for k, op in [('negative', pd.Series.lt), ('zero', pd.Series.eq), ('positive', pd.Series.gt)]}}

    def descriptions(g):
        return [{'value': k, 'rows': int(v)} for k, v in sorted(g.Description.value_counts().items(), key=lambda x: (-x[1], x[0]))]

    def records(g):
        return [{'record': int(r['_record']), **{k: r[k] for k in FIELDS}} for _, r in g.iterrows()]

    prefixes = {k: {**stats(g), 'descriptions': descriptions(g)[:5], 'examples': records(g.head(3))}
                for k, g in f.groupby('_prefix', sort=True)}
    codes = {k: {**stats(g), 'descriptions': descriptions(g)}
             for k, g in f[~f['_ordinary']].groupby('StockCode', sort=True)}
    customers = {}
    for missing, label in [(False, 'present'), (True, 'missing')]:
        g = f[f['_missing'].eq(missing)]
        candidate = g[g['_candidate']]
        products = []
        for code, h in candidate.groupby('StockCode', sort=True):
            products.append({'code': code, 'rows': len(h), 'invoices': int(h.Invoice.nunique()), 'descriptions': descriptions(h)[:3]})
        products.sort(key=lambda x: (-x['invoices'], x['code']))
        customers[label] = {**stats(g), 'candidate_sales': stats(candidate),
            'countries': {k: {'rows': len(h), 'within_group_share': ratio(len(h), len(g)), 'net': money(h['_amount'].sum())}
                          for k, h in g.groupby('Country', sort=True)}, 'top_products': products[:10]}
    return {'rows': len(f), 'price_decimal_places': precision, 'total': stats(f),
            'prefixes': prefixes, 'special_codes': codes, 'special_total': stats(f[~f['_ordinary']]),
            'extremes': records(f[f['_q'].abs().eq(80995)]), 'negative_prices': records(f[f['_p'].lt(0)]),
            'customers': customers,
            'mixed_identity_invoices': int(f.groupby('Invoice')['_missing'].nunique().gt(1).sum()),
            'multiple_known_customer_invoices': int(f[f['Customer ID'].ne('')].groupby('Invoice')['Customer ID'].nunique().gt(1).sum()),
            'counterexamples': {
                'c_nonnegative': {'rows': int((f['_prefix'].eq('C') & f['_q'].ge(0)).sum()), 'examples': records(f[f['_prefix'].eq('C') & f['_q'].ge(0)].head(3))},
                'numeric_invoice_negative': {'rows': int((f.Invoice.str.fullmatch(r'[0-9]+') & f['_q'].lt(0)).sum()), 'examples': records(f[f.Invoice.str.fullmatch(r'[0-9]+') & f['_q'].lt(0)].head(3))},
                'ordinary_stock_nonpositive': {'rows': int((f['_ordinary'] & (f['_q'].le(0) | f['_p'].le(0))).sum()), 'examples': records(f[f['_ordinary'] & (f['_q'].le(0) | f['_p'].le(0))].head(3))}}}


def code_meaning(code, descriptions):
    """依据描述给出有限解释；正则异常本身不是业务分类依据。"""
    known = {'ADJUST': '人工调整；具体会计科目待核对', 'ADJUST2': '人工调整；具体会计科目待核对',
             'AMAZONFEE': 'Amazon 平台费用；不作为商品收入', 'B': '坏账调整；不是负售价商品',
             'BANK CHARGES': '银行手续费；单独核算', 'C2': '运输费（CARRIAGE）；与商品收入分列',
             'CRUK': '描述为 CRUK Commission 的佣金；收付方向待核对', 'D': '折扣；需分配到销售口径，不能简单丢弃',
             'DOT': 'Dotcom 邮费；不能据此认定所有匿名记录渠道', 'M': '手工录入项目；无法仅凭 Manual 判断业务',
             'm': '手工录入项目；大小写差异暂不合并', 'POST': '邮费；与商品收入分列',
             'S': '样品；收费样品与免费样品需分别判断', 'PADS': '描述指向配套垫子，可能是实体商品，需商品主数据确认'}
    if code in known:
        return known[code]
    if code.startswith('gift_'):
        return '礼券系列候选；有礼券描述时支持该解释，空描述仅编码推测；面额不等于应确认收入'
    if code.startswith('TEST'):
        return '测试商品候选；结合描述核对，分析层隔离，原始层保留'
    substantive = [x['value'] for x in descriptions if x['value'] and x['value'] not in ('ebay', 'update')]
    if code.endswith(' '):
        return '尾空格编码，描述指向实体商品；格式异常不等于非商品'
    if substantive:
        return '描述指向实体商品；前缀异常不构成删除依据，待主数据核对'
    return '缺少有效商品描述；业务含义未知，隔离待核对，不能编造含义'


def render(m):
    pct = lambda x: '不适用' if x is None else f'{x:.6%}'
    avg = lambda x: '不适用' if x is None else f'{x:.6f}'
    esc = lambda x: json.dumps(x, ensure_ascii=False).replace('|', '\\|')
    lines = ['# Q1.2 关键发现', '', '本报告自动生成；支持代码为 `q1_findings.py`，完整指标为 `findings_metrics.json`。本轮不删除或修正原始记录。', '',
             f"输入：{m['source']['handle']}；SHA-256：`{m['source']['sha256']}`；{m['rows']:,} 条记录。", '',
             f"金额是 Quantity × Price 的原始带符号合计，单位英镑。精确保留 {m['price_decimal_places']} 位小数，不逐行舍入；总净额 {m['total']['net']}，绝对金额合计 {m['total']['absolute']}。它们不是已审定的商品销售收入。", '',
             '记录序号从表头后的第一条逻辑记录起算为 1；原始空白、大小写及重复记录保留。百分比只在展示时舍入，空分母标为不适用。', '',
             '## 1. 发票前缀及销售口径', '', '| 前缀（空代表纯数字） | 记录数 | 不同发票数 | 数量负/零/正 | 价格负/零/正 | 原始净额 |', '|---|---:|---:|---|---|---:|']
    for key, v in m['prefixes'].items():
        signs = lambda s: '/'.join(str(s[k]) for k in ('negative', 'zero', 'positive'))
        lines.append(f"| {esc(key)} | {v['rows']} | {v['invoices']} | {signs(v['quantity_sign'])} | {signs(v['price_sign'])} | {v['net']} |")
    lines += ['', f'[UCI 官方字段说明]({UCI})将 C 开头的发票定义为取消；官方没有解释 A。实际 A 记录的 B 编码、Adjust bad debt 描述支持“坏账调整”的解释，不是商品销售。官方说明是字段语义参考；本次计算依据冻结的 Kaggle CSV。', '',
              'C 发票应作为取消/贷项类事件保留；是否抵减本期销售，需要与原销售的商品、时间、数量对应，不能把全部 C 都称为实物退货。A 调整单独进入坏账/财务调整视图，不混入商品销量。纯数字发票也不自动等于有效销售。', '',
              '毛销售应统计核实的商品正向销售；净销售再纳入匹配取消、退货和销售折扣。邮费、佣金、银行费、坏账与礼券的处理分别写清，不能一律取绝对值或只留正数。', '', '### 反例实验', '']
    for name, label in [('c_nonnegative', 'C 前缀但数量非负'), ('numeric_invoice_negative', '纯数字发票但数量负'), ('ordinary_stock_nonpositive', '常规编码但数量或单价非正')]:
        v = m['counterexamples'][name]
        lines += [f"- {label}：{v['rows']:,} 条。示例见下方原始记录及 JSON，不据此前缀强行翻转符号。"]
        for r in v['examples']:
            lines.append(f"  - 记录 {r['record']}：`{json.dumps({k:r[k] for k in FIELDS}, ensure_ascii=False)}`")
    lines += ['', '各前缀的高频描述和代表原始记录同时保存在 JSON。取消前缀与数量符号不完全一致，是阻止简单清洗规则上线的直接证据。', '',
              '## 2. 全部特殊格式 StockCode', '',
              f"共 {len(m['special_codes'])} 个编码、{m['special_total']['rows']:,} 条，占行数 {pct(m['special_total']['row_share'])}；原始净额 {m['special_total']['net']}，占总净额 {pct(m['special_total']['net_share'])}；占绝对金额 {pct(m['special_total']['absolute_share'])}。负份额表示净流出/冲减，不能理解成负概率。", '',
              '筛选仅按不符合 `[0-9]+[A-Za-z]*` 的格式进行，**不是已确认非商品清单**。题目把这两者相近表述容易误导：PADS、部分 DCGS、SP1002 以及尾空格编码有实体商品描述；也有空描述无法解释的编码。以下每个编码均列出，描述完整频次见 JSON。', '',
              '| 原始编码 | 行数 | 行占比 | 净额 | 净额占比 | 描述（前两项） | 业务解读与边界 |', '|---|---:|---:|---:|---:|---|---|']
    for code, v in m['special_codes'].items():
        desc = '；'.join(x['value'] or '（空）' for x in v['descriptions'][:2]).replace('|', '\\|')
        lines.append(f"| {esc(code)} | {v['rows']} | {pct(v['row_share'])} | {v['net']} | {pct(v['net_share'])} | {desc} | {code_meaning(code, v['descriptions'])} |")
    lines += ['', '## 3. 极值、负价与保留标准', '']
    for title, rows in [('数量 ±80995 的全部记录', m['extremes']), ('全部负单价记录', m['negative_prices'])]:
        lines += [f'### {title}', '', '| 记录序号 | ' + ' | '.join(FIELDS) + ' |', '|---|' + '---|' * len(FIELDS)]
        for r in rows:
            lines.append('| ' + str(r['record']) + ' | ' + ' | '.join(esc(r[k]) for k in FIELDS) + ' |')
        lines.append('')
    lines += ['两条数量极值具有相同客户、商品、单价，正单后 12 分钟出现取消单；每条绝对金额 168469.600，两条净额为零。这支持“交易被冲销”的解释，但缺少操作日志，不能证明最初是误录还是有效大单后取消，也不能给出已证实的数据错误标签。只删除负单会虚增收入；只删除正单会虚减收入。', '',
              '五条负价记录均为 A 前缀、B 编码、Adjust bad debt、数量 1、客户缺失、英国；更符合坏账调整而非商品负售价。同一描述也存在正价调整，不能简单以描述统一改负号。', '',
              '保留全部原始记录、追踪来源；分析层将财务调整分列，极值成对审核。只有确认重复导入或获得业务更正依据才做可追溯修正；用途不同可有不同过滤视图，不能覆盖原件。', '',
              '## 4. 缺失客户群的比较', '',
              '“客单价”有歧义：匿名客户不可按人数去重。本报告先给每个组原始净额/组内不同发票数（含取消和调整，称发票均额），再给候选销售均额。候选仅取纯数字发票、正数量、正单价、常规编码；该敏感性视图会遗漏部分特殊编码实体商品，不等同最终销售口径。', '',
              f"同一发票混合缺失/非缺失身份：{m['mixed_identity_invoices']} 张；同一发票有多个非空客户 ID：{m['multiple_known_customer_invoices']} 张。若混合，组内发票数不可以直接相加当订单数。", '',
              '| 客户 ID | 行数 | 行占比 | 原始净额 | 净额占比 | 绝对金额占比 | 不同发票 | 原始发票均额 | 候选销售行数 | 候选销售发票数 | 候选销售均额 |', '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for key, label in [('missing','缺失'), ('present','非缺失')]:
        v = m['customers'][key]; c = v['candidate_sales']
        lines.append(f"| {label} | {v['rows']} | {pct(v['row_share'])} | {v['net']} | {pct(v['net_share'])} | {pct(v['absolute_share'])} | {v['invoices']} | {avg(v['invoice_mean'])} | {c['rows']} | {c['invoices']} | {avg(c['invoice_mean'])} |")
    for key, label in [('missing','缺失'), ('present','非缺失')]:
        v = m['customers'][key]
        lines += ['', f'### {label}组：国家分布与高频商品', '', '国家按记录数计算组内占比，完整列出，不把同一客户的多条明细当不同人数。', '', '| 国家 | 记录数 | 组内行占比 | 原始净额 |', '|---|---:|---:|---:|']
        for country, x in sorted(v['countries'].items(), key=lambda pair: (-pair[1]['rows'], pair[0])):
            lines.append(f"| {esc(country)} | {x['rows']} | {pct(x['within_group_share'])} | {x['net']} |")
        lines += ['', '候选销售商品 TOP 10 按不同发票出现次数排序、编码升序打破并列；不直接用件数或原始行数作人气排名，描述只用于辅助辨识。', '', '| 编码 | 发票数 | 行数 | 高频描述 |', '|---|---:|---:|---|']
        for x in v['top_products']:
            lines.append(f"| {esc(x['code'])} | {x['invoices']} | {x['rows']} | {esc(x['descriptions'][0]['value'])} |")
        lines.append('')
    missing, present = m['customers']['missing'], m['customers']['present']
    lines += ['### 反直觉比较', '',
              f"缺失组占明细行 {pct(missing['row_share'])}，却只占原始净额 {pct(missing['net_share'])}。原始发票均额为 {avg(missing['invoice_mean'])}，低于非缺失组的 {avg(present['invoice_mean'])}；但候选销售视图中，分别为 {avg(missing['candidate_sales']['invoice_mean'])} 和 {avg(present['candidate_sales']['invoice_mean'])}，排序反转。说明‘匿名客单更低’对口径不稳健，不能直接形成客户画像。", '',
              f"缺失组候选销售每张发票平均 {missing['candidate_sales']['rows']/missing['candidate_sales']['invoices']:.2f} 条明细，非缺失组为 {present['candidate_sales']['rows']/present['candidate_sales']['invoices']:.2f} 条。前者较高，可提出大购物篮或渠道汇总等假设，但明细数不是唯一商品数、更不是人数；需要订单来源确认。", '',
              f"英国明细的组内占比：缺失组 {pct(missing['countries']['United Kingdom']['within_group_share'])}，非缺失组 {pct(present['countries']['United Kingdom']['within_group_share'])}，缺失明显集中在英国。两组 TOP 10 商品编码重叠 {len({x['code'] for x in missing['top_products']} & {x['code'] for x in present['top_products']})} 个；排名差异只能描述订单组合，不能单凭商品类型认定渠道或消费能力。", '',
              '### 解释边界与下一步', '',
              '缺失客户 ID 的记录可能来自未留客户标识的订单、渠道汇总、系统迁移或人工录入，不能从空 ID 直接推出“游客”“普通散客”或“线下销售”。国家分布反映记录来源，不能证明身份。原始与候选均额之间同时变化了金额和发票分母，不能把差异全部归因于财务调整。进一步的单条件与累积条件消融见 [独立实验报告](../reports/q1_2_sensitivity.md)，候选口径仍有选择偏差。', '',
              f'[UCI 数据说明]({UCI})称该企业为无实体店的线上零售商，且许多客户为批发商。因此不能仅因为匿名就推断线下收银顾客，也不能把全部大额订单判成错误。缺失组与非缺失组的因果差异仍需渠道、订单系统及客户登记流程佐证。', '',
              '下一轮 Q1.3 将依据这些证据分别定义销售报表、RFM、推荐视图，明确排除范围和信息损失；本轮统计通过不代表这些清洗策略已实施。', '']
    return '\n'.join(lines)


def run_findings(input_path, output_dir):
    spec = load_sources()['retail']
    verify_file(Path(input_path), spec['files'][0])
    frame = pd.read_csv(input_path, dtype=str, keep_default_na=False, na_filter=False, skip_blank_lines=False, encoding='utf-8-sig')
    result = analyze(frame)
    result['source'] = {'handle': spec['handle'], 'sha256': spec['files'][0]['sha256']}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'findings_metrics.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    (output_dir / 'findings.md').write_text(render(result), encoding='utf-8')
    return {'rows': result['rows'], 'scope': '仅 Q1.2', 'output_dir': str(output_dir)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT / 'data/online_retail_ii.csv')
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    print(json.dumps(run_findings(args.input, args.output_dir), ensure_ascii=False))
