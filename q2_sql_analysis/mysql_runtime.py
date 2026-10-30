"""明确区分新建、复用和恢复本地 MySQL；不猜测或覆盖已有实例凭据。"""

import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager

import pymysql

ROOT=Path(__file__).resolve().parents[1]
NAME=os.environ.get('GEKKO_MYSQL_CONTAINER','gekko-de-exam-mysql')
VOLUME=os.environ.get('GEKKO_MYSQL_VOLUME','gekko-de-exam-mysql-data')
PORT=int(os.environ.get('GEKKO_MYSQL_PORT','3307'))
LABEL='gekko.data-engineer.exam=managed'
IMAGE='mysql:8.4@sha256:a0225d1ea6631c8bc2385dc4c2faba17bbf1834ecf369e1659a9a382bd8d5dd7'
CONFIG=Path(os.environ.get('GEKKO_MYSQL_ENV_FILE',str(ROOT/'.env')))
CA=ROOT/'.venv'/('mysql-ca.pem' if NAME=='gekko-de-exam-mysql' else f'mysql-ca-{NAME}.pem')
MYSQL_KEYS=('MYSQL_USER','MYSQL_PASSWORD','MYSQL_DATABASE','MYSQL_ROOT_PASSWORD')


def command(args,timeout=60):
    r=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    if r.returncode:
        raise RuntimeError(f'{args[0]} {args[1]} 失败，退出码 {r.returncode}；不输出可能包含凭据的详情')
    return r.stdout


def private_values():
    if not CONFIG.exists():
        raise RuntimeError('缺少私有数据库配置；已有实例请用 GEKKO_MYSQL_ENV_FILE 显式指定原配置')
    values={}
    for line in CONFIG.read_text().splitlines():
        if line and not line.startswith('#'):
            if '=' not in line:
                raise RuntimeError('私有配置格式错误，不覆盖现有文件')
            key,value=line.split('=',1)
            if key in values:
                raise RuntimeError('私有配置含重复键，不覆盖现有文件')
            values[key]=value
    return values


def settings():
    values=private_values()
    if not all(values.get(key) for key in MYSQL_KEYS):
        raise RuntimeError('私有配置缺少非空数据库参数，不覆盖现有文件')
    return {key:values[key] for key in MYSQL_KEYS}


@contextmanager
def mysql_env_file():
    """共享 .env 中的模型密钥不得传入数据库容器；临时文件权限为 0600。"""
    values=settings()
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',prefix='gekko-mysql-',suffix='.env') as stream:
        for key in MYSQL_KEYS:stream.write(key+'='+values[key]+'\n')
        stream.flush()
        yield stream.name


def connect(database=True):
    s=settings()
    return pymysql.connect(host='127.0.0.1',port=PORT,user=s['MYSQL_USER'],password=s['MYSQL_PASSWORD'],
        database=s['MYSQL_DATABASE'] if database else None,charset='utf8mb4',collation='utf8mb4_0900_bin',
        ssl_ca=str(CA),ssl_verify_cert=True,ssl_verify_identity=False,
        autocommit=False,connect_timeout=5,read_timeout=120,write_timeout=120,
        sql_mode='STRICT_ALL_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION')


def ensure_mysql():
    if not all(re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*',v) for v in (NAME,VOLUME)) or not 1<=PORT<=65535:
        raise RuntimeError('实例名、卷名或回环端口配置不合法')
    info=subprocess.run(['docker','info','--format','{{.ServerVersion}}'],capture_output=True,text=True,timeout=15)
    if info.returncode:
        if any(word in info.stderr.lower() for word in ('permission denied','operation not permitted')):
            raise PermissionError('当前进程无权访问 Docker；不能据此认定服务未启动')
        if sys.platform=='darwin':
            command(['docker','desktop','start'],timeout=120)
        else:
            raise RuntimeError('Docker 服务未启动，请先准备本机 Docker')
    names=command(['docker','ps','-a','--format','{{.Names}}']).splitlines()
    exists=NAME in names
    item=json.loads(command(['docker','inspect',NAME]))[0] if exists else None
    if exists:
        if item['Config'].get('Labels',{}).get('gekko.data-engineer.exam')!='managed':
            raise RuntimeError('同名容器不是本项目管理的实例，拒绝修改')
        bindings=item['HostConfig'].get('PortBindings',{}).get('3306/tcp') or []
        if not any(b['HostIp']=='127.0.0.1' and b['HostPort']==str(PORT) for b in bindings):
            raise RuntimeError('已有实例端口不符，请显式设置 GEKKO_MYSQL_PORT；拒绝连接其他服务')
        settings()
        if not item['State']['Running']:
            command(['docker','start',NAME])
    else:
        volumes=command(['docker','volume','ls','--format','{{.Name}}']).splitlines()
        volume_exists=VOLUME in volumes
        if volume_exists:
            labels=json.loads(command(['docker','volume','inspect','--format','{{json .Labels}}',VOLUME])) or {}
            if labels.get('gekko.data-engineer.exam')!='managed':
                raise RuntimeError('存量卷没有本项目所有权标签，拒绝自动接管；请核实迁移方案')
            settings()
        elif CONFIG.exists():
            values=private_values()
            if any(key in values for key in MYSQL_KEYS):settings()
        with socket.socket() as probe:
            # 允许已关闭连接的 TIME_WAIT 回收；仍不能抢占活跃监听端口。
            probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            try:
                probe.bind(('127.0.0.1',PORT))
            except OSError as exc:
                raise RuntimeError('回环端口已占用，请选择 GEKKO_MYSQL_PORT；未新建实例或凭据') from exc
        exists_config=CONFIG.exists()
        # 新实例/新卷允许向“只有模型配置”的文件追加全新数据库凭据；残缺 MYSQL 配置仍拒绝。
        if not exists_config or not any(key in private_values() for key in MYSQL_KEYS):
            fd=os.open(CONFIG,os.O_WRONLY|(os.O_APPEND if exists_config else os.O_CREAT|os.O_EXCL),0o600)
            os.chmod(CONFIG,0o600)
            with os.fdopen(fd,'w') as stream:
                if exists_config:stream.write('\n')
                stream.write('MYSQL_DATABASE=gekko_exam\nMYSQL_USER=gekko_exam\n')
                stream.write('MYSQL_PASSWORD='+secrets.token_hex(24)+'\nMYSQL_ROOT_PASSWORD='+secrets.token_hex(24)+'\n')
        if not volume_exists:
            command(['docker','volume','create','--label',LABEL,VOLUME])
        with mysql_env_file() as env_path:
            command(['docker','run','-d','--name',NAME,'--label',LABEL,'--env-file',env_path,
                     '-p',f'127.0.0.1:{PORT}:3306','--mount',f'type=volume,source={VOLUME},target=/var/lib/mysql',
                     IMAGE,'--character-set-server=utf8mb4','--collation-server=utf8mb4_0900_bin'],timeout=300)
    CA.parent.mkdir(parents=True,exist_ok=True)
    for _ in range(90):
        r=subprocess.run(['docker','cp',f'{NAME}:/var/lib/mysql/ca.pem',str(CA)],capture_output=True,text=True,timeout=15)
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
                            'endpoint':f'127.0.0.1:{PORT}','database':settings()['MYSQL_DATABASE'],
                            'container':NAME,'volume':VOLUME,'configuration':'显式原配置或全新实例初始化；不输出凭据'}
            except pymysql.Error as exc:
                code=exc.args[0] if exc.args else None
                if code in (1044,1045,1049):
                    raise RuntimeError('数据库认证或库选择失败，请检查原私有配置；不会覆盖密码或重建数据') from None
                if code not in (2002,2003,2006,2013):
                    raise RuntimeError(f'MySQL 连接检查失败，错误代码 {code}；不是普通启动等待') from None
            except OSError:
                pass
        time.sleep(1)
    raise RuntimeError('MySQL 在等待窗口内未就绪；保留现有数据，请检查本机实例状态')


if __name__=='__main__':
    try:
        print(json.dumps(ensure_mysql(),ensure_ascii=False))
    except (RuntimeError,PermissionError) as exc:
        print(str(exc),file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(f'数据库初始化失败：{type(exc).__name__}',file=sys.stderr)
        raise SystemExit(1)
