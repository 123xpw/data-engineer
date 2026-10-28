"""Q1.3 文档独立入口：检查与交付策略，不实施清洗或认证业务含义。"""

import argparse
import hashlib
import json
from pathlib import Path
import re

SOURCE=Path(__file__).resolve().parent


def deliver_strategy(output_dir):
    strategy=(SOURCE/'cleaning_strategy.md').read_text(encoding='utf-8')
    body=strategy.split('\n',1)[1] if strategy.startswith('# ') else strategy
    count=len(re.sub(r'\s','',body))
    if not 300<=count<=500:
        raise ValueError('策略正文须为 300–500 个非空白字符（不含标题）')
    review=(SOURCE/'strategy_review.md').read_text(encoding='utf-8')
    if not review.strip():
        raise ValueError('缺少规则与证据审查记录')
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    hashes={}
    for name,text in [('cleaning_strategy.md',strategy),('strategy_review.md',review)]:
        target=output_dir/name
        if target.resolve()!=(SOURCE/name).resolve():
            target.write_text(text,encoding='utf-8')
        hashes[name]=hashlib.sha256(text.encode('utf-8')).hexdigest()
    return {'scope':'Q1.3 策略文档交付；未实施 ETL','nonwhitespace_characters':count,
            'han_characters':len(re.findall(r'[\u4e00-\u9fff]',body)),
            'artifact_sha256':hashes,'business_approval':'未获得；见规则假设和待确认范围',
            'validation_limit':'程序只核验交付文件和长度；不是自动业务语义审查'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=SOURCE)
    print(json.dumps(deliver_strategy(parser.parse_args().output_dir),ensure_ascii=False))
