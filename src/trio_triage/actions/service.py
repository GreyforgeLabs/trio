# SPDX-License-Identifier: Apache-2.0
"""Newly authored action authority and crash-safe journal.

No credentials, HTTP client, shell, donor executable or automatic retry are
available here. A separately configured adapter must supply the narrow transport.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from trio_triage.errors import TrioError
from trio_triage.storage import atomic_json, read_json, confined

OPERATIONS = frozenset({"comment", "close", "reopen"})
ID_PATTERN = re.compile(r"[a-f0-9]{32}\Z")
NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
SECRET_PATTERN = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"(?i:authorization\s*:\s*bearer)|"
    r"(?i:(?:password|access_token|api_key)\s*[=:]\s*[^\s]{8,}))"
)


def _fail(code, exit_code=3):
    raise TrioError(code, "action refused", exit_code=exit_code)


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _directory(store, create=False):
    store.require()
    root = Path(store.root)
    if not root.is_dir() or root.is_symlink():
        _fail("NOT_INITIALIZED")
    path = root / "actions"
    if path.is_symlink():
        _fail("SCOPE_DENIED")
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
    return path


def _path(store, operation_id):
    if not isinstance(operation_id, str) or not ID_PATTERN.fullmatch(operation_id):
        _fail("INVALID_OPERATION")
    return _directory(store) / (operation_id + ".json")


@contextmanager
def _writer_lock(store):
    path = _directory(store, create=True) / "publisher.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _fail("PUBLISHER_BUSY")
        yield
    finally:
        os.close(fd)


def _validate_target(target):
    fields = {"host", "repository_id", "full_name", "kind", "number", "item_id"}
    if not isinstance(target, dict) or set(target) != fields:
        _fail("INVALID_TARGET")
    if target["host"] != "github.com" or target["kind"] not in ("issue", "pr"):
        _fail("SCOPE_DENIED")
    if not isinstance(target["full_name"], str) or not NAME_PATTERN.fullmatch(target["full_name"]):
        _fail("INVALID_TARGET")
    for key in ("repository_id", "number", "item_id"):
        if type(target[key]) is not int or target[key] <= 0:
            _fail("INVALID_TARGET")


def _validate_expected(target, expected):
    fields = {"state"} | ({"head_sha", "merged"} if target["kind"] == "pr" else set())
    if not isinstance(expected, dict) or set(expected) != fields or expected["state"] not in ("open", "closed"):
        _fail("INVALID_PRECONDITION")
    if target["kind"] == "pr":
        if type(expected["merged"]) is not bool or not isinstance(expected["head_sha"], str) or not re.fullmatch("[a-f0-9]{40}", expected["head_sha"]):
            _fail("INVALID_PRECONDITION")


def _screen(text):
    if not isinstance(text, str) or not text.strip() or len(text.encode()) > 65536:
        _fail("INVALID_TEXT")
    if SECRET_PATTERN.search(text) or any(ord(c) < 32 and c not in "\n\t" for c in text):
        _fail("SHARE_BLOCKED")


def _enrolled(store, target):
    # Enrollment is a locally captured scope record; it is never an imported
    # plan flag or retrieved text. Contradictory/private scopes fail closed.
    found = []
    datasets = confined(store.root, "datasets")
    for path in sorted(datasets.glob("*/scope.json")):
        path = confined(store.root, path.relative_to(store.root))
        scope = read_json(path)
        if scope.get("repository_id") != target["repository_id"]:
            continue
        if (scope.get("host") != target["host"] or
            scope.get("full_name") != target["full_name"]):
            _fail("IDENTITY_MISMATCH")
        suspension = confined(store.root, path.parent.relative_to(store.root) / "local" / "suspension.json")
        if scope.get("visibility") != "public" or scope.get("suspended") or suspension.exists():
            _fail("PUBLIC_REPO_REQUIRED")
        found.append(path.parent.name)
    if not found:
        _fail("SCOPE_DENIED")
    return found


def plan(store, target, operation, text, expected, *, finding_digest=None,
         policy_revision="1"):
    """Persist a non-executing exact preview. Planning does not enable writes."""
    store.require()
    if operation not in OPERATIONS:
        _fail("ACTION_UNSUPPORTED")
    _validate_target(target)
    _validate_expected(target, expected)
    _enrolled(store, target)
    _screen(text)
    if operation == "reopen" and target["kind"] == "pr" and expected["merged"]:
        _fail("MERGED_PR")
    if finding_digest is not None and not re.fullmatch("[a-f0-9]{64}", finding_digest):
        _fail("INVALID_PRECONDITION")
    if not isinstance(policy_revision, str) or not policy_revision:
        _fail("INVALID_PRECONDITION")
    operation_id = uuid.uuid4().hex
    proposal = {
        "schema": "trio.action-plan/v1", "operation_id": operation_id,
        "target": dict(target), "operation": operation, "text": text,
        "expected": dict(expected), "finding_digest": finding_digest,
        "policy_revision": policy_revision,
        "destination": "https://api.github.com/repos/" + target["full_name"],
    }
    proposal["digest"] = _digest(proposal)
    record = {"schema": "trio.action-journal/v1", "plan": proposal,
              "authorization": None, "created_at": _now(),
              "steps": {
                  "comment": {"outcome": "not_sent"},
                  "state": {"outcome": "not_requested" if operation == "comment" else "not_sent"},
              }, "attempted": False, "completed": False}
    with _writer_lock(store):
        atomic_json(_path(store, operation_id), record)
    return proposal


def inspect(store, operation_id):
    """Read without creating directories, locks or credentials."""
    path = _path(store, operation_id)
    if not path.exists() or path.is_symlink():
        _fail("ACTION_MISSING")
    record = read_json(path)
    if record.get("schema") != "trio.action-journal/v1":
        _fail("SCHEMA_NEWER")
    proposal = record.get("plan", {})
    digest = proposal.get("digest")
    content = {k: v for k, v in proposal.items() if k != "digest"}
    if content.get("operation_id") != operation_id or _digest(content) != digest:
        _fail("PLAN_CHANGED")
    return record


def _publisher(store, publisher, require_enabled=True):
    cfg = store.config
    if require_enabled and cfg.get("writes_enabled") is not True:
        _fail("ACTION_DISABLED")
    designated = cfg.get("publisher_id")
    if not designated or cfg.get("installation_id") != designated:
        _fail("REVIEW_ONLY")
    roles = cfg.get("roles", {}).get(publisher, [])
    if isinstance(roles, str):
        roles = [roles]
    if "publisher" not in roles:
        _fail("PUBLISHER_REQUIRED")


def _pending(store, excluding=None):
    directory = _directory(store)
    if not directory.exists():
        return []
    pending = []
    for path in sorted(directory.glob("*.json")):
        record = inspect(store, path.stem)
        if path.stem != excluding and any(s["outcome"] == "unknown" for s in record["steps"].values()):
            pending.append(path.stem)
    return pending


def publisher_ready(store):
    """A handover cannot activate a journal with unresolved attempts."""
    return {"ready": not bool(_pending(store)), "unknown_operations": _pending(store)}


def authorize(store, operation_id, digest, publisher):
    """A local publisher action only; never called by exchange/import."""
    with _writer_lock(store):
        _publisher(store, publisher)
        record = inspect(store, operation_id)
        proposal = record["plan"]
        if proposal["digest"] != digest or record["attempted"]:
            _fail("PLAN_CHANGED")
        if proposal["operation"] not in store.config.get("enabled_actions", []):
            _fail("ACTION_DISABLED")
        if _pending(store):
            _fail("DELIVERY_UNKNOWN", 4)
        record["authorization"] = {
            "digest": digest, "publisher": publisher,
            "installation_id": store.config["installation_id"], "at": _now(),
        }
        atomic_json(_path(store, operation_id), record)
    return {"operation_id": operation_id, "digest": digest, "authorized": True}


def _validate_local_finding(store, digest, target, operation):
    from trio_triage.team import TeamService
    from trio_triage.triage import TriageService
    from trio_triage.evidence import EvidenceService
    entities = {
        e["entity_id"] for e in TeamService(store).events()
        if e["operation"] == "finding" and e["payload"].get("decision_digest") == digest
    }
    if len(entities) != 1:
        _fail("PLAN_CHANGED")
    view = TriageService(store).show(entities.pop())
    if view["conflict"] or len(view["revisions"]) != 1:
        _fail("PLAN_CHANGED")
    revision = view["revisions"][0]
    if revision["payload"].get("decision_digest") != digest:
        _fail("PLAN_CHANGED")
    payload = revision["payload"]
    def matches(item):
        if not isinstance(item, dict):
            return False
        if all(item.get(k) == v for k, v in target.items()):
            return True
        repo = item.get("repository", {})
        return (repo.get("host") == target["host"] and
                repo.get("database_id") == target["repository_id"] and
                repo.get("full_name") == target["full_name"] and
                item.get("kind") == target["kind"] and
                item.get("number") == target["number"] and
                item.get("database_id") == target["item_id"])
    if not any(matches(item) for item in payload.get("items", [])):
        _fail("PLAN_CHANGED")
    if operation == "close" and payload.get("category") == "duplicate" and matches(payload.get("canonical_survivor")):
        _fail("PLAN_CHANGED")
    reviews = view["reviews"]
    if not any(r["state"] == "current" and r["trust"] == "locally-recorded" and
               r["decision"] == "approve" for r in reviews):
        _fail("REVIEW_UNVERIFIED")
    if any(r["state"] == "current" and r["decision"] in ("reject", "needs_evidence")
           for r in reviews):
        _fail("REVIEW_UNVERIFIED")
    for ref in revision["payload"]["evidence_refs"]:
        evidence = EvidenceService(store)
        evidence.require_shareable(ref["dataset"])
        if not evidence.is_current(ref):
            _fail("PLAN_CHANGED")


def _live(store, proposal, transport, publisher, *, state_step=False):
    datasets = _enrolled(store, proposal["target"])
    current = transport.current_target(proposal["target"])
    identity = transport.identity()
    if identity.get("publisher") != publisher or identity.get("permitted") is not True:
        _fail("IDENTITY_MISMATCH")
    if current.get("visibility") != "public":
        for dataset in datasets:
            path = confined(store.root, Path("datasets") / dataset / "local" / "suspension.json")
            atomic_json(path, {"schema": "trio.suspension/v1", "dataset": dataset,
                              "at": _now(), "reason": "scope revocation"})
        _fail("PUBLIC_REPO_REQUIRED")
    for key, value in proposal["target"].items():
        if current.get(key) != value:
            _fail("IDENTITY_MISMATCH")
    for key, value in proposal["expected"].items():
        if current.get(key) != value:
            _fail("PLAN_CHANGED")
    if current.get("privacy_blocked") or current.get("suspended"):
        _fail("SHARE_BLOCKED")
    if str(store.config.get("policy_revision", "1")) != proposal["policy_revision"]:
        _fail("PLAN_CHANGED")
    if proposal["finding_digest"] is not None:
        _validate_local_finding(store, proposal["finding_digest"], proposal["target"], proposal["operation"])
    required = "pull_requests" if proposal["target"]["kind"] == "pr" else "issues"
    if current.get("permissions", {}).get(required) != "write":
        _fail("PERMISSION_DENIED")
    _screen(proposal["text"])
    return current


class ActionRejected(Exception):
    """Transport guarantees the remote effect was rejected, not delivered.

    Its message is deliberately never serialized into the journal or output.
    """


def execute(store, operation_id, transport, publisher):
    """The sole remote writer. Every non-idempotent dispatch is journaled first."""
    with _writer_lock(store):
        record = inspect(store, operation_id)
        if record["completed"]:
            return record
        _publisher(store, publisher)
        proposal = record["plan"]
        auth = record["authorization"]
        if not auth or auth.get("digest") != proposal["digest"] or auth.get("publisher") != publisher or auth.get("installation_id") != store.config["installation_id"]:
            _fail("PLAN_UNAUTHORIZED")
        if proposal["operation"] not in store.config.get("enabled_actions", []):
            _fail("ACTION_DISABLED")
        if record["attempted"] or _pending(store, excluding=operation_id):
            _fail("DELIVERY_UNKNOWN", 4)
        for existing in sorted(_directory(store).glob("*.json")):
            if existing.stem == operation_id:
                continue
            prior = inspect(store, existing.stem)
            if (prior["plan"]["target"] == proposal["target"] and
                prior["plan"]["text"] == proposal["text"] and
                prior["steps"]["comment"]["outcome"] == "succeeded"):
                _fail("PRIOR_EFFECT")
        _live(store, proposal, transport, publisher)
        for step in ("comment", "state"):
            status = record["steps"][step]
            if status["outcome"] == "not_requested":
                continue
            # Check again immediately before the later effect. Own comment
            # update timestamps are intentionally outside the preconditions.
            if step == "state":
                try:
                    _live(store, proposal, transport, publisher, state_step=True)
                except Exception:
                    status["outcome"] = "not_sent"
                    status["code"] = "PRECONDITION_CHANGED"
                    record["completed"] = True
                    atomic_json(_path(store, operation_id), record)
                    return record
            record["attempted"] = True
            status.update(outcome="unknown", attempted_at=_now())
            atomic_json(_path(store, operation_id), record)
            try:
                if step == "comment":
                    result = transport.comment(proposal["target"], proposal["text"], operation_id)
                    if type(result.get("comment_id")) is not int or result["comment_id"] <= 0:
                        raise ValueError("invalid transport acknowledgement")
                    status["comment_id"] = result["comment_id"]
                else:
                    result = transport.set_state(proposal["target"], "closed" if proposal["operation"] == "close" else "open")
                    if result.get("state") != ("closed" if proposal["operation"] == "close" else "open"):
                        raise ValueError("invalid transport acknowledgement")
                status["outcome"] = "succeeded"
            except ActionRejected:
                status.update(outcome="failed", code="REMOTE_REJECTED")
            except Exception:
                status.update(outcome="unknown", code="DELIVERY_UNKNOWN")
            atomic_json(_path(store, operation_id), record)
            if status["outcome"] != "succeeded":
                # Never dispatch the state change after a failed/unknown comment.
                record["completed"] = status["outcome"] == "failed"
                atomic_json(_path(store, operation_id), record)
                return record
        record["completed"] = True
        atomic_json(_path(store, operation_id), record)
        return record


def reconcile(store, operation_id, transport):
    """Read-only transport observation; never retry POST/PATCH."""
    with _writer_lock(store):
        record = inspect(store, operation_id)
        if not record["attempted"]:
            return record
        observations = transport.observe(record["plan"], record)
        target = observations.get("target", {})
        if any(target.get(k) != v for k, v in record["plan"]["target"].items()) or observations.get("visibility") != "public":
            _fail("IDENTITY_MISMATCH")
        for step, status in record["steps"].items():
            if status["outcome"] != "unknown":
                continue
            observed = observations.get(step, {})
            # A matching state alone cannot establish which writer changed it;
            # the adapter must supply affirmative operation-linked evidence.
            if observed.get("operation_id") != operation_id or observed.get("confirmed") is not True:
                continue
            if observed.get("outcome") not in ("succeeded", "failed"):
                continue
            if step == "comment" and (
                observed.get("text") != record["plan"]["text"] or
                observed.get("publisher") != record["authorization"]["publisher"] or
                type(observed.get("comment_id")) is not int
            ):
                continue
            status["outcome"] = observed["outcome"]
            status["reconciled_at"] = _now()
            if step == "comment":
                status["comment_id"] = observed["comment_id"]
        record["completed"] = all(s["outcome"] in ("succeeded", "failed", "not_requested") for s in record["steps"].values())
        # A reconciled comment followed by a not-sent closure remains a partial
        # completed attempt. It requires a new exact plan for the remaining step.
        if not any(s["outcome"] == "unknown" for s in record["steps"].values()):
            record["completed"] = True
        atomic_json(_path(store, operation_id), record)
        return record


class FakeTransport:
    """Synthetic in-memory transport; it never opens a network connection."""

    def __init__(self, current, publisher="synthetic-publisher", faults=None):
        self.current = dict(current)
        self.publisher = publisher
        self.faults = dict(faults or {})
        self.calls = []
        self.comments = []
        self.states = []

    def identity(self):
        return {"publisher": self.publisher, "permitted": True}

    def current_target(self, target):
        return dict(self.current)

    def _fault(self, step, when):
        fault = self.faults.get(step)
        if fault == "rejected" and when == "before":
            raise ActionRejected()
        if fault == when:
            raise ConnectionError("synthetic transport uncertainty")

    def comment(self, target, text, operation_id):
        self.calls.append("comment")
        self._fault("comment", "before")
        comment = {"comment_id": len(self.comments) + 1, "text": text,
                   "publisher": self.publisher, "operation_id": operation_id}
        self.comments.append(comment)
        self._fault("comment", "after")
        return {"comment_id": comment["comment_id"]}

    def set_state(self, target, state):
        self.calls.append("state")
        self._fault("state", "before")
        self.current["state"] = state
        self.states.append(state)
        self._fault("state", "after")
        return {"state": state}

    def observe(self, proposal, journal):
        result = {"target": proposal["target"], "visibility": self.current["visibility"]}
        matches = [c for c in self.comments if c["operation_id"] == proposal["operation_id"]]
        if len(matches) == 1:
            result["comment"] = dict(matches[0], confirmed=True, outcome="succeeded")
        # This fake has its own operation history; a live adapter must establish
        # an equivalent linkage instead of guessing from the current state.
        if journal["steps"]["state"]["outcome"] == "unknown" and self.states:
            result["state"] = {"confirmed": True, "outcome": "succeeded",
                               "operation_id": proposal["operation_id"]}
        return result
