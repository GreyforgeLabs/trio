"""Immutable event exchange; signatures are never inferred. Apache-2.0."""
import datetime,json,re,uuid
from pathlib import Path
from ..storage import canonical,digest,atomic_json,read_json
from ..errors import TrioError

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def screen(value):
    # Inspect decoded strings and structured assignments before JSON escaping.
    sensitive=re.compile(r"(?:-----BEGIN .*PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|Bearer [A-Za-z0-9._-]{16,}|(?:api_key|access_token|password|token|secret)[\"']?\s*[:=]\s*[\"']?[^\s,}\"']{12,})",re.I)
    credential=re.compile(r"(?:api_key|access_token|password|token|secret)",re.I)
    def inspect(item):
        if isinstance(item,str):
            if sensitive.search(item):raise TrioError("SHARE_BLOCKED")
        elif isinstance(item,dict):
            for key,child in item.items():
                if isinstance(key,str):
                    inspect(key)
                    if credential.fullmatch(key) and isinstance(child,str) and re.search(r"[^\s,}\"']{12,}",child):raise TrioError("SHARE_BLOCKED")
                inspect(child)
        elif isinstance(item,list):
            for child in item:inspect(child)
    inspect(value)

class TeamService:
    def __init__(self,store):self.store=store;store.require()
    def events(self):
        with self.store.db() as db:return [json.loads(r[0]) for r in db.execute("SELECT data FROM events ORDER BY id")]
    def heads(self,entity):
        events=[e for e in self.events() if e["entity_id"]==entity];parents={p for e in events for p in e["parents"]}
        return sorted(e["event_id"] for e in events if e["event_id"] not in parents)
    def get(self,event_id):
        with self.store.db() as db:row=db.execute("SELECT data FROM events WHERE id=?",(event_id,)).fetchone()
        if not row:raise TrioError("EVIDENCE_MISSING")
        e=json.loads(row[0]);e["trust"]="locally-recorded" if e.get("local_origin")==self.store.config["installation_id"] and self.store.config["installation_id"] else "claimed"
        return e
    def append(self,entity,operation,payload,actor,parents=None,refs=None):
        role="reviewer" if operation in ("review","withdraw-review") else "maintainer" if operation in ("resolve","review-resolution") else "contributor"
        self.store.role(actor,role)
        parents=[] if parents is None else parents
        actual=self.heads(entity)
        if operation!="review-resolution" and sorted(parents)!=actual:raise TrioError("REVISION_CONFLICT")
        payload=dict(payload)
        e={"version":1,"workspace_id":self.store.config["workspace_id"],"entity_id":entity,"parents":sorted(parents),"operation":operation,"actor":{"id":actor,"kind":payload.get("author_kind","human"),"trust":"claimed"},"evidence_refs":refs or [],"payload":payload,"timestamp":payload.get("authored_at",now()) if operation=="finding" else now(),"nonce":uuid.uuid4().hex}
        e["payload_digest"]=digest(payload);e["event_id"]=digest(e)
        self.validate_event(e)
        stored={**e,"local_origin":self.store.config["installation_id"]}
        with self.store.db(True) as db:
            existing=[json.loads(r[0]) for r in db.execute("SELECT data FROM events WHERE entity=?",(entity,))]
            ancestor={p for old in existing for p in old["parents"]}
            heads=sorted(old["event_id"] for old in existing if old["event_id"] not in ancestor)
            if operation!="review-resolution" and sorted(parents)!=heads:raise TrioError("REVISION_CONFLICT")
            if operation=="review":
                findings=[json.loads(r[0]) for r in db.execute("SELECT data FROM events WHERE entity=?",(payload["finding_id"],))]
                past={p for old in findings for p in old["parents"]}
                current=[old["event_id"] for old in findings if old["event_id"] not in past]
                if current!=[payload["finding_revision"]]:raise TrioError("PLAN_CHANGED")
            db.execute("INSERT INTO events VALUES(?,?,?)",(e["event_id"],entity,canonical(stored).decode()))
        return {**stored,"trust":"locally-recorded"}
    def status(self):
        events=self.events();entities=sorted({e["entity_id"] for e in events})
        conflicts=[{"entity":e,"heads":self.heads(e)} for e in entities if len(self.heads(e))>1]
        from ..triage import TriageService
        for entity in {e["entity_id"] for e in events if e["operation"]=="finding"}:
            finding=TriageService(self.store).show(entity)
            if finding["review_conflict"]:conflicts.append({"entity":entity,"review_heads":[r["event_id"] for r in finding["reviews"] if r["state"]=="current"]})
        return {"schema":"trio.team-status/v1","events":len(events),"conflicts":conflicts,"trust":"local roles do not authenticate imported attribution"}
    def export(self,path=None,ids=None,approve=False):
        if ids is None:raise TrioError("EXPLICIT_SELECTION_REQUIRED",exit_code=2)
        selected=[e for e in self.events() if e["event_id"] in ids]
        required={p for e in selected for p in e["parents"]}|{e["payload"]["finding_revision"] for e in selected if e["operation"]=="review"}|{e["payload"]["review_id"] for e in selected if e["operation"]=="withdraw-review"}
        while required-set(e["event_id"] for e in selected):
            additions=[e for e in self.events() if e["event_id"] in required and e not in selected]
            selected.extend(additions);required.update(p for e in additions for p in e["parents"]);required.update(e["payload"]["finding_revision"] for e in additions if e["operation"]=="review")
        from ..evidence import EvidenceService
        evidence=EvidenceService(self.store)
        for e in selected:
            for ref in e["evidence_refs"]:
                evidence.require_shareable(ref["dataset"])
                scope=evidence.scope(ref["dataset"])
                if scope.get("suspended") or scope.get("visibility")!="public":raise TrioError("SHARE_BLOCKED")
        # Export decisions; team notes require a reviewed packet instead.
        safe=[]
        for e in selected:
            if e["operation"] in ("group","group-update") and e["payload"].get("notes"):raise TrioError("SHARE_BLOCKED")
            safe.append({k:v for k,v in e.items() if k!="local_origin"})
        result={"schema":"trio.team-bundle/v1","events":safe};screen(result)
        result["digest"]=digest(result)
        if len(canonical(result))>16777216:raise TrioError("RESOURCE_LIMIT")
        if path is not None:
            if not approve:return {"preview":result,"destination":str(path),"requires_approval":True}
            atomic_json(path,result)
        return result
    def export_workspace(self,path,ids,approve_digest=None):
        root=Path(path).absolute()
        if root==self.store.root or root.is_relative_to(Path(__file__).resolve().parents[3]) or any(p.is_symlink() for p in [root,*root.parents]):raise TrioError("SCOPE_DENIED")
        bundle=self.export(ids=ids)
        approval=digest({"destination":str(root),"bundle_digest":bundle["digest"]})
        if approve_digest!=approval:return {"schema":"trio.team-preview/v1","destination":str(root),"payload":bundle,"approval_digest":approval}
        if root.exists():
            allowed={"team.json"}|{"events/"+e["event_id"]+".json" for e in bundle["events"]}
            for p in root.rglob("*"):
                if p.is_symlink() or p.is_file() and p.relative_to(root).as_posix() not in allowed:raise TrioError("REVISION_CONFLICT")
            for e in bundle["events"]:
                old=root/"events"/(e["event_id"]+".json")
                if old.exists() and read_json(old)!=e:raise TrioError("REVISION_CONFLICT")
        for e in bundle["events"]:atomic_json(root/"events"/(e["event_id"]+".json"),e)
        atomic_json(root/"team.json",{"schema":"trio.team-workspace/v1","workspace_id":self.store.config["workspace_id"],"events":[e["event_id"] for e in bundle["events"]],"bundle_digest":bundle["digest"]})
        return {"schema":"trio.team-export/v1","destination":str(root),"digest":bundle["digest"]}
    def import_workspace(self,path):
        root=Path(path).absolute()
        if any(p.is_symlink() for p in [root,*root.parents]):raise TrioError("SCOPE_DENIED")
        metadata=read_json(root/"team.json")
        if metadata.get("schema")!="trio.team-workspace/v1" or metadata.get("workspace_id")!=self.store.config["workspace_id"] or not isinstance(metadata.get("events"),list) or len(metadata["events"])>10000:raise TrioError("SCOPE_DENIED")
        expected={"team.json"}|{"events/"+x+".json" for x in metadata["events"] if isinstance(x,str) and re.fullmatch(r"[0-9a-f]{64}",x)}
        actual=set()
        for p in root.rglob("*"):
            if p.is_symlink():raise TrioError("SCOPE_DENIED")
            if p.is_file():actual.add(p.relative_to(root).as_posix())
        if actual!=expected:raise TrioError("SCOPE_DENIED")
        events=[read_json(root/"events"/(x+".json")) for x in metadata["events"]]
        if sum(len(canonical(e)) for e in events)>16777216:raise TrioError("RESOURCE_LIMIT")
        return self.import_bundle_data({"schema":"trio.team-bundle/v1","events":events,"digest":metadata["bundle_digest"]})
    def import_bundle(self,path):
        return self.import_bundle_data(read_json(path))
    def import_bundle_data(self,bundle):
        screen(bundle)
        if not isinstance(bundle,dict) or set(bundle)!={"schema","events","digest"} or bundle.get("schema")!="trio.team-bundle/v1" or not isinstance(bundle.get("events"),list):raise TrioError("SCHEMA_NEWER")
        if bundle.get("digest")!=digest({k:v for k,v in bundle.items() if k!="digest"}):raise TrioError("EVIDENCE_CORRUPT")
        events=bundle["events"]
        if len(events)>10000:raise TrioError("RESOURCE_LIMIT")
        known={e["event_id"]:{k:v for k,v in e.items() if k!="local_origin"} for e in self.events()};incoming={}
        for e in events:
            required={"version","workspace_id","entity_id","parents","operation","actor","evidence_refs","payload","timestamp","nonce","payload_digest","event_id"}
            if set(e)!=required or type(e["version"]) is not int or e["version"]!=1:raise TrioError("SCHEMA_NEWER")
            if e["operation"] not in ("finding","group","group-update","review","withdraw-review","resolve","review-resolution"):raise TrioError("SCOPE_DENIED")
            self.validate_event(e)
            if e["actor"].get("trust")!="claimed" or e["payload_digest"]!=digest(e["payload"]) or e["event_id"]!=digest({k:v for k,v in e.items() if k!="event_id"}):raise TrioError("EVIDENCE_CORRUPT")
            if e["event_id"] in incoming and incoming[e["event_id"]]!=e:raise TrioError("REVISION_CONFLICT")
            if e["event_id"] in known and known[e["event_id"]]!=e:raise TrioError("REVISION_CONFLICT")
            incoming[e["event_id"]]=e
        union={**known,**incoming}
        for e in events:
            if not isinstance(e["parents"],list) or len(e["parents"])!=len(set(e["parents"])) or any(p not in union or e["operation"]!="review-resolution" and union[p]["entity_id"]!=e["entity_id"] for p in e["parents"]):raise TrioError("REVISION_CONFLICT")
            if e["operation"]=="review":
                p=e["payload"];revision=union.get(p["finding_revision"])
                if not revision or revision["entity_id"]!=p["finding_id"] or revision["payload"].get("decision_digest")!=p["decision_digest"] or revision["payload"].get("selection_digests")!=p.get("source_selection"):raise TrioError("EVIDENCE_CORRUPT")
            if e["operation"]=="review-resolution" and any(union[x]["operation"]!="review" or union[x]["payload"]["finding_id"]!=e["payload"]["finding_id"] for x in e["parents"]):raise TrioError("REVISION_CONFLICT")
            if e["operation"]=="withdraw-review":
                prior=union.get(e["payload"]["review_id"])
                if not prior or prior["operation"]!="review" or prior["actor"]["id"]!=e["actor"]["id"]:raise TrioError("REVIEW_UNVERIFIED")
            pending=[*e["parents"]];seen=set()
            while pending:
                x=pending.pop()
                if x==e["event_id"]:raise TrioError("REVISION_CONFLICT")
                if x not in seen:seen.add(x);pending.extend(union[x]["parents"])
        inserted=0
        with self.store.db(True) as db:
            for eid,e in incoming.items():
                if eid not in known:db.execute("INSERT INTO events VALUES(?,?,?)",(eid,e["entity_id"],canonical(e).decode()));inserted+=1
        return {"schema":"trio.team-import/v1","inserted":inserted,"trust":"claimed","source_verification":"unverified-source","status":self.status(),"conflicts":self.status()["conflicts"]}
    def validate_event(self,e):
        if e["workspace_id"]!=self.store.config["workspace_id"] or not isinstance(e["entity_id"],str) or not e["entity_id"] or not isinstance(e["parents"],list) or any(not isinstance(x,str) or len(x)!=64 for x in e["parents"]):raise TrioError("SCOPE_DENIED")
        actor=e["actor"]
        if not isinstance(actor,dict) or set(actor)!={"id","kind","trust"} or not isinstance(actor["id"],str) or not actor["id"] or actor["kind"] not in ("human","agent") or actor["trust"]!="claimed":raise TrioError("REVIEW_UNVERIFIED")
        if not isinstance(e["timestamp"],str) or not isinstance(e["nonce"],str) or not isinstance(e["payload"],dict) or not isinstance(e["evidence_refs"],list) or len(e["evidence_refs"])>1000:raise TrioError("EVIDENCE_CORRUPT")
        p=e["payload"];op=e["operation"]
        if op=="finding" or op=="resolve" and "category" in p:
            from ..triage import CATEGORIES
            from ..contracts import timestamp
            try:
                timestamp(p["authored_at"])
                if set(p["author_attribution"])!={"id","kind"} or not isinstance(p["author_attribution"]["id"],str) or not p["author_attribution"]["id"] or p["author_attribution"]["kind"] not in ("human","agent"):raise ValueError()
                if op=="finding" and (p["author_attribution"]["id"]!=actor["id"] or p["author_attribution"]["kind"]!=actor["kind"] or p["authored_at"]!=e["timestamp"]):raise ValueError()
            except (ValueError,TypeError,KeyError):raise TrioError("EVIDENCE_CORRUPT") from None
            if p.get("category") not in CATEGORIES or not isinstance(p.get("items"),list) or len(p["items"])<2 or not isinstance(p.get("rationale"),str) or not p["rationale"]:raise TrioError("EVIDENCE_CORRUPT")
            from ..contracts import validate_item,validate_repository
            try:
                for item in p["items"]:
                    validate_item({k:item[k] for k in ("kind","number","database_id","node_id")});validate_repository(item["repository"])
                    if item["database_id"] is None:raise ValueError()
            except (ValueError,KeyError,TypeError):raise TrioError("IDENTITY_MISMATCH") from None
            if p["category"]=="duplicate" and p.get("canonical_survivor") not in p["items"]:raise TrioError("EVIDENCE_CORRUPT")
            base={k:v for k,v in p.items() if k not in ("decision_digest","resolution")}
            if p.get("decision_digest")!=digest(base):raise TrioError("EVIDENCE_CORRUPT")
        if op in ("group","group-update"):
            if p.get("status") not in ("draft","needs_review","ready","archived") or not isinstance(p.get("members"),list) or len(p["members"])>1000 or not isinstance(p.get("notes"),str):raise TrioError("EVIDENCE_CORRUPT")
        if op=="withdraw-review":
            if set(p)!={"review_id"} or not isinstance(p["review_id"],str) or not re.fullmatch(r"[0-9a-f]{64}",p["review_id"]) or e["evidence_refs"]:raise TrioError("EVIDENCE_CORRUPT")
        if op=="review-resolution":
            if set(p)!={"finding_id","selected","rationale"} or not isinstance(p.get("finding_id"),str) or e["entity_id"]!="review-resolution-"+p["finding_id"] or p.get("selected") not in e["parents"] or len(e["parents"])<2 or len(set(e["parents"]))!=len(e["parents"]) or not isinstance(p.get("rationale"),str) or not p["rationale"]:raise TrioError("REVISION_CONFLICT")
        if op=="review":
            if p.get("decision") not in ("approve","reject","needs_evidence") or not isinstance(p.get("finding_id"),str) or not isinstance(p.get("finding_revision"),str) or not isinstance(p.get("decision_digest"),str):raise TrioError("EVIDENCE_CORRUPT")
        for ref in e["evidence_refs"]:
            required={"schema","dataset","repository","identity","snapshot","component","object","revision","locator","excerpt_sha256"}
            if not isinstance(ref,dict) or set(ref)!=required or ref["schema"]!="trio.evidence-ref/v1":raise TrioError("EVIDENCE_CORRUPT")
            from ..contracts import checked_id,validate_repository,validate_item
            try:
                checked_id(ref["dataset"]);checked_id(ref["snapshot"]);checked_id(ref["excerpt_sha256"]);validate_repository(ref["repository"]);validate_item(ref["identity"])
                if type(ref["locator"]["start"]) is not int or type(ref["locator"]["end"]) is not int or not 0<=ref["locator"]["start"]<=ref["locator"]["end"]:raise ValueError()
            except (ValueError,KeyError,TypeError):raise TrioError("EVIDENCE_CORRUPT") from None
            # A recipient need not own the source. It remains unverified rather than changing trust.

    def resolve(self,entity,parents,rationale,actor,selected_id=None):
        if len(parents)<2 or not rationale:raise TrioError("REVISION_CONFLICT")
        predecessors=[self.get(p) for p in parents]
        if all(e["operation"]=="review" and e["payload"]["finding_id"]==entity for e in predecessors):
            from ..triage import TriageService
            current=TriageService(self.store).show(entity)
            competing=[r["event_id"] for r in current["reviews"] if r["state"]=="current"]
            if set(competing)!=set(parents) or selected_id not in parents:raise TrioError("REVISION_CONFLICT")
            return self.append("review-resolution-"+entity,"review-resolution",{"finding_id":entity,"selected":selected_id,"rationale":rationale},actor,parents)
        selected=next((e for e in predecessors if e["event_id"]==selected_id),predecessors[0])
        if selected_id is not None and selected_id not in parents:raise TrioError("REVISION_CONFLICT")
        payload={**selected["payload"],"resolution":{"rationale":rationale,"predecessors":parents,"selected":selected["event_id"]}}
        return self.append(entity,"resolve",payload,actor,parents,selected["evidence_refs"])
