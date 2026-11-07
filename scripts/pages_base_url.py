"""Compute a GitHub Pages path without network access or publication."""
import argparse
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def pages_base_url(repository):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Use OWNER/REPOSITORY')
    owner, name = repository.split('/')
    return '' if name.lower() == owner.lower() + '.github.io' else '/' + name

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', default=os.environ.get('GITHUB_REPOSITORY'))
    parser.add_argument('--check-repository', action='store_true')
    args = parser.parse_args()
    if not args.repository:
        parser.error('repository is required')
    if args.check_repository:
        configured = json.loads((ROOT / 'tutorial.json').read_text())['repository']
        if not configured or configured.lower() != args.repository.lower():
            parser.error('tutorial.json repository must match GITHUB_REPOSITORY')
    print(pages_base_url(args.repository))

if __name__ == '__main__':main()
