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
    # 没有候选便没有比较对象；保持未知，不能把“未比较”编码成价格相同。
    out['price_mismatch']=pd.array([pd.NA]*len(out),dtype='boolean')
    out.loc[valid,'price_mismatch']=out.loc[valid,'_price_milli'].to_numpy()!=candidates.iloc[chosen[valid]]['_price_milli'].to_numpy()
    return out.sort_values('source_row').reset_index(drop=True)


def validate_output(sales,rfm,returns):
    require((sales['quantity']>0).all() and (sales['unit_price']>0).all(),'销售数量/价格不为正')
    require((sales['total_amount']>0).all(),'销售金额不为正')
    require(np.array_equal(np.rint(sales['total_amount'].to_numpy()*1000).astype('int64'),sales['_amount_milli'].to_numpy()),'导出浮点无法恢复千分整数金额')
    require(not rfm['customer_id'].isna().any() and rfm['customer_id'].is_unique,'客户特征键异常')
    require((rfm['recency_days']>=0).all() and (rfm['frequency']>=1).all(),'RFM 分母/时间异常')
    require(returns['invoice_no'].str.startswith('C').all(),'退货日志混入非 C 事件')
    require(isinstance(returns['price_mismatch'].dtype,pd.BooleanDtype),'价格比较必须使用可空布尔类型')
    require(returns['price_mismatch'].isna().equals(returns['matched_source_row'].isna()),'价格比较的未知状态必须恰好对应未匹配记录')
    matched=returns[returns['matched_source_row'].notna()]
    require(matched['matched_source_row'].is_unique,'销售行被重复消费')
    if len(matched):
        right=sales.set_index('source_row').loc[matched['matched_source_row'].astype('int64')]
        require((right['invoice_datetime'].to_numpy()<matched['invoice_datetime'].to_numpy()).all(),'匹配未来或同时间订单')
        require((right['quantity'].to_numpy()==-matched['quantity'].to_numpy()).all(),'匹配数量不相反')
        require((right['stock_code'].to_numpy()==matched['stock_code'].to_numpy()).all(),'匹配商品不同')
        require((right['customer_id'].to_numpy()==matched['customer_id'].to_numpy()).all(),'匹配客户不同')
        require(np.array_equal(matched['price_mismatch'].to_numpy(dtype=bool),
            matched['_price_milli'].to_numpy()!=right['_price_milli'].to_numpy()),'价格差异标记与匹配双方原始价格不符')


def summarize_output(frame,numeric_columns):
    """按输出自己的行粒度统计，空分母保留未知，不改业务数据。"""
    rows=len(frame);nulls={key:int(value) for key,value in frame.isna().sum().items()}
    distributions={}
    for name in numeric_columns:
        valid=frame[name].dropna()
        require(np.isfinite(valid.to_numpy(dtype=float)).all(),'报告数值列含非有限值：'+name)
        values={'count':len(valid),'min':None,'p50':None,'p95':None,'max':None,'mean':None}
        if len(valid):
            values.update(min=float(valid.min()),p50=float(valid.quantile(.5,interpolation='linear')),
                          p95=float(valid.quantile(.95,interpolation='linear')),max=float(valid.max()),mean=float(valid.mean()))
            require(all(np.isfinite(v) for k,v in values.items() if k!='count'),'报告统计溢出或非有限：'+name)
        distributions[name]=values
    countries=[{'value':None if pd.isna(value) else str(value),'rows':int(count)}
               for value,count in frame['country'].value_counts(dropna=False).items()]
    countries.sort(key=lambda item:(-item['rows'],item['value'] is not None,item['value'] or ''))
    return {'rows':rows,'null_counts':nulls,'null_rates':{key:value/rows if rows else None for key,value in nulls.items()},
            'dtypes':frame.dtypes.astype(str).to_dict(),'numeric_distributions':distributions,'country_distribution':countries}


def render_validation_report(report):
    """面向验收者解释统计的用途；完整指标另存JSON，避免只贴大对象。"""
    parts=['# Q3 ETL 数据校验与统计解释\n\n',
        '## 我是怎样确定统计口径的\n\n',
        '我把销售、客户和取消记录分开统计，因为三张表的行粒度不同。销售和取消是一条来源明细，客户表则是一位有标识的客户。若把它们使用同一个分母，空值率和国家占比会失去含义；因此下面的空值率一律是该输出字段的空值数量除以该输出实际行数，而不是原始文件总行数。空输出没有可解释的比例，写null而不是0%，也不能把空表说成质量完美。\n\n',
        '我同时展示均值、中位数和高分位数，而不只给均值。少量大数量或高金额明细可能拉高均值，p50与p95能帮助判断长尾；极端值仍保留并单列核查，不因为超出分位数就删掉。分位数按排序位置(n-1)*q做线性插值，所以它可能不是某条原始记录的值，也不是实际成交价格。有效数排除真正的NULL，但不会把零、负数、空字符串或未知编码随意补成别的值。\n\n',
        '销售表按正向商品毛交易解释，不能仅因金额都非负就称为净收入。取消表保留原始符号，负数量和负金额可能正是需要观察的事件，不能直接套销售表的非负规则。商品属性或退款是否最终完成仍需业务主数据核对，分布只描述程序产物，不能认证这些业务事实。金额沿用原数据单位，不推断或换算币种；内部千分整数与导出float的取舍不因报告统计而改变。\n\n',
        '客户RFM使用有标识的毛购买记录，frequency是独立发票数，monetary是该客户的毛购买总额；它们与销售明细的数量或单行金额不能直接比较。客户主要国家已经按明确规则选取，因此这里国家分布是客户数，而销售与取消的国家分布是明细数。这也是为什么国家占比变化不能立即解释为市场份额或真实活跃人群变化。\n\n',
        '取消匹配仍只是候选。price_mismatch为NULL表示没有比较对象，不能当作价格相同，也不应为了降低空值率而填False。只有已比较行可用于解释价差比例；匹配覆盖率不是准确率。未匹配也可能来自原始销售范围、缺身份、精确数量规则或候选已被消费，而不是已经证明没有原单。\n\n',
        '所有逐列空值数量、比例、类型以及完整数值和国家分布保存在validation_metrics.json，便于机器复算；本页只列关键数值及国家TOP5，其余合计保留，不把未展示的国家当作不存在。并列按NULL在先、原字符串升序确定，重跑不依赖原始出现顺序。表内数值作展示舍入，JSON保留float值。浮点统计的独立核验有明确容差，计数与分母则精确比较；这些检查不是本人或另一位人员已经完成语义审核的声明。\n\n',
        '## 三份输出的实际统计\n\n',
        f"原始来源记录 {report['rows']}；销售明细 {report['sales_rows']}；客户 {report['customers']}；取消明细 {report['returns_rows']}。完整指标见 [validation_metrics.json](validation_metrics.json)。\n\n"]
    def show(value):return 'null' if value is None else format(value,'.8g')
    for name,summary in report['outputs'].items():
        parts.append(f"### {name}\n\n实际行数：{summary['rows']}。\n\n")
        if not summary['rows']:parts.append('空输出：各列空值率为null，不报告0%。\n\n')
        else:
            missing=[f"`{key}` {count}（{summary['null_rates'][key]:.6%}）" for key,count in summary['null_counts'].items() if count]
            parts.append('空值数量/空值率：'+('；'.join(missing)+'；其余字段为0。' if missing else '所有字段均为0。')+'\n\n')
        parts.append('| 数值列 | 有效数 | min | p50 | p95 | max | mean |\n|---|---:|---:|---:|---:|---:|---:|\n')
        for key,stats in summary['numeric_distributions'].items():
            parts.append('| '+key+' | '+' | '.join(show(stats[k]) for k in ('count','min','p50','p95','max','mean'))+' |\n')
        parts.append('\n国家分布（按本表行数，TOP5）：\n\n| 原国家值 | 行数 |\n|---|---:|\n')
        countries=summary['country_distribution']
        for item in countries[:5]:parts.append(f"| {str(item['value']).replace('|',' / ') if item['value'] is not None else 'NULL（缺失）'} | {item['rows']} |\n")
        parts.append(f"| 其余国家合计 | {sum(item['rows'] for item in countries[5:])} |\n\n")
    parts.append('## 如何复核及当前边界\n\n逐列比例和分布应从实际Parquet复算，不能只信本报告或文件存在。确定性、金额/客户/候选的独立CSV参考与报告统计是不同检查；三份Parquet和本机两分钟要求另有真实回执。原始记录不因本报告被删除或修改，毛购买RFM和候选退款也不因报告完整就成为业务真值。\n')
    return ''.join(parts)


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
        compared=returns['price_mismatch'].dropna()
        price_counts={'unknown':len(returns)-len(compared),'same':int((~compared).sum()),'different':int(compared.sum())}
        sensitivity={'assumption':'仅作如果全部匹配候选均确认退货的敏感性，不作为已证实退款',
            'candidate_sales_rows':len(matched_sales),'candidate_original_amount_milli':int(matched_sales['_amount_milli'].sum()),
            'customers_with_candidates':int(matched_sales['customer_id'].nunique()),
            'customers_disappearing_if_candidates_removed':len(rfm)-int(remaining_customers),
            'matched_price_mismatch_rows':price_counts['different'],
            'matching_coverage_fraction':len(matched_ids)/len(returns) if len(returns) else None,
            'limit':'覆盖率不是准确率；未匹配不等于无原单，毛购买 RFM 不能当净留存特征'}
        seconds=time.perf_counter()-start
        report={'rows':len(f),'sales_rows':len(sales),'customers':len(rfm),'returns_rows':len(returns),
            'sales_amount_milli':int(sales['_amount_milli'].sum()),'reason_counts':reasons.value_counts().to_dict(),
            'match_reasons':returns['match_reason'].value_counts().to_dict(),'seconds':round(seconds,6),'under_120_seconds':seconds<120,
            'scope':'正向商品毛交易、毛购买 RFM、容量受限精确数量候选；非净退款认证',
            'return_candidate_sensitivity':sensitivity,
            'price_comparison_counts':price_counts,
            'reference_day':str(f['invoice_datetime'].max().normalize()),'source_sha256':load_sources()['retail']['files'][0]['sha256'],
            'statistics_policy':{'null_rate_denominator':'each_output_rows','empty_rate':None,'quantile_interpolation':'linear'},
            'outputs':{name:summarize_output(frame,['recency_days','frequency','monetary','unique_products'] if name=='customer_features' else ['quantity','unit_price','total_amount']) for name,frame in frames.items()}}
        (output_dir/'validation_report.md').write_text(render_validation_report(report))
        report['seconds']=round(time.perf_counter()-start,6)
        report['under_120_seconds']=report['seconds']<120
        (output_dir/'validation_metrics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
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
