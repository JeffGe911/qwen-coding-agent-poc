"""Index the chunks with local bge-m3 embeddings (Ollama /api/embed on 127.0.0.1) and BM25, and retrieve with both.

Dense search finds paraphrases and cross-language matches (a Chinese question, English documents); BM25 finds exact
tokens such as option names (-Wno-fatal), system tasks ($fatal) and warning codes, which embeddings often blur.
The two rankings are fused with reciprocal-rank fusion. Standard library only; vectors are kept as float32 bytes.
"""
from array import array
import hashlib
import json
import math
from pathlib import Path
import re
import time
import urllib.request

from qwen_agent.client import validate_url

from . import corpus

EMBED_MODEL = "bge-m3"
INDEX_VERSION = "index-v1"
TOKEN = re.compile(r"[$`]?[a-z0-9_]+(?:[-.][a-z0-9_]+)*")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def origin(base_url):
    """http://127.0.0.1:PORT from a loopback /v1 base URL (non-loopback URLs are refused, as for the model client)."""
    return validate_url(base_url)[: -len("/v1")]


def embed(texts, base_url, model=EMBED_MODEL, batch=32, timeout=300):
    vecs = []
    for i in range(0, len(texts), batch):
        body = json.dumps({"model": model, "input": texts[i:i + batch]}).encode()
        req = urllib.request.Request(origin(base_url) + "/api/embed", data=body, headers={"Content-Type": "application/json"})
        with OPENER.open(req, timeout=timeout) as r:
            for v in json.loads(r.read())["embeddings"]:
                norm = math.sqrt(sum(x * x for x in v)) or 1.0
                vecs.append(array("f", (x / norm for x in v)))
    return vecs


def model_digest(base_url, name=EMBED_MODEL):
    with OPENER.open(origin(base_url) + "/api/tags", timeout=10) as r:
        for m in json.loads(r.read()).get("models", []):
            if m["name"].split(":")[0] == name.split(":")[0]:
                return m["digest"]
    raise LookupError(f"{name} is not available on {base_url}")


def tokens(text):
    return TOKEN.findall(text.lower())


def embed_text(c):
    return f"{c['document']} > {c['section']}\n{c['text']}"


def build(root, out_dir, base_url):
    chunks = corpus.chunks(root)
    t0 = time.monotonic()
    vecs = embed([embed_text(c) for c in chunks], base_url)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "chunks.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    blob = b"".join(v.tobytes() for v in vecs)
    (out / "vectors.f32").write_bytes(blob)
    manifest = (Path(root) / "knowledge" / "MANIFEST.json").read_bytes()
    meta = {"index_version": INDEX_VERSION, "chunker_version": corpus.CHUNKER_VERSION, "max_chars": corpus.MAX_CHARS, "chunks": len(chunks),
            "dim": len(vecs[0]), "embed_model": EMBED_MODEL, "embed_model_digest": model_digest(base_url), "embed_seconds": round(time.monotonic() - t0, 1),
            "corpus_manifest_sha256": hashlib.sha256(manifest).hexdigest(), "vectors_sha256": hashlib.sha256(blob).hexdigest()}
    (out / "meta.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8", newline="\n")
    return meta


class Index:
    def __init__(self, out_dir):
        out = Path(out_dir)
        self.meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
        self.chunks = [json.loads(line) for line in (out / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if line]
        flat = array("f")
        flat.frombytes((out / "vectors.f32").read_bytes())
        dim = self.meta["dim"]
        self.vectors = [flat[i * dim:(i + 1) * dim] for i in range(len(self.chunks))]
        self.docs = [tokens(embed_text(c)) for c in self.chunks]
        self.avgdl = sum(map(len, self.docs)) / len(self.docs)
        df = {}
        for d in self.docs:
            for t in set(d):
                df[t] = df.get(t, 0) + 1
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - k + 0.5) / (k + 0.5)) for t, k in df.items()}
        self.tf = [{t: d.count(t) for t in set(d)} for d in self.docs]

    def bm25(self, query, k1=1.5, b=0.75):
        q = set(tokens(query))
        return [sum(self.idf[t] * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / self.avgdl)) for t in q if t in tf)
                for d, tf in zip(self.docs, self.tf)]

    def search(self, query, query_vec, k=6, depth=30, rrf_k=60):
        """Top-k chunks by reciprocal-rank fusion of dense and BM25 rankings, each with its scores."""
        dense = [sum(a * b for a, b in zip(query_vec, v)) for v in self.vectors]
        sparse = self.bm25(query)
        rank_d = sorted(range(len(dense)), key=lambda i: -dense[i])[:depth]
        rank_s = [i for i in sorted(range(len(sparse)), key=lambda i: -sparse[i])[:depth] if sparse[i] > 0]
        fused = {}
        for ranks in (rank_d, rank_s):
            for r, i in enumerate(ranks):
                fused[i] = fused.get(i, 0.0) + 1.0 / (rrf_k + r + 1)
        top = sorted(fused, key=lambda i: -fused[i])[:k]
        return [{"chunk": self.chunks[i], "dense": round(dense[i], 4), "bm25": round(sparse[i], 3), "rrf": round(fused[i], 5)} for i in top]
