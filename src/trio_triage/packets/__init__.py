"""Local packets and explicitly approved share previews. Apache-2.0."""
from ..team import TeamService,screen
from ..triage import TriageService
from ..storage import atomic_json,confined,digest,canonical
import html,re
from ..errors import TrioError
class PacketService:
    def __init__(self,store):self.store=store;store.require()
    def create(self,findings,output=None):
        packet={"schema":"trio.packet/v1","findings":[TriageService(self.store).show(f) for f in findings],"coverage":"recorded evidence only; not current visibility","conflicts":[x for x in TeamService(self.store).status()["conflicts"] if x["entity"] in findings],"next_steps":["Inspect source references; reassess stale decisions; authorize actions separately."]}
        from ..evidence import EvidenceService
        from ..contracts import coverage
        packet["evidence"]=[]
        refs=[ref for finding in packet["findings"] for r in finding["revisions"] for ref in r["evidence_refs"]]
        if len(refs)>100:raise TrioError("RESOURCE_LIMIT")
        for ref in refs:
            try:
                resolved=EvidenceService(self.store).resolve_ref(ref)
                screen(resolved["text"])
                manifest=EvidenceService(self.store).snapshot(ref["dataset"],ref["snapshot"])
                packet["evidence"].append({"ref":ref,"excerpt":resolved["text"] if len(resolved["text"].encode())<=512 else None,"coverage":coverage(manifest),"observed_at":manifest.get("completed_at"),"verified":True})
            except TrioError as e:
                if e.code=="SHARE_BLOCKED":raise
                packet["evidence"].append({"ref":ref,"verified":False,"coverage":"unverified-source"})
        packet["digest"]=digest(packet)
        if len(canonical(packet))>1048576:raise TrioError("RESOURCE_LIMIT")
        if output:
            path=confined(self.store.root,output)
            if path.suffix==".md":
                from ..evidence.service import atomic_bytes
                atomic_bytes(path,self.markdown(packet).encode())
            else:atomic_json(path,packet)
        return packet
    def share(self,packet,output,approve_digest=None):
        screen(packet)
        for finding in packet["findings"]:
            for r in finding["revisions"]:
                if r["payload"].get("notes"):raise TrioError("SHARE_BLOCKED")
                from ..evidence import EvidenceService
                for ref in r["evidence_refs"]:
                    EvidenceService(self.store).require_shareable(ref["dataset"])
                    EvidenceService(self.store).resolve_ref(ref)
        if packet["digest"]!=digest({k:v for k,v in packet.items() if k!="digest"}):raise TrioError("EVIDENCE_CORRUPT")
        import copy
        packet=copy.deepcopy(packet)
        for f in packet["findings"]:
            for revision in f["revisions"]:revision.pop("local_origin",None)
        packet["digest"]=digest({k:v for k,v in packet.items() if k!="digest"})
        approval=digest({"payload_digest":packet["digest"],"destination":output})
        if approve_digest!=approval:return {"schema":"trio.share-preview/v1","destination":output,"digest":packet["digest"],"approval_digest":approval,"payload":packet,"requires_approval":True}
        atomic_json(confined(self.store.root,output),packet)
        return {"schema":"trio.share/v1","digest":packet["digest"],"destination":output}

    def markdown(self,packet):
        def safe(text):
            value=html.escape(re.sub(r"[\x00-\x1f\x7f]",lambda m:"\\u%04x"%ord(m.group()),str(text)))
            for char in "`![]()*_#":value=value.replace(char,"&#"+str(ord(char))+";")
            return value
        lines=["# Review packet", "", "Recorded evidence only; not a live visibility check.", ""]
        for f in packet["findings"]:
            lines.extend(["## "+safe(f["id"]),"", "Conflict: "+str(f["conflict"])+"; stale: "+str(f["stale"]), ""])
            for r in f["revisions"]:lines.extend([safe(r["payload"]["category"])+": "+safe(r["payload"]["rationale"]),""])
            for review in f["reviews"]:lines.extend(["Review: "+safe(review["decision"])+" ("+safe(review["state"])+", "+safe(review["trust"])+")",""])
        for e in packet["evidence"]:
            lines.extend(["Source: "+safe(e["ref"]["component"])+" / "+safe(e["ref"]["snapshot"]),"",safe(e.get("excerpt") or "Excerpt omitted or source unverified."),""])
        lines.extend(["Actions require separate exact authorization.",""])
        return "\n".join(lines)
