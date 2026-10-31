"""手算固定夹具，独立于真实业务数据；先验证小样本再扩大。"""
import unittest
from pathlib import Path
import tempfile
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from q3_etl_pipeline.pipeline import normalize,filter_real_sales,compute_rfm,match_returns,validate_output
COLUMNS=['Invoice','StockCode','Description','Quantity','InvoiceDate','Price','Customer ID','Country']

def row(invoice,stock,qty,day,customer='u',price='1.125',country='Z'):
    return [invoice,stock,'人工商品',str(qty),f'2011-01-{day:02d} 10:00:00',price,customer,country]

def frame(rows):return normalize(pd.DataFrame(rows,columns=COLUMNS))


class PipelineTests(unittest.TestCase):
    def price_fixture(self):
        f=frame([row('1','100',1,1),row('2','200',1,1,price='2.000'),
                 row('C1','100',-1,2),row('C2','200',-1,2,price='2.001'),
                 row('C3','300',-1,2),row('C4','100',-1,3,customer=''),
                 row('C5','100',-1,3),row('C6','200',-1,1),row('C7','100',1,3)])
        sales,_=filter_real_sales(f)
        return sales,compute_rfm(sales,'2011-01-03'),match_returns(f,sales)

    def test_price_comparison_three_states_and_parquet_roundtrip(self):
        sales,rfm,out=self.price_fixture();indexed=out.set_index('invoice_no')
        self.assertIsInstance(out['price_mismatch'].dtype,pd.BooleanDtype)
        self.assertFalse(indexed.loc['C1','price_mismatch'])
        self.assertTrue(indexed.loc['C2','price_mismatch'])
        for invoice in ('C3','C4','C5','C6','C7'):
            self.assertTrue(pd.isna(indexed.loc[invoice,'price_mismatch']),invoice)
        validate_output(sales,rfm,out)
        with tempfile.TemporaryDirectory() as temporary:
            p=Path(temporary)/'returns.parquet';out.to_parquet(p,index=False)
            actual=pd.read_parquet(p)
            pd.testing.assert_frame_equal(out,actual)
            column=pq.read_table(p)['price_mismatch']
            self.assertEqual(column.type,pa.bool_());self.assertEqual(column.null_count,5)

    def test_unknown_price_cannot_be_filled_as_equal(self):
        sales,rfm,out=self.price_fixture()
        out['price_mismatch']=out['price_mismatch'].astype('boolean').fillna(False)
        with self.assertRaisesRegex(ValueError,'未知状态'):validate_output(sales,rfm,out)

    def test_known_price_cannot_be_discarded_as_unknown(self):
        sales,rfm,out=self.price_fixture()
        out['price_mismatch']=out['price_mismatch'].astype('boolean')
        out.loc[out['invoice_no']=='C1','price_mismatch']=pd.NA
        with self.assertRaisesRegex(ValueError,'未知状态'):validate_output(sales,rfm,out)

    def test_known_price_comparison_cannot_be_reversed(self):
        for invoice,value in [('C1',True),('C2',False)]:
            with self.subTest(invoice=invoice):
                sales,rfm,out=self.price_fixture();out['price_mismatch']=out['price_mismatch'].astype('boolean')
                out.loc[out['invoice_no']==invoice,'price_mismatch']=value
                with self.assertRaisesRegex(ValueError,'价格差异标记'):validate_output(sales,rfm,out)

    def test_all_unknown_and_empty_returns_keep_nullable_boolean(self):
        for rows in ([row('1','100',1,1),row('C1','300',-1,2)],[row('1','100',1,1)]):
            with self.subTest(rows=rows):
                f=frame(rows);sales,_=filter_real_sales(f);out=match_returns(f,sales)
                self.assertIsInstance(out['price_mismatch'].dtype,pd.BooleanDtype)
                self.assertTrue(out['price_mismatch'].isna().all())
                validate_output(sales,compute_rfm(sales,'2011-01-02'),out)
                with tempfile.TemporaryDirectory() as temporary:
                    p=Path(temporary)/'returns.parquet';out.to_parquet(p,index=False)
                    pd.testing.assert_frame_equal(out,pd.read_parquet(p))

    def test_fixed_sales_rfm_fraction_and_country_tie(self):
        f=frame([row('1','100',2,1),row('1','200',1,1,price='0.001'),row('2','100',1,3,price='2',country='A'),row('3','100',1,4,customer=''),row('C4','100',-1,4)])
        sales,reasons=filter_real_sales(f);r=compute_rfm(sales,'2011-01-04');returns=match_returns(f,sales)
        self.assertEqual(len(sales),4);self.assertEqual(len(r),1)
        item=r.iloc[0];self.assertEqual(item['customer_id'],'u');self.assertEqual(item['frequency'],2)
        self.assertEqual(item['recency_days'],1);self.assertEqual(item['unique_products'],2)
        self.assertAlmostEqual(item['monetary'],4.251,places=12)
        self.assertEqual(item['country'],'A');self.assertFalse(item['is_one_time_buyer'])
        validate_output(sales,r,returns)

    def test_nearest_capacity_no_future_partial_and_anonymous(self):
        rows=[row('1','100',5,1),row('2','100',5,2),row('3','100',5,2),row('4','200',10,1),row('5','300',1,5),
              row('C1','100',-5,3),row('C2','100',-5,4),row('C3','100',-5,5),row('C4','100',-5,6),
              row('C5','200',-5,3),row('C6','300',-1,3),row('C7','100',-5,3,customer=''),row('C8','100',5,3)]
        f=frame(rows);sales,_=filter_real_sales(f);out=match_returns(f,sales).set_index('invoice_no')
        self.assertEqual(out.loc['C1','matched_original_invoice'],'3')
        self.assertEqual(out.loc['C2','matched_original_invoice'],'2')
        self.assertEqual(out.loc['C3','matched_original_invoice'],'1')
        self.assertEqual(out.loc['C1','same_time_candidate_rows'],2)
        for invoice,reason in [('C4','eligible_candidates_consumed'),('C5','no_exact_quantity_candidate'),('C6','no_strictly_earlier_sale'),('C7','missing_customer'),('C8','unexpected_nonnegative_cancel_quantity')]:
            self.assertTrue(pd.isna(out.loc[invoice,'matched_original_invoice']))
            self.assertEqual(out.loc[invoice,'match_reason'],reason)

    def test_equal_time_sale_forbidden_and_special_product_not_blindly_removed(self):
        f=frame([row('1','PADS',1,1,price='0.001'),row('2','POST',1,1),row('3','M',1,1),row('C1','PADS',-1,1,price='0.001')])
        sales,reasons=filter_real_sales(f)
        self.assertEqual(sales['stock_code'].tolist(),['PADS'])
        self.assertEqual(reasons.iloc[1],'nonproduct');self.assertEqual(reasons.iloc[2],'pending_product')
        self.assertEqual(match_returns(f,sales).iloc[0]['match_reason'],'no_strictly_earlier_sale')

    def test_fractional_quantity_is_not_silently_truncated(self):
        values=row('1','100',1,1);values[3]='1.5'
        with self.assertRaisesRegex(ValueError,'数量不是整数'):frame([values])


if __name__=='__main__':unittest.main()
