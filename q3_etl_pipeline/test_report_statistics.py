"""报告统计手算与独立损坏拒绝；不是数据集结论或真人审核。"""
from copy import deepcopy
import unittest
import pandas as pd
import pyarrow as pa
from q3_etl_pipeline import pipeline as q


def sample():
    return pd.DataFrame({'quantity':pd.Series([1,None,3,100],dtype='Int64'),
                         'country':pd.Series(['B','A','B',None],dtype='string')})


class ReportStatisticsTests(unittest.TestCase):
    def test_missing_rates_and_long_tail_linear_quantiles_by_hand(self):
        result=q.summarize_output(sample(),['quantity'])
        self.assertEqual(result['rows'],4)
        self.assertEqual(result['null_counts']['quantity'],1)
        self.assertEqual(result['null_rates']['quantity'],0.25)
        n=result['numeric_distributions']['quantity'];self.assertEqual(n['count'],3)
        self.assertEqual((n['min'],n['p50'],n['max']),(1,3,100))
        self.assertAlmostEqual(n['p95'],90.3,places=12);self.assertAlmostEqual(n['mean'],104/3,places=12)
        self.assertEqual(result['country_distribution'],[{'value':'B','rows':2},{'value':None,'rows':1},{'value':'A','rows':1}])

    def test_empty_output_has_unknown_rate_and_no_distribution(self):
        result=q.summarize_output(sample().iloc[:0],['quantity'])
        self.assertEqual(result['rows'],0);self.assertIsNone(result['null_rates']['quantity'])
        self.assertEqual(result['numeric_distributions']['quantity'],{'count':0,'min':None,'p50':None,'p95':None,'max':None,'mean':None})
        self.assertEqual(result['country_distribution'],[])

    def test_nonfinite_numeric_value_is_not_a_valid_statistic(self):
        f=pd.DataFrame({'quantity':[1,float('inf')],'country':['A','A']})
        with self.assertRaisesRegex(ValueError,'非有限'):q.summarize_output(f,['quantity'])

    def test_independent_parquet_statistics_rejects_targeted_corruption(self):
        from scripts.q3_report_reference import check_frame_statistics
        frame=sample();table=pa.Table.from_pandas(frame,preserve_index=False)
        claim=q.summarize_output(frame,['quantity']);check_frame_statistics(table,claim,['quantity'])
        for field in ('null_rate','quantile','country','missing_distribution'):
            bad=deepcopy(claim)
            if field=='null_rate':bad['null_rates']['quantity']=0.2
            elif field=='quantile':bad['numeric_distributions']['quantity']['p95']=100
            elif field=='country':bad['country_distribution'].pop()
            else:bad['numeric_distributions']={}
            with self.subTest(field=field),self.assertRaises(AssertionError):check_frame_statistics(table,bad,['quantity'])

    def test_report_explains_missing_denominator_and_points_to_full_metrics(self):
        stats=q.summarize_output(sample(),['quantity'])
        report=dict(rows=4,sales_rows=4,customers=4,returns_rows=4,scope='合成夹具',
                    outputs={name:deepcopy(stats) for name in ('sales_facts','customer_features','returns_log')})
        text=q.render_validation_report(report)
        for term in ('空值率','p50','p95','线性插值','validation_metrics.json','毛购买','候选','不是准确率'):
            self.assertIn(term,text)
        self.assertNotIn('```json',text)


if __name__=='__main__':unittest.main()
