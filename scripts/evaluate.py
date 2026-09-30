# SPDX-License-Identifier: Apache-2.0
"""Public/synthetic frozen-task harness; no network or agent invocation."""
import argparse,json
from trio_triage.storage import Store,read_json,canonical
from trio_triage.evaluation import evaluate
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--home",required=True);p.add_argument("--dataset",required=True);p.add_argument("--snapshot",required=True);p.add_argument("--tasks",required=True)
    a=p.parse_args();result=evaluate(Store(a.home),a.dataset,a.snapshot,read_json(a.tasks));print(canonical(result).decode())
