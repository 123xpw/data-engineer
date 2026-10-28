"""补证实验的手算夹具；所有行均为合成测试数据。"""

import csv
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from scripts.q1_review_experiments import analyze, distribution

FIELDS=['Invoice','StockCode','Description','Quantity','InvoiceDate','Price','Customer ID','Country']
ROWS=[
 ['1','001','a','2','2020-01-01 00:00:00','1','a','UK'],
 ['1','001','a','1','2020-01-01 00:00:00','-1','a','UK'],
 ['2','001','a','0','2020-01-01 00:00:00','0','','UK'],
 ['3','001','a','1','2020-01-01 00:00:00','3','','UK'],
 ['3','001','a','1','2020-01-01 00:00:00','0','','UK'],
 ['3','001','a','1','2020-02-01 00:00:00','1','','FR'],
 ['C4','001','a','-1','2020-01-01 00:00:00','2','','UK'],
 ['5','POST','postage','1','2020-01-01 00:00:00','4','','UK'],
 ['6','001','a','-2','2020-01-01 00:00:00','-1','a','UK'],
]


class ReviewTests(unittest.TestCase):
    def calculate(self, rows=ROWS):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'data.csv';mapping=Path(folder)/'map.csv'
            with path.open('w',newline='') as stream:
                writer=csv.writer(stream);writer.writerow(FIELDS);writer.writerows(rows)
            result=analyze(path,mapping)
            with mapping.open(newline='') as stream:
                records=list(csv.DictReader(stream))
            self.assertEqual([int(x['record']) for x in records],list(range(1,len(rows)+1)))
            return result

    def test_rule_partition_hand_values(self):
        r=self.calculate()
        self.assertEqual(r['total'],{'rows':9,'quantity':'4','net':'9','absolute':'15','invoices':6})
        sums={key:sum(Decimal(x['net']) for x in r['decisions'] if x['decision']==key) for key in ['candidate_keep','pending','exclude_positive_basket']}
        self.assertEqual(sums,{'candidate_keep':6,'pending':5,'exclude_positive_basket':-2})
        self.assertGreater(r['decision_invoice_sum'],r['decision_invoice_union'])

    def test_fixed_denominator_decomposition(self):
        r=self.calculate()['decompositions']
        for g in r.values():
            self.assertEqual(g['raw_mean'],1.5)
            self.assertEqual(g['fixed_denominator_mean'],1)
            self.assertEqual(g['numerator_effect'],-.5)
            self.assertTrue(g['exact_identity_verified'])
        self.assertEqual(r['present']['denominator_effect'],1)
        self.assertEqual(r['missing']['denominator_effect'],3)
        self.assertEqual(r['missing']['selected_mean'],4)
        self.assertEqual(r['missing']['partitions']['disappeared']['invoices'],3)
        self.assertEqual(r['missing']['partitions']['disappeared']['raw_zero'],1)
        self.assertEqual(r['missing']['partitions']['retained_amount_unchanged']['invoices'],1)
        self.assertEqual(r['present']['partitions']['retained_amount_changed']['invoices'],1)

    def test_cross_layers_are_not_new_invoices(self):
        r=self.calculate()
        self.assertEqual(r['cross_layer_invoices'],{'country':1,'month':1})
        self.assertEqual(r['layers']['country']['UK']['missing']['net'],'3')
        self.assertEqual(r['layers']['country']['FR']['missing']['net'],'1')
        self.assertEqual(r['global_candidate_distributions']['missing']['invoices'],1)

    def test_empty_candidate_and_mixed_identity(self):
        rows=[ROWS[2],['2','001','a','1','2020-01-01 00:00:00','0','a','UK']]
        r=self.calculate(rows)
        self.assertEqual(r['mixed_identity_invoices'],1)
        self.assertIsNone(r['decompositions']['missing']['selected_mean'])
        self.assertIsNone(r['decompositions']['present']['denominator_effect'])

    def test_precision_and_quantile(self):
        r=distribution({'a':Decimal('1.005'),'b':Decimal('2.005'),'c':Decimal('9.005')})
        self.assertEqual(r['net'],'12.015')
        self.assertEqual(r['median'],2.005)
        self.assertEqual(r['p90'],7.605)
        self.assertEqual(r['trimmed_mean'],1.505)
        self.assertEqual(r['removed_top_net'],'9.005')

    def test_top_one_percent_ceil_and_empty(self):
        r=distribution({str(i):Decimal(i) for i in range(1,102)})
        self.assertEqual(r['removed_top_count'],2)
        self.assertEqual(r['removed_top_net'],'201')
        self.assertEqual(r['trimmed_mean'],50)
        self.assertIsNone(distribution({'a':Decimal(1)})['trimmed_mean'])
        self.assertIsNone(distribution({})['mean'])


if __name__=='__main__':
    unittest.main()
