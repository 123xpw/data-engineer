"""Q2.1：真实 MySQL 反连接；缺失类别与缺失翻译分别披露。"""

import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from q2_sql_analysis.mysql_runtime import connect
from q2_sql_analysis.load_olist import load,require_ready,warnings_fail

SQL=Path(__file__).with_name('q2_1_translation_gap.sql')


def query(output_dir=ROOT/'q2_sql_analysis'):
    with connect() as connection,connection.cursor() as cur:
        version=require_ready(connection)
        cur.execute(SQL.read_text());gaps=[{'category':r[0],'products':r[1]} for r in cur.fetchall()]
        warnings_fail(connection)
        cur.execute("SELECT COUNT(*), SUM(product_category_name IS NULL OR product_category_name='') FROM products")
        total,unknown=cur.fetchone()
        cur.execute('SELECT VERSION()');server=cur.fetchone()[0]
        result={'server_version':server,'load_version':version,'total_products':total,'unknown_category_products':int(unknown),
                'named_translation_gaps':gaps,'named_gap_products':sum(r['products'] for r in gaps),
                'scope':'精确类别名反连接；空类别单列，不猜测补译'}
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    (output_dir/'q2_1_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    lines=['# Q2.1 商品类别翻译缺口','',f"实际数据库：MySQL {server}；导入批次：`{version}`。产品 {total} 个。",'',
           '| 有名但没有有效英文对照的类别 | 商品数 |','|---|---:|']
    lines += [f"| {r['category']} | {r['products']} |" for r in gaps]
    lines += ['',f"另有 {unknown} 个商品的类别为空，不把它命名成一个‘未翻译类别’。有名未译类别共 {len(gaps)} 个，涉及 {result['named_gap_products']} 个商品。",'',
              '题目模块说明预设“3 个类别”，而冻结数据在上述口径下并非三个有名类别。若将空类别聚为一组，会多出一个缺失值组；不能将其与缺少英文映射混称。', '',
              'SQL 使用 NOT EXISTS：只要存在一个非空白英文映射就不算缺口。NULL、空字符串和仅由普通空格组成的英文不视为有效翻译；类别匹配保留大小写和尾空格，使用 utf8mb4_0900_bin。原始暂存值未被覆盖，分析视图将空字符串显式映射为 NULL。', '',
              '## 三种补译方案与利弊','',
              '| 方案 | 好处 | 代价与风险 |','|---|---|---|',
              '| 人工/业务方维护版本化词典 | 可核对专业含义，责任清楚 | 需要审核时间；原始类别缺失仍不能凭空恢复 |',
              '| 机器翻译或 LLM 提议，人工确认后入词典 | 能快速产生候选，减少重复查词 | 可能误译专业词或编造标签；须记录模型、审核人及版本，不直接覆盖原始值 |',
              '| 保留葡语原名或明确未译占位，并单列缺失类别 | 可立即继续分析，保留来源，不伪造英文 | 展示不统一，跨语言聚合需后续治理；占位不能合并不同原类别 |','',
              '本轮只识别缺口与提出治理选项，未实际调用 LLM、未代填译名，也未把题目预设数量当测试答案。','']
    (output_dir/'q2_1_findings.md').write_text('\n'.join(lines))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,default=ROOT/'data')
    parser.add_argument('--output-dir',type=Path,default=Path(__file__).parent)
    parser.add_argument('--skip-load',action='store_true',help='仅查询已经完整发布的本地数据批次')
    args=parser.parse_args()
    try:
        from artifact_manifest import publish
        def action(fresh):
            if not args.skip_load:
                load(args.data_dir, fresh/'load_report.json')
            return query(fresh)
        print(json.dumps(publish('q2.1', args.output_dir, action),ensure_ascii=False))
    except Exception as exc:
        print(f'Q2.1 失败：{type(exc).__name__}',file=sys.stderr)
        raise SystemExit(1)
