"""CLI adapter over public services. Apache-2.0."""
import argparse,json,os,shutil,sys,tempfile,hashlib
from pathlib import Path
from .errors import TrioError
from .storage import Store,canonical,read_json,atomic_json,confined,digest
from .catalog import catalog
class Parser(argparse.ArgumentParser):
    def error(self,message):raise TrioError("INVALID_INVOCATION",exit_code=2)
def parser():
    p=Parser(prog="trio",description="Public GitHub operations, contributions, evidence and team review")
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
    opt(sub.choices["commands"],"--command")
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
    f=family("inventory",["sync","snapshots","list","show","drift"])
    x=f["sync"];opt(x,"--token-env",required=True);opt(x,"--organization");opt(x,"--repository-limit",type=int,default=100);opt(x,"--item-limit",type=int,default=1000);opt(x,"--request-budget",type=int,default=100)
    for k in ("list","show"):opt(f[k],"--snapshot",required=True)
    x=f["list"];opt(x,"--kind",default="repositories",choices=["repositories","forks","pulls","issues","notifications","workflow_runs","releases"]);opt(x,"--repository");opt(x,"--limit",type=int,default=20);opt(x,"--cursor")
    opt(f["show"],"--repository",required=True);opt(f["drift"],"--before",required=True);opt(f["drift"],"--after",required=True)
    f=family("ops",["policy","plan","inspect","approve","execute","reconcile"])
    opt(f["policy"],"--path")
    x=f["plan"];opt(x,"--token-env",required=True);opt(x,"--operation",required=True,choices=["notification-ack","issue-label","issue-comment","issue-close","issue-reopen","pr-ready","pr-close","pr-update-branch","pr-merge"]);opt(x,"--repository");opt(x,"--number",type=int);opt(x,"--thread");opt(x,"--text");opt(x,"--labels",help="JSON file containing the exact replacement label list");opt(x,"--merge-method",default="merge",choices=["merge","squash","rebase"])
    for k in ("inspect","approve","execute","reconcile"):opt(f[k],"--id",required=True)
    for k in ("plan","execute","reconcile"):
        if k!="plan":opt(f[k],"--token-env",required=True)
    for k in ("approve","execute"):actor(f[k])
    opt(f["approve"],"--digest",required=True)
    f=family("contribution",["intake","list","show","acquire","patch","validate","plan","inspect","approve","publish","reconcile","revise","refresh"])
    x=f["intake"];opt(x,"--repository",required=True);q=x.add_mutually_exclusive_group(required=True);q.add_argument("--issue",type=int);q.add_argument("--finding")
    for k in f:
        if k not in ("intake","list"):opt(f[k],"--id",required=True)
    for k in ("intake","acquire","plan","publish","reconcile","revise","refresh"):opt(f[k],"--token-env",required=True)
    for k in ("acquire","refresh"):opt(f[k],"--base",required=True);opt(f[k],"--base-branch",required=True);opt(f[k],"--request-budget",type=int,default=1000)
    opt(f["patch"],"--path",required=True)
    x=f["validate"];opt(x,"--commands",required=True,help="JSON file containing explicitly selected argv arrays");opt(x,"--image",required=True);opt(x,"--timeout",type=int,default=60);opt(x,"--memory-mb",type=int,default=512);opt(x,"--pids",type=int,default=64);opt(x,"--cpus",type=int,default=1)
    for k in ("plan","revise"):
        x=f[k];opt(x,"--branch",required=True);opt(x,"--title",required=True);opt(x,"--body",required=True,help="UTF-8 file containing exact pull request body");opt(x,"--author-name",required=True);opt(x,"--author-email",required=True);opt(x,"--message");opt(x,"--mode",default="direct",choices=["direct","fork"]);opt(x,"--fork-owner")
    for k in ("approve","publish"):actor(f[k])
    opt(f["approve"],"--digest",required=True)
    return p

def run(a,p):
    command=a.family+(" "+a.leaf if getattr(a,"leaf",None) else "")
    if command=="commands":return catalog(p,getattr(a,"command",None))
    store=Store(a.home,a.config_location)
    if command=="init":store.init(read_json(a.config) if a.config else None);return {"schema":"trio.init/v1","state_version":1,"writes_enabled":store.config["writes_enabled"]}
    store.require()
    if command.startswith(("inventory ","ops ","contribution ")):
        from .operations import GitHubTransport,MaintenanceService,OperationState
        transport=GitHubTransport(a.token_env,store.config["timeout"]) if getattr(a,"token_env",None) else None
        if command.startswith("inventory "):
            from .inventory import InventoryService
            service=InventoryService(store)
            if a.leaf=="sync":return service.sync(transport,a.organization,a.repository_limit,a.item_limit,a.request_budget)
            if a.leaf=="snapshots":return service.snapshots()
            if a.leaf=="list":return service.list(a.snapshot,a.kind,a.repository,a.limit,a.cursor,a.max_bytes)
            if a.leaf=="show":return service.show(a.snapshot,a.repository)
            if a.leaf=="drift":return service.drift(a.before,a.after)
        if command.startswith("ops "):
            service=MaintenanceService(store)
            if a.leaf=="policy":return service.configure(read_json(a.path)) if a.path else {"schema":"trio.operations-policy/v1","policy":service.policy()}
            if a.leaf=="plan":return service.plan(transport,a.operation,a.repository,a.number,a.thread,a.text,read_json(a.labels) if a.labels else None,a.merge_method)
            if a.leaf=="inspect":return service.inspect(a.id)
            if a.leaf=="approve":return service.approve(a.id,a.digest,a.actor)
            if a.leaf=="execute":return service.execute(a.id,a.actor,transport)
            if a.leaf=="reconcile":return service.reconcile(a.id,transport)
        if command.startswith("contribution "):
            from .contributions import ContributionService,MAX_PATCH
            service=ContributionService(store)
            def bytes_file(path,limit):
                selected=Path(path).absolute()
                if any(x.is_symlink() for x in [selected,*selected.parents]) or not selected.is_file():raise TrioError("UNSAFE_PATH",exit_code=2)
                with selected.open("rb") as stream:raw=stream.read(limit+1)
                if len(raw)>limit:raise TrioError("RESOURCE_LIMIT")
                return raw
            if a.leaf=="intake":return service.intake(transport,a.repository,a.issue,a.finding)
            if a.leaf=="list":return service.list()
            if a.leaf=="show":return service.show(a.id)
            if a.leaf=="acquire":return service.acquire(a.id,transport,a.base,a.base_branch,a.request_budget)
            if a.leaf=="patch":return service.patch(a.id,bytes_file(a.path,MAX_PATCH))
            if a.leaf=="validate":return service.validate(a.id,read_json(a.commands),a.image,timeout=a.timeout,memory_mb=a.memory_mb,pids=a.pids,cpus=a.cpus)
            if a.leaf in ("plan","revise"):return service.plan(a.id,transport,a.branch,a.title,bytes_file(a.body,60000).decode("utf-8"),a.author_name,a.author_email,a.message,a.mode,a.fork_owner,revision=a.leaf=="revise")
            if a.leaf=="inspect":return service.inspect_plan(a.id)
            if a.leaf=="approve":return service.approve(a.id,a.digest,a.actor,"publication-plans")
            if a.leaf=="publish":return service.publish(a.id,a.actor,transport)
            if a.leaf=="reconcile":return service.reconcile(a.id,transport)
            if a.leaf=="refresh":return service.refresh(a.id,transport,a.base,a.base_branch,a.request_budget)
    if command in ("status","doctor"):
        with store.db() as db:fts=bool(db.execute("SELECT sqlite_compileoption_used('ENABLE_FTS5')").fetchone()[0])
        return {"schema":"trio."+command+"/v1","initialized":True,"state_version":1,"fts5":fts,"writes_enabled":store.config["writes_enabled"],"operations_policy":__import__("trio_triage.operations",fromlist=["OperationState"]).OperationState(store).policy(),"live_validation":"NOT_RUN","retention":"no automatic authoritative evidence pruning"}
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
            if result.get("complete") is False or result.get("outcome") in {"pending","stopped","uncertain","failed"}:code=4 if result.get("outcome") in {"uncertain","failed"} else 1
            steps=result.get("steps",{})
            if any(v.get("outcome") in ("unknown","failed","uncertain") for v in steps.values()):code=4

        raw=canonical(result)+b"\n"
        if len(raw)>maximum:
            from .catalog import LEAVES
            command=a.family+(" "+a.leaf if getattr(a,"leaf",None) else "")
            effect=LEAVES[command][0]
            if "write-local" in effect and not (command in ("team export","packet share") and result.get("requires_approval")):
                identifiers={k:result[k] for k in ("id","event_id","entity_id","dataset","snapshot","corpus","operation_id","digest","seal_digest","tree","base") if k in result}
                status={k:result[k] for k in ("outcome","error","complete") if k in result}
                result={"schema":result["schema"],"completed":code==0,"record_written":True,"output_truncated":True,"identifiers":identifiers,**status,"diagnostic":"Inspect the durable record with a larger response budget"}
                code=code or 1;raw=canonical(result)+b"\n"
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
