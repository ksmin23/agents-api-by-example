"""Build one deterministic pure-Python wheel and a private PEP 503 fixture index."""
import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import zipfile

def prepare(root):
    root = Path(root)
    generated = root / 'deploy/.generated'
    index = generated / 'index/simple/acme-sales'
    index.mkdir(parents=True, exist_ok=True)
    members = {
        'acme_sales/__init__.py': (root / 'deploy/private_package/acme_sales/__init__.py').read_bytes(),
        'acme_sales-0.1.0.dist-info/METADATA': b'Metadata-Version: 2.1\nName: acme-sales\nVersion: 0.1.0\nRequires-Python: >=3.11\n',
        'acme_sales-0.1.0.dist-info/WHEEL': b'Wheel-Version: 1.0\nGenerator: tutorial-fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
    }
    records = []
    for name, data in members.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
        records.append(f'{name},sha256={digest},{len(data)}')
    record_name = 'acme_sales-0.1.0.dist-info/RECORD'
    members[record_name] = ('\n'.join(records + [record_name + ',,']) + '\n').encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as wheel:
        for name, data in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            wheel.writestr(info, data)
    raw = stream.getvalue()
    digest = hashlib.sha256(raw).hexdigest()
    filename = 'acme_sales-0.1.0-py3-none-any.whl'
    (index / filename).write_bytes(raw)
    (index / 'index.html').write_text(f'<a href="{filename}#sha256={digest}">{filename}</a>\n')
    (generated / 'requirements.txt').write_text(f'acme-sales==0.1.0 --hash=sha256:{digest}\n')
    (generated / 'requirements.bad.txt').write_text('acme-sales==0.1.0 --hash=sha256:' + '0' * 64 + '\n')
    (generated / 'data').mkdir(exist_ok=True)
    shutil.copyfile(root / 'data/sales.csv', generated / 'data/sales.csv')
    return {'wheel': filename, 'sha256': digest, 'version': '0.1.0'}

if __name__ == '__main__':
    print(json.dumps(prepare(Path(__file__).resolve().parents[1])))
