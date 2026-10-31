"""在新虚拟环境和临时源码副本安装依赖、下载真实数据并执行验证。"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from verification_support import EvidenceRun, ROOT, verify_outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=ROOT / "reports" / "hardening")
    args = parser.parse_args()
    with EvidenceRun(args.report_dir, "clean_environment") as evidence, tempfile.TemporaryDirectory(prefix="gekko-clean-") as folder:
        root = Path(folder)
        project = root / "project"
        project.mkdir()
        for path in ROOT.glob("*.py"):
            shutil.copyfile(path, project / path.name)
        for name in ("requirements.txt", "data_sources.json", "VALIDATION_GATES.md", "delivery_requirements.json"):
            shutil.copyfile(ROOT / name, project / name)
        for name in ("scripts", "tests"):
            shutil.copytree(ROOT / name, project / name, ignore=shutil.ignore_patterns("__pycache__"))
        (project / "q1_data_quality").mkdir()
        for path in (ROOT / "q1_data_quality").iterdir():
            if path.suffix == ".py" or path.name.startswith("ACCEPTANCE_") or path.name in ("cleaning_strategy.md", "strategy_review.md"):
                shutil.copyfile(path, project / "q1_data_quality" / path.name)
        for name in ('q3_etl_pipeline','q4_llm_extraction','q5_system_design','audit'):
            shutil.copytree(ROOT/name,project/name,ignore=shutil.ignore_patterns('__pycache__','outputs','pipeline_log.txt'))
        environment = os.environ.copy()
        shutil.copytree(ROOT / "q2_sql_analysis", project / "q2_sql_analysis", ignore=shutil.ignore_patterns("__pycache__"))
        # 全新 Python/下载环境；数据库为本机独立项目实例，明确不声称重建操作系统或服务器。
        environment["GEKKO_MYSQL_ENV_FILE"] = os.environ.get("GEKKO_MYSQL_ENV_FILE", str(ROOT / ".env"))
        for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
            environment.pop(key, None)
        environment["PYTHONNOUSERSITE"] = "1"
        environment["KAGGLEHUB_CACHE"] = str(root / "empty-cache")
        environment['Q4_LIVE']='0'
        for key in ('Q4_API_KEY','DEEPSEEK_API_KEY','OPENAI_API_KEY'):
            environment.pop(key,None)
        def command(args, *, timeout=900):
            result = subprocess.run(args, cwd=project, env=environment, capture_output=True, text=True, timeout=timeout)
            if result.returncode != 0:
                # 不复制可能含私人源 URL 或凭据的安装日志。
                raise AssertionError(f"{Path(args[0]).name} 子进程失败，退出码 {result.returncode}")
            return result.stdout
        def create():
            command([sys.executable, "-m", "venv", str(root / "venv")])
            return {"fresh_venv": True, "fresh_source_copy": True, "user_site_disabled": True,
                    "mysql_scope": "使用本机项目实例和私有配置，重新导入；不声称是新建服务器"}
        if not evidence.check("创建空虚拟环境与源码副本", create):
            return 1
        python = str(root / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
        def install():
            command([python, "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check", "-r", "requirements.txt"])
            command([python, "-m", "pip", "check"])
            freeze = command([python, "-m", "pip", "freeze", "--disable-pip-version-check"]).splitlines()
            expected = [line.strip() for line in (project / "requirements.txt").read_text().splitlines() if line.strip() and not line.startswith("#")]
            normalize = lambda lines: sorted(x.lower().replace("_", "-") for x in lines)
            if normalize(freeze) != normalize(expected):
                raise AssertionError("干净环境实际依赖与锁定文件不同")
            return {"pip_check": "passed", "installed": freeze}
        if not evidence.check("锁定依赖从零安装且版本一致", install):
            return 1
        if not evidence.check("干净环境单元测试", lambda: {"result": command([python, "-m", "unittest", "discover", "-s", "tests", "-v"])}):
            return 1
        def download():
            command([python, "run_all.py", "--stage", "data"])
            spec = json.loads((project / "data_sources.json").read_text())["datasets"]
            results = {}
            for name, dataset in spec.items():
                results[name] = verify_outputs(project / "data", dataset["files"])
            return {"empty_cache_download": True, "independent_files": results}
        if not evidence.check("空数据空缓存下载并从外部核验", download):
            return 1
        def verify():
            command([python, "scripts/verify_baseline.py"])
            report = json.loads((project / "reports/hardening/baseline_latest.json").read_text())
            if report["status"] != "passed":
                raise AssertionError("干净环境真实流程验证未通过")
            return {"run_id": report["run_id"], "checks": report["checks"]}
        evidence.check("干净环境独立解析和故障流程", verify)
    print(evidence.path)
    return 0 if evidence.report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
