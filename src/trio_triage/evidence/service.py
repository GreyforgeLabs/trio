# SPDX-License-Identifier: Apache-2.0
import contextlib
import fcntl
import hashlib
import os
import shutil
import tempfile
import time
from pathlib import Path
from .. import contracts as c
from ..errors import TrioError
from ..storage import confined
from ..search.cache_source import TriageCache, PROFILES, SCOPES
from ..search.projections import reproduce, pointer_get, _boundary


def safe_error(error):
    if isinstance(error, TrioError):
        return error
    return TrioError("EVIDENCE_CORRUPT", "evidence validation failed")


def atomic_bytes(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise TrioError("SCOPE_DENIED")
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if os.path.exists(name): os.unlink(name)


def sealed(value):
    return dict(value, checksum=c.digest(c.canonical(value)))


class EvidenceService:
    def __init__(self, store):
        self.store = store
        self.store.require()

    def path(self, dataset, *parts):
        c.checked_id(dataset)
        return confined(self.store.root, Path("datasets") / dataset / Path(*parts))

    def _read(self, path, maximum=None):
        maximum = maximum or self.store.config["metadata_max_bytes"]
        if not path.is_file() or path.is_symlink():
            raise TrioError("EVIDENCE_MISSING")
        if path.stat().st_size > maximum:
            raise TrioError("RESOURCE_LIMIT")
        with path.open("rb") as stream: raw = stream.read(maximum + 1)
        if len(raw) > maximum: raise TrioError("RESOURCE_LIMIT")
        return raw

    def _json(self, path):
        return c.strict_json(self._read(path))

    @contextlib.contextmanager
    def _lock(self):
        path = confined(self.store.root, "evidence.lock")
        with path.open("a+b") as stream:
            os.chmod(path, 0o600)
            fcntl.flock(stream, fcntl.LOCK_EX)
            try: yield
            finally: fcntl.flock(stream, fcntl.LOCK_UN)

    def _usage(self, root):
        used = 0
        if root.exists():
            for directory, dirs, files in os.walk(root, followlinks=False):
                for name in (*dirs, *files):
                    p = Path(directory) / name
                    if p.is_symlink(): raise TrioError("SCOPE_DENIED")
                for name in files:
                    st = (Path(directory)/name).stat()
                    used += max(st.st_size, st.st_blocks * 512)
        return used

    def _admit(self, dataset, amount):
        config = self.store.config
        reserve = config["reserve_bytes"]
        if amount + reserve + self._usage(self.path(dataset)) > config["dataset_max_bytes"] or amount + reserve + self._usage(self.store.root) > config["state_max_bytes"]:
            raise TrioError("RESOURCE_LIMIT")
        if shutil.disk_usage(self.store.root).free < amount + reserve:
            raise TrioError("RESOURCE_LIMIT")

    def enroll(self, scope):
        scope = c.validate_scope(scope)
        identity = dict(host=scope["host"], full_name=scope["full_name"], database_id=scope["repository_id"], node_id=None)
        dataset = c.digest(c.canonical([scope["host"], scope["repository_id"], scope.get("profile")]))
        with self._lock():
            path=self.path(dataset,"scope.json")
            metadata_path=self.path(dataset,"evidence","cache.json")
            if path.exists():
                current=self.scope(dataset)
                if any(current.get(k)!=scope.get(k) for k in ("host","repository_id","full_name","profile")):raise TrioError("IDENTITY_MISMATCH")
                if c.timestamp(scope["observed_at"])<c.timestamp(current["observed_at"]):raise TrioError("IDENTITY_MISMATCH")
            if metadata_path.exists():
                metadata=self._json(metadata_path)
                try:
                    c.fields(metadata,("schema_version","artifact","repository"));c.version(metadata,"evidence-cache");c.same_repository(identity,metadata["repository"])
                except (ValueError,KeyError,TypeError):raise TrioError("IDENTITY_MISMATCH") from None
            else:
                self._admit(dataset,8192)
                atomic_bytes(metadata_path,c.canonical(dict(schema_version=1,artifact="evidence-cache",repository=identity)).encode())
            # scope.json is the enrollment commit record, published only after cache metadata.
            atomic_bytes(path,c.canonical(scope).encode())
        return {"schema":"trio.dataset/v1", "dataset":dataset, "repository":scope, "visibility_basis":"recorded observation"}

    def scope(self, dataset):
        return c.validate_scope(self._json(self.path(dataset, "scope.json")))

    def datasets(self, limit=100):
        if type(limit) is not int or not 1 <= limit <= 100: raise TrioError("RESOURCE_LIMIT")
        root = confined(self.store.root, "datasets")
        values = []
        if root.exists():
            for p in sorted(root.iterdir()):
                if p.is_symlink(): raise TrioError("SCOPE_DENIED")
                if len(values) == limit: break
                if not (p/"scope.json").exists():continue
                values.append({"dataset":c.checked_id(p.name), "repository":self.scope(p.name)})
        return values

    def source(self, dataset):
        scope = self.scope(dataset)
        try:
            source = TriageCache(self.path(dataset, "evidence"), max_object_bytes=self.store.config["object_max_bytes"], max_metadata_bytes=self.store.config["metadata_max_bytes"])
            if any(source.repository[k] != v for k,v in dict(host=scope["host"], full_name=scope["full_name"], database_id=scope["repository_id"]).items()):
                raise TrioError("IDENTITY_MISMATCH")
            return source
        except (OSError, ValueError) as error: raise safe_error(error) from None

    def snapshot(self, dataset, identifier):
        try: return self.source(dataset).manifest(identifier)
        except (OSError, ValueError) as error: raise safe_error(error) from None

    def snapshots(self, dataset, limit=100):
        if type(limit) is not int or not 1 <= limit <= 100: raise TrioError("RESOURCE_LIMIT")
        root = self.path(dataset, "evidence", "snapshots")
        return [{"snapshot":p.stem, "coverage":self.coverage(self.snapshot(dataset,p.stem))} for p in sorted(root.glob("*.json"))[:limit]]

    def publish(self, dataset, manifest, payloads):
        """Only validated supplied source bytes; no donor current-item globals or ledgers."""
        source = self.source(dataset)
        try:
            c.validate_snapshot(manifest); c.same_repository(source.repository, manifest["repository"])
            refs = {}
            for record in manifest["items"]:
                if record["identity"]["database_id"] is None: raise TrioError("IDENTITY_MISMATCH")
                for name, descriptor in record["components"].items():
                    ref = descriptor["object"]
                    if ref is None: continue
                    filename = c.object_name(ref); refs[filename] = ref
                    payload = payloads.get(filename)
                    if payload is None: payload = source.object(name,descriptor,record["identity"]["kind"])
                    if ref["bytes"] > self.store.config["object_max_bytes"]: raise TrioError("RESOURCE_LIMIT")
                    c.validate_payload(name,descriptor,record["identity"]["kind"],payload)
                    if ref["format"] == "json": c.strict_json(payload)
            if payloads.keys() - refs.keys(): raise TrioError("EVIDENCE_CORRUPT")
            raw = c.canonical(manifest).encode()
            if len(raw)>self.store.config["metadata_max_bytes"]: raise TrioError("RESOURCE_LIMIT")
            with self._lock():
                self._admit(dataset,len(raw)+sum(ref["bytes"]+4096 for ref in refs.values()))
                for filename, ref in refs.items():
                    path = self.path(dataset,"evidence","objects",filename)
                    if path.exists():
                        existing = self._read(path,self.store.config["object_max_bytes"])
                        if hashlib.sha256(existing).hexdigest()!=ref["sha256"] or len(existing)!=ref["bytes"]: raise TrioError("EVIDENCE_CORRUPT")
                    else: atomic_bytes(path,payloads[filename].encode())
                path = self.path(dataset,"evidence","snapshots",manifest["snapshot_id"]+".json")
                if path.exists():
                    if self._read(path)!=raw: raise TrioError("EVIDENCE_CORRUPT")
                else: atomic_bytes(path,raw)
            return {"schema":"trio.capture/v1", "dataset":dataset,"snapshot":manifest["snapshot_id"],"coverage":self.coverage(manifest),"repository":self.scope(dataset)}
        except (OSError, ValueError, KeyError, TypeError) as error: raise safe_error(error) from None

    def import_cache(self, dataset, path, snapshots=None):
        """Explicit directory-only public donor import. Never copy local journals/config."""
        incoming = Path(path).absolute()
        if any(p.is_symlink() for p in [incoming,*incoming.parents]): raise TrioError("SCOPE_DENIED")
        if not incoming.is_dir(): raise TrioError("UNSUPPORTED_FORMAT")
        try:
            cache = TriageCache(incoming,max_object_bytes=self.store.config["object_max_bytes"],max_metadata_bytes=self.store.config["metadata_max_bytes"])
            c.same_repository(self.source(dataset).repository,cache.repository)
            chosen = list(snapshots) if snapshots is not None else sorted(p.stem for p in cache.path("snapshots").glob("*.json"))
            if not chosen or len(chosen)>100: raise TrioError("RESOURCE_LIMIT")
            prepared=[]; staged=0
            for identifier in chosen:
                manifest=cache.manifest(identifier); payloads={}
                for record in manifest["items"]:
                    for name,descriptor in record["components"].items():
                        if descriptor["object"]:
                            payloads[c.object_name(descriptor["object"])]=cache.object(name,descriptor,record["identity"]["kind"])
                staged+=sum(len(p.encode()) for p in payloads.values())+len(c.canonical(manifest).encode())
                if staged>self.store.config["verified_max_bytes"]:raise TrioError("RESOURCE_LIMIT")
                self._admit(dataset,staged)
                prepared.append((manifest,payloads))
            # Validate the complete selected import before publishing any snapshot.
            if self.source(dataset).repository["node_id"] is None and cache.repository["node_id"] is not None:
                with self._lock():
                    atomic_bytes(self.path(dataset,"evidence","cache.json"),c.canonical(dict(schema_version=1,artifact="evidence-cache",repository=cache.repository)).encode())
            results=[self.publish(dataset,m,p) for m,p in prepared]
            return {"schema":"trio.import/v1","dataset":dataset,"snapshots":[r["snapshot"] for r in results],"source_unchanged":True}
        except (OSError, ValueError,KeyError,TypeError) as error: raise safe_error(error) from None

    def freeze_corpus(self, dataset, inventory, *, scope="open-items", profile="discussion", max_age=86400):
        try:
            if scope not in SCOPES or profile not in PROFILES or type(max_age) is not int or max_age<0: raise TrioError("SCOPE_DENIED")
            manifest=self.snapshot(dataset,inventory)
            members=sorted([r["identity"] for r in manifest["items"] if r["identity"]["kind"] in SCOPES[scope]],key=lambda r:(r["kind"],r["number"]))
            if len(members)>self.store.config["corpus_size"]: raise TrioError("RESOURCE_LIMIT")
            plan=sealed(dict(schema_version=1,artifact="evidence-corpus-plan",repository=manifest["repository"],inventory_snapshot=inventory,scope=scope,profile=profile,max_age=max_age,members=members))
            states={}
            for identity in members:
                record=next(r for r in manifest["items"] if r["identity"]==identity)
                complete=all(name in record["components"] and record["components"][name]["status"] in ("complete","not_applicable") for name in PROFILES[profile])
                states[identity["kind"]+":"+str(identity["number"])]=dict(attempts=1,snapshot_id=inventory,outcome="complete" if complete else "gaps",error=None)
            state=sealed(dict(schema_version=1,artifact="evidence-corpus-state",plan_id=plan["checksum"],updated_at=c.now(),status="finished",items=states,last_run=None))
            with self._lock():
                self._admit(dataset,len(c.canonical(plan).encode())+len(c.canonical(state).encode())+8192)
                atomic_bytes(self.path(dataset,"evidence","corpora",plan["checksum"]+".plan.json"),c.canonical(plan).encode())
                atomic_bytes(self.path(dataset,"evidence","corpora",plan["checksum"]+".state.json"),c.canonical(state).encode())
            selected=self.source(dataset).select(corpus=plan["checksum"])
            return {"schema":"trio.corpus/v1","dataset":dataset,"corpus":plan["checksum"],"checkpoint":selected.checkpoint,"coverage":selected.coverage,"enumeration":self.inventory_observation(dataset,inventory)}
        except (OSError,ValueError,KeyError,TypeError) as error: raise safe_error(error) from None

    def resolve_ref(self, ref):
        required={"schema","dataset","repository","identity","snapshot","component","object","revision","locator","excerpt_sha256"}
        if not isinstance(ref,dict) or set(ref)!=required or ref["schema"]!="trio.evidence-ref/v1": raise TrioError("EVIDENCE_CORRUPT")
        try:
            source=self.source(ref["dataset"]); manifest=source.manifest(ref["snapshot"])
            record=next(r for r in manifest["items"] if r["identity"]==ref["identity"])
            desc=record["components"][ref["component"]]
            if ref["repository"]!=manifest["repository"] or ref["object"]!=desc["object"] or ref["revision"]!=desc["revision"]: raise TrioError("EVIDENCE_CORRUPT")
            payload=source.object(ref["component"],desc,ref["identity"]["kind"])
            text=reproduce(payload,ref["locator"])
            if c.digest(text)!=ref["excerpt_sha256"]: raise TrioError("EVIDENCE_CORRUPT")
            return {"schema":"trio.evidence/v1","ref":ref,"text":text,"verified":True,"visibility_basis":"captured public observation; no live check"}
        except (OSError,ValueError,KeyError,TypeError,StopIteration,IndexError) as error: raise safe_error(error) from None

    def capture(self, dataset, kind, number, transport, *, profile="discussion", budget=None, resume=True):
        """Bounded read-only transport injection; durable local page checkpoints.

        transport.get receives only locally constructed GitHub paths and returns
        decoded JSON or UTF-8 diff text. It must reject redirects and classify
        throttling with a safe TrioError; no transport payload is retained on error.
        """
        if kind not in ("issue","pr") or type(number) is not int or number<1 or profile not in PROFILES: raise TrioError("SCOPE_DENIED")
        budget=self.store.config["request_budget"] if budget is None else budget
        if type(budget) is not int or not 1<=budget<=10000: raise TrioError("RESOURCE_LIMIT")
        source=self.source(dataset); repo=source.repository; base="/repos/"+repo["full_name"]
        calls=0;cancelled=False
        cooldown=confined(self.store.root,Path("acquisition")/(c.digest(c.canonical(self.scope(dataset).get("profile") or "anonymous"))+".json"))
        if self.path(dataset,"local","suspension.json").exists():raise TrioError("SCOPE_DENIED")
        def get(path,method="get",after=None):
            nonlocal calls,cancelled
            if cancelled:raise TrioError("CANCELLED")
            if calls>=budget: raise TrioError("REQUEST_BUDGET")
            if cooldown.exists() and self._json(cooldown).get("until",0)>time.time():raise TrioError("THROTTLED")
            calls+=1
            try:
                if method=="namespace":return transport.namespace()
                if method=="closing_page":return transport.closing_page(path,after)
                return getattr(transport,method)(path)
            except KeyboardInterrupt:
                cancelled=True
                raise TrioError("CANCELLED") from None
            except TrioError as error:
                if error.code=="THROTTLED":
                    delay=getattr(error,"retry_after",60)
                    if type(delay) is not int or not 1<=delay<=86400:delay=60
                    with self._lock():atomic_bytes(cooldown,c.canonical(dict(schema="trio.cooldown/v1",until=time.time()+delay)).encode())
                raise
        expected_profile=self.scope(dataset).get("profile")
        if hasattr(transport,"namespace"):
            observed_profile=transport.namespace() if getattr(transport,"token",object()) is None else get(None,method="namespace")
        else:
            observed_profile=None
        if observed_profile!=expected_profile:raise TrioError("IDENTITY_MISMATCH","read account namespace differs from enrolled dataset")
        observed=get(base)
        if not isinstance(observed,dict) or observed.get("private") is not False or observed.get("visibility","public")!="public":
            self.suspend(dataset,"known privacy transition")
            raise TrioError("PUBLIC_REPO_REQUIRED")
        if type(observed.get("id")) is not int or observed["id"]!=repo["database_id"] or observed.get("full_name")!=repo["full_name"]: raise TrioError("IDENTITY_MISMATCH")
        summary_path=base+("/pulls/" if kind=="pr" else "/issues/")+str(number)
        summary=get(summary_path)
        if repo["node_id"] is None and isinstance(observed.get("node_id"),str):
            repo=dict(repo,node_id=observed["node_id"])
            with self._lock():atomic_bytes(self.path(dataset,"evidence","cache.json"),c.canonical(dict(schema_version=1,artifact="evidence-cache",repository=repo)).encode())
        if not isinstance(summary,dict) or type(summary.get("id")) is not int or summary["id"]<1 or type(summary.get("number")) is not int or summary.get("number")!=number or (kind=="issue" and "pull_request" in summary): raise TrioError("IDENTITY_MISMATCH")
        identity=dict(kind=kind,number=number,database_id=summary["id"],node_id=summary.get("node_id"))
        revision=dict(updated_at=summary.get("updated_at"),base_sha=None,head_sha=None)
        if kind=="pr":
            for name in ("base","head"):
                branch=summary.get(name,{})
                linked=branch.get("repo")
                if not isinstance(linked,dict) or linked.get("private") is not False or linked.get("visibility","public")!="public": raise TrioError("PUBLIC_REPO_REQUIRED")
                if name=="base" and (linked.get("id")!=repo["database_id"] or linked.get("full_name")!=repo["full_name"]): raise TrioError("IDENTITY_MISMATCH")
                if type(linked.get("id")) is not int or not isinstance(linked.get("full_name"),str) or not c.REPO_RE.fullmatch(linked["full_name"]): raise TrioError("IDENTITY_MISMATCH")
                # Public linked scope is independently checked before requesting PR code.
                linked_live=get("/repos/"+linked["full_name"])
                if linked_live.get("private") is not False or linked_live.get("id")!=linked["id"] or linked_live.get("full_name")!=linked["full_name"]: raise TrioError("PUBLIC_REPO_REQUIRED")
                revision[name+"_sha"]=branch.get("sha")
        c.validate_revision(revision); started=c.now(); summary=dict(summary)
        summary["state"]="merged" if kind=="pr" and summary.get("merged") is True else summary.get("state","unknown")
        job_id=c.digest(c.canonical([dataset,identity,revision,profile]))
        job_path=self.path(dataset,"local","capture-"+job_id+".json")
        saved={"schema":"trio.capture-job/v1","dataset":dataset,"identity":identity,"revision":revision,"profile":profile,"pages":{}}
        if resume and job_path.exists():
            old=self._json(job_path)
            if old.get("checksum")!=c.digest(c.canonical({k:v for k,v in old.items() if k!="checksum"})) or any(old.get(k)!=saved[k] for k in ("schema","dataset","identity","revision","profile")): raise TrioError("EVIDENCE_CORRUPT")
            saved["pages"]=old["pages"]
        payloads={}; components={}; requested=sorted(PROFILES[profile]); ordered=sorted(requested,key=lambda n:(0 if n=="summary" else 1 if n=="files" else 3 if n=="diff" else 2,n))
        from .read_contract import ReadFailure
        class Reader:
            def get(inner,path):
                try:data=get("/"+path.lstrip("/"))
                except TrioError as error:raise ReadFailure(error.code) from None
                rows=data if isinstance(data,list) else data.get("check_suites",data.get("check_runs",[])) if isinstance(data,dict) else []
                page=int(path.split("page=")[-1]) if "page=" in path else 1
                more=len(rows)==100 and (not isinstance(data,dict) or data.get("total_count",page*100+1)>page*100)
                return data,{"link":"rel=\"next\"" if more else ""}
            def diff(inner,path):
                try:return get("/"+path.lstrip("/"),method="diff"),{}
                except (TrioError,AttributeError) as error:raise ReadFailure("diff read unavailable") from None
            def closing_page(inner,node_id,after):
                try:return get(node_id,method="closing_page",after=after)
                except (TrioError,AttributeError) as error:raise ReadFailure("closing relationships read unavailable") from None
        reader=Reader()
        def descriptor(name,status,payload=None,error=None,resource=None,pagination=None):
            at=c.now()
            ref=c.artifact_ref(payload,"diff" if name=="diff" else "json") if payload is not None else None
            if ref: payloads[c.object_name(ref)]=payload
            count=len(c.strict_json(payload)) if payload is not None and name in c.COLLECTIONS else None
            return dict(status=status,fetched_at=at,source=dict(transport="rest",resource=resource or summary_path),revision=revision,expected_count=None,received_count=count,pagination_complete=pagination,truncated=False,error=error,object=ref)
        endpoints={"comments":base+"/issues/"+str(number)+"/comments","files":summary_path+"/files","reviews":summary_path+"/reviews","review_comments":summary_path+"/comments","timeline":base+"/issues/"+str(number)+"/timeline"}
        for name in ordered:
            if kind=="issue" and name in c.PR_ONLY:
                components[name]=dict(status="not_applicable",fetched_at=None,source=None,revision=revision,expected_count=None,received_count=None,pagination_complete=None,truncated=False,error=None,object=None); continue
            if name=="summary": components[name]=descriptor(name,"complete",c.canonical(summary)); continue
            if name in ("closing_issues","checks","diff"):
                from .pr_components import collect_diff,collect_checks,collect_closing
                if name=="diff":
                    file_desc=components["files"];file_rows=c.strict_json(payloads[c.object_name(file_desc["object"])]) if file_desc["object"] else []
                    components[name]=collect_diff(reader,summary_path,revision,file_desc,file_rows,summary,payloads)
                elif name=="checks":components[name]=collect_checks(reader,repo,summary,revision,payloads)
                else:components[name]=collect_closing(reader,repo,identity,revision,payloads)
                continue
            rows=[]; page=1; complete=False; reason=None; endpoint=endpoints[name]; seen=set()
            expected=summary.get({"comments":"comments","files":"changed_files","review_comments":"review_comments"}.get(name,""))
            if expected is not None and (type(expected) is not int or expected<0):raise TrioError("EVIDENCE_CORRUPT")
            try:
                while page<=1000:
                    key=name+":"+str(page)
                    if key in saved["pages"]:
                        ref=saved["pages"][key]
                        raw=self._read(self.path(dataset,"evidence","objects",c.object_name(ref)),self.store.config["object_max_bytes"])
                        if len(raw)!=ref["bytes"] or hashlib.sha256(raw).hexdigest()!=ref["sha256"]: raise TrioError("EVIDENCE_CORRUPT")
                        data=c.strict_json(raw)
                        # Mutable discussions are revalidated; saved pages never conceal edits.
                        pages_saved=[int(k.split(":")[1]) for k in saved["pages"] if k.startswith(name+":")]
                        if name!="files" or page==max(pages_saved):
                            fresh=get(endpoint+"?per_page=100&page="+str(page))
                            if not isinstance(fresh,list) or len(fresh)>100:raise TrioError("EVIDENCE_CORRUPT")
                            if c.canonical(fresh)!=c.canonical(data):
                                data=fresh;raw=c.canonical(data).encode();ref=c.artifact_ref(raw.decode())
                                with self._lock():
                                    self._admit(dataset,len(raw)+8192)
                                    atomic_bytes(self.path(dataset,"evidence","objects",c.object_name(ref)),raw)
                                    for old in list(saved["pages"]):
                                        if old.startswith(name+":") and int(old.split(":")[1])>=page:del saved["pages"][old]
                                    saved["pages"][key]=ref
                                    atomic_bytes(job_path,c.canonical(sealed(saved)).encode())
                    else:
                        data=get(endpoint+"?per_page=100&page="+str(page))
                        if not isinstance(data,list) or len(data)>100: raise TrioError("EVIDENCE_CORRUPT")
                        raw=c.canonical(data).encode()
                        if len(raw)>self.store.config["object_max_bytes"]: raise TrioError("RESOURCE_LIMIT")
                        ref=c.artifact_ref(raw.decode())
                        with self._lock():
                            self._admit(dataset,len(raw)+8192)
                            atomic_bytes(self.path(dataset,"evidence","objects",c.object_name(ref)),raw)
                            saved["pages"][key]=ref
                            atomic_bytes(job_path,c.canonical(sealed(saved)).encode())
                    keys=[row.get("filename") if name=="files" else row.get("node_id",row.get("id")) for row in data if isinstance(row,dict)]
                    if len(keys)!=len(data) or any(k is None or isinstance(k,bool) or not isinstance(k,(str,int)) for k in keys) or len(set(keys))!=len(keys) or seen.intersection(keys):raise TrioError("EVIDENCE_CORRUPT")
                    seen.update(keys)
                    rows.extend(data)
                    if len(c.canonical(rows).encode())>self.store.config["object_max_bytes"]: raise TrioError("RESOURCE_LIMIT")
                    if len(data)<100: complete=True; break
                    page+=1
                if not complete: reason="page ceiling"
                if complete and expected is not None and len(rows)!=expected:complete=False;reason="collection count changed"
                if complete and name=="files" and any("patch" not in row for row in rows):complete=False;reason="file patches omitted"
            except TrioError as error:
                if error.code=="EVIDENCE_CORRUPT": raise
                reason=error.code
            except Exception:
                reason="transport failed"
            components[name]=descriptor(name,"complete" if complete else "partial" if rows else "failed",c.canonical(rows) if rows or complete else None,error=None if complete else reason,resource=endpoint,pagination=complete)
            components[name]["expected_count"]=expected
        try:
            final=get(summary_path)
            final_repo=get(base)
            if final_repo.get("private") is not False:
                self.suspend(dataset)
                raise TrioError("PUBLIC_REPO_REQUIRED")
            if final_repo.get("id")!=repo["database_id"] or final_repo.get("full_name")!=repo["full_name"]:raise TrioError("IDENTITY_MISMATCH")
            drift=not isinstance(final,dict) or final.get("id")!=identity["database_id"] or final.get("number")!=number or final.get("updated_at")!=revision["updated_at"]
            if kind=="pr":
                from .read_contract import check_scope
                drift=drift or any(final.get(n,{}).get("sha")!=revision[n+"_sha"] for n in ("head","base")) or check_scope(final)!=check_scope(summary)
                for side in ("head","base"):
                    linked=final.get(side,{}).get("repo",{})
                    if linked.get("private") is not False or not c.REPO_RE.fullmatch(linked.get("full_name","")):raise TrioError("PUBLIC_REPO_REQUIRED")
                    checked=get("/repos/"+linked["full_name"])
                    if checked.get("private") is not False or checked.get("id")!=linked.get("id"):raise TrioError("IDENTITY_MISMATCH")
            if drift:
                for desc in components.values():
                    if desc["status"]=="complete": desc.update(status="partial",error="revision drift")
        except Exception:
            for desc in components.values():
                if desc["status"]=="complete": desc.update(status="partial",error="final identity recheck unavailable")
        manifest=c.seal_snapshot(dict(schema_version=1,artifact="evidence-snapshot",repository=repo,started_at=started,completed_at=c.now(),requested_components=requested,items=[dict(identity=identity,revision=revision,components=components)]))
        result=self.publish(dataset,manifest,payloads)
        result.update(requests=calls,job=job_id,cancelled=cancelled,coverage_detail={n:components[n]["status"] for n in requested})
        return result

    def suspend(self,dataset,reason="scope revocation"):
        self.scope(dataset)
        with self._lock():
            atomic_bytes(self.path(dataset,"local","suspension.json"),c.canonical(dict(schema="trio.suspension/v1",dataset=dataset,at=c.now(),reason="scope revocation")).encode())
        return {"dataset":dataset,"suspended":True}

    def require_shareable(self,dataset):
        self.scope(dataset)
        if self.path(dataset,"local","suspension.json").exists():raise TrioError("SHARE_BLOCKED")

    def is_current(self,ref):
        self.resolve_ref(ref)
        source=self.source(ref["dataset"]);latest=None;latest_record=None
        root=self.path(ref["dataset"],"evidence","snapshots")
        for path in root.glob("*.json"):
            manifest=source.manifest(path.stem)
            for record in manifest["items"]:
                if (record["identity"]["kind"],record["identity"]["number"])==(ref["identity"]["kind"],ref["identity"]["number"]):
                    order=(c.timestamp(manifest["completed_at"]),manifest["snapshot_id"])
                    if latest is None or order>latest:latest=order;latest_record=record
        descriptor=latest_record["components"].get(ref["component"]) if latest_record else None
        return bool(latest_record and latest_record["identity"]==ref["identity"] and descriptor and descriptor["object"]==ref["object"] and descriptor["revision"]==ref["revision"] and descriptor["status"]=="complete")

    def corpus_run(self,dataset,corpus,transport,*,budget=None):
        c.checked_id(corpus);source=self.source(dataset);selected=source.select(corpus=corpus)
        plan=self._json(self.path(dataset,"evidence","corpora",corpus+".plan.json"))
        state_path=self.path(dataset,"evidence","corpora",corpus+".state.json")
        state=self._json(state_path)
        remaining=self.store.config["request_budget"] if budget is None else budget
        if type(remaining) is not int or remaining<1:raise TrioError("RESOURCE_LIMIT")
        class BudgetTransport:
            token=getattr(transport,"token",None if not hasattr(transport,"namespace") else object())
            def namespace(inner):
                nonlocal remaining
                if not hasattr(transport,"namespace"):return None
                if inner.token is not None:
                    if remaining<=0:raise TrioError("REQUEST_BUDGET")
                    remaining-=1
                return transport.namespace()
            def diff(inner,path):
                nonlocal remaining
                if remaining<=0:raise TrioError("REQUEST_BUDGET")
                remaining-=1
                return transport.diff(path)
            def closing_page(inner,node_id,after):
                nonlocal remaining
                if remaining<=0:raise TrioError("REQUEST_BUDGET")
                remaining-=1
                return transport.closing_page(node_id,after)
            def get(inner,path):
                nonlocal remaining
                if remaining<=0:raise TrioError("REQUEST_BUDGET")
                remaining-=1
                return transport.get(path)
        wrapped=BudgetTransport();requests=remaining;state["status"]="running"
        def commit():
            value={k:v for k,v in state.items() if k!="checksum"};value["updated_at"]=c.now()
            with self._lock():atomic_bytes(state_path,c.canonical(sealed(value)).encode())
        commit()
        for identity in plan["members"]:
            if remaining<=0:state["status"]="stopped";break
            key=identity["kind"]+":"+str(identity["number"]);entry=state["items"][key]
            entry["attempts"]+=1;entry.update(outcome="running",error=None);commit()
            try:
                result=self.capture(dataset,identity["kind"],identity["number"],wrapped,profile=plan["profile"],budget=remaining)
                manifest=self.snapshot(dataset,result["snapshot"])
                c.same_item(identity,manifest["items"][0]["identity"])
                entry.update(snapshot_id=result["snapshot"],outcome="complete" if result["coverage"]["complete"] else "gaps",error=None)
                if result.get("cancelled"):
                    state["status"]="interrupted";commit();break
            except (Exception,KeyboardInterrupt) as error:
                entry.update(outcome="error",error="acquisition stopped")
                state["status"]="interrupted" if isinstance(error,KeyboardInterrupt) else "stopped";commit();break
            commit()
        else:state["status"]="finished"
        state["last_run"]=dict(started_at=c.now(),request_budget=requests,requests=requests-remaining,reason=None if state["status"]=="finished" else "stopped")
        commit();new=self.source(dataset).select(corpus=corpus)
        return {"schema":"trio.corpus-run/v1","dataset":dataset,"corpus":corpus,"checkpoint":new.checkpoint,"requests":requests-remaining,"status":state["status"],"coverage":new.coverage}

    run_corpus = corpus_run

    def combine_snapshots(self,dataset,identifiers):
        import copy
        if not isinstance(identifiers,(list,tuple)) or not identifiers or len(identifiers)>self.store.config["corpus_size"] or len(set(identifiers))!=len(identifiers):raise TrioError("RESOURCE_LIMIT")
        source=self.source(dataset);manifests=[source.manifest(c.checked_id(identifier)) for identifier in identifiers]
        selected={};components=set()
        for manifest in manifests:
            for record in manifest["items"]:
                key=(record["identity"]["kind"],record["identity"]["number"])
                if key in selected and selected[key]!=record:raise TrioError("REVISION_CONFLICT","choose one exact observation per item before combining")
                selected[key]=copy.deepcopy(record);components.update(record["components"])
        if not selected or len(selected)>self.store.config["corpus_size"]:raise TrioError("RESOURCE_LIMIT")
        completed=max((m["completed_at"] for m in manifests),key=c.timestamp)
        for record in selected.values():
            for name in components-record["components"].keys():
                applicable=not(record["identity"]["kind"]=="issue" and name in c.PR_ONLY)
                record["components"][name]=dict(status="unavailable" if applicable else "not_applicable",fetched_at=completed if applicable else None,source=dict(transport="rest",resource="explicit captured selection; component not requested") if applicable else None,revision=record["revision"],expected_count=None,received_count=None,pagination_complete=None,truncated=False,error="not-requested: selected snapshot omitted component" if applicable else None,object=None)
        combined=c.seal_snapshot(dict(schema_version=1,artifact="evidence-snapshot",repository=source.repository,started_at=min((m["started_at"] for m in manifests),key=c.timestamp),completed_at=completed,requested_components=sorted(components),items=[selected[key] for key in sorted(selected)]))
        result=self.publish(dataset,combined,{})
        observation=dict(schema="trio.inventory-observation/v1",dataset=dataset,snapshot=combined["snapshot_id"],basis="explicit selected captures",member_count=len(selected),pagination_complete=None,truncated=False,live_enumeration_complete=False,source_snapshots=sorted(identifiers))
        with self._lock():atomic_bytes(self.path(dataset,"local","inventory-"+combined["snapshot_id"]+".json"),c.canonical(sealed(observation)).encode())
        return dict(result,inventory=observation)

    def capture_inventory(self,dataset,transport,*,limit=100,budget=None):
        if type(limit) is not int or not 1<=limit<=self.store.config["corpus_size"]:raise TrioError("RESOURCE_LIMIT")
        budget=self.store.config["request_budget"] if budget is None else budget
        if type(budget) is not int or not 1<=budget<=10000:raise TrioError("RESOURCE_LIMIT")
        if self.path(dataset,"local","suspension.json").exists():raise TrioError("SCOPE_DENIED")
        scope=self.scope(dataset);source=self.source(dataset);repository=source.repository;prefix="/repos/"+repository["full_name"]
        calls=0;cancelled=False
        cooldown=confined(self.store.root,Path("acquisition")/(c.digest(c.canonical(scope.get("profile") or "anonymous"))+".json"))
        def read(path=None,namespace=False):
            nonlocal calls,cancelled
            if cancelled:raise TrioError("CANCELLED")
            if cooldown.exists() and self._json(cooldown).get("until",0)>time.time():raise TrioError("THROTTLED")
            if calls>=budget:raise TrioError("REQUEST_BUDGET")
            calls+=1
            try:return transport.namespace() if namespace else transport.get(path)
            except KeyboardInterrupt:
                cancelled=True
                raise TrioError("CANCELLED") from None
            except TrioError as error:
                if error.code=="THROTTLED":
                    delay=getattr(error,"retry_after",60)
                    if type(delay) is not int or not 1<=delay<=86400:delay=60
                    with self._lock():atomic_bytes(cooldown,c.canonical(dict(schema="trio.cooldown/v1",until=time.time()+delay)).encode())
                raise
        namespace=transport.namespace() if hasattr(transport,"namespace") and getattr(transport,"token",object()) is None else read(namespace=True) if hasattr(transport,"namespace") else None
        if namespace!=scope.get("profile"):raise TrioError("IDENTITY_MISMATCH")
        observed=read(prefix)
        if observed.get("private") is not False:
            self.suspend(dataset);raise TrioError("PUBLIC_REPO_REQUIRED")
        if type(observed.get("id")) is not int or observed.get("id")!=repository["database_id"] or observed.get("full_name")!=repository["full_name"]:raise TrioError("IDENTITY_MISMATCH")
        if repository["node_id"] is None and isinstance(observed.get("node_id"),str):
            repository=dict(repository,node_id=observed["node_id"])
            with self._lock():atomic_bytes(self.path(dataset,"evidence","cache.json"),c.canonical(dict(schema_version=1,artifact="evidence-cache",repository=repository)).encode())
        started=c.now();page=1;records=[];payloads={};seen=set();complete=False;truncated=False;reason=None
        try:
            while len(records)<limit:
                endpoint=prefix+"/issues?state=open&per_page=100&page="+str(page)
                rows=read(endpoint)
                if not isinstance(rows,list) or len(rows)>100:raise TrioError("EVIDENCE_CORRUPT")
                for row in rows:
                    if not isinstance(row,dict) or type(row.get("id")) is not int or type(row.get("number")) is not int:raise TrioError("IDENTITY_MISMATCH")
                    kind="pr" if "pull_request" in row else "issue"
                    if kind=="pr":
                        # REST issue-list PR IDs identify Issue objects, not PullRequest objects.
                        number=row["number"];pull=read(prefix+"/pulls/"+str(number))
                        if not isinstance(pull,dict):raise TrioError("IDENTITY_MISMATCH")
                        for side in ("base","head"):
                            branch=pull.get(side,{}) if isinstance(pull.get(side),dict) else {}
                            linked=branch.get("repo")
                            if not isinstance(linked,dict) or linked.get("private") is not False or not c.REPO_RE.fullmatch(linked.get("full_name","")):
                                raise TrioError("PUBLIC_REPO_REQUIRED")
                            checked=read("/repos/"+linked["full_name"])
                            if checked.get("private") is not False or type(checked.get("id")) is not int or checked.get("id")!=linked.get("id") or checked.get("full_name")!=linked.get("full_name"):raise TrioError("PUBLIC_REPO_REQUIRED")
                            if side=="base" and (checked["id"]!=repository["database_id"] or checked["full_name"]!=repository["full_name"]):raise TrioError("IDENTITY_MISMATCH")
                        from .read_contract import summary_identity
                        try:summary_identity(pull,"pr",number,repository)
                        except (ValueError,KeyError,TypeError):raise TrioError("IDENTITY_MISMATCH") from None
                        row=pull
                    identity=dict(kind=kind,number=row["number"],database_id=row["id"],node_id=row.get("node_id"));c.validate_item(identity)
                    key=(kind,identity["number"])
                    if key in seen or row["id"] in {r["identity"]["database_id"] for r in records}:raise TrioError("IDENTITY_MISMATCH")
                    if len(records)>=limit:truncated=True;break
                    if row.get("html_url")!=f"https://github.com/{repository['full_name']}/{'pull' if kind=='pr' else 'issues'}/{identity['number']}" or row.get("state")!="open":raise TrioError("IDENTITY_MISMATCH")
                    revision=dict(updated_at=row.get("updated_at"),base_sha=row.get("base",{}).get("sha") if kind=="pr" else None,head_sha=row.get("head",{}).get("sha") if kind=="pr" else None);c.validate_revision(revision)
                    if revision["updated_at"] is None:raise TrioError("IDENTITY_MISMATCH")
                    payload=c.canonical(row);ref=c.artifact_ref(payload)
                    if ref["bytes"]>self.store.config["object_max_bytes"]:raise TrioError("RESOURCE_LIMIT")
                    payloads[c.object_name(ref)]=payload
                    desc=dict(status="complete",fetched_at=c.now(),source=dict(transport="rest",resource=endpoint),revision=revision,expected_count=None,received_count=None,pagination_complete=None,truncated=False,error=None,object=ref)
                    records.append(dict(identity=identity,revision=revision,components={"summary":desc}));seen.add(key)
                if truncated:break
                if len(rows)<100:complete=True;break
                if len(records)>=limit:truncated=True;break
                page+=1
        except (TrioError,KeyboardInterrupt) as error:
            if isinstance(error,TrioError) and error.code in ("EVIDENCE_CORRUPT","IDENTITY_MISMATCH"):raise
            truncated=True
            reason="cancelled" if isinstance(error,KeyboardInterrupt) else error.code
        if not records:raise TrioError(reason if reason in ("PUBLIC_REPO_REQUIRED","REQUEST_BUDGET","THROTTLED","CANCELLED") else "EVIDENCE_MISSING","inventory captured no selected item observations")
        try:
            final=read(prefix)
            if final.get("private") is not False:self.suspend(dataset);raise TrioError("PUBLIC_REPO_REQUIRED")
            if final.get("id")!=repository["database_id"] or final.get("full_name")!=repository["full_name"]:raise TrioError("IDENTITY_MISMATCH")
        except (TrioError,KeyboardInterrupt):
            complete=False;reason="final repository scope recheck unavailable"
            for record in records:record["components"]["summary"].update(status="partial",error="final repository scope recheck unavailable")
        manifest=c.seal_snapshot(dict(schema_version=1,artifact="evidence-snapshot",repository=repository,started_at=started,completed_at=c.now(),requested_components=["summary"],items=records))
        result=self.publish(dataset,manifest,payloads)
        observation=dict(schema="trio.inventory-observation/v1",dataset=dataset,snapshot=manifest["snapshot_id"],basis="bounded public open-item REST enumeration",member_count=len(records),pagination_complete=complete,truncated=truncated,live_enumeration_complete=complete,reason=reason)
        with self._lock():atomic_bytes(self.path(dataset,"local","inventory-"+manifest["snapshot_id"]+".json"),c.canonical(sealed(observation)).encode())
        return dict(result,inventory=observation,requests=calls)

    def inventory_observation(self,dataset,snapshot):
        path=self.path(dataset,"local","inventory-"+c.checked_id(snapshot)+".json")
        if not path.exists():return {"basis":"explicit captured snapshot","live_enumeration_complete":False,"pagination_complete":None}
        value=self._json(path)
        if value.get("checksum")!=c.digest(c.canonical({k:v for k,v in value.items() if k!="checksum"})) or value.get("dataset")!=dataset or value.get("snapshot")!=snapshot:raise TrioError("EVIDENCE_CORRUPT")
        return value

    def coverage(self,manifest,*,max_age=86400):
        """Product diagnostics over the unchanged strict public donor contract.

        Observation completeness describes capture; temporal staleness is reported
        separately and never upgrades a missing collection to an empty collection.
        """
        if type(max_age) is not int or max_age<0:raise TrioError("INVALID_ARGUMENT",exit_code=2)
        base=c.coverage(manifest);counts={s:0 for s in ("complete","partial","missing","stale","failed","not-requested","not-applicable")}
        for record in manifest["items"]:
            for name in sorted(c.COMPONENTS):
                desc=record["components"].get(name)
                if desc is None:status="missing" if name in manifest["requested_components"] else "not-requested"
                elif desc["status"]=="not_applicable":status="not-applicable"
                elif desc["status"]=="unavailable":status="not-requested" if isinstance(desc["error"],str) and desc["error"].startswith("not-requested:") else "missing"
                elif desc["status"]=="complete" and c.component_problems(name,desc,record["revision"],c.now(),max_age):status="stale"
                else:status=desc["status"]
                counts[status]+=1
        return dict(base,statuses=counts,current_complete=not any(counts[s] for s in ("partial","missing","stale","failed")),age_policy_seconds=max_age,complete_basis="source observations; temporal freshness reported separately")

    def selection_coverage(self,dataset,selection,*,max_age=86400):
        source=self.source(dataset);selected=source.select(**selection)
        totals={s:0 for s in ("complete","partial","missing","stale","failed","not-requested","not-applicable")}
        for member in selected.members:
            if member["record"] is None:
                totals["missing"]+=len(c.COMPONENTS);continue
            manifest=source.manifest(member["snapshot_id"])
            single=dict(manifest,items=[member["record"]]);single=c.seal_snapshot({k:v for k,v in single.items() if k!="snapshot_id"})
            for status,count in self.coverage(single,max_age=max_age)["statuses"].items():totals[status]+=count
        return dict(selected.coverage,statuses=totals,age_policy_seconds=max_age,freshness_basis="recorded observations; no live check")
