"""Run chapter 15 in a fresh kernel; --live authorizes paid API execution."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_extensions import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Run the actual Agents API with two subagents')
    args = parser.parse_args()
    return 0 if run(15, args.live, chapter_slug='15_multi_agent') else 1


if __name__ == '__main__':
    raise SystemExit(main())
