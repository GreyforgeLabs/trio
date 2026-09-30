#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read-only compatibility bridge for a separately installed Tranche checkout.

No Tranche source is shipped here. Only an explicitly selected, hash-pinned
public source file is loaded. Model calls, credentials and GitHub writes are
not part of this export. Run with Trio installed (or PYTHONPATH=src).
"""
import hashlib
import importlib.util
from pathlib import Path

from trio_triage import contracts as c
from trio_triage.errors import TrioError
from trio_triage.handoff import ENVELOPE, TRANCHE_BLOB, TRANCHE_COMMIT, sealed, validate_envelope
from trio_triage.storage import digest, read_json


def load_tranche(root):
    root = Path(root).absolute()
    path = root / "tranche.py"
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise TrioError("UNSAFE_PATH")
    if path.stat().st_size > 1048576:
        raise TrioError("RESOURCE_LIMIT")
    with path.open("rb") as stream:
        raw = stream.read(1048577)
    if len(raw) > 1048576:
        raise TrioError("RESOURCE_LIMIT")
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != TRANCHE_BLOB:
        raise TrioError("HANDOFF_VERSION", "Tranche source differs from the supported public version")
    spec = importlib.util.spec_from_file_location("_trio_selected_tranche", path)
    module = importlib.util.module_from_spec(spec)
    # The checked bytes, not a second filesystem read, are the executed source.
    exec(compile(raw, str(path), "exec"), module.__dict__)
    def forbidden(*args, **kwargs):
        raise TrioError("SCOPE_DENIED", "Export cannot call a model or read credentials")
    module.ask = forbidden
    module.read_key = forbidden
    return module


def export(api, batch_id):
    """Use the producer's own binding API; independently validate the envelope."""
    files = {"snapshot": Path(api.PAGES_DIR) / "snapshot.json",
             **{name: Path(api.OUT_DIR) / name for name in
                ("summary.json", "clusters.json", "dupes.json", "batches.json", "judgments.jsonl", "pair_verdicts.jsonl")}}
    def observed():
        values = {}
        for name, path in files.items():
            if any(p.is_symlink() for p in (path, *path.parents)):
                raise TrioError("UNSAFE_PATH")
            if not path.exists() and name in ("judgments.jsonl", "pair_verdicts.jsonl"):
                values[name] = None
                continue
            if not path.is_file() or path.stat().st_size > 67108864:
                raise TrioError("RESOURCE_LIMIT")
            values[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        return values
    before = observed()
    snapshot = read_json(files["snapshot"], max_bytes=67108864)
    summary = read_json(files["summary.json"])
    clusters = read_json(files["clusters.json"])
    relationships = read_json(files["dupes.json"])
    batches = read_json(files["batches.json"])
    if (snapshot.get("version") != 1 or snapshot.get("repo") != api.REPO
            or not isinstance(snapshot.get("items"), list) or snapshot.get("digest") != digest(snapshot["items"])
            or summary.get("format_version") != 2 or summary.get("repo") != api.REPO
            or summary.get("allow_unbound") is not False or summary.get("unbound_judgments") != 0
            or batches.get("format_version") != 3 or batches.get("repo") != api.REPO):
        raise TrioError("HANDOFF_VERSION", "Fresh bound Tranche v3 reports are required")
    checksums = {"clusters.json": digest(clusters), "dupes.json": digest(relationships)}
    if summary.get("output_digests") != checksums or batches.get("dupes_digest") != checksums["dupes.json"]:
        raise TrioError("HANDOFF_STALE", "Tranche report files belong to different generations")
    prs = api.load_prs()
    judgments = api.current_judgments(prs)
    pairs = api.current_pairs(prs, judgments)
    if (summary.get("report_binding") != api.report_binding(prs, judgments, pairs)
            or summary.get("prs_in_corpus") != len(prs)):
        raise TrioError("HANDOFF_STALE", "Captured input or judgments changed; regenerate the report")
    if not isinstance(batches.get("batches"), list):
        raise TrioError("HANDOFF_CORRUPT")
    # Recompute only pure batch composition using the verified producer API.
    if batches != api.merge_batches(relationships, judgments, prs, checksums["dupes.json"]):
        raise TrioError("HANDOFF_STALE", "Batch composition differs from the current verified report")
    selected = [batch for batch in batches["batches"] if batch.get("id") == batch_id]
    if len(selected) != 1:
        raise TrioError("INVALID_TARGET", "Select one existing batch identifier")
    batch = selected[0]
    membership = batch.get("members")
    if not isinstance(membership, list) or not membership:
        raise TrioError("HANDOFF_CORRUPT")
    raws = {raw["number"]: raw for raw in snapshot["items"]}
    if len(raws) != len(snapshot["items"]) or any(number not in raws for number in membership):
        raise TrioError("HANDOFF_CORRUPT")
    items = [raws[number] for number in membership]
    try:
        base = items[0]["base"]["repo"]
        repository = c.repository(api.REPO, database_id=base["id"])
    except (ValueError, KeyError, TypeError):
        raise TrioError("HANDOFF_IDENTITY") from None
    chosen = set(membership)
    selected_relations = {
        "confirmed_groups": [g for g in relationships["confirmed_groups"] if chosen.intersection(g)],
        "review_groups": [g for g in relationships["review_groups"] if chosen.intersection(g["members"])],
        "uncertain_pairs": [p for p in relationships["uncertain_pairs"] if p["a"] in chosen or p["b"] in chosen],
        "meaning": "Imported model suggestions, not verified duplicates; no survivor or approval selected",
    }
    result = sealed({"schema": ENVELOPE, "repository": repository,
        "source": {"tool_commit": TRANCHE_COMMIT, "tool_blob": TRANCHE_BLOB,
                   "snapshot_digest": snapshot["digest"], "observed_at": snapshot["observed_at"],
                   "report_binding": summary["report_binding"],
                   "output_digests": dict(checksums, **{"batches.json": digest(batches)})},
        "batch": {"id": batch_id, "members": membership, "source_digest": digest(batch)},
        "items": items, "relationships": selected_relations})
    validate_envelope(result)
    if observed() != before:
        raise TrioError("HANDOFF_STALE", "Tranche inputs changed during export")
    return result


def read_selected_batch(root, batch_id):
    """One explicit installed dependency; no files need a manual handoff."""
    try:
        return export(load_tranche(root), batch_id)
    except (KeyError, TypeError, ValueError, OSError):
        raise TrioError("HANDOFF_CORRUPT", "Invalid or incomplete Tranche export inputs") from None
