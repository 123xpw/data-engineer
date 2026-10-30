"""Q2.2：月度成交查询与口径诊断；金额按十进制字符串输出。"""

import argparse
from decimal import Decimal
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from q2_sql_analysis.mysql_runtime import connect
from q2_sql_analysis.load_olist import load,require_ready,warnings_fail

SQL=Path(__file__).with_name('q2_2_monthly_metrics.sql')
COUNTS={'total_orders','delivered_orders','canceled_orders','valid_delivery_orders','missing_delivery_time_orders',
        'delivered_missing_item_orders','delivered_invalid_amount_orders','negative_delivery_orders'}


def normalize(rows):
    return [{key:int(value) if key in COUNTS else str(value) if isinstance(value,Decimal) else value
             for key,value in row.items()} for row in rows]


def validate_months(rows):
    if not rows:
        raise ValueError('无月度订单，不能当成正式数据查询成功')
    for row in rows:
        if row['month'] is None or any(row[k] for k in ('delivered_missing_item_orders','delivered_invalid_amount_orders','negative_delivery_orders')):
            raise ValueError('存在缺下单时间、未知成交金额或负送达时长，需先解释')


def query(output_dir=ROOT/'q2_sql_analysis'):
    with connect() as c,c.cursor() as cur:
        version=require_ready(c)
        cur.execute(SQL.read_text())
        columns=[x[0] for x in cur.description]
        rows=normalize([dict(zip(columns,row)) for row in cur.fetchall()])
        warnings_fail(c)
        validate_months(rows)
        cur.execute('SELECT VERSION()');server=cur.fetchone()[0]
    result={'server_version':server,'load_version':version,'cancel_rate_unit':'百分数',
            'delivery_days':'有效 delivered 订单等权，秒/86400，六位小数；NULL 排除并披露',
            'months':rows}
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    (output_dir/'q2_2_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    lines=['# Q2.2 月度真实成交分析','',f'数据库 MySQL {server}；批次 `{version}`。',
           '', '订单月份按下单时间；总订单包括所有状态，取消仅指 canceled。取消率以百分数表示。',
           '已送达 GMV 包含明细价格和运费；先按订单聚合，未连接支付或评论表。',
           '平均送达天数按订单等权，使用有效送达时间；不足一天保留，NULL 不填零。', '',
           '| 月份 | 下单 | 送达 | 取消 | 取消率 % | 已送达 GMV | 平均天数 | 有效时长单数 | 缺时长单数 |',
           '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        keys=['month','total_orders','delivered_orders','canceled_orders','cancel_rate','delivered_gmv','avg_delivery_days','valid_delivery_orders','missing_delivery_time_orders']
        lines.append('| '+' | '.join('NULL' if r[k] is None else str(r[k]) for k in keys)+' |')
    lines+=['','缺送达时间的订单仍保留在送达计数和 GMV 中，只退出时长分母。没有 delivered 订单的月份 GMV 为 0、平均时长为 NULL；未造出无下单月份。',
            '所有诊断列见 JSON。缺下单时间、已送达无明细/缺金额、负时长会阻止正式产物发布，不能静默填补。',
            '此结果只按给定状态计算；不代表已审计收入、退款净额、支付结算或完整业务真值。','']
    (output_dir/'q2_2_findings.md').write_text('\n'.join(lines))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,default=ROOT/'data')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'q2_sql_analysis')
    parser.add_argument('--skip-load',action='store_true')
    args=parser.parse_args()
    try:
        from artifact_manifest import publish
        def action(fresh):
            if not args.skip_load:
                load(args.data_dir, fresh/'load_report.json')
            return query(fresh)
        print(json.dumps(publish('q2.2', args.output_dir, action),ensure_ascii=False))
    except Exception as exc:
        print(f'Q2.2 失败：{type(exc).__name__}',file=sys.stderr)
        raise SystemExit(1)
