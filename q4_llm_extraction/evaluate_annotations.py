"""拒绝空标注；评价人工标签与预测的差异，不把模型自评分当准确率。"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from artifact_manifest import atomic_json, digest
from q4_llm_extraction.extract_reviews import CATEGORIES, annotation_sample, read_reviews, strict_json, validate_batch


def evaluate(labels, predictions, expected):
    if not isinstance(labels.get('annotator'), str) or not labels['annotator'].strip() or not labels.get('annotated_utc'):
        raise ValueError('没有人工标注人/时间，拒绝报告准确率')
    datetime.fromisoformat(labels['annotated_utc'].replace('Z', '+00:00'))
    expected_rows = {r['source_row']: r for r in expected['rows']}
    if len(expected_rows) != 30 or len(labels.get('rows', [])) != 30:
        raise ValueError('必须提交冻结的 30 条标注')
    source_ids = [r['source_row'] for r in labels['rows']]
    if len(set(source_ids)) != 30 or set(source_ids) != set(expected_rows):
        raise ValueError('标注样本来源行缺失或重复')
    predicted = {}
    for row in predictions:
        if row['source_row'] in predicted:
            raise ValueError('预测存在重复来源行')
        predicted[row['source_row']] = row
    tp = fp = fn = exact = sentiment_correct = actionable_correct = 0
    audit = {'evidence_supported': 0, 'translation_faithful': 0, 'severity_reasonable': 0}
    audited_rows = 0; differences = []
    for row in labels['rows']:
        sid = row['source_row']; original = expected_rows[sid]
        if any(row[k] != original[k] for k in ('message', 'review_id', 'order_id')):
            raise ValueError('标注原文或标识与冻结样本不一致')
        truth = row.get('labels')
        if not isinstance(truth, dict) or set(truth) != {'categories', 'sentiment', 'actionable_for_seller', 'note'}:
            raise ValueError('人工标签未完成')
        categories = truth['categories']
        if not isinstance(categories, list) or any(c not in CATEGORIES for c in categories) or len(set(categories)) != len(categories):
            raise ValueError('人工类别错误或重复')
        if truth['sentiment'] not in ('negative', 'neutral', 'positive') or type(truth['actionable_for_seller']) is not bool:
            raise ValueError('人工情感/可行动性标签错误')
        pred = predicted.get(sid)
        if not pred or pred['review_id'] != row['review_id'] or pred['order_id'] != row['order_id'] or pred['status'] != 'resolved':
            raise ValueError('样本预测缺失、错配或未完成')
        validate_batch({'results':[{k:pred[k] for k in ('source_row','issues','sentiment_score','actionable_for_seller','confidence')}]},[original])
        actual = {issue['category'] for issue in pred['issues']}; target = set(categories)
        tp += len(actual & target); fp += len(actual-target); fn += len(target-actual)
        exact += actual == target
        score = pred['sentiment_score']; feeling = 'negative' if score < -0.2 else 'positive' if score > 0.2 else 'neutral'
        sentiment_correct += feeling == truth['sentiment']
        actionable_correct += pred['actionable_for_seller'] == truth['actionable_for_seller']
        review = row.get('prediction_audit')
        if not isinstance(review, dict) or set(review) != set(audit) or any(type(v) is not bool for v in review.values()):
            raise ValueError('尚未完成人工解盲后的引文/翻译/严重度复核')
        if pred['issues']:
            audited_rows += 1
            for key in audit:
                audit[key] += review[key]
        differences.append({'source_row': sid, 'expected_categories': sorted(target), 'predicted_categories': sorted(actual),
                            'categories_equal': actual == target, 'sentiment_equal': feeling == truth['sentiment'],
                            'actionable_equal': pred['actionable_for_seller'] == truth['actionable_for_seller'],
                            'prediction_audit': review, 'note': truth['note']})
    precision = tp/(tp+fp) if tp+fp else None
    recall = tp/(tp+fn) if tp+fn else None
    f1 = 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None
    return {'sample_size': 30, 'tp': tp, 'fp': fp, 'fn': fn, 'micro_precision': precision, 'micro_recall': recall, 'micro_f1': f1,
            'category_set_exact_match': exact/30, 'sentiment_agreement': sentiment_correct/30,
            'actionability_agreement': actionable_correct/30, 'predicted_issue_rows_audited': audited_rows,
            'human_audit_row_pass_rates': {k: v/audited_rows if audited_rows else None for k, v in audit.items()},
            'annotator': labels['annotator'], 'annotated_utc': labels['annotated_utc'], 'differences': differences,
            'scope': '非空低分 30 行人工样本；类别集合粒度，不是逐问题实体 F1；解盲检查可能有锚定偏差；非总体准确率认证'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--predictions', type=Path, default=Path(__file__).with_name('extracted_issues.json'))
    parser.add_argument('--input', type=Path, default=ROOT/'data/olist/olist_order_reviews_dataset.csv')
    parser.add_argument('--output', type=Path, default=ROOT/'reports/q4/human_evaluation.json')
    args = parser.parse_args(); rows, _ = read_reviews(args.input)
    result = evaluate(strict_json(args.labels.read_text()), strict_json(args.predictions.read_text()), annotation_sample(rows))
    result['label_sha256'] = digest(args.labels); result['prediction_sha256'] = digest(args.predictions)
    atomic_json(args.output, result)
    print(json.dumps({k: v for k, v in result.items() if k != 'differences'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
