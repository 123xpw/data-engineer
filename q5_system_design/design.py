"""Q5 独立文档交付与情景计算；不把程序检查冒充架构压测或业务认证。"""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
SOURCE=Path(__file__).with_name('real_time_pipeline_design.md')


def scenario(orders_per_day=1000000,review_fraction='0.3',input_tokens=600,output_tokens=150,input_price='1',output_price='3',route_fraction='0.1',cache_hit_fraction='0.2'):
    annual_reviews=Decimal(orders_per_day)*365*Decimal(review_fraction)
    cost=annual_reviews*(input_tokens*Decimal(input_price)+output_tokens*Decimal(output_price))/1000000
    filtered=cost*Decimal(route_fraction)*(1-Decimal(cache_hit_fraction))
    return {'annual_all_review_cost_usd':str(cost),'annual_routed_cost_usd':str(filtered),
        'average_orders_per_second':str(Decimal(orders_per_day)/86400),
        'assumed_peak_events_per_second':str(Decimal(orders_per_day)/86400*20*6),
        'scope':'输入/输出单价与比例均为压力情景假设，不是厂商报价或实际费用；未含基础设施/人工'}


def deliver(output_dir):
    text=SOURCE.read_text()
    body=text.split('## 设计正文\n',1)[1].split('## 架构图',1)[0]
    count=len(re.sub(r'\s','',body))
    if not 800<=count<=1500 or '```mermaid' not in text:raise ValueError('正文长度或架构图缺失')
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    if (output_dir/SOURCE.name).resolve()!=SOURCE.resolve():(output_dir/SOURCE.name).write_text(text)
    result={'body_nonwhitespace_characters':count,'han_characters':len(re.findall(r'[\u4e00-\u9fff]',body)),
        'scenario':scenario(),'scope':'文档交付、字数与数学情景；未部署、压测或独立人员审阅'}
    (output_dir/'design_metrics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-dir',type=Path,default=SOURCE.parent)
    from artifact_manifest import publish
    args=parser.parse_args()
    print(json.dumps(publish('q5',args.output_dir,deliver),ensure_ascii=False))
