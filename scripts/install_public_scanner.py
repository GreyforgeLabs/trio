# SPDX-License-Identifier: Apache-2.0
"""Explicit public-development utility; install only the pinned offline scanner."""
import argparse,hashlib,io,os,tarfile,urllib.request
from pathlib import Path
VERSION="8.30.1"
URL="https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz"
ARCHIVE_SHA="551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"
BINARY_SIZE=21958840
BINARY_SHA="88f91962aa2f93ac6ab281d553b9e125f5197bbbce38f9f2437f7299c32e5509"
def install(output):
    path=Path(output).absolute()
    if any(p.is_symlink() for p in [path,*path.parents]) or path.exists():raise ValueError("scanner destination refused")
    with urllib.request.urlopen(URL,timeout=45) as response:raw=response.read(20000001)
    if len(raw)>20000000 or hashlib.sha256(raw).hexdigest()!=ARCHIVE_SHA:raise ValueError("scanner archive refused")
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members=archive.getmembers();selected=[m for m in members if m.name=="gitleaks"]
        if len(selected)!=1 or not selected[0].isfile() or selected[0].size!=BINARY_SIZE:raise ValueError("scanner archive refused")
        binary=archive.extractfile(selected[0]).read()
    if hashlib.sha256(binary).hexdigest()!=BINARY_SHA:raise ValueError("scanner binary refused")
    path.parent.mkdir(parents=True,exist_ok=True)
    with open(path,"xb") as stream:stream.write(binary);stream.flush();os.fsync(stream.fileno())
    os.chmod(path,0o700)
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--output",required=True);args=parser.parse_args()
    try:install(args.output);print('{"scanner":"gitleaks","version":"8.30.1","verified":true}')
    except Exception:print('{"scanner":"gitleaks","verified":false}');raise SystemExit(3)
