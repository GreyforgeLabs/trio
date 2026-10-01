# SPDX-License-Identifier: Apache-2.0
"""Explicit GitHub operations transport and durable, plan-bound maintenance.

Credentials exist only in the selected transport. Plans/journals never contain
credentials. Repository text and remote identities do not grant local roles.
"""
import base64,datetime,hashlib,os,re,urllib.error,urllib.parse,urllib.request,uuid
from .errors import TrioError
from .contracts import strict_json
from .storage import atomic_json,canonical,confined,digest,read_json

REPO=re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
SHA=re.compile(r"[0-9a-f]{40}")
MAX_OPERATION_RECORD_BYTES=134217728
OPERATIONS={"notification-ack","issue-label","issue-comment","issue-close","issue-reopen","pr-ready","pr-close","pr-update-branch","pr-merge","contribution-publish"}
PERMISSIONS={"notification-ack":"notifications:write","issue-label":"issues:write","issue-comment":"issues:write","issue-close":"issues:write","issue-reopen":"issues:write","pr-ready":"pull_requests:write","pr-close":"pull_requests:write","pr-update-branch":"contents:write","pr-merge":"contents:write","contribution-publish":"contents:write"}

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00","Z")
def repo_name(value):
    if not isinstance(value,str) or not REPO.fullmatch(value) or any(part in {".",".."} for part in value.split("/")):raise TrioError("INVALID_TARGET",exit_code=2)
    return value

def sha(value):
    if not isinstance(value,str) or not SHA.fullmatch(value):raise TrioError("INVALID_TARGET",exit_code=2)
    return value

def safe_id(value):
    if not isinstance(value,str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}",value):raise TrioError("INVALID_TARGET",exit_code=2)
    return value

def integer(value):
    if type(value) is not int or value<1:raise TrioError("INVALID_TARGET",exit_code=2)
    return value

class GitHubTransport:
    """Fixed HTTPS origin, no redirects, retries, helpers, or arbitrary requests.

    ``opener`` is an injectable offline HTTP fixture. It never changes the origin.
    Authorization is resolved only when this adapter is explicitly instantiated.
    """
    def __init__(self,token_env,timeout=45,opener=None):
        if not isinstance(token_env,str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}",token_env):raise TrioError("CREDENTIAL_REQUIRED",exit_code=2)
        token=os.environ.get(token_env)
        if not token or any(c in token for c in "\r\n"):raise TrioError("CREDENTIAL_REQUIRED",exit_code=2)
        self._token=token;self.timeout=timeout;self.last_headers={};self.last_status=None
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*a,**k):raise TrioError("TRANSPORT_REDIRECT",exit_code=4)
        self.opener=opener or urllib.request.build_opener(NoRedirect)
    def safe_content(self,value):
        def inspect(item):
            if isinstance(item,str) and self._token in item:raise TrioError("CREDENTIAL_CONTENT",exit_code=2)
            if isinstance(item,dict):
                for key,child in item.items():inspect(key);inspect(child)
            if isinstance(item,list):
                for child in item:inspect(child)
        inspect(value)
        from .team import screen
        screen(value)
        return value
    def redact(self,value):
        if isinstance(value,str):return value.replace(self._token,"[REDACTED]")
        if isinstance(value,list):return [self.redact(x) for x in value]
        if isinstance(value,dict):return {self.redact(k):self.redact(v) for k,v in value.items()}
        return value
    def request(self,method,path,payload=None):
        if method not in {"GET","POST","PATCH","PUT","DELETE"} or not isinstance(path,str) or not re.fullmatch(r"/[A-Za-z0-9_./%?=&,+~-]+",path) or ".." in path or "%2f" in path.lower() or "%5c" in path.lower():raise TrioError("INVALID_TARGET",exit_code=2)
        if not (path=="/user" or path=="/graphql" or path.startswith(("/user/","/orgs/","/repos/","/notifications"))):raise TrioError("INVALID_TARGET",exit_code=2)
        req=urllib.request.Request("https://api.github.com"+path,method=method,
            data=canonical(payload) if payload is not None else None,
            headers={"User-Agent":"trio/0.2.0","Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28","Authorization":"Bearer "+self._token,**({"Content-Type":"application/json"} if payload is not None else {})})
        try:
            with self.opener.open(req,timeout=self.timeout) as response:
                self.last_headers=dict(response.headers.items());self.last_status=response.status;raw=response.read(67108865)
                if len(raw)>67108864:raise TrioError("RESOURCE_LIMIT")
                return self.redact(strict_json(raw.decode("utf-8"))) if raw.strip() else None
        except urllib.error.HTTPError as error:
            # Status proves a server refusal, unlike an I/O failure after dispatch.
            if error.code in {401,403}:code="PERMISSION_DENIED"
            elif error.code==404:code="TARGET_MISSING"
            elif error.code in {409,422}:code="PRECONDITION_FAILED"
            elif error.code==429:code="THROTTLED"
            else:code="WRITE_UNCERTAIN" if method!="GET" else "REMOTE_FAILURE"
            raise TrioError(code,exit_code=4) from None
        except TrioError as failure:
            if method!="GET" and failure.code not in {"PERMISSION_DENIED","TARGET_MISSING","PRECONDITION_FAILED","THROTTLED"}:raise TrioError("WRITE_UNCERTAIN",exit_code=4) from None
            raise
        except (OSError,TimeoutError,ValueError,UnicodeError):
            raise TrioError("WRITE_UNCERTAIN" if method!="GET" else "TRANSPORT_FAILURE",exit_code=4) from None
    def get(self,path):return self.request("GET",path)
    def identity(self):
        user=self.get("/user")
        if not isinstance(user,dict) or type(user.get("id")) is not int or user["id"]<1 or not isinstance(user.get("login"),str):raise TrioError("IDENTITY_MISMATCH")
        return {"id":user["id"],"login":user["login"]}
    def repository(self,repository,public=False):
        data=self.get("/repos/"+repo_name(repository))
        if not isinstance(data,dict) or type(data.get("id")) is not int or data["id"]<1 or data.get("full_name","").lower()!=repository.lower() or type(data.get("private")) is not bool:raise TrioError("IDENTITY_MISMATCH")
        if public and data["private"]:raise TrioError("PUBLIC_REPO_REQUIRED")
        return data
    def pages(self,path,limit=1000,budget=100):
        if type(limit) is not int or not 1<=limit<=100000 or type(budget) is not int or not 1<=budget<=10000:raise TrioError("INVALID_INVOCATION",exit_code=2)
        result=[];page=1;complete=False;error=None;calls=0
        page_size=50 if path.startswith("/notifications") else 100
        try:
            while calls<budget:
                calls+=1;rows=self.get(path+("&" if "?" in path else "?")+"per_page="+str(page_size)+"&page="+str(page))
                if isinstance(rows,dict):rows=rows.get("workflow_runs")
                if not isinstance(rows,list) or any(not isinstance(x,dict) for x in rows):raise TrioError("REMOTE_SCHEMA",exit_code=4)
                take=min(len(rows),limit-len(result));result.extend(rows[:take])
                link=self.last_headers.get("Link",self.last_headers.get("link",""));next_page=None
                for part in link.split(","):
                    if 'rel="next"' not in part:continue
                    match=re.fullmatch(r'\s*<([^>]+)>;\s*rel="next"\s*',part)
                    if not match:raise TrioError("PAGINATION_REFUSED",exit_code=4)
                    url=urllib.parse.urlsplit(match[1]);expected=urllib.parse.urlsplit("https://api.github.com"+path)
                    query=urllib.parse.parse_qs(url.query);original=urllib.parse.parse_qs(expected.query)
                    if url.scheme!="https" or url.netloc!="api.github.com" or url.path!=expected.path or url.fragment or any(query.get(k)!=v for k,v in original.items()) or set(query)-set(original)-{"page","per_page"} or query.get("per_page")!=[str(page_size)] or len(query.get("page",[]))!=1:raise TrioError("PAGINATION_REFUSED",exit_code=4)
                    try:next_page=int(query["page"][0])
                    except ValueError:raise TrioError("PAGINATION_REFUSED",exit_code=4) from None
                    if next_page!=page+1:raise TrioError("PAGINATION_REFUSED",exit_code=4)
                if take<len(rows):break
                if next_page is None and (link or len(rows)<page_size):complete=True;break
                if len(result)>=limit:break
                page=next_page or page+1
        except TrioError as failure:error=failure.code
        return {"records":result,"complete":complete,"error":error,"requests":calls,"observed_at":now()}

DEFAULT_POLICY={"schema":"trio.operations-policy/v1","revision":"1","maintenance_enabled":False,"publication_enabled":False,"identity_id":None,"actors":{},"repositories":{},"notifications_enabled":False,"permissions":[],"sandbox_images":[]}
def validate_policy(value):
    if not isinstance(value,dict) or set(value)-set(DEFAULT_POLICY):raise TrioError("INVALID_POLICY",exit_code=2)
    p={**DEFAULT_POLICY,**value}
    if p["schema"]!="trio.operations-policy/v1" or not isinstance(p["revision"],str) or not p["revision"] or any(type(p[k]) is not bool for k in ("maintenance_enabled","publication_enabled","notifications_enabled")):raise TrioError("INVALID_POLICY",exit_code=2)
    if p["identity_id"] is not None:integer(p["identity_id"])
    if not isinstance(p["actors"],dict) or any(not isinstance(k,str) or not k or not isinstance(v,list) or any(not isinstance(x,str) or x not in {"approver","publisher"} for x in v) for k,v in p["actors"].items()):raise TrioError("INVALID_POLICY",exit_code=2)
    if not isinstance(p["repositories"],dict):raise TrioError("INVALID_POLICY",exit_code=2)
    for name,rule in p["repositories"].items():
        repo_name(name)
        if not isinstance(rule,dict) or set(rule)-{"repository_id","actions","mode","fork_owner"} or type(rule.get("repository_id")) is not int or rule["repository_id"]<1 or not isinstance(rule.get("actions"),list) or any(not isinstance(x,str) or x not in OPERATIONS for x in rule["actions"]) or not isinstance(rule.get("mode","direct"),str) or rule.get("mode","direct") not in {"direct","fork"} or "fork_owner" in rule and (not isinstance(rule["fork_owner"],str) or not re.fullmatch(r"[A-Za-z0-9-]{1,39}",rule["fork_owner"])):raise TrioError("INVALID_POLICY",exit_code=2)
    if not isinstance(p["permissions"],list) or any(not isinstance(x,str) or x not in set(PERMISSIONS.values())|{"pull_requests:write"} for x in p["permissions"]):raise TrioError("INVALID_POLICY",exit_code=2)
    if not isinstance(p["sandbox_images"],list) or any(not isinstance(x,str) or not re.fullmatch(r"[a-zA-Z0-9._:/-]+@sha256:[0-9a-f]{64}",x) for x in p["sandbox_images"]):raise TrioError("INVALID_POLICY",exit_code=2)
    return p

class OperationState:
    def __init__(self,store):self.store=store;self.root=confined(store.root,"operations")
    def policy(self):
        path=self.root/"policy.json"
        return validate_policy(read_json(path)) if path.exists() else validate_policy({})
    def configure(self,value):
        policy=validate_policy(value)
        with self.store.write_lock():atomic_json(self.root/"policy.json",policy)
        return {"schema":"trio.operations-policy/v1","policy":policy,"digest":digest(policy)}
    def put(self,kind,identifier,value):atomic_json(confined(self.root,kind+"/"+safe_id(identifier)+".json"),value)
    def get(self,kind,identifier):return read_json(confined(self.root,kind+"/"+safe_id(identifier)+".json"),max_bytes=MAX_OPERATION_RECORD_BYTES)
    def gate(self,plan,actor,transport,publication=False):
        policy=self.policy();roles=policy["actors"].get(actor,[])
        if not policy["publication_enabled" if publication else "maintenance_enabled"] or "publisher" not in roles:raise TrioError("GATE_CLOSED")
        if plan["policy_digest"]!=digest(policy):raise TrioError("STALE_APPROVAL")
        identity=transport.identity()
        if identity!=plan["identity"] or identity["id"]!=policy["identity_id"]:raise TrioError("IDENTITY_CHANGED")
        action=plan["operation"]
        if PERMISSIONS[action] not in policy["permissions"]:raise TrioError("PERMISSION_DENIED",exit_code=4)
        if action=="notification-ack" and not policy["notifications_enabled"]:raise TrioError("GATE_CLOSED")
        rule=policy["repositories"].get(plan["repository"])
        if not rule or action not in rule["actions"] or rule["repository_id"]!=plan["repository_id"]:raise TrioError("GATE_CLOSED")
        return policy
    def approve(self,identifier,expected,actor,kind="plans"):
        with self.store.write_lock():
            plan=self.get(kind,identifier);policy=self.policy()
            if "approver" not in policy["actors"].get(actor,[]):raise TrioError("SCOPE_DENIED")
            if plan["digest"]!=expected or digest({k:v for k,v in plan.items() if k!="digest"})!=expected or plan["policy_digest"]!=digest(policy):raise TrioError("STALE_APPROVAL")
            receipt={"schema":"trio.operation-approval/v1","plan":identifier,"plan_digest":expected,"policy_digest":digest(policy),"actor":actor,"approved_at":now()}
            self.put("approvals",identifier,receipt)
            return receipt
    def require_approval(self,plan):
        receipt=self.get("approvals",plan["id"])
        if receipt["plan_digest"]!=plan["digest"] or receipt["policy_digest"]!=plan["policy_digest"] or "approver" not in self.policy()["actors"].get(receipt["actor"],[]):raise TrioError("STALE_APPROVAL")
    def check_plan(self,plan):
        if digest({k:v for k,v in plan.items() if k!="digest"})!=plan.get("digest"):raise TrioError("PLAN_CORRUPT")

class MaintenanceService(OperationState):
    def observe(self,transport,operation,repository=None,number=None,thread=None):
        if operation=="notification-ack":
            if not isinstance(thread,str) or not re.fullmatch(r"[0-9]{1,32}",thread):raise TrioError("INVALID_TARGET",exit_code=2)
            item=transport.get("/notifications/threads/"+thread)
            if not isinstance(item,dict) or str(item.get("id"))!=thread:raise TrioError("IDENTITY_MISMATCH")
            selected=item.get("repository",{});name=repo_name(selected.get("full_name"));repo=transport.repository(name)
            if repo["id"]!=selected.get("id"):raise TrioError("IDENTITY_MISMATCH")
            return {"thread":thread,"unread":item.get("unread"),"updated_at":item.get("updated_at"),"repository_id":repo["id"],"repository":name},repo,item
        repo=transport.repository(repo_name(repository));integer(number)
        item=transport.get("/repos/"+repository+("/pulls/" if operation.startswith("pr-") else "/issues/")+str(number))
        if not isinstance(item,dict) or type(item.get("id")) is not int or item.get("number")!=number or not operation.startswith("pr-") and item.get("pull_request"):raise TrioError("IDENTITY_MISMATCH")
        target={"repository_id":repo["id"],"item_id":item["id"],"number":number,"state":item.get("state"),"updated_at":item.get("updated_at")}
        if operation.startswith("pr-"):target.update(head=item.get("head",{}).get("sha"),base=item.get("base",{}).get("sha"),draft=item.get("draft"),merged=item.get("merged"),node_id=item.get("node_id"))
        if operation=="issue-label":target["labels"]=sorted(x["name"] for x in item.get("labels",[]) if isinstance(x,dict) and isinstance(x.get("name"),str))
        return target,repo,item
    def plan(self,transport,operation,repository=None,number=None,thread=None,text=None,labels=None,merge_method="merge"):
        if operation not in OPERATIONS-{"contribution-publish"}:raise TrioError("INVALID_INVOCATION",exit_code=2)
        identity=transport.identity();target,repo,item=self.observe(transport,operation,repository,number,thread)
        identifier=uuid.uuid4().hex;params={}
        if operation=="issue-comment":
            if not isinstance(text,str) or not 1<=len(text.encode())<=60000:raise TrioError("INVALID_INVOCATION",exit_code=2)
            params["body"]=text+"\n\n<!-- trio-operation:"+identifier+" -->"
        if operation=="issue-label":
            if not isinstance(labels,list) or len(labels)>100 or any(not isinstance(x,str) or not 1<=len(x)<=100 for x in labels) or len(set(labels))!=len(labels):raise TrioError("INVALID_INVOCATION",exit_code=2)
            params["labels"]=labels
        if operation=="pr-merge":
            if merge_method not in {"merge","squash","rebase"} or target["state"]!="open" or target["draft"] or target["merged"]:raise TrioError("PRECONDITION_FAILED")
            params={"sha":sha(target["head"]),"merge_method":merge_method}
        if operation=="pr-update-branch":params={"expected_head_sha":sha(target["head"])}
        if operation=="pr-ready" and (not target["draft"] or target["state"]!="open"):raise TrioError("PRECONDITION_FAILED")
        transport.safe_content(params)
        if operation=="notification-ack":repository=target["repository"]
        plan={"schema":"trio.maintenance-plan/v1","id":identifier,"operation":operation,"identity":identity,"repository":repository,"repository_id":repo["id"] if repo else target["repository_id"],"target":target,"parameters":params,"policy_digest":digest(self.policy()),"created_at":now()}
        plan["digest"]=digest(plan)
        with self.store.write_lock():self.put("plans",identifier,plan)
        return plan
    def inspect(self,identifier):
        plan=self.get("plans",identifier);self.check_plan(plan)
        path=confined(self.root,"journals/"+safe_id(identifier)+".json")
        return {"schema":"trio.maintenance-inspect/v1","plan":plan,"journal":read_json(path) if path.exists() else None}
    def permissions(self,repo,operation):
        if repo is None:return
        permissions=repo.get("permissions",{})
        accepted=("admin","maintain","push") if operation.startswith("pr-") else ("admin","maintain","push","triage")
        if not isinstance(permissions,dict) or not any(permissions.get(k) is True for k in accepted):raise TrioError("PERMISSION_DENIED",exit_code=4)
    def dispatch(self,transport,plan):
        operation=plan["operation"];target=plan["target"];params=plan["parameters"]
        if operation=="notification-ack":return transport.request("PATCH","/notifications/threads/"+target["thread"])
        prefix="/repos/"+plan["repository"]
        if operation=="issue-comment":return transport.request("POST",prefix+"/issues/"+str(target["number"])+"/comments",params)
        if operation=="issue-label":return transport.request("PUT",prefix+"/issues/"+str(target["number"])+"/labels",params)
        if operation in {"issue-close","issue-reopen","pr-close"}:return transport.request("PATCH",prefix+("/pulls/" if operation.startswith("pr-") else "/issues/")+str(target["number"]),{"state":"open" if operation=="issue-reopen" else "closed"})
        if operation=="pr-update-branch":return transport.request("PUT",prefix+"/pulls/"+str(target["number"])+"/update-branch",params)
        if operation=="pr-merge":return transport.request("PUT",prefix+"/pulls/"+str(target["number"])+"/merge",params)
        if operation=="pr-ready":
            response=transport.request("POST","/graphql",{"query":"mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id}){pullRequest{id isDraft}}}","variables":{"id":target["node_id"]}})
            if not isinstance(response,dict) or response.get("errors") or response.get("data",{}).get("markPullRequestReadyForReview",{}).get("pullRequest",{}).get("isDraft") is not False or response.get("data",{}).get("markPullRequestReadyForReview",{}).get("pullRequest",{}).get("id")!=target["node_id"]:raise TrioError("WRITE_UNCERTAIN",exit_code=4)
            return response
        raise TrioError("INVALID_INVOCATION",exit_code=2)
    def execute(self,identifier,actor,transport):
        with self.store.write_lock():
            plan=self.get("plans",identifier);self.check_plan(plan);self.require_approval(plan);self.gate(plan,actor,transport)
            journal_path=confined(self.root,"journals/"+safe_id(identifier)+".json")
            if journal_path.exists():raise TrioError("OPERATION_ALREADY_ATTEMPTED")
            target,repo,_=self.observe(transport,plan["operation"],plan["repository"],plan["target"].get("number"),plan["target"].get("thread"))
            if target!=plan["target"]:raise TrioError("PRECONDITION_CHANGED")
            if plan["operation"]!="notification-ack":self.permissions(repo,plan["operation"])
            journal={"schema":"trio.maintenance-journal/v1","id":identifier,"plan_digest":plan["digest"],"identity":plan["identity"],"attempted_at":now(),"outcome":"attempted","response_id":None}
            self.put("journals",identifier,journal)
            try:
                result=self.dispatch(transport,plan)
                if plan["operation"]=="pr-merge" and (not isinstance(result,dict) or result.get("merged") is not True):raise TrioError("WRITE_UNCERTAIN",exit_code=4)
                op=plan["operation"];expected=plan["target"];valid=True
                if op=="notification-ack":valid=transport.last_status in {204,205} and result is None
                elif op=="issue-comment":valid=isinstance(result,dict) and type(result.get("id")) is int and result.get("body")==plan["parameters"]["body"] and result.get("user",{}).get("id")==plan["identity"]["id"] and result.get("issue_url")=="https://api.github.com/repos/"+plan["repository"]+"/issues/"+str(expected["number"])
                elif op=="issue-label":valid=isinstance(result,list) and sorted(x.get("name","") for x in result if isinstance(x,dict))==sorted(plan["parameters"]["labels"])
                elif op in {"issue-close","issue-reopen","pr-close"}:valid=isinstance(result,dict) and result.get("id")==expected["item_id"] and result.get("number")==expected["number"] and result.get("state")==("open" if op=="issue-reopen" else "closed")
                elif op=="pr-update-branch":valid=transport.last_status==202 and isinstance(result,dict) and isinstance(result.get("message"),str)
                if not valid:raise TrioError("WRITE_UNCERTAIN",exit_code=4)
                journal.update(outcome="pending" if op=="pr-update-branch" else "successful",response_id=result.get("id") if isinstance(result,dict) else None,completed_at=now())
            except (KeyboardInterrupt,SystemExit):
                journal.update(outcome="uncertain",error="CANCELLED");self.put("journals",identifier,journal);raise
            except TrioError as error:journal.update(outcome="uncertain" if error.code=="WRITE_UNCERTAIN" else "failed",error=error.code,completed_at=now())
            except Exception:journal.update(outcome="uncertain",error="WRITE_UNCERTAIN",completed_at=now())
            self.put("journals",identifier,journal)
            return journal
    def reconcile(self,identifier,transport):
        with self.store.write_lock():
            plan=self.get("plans",identifier);self.check_plan(plan);journal=self.get("journals",identifier)
            if transport.identity()!=plan["identity"]:raise TrioError("IDENTITY_CHANGED")
            target,repo,_=self.observe(transport,plan["operation"],plan["repository"],plan["target"].get("number"),plan["target"].get("thread"))
            if target.get("repository_id")!=plan["target"].get("repository_id") or target.get("item_id")!=plan["target"].get("item_id"):raise TrioError("IDENTITY_MISMATCH")
            if journal["outcome"]=="attempted":journal["outcome"]="uncertain"
            journal.update(observed=target,reconciled_at=now())
            desired=None;op=plan["operation"]
            if op=="notification-ack":desired=target.get("unread") is False
            elif op in {"issue-close","pr-close"}:desired=target.get("state")=="closed"
            elif op=="issue-reopen":desired=target.get("state")=="open"
            elif op=="issue-label":desired=target.get("labels")==sorted(plan["parameters"]["labels"])
            elif op=="pr-ready":desired=target.get("draft") is False
            elif op=="pr-merge":desired=target.get("merged") is True
            elif op=="pr-update-branch":desired=target.get("head")!=plan["target"]["head"] and target.get("base")==plan["target"]["base"]
            journal["desired_postcondition_observed"]=desired
            journal["attribution"]="Response receipt" if journal["outcome"]=="successful" else "Unproved; current state alone cannot attribute a dispatch"
            if plan["operation"]=="issue-comment" and journal["outcome"] in {"attempted","uncertain"}:
                rows=transport.pages("/repos/"+plan["repository"]+"/issues/"+str(plan["target"]["number"])+"/comments",limit=1000,budget=10)
                matched=[x for x in rows["records"] if x.get("body")==plan["parameters"]["body"] and x.get("user",{}).get("id")==plan["identity"]["id"]]
                if len(matched)==1:journal.update(outcome="successful",response_id=matched[0]["id"],confirmation="exact unique operation marker and authenticated author")
            self.put("journals",identifier,journal);return journal
