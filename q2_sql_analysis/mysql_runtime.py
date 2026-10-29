"""启动本项目独立的本地 MySQL；凭据仅保存在忽略的 .env 中。"""

import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

import pymysql

ROOT=Path(__file__).resolve().parents[1]
NAME='gekko-de-exam-mysql'
LABEL='gekko.data-engineer.exam=managed'
IMAGE='mysql:8.4@sha256:a0225d1ea6631c8bc2385dc4c2faba17bbf1834ecf369e1659a9a382bd8d5dd7'
CONFIG=Path(os.environ.get('GEKKO_MYSQL_ENV_FILE',str(ROOT/'.env')))
CA=ROOT/'.venv/mysql-ca.pem'


def command(args,timeout=60):
    r=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    if r.returncode:
        # Docker inspect 和日志可能包含凭据，不把完整输出写入报告。
        raise RuntimeError(f'{args[0]} {args[1]} 失败，退出码 {r.returncode}')
    return r.stdout


def settings():
    if not CONFIG.exists():
        raise RuntimeError('缺少本地 .env；先运行 mysql_runtime.py 初始化')
    values={}
    for line in CONFIG.read_text().splitlines():
        if line and not line.startswith('#'):
            key,value=line.split('=',1);values[key]=value
    required=['MYSQL_USER','MYSQL_PASSWORD','MYSQL_DATABASE','MYSQL_ROOT_PASSWORD']
    if not all(key in values for key in required):
        raise RuntimeError('已有 .env 缺少数据库配置；不覆盖现有文件')
    return values


def connect(database=True):
    s=settings()
    return pymysql.connect(host='127.0.0.1',port=3307,user=s['MYSQL_USER'],password=s['MYSQL_PASSWORD'],
        database=s['MYSQL_DATABASE'] if database else None,charset='utf8mb4',collation='utf8mb4_0900_bin',
        ssl_ca=str(CA),ssl_verify_cert=True,ssl_verify_identity=False,
        autocommit=False,connect_timeout=5,read_timeout=120,write_timeout=120,
        sql_mode='STRICT_ALL_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION')


def ensure_mysql():
    info=subprocess.run(['docker','info','--format','{{.ServerVersion}}'],capture_output=True,text=True)
    if info.returncode:
        if any(word in info.stderr.lower() for word in ('permission denied','operation not permitted')):
            raise PermissionError('当前进程无权访问 Docker；不能据此认定服务未启动')
        if sys.platform=='darwin':
            command(['docker','desktop','start'],timeout=120)
        else:
            raise RuntimeError('Docker 服务未启动；请先准备 Docker 或本地运行环境')
    if not CONFIG.exists():
        fd=os.open(CONFIG,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as stream:
            stream.write('MYSQL_DATABASE=gekko_exam\nMYSQL_USER=gekko_exam\n')
            stream.write('MYSQL_PASSWORD='+secrets.token_hex(24)+'\nMYSQL_ROOT_PASSWORD='+secrets.token_hex(24)+'\n')
    settings()
    inspected=subprocess.run(['docker','inspect',NAME],capture_output=True,text=True)
    if inspected.returncode:
        command(['docker','run','-d','--name',NAME,'--label',LABEL,'--env-file',str(CONFIG),
                 '-p','127.0.0.1:3307:3306','--mount','type=volume,source=gekko-de-exam-mysql-data,target=/var/lib/mysql',
                 IMAGE,'--character-set-server=utf8mb4','--collation-server=utf8mb4_0900_bin'],timeout=300)
    else:
        item=json.loads(inspected.stdout)[0]
        if item['Config'].get('Labels',{}).get('gekko.data-engineer.exam')!='managed':
            raise RuntimeError('同名容器不是本项目管理的实例，拒绝修改')
        if not item['State']['Running']:
            command(['docker','start',NAME])
    CA.parent.mkdir(parents=True,exist_ok=True)
    for _ in range(90):
        r=subprocess.run(['docker','cp',f'{NAME}:/var/lib/mysql/ca.pem',str(CA)],capture_output=True,text=True)
        if r.returncode==0:
            try:
                with connect() as c,c.cursor() as cur:
                    cur.execute('SELECT VERSION(), @@sql_mode, @@collation_connection');version,mode,collation=cur.fetchone()
                    if int(version.split('.')[0])<8 or 'MariaDB' in version:
                        raise RuntimeError('必须使用真实 MySQL 8.0+')
                    cur.execute("SHOW STATUS LIKE 'Ssl_cipher'");cipher=cur.fetchone()[1]
                    if not cipher:
                        raise RuntimeError('本地数据库 TLS 未建立')
                    image_id=command(['docker','inspect','--format','{{.Image}}',NAME]).strip()
                    return {'version':version,'sql_mode':mode,'collation':collation,'tls_cipher':cipher,'image_id':image_id,
                            'endpoint':'127.0.0.1:3307','database':settings()['MYSQL_DATABASE']}
            except (pymysql.Error,OSError):
                pass
        time.sleep(1)
    raise RuntimeError('MySQL 在等待窗口内未就绪；保留现有数据，需检查本机 Docker 状态')


if __name__=='__main__':
    print(json.dumps(ensure_mysql(),ensure_ascii=False))
