# SPDX-License-Identifier: Apache-2.0
"""Production-shaped offline HTTP and CLI operations acceptance fixtures."""
import base64,io,json,os,tempfile,unittest,urllib.error,urllib.parse
from pathlib import Path
from unittest.mock import patch
from trio_triage.storage import Store,read_json,canonical
from trio_triage.operations import GitHubTransport,MaintenanceService,validate_policy
from trio_triage.inventory import InventoryService
from trio_triage.errors import TrioError

TOKEN="offline-credential-canary"
IMAGE="docker.io/library/python@sha256:"+"4"*64
class Response(io.BytesIO):
    def __init__(self,value,status=200,headers=None):super().__init__(canonical(value) if value is not None else b"");self.status=status;self.headers=headers or {}
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
class HTTP:
    def __init__(self):
        self.requests=[];self.fail=None;self.bad=None;self.identity={"id":7,"login":"alice"};self.permissions=True;self.notifications=[{"id":"12","unread":True,"updated_at":"t1","repository":{"id":1,"full_name":"public/project","private":False},"subject":{"title":"private runtime notification","type":"Issue"}}]
        self.repo={"id":1,"full_name":"public/project","private":False,"owner":{"id":1,"login":"public"},"permissions":{"push":True,"triage":True},"fork":False,"default_branch":"main"}
        self.issue={"id":11,"number":1,"state":"open","updated_at":"t1","labels":[],"title":"Fix answer","html_url":"https://github.com/public/project/issues/1"}
        self.pr={"id":22,"node_id":"PR_node","number":2,"state":"open","updated_at":"t1","draft":True,"merged":False,"head":{"sha":"b"*40,"repo":self.repo,"ref":"feature"},"base":{"sha":"a"*40,"repo":self.repo,"ref":"main"}};self.comments=[]
    def open(self,request,timeout=None):
        assert request.full_url.startswith("https://api.github.com/")
        assert request.get_header("Authorization")=="Bearer "+TOKEN
        method=request.get_method();url=urllib.parse.urlsplit(request.full_url);path=url.path;query=urllib.parse.parse_qs(url.query);payload=json.loads(request.data) if request.data else None
        self.requests.append((method,path,query,payload));key=(method,path)
        if self.fail==key:self.fail=None;raise TimeoutError("do not expose credential "+TOKEN)
        value,status,headers=self.route(method,path,query,payload)
        if self.bad==key:value={"id":999,"state":"unexpected"}
        return Response(value,status,headers)
    def missing(self,path):raise urllib.error.HTTPError("https://api.github.com"+path,404,"Not Found",{},None)
    def route(self,method,path,query,payload):
        if path=="/user":return self.identity,200,{"X-OAuth-Scopes":"notifications, repo"}
        if path=="/repos/public/project":return {**self.repo,"permissions":{"push":self.permissions,"triage":self.permissions}},200,{}
        if path.startswith(("/user/repos","/orgs/example/repos")):return [self.repo] if query.get("page")==["1"] else [],200,{}
        if path=="/notifications":return self.notifications if query.get("page")==["1"] else [],200,{}
        if path=="/notifications/threads/12":
            if method=="GET":return self.notifications[0],200,{}
            self.notifications[0]["unread"]=False;return None,205,{}
        if path=="/repos/public/project/issues/1":
            if method=="PATCH":self.issue.update(payload)
            return dict(self.issue),200,{}
        if path=="/repos/public/project/pulls/2":
            if method=="PATCH":self.pr.update(payload)
            return dict(self.pr),200,{}
        if path=="/repos/public/project/issues/1/comments":
            if method=="POST":
                row={"id":100+len(self.comments),"body":payload["body"],"user":self.identity,"issue_url":"https://api.github.com/repos/public/project/issues/1"};self.comments.append(row);return row,201,{}
            return self.comments,200,{}
        if path=="/repos/public/project/issues/1/labels":self.issue["labels"]=[{"name":x} for x in payload["labels"]];return self.issue["labels"],200,{}
        if path=="/repos/public/project/pulls/2/update-branch":return {"message":"Updating pull request branch"},202,{}
        if path=="/repos/public/project/pulls/2/merge":self.pr["merged"]=True;return {"merged":True,"sha":"c"*40},200,{}
        if path=="/graphql":self.pr["draft"]=False;return {"data":{"markPullRequestReadyForReview":{"pullRequest":{"id":"PR_node","isDraft":False}}}},200,{}
        if path=="/repos/public/project/pulls":return [self.pr],200,{}
        if path=="/repos/public/project/issues":return [self.issue,{"id":22,"number":2,"pull_request":{}}],200,{}
        if path=="/repos/public/project/actions/runs":return {"workflow_runs":[{"id":35,"status":"completed","conclusion":"success"}]},200,{}
        if path=="/repos/public/project/releases":return [{"id":44,"tag_name":"v1"}],200,{}
        return self.missing(path)

class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.store=Store(self.root/"state");self.store.init();self.http=HTTP();self.env=patch.dict(os.environ,{"TRIO_TEST_TOKEN":TOKEN});self.env.start();self.addCleanup(self.env.stop);self.transport=GitHubTransport("TRIO_TEST_TOKEN",opener=self.http);self.service=MaintenanceService(self.store)
        self.policy={"revision":"one","maintenance_enabled":True,"publication_enabled":True,"identity_id":7,"actors":{"reviewer":["approver"],"operator":["publisher"]},"repositories":{"public/project":{"repository_id":1,"actions":["notification-ack","issue-label","issue-comment","issue-close","issue-reopen","pr-ready","pr-close","pr-update-branch","pr-merge","contribution-publish"]}},"notifications_enabled":True,"permissions":["notifications:write","issues:write","contents:write","pull_requests:write"],"sandbox_images":[IMAGE]};self.service.configure(self.policy)
    def proposed(self,operation):
        return self.service.plan(self.transport,operation,"public/project",2 if operation.startswith("pr-") else 1,"12" if operation=="notification-ack" else None,text="Reviewed explanation",labels=["bug"])
    def approve(self,plan):return self.service.approve(plan["id"],plan["digest"],"reviewer")
    def test_all_nine_real_endpoint_requests(self):
        for operation in ("notification-ack","issue-label","issue-comment","issue-close","issue-reopen","pr-ready","pr-close","pr-update-branch","pr-merge"):
            with self.subTest(operation=operation):
                self.http.pr.update(state="open",draft=operation!="pr-merge",merged=False)
                plan=self.proposed(operation);self.approve(plan);result=self.service.execute(plan["id"],"operator",self.transport)
                self.assertEqual(result["outcome"],"pending" if operation=="pr-update-branch" else "successful")
                write=[r for r in self.http.requests if r[0]!="GET"][-1]
                if operation=="pr-merge":self.assertEqual(write[3]["sha"],"b"*40)
                if operation=="pr-update-branch":self.assertEqual(write[3]["expected_head_sha"],"b"*40)
                if operation=="notification-ack":self.assertEqual(write[:2],("PATCH","/notifications/threads/12"))
    def test_default_gate_and_approval_and_identity_and_permission(self):
        plan=self.proposed("issue-close");self.approve(plan)
        self.http.identity={"id":8,"login":"other"}
        with self.assertRaisesRegex(TrioError,"."):self.service.execute(plan["id"],"operator",self.transport)
        self.assertFalse(any(r[0]!="GET" for r in self.http.requests))
        self.http.identity={"id":7,"login":"alice"};self.http.permissions=False
        with self.assertRaises(TrioError):self.service.execute(plan["id"],"operator",self.transport)
        self.http.permissions=True;self.service.configure({})
        with self.assertRaises(TrioError):self.service.execute(plan["id"],"operator",self.transport)
    def test_stale_target_and_stale_policy(self):
        plan=self.proposed("issue-comment");self.approve(plan);self.http.issue["updated_at"]="t2"
        with self.assertRaises(TrioError):self.service.execute(plan["id"],"operator",self.transport)
        self.policy["revision"]="two";self.service.configure(self.policy)
        with self.assertRaises(TrioError):self.service.approve(plan["id"],plan["digest"],"reviewer")
    def test_timeout_never_replays_and_reconcile_is_read_only(self):
        plan=self.proposed("issue-comment");self.approve(plan);self.http.fail=("POST","/repos/public/project/issues/1/comments")
        self.assertEqual(self.service.execute(plan["id"],"operator",self.transport)["outcome"],"uncertain")
        with self.assertRaises(TrioError):self.service.execute(plan["id"],"operator",self.transport)
        self.assertEqual(self.service.reconcile(plan["id"],self.transport)["outcome"],"uncertain")
        self.assertEqual(sum(r[0]=="POST" for r in self.http.requests),1)
    def test_bad_mutation_responses_are_uncertain(self):
        for operation,path in (("issue-comment","/repos/public/project/issues/1/comments"),("issue-close","/repos/public/project/issues/1"),("pr-ready","/graphql")):
            with self.subTest(operation=operation):
                plan=self.proposed(operation);self.approve(plan);self.http.bad=("POST" if operation!="issue-close" else "PATCH",path)
                self.assertEqual(self.service.execute(plan["id"],"operator",self.transport)["outcome"],"uncertain");self.http.bad=None
    def test_credentials_cannot_persist_or_echo_in_failure(self):
        with self.assertRaises(TrioError):self.service.plan(self.transport,"issue-comment","public/project",1,text="Do not send "+TOKEN)
        self.assertNotIn(TOKEN,repr(list((self.store.root/"operations").rglob("*.json"))))
        with patch.dict(os.environ,{"TRIO_TEST_TOKEN":'quote"tab\tcredential'}):
            transport=GitHubTransport("TRIO_TEST_TOKEN",opener=self.http)
            with self.assertRaises(TrioError):transport.safe_content({"x":'quote"tab\tcredential'})
    def test_inventory_account_org_and_issue_pr_split(self):
        service=InventoryService(self.store)
        for org in (None,"example"):
            result=service.sync(self.transport,org);self.assertTrue(result["complete"])
            rows=service.list(result["snapshot"],"issues","public/project")["records"];self.assertEqual([x["id"] for x in rows],[11]);self.assertEqual(service.show(result["snapshot"],"public/project")["repository"]["id"],1)
            self.assertEqual((self.store.root/"operations/inventory"/(result["snapshot"]+".json")).stat().st_mode & 0o777,0o600)
    def test_inventory_partial_failure_does_not_delete(self):
        service=InventoryService(self.store);old=service.sync(self.transport);self.http.fail=("GET","/repos/public/project/issues");new=service.sync(self.transport)
        self.assertFalse(new["complete"]);drift=service.drift(old["snapshot"],new["snapshot"])
        self.assertEqual(drift["changes"]["issues:public/project"]["absent"],[]);self.assertFalse(drift["changes"]["issues:public/project"]["comparable"])
    def test_missing_inventory_ids_preserve_partial_reports(self):
        service=InventoryService(self.store)
        old=service.sync(self.transport)
        del self.http.repo["id"]
        new=service.sync(self.transport)
        self.assertFalse(new["complete"])
        drift=service.drift(old["snapshot"],new["snapshot"])
        self.assertFalse(drift["changes"]["repositories"]["comparable"])
        self.assertEqual(drift["changes"]["repositories"]["absent"],[])
        organization=service.sync(self.transport,"example")
        self.assertFalse(organization["complete"])
        self.assertEqual(organization["components"]["repositories"]["error"],"REMOTE_SCHEMA")
        self.assertFalse(organization["components"]["notifications"]["complete"])
    def test_pagination_link_short_page_and_external_link_refusal(self):
        class Pages(HTTP):
            def route(self,method,path,query,payload):
                page=int(query.get("page",["1"])[0]);return [{"id":page}],200,{"Link":'<https://api.github.com/notifications?per_page=50&page=2>; rel="next"'} if page==1 else {}
        transport=GitHubTransport("TRIO_TEST_TOKEN",opener=Pages());result=transport.pages("/notifications")
        self.assertTrue(result["complete"]);self.assertEqual(len(result["records"]),2)
        class Evil(Pages):
            def route(self,*a):return [{"id":1}],200,{"Link":'<https://example.invalid/steal?per_page=50&page=2>; rel="next"'}
        result=GitHubTransport("TRIO_TEST_TOKEN",opener=Evil()).pages("/notifications")
        self.assertFalse(result["complete"]);self.assertEqual(result["error"],"PAGINATION_REFUSED")
    def test_notification_requires_exact_repository_policy(self):
        self.policy["repositories"]={};self.service.configure(self.policy);plan=self.proposed("notification-ack");self.approve(plan)
        with self.assertRaises(TrioError):self.service.execute(plan["id"],"operator",self.transport)
    def test_cli_discovery_and_network_fixture_roundtrip(self):
        from trio_triage.cli import parser,run
        p=parser()
        def invoke(args):return run(p.parse_args(["--home",str(self.store.root),*args]),p)
        with patch("trio_triage.operations.GitHubTransport",return_value=self.transport):
            snapshot=invoke(["inventory","sync","--token-env","TRIO_TEST_TOKEN"])["snapshot"]
            self.assertEqual(invoke(["inventory","list","--snapshot",snapshot])["records"][0]["id"],1)
            plan=invoke(["ops","plan","--operation","issue-close","--repository","public/project","--number","1","--token-env","TRIO_TEST_TOKEN"])
            invoke(["ops","approve","--id",plan["id"],"--digest",plan["digest"],"--actor","reviewer"])
            self.assertEqual(invoke(["ops","execute","--id",plan["id"],"--actor","operator","--token-env","TRIO_TEST_TOKEN"])["outcome"],"successful")
        self.assertLess(len(canonical(invoke(["commands"]))),12000)
        self.assertTrue(invoke(["commands","--command","contribution validate"])["leaves"][0]["arguments"])

    def test_malformed_policy_types_are_deterministic(self):
        for change in ({"actors":{"x":[{}]}},{"permissions":[{}]},{"repositories":{"public/project":{"repository_id":1,"actions":[{}]}}},{"maintenance_enabled":1},{"identity_id":True}):
            with self.subTest(change=change),self.assertRaises(TrioError) as error:validate_policy(change)
            self.assertEqual(error.exception.exit_code,2)
    def test_generic_credential_and_escaped_selected_values_never_persist(self):
        payload="api_key"+"="+"SYNTHETIC_NONLIVE_CANARY_123456789012345"
        with self.assertRaises(TrioError):self.service.plan(self.transport,"issue-comment","public/project",1,text=payload)
        value=self.transport.redact({TOKEN:[TOKEN,{"nested":TOKEN}]})
        self.assertNotIn(TOKEN,json.dumps(value))
        self.assertFalse((self.store.root/"operations/plans").exists())
    def test_private_inventory_never_enters_team_ledger_or_export(self):
        self.http.repo.update(private=True,description="synthetic account-only canary")
        result=InventoryService(self.store).sync(self.transport)
        self.assertIn("synthetic account-only canary",json.dumps(InventoryService(self.store).snapshot(result["snapshot"])))
        from trio_triage.team import TeamService
        self.assertNotIn("synthetic account-only canary",json.dumps(TeamService(self.store).export(ids=[])))
        with self.store.db() as db:self.assertEqual(db.execute("SELECT count(*) FROM events").fetchone()[0],0)
    def test_malformed_repository_is_partial_not_fatal(self):
        class Malformed(HTTP):
            def route(self,method,path,query,payload):
                if path=="/user/repos":return [{"id":3}],200,{}
                return super().route(method,path,query,payload)
        result=InventoryService(self.store).sync(GitHubTransport("TRIO_TEST_TOKEN",opener=Malformed()))
        self.assertFalse(result["complete"]);self.assertEqual(result["components"]["repositories"]["error"],"REMOTE_SCHEMA")
    def test_notifications_exact_50_page_and_budget_never_false_complete(self):
        class Fifty(HTTP):
            def route(self,method,path,query,payload):
                self.asserted=query.get("per_page")==["50"]
                return [{"id":str(x)} for x in range(50)] if query.get("page")==["1"] else [{"id":"50"}],200,{}
        http=Fifty();transport=GitHubTransport("TRIO_TEST_TOKEN",opener=http)
        self.assertEqual(len(transport.pages("/notifications")["records"]),51);self.assertTrue(http.asserted)
        self.assertFalse(transport.pages("/notifications",budget=1)["complete"])
    def test_comment_applied_then_timeout_recovers_only_authenticated_marker(self):
        class Applied(HTTP):
            def open(self,request,timeout=None):
                result=super().open(request,timeout)
                if request.get_method()=="POST":raise TimeoutError("synthetic postdispatch failure")
                return result
        self.http=Applied();self.transport=GitHubTransport("TRIO_TEST_TOKEN",opener=self.http)
        plan=self.proposed("issue-comment");self.approve(plan);self.assertEqual(self.service.execute(plan["id"],"operator",self.transport)["outcome"],"uncertain")
        self.http.comments[0]["user"]={"id":8};self.assertEqual(self.service.reconcile(plan["id"],self.transport)["outcome"],"uncertain")
        self.http.comments[0]["user"]={"id":7};self.assertEqual(self.service.reconcile(plan["id"],self.transport)["outcome"],"successful")
        self.assertEqual(sum(r[0]=="POST" for r in self.http.requests),1)

    def test_cli_rejected_mutation_exits_nonzero(self):
        import sys
        from trio_triage.cli import main
        plan=self.proposed("issue-close");self.approve(plan)
        original=self.http.route
        def denied(method,path,query,payload):
            if method=="PATCH" and path=="/repos/public/project/issues/1":
                raise urllib.error.HTTPError("https://api.github.com"+path,403,"Forbidden",{},None)
            return original(method,path,query,payload)
        self.http.route=denied
        wire=io.BytesIO();output=io.TextIOWrapper(wire,encoding="utf-8")
        with patch("trio_triage.operations.GitHubTransport",return_value=self.transport),patch.object(sys,"stdout",output):
            code=main(["--home",str(self.store.root),"ops","execute","--id",plan["id"],"--actor","operator","--token-env","TRIO_TEST_TOKEN","--json"])
        output.flush();result=json.loads(wire.getvalue())
        self.assertEqual(result["outcome"],"failed")
        self.assertEqual(code,4)
        self.assertEqual(self.http.issue["state"],"open")
        self.assertEqual(self.service.inspect(plan["id"])["journal"]["outcome"],"failed")
