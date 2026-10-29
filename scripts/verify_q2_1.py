"""MySQL 九表独立往返、粒度/关系、故障边界及翻译查询验收。"""

from collections import Counter
import csv
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import pandas as pd
import pymysql

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from q2_sql_analysis.mysql_runtime import connect,ensure_mysql
from q2_sql_analysis.catalog import tables,KEYS,MONEY
from q2_sql_analysis.load_olist import load,require_ready,validate_value
from q2_sql_analysis.q2_1 import query
from check_q2_1_cases import check_cases
from check_q2_typed_values import expected_values,assert_record,check_blindspot
from verification_support import EvidenceRun,sha256


def verify_roundtrip():
    result={};frames={}
    with connect() as c:
        version=require_ready(c)
        for name,spec in tables().items():
            path=ROOT/'data'/spec['target'];assert sha256(path)==spec['sha256']
            chunks=[];rows=0
            with c.cursor(pymysql.cursors.SSCursor) as cur:
                cur.execute(f'SELECT * FROM `raw_{name}` ORDER BY _source_row')
                # 独立 pandas C 解析，逐字段比较；不调用导入器的 CSV/摘要函数。
                for frame in pd.read_csv(path,dtype=str,keep_default_na=False,na_filter=False,skip_blank_lines=False,encoding='utf-8-sig',chunksize=25000):
                    assert list(frame.columns)==spec['columns']
                    for original in frame.itertuples(index=False,name=None):
                        rows+=1;actual=cur.fetchone()
                        assert actual==(rows,*original),f'{name} 记录 {rows} 往返不符'
                    chunks.append(frame)
                assert cur.fetchone() is None,f'{name} 数据库多行'
            assert rows==spec['rows']
            frame=pd.concat(chunks,ignore_index=True);frames[name]=frame
            # 原始值对齐不够：分析视图转换后的每个值也须留在正确来源行。
            with c.cursor(pymysql.cursors.SSCursor) as cur:
                cur.execute(f'SELECT * FROM `{name}` ORDER BY _source_row')
                for source_row,values in enumerate(frame.itertuples(index=False,name=None),1):
                    expected=(source_row,*expected_values(name,spec['columns'],values))
                    assert_record(cur.fetchone(),expected,f'{name} 来源记录 {source_row}')
                assert cur.fetchone() is None,f'{name} 分析视图多行'
            with c.cursor() as cur:
                cur.execute(f'SELECT COUNT(*) FROM `{name}`');assert cur.fetchone()[0]==rows
                cols=spec['columns']
                cur.execute('SELECT '+','.join(f'SUM(`{col}` IS NULL)' for col in cols)+f' FROM `{name}`')
                nulls=[int(x or 0) for x in cur.fetchone()]
                assert nulls==[int(frame[col].eq('').sum()) for col in cols],f'{name} 空值转换不符'
                monetary={}
                for col in set(cols)&MONEY:
                    expected=sum((Decimal(v) for v in frame[col] if v!=''),Decimal(0))
                    cur.execute(f'SELECT SUM(`{col}`) FROM `{name}`');actual=cur.fetchone()[0]
                    assert actual==expected,f'{name}.{col} 金额不符'
                    monetary[col]=str(actual)
                keys=KEYS[name]
                duplicates=None
                if keys:
                    expected=int(frame.duplicated(subset=keys).sum())
                    group=', '.join(f'`{col}`' for col in keys)
                    cur.execute(f'SELECT COALESCE(SUM(n-1),0) FROM (SELECT COUNT(*) n FROM `{name}` GROUP BY {group}) x')
                    duplicates=int(cur.fetchone()[0]);assert duplicates==expected
            result[name]={'rows':rows,'all_cells_equal':True,'all_typed_values_equal_by_source_row':True,'null_counts':dict(zip(cols,nulls)),
                              'amount_totals':monetary,'candidate_key':keys,'extra_rows_on_candidate_key':duplicates}
        with c.cursor() as cur:
            for table,column in [('order_reviews','review_id'),('order_reviews','order_id'),('geolocation','geolocation_zip_code_prefix')]:
                cur.execute(f'SELECT COUNT(*)-COUNT(DISTINCT `{column}`) FROM `{table}`')
                count=int(cur.fetchone()[0]);assert count==int(frames[table][column].duplicated().sum())
                result[table][f'extra_rows_by_{column}']=count
            relationships={}
            for child,key,parent,parent_key in [('orders','customer_id','customers','customer_id'),('order_items','order_id','orders','order_id'),
                  ('order_items','product_id','products','product_id'),('order_items','seller_id','sellers','seller_id'),
                  ('order_payments','order_id','orders','order_id'),('order_reviews','order_id','orders','order_id')]:
                expected=int((~frames[child][key].isin(set(frames[parent][parent_key]))).sum())
                cur.execute(f'SELECT COUNT(*) FROM `{child}` c WHERE NOT EXISTS (SELECT 1 FROM `{parent}` p WHERE p.`{parent_key}`=c.`{key}`)')
                actual=int(cur.fetchone()[0]);assert actual==expected
                relationships[f'{child}.{key}->{parent}.{parent_key}']=actual
    return {'load_version':version,'tables':result,'orphan_child_rows':relationships,
            'limitation':'逐字段相等证明导入保存了原值，不证明原值的业务真实性；无业务键表仍保留来源行键'}


def real_query():
    actual=query()
    with (ROOT/'data/olist/olist_products_dataset.csv').open(newline='',encoding='utf-8-sig') as stream:
        categories=Counter(row['product_category_name'] for row in csv.DictReader(stream))
    with (ROOT/'data/olist/product_category_name_translation.csv').open(newline='',encoding='utf-8-sig') as stream:
        translated={row['product_category_name'] for row in csv.DictReader(stream) if row['product_category_name_english'].strip(' ')}
    expected=[{'category':key,'products':count} for key,count in sorted(categories.items()) if key!='' and key not in translated]
    assert actual['named_translation_gaps']==expected
    assert actual['unknown_category_products']==categories['']
    assert actual['total_products']==sum(categories.values())
    return {'query_result':actual,'reference':'标准库 CSV/Counter/集合，未调用生产查询生成预期','hardcoded_expected_categories':False}


def failures():
    with connect() as c,c.cursor() as cur:
        before=require_ready(c)
        cur.execute('SELECT COUNT(*) FROM products');count=cur.fetchone()[0]
    with tempfile.TemporaryDirectory() as empty:
        try:
            load(Path(empty),Path(empty)/'report.json')
        except FileNotFoundError:
            pass
        else:
            raise AssertionError('缺输入仍宣称导入成功')
    with connect() as c,c.cursor() as cur:
        assert require_ready(c)==before
        cur.execute('SELECT COUNT(*) FROM products');assert cur.fetchone()[0]==count
        cur.execute('CREATE TEMPORARY TABLE strict_probe (id INT PRIMARY KEY, label VARCHAR(4))')
        try:
            cur.execute('INSERT INTO strict_probe VALUES (1,%s)',('ABCDE',))
        except pymysql.DataError:
            pass
        else:
            raise AssertionError('超长字段被静默截断')
        cur.execute('INSERT INTO strict_probe VALUES (1,%s)',('ok',))
        try:
            cur.execute('INSERT INTO strict_probe VALUES (1,%s)',('new',))
        except pymysql.IntegrityError:
            pass
        else:
            raise AssertionError('重复主键被忽略或覆盖')
        # 只在当前未提交事务中模拟未就绪，回滚后不影响正式状态。
        cur.execute("UPDATE _load_state SET state='publishing' WHERE singleton=1")
        try:
            require_ready(c)
        except RuntimeError:
            pass
        else:
            raise AssertionError('未完整发布仍可通过查询守卫')
        c.rollback();assert require_ready(c)==before
    for column,value in [('price','1.0001'),('order_item_id','1.5'),('order_purchase_timestamp','bad'),('price','NaN')]:
        try:
            validate_value(column,value)
        except (ValueError,ArithmeticError):
            pass
        else:
            raise AssertionError(f'{column} 非法或有损转换被接受')
    return {'missing_input_keeps_old_version':True,'sql_truncation_rejected':True,'duplicate_pk_rejected':True,
            'unready_query_rejected':True,'lossy_cast_rejected':True,
            'limitation':'未模拟进程强杀、机器断电或并发读写；不能据此宣称所有恢复场景均已验证'}


def main():
    with EvidenceRun(ROOT/'reports/q2_1','acceptance') as e:
        if not e.check('真实 MySQL 环境',ensure_mysql):
            return 1
        with connect() as c:
            try:
                before=require_ready(c)
            except pymysql.Error:
                before=None
        if not e.check('九表重新导入并整批发布',load):
            return 1
        def roundtrip():
            result=verify_roundtrip()
            assert result['load_version']!=before,'重跑未生成新批次'
            return result
        e.check('独立全字段往返、类型缺失、金额、键与关系',roundtrip)
        e.check('真实 MySQL 手算 SQL 反例',check_cases)
        e.check('保留汇总数的日期偏移和金额错配实验',check_blindspot)
        e.check('真实 Q2.1 结果独立复算',real_query)
        e.check('失败守卫与无损边界',failures)
        def entrypoints():
            with tempfile.TemporaryDirectory(prefix='gekko-q21-entry-') as folder:
                tmp=Path(folder)
                cmd=[sys.executable,str(ROOT/'run_all.py'),'--stage','q2.1','--q2-output-dir',str(tmp/'output'),'--report',str(tmp/'run.json')]
                completed=subprocess.run(cmd,cwd=tmp,capture_output=True,text=True,timeout=360)
                assert completed.returncode==0, f'Q2.1 总入口退出码 {completed.returncode}'
                report=json.loads((tmp/'run.json').read_text())
                assert report['results'][0]['status']=='passed'
                actual=json.loads((tmp/'output/q2_1_results.json').read_text())
                original=json.loads((ROOT/'q2_sql_analysis/q2_1_results.json').read_text())
                assert {k:v for k,v in actual.items() if k!='load_version'}=={k:v for k,v in original.items() if k!='load_version'}
                failed=subprocess.run(cmd+['--data-dir',str(tmp/'missing')],cwd=tmp,capture_output=True,text=True,timeout=60)
                assert failed.returncode==1
                report=json.loads((tmp/'run.json').read_text())
                stages=report['results'][0]['detail']['results']
                assert [(x['stage'],x['status']) for x in stages]==[('q2.load','failed'),('q2.1','blocked_dependency')]
                return {'outside_cwd':True,'business_output_equal':True,'load_version_differs_by_design':True,
                        'failed_load_does_not_query_old_data':True}
        e.check('Q2.1 总入口及依赖失败隔离',entrypoints)
        def regression_and_environment():
            env=json.loads((ROOT/'reports/hardening/clean_environment_latest.json').read_text())
            assert env['status']=='passed' and env['source_sha256']['requirements.txt']==sha256(ROOT/'requirements.txt')
            run=subprocess.run([sys.executable,str(ROOT/'scripts/verify_q1_3.py')],cwd=ROOT,capture_output=True,text=True,timeout=600)
            assert run.returncode==0,run.stdout[-1500:]
            report=json.loads((ROOT/'reports/q1_3/acceptance_latest.json').read_text())
            assert report['status']=='passed' and report['source_sha256']==e.report['source_sha256']
            return {'clean_python_run':env['run_id'],'q1_regression_run':report['run_id'],
                    'environment_scope':'全新 Python/源码/数据缓存安装与下载；复用本机项目 MySQL 实例重新导入，不是全新服务器'}
        e.check('新依赖干净环境及全部既有计算回归',regression_and_environment)
        e.report['business_scope']='仅无损暂存与 Q2.1 明示语义，不认证全部原始数据或后续分析'
        e.report['artifact_sha256']={name:sha256(ROOT/name) for name in ['q2_sql_analysis/q2_1_results.json','q2_sql_analysis/q2_1_findings.md']}
        e.save()
    print(e.path)
    return 0 if e.report['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
