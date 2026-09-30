# Copyright (c) 2026 EFrMG; MIT, licenses/triage-o-mator-MIT.txt.
# Selected public upstream literal primitive from bin/_search.py; adapted callable harness.
import json
def strings(value, path=""):
    """Yield JSON string values and RFC 6901 pointers; keys and numbers are not searched."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from strings(child, f"{path}/{index}")
    elif isinstance(value, dict):
        for name, child in value.items():
            escaped = name.replace("~", "~0").replace("/", "~1")
            yield from strings(child, f"{path}/{escaped}")

def first_match(payload, component, query):
    values = [("", payload)] if component == "diff" else strings(json.loads(payload))
    for pointer, value in values:
        position = value.find(query)
        if position < 0:
            continue

        start = max(0, position - 60)
        end = min(len(value), position + len(query) + 60)
        return dict(pointer=pointer[:256], pointer_truncated=len(pointer) > 256,
                    character_offset=position, excerpt=value[start:end], excerpt_start=start,
                    omitted_before=start, omitted_after=len(value) - end)

    return None

# Newly authored harness orchestration below, Apache-2.0.
import time,resource,tracemalloc
from .evidence import EvidenceService
from .search import SearchService
from .storage import canonical,digest

def evaluate(store,dataset,snapshot,tasks,tokenizer=None):
    source=EvidenceService(store).source(dataset);manifest=source.manifest(snapshot)
    frozen_digest=digest(tasks);arms=[]
    for arm in ("A-upstream-literal-primitive","B-integrated-literal","C-integrated-ranked"):
        outcomes=[]
        for task in tasks:
            tracemalloc.start();start=time.perf_counter();query=task["query"];hits=[];verified=None;completed=False;error=None
            try:
                if arm.startswith("A"):
                    for record in manifest["items"]:
                        for component,descriptor in record["components"].items():
                            if component not in ("summary","comments","files","diff","reviews","review_comments","closing_issues") or not descriptor["object"]:continue
                            payload=source.object(component,descriptor,record["identity"]["kind"])
                            if first_match(payload,component,query):hits.append(record["identity"]["number"]);break
                    result={"items":sorted(set(hits)),"upstream_coverage":"first case-sensitive match per component; no team flow"}
                else:
                    result=SearchService(store,tokenizer=tokenizer).query(dataset,snapshot,query,mode="literal" if arm.startswith("B") else "ranked",max_bytes=60000)
                    hits=[i["identity"]["number"] for i in result["items"]]
                    verified=all(EvidenceService(store).resolve_ref(f["ref"])["verified"] for i in result["items"] for f in i["fragments"])
                completed=True
            except Exception as failure:
                from .errors import TrioError
                error=failure.code if isinstance(failure,TrioError) else "EVALUATION_FAILURE"
                result={"schema":"trio.evaluation-error/v1","code":error};hits=[]
            elapsed=time.perf_counter()-start;_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
            wire=canonical(result)+b"\n";expected=task["expected_items"]
            outcomes.append({"task":task["id"],"completed":completed,"error":error,"retrieval_correct":completed and sorted(set(hits))==sorted(expected),"source_recall":len(set(hits)&set(expected))/len(expected) if expected else 1.0 if completed else 0.0,"citations_supported":verified,"output_bytes":len(wire),"input_tokens":len(tokenizer.encode(query)) if tokenizer else None,"output_tokens":len(tokenizer.encode(wire.decode())) if tokenizer else None,"retrieval_invocations":1,"api_requests":0,"latency_seconds":elapsed,"python_peak_bytes":peak,"process_peak_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,"false_duplicate_recommendations":None,"reviewer_time":None})
        correct=sum(x["retrieval_correct"] for x in outcomes)
        measured_tokens=sum(x["input_tokens"]+x["output_tokens"] for x in outcomes) if tokenizer else None
        arms.append({"arm":arm,"outcomes":outcomes,"manual_setup":"selected pinned upstream literal primitive; complete upstream review workflow NOT_RUN" if arm.startswith("A") else "integrated services","all_tasks":len(outcomes),"completed":sum(x["completed"] for x in outcomes),"correct":correct,"all_task_totals":{"output_bytes":sum(x["output_bytes"] for x in outcomes),"retrieval_invocations":len(outcomes),"api_requests":0,"latency_seconds":sum(x["latency_seconds"] for x in outcomes),"measured_tokens":measured_tokens},"retrieval_tokens_per_correct_task":measured_tokens/correct if measured_tokens is not None and correct else None})
    return {"schema":"trio.evaluation/v1","classification":"synthetic compatibility/resource probe; not decision-quality evidence","tasks_digest":frozen_digest,"dataset":dataset,"snapshot":snapshot,"arms":arms,"model_evaluation":"NOT_RUN","public_30_case_quality_evaluation":"NOT_RUN","reviewer_time":"NOT_MEASURED","tokens_per_correct_task":None,"billing_basis":"NOT_RUN","randomization":"fixed order for reproducible synthetic resource smoke only; independent reviewed trials must alternate order","build_storage_bytes":sum(p.stat().st_size for p in store.cache_root.rglob("*.sqlite")) if store.cache_root.exists() else 0}
