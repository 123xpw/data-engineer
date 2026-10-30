"""R2：真实独立 MySQL 新建、配置复用、恢复及失败隔离实验。"""

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid

import pymysql

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from q2_sql_analysis.mysql_runtime import connect,ensure_mysql
from scripts.verification_support import EvidenceRun,require,sha256


def main():
    with EvidenceRun(ROOT/'reports/repairs/r2','acceptance') as e:
        e.report['repair_contract_sha256']=sha256(ROOT/'repairs/R2_ACCEPTANCE.md')
        e.report['repair_script_sha256']=sha256(__file__);e.save()
        if not e.check('原项目配置兼容',ensure_mysql):return 1
        def lifecycle():
            token=uuid.uuid4().hex[:12];name='gekko-r2-'+token;volume=name+'-data'
            def docker(*args):
                r=subprocess.run(['docker',*args],capture_output=True,text=True,timeout=90)
                require(r.returncode==0,'测试 Docker 操作失败：'+args[0]);return r.stdout
            require(name not in docker('ps','-a','--format','{{.Names}}').splitlines(),'测试容器名碰撞')
            require(volume not in docker('volume','ls','--format','{{.Name}}').splitlines(),'测试卷名碰撞')
            with connect() as c,c.cursor() as cur:
                cur.execute('SELECT state,version FROM _load_state');before=cur.fetchall()
                cur.execute('SELECT COUNT(*) FROM products');before_count=cur.fetchone()[0]
            original_config=sha256(ROOT/'.env')
            records=[];restored=False
            try:
                with tempfile.TemporaryDirectory(prefix='gekko-r2-') as folder:
                    temp=Path(folder);config=temp/'private.env'
                    config.write_text('DEEPSEEK_API_KEY=fixture-model-never-send\nQ4_LIVE=0\n');config.chmod(0o600)
                    with socket.socket() as sock:
                        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
                    env={**os.environ,'GEKKO_MYSQL_CONTAINER':name,'GEKKO_MYSQL_VOLUME':volume,
                         'GEKKO_MYSQL_PORT':str(port),'GEKKO_MYSQL_ENV_FILE':str(config)}
                    def invoke(label,expected=0,extra=None,script=ROOT/'q2_sql_analysis/mysql_runtime.py',fragment=None):
                        start=time.monotonic()
                        r=subprocess.run([sys.executable,str(script)],env={**env,**(extra or {})},cwd=temp,capture_output=True,text=True,timeout=180)
                        elapsed=time.monotonic()-start
                        records.append({'case':label,'exit_code':r.returncode,'seconds':round(elapsed,3)})
                        e.report['lifecycle_progress']=records.copy();e.save()
                        require(r.returncode==expected,f'{label} 退出码不符，stderr: {r.stderr[-300:]}')
                        if expected:
                            require(elapsed<10,f'{label} 未快速失败')
                            require(fragment in r.stderr,f'{label} 缺明确诊断')
                        return json.loads(r.stdout) if not expected else None
                    first=invoke('全新受管实例')
                    def no_model_environment():
                        environment=json.loads(docker('inspect','--format','{{json .Config.Env}}',name))
                        keys={v.split('=',1)[0] for v in environment}
                        require(not {'DEEPSEEK_API_KEY','Q4_LIVE'}&keys,'模型变量被传入数据库容器')
                    no_model_environment()
                    require(config.stat().st_mode & 0o777==0o600,'新配置权限不正确')
                    cfg_hash=sha256(config);second=invoke('同配置重跑')
                    require(sha256(config)==cfg_hash and first['image_id']==second['image_id'],'重跑改变配置或实例镜像')
                    values=dict(line.split('=',1) for line in config.read_text().splitlines() if line and not line.startswith('#'))
                    require(values.get('DEEPSEEK_API_KEY')=='fixture-model-never-send','初始化覆盖了已有模型配置')
                    def test_connection():
                        return pymysql.connect(host='127.0.0.1',port=port,user=values['MYSQL_USER'],password=values['MYSQL_PASSWORD'],
                            database=values['MYSQL_DATABASE'],ssl_ca=str(ROOT/'.venv'/f'mysql-ca-{name}.pem'),ssl_verify_cert=True)
                    with test_connection() as c,c.cursor() as cur:
                        cur.execute('CREATE TABLE recovery_marker (id INT PRIMARY KEY, value INT)')
                        cur.execute('INSERT INTO recovery_marker VALUES (1,731)');c.commit()
                    checkout=temp/'other_checkout/q2_sql_analysis';checkout.mkdir(parents=True)
                    shutil.copyfile(ROOT/'q2_sql_analysis/mysql_runtime.py',checkout/'mysql_runtime.py')
                    invoke('新目录显式复用配置',script=checkout/'mysql_runtime.py')
                    absent=temp/'absent.env'
                    invoke('已有实例缺配置',1,{'GEKKO_MYSQL_ENV_FILE':str(absent)},fragment='缺少私有数据库配置')
                    require(not absent.exists(),'缺配置场景生成了误导性密码')
                    bad=temp/'wrong.env';bad.write_text('\n'.join(k+'='+('wrong-test-password' if k=='MYSQL_PASSWORD' else v) for k,v in values.items())+'\n')
                    invoke('已有实例错误密码',1,{'GEKKO_MYSQL_ENV_FILE':str(bad)},fragment='数据库认证或库选择失败')
                    incomplete=temp/'incomplete.env';incomplete.write_text('MYSQL_USER=gekko_exam\n')
                    incomplete_hash=sha256(incomplete)
                    invoke('不完整配置',1,{'GEKKO_MYSQL_ENV_FILE':str(incomplete)},fragment='私有配置缺少非空数据库参数')
                    require(sha256(incomplete)==incomplete_hash,'不完整配置被覆盖')
                    with socket.socket() as busy:
                        busy.bind(('127.0.0.1',0));busy.listen()
                        conflict=temp/'conflict.env'
                        invoke('端口已占用',1,{'GEKKO_MYSQL_CONTAINER':name+'-conflict','GEKKO_MYSQL_VOLUME':volume+'-conflict',
                            'GEKKO_MYSQL_PORT':str(busy.getsockname()[1]),'GEKKO_MYSQL_ENV_FILE':str(conflict)},fragment='回环端口已占用')
                        require(not conflict.exists(),'端口冲突仍创建凭据')
                    # 名字在本轮开始时确认不存在，且再次核验所有权后仅删除自己的测试容器。
                    labels=json.loads(docker('inspect','--format','{{json .Config.Labels}}',name))
                    require(labels.get('gekko.data-engineer.exam')=='managed','测试容器所有权丢失')
                    docker('rm','-f',name)
                    invoke('存量受管卷缺配置',1,{'GEKKO_MYSQL_ENV_FILE':str(absent)},fragment='缺少私有数据库配置')
                    require(not absent.exists(),'恢复场景生成新密码')
                    invoke('原配置恢复受管卷')
                    no_model_environment()
                    with test_connection() as c,c.cursor() as cur:
                        cur.execute('SELECT value FROM recovery_marker WHERE id=1');restored=cur.fetchone()==(731,)
                    require(restored,'容器恢复后数据标记丢失')
                    require(sha256(config)==cfg_hash,'恢复覆盖原配置')
            finally:
                if name in docker('ps','-a','--format','{{.Names}}').splitlines():
                    labels=json.loads(docker('inspect','--format','{{json .Config.Labels}}',name))
                    require(labels.get('gekko.data-engineer.exam')=='managed','拒绝清理所有权不符的容器')
                    docker('rm','-f',name)
                if volume in docker('volume','ls','--format','{{.Name}}').splitlines():
                    labels=json.loads(docker('volume','inspect','--format','{{json .Labels}}',volume))
                    require(labels.get('gekko.data-engineer.exam')=='managed','拒绝清理所有权不符的卷')
                    docker('volume','rm',volume)
                (ROOT/'.venv'/f'mysql-ca-{name}.pem').unlink(missing_ok=True)
            with connect() as c,c.cursor() as cur:
                cur.execute('SELECT state,version FROM _load_state');require(cur.fetchall()==before,'原项目批次变化')
                cur.execute('SELECT COUNT(*) FROM products');require(cur.fetchone()[0]==before_count,'原项目产品行数变化')
            require(sha256(ROOT/'.env')==original_config,'原项目凭据变化')
            return {'cases':records,'restored_data_marker':restored,'original_project_unchanged':True,
                    'model_only_configuration_bootstrapped':True,'model_keys_absent_from_container_environment':True,
                    'temporary_owned_container_and_volume_removed':True,'limitation':'本机 Docker 实测；不声明其它平台或远程数据库兼容'}
        e.check('独立实例生命周期与非破坏性失败实验',lifecycle)
    print(e.path)
    return 0 if e.report['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
