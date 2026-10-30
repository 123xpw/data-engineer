"""Q2.4 业务修正版：保留原题筛选、订单等权评分与价格诊断。"""
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
SQL=Path(__file__).with_name('q2_4_corrected.sql')
DOCUMENT=Path(__file__).with_name('q2_4_query_optimization.md')
COUNTS={'orders','reviewed_orders','missing_item_orders','invalid_price_items'}


def query(output_dir=ROOT/'q2_sql_analysis'):
    with connect() as c,c.cursor() as cur:
        version=require_ready(c);cur.execute(SQL.read_text())
        columns=[r[0] for r in cur.description]
        rows=[{k:int(v) if k in COUNTS else str(v) if isinstance(v,Decimal) else v for k,v in zip(columns,row)} for row in cur.fetchall()]
        warnings_fail(c)
    if not rows or any(r['missing_item_orders'] or r['invalid_price_items'] for r in rows):
        raise ValueError('存在未知价格或缺商品明细，拒绝当完整收入发布')
    result={'load_version':version,'scope':'原题筛选；商品价格不含运费/退款，评分每订单最新一条等权；不是净收入审计',
            'states':rows}
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    (output_dir/'q2_4_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    if (output_dir/DOCUMENT.name).resolve()!=DOCUMENT.resolve():
        (output_dir/DOCUMENT.name).write_text(DOCUMENT.read_text())
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,default=ROOT/'data')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'q2_sql_analysis')
    parser.add_argument('--skip-load',action='store_true')
    args=parser.parse_args()
    try:
        def action(fresh):
            if not args.skip_load:load(args.data_dir,fresh/'load_report.json')
            return query(fresh)
        print(json.dumps(publish('q2.4',args.output_dir,action),ensure_ascii=False))
    except Exception as exc:
        print(f'Q2.4 失败：{type(exc).__name__}',file=sys.stderr)
        raise SystemExit(1)
