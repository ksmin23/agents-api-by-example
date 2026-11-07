"""Explicitly synchronize teaching Plugin copies; not part of artifact builds."""
from pathlib import Path
from tutorial_helpers.extensions import sync_plugin

if __name__ == '__main__':
    sync_plugin(Path(__file__).resolve().parents[1])
    print('Synchronized Plugin source copies. Review the diff before building.')
