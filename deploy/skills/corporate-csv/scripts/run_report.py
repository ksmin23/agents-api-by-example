"""Skill entry point. Its business implementation comes from the private wheel."""
import argparse
import hashlib
import json
from pathlib import Path
import acme_sales

def generate(input_path, output_dir):
    raw = Path(input_path).read_bytes()
    metrics = acme_sales.calculate(raw.decode('utf-8'))
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'summary.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2))
    lines = ['# 매출 분석 보고서', '', f"거래 행 수: {metrics['row_count']}",
             f"총 판매 수량: {metrics['total_quantity']}", f"총매출: {metrics['total_revenue']:,}",
             '', '| 상품 | 매출 |', '| --- | ---: |']
    lines += [f'| {name} | {value:,} |' for name, value in metrics['by_product'].items()]
    (out / 'report.md').write_text('\n'.join(lines) + '\n')
    (out / 'package_evidence.json').write_text(json.dumps({
        'distribution': 'acme-sales', 'version': acme_sales.__version__,
        'module_file': acme_sales.__file__, 'input_sha256': hashlib.sha256(raw).hexdigest(),
    }, indent=2))
    return metrics

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    print(json.dumps(generate(args.input, args.output_dir)))
