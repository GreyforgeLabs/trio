# SPDX-License-Identifier: Apache-2.0
"""Private account-scoped inventory; partial acquisition never implies deletion."""
import uuid,re
from .operations import OperationState,now,repo_name,integer
from .storage import canonical,digest,read_json,confined
from .errors import TrioError

KINDS={"repositories","forks","pulls","issues","notifications","workflow_runs","releases"}
def valid_id(row):
    return type(row.get("id")) in (int,str)
def project(kind,row):
    common={k:row[k] for k in ("id","node_id","number","name","full_name","html_url","state","updated_at","created_at","private","fork","default_branch","draft","unread","status","conclusion","tag_name","published_at") if k in row}
    for key in ("title","description"):
        if isinstance(row.get(key),str):common[key]=row[key][:512]
    if isinstance(row.get("repository"),dict):common["repository"]={k:row["repository"][k] for k in ("id","full_name","private") if k in row["repository"]}
    if isinstance(row.get("subject"),dict):common["subject"]={k:row["subject"][k][:512] for k in ("title","type","url") if isinstance(row["subject"].get(k),str)}
    for key in ("base","head"):
        if isinstance(row.get(key),dict):common[key]={k:row[key][k] for k in ("ref","sha") if k in row[key]}
    if "pull_request" in row:common["pull_request"]=True
    return common

class InventoryService(OperationState):
    def sync(self,transport,organization=None,repository_limit=100,item_limit=1000,request_budget=100):
        if type(repository_limit) is not int or not 1<=repository_limit<=1000 or type(item_limit) is not int or not 1<=item_limit<=10000 or type(request_budget) is not int or not 1<=request_budget<=10000:raise TrioError("INVALID_INVOCATION",exit_code=2)
        if organization is not None and (not isinstance(organization,str) or not re.fullmatch(r"[A-Za-z0-9-]{1,39}",organization)):raise TrioError("INVALID_TARGET",exit_code=2)
        identity=transport.identity();scope="org:"+organization if organization else "account:"+str(identity["id"])
        remaining=request_budget;components={}
        def acquire(key,path,kind,limit=item_limit):
            nonlocal remaining
            if remaining<=0:result={"records":[],"complete":False,"error":"REQUEST_BUDGET","requests":0,"observed_at":now()}
            else:result=transport.pages(path,limit=limit,budget=remaining)
            remaining-=result["requests"]
            result["records"]=[project(kind,x) for x in result["records"]]
            # Record IDs must be present. Unknown/malformed records make scope partial.
            if any(not valid_id(x) for x in result["records"]):result.update(complete=False,error="REMOTE_SCHEMA")
            components[key]=result;return result
        repositories=acquire("repositories","/orgs/"+organization+"/repos?type=all" if organization else "/user/repos?visibility=all&affiliation=owner,collaborator,organization_member","repositories",repository_limit)
        components["forks"]={**repositories,"records":[x for x in repositories["records"] if x.get("fork") is True]}
        for repository in repositories["records"]:
            try:name=repo_name(repository.get("full_name"))
            except TrioError:
                repositories.update(complete=False,error="REMOTE_SCHEMA");components["forks"].update(complete=False,error="REMOTE_SCHEMA");continue
            prefix="/repos/"+name
            for kind,suffix in (("pulls","/pulls?state=open"),("issues","/issues?state=open"),("workflow_runs","/actions/runs"),("releases","/releases")):
                result=acquire(kind+":"+name,prefix+suffix,kind)
                if kind=="issues":
                    # GitHub issue collections also contain pull requests.
                    result["records"]=[x for x in result["records"] if "pull_request" not in x]
        # Notifications are recipient data. Organization selection filters known
        # repository IDs and never claims complete if repository acquisition failed.
        notifications=acquire("notifications","/notifications?all=true&participating=false","notifications")
        if organization:
            ids={x["id"] for x in repositories["records"] if valid_id(x)}
            notifications["records"]=[x for x in notifications["records"] if x.get("repository",{}).get("id") in ids]
            if not repositories["complete"]:notifications.update(complete=False,error=notifications["error"] or "REPOSITORY_SCOPE_PARTIAL")
        if transport.identity()!=identity:
            for component in components.values():component.update(complete=False,error="IDENTITY_CHANGED")
        snapshot={"schema":"trio.inventory-snapshot/v1","id":uuid.uuid4().hex,"identity":identity,"scope":scope,"created_at":now(),"components":components,"request_budget":request_budget,"requests":request_budget-remaining,"complete":all(x["complete"] for x in components.values())}
        snapshot["digest"]=digest(snapshot)
        with self.store.write_lock():self.put("inventory",snapshot["id"],snapshot)
        return {"schema":"trio.inventory-sync/v1","snapshot":snapshot["id"],"identity":identity,"scope":scope,"digest":snapshot["digest"],"complete":snapshot["complete"],"components":{k:{key:v[key] for key in ("complete","error","requests","observed_at")}|{"count":len(v["records"])} for k,v in components.items()}}
    def snapshot(self,identifier):
        value=self.get("inventory",identifier)
        if digest({k:v for k,v in value.items() if k!="digest"})!=value.get("digest"):raise TrioError("INVENTORY_CORRUPT")
        return value
    def snapshots(self):
        directory=self.root/"inventory"
        return {"schema":"trio.inventory-snapshots/v1","snapshots":[{k:v[k] for k in ("id","identity","scope","created_at","complete","digest")} for v in (read_json(x) for x in sorted(directory.glob("*.json")))] if directory.exists() else []}
    def list(self,identifier,kind="repositories",repository=None,limit=20,cursor=None,max_bytes=12000):
        if kind not in KINDS or type(limit) is not int or not 1<=limit<=1000:raise TrioError("INVALID_INVOCATION",exit_code=2)
        value=self.snapshot(identifier);key=kind+(":"+repo_name(repository) if repository and kind not in {"repositories","forks","notifications"} else "")
        if key not in value["components"]:raise TrioError("SELECTION_REQUIRED",exit_code=2)
        component=value["components"][key];offset=0
        if cursor:
            import base64
            from .contracts import strict_json
            try:c=strict_json(base64.urlsafe_b64decode(cursor+"="*(-len(cursor)%4)).decode())
            except Exception:raise TrioError("INVALID_CURSOR") from None
            if not isinstance(c,dict) or c.get("snapshot")!=value["digest"] or c.get("component")!=key or type(c.get("offset")) is not int or not 0<=c["offset"]<=len(component["records"]):raise TrioError("INVALID_CURSOR")
            offset=c["offset"]
        rows=component["records"];selected=[]
        result={"schema":"trio.inventory-list/v1","snapshot":identifier,"scope":value["scope"],"identity":value["identity"],"kind":key,"observed_at":component["observed_at"],"complete":component["complete"],"error":component["error"],"records":selected,"next_cursor":None}
        import base64
        for row in rows[offset:offset+limit]:
            selected.append(row);next_offset=offset+len(selected)
            result["next_cursor"]=base64.urlsafe_b64encode(canonical({"snapshot":value["digest"],"component":key,"offset":next_offset})).decode().rstrip("=") if next_offset<len(rows) else None
            if len(canonical(result))+1>max_bytes:
                selected.pop();next_offset=offset+len(selected)
                result["next_cursor"]=base64.urlsafe_b64encode(canonical({"snapshot":value["digest"],"component":key,"offset":next_offset})).decode().rstrip("=");break
        if not selected and offset<len(rows):raise TrioError("BUDGET_TOO_SMALL")
        return result
    def show(self,identifier,repository):
        value=self.snapshot(identifier);name=repo_name(repository)
        rows=[x for x in value["components"]["repositories"]["records"] if x.get("full_name")==name]
        if len(rows)!=1:raise TrioError("TARGET_MISSING")
        return {"schema":"trio.inventory-repository/v1","snapshot":identifier,"observed_at":value["created_at"],"repository":rows[0],"coverage":{k:{"complete":v["complete"],"error":v["error"],"count":len(v["records"])} for k,v in value["components"].items() if k.endswith(":"+name)}}
    def drift(self,before,after):
        old=self.snapshot(before);new=self.snapshot(after)
        if old["identity"]!=new["identity"] or old["scope"]!=new["scope"]:raise TrioError("IDENTITY_MISMATCH")
        changes={}
        for key in sorted(set(old["components"])|set(new["components"])):
            a=old["components"].get(key);b=new["components"].get(key)
            arows={str(x["id"]):x for x in a["records"] if valid_id(x)} if a else {};brows={str(x["id"]):x for x in b["records"] if valid_id(x)} if b else {}
            trustworthy=bool(a and b and a["complete"] and b["complete"])
            changes[key]={"comparable":trustworthy,"added":sorted(set(brows)-set(arows)) if trustworthy else [],"absent":sorted(set(arows)-set(brows)) if trustworthy else [],"changed":[x for x in sorted(set(arows)&set(brows)) if arows[x]!=brows[x]],"absence":"observed absence; not a deletion claim" if trustworthy else "unknown due to partial or unrequested acquisition"}
        return {"schema":"trio.inventory-drift/v1","before":before,"after":after,"changes":changes}
