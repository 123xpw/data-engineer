"""拒绝缺轮、错误结果或只看中位数掩盖尾部变慢的性能证据。"""
from copy import deepcopy
import unittest
from audit.q2_3_performance import ORDER,summarize

def records():
    values={'baseline':iter([10,11,12]),'candidate':iter([2,3,4])}
    return [{'round':round_no,'query':name,'seconds':next(values[name]),'status':'passed','all_fields_equal':True} for round_no,name in ORDER]

class PerformanceEvidenceCases(unittest.TestCase):
    def test_known_medians_and_ratio(self):
        result=summarize(records())
        self.assertEqual(result['median_seconds'],{'baseline':11,'candidate':3})
        self.assertAlmostEqual(result['baseline_over_candidate'],11/3)

    def test_fast_median_does_not_hide_slow_tail(self):
        rows=records();rows[-1]['seconds']=15
        with self.assertRaisesRegex(AssertionError,'区间重叠'):summarize(rows)

    def test_missing_duplicate_or_wrong_result_is_rejected(self):
        rows=records()
        for bad in (rows[:-1],rows+[rows[-1]],rows[:1]+rows[2:]+rows[1:2]):
            with self.subTest(bad=bad),self.assertRaises(AssertionError):summarize(bad)
        rows[1]['all_fields_equal']=False
        with self.assertRaisesRegex(AssertionError,'全部字段'):summarize(rows)

    def test_nonfinite_or_insufficient_gain_is_rejected(self):
        for value in (float('nan'),float('inf'),0,-1,True):
            rows=records();rows[1]['seconds']=value
            with self.subTest(value=value),self.assertRaises(AssertionError):summarize(rows)
        rows=records()
        for row in rows:
            if row['query']=='candidate':row['seconds']=9.5
        with self.assertRaisesRegex(AssertionError,'20%'):summarize(rows)

if __name__=='__main__':unittest.main()
