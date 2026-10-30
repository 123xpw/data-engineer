"""Q2.3：卖家订单粒度、确定性评价选择及明确分母的卖家分析。"""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from artifact_manifest import publish
from q2_sql_analysis.mysql_runtime import connect
from q2_sql_analysis.load_olist import load,require_ready,warnings_fail
SQL=Path(__file__).with_name('q2_3_top_sellers.sql')
COUNTS={'order_count','unique_customers','state_rank','reviewed_orders','delivered_orders','canceled_orders','valid_delivery_orders','missing_delivery_time_orders','invalid_amount_orders','missing_dimension_orders'}


def execute(connection, sql=None):
    with connection.cursor() as cur:
        cur.execute(sql or SQL.read_text())
        names=[r[0] for r in cur.description]
        rows=[{k:int(v) if k in COUNTS else str(v) if isinstance(v,Decimal) else v for k,v in zip(names,row)} for row in cur.fetchall()]
    warnings_fail(connection)
    return rows


def query(output_dir=ROOT/'q2_sql_analysis'):
    with connect() as c:
        version=require_ready(c);rows=execute(c)
        if len(rows)!=20 or any(r['invalid_amount_orders'] or r['missing_dimension_orders'] for r in rows):
            raise ValueError('卖家数不足或存在金额/维度缺失，拒绝正式发布')
        with c.cursor() as cur:
            cur.execute("SELECT COUNT(*), SUM(o.order_status='canceled') FROM orders o WHERE o.order_purchase_timestamp>='2017-01-01' AND o.order_purchase_timestamp<'2018-01-01' AND NOT EXISTS (SELECT 1 FROM order_items i WHERE i.order_id=o.order_id)")
            missing,canceled=cur.fetchone()
    result={'load_version':version,'year':2017,'rate_unit':'百分数','review_rule':'每订单按创建、回答、review_id、来源行降序取一条；不是权威性认证',
            'unattributed_orders':missing,'unattributed_canceled_orders':int(canceled),'sellers':rows}
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    (output_dir/'q2_3_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    keys=['seller_id','seller_state','gmv_2017','order_count','unique_customers','avg_review_score','late_delivery_rate','cancel_rate','state_rank']
    lines=['# Q2.3 2017 年卖家分析','',
        '月份/年份按下单时间；GMV 只含 delivered 的价格与运费。订单数和取消率以有明细可归属的卖家订单为分母；同订单多件先合并，多卖家订单对每位卖家各计一次。客户按 customer_unique_id。',
        '',f'没有明细的订单 {missing} 张，其中取消 {canceled} 张，无法分配给卖家。本结果不能覆盖这些订单的卖家责任。',
        '', '评价选取规则见 JSON；同一订单多条评价只取一条，平均值按卖家订单等权，缺评价不填零。延迟率仅含 delivered 且实际/预计时间齐全订单；诊断分母见 JSON。所有率单位为百分数。',
        '', '州内 RANK 在全部有 2017 订单的卖家上计算，GMV 同分同名次，随后按平台 GMV 降序、seller_id 升序取恰好 20 名。', '',
        '| '+' | '.join(keys)+' |','|'+'|'.join(['---']*len(keys))+'|']
    lines += ['| '+' | '.join('NULL' if row[k] is None else str(row[k]) for k in keys)+' |' for row in rows]
    lines += ['', '创建/回答时间只是可重现的排序依据；无法据此证明哪条评价代表最终意见，敏感性实验另见验收报告。未实现逐卖家物流归因，多卖家订单共享订单级送达时间与评价。','']
    (output_dir/'q2_3_findings.md').write_text('\n'.join(lines))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,default=ROOT/'data')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'q2_sql_analysis')
    parser.add_argument('--skip-load',action='store_true')
    args=parser.parse_args()
    try:
        def action(fresh):
            if not args.skip_load:
                load(args.data_dir,fresh/'load_report.json')
            return query(fresh)
        print(json.dumps(publish('q2.3',args.output_dir,action),ensure_ascii=False))
    except Exception as exc:
        print(f'Q2.3 失败：{type(exc).__name__}',file=sys.stderr)
        raise SystemExit(1)
