"""固定手算及报告语义回归；合成情景不是实际模型调用。"""
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from q4_llm_extraction import extract_reviews as q

PRICES={'input_usd_per_million':'0.3','output_usd_per_million':'1.2','batch_size':16}
SCENARIO=dict(count=32,batch_size=16,fixed_prompt_tokens=1000,text_tokens=3200,
              single_output_tokens=6400,batch_output_tokens=6400,per_batch_overhead_tokens=20)


def full_metrics():
    return dict(live=True,api_entries_campaign=912,usage_cost_upper_bound_usd='1.7664627',
                budget_occupied_usd='1.7664627',uncertain_cost_requests=0,
                prompt_tokens_campaign=1220873,completion_tokens_campaign=1166834,
                usage_reported_text_rows_campaign=14344,routes={'llm':14294},
                output_rows=22754,unresolved=0,actual_billed_cost_usd=None)


class CostReportTests(unittest.TestCase):
    def test_fixed_token_hand_calculation(self):
        result=q.compare_batch_cost(PRICES,**SCENARIO)
        self.assertEqual(result['single_input_tokens'],35200)
        self.assertEqual(result['batch_input_tokens'],5240)
        self.assertEqual(Decimal(result['single_scenario_usd']),Decimal('0.01824'))
        self.assertEqual(Decimal(result['batch_scenario_usd']),Decimal('0.009252'))
        self.assertEqual(Decimal(result['single_minus_batch_usd']),Decimal('0.008988'))

    def test_repair_can_reverse_saving_and_bad_inputs_are_rejected(self):
        result=q.compare_batch_cost(PRICES,**SCENARIO,batch_repair_usd='0.02')
        self.assertEqual(Decimal(result['batch_scenario_usd']),Decimal('0.029252'))
        self.assertLess(Decimal(result['single_minus_batch_usd']),0)
        for changes in ({'count':True},{'batch_size':0},{'text_tokens':-1},{'batch_repair_usd':'NaN'}):
            args={**SCENARIO,**changes}
            with self.subTest(changes=changes),self.assertRaises(ValueError):q.compare_batch_cost(PRICES,**args)

    def test_denominators_and_non_measured_single_cost_are_explicit(self):
        text=q.render_cost_report(full_metrics(),PRICES)
        for n in (14344,14294,22754):
            self.assertIn(str(Decimal('1.7664627')/n),text)
        for phrase in ('未进行全量单条实测','合成情景','不是实际账单','实际账单费用未核对，为 null','修复费用已包含'):
            self.assertIn(phrase,text)
        self.assertIn('0.01824',text);self.assertIn('0.009252',text)

    def test_partial_or_no_network_does_not_report_full_sample_averages(self):
        for live,unresolved in ((False,14294),(True,2)):
            metrics=full_metrics();metrics.update(live=live,unresolved=unresolved)
            if not live:metrics.update(api_entries_campaign=0,usage_reported_text_rows_campaign=0,usage_cost_upper_bound_usd='0',budget_occupied_usd='0')
            text=q.render_cost_report(metrics,PRICES if live else None)
            self.assertNotIn('| 完整模型来源行 |',text)
            self.assertNotIn('| 全部低分来源行 |',text)
            self.assertIn('不代表全量模型免费',text)

    def test_pipeline_regenerates_report_instead_of_manual_patch(self):
        rows=[dict(source_row=1,review_id='fixture',order_id='fixture',message='Ruim')]
        with tempfile.TemporaryDirectory() as folder,patch.object(q,'read_reviews',return_value=(rows,{'sha256':'fixture'})):
            with patch.object(q,'render_cost_report',return_value='generated-comparison') as render:
                q.run_pipeline('fixture',Path(folder),live=False)
            render.assert_called_once()
            self.assertEqual((Path(folder)/'cost_report.md').read_text(),'generated-comparison')


if __name__=='__main__':unittest.main()
