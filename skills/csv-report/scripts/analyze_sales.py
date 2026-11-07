"""Deterministic sales-report implementation shipped in the Skill bundle."""
import argparse
from collections import defaultdict
import csv
import hashlib
import io
import json
from pathlib import Path


def generate(input_path,output_dir):
    raw=Path(input_path).read_bytes()
    reader=csv.DictReader(io.StringIO(raw.decode('utf-8')))
    if reader.fieldnames!=['date','product','quantity','unit_price']:
        raise ValueError('Unexpected CSV columns')
    rows=list(reader)
    products=defaultdict(int)
    quantity=0
    for row in rows:
        units,price=int(row['quantity']),int(row['unit_price'])
        if units<0 or price<0:
            raise ValueError('Negative values are not supported in this exercise')
        quantity+=units
        products[row['product']]+=units*price
    metrics={'row_count':len(rows),'total_quantity':quantity,
             'total_revenue':sum(products.values()),'by_product':dict(sorted(products.items()))}
    folder=Path(output_dir)
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'summary.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 매출 분석 보고서','',f'거래 행 수: {len(rows)}',f'총 판매 수량: {quantity}',
           f'총매출: {metrics["total_revenue"]:,}','','| 상품 | 매출 |','| --- | ---: |']
    lines += [f'| {name} | {amount:,} |' for name,amount in sorted(products.items())]
    (folder/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (folder/'skill_evidence.json').write_text(json.dumps({
        'skill_name':'csv-report','script_revision':'csv-report-v1',
        'input_sha256':hashlib.sha256(raw).hexdigest(),
    },indent=2),encoding='utf-8')
    return metrics


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(generate(args.input,args.output_dir),ensure_ascii=False))
