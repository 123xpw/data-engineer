"""人工设计的业务反例；样本不是真实业务数据，不用于报告结论。"""

import csv
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

import pandas as pd
from q1_data_quality.q1_findings import analyze, FIELDS, code_meaning
from scripts.q1_findings_reference import reference, compare


# 手算：2.010+2-2.010+3-4+1=2.000；绝对金额 14.020；缺失组净额 -1，行数 3/6。
ROWS = [
    ['001','001','apple','2','2020-01-01 00:00:00','1.005','c1','UK'],
    ['001','001','apple','1','2020-01-01 00:00:00','2','','UK'],
    ['C002','001','apple','-2','2020-01-02 00:00:00','1.005','c1','UK'],
    ['C003','DCGS1','DOG COLLAR','1','2020-01-02 00:00:00','3','c2','FR'],
    ['A004','B','Adjust bad debt','1','2020-01-02 00:00:00','-4','','UK'],
    ['005','POST','postage','-1','2020-01-02 00:00:00','-1','','FR'],
]


class FindingsTests(unittest.TestCase):
    def analyze(self, rows=ROWS):
        return analyze(pd.DataFrame(rows, columns=FIELDS))

    def test_manual_money_and_missing(self):
        m = self.analyze()
        self.assertEqual(m['total']['net'], '2.000')
        self.assertEqual(m['total']['absolute'], '14.020')
        self.assertEqual(m['price_decimal_places'], 3)
        self.assertEqual(m['customers']['missing']['net'], '-1.000')
        self.assertEqual(m['customers']['missing']['row_share'], .5)
        self.assertEqual(m['customers']['missing']['net_share'], -.5)
        self.assertEqual(m['customers']['missing']['invoices'],3)
        self.assertAlmostEqual(m['customers']['missing']['invoice_mean'], -1/3)
        self.assertEqual(m['mixed_identity_invoices'],1)
        self.assertEqual(m['special_total']['net'],'0.000')

    def test_prefix_is_not_quantity_sign(self):
        m = self.analyze()
        self.assertEqual(m['prefixes']['C']['rows'],2)
        self.assertEqual(m['prefixes']['C']['quantity_sign']['positive'],1)
        self.assertEqual(m['counterexamples']['numeric_invoice_negative']['rows'],1)
        self.assertEqual(m['prefixes']['A']['net'],'-4.000')

    def test_candidate_order_not_line_average(self):
        m = self.analyze(ROWS + [ROWS[0]])
        c = m['customers']['present']['candidate_sales']
        self.assertEqual(c['rows'],2)
        self.assertEqual(c['invoices'],1)
        self.assertEqual(c['net'],'4.020')
        self.assertEqual(c['invoice_mean'],4.02)
        top = m['customers']['present']['top_products'][0]
        self.assertEqual((top['code'],top['rows'],top['invoices']),('001',2,1))

    def test_zero_denominator_and_abs(self):
        m = self.analyze([ROWS[0], ROWS[2]])
        self.assertEqual(m['total']['net'],'0.000')
        self.assertIsNone(m['total']['net_share'])
        self.assertEqual(m['total']['absolute'],'4.020')
        self.assertIsNone(m['customers']['missing']['invoice_mean'])
        self.assertEqual(m['customers']['missing']['countries'],{})

    def test_no_stripping_identifiers_or_null(self):
        rows = [ROWS[0], ['7','47503J ','TOOLS','1','2020-01-01 00:00:00','0','NULL','NA']]
        m = self.analyze(rows)
        self.assertIn('47503J ',m['special_codes'])
        self.assertEqual(m['customers']['missing']['rows'],0)
        self.assertIn('NA',m['customers']['present']['countries'])
        self.assertIn('实体商品',code_meaning('47503J ', [{'value':'TOOLS','rows':1}]))
        self.assertIn('未知',code_meaning('C3',[{'value':'','rows':1}]))

    def test_ranking_by_invoices_not_lines(self):
        row = lambda invoice,stock: [invoice,stock,stock,'1','2020-01-01 00:00:00','1','c','UK']
        m = self.analyze([row('1','2')]*5+[row('2','1'),row('3','1'),row('4','3'),row('5','3')])
        self.assertEqual([x['code'] for x in m['customers']['present']['top_products']],['1','3','2'])

    def test_permutation_invariance(self):
        a,b = self.analyze(),self.analyze(list(reversed(ROWS)))
        for m in (a,b):
            for v in m['prefixes'].values():
                v.pop('examples')
            for v in m['counterexamples'].values():
                v.pop('examples')
            m.pop('negative_prices')
        self.assertEqual(a,b)

    def test_cancelling_pair_metamorphic(self):
        a = self.analyze()
        positive = ['999','001','apple','7','2020-01-03 00:00:00','1.125','c1','UK']
        negative = ['C999','001','apple','-7','2020-01-03 00:00:00','1.125','c1','UK']
        b = self.analyze(ROWS+[positive,negative])
        self.assertEqual(a['total']['net'],b['total']['net'])
        self.assertEqual(Decimal(b['total']['absolute'])-Decimal(a['total']['absolute']),Decimal('15.750'))
        self.assertEqual(b['rows'],a['rows']+2)

    def test_independent_reference_on_hand_fixture(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'fixture.csv'
            with path.open('w',newline='') as stream:
                writer=csv.writer(stream); writer.writerow(FIELDS); writer.writerows(ROWS)
            ref=reference(path)
            self.assertEqual(ref['total']['net'],'2.000')
            self.assertEqual(ref['total']['absolute'],'14.020')
            compare(ref,self.analyze())

    def test_missing_prefix_and_multiple_customer(self):
        rows = [ROWS[0], ['001','001','apple','1','2020-01-01 00:00:00','1','c2','UK'],
                ['12X','001','apple','1','2020-01-01 00:00:00','1','c3','UK']]
        m=self.analyze(rows)
        self.assertEqual(m['multiple_known_customer_invoices'],1)
        self.assertIn('<无前导前缀的异常格式>', m['prefixes'])


if __name__ == '__main__':
    unittest.main()
