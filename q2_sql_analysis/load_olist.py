"""九表无损暂存、显式分析视图及整批发布；不去重、不猜补缺失值。"""

import argparse
import csv
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import uuid

import pymysql

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from download_data import verify_file
from q2_sql_analysis.catalog import tables,expression,INTEGER,MONEY,GEO,DATES
from q2_sql_analysis.mysql_runtime import ensure_mysql,connect


def row_bytes(row):
    return (json.dumps(list(row),ensure_ascii=False,separators=(',',':'))+'\n').encode()


def validate_value(column,value):
    if len(value)>512:
        raise ValueError(f'{column} 超过暂存列长度，不能截断')
    if value=='':
        return
    if column in INTEGER|MONEY|GEO:
        n=Decimal(value)
        if not n.is_finite():
            raise ValueError('非有限数值不能进入分析视图')
        if column in INTEGER and (n!=n.to_integral_value() or abs(n)>=2**63):
            raise ValueError('整数列不能舍入或溢出')
        if column in MONEY and (abs(n)>=Decimal('1e17') or n!=n.quantize(Decimal('.001'))):
            raise ValueError('金额不能在 DECIMAL 转换中舍入或溢出')
        if column in GEO and (abs(n)>=Decimal('1e10') or n!=n.quantize(Decimal('1e-20'))):
            raise ValueError('地理坐标不能在转换中舍入或溢出')
    elif column in DATES:
        if datetime.strptime(value,'%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')!=value:
            raise ValueError('时间格式不符合已声明口径')


def warnings_fail(connection):
    with connection.cursor() as cur:
        cur.execute('SHOW COUNT(*) WARNINGS')
        if cur.fetchone()[0]:
            raise ValueError('MySQL 产生警告，禁止静默接受截断或转换')


def require_ready(connection):
    with connection.cursor() as cur:
        cur.execute('SELECT state, version FROM _load_state WHERE singleton=1')
        row=cur.fetchone()
        if not row or row[0]!='ready':
            raise RuntimeError('当前数据批次尚未完整发布，拒绝查询')
        return row[1]


def load(data_dir=ROOT/'data',report_path=ROOT/'reports/olist_load.json'):
    server=ensure_mysql();catalog=tables();token=uuid.uuid4().hex[:12]
    paths={name:Path(data_dir)/spec['target'] for name,spec in catalog.items()}
    # 在创建数据库对象之前先核验全部输入，缺文件不会发布半套表。
    for name,spec in catalog.items():
        verify_file(paths[name],spec)
    report={'server':server,'version':token,'tables':{},'scope':'原始暂存往返及显式类型视图，不做业务去重'}
    with connect() as connection:
        with connection.cursor() as cur:
            cur.execute("SELECT GET_LOCK('gekko_olist_loader',10)")
            if cur.fetchone()[0]!=1:
                raise RuntimeError('另一个导入正在运行')
            cur.execute('CREATE TABLE IF NOT EXISTS _load_state (singleton INT PRIMARY KEY, state VARCHAR(20), version VARCHAR(40))')
            connection.commit()
        pending={}
        for name,spec in catalog.items():
            table=f'_new_{token}_{name}';pending[name]=table;columns=spec['columns']
            definitions=', '.join(f'`{column}` VARCHAR(512) NOT NULL' for column in columns)
            indexes=', '.join(f'KEY `idx_{i}` (`{column}`(64))' for i,column in enumerate(columns) if column.endswith('_id') or column=='product_category_name')
            with connection.cursor() as cur:
                cur.execute(f'CREATE TABLE `{table}` (_source_row BIGINT NOT NULL PRIMARY KEY, {definitions}'+(', '+indexes if indexes else '')+') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin')
            digest=hashlib.sha256();rows=0;batch=[]
            insert=f'INSERT INTO `{table}` VALUES ('+','.join(['%s']*(len(columns)+1))+')'
            with paths[name].open(newline='',encoding='utf-8-sig') as stream,connection.cursor() as cur:
                reader=csv.reader(stream,strict=True)
                if next(reader)!=columns:
                    raise ValueError('输入表头变化')
                for rows,row in enumerate(reader,1):
                    if len(row)!=len(columns):
                        raise ValueError('记录列数变化')
                    for column,value in zip(columns,row):
                        validate_value(column,value)
                    digest.update(row_bytes(row));batch.append((rows,*row))
                    if len(batch)==5000:
                        cur.executemany(insert,batch);warnings_fail(connection);batch=[]
                if batch:
                    cur.executemany(insert,batch);warnings_fail(connection)
            connection.commit()
            actual=hashlib.sha256();read_rows=0
            with connection.cursor(pymysql.cursors.SSCursor) as cur:
                cur.execute(f'SELECT * FROM `{table}` ORDER BY _source_row')
                for read_rows,record in enumerate(cur,1):
                    if record[0]!=read_rows:
                        raise ValueError('来源记录序号不连续')
                    actual.update(row_bytes(record[1:]))
            if rows!=spec['rows'] or read_rows!=rows or digest.digest()!=actual.digest():
                raise ValueError('暂存往返不一致，禁止发布')
            report['tables'][name]={'rows':rows,'source_sha256':spec['sha256'],'decoded_cells_sha256':actual.hexdigest()}
            print(f'{name}: {rows} 条暂存及全字段往返通过',flush=True)
        with connection.cursor() as cur:
            cur.execute("REPLACE INTO _load_state VALUES (1,'publishing',%s)",(token,));connection.commit()
            cur.execute('SHOW FULL TABLES WHERE Table_type = %s',('BASE TABLE',));existing={row[0] for row in cur.fetchall()}
            renames=[];backups=[]
            for name,new in pending.items():
                current=f'raw_{name}'
                if current in existing:
                    old=f'_old_{token}_{name}';backups.append(old);renames.append(f'`{current}` TO `{old}`')
                renames.append(f'`{new}` TO `{current}`')
            cur.execute('RENAME TABLE '+', '.join(renames))
            for name,spec in catalog.items():
                columns=', '.join(expression(column)+f' AS `{column}`' for column in spec['columns'])
                cur.execute(f'CREATE OR REPLACE VIEW `{name}` AS SELECT _source_row, {columns} FROM `raw_{name}`')
                warnings_fail(connection)
            cur.execute("UPDATE _load_state SET state='ready' WHERE singleton=1");connection.commit()
            for old in backups:
                cur.execute(f'DROP TABLE `{old}`')
            cur.execute("SELECT RELEASE_LOCK('gekko_olist_loader')")
    report_path=Path(report_path);report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return {'version':token,'tables':{k:v['rows'] for k,v in report['tables'].items()},'report':str(report_path)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,default=ROOT/'data')
    parser.add_argument('--report',type=Path,default=ROOT/'reports/olist_load.json')
    args=parser.parse_args()
    try:
        print(json.dumps(load(args.data_dir,args.report),ensure_ascii=False))
    except Exception as exc:
        # 数据库异常可能包含 SQL 和原始值，只汇报异常类型。
        print(f'导入失败：{type(exc).__name__}',file=sys.stderr)
        raise SystemExit(1)
