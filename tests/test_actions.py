# SPDX-License-Identifier: Apache-2.0
"""Synthetic action authority, uncertainty and recovery tests; no network."""
import copy
import fcntl
import json
from pathlib import Path
import tempfile
import unittest

from trio_triage.actions import (
    FakeTransport, authorize, execute, inspect, plan, reconcile, publisher_ready,
)
from trio_triage.errors import TrioError
from trio_triage.storage import Store, atomic_json

ACTOR = "synthetic-publisher"
TARGET = {"host": "github.com", "repository_id": 101,
          "full_name": "example-org/example-repo", "kind": "issue",
          "number": 42, "item_id": 202}


def finding_item(number=42, database_id=202):
    return {"repository": {"host": TARGET["host"], "full_name": TARGET["full_name"],
                           "database_id": TARGET["repository_id"], "node_id": None},
            "kind": "issue", "number": number, "database_id": database_id,
            "node_id": None}


class ActionsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "state")
        self.store.init({"writes_enabled": True,
                         "enabled_actions": ["comment", "close", "reopen"],
                         "installation_id": "synthetic-installation",
                         "publisher_id": "synthetic-installation",
                         "roles": {ACTOR: ["publisher"]}})
        self.scope = self.store.root / "datasets" / "synthetic" / "scope.json"
        atomic_json(self.scope, {"host": TARGET["host"],
                               "repository_id": TARGET["repository_id"],
                               "full_name": TARGET["full_name"],
                               "visibility": "public"})
        self.current = dict(TARGET, visibility="public", state="open",
                            permissions={"issues": "write", "pull_requests": "write"})
        self.transport = FakeTransport(self.current, ACTOR)

    def proposal(self, operation="close", target=None, expected=None, text="Synthetic reviewed explanation."):
        return plan(self.store, target or TARGET, operation, text,
                    expected or {"state": "open"})

    def approved(self, operation="close", **kwargs):
        proposal = self.proposal(operation, **kwargs)
        authorize(self.store, proposal["operation_id"], proposal["digest"], ACTOR)
        return proposal["operation_id"]

    def assert_code(self, code, fn, *args, **kwargs):
        with self.assertRaises(TrioError) as error:
            fn(*args, **kwargs)
        self.assertEqual(error.exception.code, code)

    def test_default_disabled_and_review_only(self):
        proposal = self.proposal()
        self.store.config["writes_enabled"] = False
        self.assert_code("ACTION_DISABLED", authorize, self.store,
                         proposal["operation_id"], proposal["digest"], ACTOR)
        self.store.config["writes_enabled"] = True
        self.store.config["publisher_id"] = "another-installation"
        self.assert_code("REVIEW_ONLY", authorize, self.store,
                         proposal["operation_id"], proposal["digest"], ACTOR)

    def test_plan_is_exact_without_effect(self):
        p = self.proposal()
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(inspect(self.store, p["operation_id"])["steps"]["comment"]["outcome"], "not_sent")

    def test_inspect_read_only(self):
        p = self.proposal()
        directory = self.store.root / "actions"
        before = {x.name: (x.read_bytes(), x.stat().st_mtime_ns) for x in directory.iterdir()}
        inspect(self.store, p["operation_id"])
        after = {x.name: (x.read_bytes(), x.stat().st_mtime_ns) for x in directory.iterdir()}
        self.assertEqual(before, after)

    def test_no_implicit_initialization(self):
        store = Store(Path(self.temp.name) / "empty")
        self.assert_code("NOT_INITIALIZED", plan, store, TARGET, "comment",
                         "Synthetic text", {"state": "open"})
        self.assertFalse(store.root.exists())

    def test_exact_digest_role_operation(self):
        p = self.proposal()
        self.assert_code("PLAN_CHANGED", authorize, self.store, p["operation_id"], "0" * 64, ACTOR)
        self.assert_code("PUBLISHER_REQUIRED", authorize, self.store, p["operation_id"], p["digest"], "claimed-reviewer")
        self.store.config["enabled_actions"] = []
        self.assert_code("ACTION_DISABLED", authorize, self.store, p["operation_id"], p["digest"], ACTOR)

    def test_unauthorized_never_dispatches(self):
        p = self.proposal()
        self.assert_code("PLAN_UNAUTHORIZED", execute, self.store, p["operation_id"], self.transport, ACTOR)
        self.assertEqual(self.transport.calls, [])

    def test_comment_then_close_and_replay(self):
        op = self.approved()
        first = execute(self.store, op, self.transport, ACTOR)
        self.assertEqual(self.transport.calls, ["comment", "state"])
        self.assertEqual(first["steps"]["comment"]["outcome"], "succeeded")
        self.assertEqual(first["steps"]["state"]["outcome"], "succeeded")
        execute(self.store, op, self.transport, ACTOR)
        self.assertEqual(self.transport.calls, ["comment", "state"])

    def test_comment_only_state_not_requested(self):
        op = self.approved("comment")
        result = execute(self.store, op, self.transport, ACTOR)
        self.assertEqual(self.transport.calls, ["comment"])
        self.assertEqual(result["steps"]["state"]["outcome"], "not_requested")

    def test_comment_unknown_before_and_after_dispatch(self):
        for when in ("before", "after"):
            with self.subTest(when=when):
                # Distinct homes avoid the global pending-attempt guard.
                self.setUp()
                op = self.approved()
                self.transport.faults["comment"] = when
                result = execute(self.store, op, self.transport, ACTOR)
                self.assertEqual(result["steps"]["comment"]["outcome"], "unknown")
                self.assertEqual(result["steps"]["state"]["outcome"], "not_sent")
                self.assertEqual(self.transport.calls, ["comment"])
                self.assert_code("DELIVERY_UNKNOWN", execute, self.store, op, self.transport, ACTOR)
                reconciled = reconcile(self.store, op, self.transport)
                self.assertEqual(reconciled["steps"]["comment"]["outcome"],
                                 "unknown" if when == "before" else "succeeded")
                self.assertEqual(self.transport.calls, ["comment"])

    def test_partial_success_failed_state(self):
        op = self.approved()
        self.transport.faults["state"] = "rejected"
        result = execute(self.store, op, self.transport, ACTOR)
        self.assertEqual(result["steps"]["comment"]["outcome"], "succeeded")
        self.assertEqual(result["steps"]["state"]["outcome"], "failed")
        execute(self.store, op, self.transport, ACTOR)
        self.assertEqual(self.transport.calls, ["comment", "state"])

    def test_state_unknown_reconciliation_never_mutates(self):
        op = self.approved()
        self.transport.faults["state"] = "after"
        result = execute(self.store, op, self.transport, ACTOR)
        self.assertEqual(result["steps"]["state"]["outcome"], "unknown")
        result = reconcile(self.store, op, self.transport)
        self.assertEqual(result["steps"]["state"]["outcome"], "succeeded")
        self.assertEqual(self.transport.calls, ["comment", "state"])

    def test_rejected_comment_no_close(self):
        op = self.approved()
        self.transport.faults["comment"] = "rejected"
        result = execute(self.store, op, self.transport, ACTOR)
        self.assertEqual(result["steps"]["comment"]["outcome"], "failed")
        self.assertEqual(self.transport.calls, ["comment"])

    def test_new_id_and_handover_cannot_escape_uncertainty(self):
        first = self.approved()
        self.transport.faults["comment"] = "after"
        execute(self.store, first, self.transport, ACTOR)
        second = self.proposal(text="A distinct synthetic proposal.")
        self.assert_code("DELIVERY_UNKNOWN", authorize, self.store,
                         second["operation_id"], second["digest"], ACTOR)
        self.assertFalse(publisher_ready(self.store)["ready"])

    def test_repeat_effect_new_id_not_replay_authority(self):
        first = self.approved("comment")
        execute(self.store, first, self.transport, ACTOR)
        second = self.approved("comment")
        self.assert_code("PRIOR_EFFECT", execute, self.store, second, self.transport, ACTOR)
        self.assertEqual(self.transport.calls, ["comment"])

    def test_private_or_drifted_remote_blocks(self):
        for key, value, code in [("visibility", "private", "PUBLIC_REPO_REQUIRED"),
                                 ("item_id", 999, "IDENTITY_MISMATCH"),
                                 ("state", "closed", "PLAN_CHANGED")]:
            with self.subTest(key=key):
                self.setUp()
                op = self.approved()
                self.transport.current[key] = value
                self.assert_code(code, execute, self.store, op, self.transport, ACTOR)
                self.assertEqual(self.transport.calls, [])

    def test_changed_publisher_permission_or_policy_blocks(self):
        op = self.approved()
        self.transport.publisher = "different-publisher"
        self.assert_code("IDENTITY_MISMATCH", execute, self.store, op, self.transport, ACTOR)
        self.transport.publisher = ACTOR
        self.transport.current["permissions"] = {"issues": "read"}
        self.assert_code("PERMISSION_DENIED", execute, self.store, op, self.transport, ACTOR)
        self.transport.current["permissions"] = {"issues": "write"}
        self.store.config["policy_revision"] = "2"
        self.assert_code("PLAN_CHANGED", execute, self.store, op, self.transport, ACTOR)

    def test_merged_pr_reopen_refuses(self):
        target = dict(TARGET, kind="pr")
        self.assert_code("MERGED_PR", self.proposal, "reopen", target=target,
                         expected={"state": "closed", "head_sha": "a" * 40, "merged": True})

    def test_suspension_sensitive_text_and_unsupported(self):
        self.assert_code("ACTION_UNSUPPORTED", self.proposal, "merge")
        synthetic = "gh" + "p_" + "SYNTHETICNONLIVE" * 3
        self.assert_code("SHARE_BLOCKED", self.proposal, text=synthetic)
        scope = json.loads(self.scope.read_bytes())
        scope["suspended"] = True
        atomic_json(self.scope, scope)
        self.assert_code("PUBLIC_REPO_REQUIRED", self.proposal)

    def test_single_writer_lock(self):
        op = self.approved()
        fd = (self.store.root / "actions" / "publisher.lock").open("rb")
        self.addCleanup(fd.close)
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assert_code("PUBLISHER_BUSY", execute, self.store, op, self.transport, ACTOR)

    def test_plan_tamper_path_and_symlink_refuse(self):
        p = self.proposal()
        path = self.store.root / "actions" / (p["operation_id"] + ".json")
        record = json.loads(path.read_bytes())
        record["plan"]["text"] = "Changed."
        atomic_json(path, record)
        self.assert_code("PLAN_CHANGED", inspect, self.store, p["operation_id"])
        self.assert_code("INVALID_OPERATION", inspect, self.store, "../outside")

    def test_reconcile_unattempted_keeps_preview(self):
        p = self.proposal()
        result = reconcile(self.store, p["operation_id"], self.transport)
        self.assertFalse(result["completed"])
        self.assertEqual(self.transport.calls, [])

    def bound_finding(self, category="related", survivor=None):
        from trio_triage.triage import TriageService
        self.store.config["roles"][ACTOR] = ["publisher", "reviewer", "contributor"]
        service = TriageService(self.store)
        finding = service.propose(category, [finding_item(), finding_item(43, 203)],
                                  [], "Synthetic explanation.", ACTOR, survivor=finding_item() if survivor else None)
        digest = finding["payload"]["decision_digest"]
        review = service.review(finding["entity_id"], digest, "approve", ACTOR)
        p = plan(self.store, TARGET, "close", "Synthetic exact explanation.",
                 {"state": "open"}, finding_digest=digest)
        authorize(self.store, p["operation_id"], p["digest"], ACTOR)
        return service, finding, review, p["operation_id"]

    def test_local_approved_finding_can_bind_action(self):
        _, _, _, op = self.bound_finding()
        result = execute(self.store, op, self.transport, ACTOR)
        self.assertTrue(result["completed"])

    def test_changed_local_finding_refuses_old_action(self):
        service, finding, _, op = self.bound_finding()
        service.propose("related", [finding_item(), finding_item(43, 203)],
                        [], "Changed synthetic rationale.", ACTOR,
                        finding_id=finding["entity_id"], parents=[finding["event_id"]])
        self.assert_code("PLAN_CHANGED", execute, self.store, op, self.transport, ACTOR)
        self.assertEqual(self.transport.calls, [])

    def test_withdrawn_local_review_cannot_execute(self):
        service, _, review, op = self.bound_finding()
        service.withdraw(review["event_id"], ACTOR)
        self.assert_code("REVIEW_UNVERIFIED", execute, self.store, op, self.transport, ACTOR)

    def test_duplicate_survivor_cannot_be_closed_under_that_finding(self):
        _, _, _, op = self.bound_finding("duplicate", survivor=TARGET)
        self.assert_code("PLAN_CHANGED", execute, self.store, op, self.transport, ACTOR)

    def test_findings_do_not_bind_foreign_target(self):
        from trio_triage.triage import TriageService
        self.store.config["roles"][ACTOR] = ["publisher", "reviewer", "contributor"]
        service = TriageService(self.store)
        items = [finding_item(44, 204), finding_item(45, 205)]
        finding = service.propose("related", items, [], "Synthetic unrelated finding.", ACTOR)
        digest = finding["payload"]["decision_digest"]
        service.review(finding["entity_id"], digest, "approve", ACTOR)
        p = plan(self.store, TARGET, "comment", "Synthetic exact explanation.",
                 {"state": "open"}, finding_digest=digest)
        authorize(self.store, p["operation_id"], p["digest"], ACTOR)
        self.assert_code("PLAN_CHANGED", execute, self.store, p["operation_id"], self.transport, ACTOR)



if __name__ == "__main__":
    unittest.main()
