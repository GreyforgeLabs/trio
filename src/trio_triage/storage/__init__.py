"""Confined durable storage. Newly authored; Apache-2.0."""
import contextlib, hashlib, json, os, sqlite3, tempfile, fcntl, shutil
from pathlib import Path
from ..errors import TrioError

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode("utf-8")
def digest(value): return hashlib.sha256(canonical(value)).hexdigest()
def read_json(path,max_bytes=16777216):
    p=Path(path).absolute()
    if any(x.is_symlink() for x in [p,*p.parents]): raise TrioError("SCOPE_DENIED")
    if not p.is_file():raise TrioError("EVIDENCE_MISSING")
    if p.stat().st_size>max_bytes: raise TrioError("RESOURCE_LIMIT")
    def pairs(values):
        d={}
        for k,v in values:
            if k in d:raise ValueError("duplicate key")
            d[k]=v
        return d
    try: return json.loads(p.read_bytes(),object_pairs_hook=pairs,parse_constant=lambda x: (_ for _ in ()).throw(ValueError()))
    except (ValueError,UnicodeError): raise TrioError("EVIDENCE_CORRUPT") from None

def atomic_json(path,value):
    p=Path(path).absolute()
    if any(x.is_symlink() for x in [p,*p.parents]):raise TrioError("SCOPE_DENIED")
    p.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=".pending-",dir=p.parent)
    try:
        with os.fdopen(fd,"wb") as f: f.write(canonical(value)+b"\n");f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o600);os.replace(tmp,p)
        d=os.open(p.parent,os.O_RDONLY);os.fsync(d);os.close(d)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def confined(root,relative):
    r=Path(root).resolve();p=Path(relative)
    if p.is_absolute() or ".." in p.parts: raise TrioError("SCOPE_DENIED")
    out=r/p
    if any(x.is_symlink() for x in [out,*out.parents] if x!=r.parent):raise TrioError("SCOPE_DENIED")
    if not out.resolve().is_relative_to(r):raise TrioError("SCOPE_DENIED")
    return out

DEFAULTS={"writes_enabled":False,"enabled_actions":[],"publisher_id":None,"installation_id":None,"workspace_id":"default","policy_revision":"1","roles":{},"request_budget":100,"timeout":45,"corpus_size":100,"object_max_bytes":67108864,"dataset_max_bytes":5000000000,"state_max_bytes":10000000000,"reserve_bytes":256000000,"index_max_bytes":536870912,"projection_max_units":1000000,"metadata_max_bytes":16777216,"verified_max_bytes":134217728,"candidate_pool":1000,"max_items":10,"fragments_per_item":2,"excerpt_bytes":512,"retrieve_bytes":4096,"max_bytes":12000}

def validate_config(c):
    if not isinstance(c,dict) or set(c)-set(DEFAULTS):raise TrioError("INVALID_CONFIG",exit_code=2)
    merged={**DEFAULTS,**c}
    if type(merged["writes_enabled"]) is not bool:raise TrioError("INVALID_CONFIG",exit_code=2)
    for k,v in DEFAULTS.items():
        if type(v) is int and (type(merged[k]) is not int or merged[k]<1):raise TrioError("INVALID_CONFIG",exit_code=2)
    roles=merged["roles"]
    if not isinstance(roles,dict) or any(not isinstance(k,str) or not k or not isinstance(v,list) or any(not isinstance(x,str) or x not in {"reader","contributor","reviewer","publisher","maintainer"} for x in v) for k,v in roles.items()):raise TrioError("INVALID_CONFIG",exit_code=2)
    acts=merged["enabled_actions"]
    if not isinstance(acts,list) or any(not isinstance(x,str) or x not in {"comment","close","reopen"} for x in acts):raise TrioError("INVALID_CONFIG",exit_code=2)
    for k in ("publisher_id","installation_id"):
        if merged[k] is not None and (not isinstance(merged[k],str) or not merged[k]):raise TrioError("INVALID_CONFIG",exit_code=2)
    for k in ("workspace_id","policy_revision"):
        if not isinstance(merged[k],str) or not merged[k]:raise TrioError("INVALID_CONFIG",exit_code=2)
    return merged

class Store:
    def __init__(self,home=None,config_location=None):
        base=Path(config_location or os.environ.get("XDG_CONFIG_HOME",str(Path.home()/".config")))/"trio-triage"
        p=Path(home) if home else Path(os.environ.get("XDG_STATE_HOME",str(Path.home()/".local/state")))/"trio-triage"
        if not p.is_absolute():p=base/p
        if any(x.is_symlink() for x in [p,*p.parents]):raise TrioError("SCOPE_DENIED")
        self.root=p.resolve()
        source=Path(__file__).resolve().parents[3]
        if self.root==Path("/") or self.root==Path.home() or self.root==source or self.root.is_relative_to(source):raise TrioError("SCOPE_DENIED")
        self.cache_root=(self.root/"cache") if home else Path(os.environ.get("XDG_CACHE_HOME",str(Path.home()/".cache")))/"trio-triage"
        self.config_root=base
        self.config=validate_config({})
        if (base/"config.json").is_file():self.config=validate_config(read_json(base/"config.json"))
        if (self.root/"config.json").is_file():self.config=validate_config(read_json(self.root/"config.json"))
    def require(self):
        if not (self.root/"state.sqlite").is_file():raise TrioError("NOT_INITIALIZED")
        with self.db() as db:
            v=db.execute("PRAGMA user_version").fetchone()[0]
            if v!=1:raise TrioError("SCHEMA_NEWER" if v>1 else "FOREIGN_SCHEMA")
            if db.execute("PRAGMA application_id").fetchone()[0]!=0x5452494f:raise TrioError("FOREIGN_SCHEMA")
            required={"events":["id","entity","data"],"local_reviews":["id","finding","digest","actor","decision","active"]}
            for table,columns in required.items():
                if [r[1] for r in db.execute("PRAGMA table_info("+table+")")]!=columns:raise TrioError("EVIDENCE_CORRUPT")
    def init(self,config=None):
        c=validate_config(config or self.config)
        if self.root.exists() and any(self.root.iterdir()):raise TrioError("ALREADY_INITIALIZED")
        self.root.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
        stage=Path(tempfile.mkdtemp(prefix=".trio-init-",dir=self.root.parent))
        try:
            atomic_json(stage/"config.json",c)
            with sqlite3.connect(stage/"state.sqlite") as db:
                db.execute("PRAGMA user_version=1");db.execute("PRAGMA application_id="+str(0x5452494f))
                db.execute("CREATE TABLE events(id TEXT PRIMARY KEY, entity TEXT NOT NULL, data TEXT NOT NULL)")
                db.execute("CREATE TABLE local_reviews(id TEXT PRIMARY KEY, finding TEXT, digest TEXT, actor TEXT, decision TEXT, active INTEGER)")
            os.chmod(stage/"state.sqlite",0o600)
            fd=os.open(stage/"state.sqlite",os.O_RDONLY);os.fsync(fd);os.close(fd)
            if self.root.exists():self.root.rmdir()
            os.replace(stage,self.root)
            fd=os.open(self.root.parent,os.O_RDONLY);os.fsync(fd);os.close(fd)
            self.config=c
        finally:
            if stage.exists():shutil.rmtree(stage)
    @contextlib.contextmanager
    def write_lock(self):
        path=confined(self.root,"state.lock")
        with open(path,"a+b") as stream:
            os.chmod(path,0o600);fcntl.flock(stream,fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(stream,fcntl.LOCK_UN)
    @contextlib.contextmanager
    def db(self,write=False):
        p=self.root/"state.sqlite"
        if not p.exists():raise TrioError("NOT_INITIALIZED")
        lock=self.write_lock() if write else contextlib.nullcontext()
        lock.__enter__()
        db=sqlite3.connect(str(p) if write else p.as_uri()+"?mode=ro&immutable=1",uri=not write)
        try:
            yield db
            if write:db.commit()
        except Exception:
            if write:db.rollback()
            raise
        finally:db.close();lock.__exit__(None,None,None)
    def role(self,actor,capability):
        if capability not in self.config["roles"].get(actor,[]):raise TrioError("REVIEW_UNVERIFIED" if capability=="reviewer" else "SCOPE_DENIED")
