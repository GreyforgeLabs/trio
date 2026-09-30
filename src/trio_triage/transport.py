"""Explicit read-only GitHub transport; no credential-helper discovery."""
import json,os,re,urllib.request,urllib.error
from .errors import TrioError
class ReadTransport:
    def __init__(self,token_env=None,timeout=45):
        if token_env is not None and not re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}",token_env):raise TrioError("INVALID_CONFIG",exit_code=2)
        self.token=os.environ.get(token_env) if token_env else None;self.timeout=timeout;self.profile=token_env or "anonymous"
    def get(self,path):
        if path!="/user" and (not isinstance(path,str) or not re.fullmatch(r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_./-]+)?(?:\?[A-Za-z0-9_=&.-]+)?",path) or ".." in path):raise TrioError("SCOPE_DENIED")
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*a,**k):raise TrioError("SCOPE_DENIED")
        headers={"User-Agent":"trio-triage/0.1","Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"}
        if self.token:headers["Authorization"]="Bearer "+self.token
        req=urllib.request.Request("https://api.github.com"+path,headers=headers)
        try:
            with urllib.request.build_opener(NoRedirect).open(req,timeout=self.timeout) as response:
                raw=response.read(67108865)
                if len(raw)>67108864:raise TrioError("RESOURCE_LIMIT")
                from .contracts import strict_json
                return strict_json(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code==429 or e.code==403 and (e.headers.get("Retry-After") or e.headers.get("X-RateLimit-Remaining")=="0"):
                error=TrioError("THROTTLED",exit_code=4)
                try:error.retry_after=min(86400,max(1,int(e.headers.get("Retry-After","60"))))
                except ValueError:error.retry_after=60
                raise error from None
            raise TrioError("SCOPE_DENIED" if e.code in (401,403,404) else "TRANSPORT_FAILURE",exit_code=4) from None
        except (OSError,ValueError):raise TrioError("TRANSPORT_FAILURE",exit_code=4) from None

    def namespace(self):
        if not self.token:return None
        identity=self.get("/user")
        if type(identity.get("id")) is not int or identity["id"]<1:raise TrioError("IDENTITY_MISMATCH")
        return "github-account:"+str(identity["id"])

    def current_target(self,target):
        repo=self.get("/repos/"+target["full_name"])
        if repo.get("private") is not False:raise TrioError("PUBLIC_REPO_REQUIRED")
        if repo.get("id")!=target["repository_id"] or repo.get("full_name")!=target["full_name"]:raise TrioError("IDENTITY_MISMATCH")
        endpoint="/pulls/" if target["kind"]=="pr" else "/issues/"
        item=self.get("/repos/"+target["full_name"]+endpoint+str(target["number"]))
        if item.get("id")!=target["item_id"] or item.get("number")!=target["number"] or target["kind"]=="issue" and item.get("pull_request"):raise TrioError("IDENTITY_MISMATCH")
        if target["kind"]=="pr":
            for name in ("head","base"):
                linked=item.get(name,{}).get("repo")
                if not isinstance(linked,dict) or linked.get("private") is not False:raise TrioError("PUBLIC_REPO_REQUIRED")
                observed=self.get("/repos/"+linked["full_name"])
                if observed.get("private") is not False or observed.get("id")!=linked.get("id"):raise TrioError("IDENTITY_MISMATCH")
        return {**target,"visibility":"public","state":item["state"],"head_sha":item.get("head",{}).get("sha"),"merged":bool(item.get("merged",False))}
    def observe(self,proposal,journal):
        observed=self.current_target(proposal["target"])
        # Present state or identical comment text cannot attribute an uncertain dispatch.
        return {"target":{k:observed[k] for k in proposal["target"]},"visibility":observed["visibility"],"observed_state":observed["state"],"comment":{"confirmed":False},"state":{"confirmed":False}}

    def _special(self,path,*,accept="application/vnd.github+json",data=None):
        if path!="/graphql" and not re.fullmatch(r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pulls/[1-9][0-9]*",path):raise TrioError("SCOPE_DENIED")
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*a,**k):raise TrioError("SCOPE_DENIED")
        headers={"User-Agent":"trio-triage/0.1","Accept":accept,"X-GitHub-Api-Version":"2022-11-28"}
        if self.token:headers["Authorization"]="Bearer "+self.token
        if data is not None:headers["Content-Type"]="application/json"
        request=urllib.request.Request("https://api.github.com"+path,headers=headers,data=data,method="POST" if data is not None else "GET")
        try:
            with urllib.request.build_opener(NoRedirect).open(request,timeout=self.timeout) as response:
                raw=response.read(67108865)
                if len(raw)>67108864:raise TrioError("RESOURCE_LIMIT")
                if accept=="application/vnd.github.diff":return raw.decode("utf-8")
                from .contracts import strict_json
                return strict_json(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code==429 or e.code==403 and (e.headers.get("Retry-After") or e.headers.get("X-RateLimit-Remaining")=="0"):
                error=TrioError("THROTTLED",exit_code=4)
                try:error.retry_after=min(86400,max(1,int(e.headers.get("Retry-After","60"))))
                except ValueError:error.retry_after=60
                raise error from None
            raise TrioError("SCOPE_DENIED" if e.code in (401,403,404) else "TRANSPORT_FAILURE",exit_code=4) from None
        except (OSError,ValueError):raise TrioError("TRANSPORT_FAILURE",exit_code=4) from None
    def diff(self,path):return self._special(path,accept="application/vnd.github.diff")
    def closing_page(self,node_id,after=None):
        if not isinstance(node_id,str) or not 1<=len(node_id)<=256 or not re.fullmatch(r"[A-Za-z0-9_=+/-]+",node_id) or after is not None and (not isinstance(after,str) or len(after)>1024):raise TrioError("SCOPE_DENIED")
        from .evidence.read_contract import CLOSING_QUERY
        payload=json.dumps({"query":CLOSING_QUERY,"variables":{"id":node_id,"after":after}},separators=(",",":")).encode()
        response=self._special("/graphql",data=payload)
        if not isinstance(response,dict):raise TrioError("TRANSPORT_FAILURE",exit_code=4)
        errors=response.get("errors",[])
        if not isinstance(errors,list):raise TrioError("TRANSPORT_FAILURE",exit_code=4)
        if errors:
            if any(isinstance(error,dict) and (error.get("type")=="RATE_LIMITED" or isinstance(error.get("extensions"),dict) and error["extensions"].get("code")=="RATE_LIMITED") for error in errors):
                failure=TrioError("THROTTLED",exit_code=4);failure.retry_after=60;raise failure
            raise TrioError("TRANSPORT_FAILURE",exit_code=4)
        data=response.get("data")
        if not isinstance(data,dict) or "node" not in data:raise TrioError("TRANSPORT_FAILURE",exit_code=4)
        node=data["node"]
        if node is None:return None
        required={"id","number","url","repository","updatedAt","baseRefOid","headRefOid","closingIssuesReferences"}
        if not isinstance(node,dict) or not required<=set(node) or not isinstance(node["repository"],dict):raise TrioError("TRANSPORT_FAILURE",exit_code=4)
        return node
