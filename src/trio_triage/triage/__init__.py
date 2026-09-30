"""Revision-bound proposals, groups, and reviews. Apache-2.0."""
import uuid
from ..team import TeamService,now
from ..storage import digest
from ..errors import TrioError
CATEGORIES={"duplicate","not_duplicate","related","competing_fix","different_cause","insufficient_evidence"}
STATES={"draft","needs_review","ready","archived"}
class TriageService:
    def __init__(self,store):self.store=store;self.team=TeamService(store)
    def propose(self,category,items,refs,rationale,actor,author_kind="human",finding_id=None,parents=None,survivor=None):
        if category not in CATEGORIES or not isinstance(items,list) or len(items)<2 or not rationale or author_kind not in ("human","agent"):raise TrioError("INVALID_FINDING",exit_code=2)
        if category=="duplicate" and survivor not in items:raise TrioError("INVALID_FINDING",exit_code=2)
        from ..evidence import EvidenceService
        for ref in refs:EvidenceService(self.store).resolve_ref(ref)
        payload={"author_attribution":{"id":actor,"kind":author_kind},"authored_at":now(),"category":category,"items":items,"evidence_refs":refs,"rationale":rationale,"author_kind":author_kind,"canonical_survivor":survivor,"selection_digests":sorted({r.get("snapshot","") for r in refs})}
        payload["decision_digest"]=digest(payload)
        return self.team.append(finding_id or "finding-"+uuid.uuid4().hex,"finding",payload,actor,parents,refs)
    def show(self,entity):
        return self._show(entity,self.team._view())
    def _show(self,entity,view):
        heads=view.heads.get(entity,[])
        if not heads:raise TrioError("EVIDENCE_MISSING")
        revisions=[self.team._with_trust(view.by_id[x]) for x in heads];reviews=[]
        from ..evidence import EvidenceService
        stale=False
        for revision in revisions:
            for ref in revision["evidence_refs"]:
                try:
                    if not EvidenceService(self.store).is_current(ref):stale=True
                except (TrioError,AttributeError):stale=True
        for e in view.reviews.get(entity,[]):
            if e["operation"]=="review" and e["payload"]["finding_id"]==entity:
                p=e["payload"];current=any(r["event_id"]==p["finding_revision"] and r["payload"].get("decision_digest")==p["decision_digest"] for r in revisions)
                trust=self.team._with_trust(e)["trust"]
                local_review=trust=="locally-recorded"
                withdrawn=any(w["actor"]["id"]==e["actor"]["id"] and (not local_review or w.get("local_origin")==e.get("local_origin")==self.store.config["installation_id"] and bool(self.store.config["installation_id"])) for w in view.withdrawals.get(e["event_id"],[]))
                reviews.append({"event_id":e["event_id"],"actor":e["actor"],"decision":p["decision"],"state":"withdrawn" if withdrawn else "current" if current and not stale else "stale","trust":trust})
        resolutions=[view.by_id[x] for x in view.heads.get("review-resolution-"+entity,[])]
        applicable_resolutions=0
        resolution_states=[]
        for resolution in resolutions:
            trust=self.team._with_trust(resolution)["trust"]
            local_authority=any(review["event_id"] in resolution["parents"] and review["trust"]=="locally-recorded" for review in reviews)
            applicable=trust=="locally-recorded" or not local_authority
            resolution_states.append({"event_id":resolution["event_id"],"trust":trust,"state":"applied" if applicable else "unverified"})
            if applicable:
                applicable_resolutions+=1
                for review in reviews:
                    if review["event_id"] in resolution["parents"] and review["event_id"]!=resolution["payload"]["selected"] and review["state"]=="current":review["state"]="superseded"
        review_conflict=applicable_resolutions>1 or len({r["decision"] for r in reviews if r["state"]=="current"})>1
        return {"schema":"trio.finding/v1","id":entity,"review_conflict":review_conflict,"revisions":revisions,"conflict":len(heads)>1 or review_conflict,"stale":stale,"reviews":reviews,"review_resolutions":resolution_states}
    def review(self,entity,decision_digest,decision,actor):
        self.store.role(actor,"reviewer")
        finding=self.show(entity)
        if finding["conflict"] or finding["stale"] or not any(r["payload"].get("decision_digest")==decision_digest for r in finding["revisions"]):raise TrioError("PLAN_CHANGED")
        if decision not in ("approve","reject","needs_evidence"):raise TrioError("INVALID_REVIEW",exit_code=2)
        return self.team.append("review-"+uuid.uuid4().hex,"review",{"finding_id":entity,"decision_digest":decision_digest,"finding_revision":finding["revisions"][0]["event_id"],"source_selection":finding["revisions"][0]["payload"]["selection_digests"],"decision":decision},actor)
    def withdraw(self,review_id,actor):
        prior=self.team.get(review_id)
        if prior["operation"]!="review" or prior["actor"]["id"]!=actor:raise TrioError("REVIEW_UNVERIFIED")
        return self.team.append("withdraw-"+uuid.uuid4().hex,"withdraw-review",{"review_id":review_id},actor)
    def group(self,members,actor,notes="",assignee=None,status="draft",entity=None,parents=None):
        if status not in STATES or not isinstance(members,list) or len(members)>1000:raise TrioError("INVALID_GROUP",exit_code=2)
        if entity:
            current=self.team.get(self.team.heads(entity)[0])["payload"]
            if current["status"]=="archived" and status!="archived":raise TrioError("INVALID_TRANSITION")
        return self.team.append(entity or "group-"+uuid.uuid4().hex,"group-update" if entity else "group",{"members":members,"notes":notes,"assignee":assignee,"status":status},actor,parents)
    def similar(self,items):
        from difflib import SequenceMatcher
        def key(x):return (x["repository"]["host"],x["repository"]["database_id"],x["kind"],x["number"],x["database_id"])
        def revision(x):return x.get("revision")
        out=[]
        for i,a in enumerate(items):
            for b in items[i+1:]:
                score=SequenceMatcher(None,a.get("title","").lower(),b.get("title","").lower()).ratio()
                suppressed=False;stale=False
                for e in self.team.events():
                    if e["operation"] in ("finding","resolve") and e["payload"].get("category")=="not_duplicate" and e["event_id"] in self.team.heads(e["entity_id"]):
                        pair=e["payload"]["items"]
                        if {key(x) for x in pair}=={key(a),key(b)}:
                            old={key(x):revision(x) for x in pair};new={key(a):revision(a),key(b):revision(b)}
                            from ..evidence import EvidenceService
                            try:current=all(EvidenceService(self.store).is_current(ref) for ref in e["evidence_refs"])
                            except TrioError:current=False
                            suppressed=old==new and current;stale=not suppressed
                out.append({"items":[a,b],"title_similarity":score,"suppressed":suppressed,"negative_stale":stale,"classification":"investigation-lead"})
        return sorted(out,key=lambda x:(-x["title_similarity"],key(x["items"][0]),key(x["items"][1])))[:1000]
