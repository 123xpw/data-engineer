"""正式入口的运行产物协议：先完整生成，再发布；失败清单不能读取旧文件。"""

import argparse
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid

ROOT = Path(__file__).resolve().parent
RUN_ID = ContextVar('artifact_run_id', default=None)
ARTIFACTS = {
    'q1.1': ('data_quality_metrics.json', 'data_quality_report.md'),
    'q1.2': ('findings_metrics.json', 'findings.md'),
    'q1.3': ('cleaning_strategy.md', 'strategy_review.md'),
    'q2.load': ('load_report.json',),
    'q2.1': ('q2_1_results.json', 'q2_1_findings.md'),
    'q2.2': ('q2_2_results.json', 'q2_2_findings.md'),
    'q2.3': ('q2_3_results.json', 'q2_3_findings.md'),
    'q2.4': ('q2_4_results.json', 'q2_4_query_optimization.md'),
    'q3': ('outputs/sales_facts.parquet','outputs/customer_features.parquet','outputs/returns_log.parquet','pipeline_log.txt','validation_metrics.json','validation_report.md'),
    'q4': ('extracted_issues.json','run_metrics.json','annotation_blind.json','cost_report.md'),
    'q5': ('real_time_pipeline_design.md','design_metrics.json'),
}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(path):
    """元数据拒绝重复字段和非标准数值，避免后一个 passed 覆盖前一个 failed。"""
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('重复 JSON 字段：'+key)
            result[key]=value
        return result
    def invalid(value):raise ValueError('JSON 包含非有限常量：'+value)
    return json.loads(Path(path).read_text(),object_pairs_hook=pairs,parse_constant=invalid)


def source_hashes():
    """生产代码与规则声明；不将生成的业务报告混入源码指纹。"""
    files = list(ROOT.glob('*.py')) + [ROOT/'requirements.txt', ROOT/'data_sources.json']
    for directory in ('q1_data_quality', 'q2_sql_analysis','q3_etl_pipeline','q4_llm_extraction','q5_system_design'):
        files += list((ROOT/directory).glob('*.py')) + list((ROOT/directory).glob('*.sql'))
    files += [ROOT/'q5_system_design/real_time_pipeline_design.md']
    files += [ROOT/'q4_llm_extraction'/name for name in ('prompt_template.txt','pipeline_design.md','accuracy_evaluation.md','deepseek_config.json')]
    files += [ROOT/'q1_data_quality'/name for name in ('cleaning_strategy.md', 'strategy_review.md')]
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(set(files)) if p.is_file()}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.publish-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def manifest_path(output_dir, stage):
    return Path(output_dir)/(stage.replace('.', '_')+'_manifest.json')


def mark(output_dir, stage, status, *, run_id=None, error=None):
    record = {'schema_version': 1, 'run_id': run_id or RUN_ID.get() or uuid.uuid4().hex,
              'stage': stage, 'status': status, 'updated_utc': datetime.now(timezone.utc).isoformat(),
              'artifacts': {}, 'source_sha256': source_hashes()}
    if error:
        record['error'] = error
    atomic_json(manifest_path(output_dir, stage), record)
    return record


def publish(stage, output_dir, action, *, inputs=(), run_id=None):
    """action 接受空输出目录；任何漏写、异常或中断都不能复用旧产物。"""
    output_dir = Path(output_dir)
    record = mark(output_dir, stage, 'running', run_id=run_id)
    try:
        record['input_sha256'] = {str(Path(p).resolve()): digest(p) for p in inputs}
        with tempfile.TemporaryDirectory(dir=output_dir, prefix='.pending-') as folder:
            fresh = Path(folder)
            result = action(fresh)
            completion = result.get('stage_completion', 'passed') if isinstance(result, dict) else 'passed'
            if completion not in ('passed', 'partial'):
                raise RuntimeError('阶段未通过，不发布成功产物')
            hashes = {name: digest(fresh/name) for name in ARTIFACTS[stage]}
            if record['source_sha256'] != source_hashes():
                raise RuntimeError('运行中源码发生变化，不发布结果')
            if any(digest(p) != value for p, value in record['input_sha256'].items()):
                raise RuntimeError('运行中输入发生变化，不发布结果')
            # 清单最后发布；中途异常时即使文件部分更新，也没有可读取的成功清单。
            for name in ARTIFACTS[stage]:
                (output_dir/name).parent.mkdir(parents=True,exist_ok=True)
                os.replace(fresh/name, output_dir/name)
            record.update(status=completion, artifacts=hashes)
            if isinstance(result, dict) and 'load_version' in result:
                record['load_version'] = result['load_version']
            if isinstance(result, dict) and 'output_dir' in result:
                result = {**result, 'output_dir': str(output_dir)}
        record['updated_utc'] = datetime.now(timezone.utc).isoformat()
        atomic_json(manifest_path(output_dir, stage), record)
        return result
    except BaseException as exc:
        record.update(status='failed', artifacts={}, error=type(exc).__name__)
        atomic_json(manifest_path(output_dir, stage), record)
        raise


def validate_manifest(path, expected_run_id, *, allow_partial=False):
    """调用者必须持有本轮编号；仅检查 latest 或文件存在不足以验收。"""
    path = Path(path)
    record = read_json(path)
    allowed = {'passed', 'partial'} if allow_partial else {'passed'}
    if not expected_run_id or record.get('run_id') != expected_run_id or record.get('status') not in allowed:
        raise ValueError('清单不是指定运行的成功产物')
    stage = record.get('stage')
    if stage not in ARTIFACTS or set(record.get('artifacts', {})) != set(ARTIFACTS[stage]):
        raise ValueError('清单缺少约定产物或包含未声明产物')
    if record.get('source_sha256') != source_hashes():
        raise ValueError('源码已变化，需要重新生成产物')
    for name, value in record['artifacts'].items():
        if digest(path.parent/name) != value:
            raise ValueError('产物哈希不一致')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    try:
        record = validate_manifest(args.manifest, args.run_id)
        print(json.dumps({'run_id': record['run_id'], 'stage': record['stage'], 'status': 'passed'}))
    except Exception as exc:
        print(f'产物拒绝：{type(exc).__name__}')
        raise SystemExit(1)
