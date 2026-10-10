"""Semantic policy retrieval using local Sentence Transformers embeddings and FAISS."""
import re
from threading import Lock
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from backend.config import SENTENCE_TRANSFORMER_MODEL

try:
    import faiss
except ImportError:  # local cosine fallback keeps the demo usable before FAISS install
    faiss = None


class PolicyRetriever:
    def __init__(self, knowledge_dir: Path):
        self.chunks = self._read_chunks(knowledge_dir)
        if not self.chunks:
            raise ValueError(f"No Markdown policy documents found in {knowledge_dir}")
        # Initialize on the first search so API startup and /health do not wait on a model download.
        self.model = None
        self.vectorizer = None
        self.vectors = None
        self.index = None
        self.retrieval_mode = "Sentence Transformer not loaded yet"
        self._initialize_lock = Lock()

    @staticmethod
    def _read_chunks(knowledge_dir: Path) -> list[dict]:
        chunks = []
        for path in sorted(knowledge_dir.glob("*.md")):
            current_heading = "overview"
            lines = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("## "):
                    if lines:
                        chunks.append({"source": path.name, "section": current_heading, "text": "\n".join(lines)})
                    current_heading = re.sub(r"[^a-z0-9]+", "-", line[3:].lower()).strip("-")
                    lines = [line]
                else:
                    lines.append(line)
            if lines:
                chunks.append({"source": path.name, "section": current_heading, "text": "\n".join(lines)})
        return chunks

    def search(self, query: str, limit: int = 3) -> list[dict]:
        self._ensure_ready()
        if self.model is not None:
            vector = self.model.encode(
                [query],
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            ).astype("float32")
        else:
            vector = normalize(self.vectorizer.transform([query])).toarray().astype("float32")
        if self.index is not None:
            scores, indices = self.index.search(vector, min(limit, len(self.chunks)))
            ranked = zip(indices[0], scores[0])
        else:
            # The same cosine ranking works without FAISS because vectors are normalized.
            scores = (self.vectors @ vector[0]).tolist()
            ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)[:limit]
        output = []
        for idx, score in ranked:
            if idx >= 0 and score > 0:
                chunk = self.chunks[int(idx)].copy()
                chunk["score"] = float(score)
                chunk["citation"] = f"{chunk['source']}#{chunk['section']}"
                output.append(chunk)
        return output

    def _ensure_ready(self) -> None:
        if self.vectors is not None:
            return
        with self._initialize_lock:
            if self.vectors is not None:
                return
            texts = [chunk["text"] for chunk in self.chunks]
            try:
                # Import and download only when retrieval is first needed.
                from sentence_transformers import SentenceTransformer

                self.model = SentenceTransformer(SENTENCE_TRANSFORMER_MODEL)
                self.vectors = self.model.encode(
                    texts,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                ).astype("float32")
                self.retrieval_mode = f"Sentence Transformers: {SENTENCE_TRANSFORMER_MODEL}"
            except Exception as exc:
                # Keep the prototype usable if the model package, cache, or model host is unavailable.
                self.model = None
                self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words="english")
                sparse = self.vectorizer.fit_transform(texts)
                self.vectors = normalize(sparse).toarray().astype("float32")
                self.retrieval_mode = f"TF-IDF fallback (Sentence Transformer unavailable: {type(exc).__name__})"
            if faiss is not None:
                # Inner product over normalized vectors is cosine similarity.
                self.index = faiss.IndexFlatIP(self.vectors.shape[1])
                self.index.add(self.vectors)

    def cited_sections(self, citations: list[str]) -> list[dict]:
        """Return the exact policy chunks named by citation IDs for grounded answer context."""
        wanted = set(citations)
        return [chunk for chunk in self.chunks if f"{chunk['source']}#{chunk['section']}" in wanted]
