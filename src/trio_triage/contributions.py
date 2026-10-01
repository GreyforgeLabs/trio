# SPDX-License-Identifier: Apache-2.0
"""Public source, constrained patches, trusted sandbox seals and GitHub publishing.

All tracked bytes are immutable local records. Sandbox output is diagnostic data,
never a seal or authority. Publication is closed until exact local policy/approval.
"""
import base64,datetime,hashlib,os,re,selectors,shutil,stat,subprocess,tempfile,time,uuid
from pathlib import Path
from .operations import OperationState,repo_name,sha,integer,now,GitHubTransport,MAX_OPERATION_RECORD_BYTES
from .storage import canonical,digest,atomic_json,read_json,confined
from .errors import TrioError

MAX_FILES=5000;MAX_SOURCE=67108864;MAX_BLOB=16777216;MAX_PATCH=1048576
MAX_SOURCE_OPT_IN=83886080

def source_budget(value):
    if type(value) is not int or not 1<=value<=MAX_SOURCE_OPT_IN:raise TrioError("INVALID_SOURCE_LIMIT",exit_code=2)
    return value

def source_limit(source):
    # Legacy records retain the original default. A stored null is not omission.
    return source_budget(source.get("max_source_bytes",MAX_SOURCE))

def path_name(value):
    if not isinstance(value,str) or not value or len(value)>1024 or value.startswith("/") or "\\" in value or any(ord(x)<32 for x in value) or any(x.lower() in {"",".","..",".git"} for x in value.split("/")):raise TrioError("UNSAFE_PATH",exit_code=2)
    return value

def git_object(kind,raw):return hashlib.sha1(kind.encode()+b" "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
def decode_files(files,*,max_source_bytes=None):
    limit=source_budget(MAX_SOURCE if max_source_bytes is None else max_source_bytes)
    if not isinstance(files,dict) or len(files)>MAX_FILES:raise TrioError("SOURCE_CORRUPT")
    result={};total=0
    for name,value in files.items():
        path_name(name)
        if not isinstance(value,dict) or set(value)!={"mode","sha","content"} or value["mode"] not in {"100644","100755","120000"}:raise TrioError("SOURCE_CORRUPT")
        try:raw=base64.b64decode(value["content"],validate=True)
        except Exception:raise TrioError("SOURCE_CORRUPT") from None
        total+=len(raw)
        if len(raw)>MAX_BLOB or total>limit or git_object("blob",raw)!=value["sha"]:raise TrioError("SOURCE_CORRUPT")
        result[name]={"mode":value["mode"],"raw":raw,"sha":value["sha"]}
    validate_source_links(result)
    return result

def encode_files(files):return {k:{"mode":v["mode"],"sha":git_object("blob",v["raw"]),"content":base64.b64encode(v["raw"]).decode()} for k,v in files.items()}
def tree_sha(files):
    tree={}
    for path,value in files.items():
        parts=path_name(path).split("/");node=tree
        for part in parts[:-1]:
            if part in node and not isinstance(node[part],dict):raise TrioError("UNSAFE_PATH")
            node=node.setdefault(part,{})
        if parts[-1] in node:raise TrioError("UNSAFE_PATH")
        node[parts[-1]]=(value["mode"],value["sha"])
    def build(node):
        rows=[]
        for name,value in node.items():
            directory=isinstance(value,dict);mode,oid=("40000",build(value)) if directory else value
            rows.append((name.encode()+ (b"/" if directory else b""),mode.encode()+b" "+name.encode()+b"\0"+bytes.fromhex(oid)))
        return git_object("tree",b"".join(raw for _,raw in sorted(rows)))
    return build(tree)

def validate_source_links(files):
    """Validate links against Git objects, without consulting the host filesystem.

    Only relative links ending at tracked regular files are supported. Directory
    links are deliberately excluded, so no materialization or read traverses a
    link ancestor. Check the complete graph before creating any filesystem entry.
    """
    tree_sha(files)  # Reject file/directory collisions, including link ancestors.
    directories={"/".join(name.split("/")[:i]) for name in files for i in range(1,len(name.split("/")))}
    targets={}
    for name,value in files.items():
        if value["mode"]!="120000":continue
        raw=value["raw"]
        try:target=raw.decode("utf-8")
        except UnicodeError:raise TrioError("UNSAFE_SOURCE_LINK") from None
        if not target or len(raw)>1024 or target.startswith("/") or "\\" in target or re.match(r"^[A-Za-z]:",target) or any(ord(c)<32 or ord(c)==127 for c in target):raise TrioError("UNSAFE_SOURCE_LINK")
        parts=name.split("/")[:-1];components=target.split("/")
        for i,component in enumerate(components):
            if not component or component.lower()==".git":raise TrioError("UNSAFE_SOURCE_LINK")
            if component=="..":
                if not parts:raise TrioError("UNSAFE_SOURCE_LINK")
                parts.pop()
            elif component!=".":parts.append(component)
            # Do not normalize through a missing/file/link path component.
            if i<len(components)-1 and parts and "/".join(parts) not in directories:raise TrioError("UNSAFE_SOURCE_LINK")
        target="/".join(parts)
        if target not in files:raise TrioError("UNSAFE_SOURCE_LINK")
        targets[name]=target
    for name in targets:
        current=name;seen=set()
        while current in targets:
            if current in seen or len(seen)>=40:raise TrioError("UNSAFE_SOURCE_LINK")
            seen.add(current);current=targets[current]

def screen_files(files):
    from .team import screen
    for name,value in files.items():screen(name);screen(value["raw"].decode("utf-8",errors="replace"))

def apply_patch(files,patch,*,max_source_bytes=None):
    limit=source_budget(MAX_SOURCE if max_source_bytes is None else max_source_bytes)
    if not isinstance(patch,bytes) or len(patch)>MAX_PATCH:raise TrioError("PATCH_REFUSED",exit_code=2)
    try:lines=patch.decode("utf-8").splitlines(keepends=True)
    except UnicodeError:raise TrioError("PATCH_REFUSED",exit_code=2) from None
    if any(x.startswith(("GIT binary patch","Binary files ","rename from ","rename to ","old mode ","new mode ","new file mode 100755","deleted file mode 100755","similarity index ")) for x in lines):raise TrioError("PATCH_REFUSED",exit_code=2)
    result={k:dict(v) for k,v in files.items()};i=0;touched=set()
    while i<len(lines):
        if lines[i].startswith(("diff --git ","index ","new file mode 100644","deleted file mode 100644")):i+=1;continue
        if not lines[i].startswith("--- "):raise TrioError("PATCH_REFUSED",exit_code=2)
        old=lines[i][4:].rstrip("\n");i+=1
        if i>=len(lines) or not lines[i].startswith("+++ "):raise TrioError("PATCH_REFUSED",exit_code=2)
        new=lines[i][4:].rstrip("\n");i+=1
        def name(label,prefix):
            if label=="/dev/null":return None
            if not label.startswith(prefix):raise TrioError("PATCH_REFUSED",exit_code=2)
            return path_name(label[len(prefix):])
        old=name(old,"a/");new=name(new,"b/")
        if old is None and new is None or old and new and old!=new:raise TrioError("PATCH_REFUSED",exit_code=2)
        target=new or old
        if target in touched or old and old not in result or old is None and new in result:raise TrioError("PATCH_REFUSED",exit_code=2)
        if old and result[old]["mode"]=="120000":raise TrioError("PATCH_REFUSED",exit_code=2)
        touched.add(target)
        raw=result[old]["raw"] if old else b""
        try:source=raw.decode("utf-8").splitlines(keepends=True)
        except UnicodeError:raise TrioError("PATCH_REFUSED",exit_code=2) from None
        output=[];position=0;hunks=0
        while i<len(lines) and lines[i].startswith("@@ "):
            match=re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\n]*\n?",lines[i])
            if not match:raise TrioError("PATCH_REFUSED",exit_code=2)
            start,count,added_start,added_count=[int(match[k]) if match[k] is not None else 1 for k in range(1,5)]
            cursor=start-1 if count else start
            if cursor<position or cursor>len(source):raise TrioError("PATCH_CONTEXT_CHANGED")
            output.extend(source[position:cursor]);position=cursor
            if (added_start-1 if added_count else added_start)!=len(output):raise TrioError("PATCH_CONTEXT_CHANGED")
            i+=1;seen_old=0;seen_new=0
            while i<len(lines) and lines[i][:1] in {" ","+","-","\\"}:
                marker=lines[i][:1];text=lines[i][1:];i+=1
                if marker=="\\":raise TrioError("PATCH_REFUSED",exit_code=2)
                if i<len(lines) and lines[i].startswith("\\ No newline at end of file"):
                    text=text.removesuffix("\n");i+=1
                if marker in {" ","-"}:
                    if position>=len(source) or source[position]!=text:raise TrioError("PATCH_CONTEXT_CHANGED")
                    position+=1;seen_old+=1
                if marker in {" ","+"}:output.append(text);seen_new+=1
                if seen_old>count or seen_new>added_count:raise TrioError("PATCH_REFUSED",exit_code=2)
                if seen_old==count and seen_new==added_count:break
            if (seen_old,seen_new)!=(count,added_count):raise TrioError("PATCH_REFUSED",exit_code=2)
            hunks+=1
        if not hunks:raise TrioError("PATCH_REFUSED",exit_code=2)
        output.extend(source[position:]);updated="".join(output).encode()
        if new is None:
            if updated:raise TrioError("PATCH_REFUSED",exit_code=2)
            del result[old]
        else:result[new]={"mode":result[old]["mode"] if old else "100644","raw":updated,"sha":git_object("blob",updated)}
    if not touched:raise TrioError("PATCH_REFUSED",exit_code=2)
    encoded=encode_files(result);decode_files(encoded,max_source_bytes=limit)
    return encoded,sorted(touched)

class PodmanSandbox:
    name="podman-offline/v1"
    def run(self,files,commands,image,timeout=60,memory_mb=512,pids=64,cpus=1,output_limit=1048576):
        executable=shutil.which("podman")
        if not executable:raise TrioError("SANDBOX_UNAVAILABLE","Install Podman and preload the explicitly approved image digest",exit_code=2)
        outcomes=[]
        validate_source_links(files)
        expected=tree_sha(files)
        with tempfile.TemporaryDirectory(prefix="trio-validation-") as directory:
            work=Path(directory)/"work";work.mkdir(mode=0o700)
            for name,value in files.items():
                if value["mode"]=="120000":continue
                destination=work/path_name(name);destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(value["raw"]);destination.chmod(0o755 if value["mode"]=="100755" else 0o644)
            # Links are created last, after all regular-file writes and chmods.
            for name,value in files.items():
                if value["mode"]!="120000":continue
                destination=work/path_name(name);destination.parent.mkdir(parents=True,exist_ok=True);destination.symlink_to(value["raw"].decode("utf-8"))
            for argv in commands:
                container="trio-validation-"+uuid.uuid4().hex
                invocation=[executable,"run","--rm","--pull=never","--name",container,"--network=none","--read-only","--cap-drop=ALL","--security-opt=no-new-privileges","--pids-limit="+str(pids),"--memory="+str(memory_mb)+"m","--cpus="+str(cpus),"--userns=keep-id","--user="+str(os.getuid())+":"+str(os.getgid()),"--log-driver=none","--env=HOME=/tmp","--env=PYTHONDONTWRITEBYTECODE=1","--tmpfs=/tmp:rw,nosuid,nodev,size=128m","--mount=type=bind,src="+str(work)+",dst=/work,ro=true","--workdir=/work",image,*argv]
                # Engine process inherits no token or helper environment.
                environment={"PATH":"/usr/local/bin:/usr/bin:/bin","HOME":str(Path.home()),"LANG":"C.UTF-8"}
                if os.environ.get("XDG_RUNTIME_DIR"):environment["XDG_RUNTIME_DIR"]=os.environ["XDG_RUNTIME_DIR"]
                started=time.monotonic();output=bytearray();failure=None;process=None
                try:
                    process=subprocess.Popen(invocation,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=environment)
                    selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ)
                    while selector.get_map():
                        if time.monotonic()-started>timeout:failure="SANDBOX_TIMEOUT";break
                        for key,_ in selector.select(.1):
                            chunk=os.read(key.fileobj.fileno(),65536)
                            if not chunk:selector.unregister(key.fileobj);continue
                            output.extend(chunk)
                            if len(output)>output_limit:failure="SANDBOX_OUTPUT_LIMIT";break
                        if failure:break
                    selector.close()
                    if failure:process.kill()
                    code=process.wait(timeout=5)
                except (OSError,subprocess.SubprocessError):failure="SANDBOX_FAILURE";code=None
                finally:
                    if process and process.poll() is None:process.kill();process.wait()
                    cleaned=subprocess.run([executable,"rm","--force","--ignore",container],capture_output=True,timeout=15,env=environment)
                    if cleaned.returncode!=0:failure="SANDBOX_CLEANUP_FAILED"
                outcomes.append({"command":argv,"returncode":code,"seconds":round(time.monotonic()-started,4),"output_sha256":hashlib.sha256(output).hexdigest(),"output_bytes":len(output),"output":bytes(output[:output_limit]).decode("utf-8",errors="replace"),"error":failure})
                if failure or code!=0:break
            # A trusted host read checks immutable tracked inputs after execution.
            observed={}
            for root,directories,names in os.walk(work,followlinks=False):
                for name in [*directories,*names]:
                    path=Path(root)/name;mode=path.lstat().st_mode
                    if stat.S_ISLNK(mode):raw=os.readlink(os.fsencode(path));git_mode="120000"
                    elif stat.S_ISREG(mode):raw=path.read_bytes();git_mode="100755" if mode&0o111 else "100644"
                    elif stat.S_ISDIR(mode):continue
                    else:raise TrioError("SANDBOX_SOURCE_CHANGED")
                    observed[path.relative_to(work).as_posix()]={"mode":git_mode,"raw":raw,"sha":git_object("blob",raw)}
            if tree_sha(observed)!=expected:raise TrioError("SANDBOX_SOURCE_CHANGED")
        return {"backend":self.name,"image":image,"outcomes":outcomes,"successful":len(outcomes)==len(commands) and all(x["returncode"]==0 and not x["error"] for x in outcomes)}

def commit_bytes(tree,parent,message,author,date):
    parsed=datetime.datetime.fromisoformat(date.replace("Z","+00:00"));epoch=int(parsed.timestamp())
    identity=author["name"]+" <"+author["email"]+"> "+str(epoch)+" +0000"
    return ("tree "+tree+"\nparent "+parent+"\nauthor "+identity+"\ncommitter "+identity+"\n\n"+message+"\n").encode()

class ContributionService(OperationState):
    def put(self,kind,identifier,value):
        # Include encoded content, all metadata and atomic_json's final newline.
        # Never write a source/patch record that the unchanged reader cannot read.
        if kind in {"sources","patches"} and len(canonical(value))+1>MAX_OPERATION_RECORD_BYTES:raise TrioError("SOURCE_RECORD_LIMIT")
        super().put(kind,identifier,value)
    def intake(self,transport,repository,number=None,finding=None):
        repository=repo_name(repository);remote=transport.repository(repository,public=True);identity=transport.identity();details={}
        if bool(number)==bool(finding):raise TrioError("INVALID_INVOCATION",exit_code=2)
        if number:
            integer(number);issue=transport.get("/repos/"+repository+"/issues/"+str(number))
            if not isinstance(issue,dict) or issue.get("number")!=number or issue.get("pull_request"):raise TrioError("INVALID_TARGET")
            details={"kind":"issue","number":number,"item_id":issue["id"],"title":issue.get("title",""),"url":issue.get("html_url")}
        else:
            from .triage import TriageService,CATEGORIES
            from . import contracts as c
            selected=TriageService(self.store).show(finding)
            if selected["conflict"] or len(selected["revisions"])!=1:raise TrioError("CONFLICT")
            revision=selected["revisions"][0]
            if revision["operation"] not in {"finding","resolve"} or revision["payload"].get("category") not in CATEGORIES:raise TrioError("INVALID_TARGET")
            refs=revision["evidence_refs"]
            if revision["payload"].get("evidence_refs")!=refs or revision["payload"].get("selection_digests")!=sorted({ref["snapshot"] for ref in refs}):raise TrioError("EVIDENCE_CORRUPT")
            if selected["stale"]:raise TrioError("PLAN_CHANGED")
            current=c.repository(remote["full_name"],database_id=remote["id"],node_id=remote.get("node_id"))
            try:
                for item in [*revision["payload"]["items"],*refs]:
                    if item["repository"]["database_id"] is None:raise ValueError()
                    c.same_repository(item["repository"],current)
            except (ValueError,KeyError,TypeError):raise TrioError("IDENTITY_MISMATCH") from None
            # Queue the exact proposal as context; finding reviews never grant
            # validation seals, publication approval, or publisher authority.
            details={"kind":"finding","finding":finding,"finding_revision":revision["event_id"],
                "decision_digest":revision["payload"]["decision_digest"],"selection_digest":digest(selected)}
        transport.safe_content(details)
        value={"schema":"trio.contribution/v1","id":uuid.uuid4().hex,"repository":remote["full_name"],"repository_id":remote["id"],"identity":identity,"intake":details,"created_at":now(),"generation":0,"stage":"queued"}
        with self.store.write_lock():self.put("contributions",value["id"],value)
        return value
    def show(self,identifier):
        value=self.get("contributions",identifier)
        return {"schema":"trio.contribution/v1",**value}
    def list(self):
        directory=self.root/"contributions"
        return {"schema":"trio.contributions/v1","contributions":[{k:v[k] for k in ("id","repository","generation","stage","created_at")} for v in (read_json(p) for p in sorted(directory.glob("*.json")))] if directory.exists() else []}
    def source(self,identifier):
        value=self.get("sources",identifier)
        if value.get("digest")!=digest({k:v for k,v in value.items() if k!="digest"}):raise TrioError("SOURCE_CORRUPT")
        files=decode_files(value["files"],max_source_bytes=source_limit(value))
        if tree_sha(files)!=value["tree"]:raise TrioError("SOURCE_CORRUPT")
        return value
    def acquire(self,identifier,transport,base,branch,request_budget=1000,max_source_bytes=None):
        sha(base);self.branch(branch)
        limit=source_budget(MAX_SOURCE if max_source_bytes is None else max_source_bytes)
        if type(request_budget) is not int or not 3<=request_budget<=10000:raise TrioError("INVALID_INVOCATION",exit_code=2)
        with self.store.write_lock():
            entry=self.get("contributions",identifier);repo=transport.repository(entry["repository"],public=True)
            if repo["id"]!=entry["repository_id"]:raise TrioError("IDENTITY_MISMATCH")
            prefix="/repos/"+entry["repository"]
            commit=transport.get(prefix+"/git/commits/"+base)
            if not isinstance(commit,dict) or commit.get("sha")!=base:raise TrioError("SOURCE_CORRUPT")
            root=sha(commit.get("tree",{}).get("sha"));tree=transport.get(prefix+"/git/trees/"+root+"?recursive=1")
            if not isinstance(tree,dict) or tree.get("sha")!=root or tree.get("truncated") is not False or not isinstance(tree.get("tree"),list) or len(tree["tree"])>MAX_FILES*2:raise TrioError("SOURCE_INCOMPLETE")
            files={};total=0;requests=3
            for item in tree["tree"]:
                name=path_name(item.get("path"));mode=item.get("mode");kind=item.get("type")
                if kind=="tree" and mode=="040000":continue
                if kind!="blob" or mode not in {"100644","100755","120000"} or name in files:raise TrioError("UNSUPPORTED_SOURCE_ENTRY")
                if type(item.get("size")) is not int or not 0<=item["size"]<=MAX_BLOB:raise TrioError("SOURCE_INCOMPLETE")
                if requests>=request_budget:raise TrioError("SOURCE_REQUEST_BUDGET")
                requests+=1
                blob=transport.get(prefix+"/git/blobs/"+sha(item.get("sha")))
                if not isinstance(blob,dict) or blob.get("encoding")!="base64":raise TrioError("SOURCE_CORRUPT")
                try:raw=base64.b64decode(blob.get("content","").replace("\n",""),validate=True)
                except Exception:raise TrioError("SOURCE_CORRUPT") from None
                total+=len(raw)
                if len(raw)!=item["size"] or total>limit or len(files)>=MAX_FILES or git_object("blob",raw)!=item["sha"] or blob.get("sha")!=item["sha"]:raise TrioError("SOURCE_CORRUPT")
                if raw.startswith(b"version https://git-lfs.github.com/spec/v1"):raise TrioError("LFS_UNSUPPORTED")
                if transport._token in name or transport._token.encode() in raw:raise TrioError("CREDENTIAL_CONTENT")
                screen_files({name:{"raw":raw}})
                files[name]={"mode":mode,"raw":raw,"sha":item["sha"]}
            if tree_sha(files)!=root:raise TrioError("SOURCE_CORRUPT")
            validate_source_links(files)
            encoded=encode_files(files);source={"schema":"trio.public-source/v1","repository":entry["repository"],"repository_id":repo["id"],"base":base,"branch":branch,"tree":root,"files":encoded,"max_source_bytes":limit,"observed_at":now()};source["digest"]=digest(source)
            self.put("sources",identifier,source)
            entry.update(stage="acquired",generation=entry["generation"]+1,source_digest=source["digest"],seal=None,plan=None);self.put("contributions",identifier,entry)
            return {"schema":"trio.contribution-acquire/v1","id":identifier,"base":base,"tree":root,"files":len(files),"bytes":total,"requests":requests,"max_source_bytes":limit,"source_digest":source["digest"]}
    def patch(self,identifier,patch):
        with self.store.write_lock():
            entry=self.get("contributions",identifier);source=self.source(identifier);limit=source_limit(source);files,touched=apply_patch(decode_files(source["files"],max_source_bytes=limit),patch,max_source_bytes=limit)
            screen_files(decode_files(files,max_source_bytes=limit))
            record={"schema":"trio.patch/v1","contribution":identifier,"source_digest":source["digest"],"patch_sha256":hashlib.sha256(patch).hexdigest(),"patch":base64.b64encode(patch).decode(),"files":files,"tree":tree_sha(decode_files(files,max_source_bytes=limit)),"paths":touched};record["digest"]=digest(record)
            self.put("patches",identifier,record);entry.update(stage="patched",generation=entry["generation"]+1,patch_digest=record["digest"],seal=None,plan=None);self.put("contributions",identifier,entry)
            return {"schema":"trio.contribution-patch/v1","id":identifier,"tree":record["tree"],"patch_sha256":record["patch_sha256"],"paths":touched}
    def patched(self,identifier):
        patch=self.get("patches",identifier);source=self.source(identifier)
        if patch.get("digest")!=digest({k:v for k,v in patch.items() if k!="digest"}) or patch["source_digest"]!=source["digest"]:raise TrioError("PATCH_STALE")
        limit=source_limit(source);files,touched=apply_patch(decode_files(source["files"],max_source_bytes=limit),base64.b64decode(patch["patch"],validate=True),max_source_bytes=limit)
        if files!=patch["files"] or tree_sha(decode_files(files,max_source_bytes=limit))!=patch["tree"]:raise TrioError("PATCH_CORRUPT")
        return patch,source
    def validate(self,identifier,commands,image,backend=None,timeout=60,memory_mb=512,pids=64,cpus=1):
        if not isinstance(commands,list) or not 1<=len(commands)<=20 or any(not isinstance(x,list) or not x or len(x)>100 or any(not isinstance(y,str) or not y or len(y)>4096 or "\0" in y for y in x) for x in commands):raise TrioError("INVALID_VALIDATION_COMMAND",exit_code=2)
        if any(type(x) is not int or x<1 for x in (timeout,memory_mb,pids,cpus)) or timeout>1800 or memory_mb>8192 or pids>1024 or cpus>8:raise TrioError("INVALID_VALIDATION_LIMIT",exit_code=2)
        from .team import screen
        screen(commands)
        with self.store.write_lock():
            policy=self.policy()
            if image not in policy["sandbox_images"]:raise TrioError("SANDBOX_IMAGE_DENIED")
            entry=self.get("contributions",identifier);patch,source=self.patched(identifier)
            entry.update(stage="patched",seal=None);self.put("contributions",identifier,entry)
            runner=backend or PodmanSandbox();result=runner.run(decode_files(patch["files"],max_source_bytes=source_limit(source)),commands,image,timeout=timeout,memory_mb=memory_mb,pids=pids,cpus=cpus)
            # Re-read trusted immutable records; sandbox never receives this root.
            after,after_source=self.patched(identifier)
            if after["digest"]!=patch["digest"] or after_source["digest"]!=source["digest"]:raise TrioError("SANDBOX_SOURCE_CHANGED")
            screen(result)
            report={"schema":"trio.validation/v1","id":identifier,"generation":entry["generation"],"base":source["base"],"base_tree":source["tree"],"source_digest":source["digest"],"patch_digest":patch["digest"],"patch_sha256":patch["patch_sha256"],"tree":patch["tree"],"commands":commands,"limits":{"timeout":timeout,"memory_mb":memory_mb,"pids":pids,"cpus":cpus},"result":result,"created_at":now()}
            self.put("validation-reports",identifier,report)
            outcomes=result.get("outcomes")
            if not result.get("successful") or result.get("backend")!=runner.name or result.get("image")!=image or not isinstance(outcomes,list) or len(outcomes)!=len(commands) or any(not isinstance(item,dict) or item.get("command")!=command or type(item.get("returncode")) is not int or item["returncode"]!=0 or item.get("error") is not None for item,command in zip(outcomes or [],commands)):raise TrioError("VALIDATION_FAILED")
            report["seal_digest"]=digest(report);self.put("seals",identifier,report);entry.update(stage="validated",seal=report["seal_digest"]);self.put("contributions",identifier,entry)
            return {"schema":"trio.contribution-validation/v1","id":identifier,"seal_digest":report["seal_digest"],"base":source["base"],"tree":patch["tree"],"commands":commands,"result":result}
    def sealed(self,identifier):
        entry=self.get("contributions",identifier);seal=self.get("seals",identifier);patch,source=self.patched(identifier)
        if seal.get("seal_digest")!=digest({k:v for k,v in seal.items() if k!="seal_digest"}) or entry.get("seal")!=seal.get("seal_digest") or seal["generation"]!=entry["generation"] or seal["patch_digest"]!=patch["digest"] or seal["source_digest"]!=source["digest"] or seal["tree"]!=patch["tree"]:raise TrioError("SEAL_STALE")
        return entry,seal,patch,source
    def branch(self,value):
        if not isinstance(value,str) or not re.fullmatch(r"[A-Za-z0-9_/-][A-Za-z0-9._/-]{0,199}",value) or ".." in value or "//" in value or value.endswith(("/",".",".lock")) or any(x.startswith(".") for x in value.split("/")):raise TrioError("INVALID_BRANCH",exit_code=2)
        return value
    def missing_get(self,transport,path):
        try:return transport.get(path)
        except TrioError as error:
            if error.code=="TARGET_MISSING":return None
            raise
    def fork_check(self,data,upstream,owner):
        if not isinstance(data,dict) or data.get("private") is not False or data.get("fork") is not True or data.get("parent",{}).get("id")!=upstream["id"] or data.get("owner",{}).get("login","").lower()!=owner.lower():raise TrioError("FORK_MISMATCH")
    def plan(self,identifier,transport,branch,title,body,author_name,author_email,message=None,mode="direct",fork_owner=None,revision=False):
        self.branch(branch)
        if mode not in {"direct","fork"} or not isinstance(title,str) or not 1<=len(title.encode())<=256 or not isinstance(body,str) or len(body.encode())>60000 or not isinstance(author_name,str) or not author_name or any(x in author_name for x in "\r\n<>") or not isinstance(author_email,str) or not re.fullmatch(r"[^ <>\r\n]+@[^ <>\r\n]+",author_email):raise TrioError("INVALID_PUBLICATION",exit_code=2)
        with self.store.write_lock():
            entry,seal,patch,source=self.sealed(identifier);identity=transport.identity();upstream=transport.repository(entry["repository"],public=True)
            if upstream["id"]!=entry["repository_id"]:raise TrioError("IDENTITY_MISMATCH")
            for name,value in decode_files(patch["files"],max_source_bytes=source_limit(source)).items():
                if transport._token in name or transport._token.encode() in value["raw"]:raise TrioError("CREDENTIAL_CONTENT")
            policy=self.policy();rule=policy["repositories"].get(entry["repository"],{})
            if rule.get("mode","direct")!=mode:raise TrioError("GATE_CLOSED")
            base_ref=transport.get("/repos/"+entry["repository"]+"/git/ref/heads/"+source["branch"])
            if base_ref.get("object",{}).get("sha")!=source["base"]:raise TrioError("BASE_CHANGED")
            owner=fork_owner or identity["login"]
            if mode=="fork" and (not re.fullmatch(r"[A-Za-z0-9-]{1,39}",owner) or rule.get("fork_owner",identity["login"])!=owner):raise TrioError("GATE_CLOSED")
            destination=entry["repository"] if mode=="direct" else owner+"/"+entry["repository"].split("/")[1]
            remote=transport.repository(destination,public=True) if mode=="direct" else self.missing_get(transport,"/repos/"+destination)
            if remote and mode=="fork":self.fork_check(remote,upstream,owner)
            managed=self.get("managed",identifier) if revision else None
            parent=source["base"]
            if revision:
                if managed["destination"]!=destination or managed["branch"]!=branch or managed["repository_id"]!=(remote or {}).get("id"):raise TrioError("MANAGED_BRANCH_MISMATCH")
                head=transport.get("/repos/"+destination+"/git/ref/heads/"+branch)
                if head.get("object",{}).get("sha")!=managed["commit"]:raise TrioError("HEAD_CHANGED")
                parent=managed["commit"]
            elif remote and self.missing_get(transport,"/repos/"+destination+"/git/ref/heads/"+branch) is not None:raise TrioError("BRANCH_EXISTS")
            timestamp=datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z");author={"name":author_name,"email":author_email};message=message or title
            if not isinstance(message,str) or not message or len(message.encode())>60000:raise TrioError("INVALID_PUBLICATION",exit_code=2)
            commit=git_object("commit",commit_bytes(patch["tree"],parent,message,author,timestamp))
            plan={"schema":"trio.contribution-plan/v1","id":uuid.uuid4().hex,"contribution":identifier,"generation":entry["generation"],"operation":"contribution-publish","identity":identity,"repository":entry["repository"],"repository_id":upstream["id"],"destination":destination,"destination_id":remote["id"] if remote else None,"mode":mode,"fork_owner":owner if mode=="fork" else None,"base":source["base"],"base_branch":source["branch"],"parent":parent,"tree":patch["tree"],"branch":branch,"title":title,"body":body,"message":message,"author":author,"timestamp":timestamp,"commit":commit,"seal_digest":seal["seal_digest"],"patch_digest":patch["digest"],"policy_digest":digest(policy),"revision":revision,"previous_pr":managed.get("pr") if managed else None,"created_at":now()}
            transport.safe_content(plan);plan["digest"]=digest(plan);self.put("publication-plans",plan["id"],plan);entry["plan"]=plan["id"];self.put("contributions",identifier,entry);return plan
    def inspect_plan(self,identifier):
        plan=self.get("publication-plans",identifier);self.check_plan(plan)
        path=confined(self.root,"publication-journals/"+identifier+".json")
        return {"schema":"trio.contribution-inspect/v1","plan":plan,"journal":read_json(path) if path.exists() else None}
    def publication_current(self,transport,plan,policy,require_permissions=True):
        upstream=transport.repository(plan["repository"],public=True)
        if upstream["id"]!=plan["repository_id"]:raise TrioError("IDENTITY_MISMATCH")
        ref=transport.get("/repos/"+plan["repository"]+"/git/ref/heads/"+plan["base_branch"])
        if ref.get("object",{}).get("sha")!=plan["base"]:raise TrioError("BASE_CHANGED")
        destination=self.missing_get(transport,"/repos/"+plan["destination"])
        if destination:
            if destination.get("full_name","").lower()!=plan["destination"].lower():raise TrioError("IDENTITY_MISMATCH")
            if destination.get("private") is not False:raise TrioError("PUBLIC_REPO_REQUIRED")
            if plan["destination_id"] and destination.get("id")!=plan["destination_id"]:raise TrioError("IDENTITY_MISMATCH")
            if plan["mode"]=="fork":self.fork_check(destination,upstream,plan["fork_owner"])
            if require_permissions and not any(destination.get("permissions",{}).get(x) is True for x in ("push","maintain","admin")):raise TrioError("PERMISSION_DENIED",exit_code=4)
        elif plan["mode"]!="fork":raise TrioError("TARGET_MISSING")
        if require_permissions and "pull_requests:write" not in policy["permissions"]:raise TrioError("PERMISSION_DENIED",exit_code=4)
        return upstream,destination
    def journal_step(self,journal,name,transport,method,path,payload,verify):
        steps=journal["steps"]
        if name in steps:
            if steps[name]["outcome"]=="successful":return steps[name].get("receipt")
            raise TrioError("RECOVERY_REQUIRED")
        steps[name]={"outcome":"attempted","attempted_at":now()};self.put("publication-journals",journal["id"],journal)
        try:
            response=transport.request(method,path,payload)
            receipt=verify(response)
            if receipt is None:raise TrioError("WRITE_UNCERTAIN",exit_code=4)
            steps[name].update(outcome="pending" if receipt.get("pending") else "successful",receipt=receipt,completed_at=now())
        except TrioError as error:
            steps[name].update(outcome="uncertain" if error.code=="WRITE_UNCERTAIN" else "failed",error=error.code,completed_at=now());self.put("publication-journals",journal["id"],journal);raise
        except BaseException:
            steps[name].update(outcome="uncertain",error="INTERRUPTED");self.put("publication-journals",journal["id"],journal);raise
        self.put("publication-journals",journal["id"],journal);return receipt
    def matching_pr(self,item,plan,destination_id):
        return isinstance(item,dict) and item.get("base",{}).get("repo",{}).get("id")==plan["repository_id"] and item.get("base",{}).get("ref")==plan["base_branch"] and item.get("head",{}).get("repo",{}).get("id")==destination_id and item.get("head",{}).get("ref")==plan["branch"] and item.get("head",{}).get("sha")==plan["commit"] and item.get("user",{}).get("id")==plan["identity"]["id"] and item.get("title")==plan["title"] and item.get("body")==plan["body"]
    def publish(self,identifier,actor,transport):
        with self.store.write_lock():
            plan=self.get("publication-plans",identifier);self.check_plan(plan);self.require_approval(plan);policy=self.gate(plan,actor,transport,True)
            entry,seal,patch,source=self.sealed(plan["contribution"])
            screen_files(decode_files(patch["files"],max_source_bytes=source_limit(source)))
            for name,value in decode_files(patch["files"],max_source_bytes=source_limit(source)).items():
                if transport._token in name or transport._token.encode() in value["raw"]:raise TrioError("CREDENTIAL_CONTENT")
            if plan["seal_digest"]!=seal["seal_digest"] or plan["generation"]!=entry["generation"]:raise TrioError("SEAL_STALE")
            upstream,destination=self.publication_current(transport,plan,policy)
            path=confined(self.root,"publication-journals/"+identifier+".json")
            journal=read_json(path) if path.exists() else {"schema":"trio.contribution-journal/v1","id":identifier,"plan_digest":plan["digest"],"steps":{},"outcome":"in_progress","created_at":now()}
            if journal["plan_digest"]!=plan["digest"]:raise TrioError("PLAN_CORRUPT")
            if any(x["outcome"]!="successful" for x in journal["steps"].values()):raise TrioError("RECOVERY_REQUIRED")
            if journal["outcome"]=="successful":return journal
            self.put("publication-journals",identifier,journal)
            def step(name,method,path,payload,verify):return self.journal_step(journal,name,transport,method,path,payload,verify)
            try:
                if destination is None:
                    # Only account-owned public forks: organization forks require an
                    # explicitly existing verified fork; no inferred org privileges.
                    if plan["fork_owner"]!=plan["identity"]["login"]:raise TrioError("EXISTING_PUBLIC_FORK_REQUIRED")
                    def fork_response(response):
                        self.fork_check(response,upstream,plan["fork_owner"])
                        return {"id":response["id"],"pending":True}
                    step("fork","POST","/repos/"+plan["repository"]+"/forks",{},fork_response)
                    destination=self.missing_get(transport,"/repos/"+plan["destination"])
                    if destination is None:
                        journal["outcome"]="pending";self.put("publication-journals",identifier,journal);return journal
                    self.fork_check(destination,upstream,plan["fork_owner"])
                    journal["steps"]["fork"].update(outcome="successful",receipt={"id":destination["id"],"pending":False});self.put("publication-journals",identifier,journal)
                journal["destination_id"]=destination["id"]
                current=self.missing_get(transport,"/repos/"+plan["destination"]+"/git/ref/heads/"+plan["branch"])
                branch_done=journal["steps"].get("ref",{}).get("outcome")=="successful"
                if current and not branch_done and not plan["revision"]:raise TrioError("BRANCH_EXISTS")
                expected=plan["commit"] if branch_done else plan["parent"]
                if current and plan["revision"] and current.get("object",{}).get("sha")!=expected:raise TrioError("HEAD_CHANGED")
                if branch_done and (not current or current.get("object",{}).get("sha")!=plan["commit"]):raise TrioError("HEAD_CHANGED")
                if plan["revision"]:
                    pr=plan["previous_pr"];existing=transport.get("/repos/"+plan["repository"]+"/pulls/"+str(pr["number"]))
                    if existing.get("id")!=pr["id"] or existing.get("state")!="open" or existing.get("head",{}).get("repo",{}).get("id")!=destination["id"] or existing.get("head",{}).get("sha")!=(plan["commit"] if branch_done else plan["parent"]) or existing.get("base",{}).get("repo",{}).get("id")!=plan["repository_id"] or existing.get("base",{}).get("ref")!=plan["base_branch"]:raise TrioError("PR_CHANGED")
                self.publication_current(transport,plan,policy)
                prefix="/repos/"+plan["destination"]
                original=decode_files(source["files"],max_source_bytes=source_limit(source));changed=decode_files(patch["files"],max_source_bytes=source_limit(source))
                for name in patch["paths"]:
                    if name not in changed:continue
                    value=changed[name];expected_sha=value["sha"]
                    step("blob:"+expected_sha,"POST",prefix+"/git/blobs",{"content":base64.b64encode(value["raw"]).decode(),"encoding":"base64"},lambda x,expected_sha=expected_sha:{"sha":expected_sha} if isinstance(x,dict) and x.get("sha")==expected_sha else None)
                changes=[]
                for name in patch["paths"]:
                    value=changed.get(name);changes.append({"path":name,"mode":value["mode"] if value else original[name]["mode"],"type":"blob","sha":value["sha"] if value else None})
                step("tree","POST",prefix+"/git/trees",{"base_tree":source["tree"],"tree":changes},lambda x:{"sha":plan["tree"]} if isinstance(x,dict) and x.get("sha")==plan["tree"] else None)
                author={**plan["author"],"date":plan["timestamp"]}
                step("commit","POST",prefix+"/git/commits",{"message":plan["message"]+"\n","tree":plan["tree"],"parents":[plan["parent"]],"author":author,"committer":author},lambda x:{"sha":plan["commit"]} if isinstance(x,dict) and x.get("sha")==plan["commit"] and x.get("tree",{}).get("sha")==plan["tree"] else None)
                # Verify complete remote tree before creating/updating a visible ref.
                remote=transport.get(prefix+"/git/trees/"+plan["tree"]+"?recursive=1")
                expected_rows=sorted((k,v["mode"],v["sha"]) for k,v in changed.items())
                if remote.get("truncated") is not False or sorted((x.get("path"),x.get("mode"),x.get("sha")) for x in remote.get("tree",[]) if x.get("type")=="blob")!=expected_rows or any(x.get("type") not in {"blob","tree"} for x in remote.get("tree",[])):raise TrioError("REMOTE_TREE_MISMATCH")
                self.publication_current(transport,plan,policy)
                if plan["revision"]:
                    step("ref","PATCH",prefix+"/git/refs/heads/"+plan["branch"],{"sha":plan["commit"],"force":False},lambda x:{"sha":plan["commit"]} if isinstance(x,dict) and x.get("object",{}).get("sha")==plan["commit"] else None)
                else:step("ref","POST",prefix+"/git/refs",{"ref":"refs/heads/"+plan["branch"],"sha":plan["commit"]},lambda x:{"sha":plan["commit"]} if isinstance(x,dict) and x.get("ref")=="refs/heads/"+plan["branch"] and x.get("object",{}).get("sha")==plan["commit"] else None)
                if journal["steps"].get("pr",{}).get("outcome")=="successful":
                    result=journal["steps"]["pr"]["receipt"]
                    existing=transport.get("/repos/"+plan["repository"]+"/pulls/"+str(result["number"]))
                    if existing.get("id")!=result["id"] or not self.matching_pr(existing,plan,destination["id"]):raise TrioError("PR_CHANGED")
                elif plan["revision"]:
                    pr=plan["previous_pr"];existing=transport.get("/repos/"+plan["repository"]+"/pulls/"+str(pr["number"]))
                    if existing.get("id")!=pr["id"] or existing.get("state")!="open" or existing.get("head",{}).get("repo",{}).get("id")!=destination["id"] or existing.get("head",{}).get("sha")!=plan["commit"]:raise TrioError("PR_CHANGED")
                    result=step("pr","PATCH","/repos/"+plan["repository"]+"/pulls/"+str(pr["number"]),{"title":plan["title"],"body":plan["body"]},lambda x:{"id":x["id"],"number":x["number"],"url":x.get("html_url")} if self.matching_pr(x,plan,destination["id"]) else None)
                else:
                    head=plan["destination"].split("/")[0]+":"+plan["branch"]
                    existing=transport.pages("/repos/"+plan["repository"]+"/pulls?state=all&head="+head.replace(":","%3A")+"&base="+plan["base_branch"],limit=1000,budget=10)
                    if not existing["complete"] or existing["records"]:raise TrioError("PR_EXISTS_OR_UNKNOWN")
                    result=step("pr","POST","/repos/"+plan["repository"]+"/pulls",{"title":plan["title"],"body":plan["body"],"head":head,"base":plan["base_branch"]},lambda x:{"id":x["id"],"number":x["number"],"url":x.get("html_url")} if self.matching_pr(x,plan,destination["id"]) else None)
                journal.update(outcome="successful",completed_at=now());managed={"schema":"trio.managed-contribution/v1","contribution":plan["contribution"],"destination":plan["destination"],"repository_id":destination["id"],"branch":plan["branch"],"commit":plan["commit"],"tree":plan["tree"],"pr":result,"plan":plan["id"]};self.put("managed",plan["contribution"],managed);entry.update(stage="published",publication=managed);self.put("contributions",entry["id"],entry)
            except TrioError as error:journal.update(outcome="uncertain" if error.code in {"WRITE_UNCERTAIN","RECOVERY_REQUIRED"} else "stopped",error=error.code)
            self.put("publication-journals",identifier,journal);return journal
    def reconcile(self,identifier,transport):
        with self.store.write_lock():
            plan=self.get("publication-plans",identifier);self.check_plan(plan);journal=self.get("publication-journals",identifier)
            if transport.identity()!=plan["identity"]:raise TrioError("IDENTITY_CHANGED")
            upstream,destination=self.publication_current(transport,plan,self.policy(),False)
            if destination:
                remote_ref=self.missing_get(transport,"/repos/"+plan["destination"]+"/git/ref/heads/"+plan["branch"])
                allowed={plan["commit"],plan["parent"]} if plan["revision"] else {plan["commit"]}
                if remote_ref and remote_ref.get("object",{}).get("sha") not in allowed or plan["revision"] and remote_ref is None:raise TrioError("HEAD_CHANGED")
            for name,step in journal["steps"].items():
                if step["outcome"] not in {"uncertain","attempted","pending"}:continue
                receipt=None;prefix="/repos/"+plan["destination"]
                if name=="fork" and destination:receipt={"id":destination["id"],"pending":False}
                elif destination and name.startswith("blob:"):
                    oid=name.split(":",1)[1];remote=self.missing_get(transport,prefix+"/git/blobs/"+oid)
                    if remote and remote.get("sha")==oid:receipt={"sha":oid}
                elif destination and name in {"tree","commit"}:
                    oid=plan[name];remote=self.missing_get(transport,prefix+"/git/"+("trees/" if name=="tree" else "commits/")+oid)
                    if remote and remote.get("sha")==oid and (name=="tree" or remote.get("tree",{}).get("sha")==plan["tree"]):receipt={"sha":oid}
                elif destination and name=="ref":
                    remote=self.missing_get(transport,prefix+"/git/ref/heads/"+plan["branch"])
                    if remote and remote.get("object",{}).get("sha")==plan["commit"]:receipt={"sha":plan["commit"]}
                elif destination and name=="pr":
                    head=plan["destination"].split("/")[0]+":"+plan["branch"]
                    rows=transport.pages("/repos/"+plan["repository"]+"/pulls?state=all&head="+head.replace(":","%3A")+"&base="+plan["base_branch"],limit=1000,budget=10)
                    found=[x for x in rows["records"] if self.matching_pr(x,plan,destination["id"])]
                    if rows["complete"] and len(found)==1:receipt={"id":found[0]["id"],"number":found[0]["number"],"url":found[0].get("html_url")}
                if receipt is not None:step.update(outcome="successful",receipt=receipt,confirmed_at=now())
                else:step["outcome"]="uncertain"
            journal["outcome"]="successful" if journal["outcome"]=="successful" else "recovered" if all(x["outcome"]=="successful" for x in journal["steps"].values()) else "uncertain";journal["reconciled_at"]=now();self.put("publication-journals",identifier,journal);return journal
    def refresh(self,identifier,transport,base,branch,request_budget=1000,max_source_bytes=None):
        # Reacquire at explicit exact base, then apply the same reviewed patch.
        # A conflict stops; all prior seals/approvals are invalidated by generation.
        patch,_=self.patched(identifier);raw=base64.b64decode(patch["patch"],validate=True)
        result=self.acquire(identifier,transport,base,branch,request_budget,max_source_bytes)
        return {"schema":"trio.contribution-refresh/v1","acquired":result,"patch":self.patch(identifier,raw),"requires_revalidation":True}
