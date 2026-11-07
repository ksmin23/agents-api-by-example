"""Provision before registering. The application API key never enters this image."""
import os
from pathlib import Path
import subprocess
import sys

if __name__ == '__main__':
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--index-url',
                    'http://packages:8080/simple', '--trusted-host', 'packages',
                    '--only-binary=:all:', '--no-deps', '--require-hashes',
                    '-r', '/opt/install/requirements.txt'], check=True)
    key = Path('/run/secrets/executor_key').read_text().strip()
    if not key:
        raise SystemExit('executor_key_missing')
    environment = {k: v for k, v in os.environ.items() if k != 'OPENAI_API_KEY'}
    environment['CODEX_API_KEY'] = key
    os.execvpe('codex', ['codex', 'exec-server', '--remote', os.environ['REMOTE_URL'],
                       '--environment-id', os.environ['ENVIRONMENT_ID']], environment)
