# SPDX-License-Identifier: Apache-2.0
"""Complete offline HTTP contribution publication and constrained sandbox tests."""
import base64,copy,hashlib,json,os,tempfile,unittest,urllib.parse
from pathlib import Path
from unittest.mock import patch
from test_operations import HTTP,Response,TOKEN,IMAGE
import test_operations as fixture
from trio_triage.contributions import ContributionService,PodmanSandbox,git_object,tree_sha,encode_files,decode_files,apply_patch,commit_bytes
from trio_triage.operations import GitHubTransport
from trio_triage.errors import TrioError
from trio_triage import contracts as c
from trio_triage.evidence import EvidenceService
from trio_triage.search import SearchService
from trio_triage.storage import Store,atomic_json,digest
from trio_triage.team import TeamService
from trio_triage.triage import TriageService

PATCH=b"--- a/answer.py\n+++ b/answer.py\n@@ -1 +1 @@\n-answer = 1\n+answer = 2\n"
class Sandbox:
    name="podman-offline/v1"
    def __init__(self,success=True):self.success=success;self.called=0
    def run(self,files,commands,image,**limits):
        self.called+=1
        assert files["answer.py"]["raw"]==b"answer = 2\n"
        return {"backend":self.name,"image":image,"outcomes":[{"command":x,"returncode":0 if self.success else 7,"output":"public synthetic validation","output_bytes":27,"output_sha256":"4"*64} for x in commands],"successful":self.success}
class GitHTTP(HTTP):
    def __init__(self):
        super().__init__();self.base="a"*40;self.files={"answer.py":{"mode":"100644","raw":b"answer = 1\n","sha":git_object("blob",b"answer = 1\n")},"docs/readme.txt":{"mode":"100644","raw":b"Public unchanged file\n","sha":git_object("blob",b"Public unchanged file\n")}}
        self.trees={tree_sha(self.files):copy.deepcopy(self.files)};self.blobs={v["sha"]:v["raw"] for v in self.files.values()};self.commits={self.base:{"sha":self.base,"tree":{"sha":tree_sha(self.files)},"parents":[]}};self.repositories={"public/project":self.repo};self.refs={("public/project","main"):self.base};self.pulls={};self.after_fail=None;self.truncated=False;self.fork_pending=False;self.fork_created=None
    def open(self,request,timeout=None):
        result=super().open(request,timeout)
        if self.after_fail==(request.get_method(),urllib.parse.urlsplit(request.full_url).path):self.after_fail=None;raise TimeoutError("possibly applied; never leak "+TOKEN)
        return result
    def rows(self,files):return [{"path":k,"mode":v["mode"],"type":"blob","sha":v["sha"],"size":len(v["raw"])} for k,v in sorted(files.items())]
    def route(self,method,path,query,payload):
        if path.startswith("/repos/"):
            parts=path.split("/");name="/".join(parts[2:4]);suffix="/"+"/".join(parts[4:])
            if suffix=="/":
                if name not in self.repositories:return self.missing(path)
                return self.repositories[name],200,{}
            if suffix=="/forks" and method=="POST":
                fork={**self.repo,"id":301,"full_name":"alice/project","owner":self.identity,"fork":True,"parent":self.repo};self.fork_created=fork
                if not self.fork_pending:self.repositories["alice/project"]=fork;self.refs[("alice/project","main")]=self.base
                return fork,202,{}
            if suffix.startswith("/git/ref/heads/"):
                branch=suffix[len("/git/ref/heads/"):];oid=self.refs.get((name,branch))
                return ({"ref":"refs/heads/"+branch,"object":{"sha":oid}},200,{}) if oid else self.missing(path)
            if suffix=="/git/refs" and method=="POST":
                branch=payload["ref"].removeprefix("refs/heads/")
                if (name,branch) in self.refs:raise AssertionError("duplicate branch create")
                self.refs[(name,branch)]=payload["sha"];return {"ref":payload["ref"],"object":{"sha":payload["sha"]}},201,{}
            if suffix.startswith("/git/refs/heads/") and method=="PATCH":
                assert payload["force"] is False
                branch=suffix[len("/git/refs/heads/"):];old=self.refs[(name,branch)]
                assert self.commits[payload["sha"]]["parents"][0]["sha"]==old
                self.refs[(name,branch)]=payload["sha"]
                for pr in self.pulls.values():
                    if pr["head"]["ref"]==branch and pr["head"]["repo"]["id"]==self.repositories[name]["id"]:pr["head"]["sha"]=payload["sha"]
                return {"ref":"refs/heads/"+branch,"object":{"sha":payload["sha"]}},200,{}
            if suffix=="/git/blobs" and method=="POST":
                raw=base64.b64decode(payload["content"]);oid=git_object("blob",raw);self.blobs[oid]=raw;return {"sha":oid},201,{}
            if suffix.startswith("/git/blobs/"):
                oid=suffix.split("/")[-1]
                return ({"sha":oid,"encoding":"base64","content":base64.b64encode(self.blobs[oid]).decode()},200,{}) if oid in self.blobs else self.missing(path)
            if suffix=="/git/trees" and method=="POST":
                files=copy.deepcopy(self.trees[payload["base_tree"]])
                for row in payload["tree"]:
                    if row["sha"] is None:del files[row["path"]]
                    else:files[row["path"]]={"mode":row["mode"],"sha":row["sha"],"raw":self.blobs[row["sha"]]}
                oid=tree_sha(files);self.trees[oid]=files;return {"sha":oid,"tree":self.rows(files),"truncated":False},201,{}
            if suffix.startswith("/git/trees/"):
                oid=suffix.split("/")[-1]
                return ({"sha":oid,"tree":self.rows(self.trees[oid]),"truncated":self.truncated},200,{}) if oid in self.trees else self.missing(path)
            if suffix=="/git/commits" and method=="POST":
                author=payload["author"];oid=git_object("commit",commit_bytes(payload["tree"],payload["parents"][0],payload["message"].removesuffix("\n"),author,author["date"]));value={"sha":oid,"tree":{"sha":payload["tree"]},"parents":[{"sha":x} for x in payload["parents"]]};self.commits[oid]=value;return value,201,{}
            if suffix.startswith("/git/commits/"):
                oid=suffix.split("/")[-1];return (self.commits[oid],200,{}) if oid in self.commits else self.missing(path)
            if suffix=="/pulls" and method=="POST":
                owner,branch=payload["head"].split(":",1);destination=owner+"/project";number=50+len(self.pulls);value={"id":number+100,"number":number,"state":"open","user":self.identity,"title":payload["title"],"body":payload["body"],"html_url":"https://github.com/public/project/pull/"+str(number),"head":{"ref":branch,"sha":self.refs[(destination,branch)],"repo":self.repositories[destination]},"base":{"ref":payload["base"],"sha":self.base,"repo":self.repo}};self.pulls[number]=value;return value,201,{}
            if suffix=="/pulls" and query.get("head"):
                owner,branch=query["head"][0].split(":",1);rows=[x for x in self.pulls.values() if x["head"]["ref"]==branch and x["head"]["repo"]["full_name"].split("/")[0]==owner];return rows,200,{}
            if suffix.startswith("/pulls/") and suffix.split("/")[-1].isdigit() and int(suffix.split("/")[-1]) in self.pulls:
                value=self.pulls[int(suffix.split("/")[-1])]
                if method=="PATCH":value.update(payload)
                return value,200,{}
        return super().route(method,path,query,payload)

class ContributionTests(unittest.TestCase):
    def setUp(self):
        fixture.OperationsTests.setUp(self);self.http=GitHTTP();self.transport=GitHubTransport("TRIO_TEST_TOKEN",opener=self.http);self.service=ContributionService(self.store);self.service.configure(self.policy)
    # This subclass exercises the inherited operations tests too, against the same
    # production adapter and a richer synthetic API, not a separate fake writer.
    def prepared(self,mode="direct"):
        if mode=="fork":self.policy["repositories"]["public/project"].update(mode="fork",fork_owner="alice");self.service.configure(self.policy)
        entry=self.service.intake(self.transport,"public/project",1);identifier=entry["id"];self.service.acquire(identifier,self.transport,self.http.base,"main");self.service.patch(identifier,PATCH);self.service.validate(identifier,[["python","-c","assert 2 == 2"]],IMAGE,Sandbox())
        plan=self.service.plan(identifier,self.transport,"trio/"+identifier[:12],"Fix answer","Public reviewed body","Synthetic Human","human@example.invalid",mode=mode);self.service.approve(plan["id"],plan["digest"],"reviewer","publication-plans");return identifier,plan
    def test_direct_and_fork_full_http_publication(self):
        for mode in ("direct","fork"):
            with self.subTest(mode=mode):
                identifier,plan=self.prepared(mode);result=self.service.publish(plan["id"],"operator",self.transport);self.assertEqual(result["outcome"],"successful",result);managed=self.service.get("managed",identifier);self.assertEqual(managed["commit"],plan["commit"]);self.assertEqual(self.http.trees[plan["tree"]]["docs/readme.txt"]["raw"],b"Public unchanged file\n");self.assertEqual(self.service.reconcile(plan["id"],self.transport)["outcome"],"successful")
    def test_each_uncertain_phase_reconciles_without_duplicate_writes(self):
        for phase in ("blobs","trees","commits","refs","pulls"):
            with self.subTest(phase=phase):
                identifier,plan=self.prepared();path="/repos/public/project/"+("git/" if phase!="pulls" else "")+phase;self.http.after_fail=("POST",path);count_before=sum(r[0]=="POST" and r[1]==path for r in self.http.requests)
                result=self.service.publish(plan["id"],"operator",self.transport);self.assertEqual(result["outcome"],"uncertain",result)
                self.assertEqual(self.service.reconcile(plan["id"],self.transport)["outcome"],"recovered")
                result=self.service.publish(plan["id"],"operator",self.transport);self.assertEqual(result["outcome"],"successful",result)
                self.assertEqual(sum(r[0]=="POST" and r[1]==path for r in self.http.requests),count_before+1)
    def test_revision_nonforce_and_refresh_invalidates_seal(self):
        identifier,plan=self.prepared();self.assertEqual(self.service.publish(plan["id"],"operator",self.transport)["outcome"],"successful")
        self.service.patch(identifier,PATCH);self.service.validate(identifier,[["python","-c","pass"]],IMAGE,Sandbox());revision=self.service.plan(identifier,self.transport,plan["branch"],"Fix answer revised","Revised public body","Synthetic Human","human@example.invalid",revision=True);self.service.approve(revision["id"],revision["digest"],"reviewer","publication-plans")
        result=self.service.publish(revision["id"],"operator",self.transport);self.assertEqual(result["outcome"],"successful",result);self.assertEqual(len(self.http.pulls),1)
        request=[x for x in self.http.requests if x[0]=="PATCH" and "/git/refs/" in x[1]][-1];self.assertIs(request[3]["force"],False)
        self.service.refresh(identifier,self.transport,self.http.base,"main")
        with self.assertRaises(TrioError):self.service.sealed(identifier)
    def test_failed_revalidation_cannot_use_prior_seal(self):
        identifier,_=self.prepared()
        with self.assertRaises(TrioError):self.service.validate(identifier,[["python","-c","exit(7)"]],IMAGE,Sandbox(False))
        with self.assertRaises(TrioError):self.service.sealed(identifier)
    def test_path_attacks_patch_failures_and_untrusted_seal(self):
        files=copy.deepcopy(self.http.files)
        for bad in (b"--- a/../escape\n+++ b/../escape\n@@ -1 +1 @@\n-x\n+y\n",b"--- a/answer.py\n+++ b/.git/config\n@@ -1 +1 @@\n-answer = 1\n+danger\n",PATCH.replace(b"answer = 1",b"wrong context")):
            with self.subTest(patch=bad),self.assertRaises(TrioError):apply_patch(files,bad)
        identifier,_=self.prepared();seal=self.service.get("seals",identifier);seal["tree"]="f"*40;self.service.put("seals",identifier,seal)
        with self.assertRaises(TrioError):self.service.sealed(identifier)
    def test_truncated_tree_and_symlink_submodule_refusal(self):
        for mode,kind in (("120000","blob"),("160000","commit")):
            with self.subTest(mode=mode):
                identifier=self.service.intake(self.transport,"public/project",1)["id"]
                original=self.http.rows
                self.http.rows=lambda files,mode=mode,kind=kind:[{"path":"unsafe","mode":mode,"type":kind,"sha":"f"*40,"size":1}]
                with self.assertRaises(TrioError):self.service.acquire(identifier,self.transport,self.http.base,"main")
                self.http.rows=original
        self.http.truncated=True;identifier=self.service.intake(self.transport,"public/project",1)["id"]
        with self.assertRaises(TrioError):self.service.acquire(identifier,self.transport,self.http.base,"main")
    def test_existing_branch_changed_base_identity_and_denied_permission(self):
        identifier,plan=self.prepared();self.http.refs[("public/project",plan["branch"]) ]="f"*40
        with self.assertRaises(TrioError):self.service.plan(identifier,self.transport,plan["branch"],"x","y","Human","human@example.invalid")
        self.assertEqual(self.service.publish(plan["id"],"operator",self.transport)["error"],"BRANCH_EXISTS")
        del self.http.refs[("public/project",plan["branch"])];self.http.refs[("public/project","main") ]="f"*40
        with self.assertRaises(TrioError):self.service.publish(plan["id"],"operator",self.transport)
    def test_async_fork_never_reports_completed_publication(self):
        identifier,plan=self.prepared("fork");self.http.fork_pending=True;result=self.service.publish(plan["id"],"operator",self.transport);self.assertEqual(result["outcome"],"pending")
        self.http.repositories["alice/project"]=self.http.fork_created
        self.assertEqual(self.service.reconcile(plan["id"],self.transport)["outcome"],"recovered")
        self.assertEqual(self.service.publish(plan["id"],"operator",self.transport)["outcome"],"successful")
    def test_cli_end_to_end_with_explicit_sandbox_backend(self):
        from trio_triage.cli import parser,run
        p=parser();body=self.root/"body.txt";body.write_text("Reviewed CLI body");patch_file=self.root/"change.patch";patch_file.write_bytes(PATCH);commands=self.root/"commands.json";commands.write_text('[["python","-c","pass"]]')
        def invoke(args):return run(p.parse_args(["--home",str(self.store.root),*args]),p)
        with patch("trio_triage.operations.GitHubTransport",return_value=self.transport),patch("trio_triage.contributions.PodmanSandbox",return_value=Sandbox()):
            identifier=invoke(["contribution","intake","--repository","public/project","--issue","1","--token-env","TRIO_TEST_TOKEN"])["id"]
            invoke(["contribution","acquire","--id",identifier,"--base",self.http.base,"--base-branch","main","--token-env","TRIO_TEST_TOKEN"])
            invoke(["contribution","patch","--id",identifier,"--path",str(patch_file)])
            invoke(["contribution","validate","--id",identifier,"--commands",str(commands),"--image",IMAGE])
            plan=invoke(["contribution","plan","--id",identifier,"--branch","trio/cli","--title","CLI fix","--body",str(body),"--author-name","Synthetic Human","--author-email","human@example.invalid","--token-env","TRIO_TEST_TOKEN"])
            invoke(["contribution","approve","--id",plan["id"],"--digest",plan["digest"],"--actor","reviewer"])
            self.assertEqual(invoke(["contribution","publish","--id",plan["id"],"--actor","operator","--token-env","TRIO_TEST_TOKEN"])["outcome"],"successful")

    def test_revision_ref_and_pr_uncertainty_resume_same_managed_pr(self):
        for phase in ("ref","pr"):
            with self.subTest(phase=phase):
                identifier,original=self.prepared();self.assertEqual(self.service.publish(original["id"],"operator",self.transport)["outcome"],"successful")
                self.service.patch(identifier,PATCH);self.service.validate(identifier,[["python","-c","pass"]],IMAGE,Sandbox())
                plan=self.service.plan(identifier,self.transport,original["branch"],"Revision "+phase,"Exact revised body","Synthetic Human","human@example.invalid",revision=True);self.service.approve(plan["id"],plan["digest"],"reviewer","publication-plans")
                route="/repos/public/project/git/refs/heads/"+plan["branch"] if phase=="ref" else "/repos/public/project/pulls/"+str(plan["previous_pr"]["number"])
                self.http.after_fail=("PATCH",route);count=sum(r[0]=="PATCH" and r[1]==route for r in self.http.requests)
                self.assertEqual(self.service.publish(plan["id"],"operator",self.transport)["outcome"],"uncertain")
                self.assertEqual(self.service.reconcile(plan["id"],self.transport)["outcome"],"recovered")
                self.assertEqual(self.service.publish(plan["id"],"operator",self.transport)["outcome"],"successful")
                self.assertEqual(sum(r[0]=="PATCH" and r[1]==route for r in self.http.requests),count+1)
    def test_secret_paths_and_commands_and_outputs_are_screened(self):
        generic="api_key"+"="+"SYNTHETIC_NONLIVE_CANARY_123456789012345"
        identifier,plan=self.prepared()
        with self.assertRaises(TrioError):self.service.patch(identifier,PATCH.replace(b"answer = 2",generic.encode()))
        backend=Sandbox()
        with self.assertRaises(TrioError):self.service.validate(identifier,[["python","-c",generic]],IMAGE,backend)
        self.assertEqual(backend.called,0)
        class Output(Sandbox):
            def run(self,*args,**kw):
                result=super().run(*args,**kw);result["outcomes"][0]["output"]=generic;return result
        with self.assertRaises(TrioError):self.service.validate(identifier,[["python","-c","pass"]],IMAGE,Output())
        for path in self.service.root.rglob("*.json"):self.assertNotIn(generic,path.read_text())
        addition=("--- /dev/null\n+++ b/"+TOKEN+".txt\n@@ -0,0 +1 @@\n+public\n").encode()
        self.service.patch(identifier,addition)
        class Any(Sandbox):
            def run(self,files,commands,image,**kw):return {"backend":self.name,"image":image,"successful":True,"outcomes":[{"command":command,"returncode":0,"error":None} for command in commands]}
        self.service.validate(identifier,[["python","-c","pass"]],IMAGE,Any())
        with self.assertRaises(TrioError):self.service.plan(identifier,self.transport,"trio/secretpath","Safe title","Safe body","Human","human@example.invalid")
    def test_source_quota_and_backend_absence_refuse_seals(self):
        identifier=self.service.intake(self.transport,"public/project",1)["id"]
        with self.assertRaises(TrioError):self.service.acquire(identifier,self.transport,self.http.base,"main",request_budget=3)
        self.service.acquire(identifier,self.transport,self.http.base,"main");self.service.patch(identifier,PATCH)
        with patch("trio_triage.contributions.shutil.which",return_value=None),self.assertRaises(TrioError):self.service.validate(identifier,[["python","-c","pass"]],IMAGE)
        with self.assertRaises(TrioError):self.service.sealed(identifier)

    def test_cli_truncated_uncertainty_preserves_failure_status(self):
        import io,sys
        from trio_triage.cli import main
        identifier,plan=self.prepared()
        second=PATCH+b"--- a/docs/readme.txt\n+++ b/docs/readme.txt\n@@ -1 +1 @@\n-Public unchanged file\n+Public reviewed file\n"
        self.service.patch(identifier,second)
        self.service.validate(identifier,[["python","-c","pass"]],IMAGE,Sandbox())
        plan=self.service.plan(identifier,self.transport,plan["branch"],"Fix two files","Reviewed body","Synthetic Human","human@example.invalid")
        self.service.approve(plan["id"],plan["digest"],"reviewer","publication-plans")
        self.http.after_fail=("POST","/repos/public/project/git/refs")
        wire=io.BytesIO();output=io.TextIOWrapper(wire,encoding="utf-8")
        with patch("trio_triage.operations.GitHubTransport",return_value=self.transport),patch.object(sys,"stdout",output):
            code=main(["--home",str(self.store.root),"contribution","publish","--id",plan["id"],"--actor","operator","--token-env","TRIO_TEST_TOKEN","--max-bytes","1024","--json"])
        output.flush();raw=wire.getvalue();result=json.loads(raw)
        self.assertIn("output_truncated",result,result)
        self.assertTrue(result["output_truncated"])
        self.assertEqual(result["outcome"],"uncertain")
        self.assertEqual(result["error"],"WRITE_UNCERTAIN")
        self.assertFalse(result["completed"])
        self.assertEqual(result["identifiers"]["id"],plan["id"])
        self.assertEqual(code,4)
        self.assertLessEqual(len(raw),1024)
        self.assertEqual(self.service.get("publication-journals",plan["id"])["outcome"],"uncertain")


class FindingIntakeTests(unittest.TestCase):
    def setUp(self):
        ContributionTests.setUp(self)
        self.store.config.update(installation_id="synthetic-finding-intake", roles={
            "proposer": ["contributor"], "reviewer": ["reviewer"],
            "other-reviewer": ["reviewer"], "maintainer": ["maintainer"]})
        atomic_json(self.store.root / "config.json", self.store.config)
        self.ev = EvidenceService(self.store)
        self.scope = dict(host="github.com", repository_id=1, full_name="public/project",
            visibility="public", observed_at="2026-09-01T00:00:00Z")
        self.dataset = self.ev.enroll(self.scope)["dataset"]
        self.repository = c.repository("public/project", database_id=1)
        self.manifest = self.snapshot("2026-09-01T00:00:00Z", "Synthetic answer evidence")
        search = SearchService(self.store)
        search.build(self.dataset, self.manifest["snapshot_id"])
        result = search.query(self.dataset, self.manifest["snapshot_id"], "answer", max_bytes=30000)
        self.refs = [item["fragments"][0]["ref"] for item in result["items"]]
        self.assertEqual(len(self.refs), 2)
        self.items = [dict(row["identity"], repository=self.repository, revision=row["revision"])
            for row in self.manifest["items"]]
        self.triage = TriageService(self.store)
        self.network = patch("socket.socket", side_effect=AssertionError("live network forbidden"))
        self.network.start(); self.addCleanup(self.network.stop)

    def snapshot(self, at, body):
        records, payloads = [], {}
        for number in (1, 2):
            revision = dict(updated_at=at, base_sha=None, head_sha=None)
            raw = c.canonical(dict(number=number, kind="issue", state="open",
                title="Synthetic answer " + str(number), body=body,
                html_url="https://github.com/public/project/issues/" + str(number)))
            ref = c.artifact_ref(raw)
            payloads[c.object_name(ref)] = raw
            descriptor = dict(status="complete", fetched_at=at,
                source=dict(transport="rest", resource="/synthetic/" + str(number)),
                revision=revision, expected_count=None, received_count=None,
                pagination_complete=None, truncated=False, error=None, object=ref)
            records.append(dict(identity=dict(kind="issue", number=number,
                database_id=10+number, node_id="I_synthetic_" + str(number)),
                revision=revision, components={"summary": descriptor}))
        manifest = c.seal_snapshot(dict(schema_version=1, artifact="evidence-snapshot",
            repository=self.repository, started_at=at, completed_at=at,
            requested_components=["summary"], items=records))
        self.ev.publish(self.dataset, manifest, payloads)
        return manifest

    def finding(self, **kwargs):
        items = kwargs.pop("items", self.items)
        return self.triage.propose("related", items, self.refs,
            "Synthetic investigation; no publication approval", "proposer", author_kind="agent", **kwargs)

    def intake(self, finding):
        return self.service.intake(self.transport, "public/project", finding=finding)

    def imported_finding(self, change=None):
        original = self.finding()
        event = TeamService(self.store).export(ids=[original["event_id"]])["events"][0]
        event = copy.deepcopy(event)
        event["entity_id"] += "-imported"
        if change is not None:
            change(event)
        payload = event["payload"]
        payload["decision_digest"] = digest({k: v for k, v in payload.items()
            if k not in ("decision_digest", "resolution")})
        event["payload_digest"] = digest(payload)
        event["event_id"] = digest({k: v for k, v in event.items() if k != "event_id"})
        bundle = dict(schema="trio.team-bundle/v1", events=[event])
        bundle["digest"] = digest(bundle)
        TeamService(self.store).import_bundle_data(bundle)
        return event

    def assert_refused(self, finding, code):
        before = self.service.list()
        with self.assertRaises(TrioError) as error:
            self.intake(finding)
        self.assertEqual(error.exception.code, code)
        self.assertEqual(self.service.list(), before)
        self.assertFalse(any(row[0] != "GET" for row in self.http.requests))

    def test_current_agent_finding_enters_queue_through_real_cli(self):
        from trio_triage.cli import parser, run
        finding = self.finding()
        selected = self.triage.show(finding["entity_id"])
        self.assertFalse(selected["stale"])
        self.assertEqual(selected["reviews"], [])
        command = parser()
        args = command.parse_args(["--home", str(self.store.root), "contribution", "intake",
            "--repository", "public/project", "--finding", finding["entity_id"],
            "--token-env", "TRIO_TEST_TOKEN"])
        with patch("trio_triage.operations.GitHubTransport", return_value=self.transport):
            entry = run(args, command)
        self.assertEqual(entry["stage"], "queued")
        self.assertEqual(entry["intake"], dict(kind="finding", finding=finding["entity_id"],
            finding_revision=finding["event_id"], decision_digest=finding["payload"]["decision_digest"],
            selection_digest=digest(selected)))
        self.assertEqual(self.service.show(entry["id"])["intake"], entry["intake"])
        self.assertFalse((self.service.root / "approvals").exists())
        self.assertFalse(any(row[0] != "GET" for row in self.http.requests))

    def test_nonfinding_ledger_entity_cannot_be_intaken_as_a_finding(self):
        group = self.triage.group(self.items, "proposer")
        self.assert_refused(group["entity_id"], "INVALID_TARGET")

    def test_consistent_imported_finding_remains_untrusted_queue_context(self):
        finding = self.imported_finding()
        shown = self.triage.show(finding["entity_id"])
        self.assertEqual(shown["revisions"][0]["trust"], "claimed")
        entry = self.intake(finding["entity_id"])
        self.assertEqual(entry["stage"], "queued")
        self.assertEqual(entry["intake"]["finding_revision"], finding["event_id"])
        self.assertEqual(self.triage.show(finding["entity_id"])["revisions"][0]["trust"], "claimed")
        self.assertFalse((self.service.root / "approvals").exists())

    def test_imported_finding_cannot_hide_citations_or_forge_selection_digests(self):
        for field in ("evidence_refs", "selection_digests"):
            with self.subTest(field=field):
                def change(event):
                    if field == "evidence_refs":
                        event["evidence_refs"] = []
                        event["payload"]["evidence_refs"][0]["repository"].update(
                            full_name="other/project", database_id=999)
                    else:
                        event["payload"]["selection_digests"] = ["f" * 64]
                finding = self.imported_finding(change)
                self.assertFalse(self.triage.show(finding["entity_id"])["stale"])
                self.assert_refused(finding["entity_id"], "EVIDENCE_CORRUPT")

    def test_conflicting_reviews_refuse_even_with_one_finding_revision(self):
        finding = self.finding()
        for actor, decision in (("reviewer", "approve"), ("other-reviewer", "reject")):
            self.triage.review(finding["entity_id"], finding["payload"]["decision_digest"], decision, actor)
        self.assertEqual(len(self.triage.show(finding["entity_id"])["revisions"]), 1)
        self.assert_refused(finding["entity_id"], "CONFLICT")

    def test_conflicting_finding_heads_refuse_until_explicitly_resolved(self):
        first = self.finding()
        peer = Store(self.root / "peer")
        peer.init(dict(self.store.config, installation_id="synthetic-finding-peer"))
        evidence = EvidenceService(peer)
        evidence.enroll(self.scope)
        evidence.import_cache(self.dataset, self.ev.path(self.dataset, "evidence"))
        TeamService(peer).import_bundle_data(TeamService(self.store).export(ids=[first["event_id"]]))
        current = self.finding(finding_id=first["entity_id"], parents=[first["event_id"]])
        other = TriageService(peer).propose("different_cause", self.items, self.refs,
            "Synthetic concurrent proposal", "proposer", finding_id=first["entity_id"], parents=[first["event_id"]])
        TeamService(self.store).import_bundle_data(TeamService(peer).export(ids=[other["event_id"]]))
        self.assert_refused(first["entity_id"], "CONFLICT")
        resolved = TeamService(self.store).resolve(first["entity_id"],
            [current["event_id"], other["event_id"]], "Reviewed synthetic alternatives",
            "maintainer", selected_id=current["event_id"])
        self.assertEqual(self.intake(first["entity_id"])["intake"]["finding_revision"], resolved["event_id"])

    def test_stale_or_missing_source_cannot_start_a_finding_contribution(self):
        finding = self.finding()
        path = self.ev.path(self.dataset, "evidence", "objects", c.object_name(self.refs[0]["object"]))
        raw = path.read_bytes()
        path.unlink()
        self.assert_refused(finding["entity_id"], "PLAN_CHANGED")
        path.write_bytes(raw)
        self.snapshot("2026-09-02T00:00:00Z", "Changed synthetic answer evidence")
        self.assert_refused(finding["entity_id"], "PLAN_CHANGED")

    def test_finding_items_must_match_live_repository_identity(self):
        for changed in (dict(database_id=2), dict(database_id=None),
                dict(full_name="other/project"), dict(host="other.invalid"),
                dict(node_id="R_contradictory_synthetic")):
            with self.subTest(changed=changed):
                items = copy.deepcopy(self.items)
                items[0]["repository"].update(changed)
                finding = self.finding(items=items)
                self.assert_refused(finding["entity_id"], "IDENTITY_MISMATCH")

    def test_source_repository_must_match_even_when_items_claim_target_repository(self):
        for item in self.items:
            item["repository"] = c.repository("public/project", database_id=2)
        other = self.finding()
        self.http.repo["id"] = 2
        self.assert_refused(other["entity_id"], "IDENTITY_MISMATCH")

    def test_finding_review_does_not_replace_exact_publication_approval(self):
        finding = self.finding()
        self.triage.review(finding["entity_id"], finding["payload"]["decision_digest"], "approve", "reviewer")
        identifier = self.intake(finding["entity_id"])["id"]
        self.service.acquire(identifier, self.transport, self.http.base, "main")
        self.service.patch(identifier, PATCH)
        self.service.validate(identifier, [["python", "-c", "pass"]], IMAGE, Sandbox())
        plan = self.service.plan(identifier, self.transport, "trio/finding", "Synthetic fix",
            "Public reviewed body", "Synthetic Human", "human@example.invalid")
        with self.assertRaises(TrioError):
            self.service.publish(plan["id"], "operator", self.transport)
        self.assertFalse(any(row[0] != "GET" for row in self.http.requests))
        self.service.approve(plan["id"], plan["digest"], "reviewer", "publication-plans")
        self.assertEqual(self.service.publish(plan["id"], "operator", self.transport)["outcome"], "successful")
