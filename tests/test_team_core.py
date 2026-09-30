# SPDX-License-Identifier: Apache-2.0
import contextlib,copy,hashlib,json,os,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from trio_triage.storage import Store,canonical,digest,read_json,atomic_json,validate_config
from trio_triage.errors import TrioError
from trio_triage.evidence import EvidenceService
from trio_triage.search import SearchService
from trio_triage.team import TeamService
from trio_triage.triage import TriageService
from trio_triage.packets import PacketService
from trio_triage.cli import parser,run
from trio_triage import contracts as c
from test_evidence_search import make_cache,REPOSITORY,START

def config(installation):return {"installation_id":installation,"workspace_id":"synthetic-team","roles":{"alice":["reader","contributor","reviewer","maintainer"],"bob":["reader","contributor","reviewer","maintainer"]}}
def state(root):return {str(p.relative_to(root)):(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}
class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.store=Store(self.root/"a");self.store.init(config("installation-a"))
        self.other=Store(self.root/"b");self.other.init(config("installation-b"))
        self.cache=self.root/"cache";self.manifest,_=make_cache(self.cache)
        scope={"format_version":1,"host":"github.com","repository_id":42,"full_name":"example/triage","visibility":"public","observed_at":START,"profile":None}
        self.dataset=EvidenceService(self.store).enroll(scope)["dataset"]
        EvidenceService(self.other).enroll(scope)
        for s in (self.store,self.other):EvidenceService(s).import_cache(self.dataset,self.cache)
        self.snapshot=self.manifest["snapshot_id"]
        SearchService(self.store).build(self.dataset,self.snapshot)
        result=SearchService(self.store).query(self.dataset,self.snapshot,"suspend",max_bytes=30000)
        self.refs=[i["fragments"][0]["ref"] for i in result["items"][:2]]
        self.items=[dict(r["identity"],repository=REPOSITORY,revision=r["revision"]) for r in self.manifest["items"][:2]]
    def finding(self,**kw):return TriageService(self.store).propose("related",self.items,self.refs,"Synthetic investigation; no semantic verdict", "alice",**kw)
    def test_full_two_installation_review_conflict_and_resolution(self):
        first=self.finding(author_kind="agent");entity=first["entity_id"];decision=first["payload"]["decision_digest"]
        self.assertEqual(TriageService(self.store).show(entity)["reviews"],[])
        review=TriageService(self.store).review(entity,decision,"approve","alice")
        exported=TeamService(self.store).export(ids=[review["event_id"]])
        result=TeamService(self.other).import_bundle_data(exported);self.assertEqual(result["inserted"],2)
        self.assertEqual(TeamService(self.other).import_bundle_data(exported)["inserted"],0)
        shown=TriageService(self.other).show(entity);self.assertEqual(shown["reviews"][0]["trust"],"claimed")
        self.assertFalse(self.other.config["writes_enabled"])
        opposing=TriageService(self.other).review(entity,decision,"reject","bob")
        TeamService(self.store).import_bundle_data(TeamService(self.other).export(ids=[opposing["event_id"]]))
        self.assertTrue(TriageService(self.store).show(entity)["review_conflict"])
        resolution=TeamService(self.store).resolve(entity,[review["event_id"],opposing["event_id"]],"Reviewed both judgments and selected the first","alice",review["event_id"])
        self.assertEqual(set(resolution["parents"]),{review["event_id"],opposing["event_id"]})
        shown=TriageService(self.store).show(entity);self.assertFalse(shown["review_conflict"]);self.assertIn("superseded",{r["state"] for r in shown["reviews"]})
    def test_edit_stales_exact_prior_review(self):
        first=self.finding();TriageService(self.store).review(first["entity_id"],first["payload"]["decision_digest"],"approve","alice")
        updated=TriageService(self.store).propose("different_cause",self.items,self.refs,"Changed judgment", "alice",finding_id=first["entity_id"],parents=[first["event_id"]])
        self.assertNotEqual(first["payload"]["decision_digest"],updated["payload"]["decision_digest"])
        self.assertEqual(TriageService(self.store).show(first["entity_id"])["reviews"][0]["state"],"stale")

    def test_status_uses_one_ledger_read_including_finding_reviews(self):
        triage = TriageService(self.store)
        team = TeamService(self.store)
        conflicted = self.finding()
        entity = conflicted["entity_id"]
        decision = conflicted["payload"]["decision_digest"]
        approve = triage.review(entity, decision, "approve", "alice")
        reject = triage.review(entity, decision, "reject", "bob")
        for _ in range(5):
            finding = self.finding()
            triage.review(
                finding["entity_id"],
                finding["payload"]["decision_digest"],
                "approve",
                "alice",
            )
        for _ in range(100):
            triage.group([], "alice")
        before = state(self.store.root)
        original = TeamService.events
        with patch.object(
            TeamService, "events", autospec=True, side_effect=original
        ) as reads:
            status = team.status()
        self.assertEqual(reads.call_count, 1)
        self.assertEqual(status["events"], 113)
        self.assertEqual(
            status["conflicts"],
            [
                {
                    "entity": entity,
                    "review_heads": sorted([approve["event_id"], reject["event_id"]]),
                }
            ],
        )
        self.assertEqual(before, state(self.store.root))
        triage.withdraw(reject["event_id"], "bob")
        self.assertEqual(team.status()["events"], 114)
        self.assertEqual(team.status()["conflicts"], [])

    def test_scoped_heads_only_decode_selected_entity(self):
        team = TeamService(self.store)
        triage = TriageService(self.store)
        group = triage.group([], "alice")
        for _ in range(20):
            triage.group([], "alice")
        with patch("trio_triage.team.json.loads", wraps=json.loads) as decoded:
            heads = team.heads(group["entity_id"])
        self.assertEqual(heads, [group["event_id"]])
        self.assertEqual(decoded.call_count, 1)

    def test_competing_group_edits_remain_conflicts(self):
        original=TriageService(self.store).group(self.items,"alice")
        TeamService(self.other).import_bundle_data(TeamService(self.store).export(ids=[original["event_id"]]))
        a=TriageService(self.store).group(self.items,"alice",status="needs_review",entity=original["entity_id"],parents=[original["event_id"]])
        b=TriageService(self.other).group(self.items,"bob",status="ready",entity=original["entity_id"],parents=[original["event_id"]])
        TeamService(self.store).import_bundle_data(TeamService(self.other).export(ids=[b["event_id"]]))
        self.assertEqual(len(TeamService(self.store).heads(original["entity_id"])),2)
        resolved=TeamService(self.store).resolve(original["entity_id"],[a["event_id"],b["event_id"]],"Selected explicit ready state","alice",b["event_id"])
        self.assertEqual(resolved["payload"]["status"],"ready");self.assertEqual(len(TeamService(self.store).heads(original["entity_id"])),1)
    def test_expected_revision_refuses_local_lost_update(self):
        first=TriageService(self.store).group(self.items,"alice")
        with self.assertRaises(TrioError) as e:TriageService(self.store).group(self.items,"alice",entity=first["entity_id"],parents=[])
        self.assertEqual(e.exception.code,"REVISION_CONFLICT")
    def test_event_workspace_export_exact_preview_and_idempotence(self):
        first=self.finding();destination=self.root/"team-workspace"
        preview=TeamService(self.store).export_workspace(destination,[first["event_id"]])
        self.assertFalse(destination.exists())
        TeamService(self.store).export_workspace(destination,[first["event_id"]],preview["approval_digest"])
        self.assertTrue((destination/"events"/(first["event_id"]+".json")).is_file())
        self.assertEqual(TeamService(self.other).import_workspace(destination)["inserted"],1)
        self.assertEqual(TeamService(self.other).import_workspace(destination)["inserted"],0)
    def test_suspended_evidence_blocks_selected_and_ancestor_bundle_exports(self):
        first=self.finding();team=TeamService(self.store)
        review=TriageService(self.store).review(first["entity_id"],first["payload"]["decision_digest"],"approve","alice")
        self.assertFalse(review["evidence_refs"])
        self.assertEqual(len(team.export(ids=[review["event_id"]])["events"]),2)
        destination=self.root/"shared-bundle.json";destination.write_bytes(b"preserved synthetic destination")
        EvidenceService(self.store).suspend(self.dataset);before=state(self.store.root)
        for selected in (first,review):
            for path,approve in ((None,False),(destination,True)):
                with self.subTest(event=selected["event_id"],path=path),self.assertRaises(TrioError) as error:
                    team.export(path=path,ids=[selected["event_id"]],approve=approve)
                self.assertEqual(error.exception.code,"SHARE_BLOCKED")
                self.assertEqual(destination.read_bytes(),b"preserved synthetic destination")
                self.assertEqual(state(self.store.root),before)
    def test_suspension_invalidates_workspace_preview_and_exact_prior_approval(self):
        first=self.finding();team=TeamService(self.store)
        review=TriageService(self.store).review(first["entity_id"],first["payload"]["decision_digest"],"approve","alice")
        destination=self.root/"suspended-workspace"
        preview=team.export_workspace(destination,[review["event_id"]])
        EvidenceService(self.store).suspend(self.dataset);before=state(self.store.root)
        for approval in (None,preview["approval_digest"]):
            with self.subTest(approval=approval),self.assertRaises(TrioError) as error:
                team.export_workspace(destination,[review["event_id"]],approval)
            self.assertEqual(error.exception.code,"SHARE_BLOCKED")
            self.assertFalse(destination.exists());self.assertEqual(state(self.store.root),before)
    def bundle_event(self,event,**changes):
        event={k:copy.deepcopy(v) for k,v in event.items() if k not in ("local_origin","trust")}
        event.update(changes);event["payload_digest"]=digest(event["payload"])
        event["event_id"]=digest({k:v for k,v in event.items() if k!="event_id"})
        bundle={"schema":"trio.team-bundle/v1","events":[event]};bundle["digest"]=digest(bundle)
        return bundle
    def test_shared_screen_blocks_decoded_and_structured_credentials(self):
        from trio_triage.team import screen
        canary="NONLIVE"+"PUBLICTESTCANARY123456"
        for key in ("api_key","access_token","password","token","secret"):
            for value in (key+"="+canary,'{"'+key+'":"'+canary+'"}',{"nested":[{key:canary}]}):
                with self.subTest(key=key,value=type(value).__name__),self.assertRaises(TrioError) as error:screen(value)
                self.assertEqual(error.exception.code,"SHARE_BLOCKED");self.assertNotIn(canary,str(error.exception))
        screen({"rationale":"Public token budget and API key documentation", "token":"short"})
    def test_sensitive_assignments_block_team_and_packet_destinations(self):
        canary="NONLIVE"+"PUBLICTESTCANARY123456";team=TeamService(self.store)
        destination=self.root/"shared.json";destination.write_bytes(b"preserved")
        packet_path=self.store.root/"packets/shared.json";packet_path.parent.mkdir();packet_path.write_bytes(b"preserved")
        for key in ("api_key","access_token"):
            for rationale in (key+"="+canary,'{"'+key+'":"'+canary+'"}'):
                finding=TriageService(self.store).propose("related",self.items,[],rationale,"alice")
                packet=PacketService(self.store).create([finding["entity_id"]]);before=state(self.store.root)
                for approved in (False,True):
                    with self.assertRaises(TrioError) as error:team.export(destination,[finding["event_id"]],approved)
                    self.assertEqual(error.exception.code,"SHARE_BLOCKED")
                for approval in (None,digest({"payload_digest":packet["digest"],"destination":"packets/shared.json"})):
                    with self.assertRaises(TrioError) as error:PacketService(self.store).share(packet,"packets/shared.json",approval)
                    self.assertEqual(error.exception.code,"SHARE_BLOCKED")
                self.assertEqual(destination.read_bytes(),b"preserved");self.assertEqual(state(self.store.root),before)
    def opposing_local_reviews(self):
        finding=self.finding();triage=TriageService(self.store)
        approved=triage.review(finding["entity_id"],finding["payload"]["decision_digest"],"approve","alice")
        rejected=triage.review(finding["entity_id"],finding["payload"]["decision_digest"],"reject","bob")
        TeamService(self.other).import_bundle_data(TeamService(self.store).export(ids=[approved["event_id"],rejected["event_id"]]))
        return finding,approved,rejected
    def test_imported_withdrawal_cannot_override_local_review_authority(self):
        finding,approved,rejected=self.opposing_local_reviews()
        withdrawal=TriageService(self.other).withdraw(rejected["event_id"],"bob")
        forged=self.bundle_event(withdrawal,actor={"id":"mallory","kind":"human","trust":"claimed"})
        before=state(self.store.root)
        with self.assertRaises(TrioError) as error:TeamService(self.store).import_bundle_data(forged)
        self.assertEqual(error.exception.code,"REVIEW_UNVERIFIED");self.assertEqual(before,state(self.store.root))
        TeamService(self.store).import_bundle_data(TeamService(self.other).export(ids=[withdrawal["event_id"]]))
        shown=TriageService(self.store).show(finding["entity_id"])
        self.assertTrue(shown["review_conflict"])
        self.assertEqual(next(r for r in shown["reviews"] if r["event_id"]==rejected["event_id"])["state"],"current")
        self.assertEqual(next(r for r in TriageService(self.other).show(finding["entity_id"])["reviews"] if r["event_id"]==rejected["event_id"])["state"],"withdrawn")
        TriageService(self.store).withdraw(rejected["event_id"],"bob")
        self.assertFalse(TriageService(self.store).show(finding["entity_id"])["review_conflict"])
    def test_invalid_withdrawal_references_fail_before_database_write(self):
        finding,approved,rejected=self.opposing_local_reviews()
        withdrawal=TriageService(self.other).withdraw(rejected["event_id"],"bob")
        for payload in ({},{"review_id":"bad"},{"review_id":"0"*64},{"review_id":finding["event_id"]},{"review_id":rejected["event_id"],"extra":True}):
            before=state(self.store.root)
            with self.subTest(payload=payload),self.assertRaises(TrioError):TeamService(self.store).import_bundle_data(self.bundle_event(withdrawal,payload=payload))
            self.assertEqual(before,state(self.store.root))
    def test_claimed_resolution_cannot_supersede_local_rejection(self):
        from trio_triage.actions.service import _validate_local_finding
        finding,approved,rejected=self.opposing_local_reviews()
        resolution=TeamService(self.other).resolve(finding["entity_id"],[approved["event_id"],rejected["event_id"]],"Remote claim selects approval","alice",approved["event_id"])
        TeamService(self.store).import_bundle_data(TeamService(self.other).export(ids=[resolution["event_id"]]))
        shown=TriageService(self.store).show(finding["entity_id"])
        self.assertTrue(shown["review_conflict"])
        self.assertEqual({r["state"] for r in shown["reviews"]},{"current"})
        self.assertEqual(shown["review_resolutions"][0]["state"],"unverified")
        target={"host":"github.com","repository_id":42,"full_name":"example/triage","kind":"issue","number":1,"item_id":1001}
        with self.assertRaises(TrioError):_validate_local_finding(self.store,finding["payload"]["decision_digest"],target,"close")
        local=TeamService(self.store).resolve(finding["entity_id"],[approved["event_id"],rejected["event_id"]],"Local maintainer explicitly selects approval","alice",approved["event_id"])
        shown=TriageService(self.store).show(finding["entity_id"])
        self.assertFalse(shown["review_conflict"])
        self.assertEqual({r["state"] for r in shown["reviews"]},{"current","superseded"})
        self.assertEqual(next(r for r in shown["review_resolutions"] if r["event_id"]==local["event_id"])["state"],"applied")
    def test_malformed_resolution_cannot_change_authority(self):
        finding,approved,rejected=self.opposing_local_reviews()
        resolution=TeamService(self.other).resolve(finding["entity_id"],[approved["event_id"],rejected["event_id"]],"Remote selection","alice",approved["event_id"])
        for changes in ({"entity_id":"review-resolution-wrong"},{"payload":{**resolution["payload"],"selected":"0"*64}},{"parents":[approved["event_id"]]},{"parents":[approved["event_id"],finding["event_id"]]}):
            before=state(self.store.root)
            with self.subTest(changes=changes),self.assertRaises(TrioError):TeamService(self.store).import_bundle_data(self.bundle_event(resolution,**changes))
            self.assertEqual(before,state(self.store.root))
    def test_team_name_cannot_promote_role(self):
        with self.assertRaises(TrioError):TriageService(self.store).review("missing","f"*64,"approve","untrusted-name")
    def test_untrusted_bundle_signer_or_authority_rejected(self):
        first=self.finding();b=TeamService(self.store).export(ids=[first["event_id"]]);b["events"][0]["actor"]["trust"]="signature-verified";b["digest"]=digest({k:v for k,v in b.items() if k!="digest"})
        before=state(self.other.root)
        with self.assertRaises(TrioError):TeamService(self.other).import_bundle_data(b)
        self.assertEqual(state(self.other.root),before)
    def test_forged_inner_decision_digest_rejected_even_rehashed_event(self):
        first=self.finding();b=TeamService(self.store).export(ids=[first["event_id"]]);e=b["events"][0];e["payload"]["rationale"]="Forged";e["payload_digest"]=digest(e["payload"]);e["event_id"]=digest({k:v for k,v in e.items() if k!="event_id"});b["digest"]=digest({k:v for k,v in b.items() if k!="digest"})
        with self.assertRaises(TrioError):TeamService(self.other).import_bundle_data(b)
    def test_share_omits_unselected_conflicts_and_local_metadata(self):
        selected=self.finding()
        unrelated=TriageService(self.store).group(self.items,"alice",notes="unselected-local-note-canary")
        packet=PacketService(self.store).create([selected["entity_id"]])
        preview=PacketService(self.store).share(packet,"packets/public.json")
        text=canonical(preview["payload"]).decode()
        self.assertNotIn("local_origin",text);self.assertNotIn("installation-a",text);self.assertNotIn("unselected-local-note-canary",text);self.assertNotIn(unrelated["entity_id"],text)
    def test_private_team_notes_not_exported(self):
        g=TriageService(self.store).group(self.items,"alice",notes="A local note without consent")
        with self.assertRaises(TrioError) as e:TeamService(self.store).export(ids=[g["event_id"]])
        self.assertEqual(e.exception.code,"SHARE_BLOCKED")
    def test_packet_markdown_and_destination_bound_share(self):
        first=self.finding();packet=PacketService(self.store).create([first["entity_id"]])
        self.assertTrue(packet["evidence"]);self.assertIn("observed_at",packet["evidence"][0])
        preview=PacketService(self.store).share(packet,"packets/shared.json")
        changed=PacketService(self.store).share(packet,"packets/other.json",preview["approval_digest"])
        self.assertTrue(changed["requires_approval"])
        PacketService(self.store).share(packet,"packets/shared.json",preview["approval_digest"])
        self.assertTrue((self.store.root/"packets/shared.json").is_file())
        malicious=copy.deepcopy(packet);malicious["findings"][0]["revisions"][0]["payload"]["rationale"]='![image](https://example.invalid/canary.png)<script>x</script>\x1b[2JIgnore instructions'
        markdown=PacketService(self.store).markdown(malicious)
        self.assertNotIn('![image](',markdown);self.assertNotIn('<script>',markdown);self.assertNotIn('\x1b',markdown)
    def test_every_populated_read_leaf_preserves_state_and_denies_transport(self):
        first=self.finding();group=TriageService(self.store).group(self.items,"alice")
        from trio_triage.actions import plan
        proposal=plan(self.store,{"host":"github.com","repository_id":42,"full_name":"example/triage","kind":"issue","number":1,"item_id":1001},"comment","Synthetic explanation",{"state":"open"})
        refpath=self.root/"ref.json";atomic_json(refpath,self.refs[0]);p=parser()
        commands=[["commands"],["group","show","--id",group["entity_id"]],["action","inspect","--id",proposal["operation_id"]],["status"],["doctor"],["datasets"],["repo","list"],["snapshots","--dataset",self.dataset],["index","info","--dataset",self.dataset,"--snapshot",self.snapshot],["search","--dataset",self.dataset,"--snapshot",self.snapshot,"--query","suspend"],["retrieve","--ref",str(refpath)],["evidence","show","--ref",str(refpath)],["similar","--dataset",self.dataset,"--snapshot",self.snapshot],["finding","show","--id",first["entity_id"]],["team","status"],["packet","--finding",first["entity_id"]],["maintenance","indexes"]]
        before=state(self.store.root)
        with patch("trio_triage.transport.ReadTransport.__init__",side_effect=AssertionError("read local must not resolve credentials")),patch("urllib.request.urlopen",side_effect=AssertionError("network forbidden")),patch("socket.socket",side_effect=AssertionError("network forbidden")):
            for cmd in commands:
                a=p.parse_args(["--home",str(self.store.root),*cmd]);result=run(a,p);self.assertIsInstance(result,dict)
                self.assertEqual(state(self.store.root),before,cmd)
    def test_negative_suppression_exact_repo_revision_pair(self):
        TriageService(self.store).propose("not_duplicate",self.items,self.refs,"Distinct synthetic causes","alice")
        items=[dict(x,title="same symptom") for x in self.items]
        self.assertTrue(TriageService(self.store).similar(items)[0]["suppressed"])
        items[1]["revision"]={**items[1]["revision"],"updated_at":"2026-09-28T12:00:00Z"}
        found=TriageService(self.store).similar(items)[0];self.assertFalse(found["suppressed"]);self.assertTrue(found["negative_stale"])
    def test_source_change_stales_review_but_old_ref_still_resolves(self):
        first=TriageService(self.store).propose("not_duplicate",self.items,self.refs,"Different selected evidence causes","alice");TriageService(self.store).review(first["entity_id"],first["payload"]["decision_digest"],"approve","alice")
        # A newer failed capture must not silently be replaced with earlier complete data.
        manifest=copy.deepcopy(self.manifest);record=next(r for r in manifest["items"] if r["identity"]==self.refs[0]["identity"]);desc=record["components"][self.refs[0]["component"]];desc.update(status="failed",object=None,error="synthetic_failed",expected_count=None,received_count=None,pagination_complete=None)
        manifest.pop("snapshot_id");manifest["completed_at"]="2026-09-29T12:00:00Z";manifest=c.seal_snapshot(manifest)
        payloads={}
        source=EvidenceService(self.store).source(self.dataset)
        for r in manifest["items"]:
            for name,d in r["components"].items():
                if d["object"]:payloads[c.object_name(d["object"])]=source.object(name,d,r["identity"]["kind"])
        EvidenceService(self.store).publish(self.dataset,manifest,payloads)
        self.assertTrue(TriageService(self.store).show(first["entity_id"])["stale"])
        self.assertTrue(EvidenceService(self.store).resolve_ref(self.refs[0])["verified"])
        pair=TriageService(self.store).similar([dict(i,title="same symptom") for i in self.items])[0]
        self.assertFalse(pair["suppressed"]);self.assertTrue(pair["negative_stale"])
    def test_foreign_database_and_future_schema_refusal_readonly(self):
        root=self.root/"foreign";root.mkdir();db=sqlite3.connect(root/"state.sqlite");db.execute("CREATE TABLE unrelated(x)");db.execute("PRAGMA user_version=1");db.close();before=state(root)
        with self.assertRaises(TrioError) as e:Store(root).require()
        self.assertEqual(e.exception.code,"FOREIGN_SCHEMA");self.assertEqual(state(root),before)
    def test_strict_json_and_config_types(self):
        for text in ('{"x":1,"x":2}','{"x":NaN}'):
            path=self.root/"bad.json";path.write_text(text)
            with self.assertRaises(TrioError):read_json(path)
        for conf in ({"enabled_actions":[{}]},{"roles":{"alice":[{}]}},{"writes_enabled":1},{"request_budget":True}):
            with self.assertRaises(TrioError) as e:validate_config(conf)
            self.assertEqual(e.exception.exit_code,2)
    def test_catalog_complete_at_default_budget(self):
        from trio_triage.catalog import catalog,LEAVES
        result=catalog(parser());self.assertEqual({x["command"] for x in result["leaves"]},set(LEAVES));self.assertLessEqual(len(canonical(result))+1,12000)
    def test_safe_store_roots(self):
        import trio_triage.storage
        source=Path(trio_triage.storage.__file__).resolve().parents[3]
        for root in (Path("/"),Path.home(),source,source/"runtime"):
            with self.assertRaises(TrioError):Store(root)

    def test_atomic_initialization_failure_retries_and_validates_before_effect(self):
        store=Store(self.root/"fresh")
        with self.assertRaises(TrioError):store.init({"writes_enabled":1})
        self.assertFalse(store.root.exists())
        with patch("trio_triage.storage.atomic_json",side_effect=OSError("synthetic interruption")):
            with self.assertRaises(OSError):store.init(config("fresh"))
        self.assertFalse(store.root.exists());store.init(config("fresh"));store.require()
    def test_interrupted_workspace_export_is_resumable_and_not_importable(self):
        first=self.finding();destination=self.root/"interrupted";team=TeamService(self.store);preview=team.export_workspace(destination,[first["event_id"]])
        from trio_triage import team as module
        original=module.atomic_json
        def fault(path,data):
            if Path(path).name=="team.json":raise OSError("synthetic interruption")
            return original(path,data)
        with patch("trio_triage.team.atomic_json",side_effect=fault):
            with self.assertRaises(OSError):team.export_workspace(destination,[first["event_id"]],preview["approval_digest"])
        with self.assertRaises(TrioError):TeamService(self.other).import_workspace(destination)
        team.export_workspace(destination,[first["event_id"]],preview["approval_digest"])
        self.assertEqual(TeamService(self.other).import_workspace(destination)["inserted"],1)
    def test_atomic_packet_export_failure_retains_prior_bytes(self):
        first=self.finding();packet=PacketService(self.store).create([first["entity_id"]]);path=self.store.root/"packets/out.json";atomic_json(path,{"prior":"complete"});before=path.read_bytes()
        preview=PacketService(self.store).share(packet,"packets/out.json")
        with patch("trio_triage.storage.os.replace",side_effect=OSError("synthetic interruption")):
            with self.assertRaises(OSError):PacketService(self.store).share(packet,"packets/out.json",preview["approval_digest"])
        self.assertEqual(path.read_bytes(),before)
    def test_frozen_synthetic_eval_honest_not_run_claims(self):
        from trio_triage.evaluation import evaluate
        tasks=json.loads((Path(__file__).parent/"fixtures/synthetic/evaluation-tasks.json").read_text())
        result=evaluate(self.store,self.dataset,self.snapshot,tasks)
        self.assertEqual(len(result["arms"]),3);self.assertTrue(all(a["correct"]==3 for a in result["arms"]))
        self.assertEqual(result["model_evaluation"],"NOT_RUN");self.assertIsNone(result["tokens_per_correct_task"])

    def test_eval_failed_tasks_retained_in_all_task_totals(self):
        from trio_triage.evaluation import evaluate
        tasks=[{"id":"kept-failure","query":"terminal","expected_items":[1,2,3,4]}]
        with patch("trio_triage.evaluation.SearchService.query",side_effect=TrioError("RESOURCE_LIMIT")):
            result=evaluate(self.store,self.dataset,self.snapshot,tasks)
        for arm in result["arms"][1:]:
            self.assertEqual(arm["all_tasks"],1);self.assertEqual(arm["completed"],0);self.assertEqual(arm["correct"],0)
            self.assertEqual(arm["outcomes"][0]["error"],"RESOURCE_LIMIT");self.assertGreater(arm["all_task_totals"]["output_bytes"],0)
    def test_cli_new_offline_dataset_import_without_network(self):
        fresh=Store(self.root/"cli-fresh");fresh.init(config("fresh"));scope=self.root/"scope.json"
        atomic_json(scope,{"format_version":1,"host":"github.com","repository_id":42,"full_name":"example/triage","visibility":"public","observed_at":START,"profile":None})
        p=parser();args=p.parse_args(["--home",str(fresh.root),"import","--scope",str(scope),"--path",str(self.cache)])
        with patch("socket.socket",side_effect=AssertionError("network denied")):result=run(args,p)
        self.assertEqual(result["dataset"],self.dataset);self.assertTrue(result["snapshots"])

    def test_concurrent_local_revision_check_is_inside_commit_lock(self):
        import threading
        original=TriageService(self.store).group(self.items,"alice")
        barrier=threading.Barrier(2);results=[]
        def worker(actor):
            team=TeamService(Store(self.store.root));heads=team.heads
            def sync(entity):
                value=heads(entity)
                if entity==original["entity_id"]:barrier.wait(timeout=5)
                return value
            team.heads=sync
            try:
                team.append(original["entity_id"],"group-update",{"members":self.items,"notes":"","assignee":actor,"status":"needs_review"},actor,[original["event_id"]]);results.append("success")
            except TrioError as error:results.append(error.code)
        threads=[threading.Thread(target=worker,args=(x,)) for x in ("alice","bob")]
        for t in threads:t.start()
        for t in threads:t.join(timeout=10)
        self.assertEqual(sorted(results),["REVISION_CONFLICT","success"])
        self.assertEqual(len(TeamService(self.store).heads(original["entity_id"])),1)
    def test_future_application_schema_refuses_without_modifying_bytes(self):
        with sqlite3.connect(self.store.root/"state.sqlite") as db:db.execute("PRAGMA user_version=2")
        before=state(self.store.root)
        with self.assertRaises(TrioError) as e:self.store.require()
        self.assertEqual(e.exception.code,"SCHEMA_NEWER");self.assertEqual(state(self.store.root),before)

    def test_explicit_team_bundle_ancestor_symlink_escape_refuses(self):
        first=self.finding();real=self.root/"real-destination";real.mkdir();link=self.root/"linked-destination";link.symlink_to(real,target_is_directory=True)
        with self.assertRaises(TrioError) as e:TeamService(self.store).export(link/"bundle.json",[first["event_id"]],True)
        self.assertEqual(e.exception.code,"SCOPE_DENIED");self.assertFalse((real/"bundle.json").exists())
        TeamService(self.store).export(real/"bundle.json",[first["event_id"]],True)
        with self.assertRaises(TrioError) as e:TeamService(self.other).import_bundle(link/"bundle.json")
        self.assertEqual(e.exception.code,"SCOPE_DENIED");self.assertFalse(TeamService(self.other).events())

    def test_author_only_revision_changes_exact_digest(self):
        first=self.finding();later=TriageService(self.store).propose("related",self.items,self.refs,first["payload"]["rationale"],"bob",finding_id=first["entity_id"],parents=[first["event_id"]])
        self.assertNotEqual(first["payload"]["decision_digest"],later["payload"]["decision_digest"])
        with self.assertRaises(TrioError) as e:TriageService(self.store).review(first["entity_id"],first["payload"]["decision_digest"],"approve","alice")
        self.assertEqual(e.exception.code,"PLAN_CHANGED")
