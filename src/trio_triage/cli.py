"""CLI adapter over public services. Apache-2.0."""
import argparse,json,os,shutil,sys,tempfile,hashlib
from pathlib import Path
from .errors import TrioError
from .storage import Store,canonical,read_json,atomic_json,confined,digest
from .catalog import catalog
class Parser(argparse.ArgumentParser):
    def error(self,message):raise TrioError("INVALID_INVOCATION",exit_code=2)
def parser():
    p=Parser(prog="trio",description="Local public repository evidence and team triage")
    def common(x,suppress=False):
        d=argparse.SUPPRESS if suppress else None
        x.add_argument("--home",default=d);x.add_argument("--config-location",default=d)
        x.add_argument("--json",action="store_true",default=argparse.SUPPRESS if suppress else False)
        x.add_argument("--max-bytes",type=int,default=argparse.SUPPRESS if suppress else 12000)
    common(p);sub=p.add_subparsers(dest="family",required=True)
    def top(name):x=sub.add_parser(name);common(x,True);return x
    def family(name,leaves):
        x=top(name);ss=x.add_subparsers(dest="leaf",required=True);out={}
        for name in leaves:y=ss.add_parser(name);common(y,True);out[name]=y
        return out
    def opt(x,*flags,**kw):return x.add_argument(*flags,**kw)
    def dataset(x):opt(x,"--dataset",required=True)
    def selection(x):dataset(x);q=x.add_mutually_exclusive_group(required=True);q.add_argument("--snapshot");q.add_argument("--corpus")
    def actor(x):opt(x,"--actor",required=True)
    for name in ("commands","status","doctor","datasets"):top(name)
    x=top("init");opt(x,"--config")
    f=family("repo",["add","list"]);opt(f["add"],"repository");opt(f["add"],"--read-token-env")
    x=top("capture");dataset(x);opt(x,"--kind",choices=["issue","pr"]);opt(x,"--number",type=int);opt(x,"--inventory",action="store_true");opt(x,"--limit",type=int,default=100);opt(x,"--profile",default="discussion",choices=["discussion","pr-context","pr-code","pr-comparison","backlog"]);opt(x,"--request-budget",type=int);opt(x,"--read-token-env")
    x=top("import");opt(x,"--dataset");opt(x,"--scope");opt(x,"--path",required=True);opt(x,"--snapshot",action="append")
    x=top("snapshots");dataset(x)
    f=family("corpus",["plan","run"]);dataset(f["plan"]);opt(f["plan"],"--inventory");opt(f["plan"],"--snapshot",action="append");opt(f["plan"],"--profile",default="discussion");dataset(f["run"]);opt(f["run"],"--corpus",required=True);opt(f["run"],"--read-token-env");opt(f["run"],"--request-budget",type=int)
    f=family("index",["build","info"])
    for x in f.values():selection(x)
    opt(f["build"],"--replace",action="store_true")
    x=top("search");selection(x);opt(x,"--query",required=True);opt(x,"--mode",choices=["ranked","literal"],default="ranked");opt(x,"--cursor");opt(x,"--max-tokens",type=int);opt(x,"--tokenizer-encoding",choices=["cl100k_base","o200k_base"]);opt(x,"--tokenizer-asset")
    x=top("retrieve")
    opt(x,"--ref",required=True)
    opt(x,"--window",type=int,default=4096)
    opt(x,"--byte-offset",type=int,help="UTF-8 byte offset relative to the cited source boundary")
    opt(x,"--max-tokens",type=int)
    opt(x,"--tokenizer-encoding",choices=["cl100k_base","o200k_base"])
    opt(x,"--tokenizer-asset")
    f=family("evidence",["show"]);opt(f["show"],"--ref",required=True)
    x=top("similar");dataset(x);opt(x,"--snapshot",required=True)
    f=family("group",["create","update","show"])
    for k in ("create","update"):
        x=f[k];actor(x);opt(x,"--members",required=True);opt(x,"--notes",default="");opt(x,"--assignee");opt(x,"--status",default="draft",choices=["draft","needs_review","ready","archived"])
    opt(f["update"],"--id",required=True);opt(f["update"],"--parent",action="append",required=True);opt(f["show"],"--id",required=True)
    f=family("finding",["propose","show","review","withdraw-review"])
    x=f["propose"];actor(x);opt(x,"--category",required=True);opt(x,"--items",required=True);opt(x,"--refs",required=True);opt(x,"--rationale",required=True);opt(x,"--author-kind",default="human",choices=["human","agent"]);opt(x,"--id");opt(x,"--parent",action="append");opt(x,"--survivor")
    opt(f["show"],"--id",required=True)
    x=f["review"];actor(x);opt(x,"--id",required=True);opt(x,"--digest",required=True);opt(x,"--decision",required=True,choices=["approve","reject","needs_evidence"])
    x=f["withdraw-review"];actor(x);opt(x,"--id",required=True)
    f=family("team",["export","import","status","resolve"])
    x=f["export"];opt(x,"--id",action="append",required=True);opt(x,"--output",required=True);opt(x,"--approve",action="store_true");opt(x,"--workspace",action="store_true");opt(x,"--approve-digest")
    x=f["import"];opt(x,"--path",required=True);opt(x,"--workspace",action="store_true")
    x=f["resolve"];actor(x);opt(x,"--id",required=True);opt(x,"--parent",action="append",required=True);opt(x,"--rationale",required=True);opt(x,"--selected",required=True)
    x=top("packet");opt(x,"--finding",action="append");opt(x,"--output");ps=x.add_subparsers(dest="leaf");y=ps.add_parser("share");common(y,True);opt(y,"--path",required=True);opt(y,"--output",required=True);opt(y,"--approve-digest")
    f=family("action",["plan","inspect","authorize","execute","reconcile"])
    x=f["plan"];opt(x,"--target",required=True);opt(x,"--expected",required=True);opt(x,"--operation",choices=["comment","close","reopen"],required=True);opt(x,"--text",required=True);opt(x,"--finding-digest");opt(x,"--read-token-env")
    for k in ("inspect","authorize","execute","reconcile"):opt(f[k],"--id",required=True)
    opt(f["reconcile"],"--read-token-env");opt(f["authorize"],"--digest",required=True);actor(f["authorize"]);actor(f["execute"])
    f=family("maintenance",["indexes"]);opt(f["indexes"],"--id",action="append");opt(f["indexes"],"--apply",action="store_true")
    x=top("migrate");opt(x,"--apply",action="store_true")
    return p

def run(a,p):
    command=a.family+(" "+a.leaf if getattr(a,"leaf",None) else "")
    if command=="commands":return catalog(p)
    store=Store(a.home,a.config_location)
    if command=="init":store.init(read_json(a.config) if a.config else None);return {"schema":"trio.init/v1","state_version":1,"writes_enabled":store.config["writes_enabled"]}
    store.require()
    if command in ("status","doctor"):
        with store.db() as db:fts=bool(db.execute("SELECT sqlite_compileoption_used('ENABLE_FTS5')").fetchone()[0])
        return {"schema":"trio."+command+"/v1","initialized":True,"state_version":1,"fts5":fts,"writes_enabled":store.config["writes_enabled"],"live_validation":"NOT_RUN","retention":"no automatic authoritative evidence pruning"}
    from .evidence import EvidenceService
    ev=EvidenceService(store)
    from .search import SearchService
    tokenizer=None
    encoding=getattr(a,"tokenizer_encoding",None);asset=getattr(a,"tokenizer_asset",None)
    if encoding or asset:
        if not encoding or not asset:raise TrioError("TOKENIZER_UNAVAILABLE")
        from .search.tokenizer import load_offline_tokenizer
        tokenizer=load_offline_tokenizer(encoding,asset)
    search=SearchService(store,tokenizer=tokenizer)
    from .triage import TriageService
    triage=TriageService(store)
    from .team import TeamService
    team=TeamService(store)
    from .packets import PacketService
    packet=PacketService(store)
    from .transport import ReadTransport
    if command=="repo add":
        if not __import__("re").fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",a.repository):raise TrioError("SCOPE_DENIED")
        transport=ReadTransport(a.read_token_env,store.config["timeout"]);profile=transport.namespace()
        data=transport.get("/repos/"+a.repository)
        if data.get("private") is not False:raise TrioError("PUBLIC_REPO_REQUIRED")
        from .team import now
        return ev.enroll({"format_version":1,"host":"github.com","repository_id":data["id"],"full_name":data["full_name"],"visibility":"public","observed_at":now(),"profile":profile})
    if command in ("repo list","datasets"):return {"schema":"trio.datasets/v1","datasets":ev.datasets()}
    if command=="snapshots":return {"schema":"trio.snapshots/v1","snapshots":ev.snapshots(a.dataset)}
    if command=="import":
        if not a.dataset and not a.scope:raise TrioError("INVALID_INVOCATION",exit_code=2)
        selected=a.dataset
        if a.scope:
            enrolled=ev.enroll(read_json(a.scope))["dataset"]
            if selected is not None and selected!=enrolled:raise TrioError("IDENTITY_MISMATCH")
            selected=enrolled
        return ev.import_cache(selected,a.path,a.snapshot)
    if command=="capture":
        transport=ReadTransport(a.read_token_env,store.config["timeout"])
        if a.inventory:
            if a.kind is not None or a.number is not None:raise TrioError("INVALID_INVOCATION",exit_code=2)
            return ev.capture_inventory(a.dataset,transport,limit=a.limit,budget=a.request_budget)
        if a.kind is None or a.number is None:raise TrioError("INVALID_INVOCATION",exit_code=2)
        return ev.capture(a.dataset,a.kind,a.number,transport,profile=a.profile,budget=a.request_budget)
    if command=="corpus plan":
        if bool(a.inventory)==bool(a.snapshot):raise TrioError("INVALID_INVOCATION",exit_code=2)
        inventory=ev.combine_snapshots(a.dataset,a.snapshot)["snapshot"] if a.snapshot else a.inventory
        return ev.freeze_corpus(a.dataset,inventory,profile=a.profile)
    if command=="corpus run":return ev.run_corpus(a.dataset,a.corpus,ReadTransport(a.read_token_env,store.config["timeout"]),budget=a.request_budget)
    if command in ("index build","index info","search"):
        selection={"snapshot":a.snapshot,"corpus":a.corpus}
        if command=="index build":return search.build(a.dataset,selection,replace=a.replace)
        if command=="index info":return search.info(a.dataset,selection)
        return search.query(a.dataset,selection,a.query,mode=a.mode,max_bytes=a.max_bytes,max_tokens=a.max_tokens,cursor=a.cursor)
    if command in ("retrieve","evidence show"):
        ref=read_json(a.ref)
        return search.retrieve(ref,max_bytes=a.max_bytes,max_tokens=getattr(a,"max_tokens",None),window=getattr(a,"window",4096),byte_offset=getattr(a,"byte_offset",None))
    if command=="similar":
        from .contracts import strict_json
        manifest=ev.snapshot(a.dataset,a.snapshot);items=[];source=ev.source(a.dataset)
        for record in manifest["items"][:100]:
            d=record["components"].get("summary")
            if not d or not d["object"]:continue
            summary=strict_json(source.object("summary",d,record["identity"]["kind"]))
            items.append(dict(record["identity"],repository=manifest["repository"],revision=record["revision"],title=summary.get("title","")))
        return {"schema":"trio.similar/v1","candidates":triage.similar(items)}
    if command=="finding propose":return triage.propose(a.category,read_json(a.items),read_json(a.refs),a.rationale,a.actor,a.author_kind,a.id,a.parent,read_json(a.survivor) if a.survivor else None)
    if command=="finding show":return triage.show(a.id)
    if command=="finding review":return triage.review(a.id,a.digest,a.decision,a.actor)
    if command=="finding withdraw-review":return triage.withdraw(a.id,a.actor)
    if command in ("group create","group update"):return triage.group(read_json(a.members),a.actor,a.notes,a.assignee,a.status,getattr(a,"id",None),getattr(a,"parent",None))
    if command=="group show":return {"schema":"trio.group/v1","heads":[team.get(x) for x in team.heads(a.id)]}
    if command=="team status":return team.status()
    if command=="team export":return team.export_workspace(a.output,a.id,a.approve_digest) if a.workspace else team.export(a.output,a.id,a.approve)
    if command=="team import":return team.import_workspace(a.path) if a.workspace else team.import_bundle(a.path)
    if command=="team resolve":return team.resolve(a.id,a.parent,a.rationale,a.actor,a.selected)
    if command=="packet":
        if not a.finding:raise TrioError("INVALID_INVOCATION",exit_code=2)
        return packet.create(a.finding,a.output)
    if command=="packet share":return packet.share(read_json(a.path),a.output,a.approve_digest)
    if command.startswith("action"):
        from . import actions
        if command=="action plan":
            target=read_json(a.target);expected=read_json(a.expected)
            # Planning performs current read scope/identity validation without effect.
            from .actions.service import _validate_target
            _validate_target(target)
            remote=ReadTransport(a.read_token_env,store.config["timeout"]).current_target(target)
            if any(remote.get(k)!=v for k,v in expected.items()):raise TrioError("PLAN_CHANGED")
            return actions.plan(store,target,a.operation,a.text,expected,finding_digest=a.finding_digest)
        if command=="action inspect":return actions.inspect(store,a.id)
        if command=="action authorize":return actions.authorize(store,a.id,a.digest,a.actor)
        if command=="action reconcile":return actions.reconcile(store,a.id,ReadTransport(a.read_token_env,store.config["timeout"]))
        # No live mutation adapter is enabled until authorized disposable live validation.
        raise TrioError("ACTION_DISABLED","Live transport experimental; validation NOT_RUN")
    if command=="maintenance indexes":
        root=store.cache_root/"indexes";allfiles=[x for x in root.rglob("*.sqlite") if x.is_file()] if root.exists() else []
        selected=[x for x in allfiles if a.id and x.stem in a.id]
        if any(x.is_symlink() for x in selected):raise TrioError("SCOPE_DENIED")
        if a.apply:
            for x in selected:x.unlink()
        return {"schema":"trio.maintenance/v1","apply":a.apply,"indexes":[x.relative_to(root).as_posix() for x in selected],"authoritative_evidence":"retained"}
    if command=="migrate":
        import sqlite3
        with store.write_lock(),tempfile.TemporaryDirectory() as temp:
            copy=Path(temp)/"state.sqlite"
            with store.db() as source,sqlite3.connect(copy) as target:source.backup(target)
            before=hashlib.sha256(copy.read_bytes()).hexdigest()
            if a.apply:
                from .evidence.service import atomic_bytes
                backup=store.root/("state-v1-"+before+".backup");atomic_bytes(backup,copy.read_bytes())
                if hashlib.sha256(backup.read_bytes()).hexdigest()!=before:raise TrioError("EVIDENCE_CORRUPT")
            return {"schema":"trio.migrate/v1","from_version":1,"to_version":1,"changes":0,"applied":a.apply,"rehearsed":True}

    raise TrioError("INVALID_INVOCATION",exit_code=2)

def main(argv=None):
    p=parser();code=0;maximum=12000;json_mode="--json" in (argv if argv is not None else sys.argv[1:])
    try:
        a=p.parse_args(argv);json_mode=a.json;maximum=a.max_bytes
        if type(maximum) is not int or not 1024<=maximum<=1048576:raise TrioError("INVALID_INVOCATION",exit_code=2)
        token_limit=getattr(a,"max_tokens",None)
        if token_limit is not None and token_limit<128:raise TrioError("INVALID_INVOCATION","minimum CLI token setting is 128 for bounded errors",exit_code=2)
        result=run(a,p)
        if isinstance(result,dict) and "schema" not in result:result={"schema":"trio."+a.family+("-"+a.leaf if getattr(a,"leaf",None) else "")+"/v1",**result}
        if isinstance(result,dict):
            coverage=result.get("coverage")
            if result.get("conflict") or result.get("conflicts") or isinstance(coverage,dict) and (coverage.get("gaps") or coverage.get("incomplete")):code=1
            inventory=result.get("inventory")
            if isinstance(inventory,dict) and (inventory.get("reason") or inventory.get("truncated") or inventory.get("pagination_complete") is False):code=1
            steps=result.get("steps",{})
            if any(v.get("outcome") in ("unknown","failed") for v in steps.values()):code=4

        raw=canonical(result)+b"\n"
        if len(raw)>maximum:
            from .catalog import LEAVES
            command=a.family+(" "+a.leaf if getattr(a,"leaf",None) else "")
            effect=LEAVES[command][0]
            if "write-local" in effect and not (command in ("team export","packet share") and result.get("requires_approval")):
                identifiers={k:result[k] for k in ("event_id","entity_id","dataset","snapshot","corpus","operation_id","digest") if k in result}
                result={"schema":result["schema"],"completed":True,"output_truncated":True,"identifiers":identifiers,"diagnostic":"Inspect the completed record with a larger response budget"}
                code=1;raw=canonical(result)+b"\n"
                if len(raw)>maximum:raise TrioError("BUDGET_TOO_SMALL")
            else:raise TrioError("BUDGET_TOO_SMALL","Increase --max-bytes for the complete response")
    except TrioError as e:
        code=e.exit_code;result={"schema":"trio.error/v1","error":{"code":e.code,"message":e.message}};raw=canonical(result)+b"\n"
    except KeyboardInterrupt:
        code=1;result={"schema":"trio.error/v1","error":{"code":"CANCELLED","message":"Stopped; inspect durable acquisition checkpoints before explicit resume"}};raw=canonical(result)+b"\n"
    except SystemExit:raise
    except Exception:
        code=5;result={"schema":"trio.error/v1","error":{"code":"INTERNAL_ERROR","message":"Operation failed; no source payload retained"}};raw=canonical(result)+b"\n"
    if json_mode:sys.stdout.buffer.write(raw)
    else:print(json.dumps(result,ensure_ascii=True,indent=2))
    return code
if __name__=="__main__":raise SystemExit(main())
