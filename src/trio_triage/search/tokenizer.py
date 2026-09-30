# SPDX-License-Identifier: Apache-2.0
"""Explicit optional installed tokenizer with caller-selected, hash-verified local data.

No registry scanning, HTTP loader, automatic encoding download, or credential path.
"""
import base64
import hashlib
import threading
from pathlib import Path
from ..errors import TrioError

_LOCK=threading.Lock()


def load_offline_tokenizer(encoding,asset):
    if encoding not in ("cl100k_base","o200k_base"):
        raise TrioError("INVALID_ARGUMENT","select cl100k_base or o200k_base",exit_code=2)
    path=Path(asset).absolute()
    if any(p.is_symlink() for p in [path,*path.parents]):raise TrioError("SCOPE_DENIED")
    if not path.is_file():raise TrioError("TOKENIZER_UNAVAILABLE","select an existing public tokenizer BPE asset",exit_code=2)
    if path.stat().st_size>67108864:raise TrioError("RESOURCE_LIMIT")
    try:
        import tiktoken
        from tiktoken_ext import openai_public
    except ImportError:
        raise TrioError("TOKENIZER_UNAVAILABLE","install the optional tokens extra and supply its public BPE asset",exit_code=2) from None
    raw=path.read_bytes()
    def local_loader(url,expected_hash=None):
        # Expected digest comes from the explicitly installed official constructor.
        if not isinstance(expected_hash,str) or len(expected_hash)!=64 or hashlib.sha256(raw).hexdigest()!=expected_hash:
            raise TrioError("TOKENIZER_UNAVAILABLE","tokenizer asset checksum does not match installed encoding",exit_code=2)
        ranks={}
        try:
            for line in raw.splitlines():
                token,rank=line.split()
                token=base64.b64decode(token,validate=True);rank=int(rank)
                if token in ranks or rank<0:raise ValueError()
                ranks[token]=rank
            if len(set(ranks.values()))!=len(ranks):raise ValueError()
        except (ValueError,TypeError):raise TrioError("TOKENIZER_UNAVAILABLE","invalid local tokenizer asset",exit_code=2) from None
        return ranks
    with _LOCK:
        original=openai_public.load_tiktoken_bpe
        openai_public.load_tiktoken_bpe=local_loader
        try:config=getattr(openai_public,encoding)()
        finally:openai_public.load_tiktoken_bpe=original
    tokenizer=tiktoken.Encoding(**config)
    class OfflineEncoding:
        name=encoding
        def encode(self,text):return tokenizer.encode(text,disallowed_special=())
    return OfflineEncoding()
