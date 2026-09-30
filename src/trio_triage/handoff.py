# SPDX-License-Identifier: Apache-2.0
"""Independent Tranche proposal interoperability; no model or GitHub writer.

An imported checksum establishes local integrity, never source authenticity,
duplicate equivalence, review approval, or permission to execute model text.
"""
import contextlib
import fcntl
import os
from pathlib import Path

from . import contracts as c
from .errors import TrioError
from .storage import atomic_json, confined, digest, read_json
from .team import TeamService, screen
from .evidence.service import EvidenceService
from .search.projections import ProjectionPolicy, project

ENVELOPE = "trio.tranche-handoff/v1"
PROVIDER_ENVELOPE = "trio.tranche-handoff/v2"
MAX_MEMBERS = 100
TRANCHE_COMMIT = "99ffca6dc635d855ed57e87204f9778a300233cd"
TRANCHE_BLOB = "d3ad2664cbcd8e0f83626a72dbd9750252d634d4"
# Reviewed local provider candidate: a tree is not a published upstream commit.
TRANCHE_PROVIDER_TREE = "a6210e2f2313e7608be6f016a675af01aefc6cdf"
TRANCHE_PROVIDER_BLOB = "45ccd80132ff740c96f5b32254385a5b45a8c1f0"
JUDGMENT_NAMES = {"category", "risk", "finished_form", "review_effort", "is_fix", "security_flag", "dupe_signal"}


def validate_provider_observations(value, members):
    """Validate provenance/data shape, never infer quality or grant authority."""
    c.fields(value, ("descriptor", "fingerprint", "judgments", "pairs"))
    descriptor = value["descriptor"]
    c.fields(descriptor, ("adapter", "provider_id", "model", "settings", "capabilities"))
    if descriptor["adapter"] not in ("typesafe-jev/v1", "json-results/v1"):
        raise ValueError()
    for name in ("provider_id", "model"):
        c.text(descriptor[name], name)
        if len(descriptor[name]) > 200 or any(ord(ch) < 32 for ch in descriptor[name]):
            raise ValueError()
    if not isinstance(descriptor["settings"], dict) or len(c.canonical(descriptor).encode()) > 16384:
        raise ValueError()
    capabilities = descriptor["capabilities"]
    c.fields(capabilities, ("judge", "pair"))
    for task, allowed in (("judge", JUDGMENT_NAMES), ("pair", {"sameness"})):
        names = capabilities[task]
        if (not isinstance(names, list) or any(not isinstance(name, str) for name in names)
                or len(set(names)) != len(names) or set(names) - allowed):
            raise ValueError()
    if capabilities["pair"] and "category" not in capabilities["judge"]:
        raise ValueError()
    if value["fingerprint"] != digest(descriptor):
        raise ValueError()
    if (not isinstance(value["judgments"], list) or len(value["judgments"]) > len(members)
            or not isinstance(value["pairs"], list) or len(value["pairs"]) > 10000):
        raise ValueError()
    seen = set()
    for record in value["judgments"]:
        c.fields(record, ("number", "binding", "answers", "resolved_model"))
        c.natural(record["number"], "number", 1)
        c.checked_id(record["binding"])
        if (record["number"] not in members or record["number"] in seen
                or not isinstance(record["answers"], dict) or set(record["answers"]) != JUDGMENT_NAMES
                or any(not isinstance(answer, dict) for answer in record["answers"].values())):
            raise ValueError()
        seen.add(record["number"])
    seen = set()
    for record in value["pairs"]:
        c.fields(record, ("a", "b", "binding", "status", "reason", "verdict", "probabilities", "resolved_model"))
        c.natural(record["a"], "a", 1)
        c.natural(record["b"], "b", 1)
        c.checked_id(record["binding"])
        key = (record["a"], record["b"])
        if record["a"] >= record["b"] or not members.intersection(key) or key in seen:
            raise ValueError()
        seen.add(key)
    # Answer values/reasons remain opaque unverified claims, like relationships.


def sealed(value):
    return dict(value, digest=digest(value))


def pr_identity(raw, repository):
    """Strict selected PR-list metadata, independently rechecked on capture."""
    try:
        if not isinstance(raw, dict):
            raise ValueError()
        identity = {"kind": "pr", "number": raw["number"],
                    "database_id": raw["id"], "node_id": raw.get("node_id")}
        c.validate_item(identity)
        if identity["database_id"] is None:
            raise ValueError()
        revision = {"updated_at": raw["updated_at"], "base_sha": raw["base"]["sha"],
                    "head_sha": raw["head"]["sha"]}
        c.validate_revision(revision)
        if any(v is None for v in revision.values()):
            raise ValueError()
        base = raw["base"]["repo"]
        if (base.get("private") is not False or base.get("visibility", "public") != "public"
                or base.get("id") != repository["database_id"]
                or base.get("full_name") != repository["full_name"]):
            raise ValueError()
        head = raw["head"]["repo"]
        if (not isinstance(head, dict) or head.get("private") is not False
                or head.get("visibility", "public") != "public" or type(head.get("id")) is not int
                or head["id"] < 1 or not isinstance(head.get("full_name"), str)
                or not c.REPO_RE.fullmatch(head["full_name"])):
            raise ValueError()
        if (raw.get("state") != "open" or raw.get("merged") is True
                or raw.get("html_url") != f"https://github.com/{repository['full_name']}/pull/{identity['number']}"
                or not isinstance(raw.get("title"), str) or not raw["title"].strip()
                or len(raw["title"]) > 10000 or type(raw.get("draft")) is not bool):
            raise ValueError()
        return identity, revision
    except (ValueError, KeyError, TypeError):
        raise TrioError("HANDOFF_IDENTITY", "Selected public PR identity or revision is incomplete") from None


def validate_envelope(value):
    try:
        provider_aware = isinstance(value, dict) and value.get("schema") == PROVIDER_ENVELOPE
        required = ("schema", "source", "repository", "batch", "items", "relationships", "digest")
        c.fields(value, (*required, "provider") if provider_aware else required)
        if value["schema"] not in (ENVELOPE, PROVIDER_ENVELOPE) or value["digest"] != digest({k: v for k, v in value.items() if k != "digest"}):
            raise ValueError()
        repository = value["repository"]
        c.validate_repository(repository)
        if repository["host"] != "github.com" or repository["database_id"] is None:
            raise ValueError()
        source = value["source"]
        source_fields = ("tool_blob", "snapshot_digest", "observed_at", "report_binding", "output_digests")
        c.fields(source, (*source_fields, "tool_base_commit", "tool_tree") if provider_aware else (*source_fields, "tool_commit"))
        supported = ((source["tool_base_commit"], source["tool_tree"], source["tool_blob"]) ==
                     (TRANCHE_COMMIT, TRANCHE_PROVIDER_TREE, TRANCHE_PROVIDER_BLOB)) if provider_aware else (
                     (source["tool_commit"], source["tool_blob"]) == (TRANCHE_COMMIT, TRANCHE_BLOB))
        if not supported:
            raise TrioError("HANDOFF_VERSION", "Unsupported Tranche producer version")
        for name in ("snapshot_digest", "report_binding"):
            c.checked_id(source[name])
        c.timestamp(source["observed_at"])
        c.fields(source["output_digests"], ("clusters.json", "dupes.json", "batches.json"))
        for checksum in source["output_digests"].values():
            c.checked_id(checksum)
        c.fields(value["batch"], ("id", "members", "source_digest"))
        c.text(value["batch"]["id"], "batch id")
        c.checked_id(value["batch"]["source_digest"])
        members = value["batch"]["members"]
        if (not isinstance(members, list) or not 1 <= len(members) <= MAX_MEMBERS
                or any(type(n) is not int or n < 1 for n in members) or len(members) != len(set(members))
                or not isinstance(value["items"], list) or len(value["items"]) != len(members)):
            raise ValueError()
        seen = set()
        for raw in value["items"]:
            identity, _ = pr_identity(raw, repository)
            if identity["number"] in seen:
                raise ValueError()
            seen.add(identity["number"])
        if seen != set(members):
            raise ValueError()
        if provider_aware:
            validate_provider_observations(value["provider"], seen)
        relationships = value["relationships"]
        c.fields(relationships, ("confirmed_groups", "review_groups", "uncertain_pairs", "meaning"))
        if any(not isinstance(relationships[key], list) for key in ("confirmed_groups", "review_groups", "uncertain_pairs")):
            raise ValueError()
        # Relationship content remains opaque, explicitly unverified source data.
        c.text(relationships["meaning"], "relationship meaning")
        if len(c.canonical(value).encode()) > 16777216:
            raise TrioError("RESOURCE_LIMIT")
        screen(value)
        return value
    except (ValueError, KeyError, TypeError):
        raise TrioError("HANDOFF_CORRUPT", "Invalid or changed handoff envelope") from None


class _BudgetReader:
    """Only the capture transport's read capabilities, with one run-wide limit."""
    def __init__(self, transport, limit):
        self.transport, self.limit, self.requests = transport, limit, 0
        self.token = getattr(transport, "token", None)

    def call(self, method, *args):
        if self.requests >= self.limit:
            raise TrioError("REQUEST_BUDGET")
        self.requests += 1
        return getattr(self.transport, method)(*args)

    def get(self, path):
        return self.call("get", path)

    def diff(self, path):
        return self.call("diff", path)

    def closing_page(self, node, after=None):
        return self.call("closing_page", node, after)

    def namespace(self):
        return self.call("namespace") if self.token is not None else None


class HandoffService:
    def __init__(self, store):
        self.store = store
        store.require()
        self.evidence = EvidenceService(store)

    def path(self, identifier):
        return confined(self.store.root, Path("handoffs") / (c.checked_id(identifier) + ".json"))

    @contextlib.contextmanager
    def lock(self, identifier):
        path = self.path(identifier).with_suffix(".lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Recheck after changing the suffix, rather than following a planted link.
        path = confined(self.store.root, path.relative_to(self.store.root))
        with path.open("a+b") as stream:
            os.chmod(path, 0o600)
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _save(self, record):
        atomic_json(self.path(record["id"]), sealed({k: v for k, v in record.items() if k != "digest"}))

    def show(self, identifier):
        record = read_json(self.path(identifier))
        if (record.get("schema") != "trio.handoff/v1" or record.get("id") != identifier
                or record.get("digest") != digest({k: v for k, v in record.items() if k != "digest"})):
            raise TrioError("HANDOFF_CORRUPT")
        envelope = validate_envelope(record["envelope"])
        if record["id"] != digest({"dataset": record["dataset"], "actor": record["actor"], "envelope": envelope["digest"]}):
            raise TrioError("HANDOFF_CORRUPT")
        return record

    def prepare(self, dataset, envelope, actor):
        self.store.role(actor, "contributor")
        if not self.store.config["installation_id"]:
            raise TrioError("INVALID_CONFIG", "Handoffs require an explicit local installation identity")
        envelope = validate_envelope(envelope)
        self.evidence.scope(dataset)
        c.same_repository({k: envelope["repository"][k] for k in ("host", "full_name", "database_id", "node_id")},
                          self.evidence.source(dataset).repository)
        self.evidence.require_shareable(dataset)
        identifier = digest({"dataset": dataset, "actor": actor, "envelope": envelope["digest"]})
        with self.lock(identifier):
            if self.path(identifier).exists():
                return dict(self.show(identifier), reused=True)
            record = {"schema": "trio.handoff/v1", "id": identifier, "dataset": dataset,
                      "actor": actor, "envelope": envelope, "profile": "pr-comparison",
                      "captures": {}, "group_id": None, "group_event": None, "snapshot": None,
                      "complete": False, "outcome": "pending", "error": None,
                      "created_at": c.now(), "visibility_basis": "imported public claim; live capture required",
                      "source_trust": "unverified proposal", "requests": 0}
            self._save(record)
            return self.show(identifier)

    def _check_capture(self, record, raw, snapshot):
        manifest = self.evidence.snapshot(record["dataset"], snapshot)
        c.same_repository(record["envelope"]["repository"], manifest["repository"])
        identity, revision = pr_identity(raw, record["envelope"]["repository"])
        if len(manifest["items"]) != 1:
            raise TrioError("HANDOFF_IDENTITY")
        item = manifest["items"][0]
        c.same_item(identity, item["identity"])
        if item["revision"] != revision:
            raise TrioError("REVISION_CHANGED", "PR changed since Tranche selection; export a fresh handoff")
        source = self.evidence.source(record["dataset"])
        summary = c.strict_json(source.object("summary", item["components"]["summary"], "pr"))
        pr_identity(summary, record["envelope"]["repository"])
        if any(raw[side]["repo"].get(key) != summary[side]["repo"].get(key)
               for side in ("base", "head") for key in ("id", "full_name", "node_id")):
            raise TrioError("HANDOFF_IDENTITY", "PR repository scope changed since selection")
        return manifest, item

    def _refs(self, dataset, manifest, item):
        refs = []
        source = self.evidence.source(dataset)
        for name, descriptor in sorted(item["components"].items()):
            if descriptor["object"] is None:
                continue
            payload = source.object(name, descriptor, "pr")
            selected = next(project(name, payload, ProjectionPolicy(max_bytes=512)), None)
            if selected is None:
                continue
            locator, text = selected
            ref = {"schema": "trio.evidence-ref/v1", "dataset": dataset,
                   "repository": manifest["repository"], "identity": item["identity"],
                   "snapshot": manifest["snapshot_id"], "component": name,
                   "object": descriptor["object"], "revision": descriptor["revision"],
                   "locator": locator, "excerpt_sha256": c.digest(text)}
            self.evidence.resolve_ref(ref)
            refs.append(ref)
        return refs

    def run(self, identifier, transport, request_budget=100):
        if type(request_budget) is not int or not 1 <= request_budget <= 10000:
            raise TrioError("RESOURCE_LIMIT")
        with self.lock(identifier):
            record = self.show(identifier)
            self.store.role(record["actor"], "contributor")
            if not self.store.config["installation_id"]:
                raise TrioError("INVALID_CONFIG", "Handoffs require an explicit local installation identity")
            self.evidence.require_shareable(record["dataset"])
            if record["complete"]:
                return dict(record, reused=True, requests=0, visibility_basis="recorded capture; no new live check")
            reader = _BudgetReader(transport, request_budget)
            try:
                snapshots, members, refs = [], [], []
                for raw in record["envelope"]["items"]:
                    key = str(raw["number"])
                    saved = record["captures"].get(key)
                    if not saved or not saved["complete"]:
                        remaining = request_budget - reader.requests
                        if remaining < 1:
                            raise TrioError("REQUEST_BUDGET")
                        result = self.evidence.capture(record["dataset"], "pr", raw["number"], reader,
                                                       profile=record["profile"], budget=remaining)
                        saved = {"snapshot": result["snapshot"], "complete": result["coverage"]["complete"],
                                 "coverage": result["coverage"]}
                        record["captures"][key] = saved
                        self._save(record)
                    manifest, item = self._check_capture(record, raw, saved["snapshot"])
                    if not saved["complete"]:
                        raise TrioError("HANDOFF_NEEDS_EVIDENCE", "Incomplete capture retained; inspect coverage and explicitly resume")
                    snapshots.append(saved["snapshot"])
                    refs.extend(self._refs(record["dataset"], manifest, item))
                    members.append(dict(item["identity"], repository=manifest["repository"], revision=item["revision"],
                                        title=raw["title"], dataset=record["dataset"], snapshot=saved["snapshot"]))
                # Recheck every selected identity/revision immediately before recording a group.
                repo = record["envelope"]["repository"]
                live_repo = reader.get("/repos/" + repo["full_name"])
                if (live_repo.get("private") is not False or live_repo.get("visibility", "public") != "public"
                        or live_repo.get("id") != repo["database_id"] or live_repo.get("full_name") != repo["full_name"]):
                    raise TrioError("PUBLIC_REPO_REQUIRED")
                for raw in record["envelope"]["items"]:
                    live = reader.get(f"/repos/{repo['full_name']}/pulls/{raw['number']}")
                    expected, revision = pr_identity(raw, repo)
                    observed, current = pr_identity(live, repo)
                    c.same_item(expected, observed)
                    if revision != current or any(raw[side]["repo"].get(key) != live[side]["repo"].get(key)
                                                  for side in ("base", "head") for key in ("id", "full_name", "node_id")):
                        raise TrioError("REVISION_CHANGED", "PR changed since Tranche selection; export a fresh handoff")
                combined = self.evidence.combine_snapshots(record["dataset"], snapshots)
                record["snapshot"] = combined["snapshot"]
                record["evidence_refs"] = refs
                group_id = "group-tranche-" + identifier
                team = TeamService(self.store)
                heads = team.heads(group_id)
                notes = "Tranche handoff " + identifier + ". Unverified review candidates; no duplicate, test, merge or publication approval."
                expected_payload = {"members": members, "notes": notes, "assignee": None,
                                    "status": "draft", "author_kind": "agent"}
                if heads:
                    # Recover a crash after the event write; never reset a human-updated group.
                    events = [event for event in team.events() if event["entity_id"] == group_id]
                    initial = [event for event in events if not event["parents"] and event["operation"] == "group"]
                    if (len(initial) != 1 or initial[0]["payload"] != expected_payload
                            or initial[0]["evidence_refs"] != refs
                            or initial[0].get("local_origin") != self.store.config["installation_id"]
                            or not self.store.config["installation_id"]
                            or initial[0]["workspace_id"] != self.store.config["workspace_id"]
                            or initial[0]["actor"] != {"id": record["actor"], "kind": "agent", "trust": "claimed"}):
                        raise TrioError("REVISION_CONFLICT")
                    event = initial[0]
                else:
                    event = team.append(group_id, "group", expected_payload, record["actor"], refs=refs)
                record.update(group_id=group_id, group_event=event["event_id"], complete=True,
                              outcome="complete", error=None, visibility_basis="public revisions checked at recorded capture time")
            except (TrioError, KeyboardInterrupt) as error:
                record.update(complete=False, outcome="stopped", error="CANCELLED" if isinstance(error, KeyboardInterrupt) else error.code)
            except (ValueError, KeyError, TypeError):
                record.update(complete=False, outcome="stopped", error="HANDOFF_CORRUPT")
            record["requests"] = reader.requests
            record["updated_at"] = c.now()
            self._save(record)
            return self.show(identifier)
