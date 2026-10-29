"""在真实 MySQL 临时表检验 Q2.1 的手算反例，不改正式表。"""

from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from q2_sql_analysis.mysql_runtime import connect
from scripts.verification_support import EvidenceRun


def check_cases():
    with connect() as c,c.cursor() as cur:
        cur.execute('CREATE TEMPORARY TABLE case_products (product_category_name VARCHAR(100) COLLATE utf8mb4_0900_bin)')
        cur.execute('CREATE TEMPORARY TABLE case_translation (product_category_name VARCHAR(100) COLLATE utf8mb4_0900_bin, product_category_name_english VARCHAR(100) COLLATE utf8mb4_0900_bin)')
        products=['ok','ok','none','none','',None,'blank','null_eng','spaces','dupe','dupe','empty_dupe','case','tail ','NULL','partialvalid']
        translation=[('ok','good'),('blank',''),('null_eng',None),('spaces','   '),('dupe','one'),('dupe','two'),
                     ('empty_dupe',''),('empty_dupe',None),('CASE','upper'),('tail','no_space'),('partialvalid',None),('partialvalid','valid')]
        cur.executemany('INSERT INTO case_products VALUES (%s)',[(v,) for v in products])
        cur.executemany('INSERT INTO case_translation VALUES (%s,%s)',translation)
        sql=(ROOT/'q2_sql_analysis/q2_1_translation_gap.sql').read_text().replace('FROM products AS','FROM case_products AS').replace('FROM product_category_name_translation AS','FROM case_translation AS')
        cur.execute(sql);actual=dict(cur.fetchall())
        expected={'none':2,'blank':1,'null_eng':1,'spaces':1,'empty_dupe':1,'case':1,'tail ':1,'NULL':1}
        assert actual==expected,f'手算反例不符，实际 {actual}；预期 {expected}'
        return {'actual':actual,'synthetic':True,'temporary_tables':True,'risk':'重复映射、空白英文、NULL、大小写及尾空格'}


if __name__=='__main__':
    with EvidenceRun(ROOT/'reports/q2_1','sql_cases') as evidence:
        evidence.check('真实 MySQL 手算反连接反例',check_cases)
    print(evidence.path)
    raise SystemExit(0 if evidence.report['status']=='passed' else 1)
