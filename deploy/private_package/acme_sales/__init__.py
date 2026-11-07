"""Fictional internal package, never uploaded to a public package index."""
from collections import defaultdict
import csv
import io

__version__ = "0.1.0"

def calculate(text):
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames != ['date', 'product', 'quantity', 'unit_price']:
        raise ValueError('invalid_columns')
    rows = list(reader)
    products = defaultdict(int)
    quantity = 0
    for row in rows:
        units, price = int(row['quantity']), int(row['unit_price'])
        if units < 0 or price < 0:
            raise ValueError('negative_amount')
        quantity += units
        products[row['product']] += units * price
    return {'row_count': len(rows), 'total_quantity': quantity,
            'total_revenue': sum(products.values()), 'by_product': dict(sorted(products.items()))}
