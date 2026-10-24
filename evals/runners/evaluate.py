#!/usr/bin/env python3
"""Reconcile acceptance evidence; absence is failure to release, never a passing mock."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from engineering.evaluations import catalog, evaluate  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument('--observations', type=Path)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
observations = json.loads(args.observations.read_text()) if args.observations else []
report = evaluate(catalog(root / 'evals/cases'), observations, sha)
report['test_environment'] = 'evidence reconciliation; no product/browser/VM execution by this runner'
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({key: value for key, value in report.items() if key != 'results'}))
sys.exit(0 if report['release_ready'] else 1)
