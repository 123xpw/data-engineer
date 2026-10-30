"""三用途 ETL：内部整数金额、毛购买特征、容量受限的精确数量退货候选。"""
from bisect import bisect_left
from datetime import datetime,timezone
import argparse
import json
import logging
from pathlib import Path
import sys
import time
import uuid
import shutil
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from download_data import load_sources,verify_file

PRODUCT_EXCEPTIONS={'PADS','SP1002','DCGS0003','DCGS0004','DCGS0037','DCGS0041','DCGS0044','DCGS0058','DCGS0062','DCGS0066N','DCGS0068','DCGS0069','DCGS0070','DCGS0072','DCGS0075','DCGS0076','DCGSSBOY','DCGSSGIRL'}
NON_PRODUCTS={'ADJUST','ADJUST2','AMAZONFEE','B','BANK CHARGES','C2','CRUK','D','DOT','POST'}
FIELDS=['invoice_no','stock_code','description','quantity','unit_price','total_amount','invoice_datetime','customer_id','country','source_row']


def require(condition,message):
    if not condition:raise ValueError(message)


def normalize(raw):
    rename={'Invoice':'invoice_no','StockCode':'stock_code','Description':'description','Quantity':'quantity','InvoiceDate':'invoice_datetime','Price':'unit_price','Customer ID':'customer_id','Country':'country'}
    f=raw.rename(columns=rename).copy()
    require(set(rename.values()).issubset(f.columns),'输入列缺失')
    parts=f['unit_price'].str.extract(r'^(-?)(\d+)(?:\.(\d{1,3}))?$')
    require(parts[1].notna().all(),'金额无法无损转换为千分整数')
    mills=parts[1].astype('int64')*1000+parts[2].fillna('').str.ljust(3,'0').astype('int64')
    f['_price_milli']=mills.where(parts[0]!='-',-mills)
    numeric_quantity=pd.to_numeric(f['quantity'],errors='raise')
    require((numeric_quantity==np.rint(numeric_quantity)).all(),'数量不是整数')
    f['quantity']=numeric_quantity.astype('int64')
    require(int(f['quantity'].abs().max())*int(f['_price_milli'].abs().max())<2**63,'整数金额存在溢出风险')
    f['_amount_milli']=f['quantity']*f['_price_milli']
    f['unit_price']=f['_price_milli']/1000
    f['total_amount']=f['_amount_milli']/1000
    f['invoice_datetime']=pd.to_datetime(f['invoice_datetime'],format='%Y-%m-%d %H:%M:%S',errors='raise')
    for name in ['invoice_no','stock_code','description','customer_id','country']:f[name]=f[name].astype('string')
    f['customer_id']=f['customer_id'].replace('',pd.NA)
    f['source_row']=np.arange(1,len(f)+1,dtype=np.int64)
    return f


def load_data(path):
    spec=load_sources()['retail']['files'][0];verify_file(Path(path),spec)
    return normalize(pd.read_csv(path,dtype=str,keep_default_na=False,na_filter=False,skip_blank_lines=False,encoding='utf-8-sig'))


def filter_real_sales(f):
    code=f['stock_code'].str.strip()
    product=code.str.fullmatch(r'[0-9]+[A-Za-z]*')|code.isin(PRODUCT_EXCEPTIONS)
    known_nonproduct=code.isin(NON_PRODUCTS)|code.str.startswith(('gift_','TEST'))
    reason=np.select([f['invoice_no'].str.startswith('C').to_numpy(dtype=bool),
        (~f['invoice_no'].str.fullmatch(r'[0-9]+')).to_numpy(dtype=bool),
        (f['quantity']<=0).to_numpy(),(f['_price_milli']<=0).to_numpy(),
        known_nonproduct.to_numpy(dtype=bool),(~product).to_numpy(dtype=bool)],
        ['cancel_event','non_numeric_invoice','nonpositive_quantity','nonpositive_price','nonproduct','pending_product'],default='retained')
    selected=f.loc[reason=='retained'].copy()
    return selected,pd.Series(reason,index=f.index,name='reason')


def compute_rfm(sales,reference_day):
    known=sales[sales['customer_id'].notna()]
    r=known.groupby('customer_id',sort=True).agg(first_purchase_date=('invoice_datetime','min'),last_purchase_date=('invoice_datetime','max'),frequency=('invoice_no','nunique'),monetary_milli=('_amount_milli','sum'),unique_products=('stock_code','nunique'))
    r['recency_days']=(pd.Timestamp(reference_day).normalize()-r['last_purchase_date'].dt.normalize()).dt.days
    r['monetary']=r.pop('monetary_milli')/1000
    country=known[['customer_id','invoice_no','country']].drop_duplicates().groupby(['customer_id','country']).size().rename('invoices').reset_index()
    country=country.sort_values(['customer_id','invoices','country'],ascending=[True,False,True]).drop_duplicates('customer_id').set_index('customer_id')['country']
    r=r.join(country);r['is_one_time_buyer']=r['frequency']==1
    return r.reset_index()[['customer_id','recency_days','frequency','monetary','first_purchase_date','last_purchase_date','unique_products','country','is_one_time_buyer']]


def match_returns(f,sales):
    out=f[f['invoice_no'].str.startswith('C')].sort_values(['invoice_datetime','source_row']).copy().reset_index(drop=True)
    candidates=sales[sales['customer_id'].notna()].sort_values(['invoice_datetime','source_row']).reset_index(drop=True)
    groups=candidates.groupby(['customer_id','stock_code','quantity'],sort=False).indices
    times=candidates['invoice_datetime'].to_numpy(dtype='datetime64[ns]').view('i8')
    cache={};chosen=np.full(len(out),-1,dtype=np.int64);reasons=[];ties=np.zeros(len(out),dtype=np.int64)
    # 仅遍历约两万条取消事件，百万行正向数据由 pandas 分组/排序；并查集跳过已消费候选。
    for row_no,row in enumerate(out.itertuples(index=False)):
        if row.quantity>=0:reasons.append('unexpected_nonnegative_cancel_quantity');continue
        if pd.isna(row.customer_id):reasons.append('missing_customer');continue
        key=(row.customer_id,row.stock_code,-row.quantity)
        indexes=groups.get(key)
        if indexes is None:reasons.append('no_exact_quantity_candidate');continue
        if key not in cache:cache[key]=np.arange(len(indexes)+1,dtype=np.int64)
        parent=cache[key]
        def find(position):
            root=position
            while parent[root]!=root:root=int(parent[root])
            while parent[position]!=position:
                previous=int(parent[position]);parent[position]=root;position=previous
            return root
        before=bisect_left(times[indexes],row.invoice_datetime.value)
        if before==0:reasons.append('no_strictly_earlier_sale');continue
        position=find(before)
        if position==0:reasons.append('eligible_candidates_consumed');continue
        selected=int(indexes[position-1]);chosen[row_no]=selected
        ties[row_no]=int(np.sum(times[indexes]==times[selected]))
        parent[position]=find(position-1);reasons.append('candidate_matched')
    valid=chosen>=0
    originals=pd.array([pd.NA]*len(out),dtype='string');source=pd.array([pd.NA]*len(out),dtype='Int64')
    originals[valid]=candidates.iloc[chosen[valid]]['invoice_no'].to_numpy()
    source[valid]=candidates.iloc[chosen[valid]]['source_row'].to_numpy()
    out['matched_original_invoice']=originals;out['matched_source_row']=source
    out['match_reason']=pd.array(reasons,dtype='string');out['same_time_candidate_rows']=ties
    out['price_mismatch']=False
    out.loc[valid,'price_mismatch']=out.loc[valid,'_price_milli'].to_numpy()!=candidates.iloc[chosen[valid]]['_price_milli'].to_numpy()
    return out.sort_values('source_row').reset_index(drop=True)


def validate_output(sales,rfm,returns):
    require((sales['quantity']>0).all() and (sales['unit_price']>0).all(),'销售数量/价格不为正')
    require((sales['total_amount']>0).all(),'销售金额不为正')
    require(np.array_equal(np.rint(sales['total_amount'].to_numpy()*1000).astype('int64'),sales['_amount_milli'].to_numpy()),'导出浮点无法恢复千分整数金额')
    require(not rfm['customer_id'].isna().any() and rfm['customer_id'].is_unique,'客户特征键异常')
    require((rfm['recency_days']>=0).all() and (rfm['frequency']>=1).all(),'RFM 分母/时间异常')
    require(returns['invoice_no'].str.startswith('C').all(),'退货日志混入非 C 事件')
    matched=returns[returns['matched_source_row'].notna()]
    require(matched['matched_source_row'].is_unique,'销售行被重复消费')
    if len(matched):
        right=sales.set_index('source_row').loc[matched['matched_source_row'].astype('int64')]
        require((right['invoice_datetime'].to_numpy()<matched['invoice_datetime'].to_numpy()).all(),'匹配未来或同时间订单')
        require((right['quantity'].to_numpy()==-matched['quantity'].to_numpy()).all(),'匹配数量不相反')
        require((right['stock_code'].to_numpy()==matched['stock_code'].to_numpy()).all(),'匹配商品不同')
        require((right['customer_id'].to_numpy()==matched['customer_id'].to_numpy()).all(),'匹配客户不同')


def run_pipeline(input_path,output_dir):
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    logger=logging.getLogger('gekko.q3');logger.setLevel(logging.INFO)
    handler=logging.FileHandler(output_dir/'pipeline_log.txt',mode='w',encoding='utf-8');logger.addHandler(handler)
    start=time.perf_counter()
    try:
        logger.info('开始读取并核验冻结原始数据');f=load_data(input_path);logger.info('原始记录 %s',len(f))
        sales,reasons=filter_real_sales(f);logger.info('销售规则去向 %s',reasons.value_counts().to_dict())
        returns=match_returns(f,sales);logger.info('退货候选归属 %s',returns['match_reason'].value_counts().to_dict())
        for row in returns[returns['matched_original_invoice'].isna()][['source_row','invoice_no','match_reason']].itertuples(index=False):logger.info('未匹配 来源行=%s 发票=%s 原因=%s',*row)
        rfm=compute_rfm(sales,f['invoice_datetime'].max());validate_output(sales,rfm,returns)
        target=output_dir/'outputs';target.mkdir(exist_ok=True)
        frames={'sales_facts':sales[FIELDS],'customer_features':rfm,'returns_log':returns[FIELDS+['matched_original_invoice','matched_source_row','match_reason','same_time_candidate_rows','price_mismatch']]}
        for name,frame in frames.items():
            frame.to_parquet(target/(name+'.parquet'),index=False,engine='pyarrow')
            pd.testing.assert_frame_equal(frame.reset_index(drop=True),pd.read_parquet(target/(name+'.parquet')).reset_index(drop=True))
            logger.info('%s 写入回读通过，%s 行',name,len(frame))
        matched_ids=returns['matched_source_row'].dropna().astype('int64')
        matched_sales=sales.set_index('source_row').loc[matched_ids]
        remaining=sales[~sales['source_row'].isin(matched_ids)]
        remaining_customers=remaining['customer_id'].dropna().nunique()
        sensitivity={'assumption':'仅作如果全部匹配候选均确认退货的敏感性，不作为已证实退款',
            'candidate_sales_rows':len(matched_sales),'candidate_original_amount_milli':int(matched_sales['_amount_milli'].sum()),
            'customers_with_candidates':int(matched_sales['customer_id'].nunique()),
            'customers_disappearing_if_candidates_removed':len(rfm)-int(remaining_customers),
            'matched_price_mismatch_rows':int(returns['price_mismatch'].sum()),
            'matching_coverage_fraction':len(matched_ids)/len(returns) if len(returns) else None,
            'limit':'覆盖率不是准确率；未匹配不等于无原单，毛购买 RFM 不能当净留存特征'}
        seconds=time.perf_counter()-start
        report={'rows':len(f),'sales_rows':len(sales),'customers':len(rfm),'returns_rows':len(returns),
            'sales_amount_milli':int(sales['_amount_milli'].sum()),'reason_counts':reasons.value_counts().to_dict(),
            'match_reasons':returns['match_reason'].value_counts().to_dict(),'seconds':round(seconds,6),'under_120_seconds':seconds<120,
            'scope':'正向商品毛交易、毛购买 RFM、容量受限精确数量候选；非净退款认证',
            'return_candidate_sensitivity':sensitivity,
            'reference_day':str(f['invoice_datetime'].max().normalize()),'source_sha256':load_sources()['retail']['files'][0]['sha256'],
            'outputs':{name:{'rows':len(frame),'null_counts':frame.isna().sum().to_dict(),'dtypes':frame.dtypes.astype(str).to_dict()} for name,frame in frames.items()}}
        (output_dir/'validation_metrics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        (output_dir/'validation_report.md').write_text('# Q3 ETL 实际统计\n\n```json\n'+json.dumps(report,ensure_ascii=False,indent=2)+'\n```\n\n匹配是候选，部分退货不自动凑单；未知编码隔离，原始文件未删除。金额输出 float、内部整数千分单位；RFM 为毛购买而非净留存。\n')
        require(seconds<120,f'实际耗时 {seconds:.6f} 秒，超过 120 秒门槛')
        logger.info('本轮完成，耗时 %.6f 秒',seconds)
        return report
    except Exception as exc:
        logger.exception('管道失败，未声称通过');handler.flush()
        failure=ROOT/'.venv/q3-failures'/f'{uuid.uuid4().hex}.log'
        failure.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(output_dir/'pipeline_log.txt',failure)
        exc.add_note('失败诊断日志：'+str(failure));raise
    finally:logger.removeHandler(handler);handler.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,default=ROOT/'data/online_retail_ii.csv')
    parser.add_argument('--output-dir',type=Path,default=Path(__file__).parent)
    args=parser.parse_args()
    from artifact_manifest import publish
    print(json.dumps(publish('q3',args.output_dir,lambda fresh:run_pipeline(args.input,fresh),inputs=[args.input]),ensure_ascii=False))
