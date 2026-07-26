"""Episodic memory / workflow cache backed by a local vector index.

Per ARCHITECTURE.md section 8: past workflows (successful and failed) are
embedded by objective (+ light context) so the planner can retrieve
few-shot examples, and successful `TaskGraph`s can be replayed instead of
re-planned from scratch when similarity is high (the "workflow cache").

Uses `chromadb`'s persistent local client if available. The import is
lazy/optional: if chromadb isn't installed, `EpisodicMemory` degrades to
a no-op in-memory list-based fallback so the rest of the app still runs
in a hackathon demo without the dependency.

TODO(chromadb): `pip install chromadb` for real persistent vector search.
TODO(embeddings): default `embed_fn` stub calls a local NIM-style
OpenAI-compatible embeddings endpoint via httpx. Swap for a real
embedding model/service as needed.
"""

from __future__ import annotations

import json
import math
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

EmbedFn = Callable[[str], list[float]]

try:
    import chromadb  # type: ignore

    _HAS_CHROMADB = True
except ImportError:  # pragma: no cover - optional dependency
    chromadb = None  # type: ignore
    _HAS_CHROMADB = False


def _default_embed_fn(text: str) -> list[float]:
    """Stub embedding call to a local OpenAI-compatible embeddings endpoint.

    Mirrors the pattern used for the local reasoning LLM (NIM / any
    OpenAI-compatible server). Swallows errors and falls back to a cheap
    deterministic hash-based pseudo-embedding so the rest of the pipeline
    keeps working even with no embedding server running (hackathon demo
    resilience over correctness).
    """
    base_url = os.environ.get("EMBEDDING_BASE_URL", "http://localhost:8000/v1")
    model = os.environ.get("EMBEDDING_MODEL", "nvidia/nv-embedqa-e5-v5")
    try:
        import httpx

        resp = httpx.post(
            f"{base_url}/embeddings",
            json={"model": model, "input": text},
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["data"][0]["embedding"]
    except Exception:
        # Deterministic fallback pseudo-embedding (NOT semantically meaningful,
        # just keeps cosine-similarity code paths exercisable offline).
        vec = [0.0] * 32
        for i, ch in enumerate(text.lower().encode("utf-8", errors="ignore")):
            vec[i % 32] += (ch % 17) / 17.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class EpisodicMemory:
    """Vector-indexed episodic memory of past task workflows.

    Each entry: {task_id, objective, task_graph_json, success, ts}.
    Retrieval is cosine similarity over `embed_fn(objective)`.
    """

    def __init__(
        self,
        persist_dir: str | Path | None = None,
        embed_fn: Optional[EmbedFn] = None,
        collection_name: str = "workflows",
    ) -> None:
        self.embed_fn: EmbedFn = embed_fn or _default_embed_fn
        self._persist_dir = Path(persist_dir) if persist_dir else (
            Path(__file__).resolve().parent.parent / "data" / "chroma"
        )
        self._collection_name = collection_name
        self._collection = None
        self._fallback: list[dict[str, Any]] = []  # used when chromadb unavailable

        if _HAS_CHROMADB:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(self._persist_dir))
            self._collection = client.get_or_create_collection(self._collection_name)

    def add_workflow(
        self,
        task_id: str,
        objective: str,
        task_graph_json: str,
        success: bool,
    ) -> None:
        """Embed and store one past workflow (successful or failed)."""
        embedding = self.embed_fn(objective)
        metadata = {
            "task_id": task_id,
            "objective": objective,
            "task_graph_json": task_graph_json,
            "success": bool(success),
            "ts": time.time(),
        }
        if self._collection is not None:
            self._collection.upsert(
                ids=[f"{task_id}:{uuid.uuid4().hex[:6]}"],
                embeddings=[embedding],
                metadatas=[
                    {
                        "task_id": task_id,
                        "objective": objective,
                        "success": bool(success),
                        "ts": metadata["ts"],
                    }
                ],
                documents=[task_graph_json],
            )
        else:
            self._fallback.append({**metadata, "embedding": embedding})

    def find_similar(
        self,
        objective: str,
        top_k: int = 3,
        only_success: bool = True,
    ) -> list[dict[str, Any]]:
        """Return up to `top_k` past workflows similar to `objective`.

        Each result dict: {task_id, objective, task_graph_json, success,
        similarity}. Sorted descending by similarity.
        """
        query_embedding = self.embed_fn(objective)

        if self._collection is not None:
            where = {"success": True} if only_success else None
            n_results = max(top_k * 3, top_k)  # over-fetch a bit before filtering
            res = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=where,
            )
            out: list[dict[str, Any]] = []
            ids = res.get("ids", [[]])[0]
            docs = res.get("documents", [[]])[0]
            metas = res.get("metadatas", [[]])[0]
            dists = res.get("distances", [[]])[0] if res.get("distances") else [None] * len(ids)
            for doc, meta, dist in zip(docs, metas, dists):
                similarity = 1.0 - dist if dist is not None else None
                out.append(
                    {
                        "task_id": meta.get("task_id"),
                        "objective": meta.get("objective"),
                        "task_graph_json": doc,
                        "success": meta.get("success"),
                        "similarity": similarity,
                    }
                )
            out.sort(key=lambda r: (r["similarity"] if r["similarity"] is not None else 0.0), reverse=True)
            return out[:top_k]

        # Fallback: brute-force cosine similarity over in-memory list.
        candidates = [
            e for e in self._fallback if (e["success"] or not only_success)
        ]
        scored = [
            {
                "task_id": e["task_id"],
                "objective": e["objective"],
                "task_graph_json": e["task_graph_json"],
                "success": e["success"],
                "similarity": _cosine_similarity(query_embedding, e["embedding"]),
            }
            for e in candidates
        ]
        scored.sort(key=lambda r: r["similarity"], reverse=True)
        return scored[:top_k]
