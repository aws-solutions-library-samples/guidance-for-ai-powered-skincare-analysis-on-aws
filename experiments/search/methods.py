"""Local reference implementations. Production engines export the same run format."""

import heapq
import math
import re
from collections import Counter, defaultdict

from .data import canonical, document_text, violations


def tokenize(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.casefold())


def ranked(scores: dict, limit: int) -> list[dict]:
    return [
        {"product_id": pid, "score": float(score)}
        for pid, score in heapq.nsmallest(limit, scores.items(), key=lambda pair: (-pair[1], pair[0]))
    ]


def fuse(rankings: list[list[dict]], limit: int, constant: int = 60) -> list[dict]:
    scores = defaultdict(float)
    for ranking in rankings:
        for rank, hit in enumerate(ranking, 1):
            scores[hit["product_id"]] += 1 / (constant + rank)
    return ranked(scores, limit)


class LocalMethods:
    def __init__(self, corpus: dict):
        self.corpus = corpus
        self.categories = defaultdict(list)
        self.ingredients = {}
        self.postings = defaultdict(dict)
        self.lengths = {}
        self.ingredient_postings = defaultdict(set)
        for pid, product in corpus.items():
            category = product["metadata"]["category"]
            self.categories[category].append(pid)
            self.ingredients[pid] = {canonical(i) for i in product["metadata"]["ingredients"]}
            terms = Counter(tokenize(document_text(product)))
            self.lengths[pid] = sum(terms.values())
            for term, frequency in terms.items():
                self.postings[term][pid] = frequency
            for ingredient in self.ingredients[pid]:
                self.ingredient_postings[(category, ingredient)].add(pid)
        self.average_length = sum(self.lengths.values()) / max(1, len(corpus))

    def eligible(self, query: dict) -> set[str]:
        return {
            pid for pid in self.categories.get(query["category"], [])
            if not violations(self.corpus[pid], query)
        }

    def legacy(self, query: dict, limit: int, filtered: bool = False) -> list[dict]:
        # Invoke the real scorer; preserve CSV input order for production's stable-sort ties.
        from experiments.search.legacy_repository import _compute_position_scores

        ids = self.categories.get(query["category"], [])
        if filtered:
            ids = [pid for pid in ids if not violations(self.corpus[pid], query)]
        required = list(dict.fromkeys(i.strip() for i in query.get("preferred_ingredients", [])))
        ingredients = [
            [i.lower().strip() for i in self.corpus[pid]["metadata"]["ingredients"]]
            for pid in ids
        ]
        scores = _compute_position_scores(ingredients, [i.lower() for i in required])
        results = [
            {"product_id": pid, "score": float(score)}
            for pid, score in zip(ids, scores)
            if not filtered or score > 0
        ]
        results.sort(key=lambda result: -result["score"])
        return results[:limit]

    def coverage(self, query: dict, limit: int) -> list[dict]:
        desired = {canonical(i) for i in query.get("preferred_ingredients", [])}
        if not desired:
            return []
        ids = set().union(*(
            self.ingredient_postings[(query["category"], ingredient)] for ingredient in desired
        ))
        scores = {
            pid: len(desired & self.ingredients[pid]) / len(desired)
            for pid in ids if not violations(self.corpus[pid], query)
        }
        return ranked(scores, limit)

    def bm25(self, query: dict, limit: int) -> list[dict]:
        # Reference BM25: k1=1.2, b=0.75, positive Robertson/Lucene-style IDF.
        # Statistics are global. Exact structured constraints are applied before top-k.
        text = query["text"] + " " + " ".join(query.get("preferred_ingredients", []))
        scores = defaultdict(float)
        for term in set(tokenize(text)):
            postings = self.postings.get(term, {})
            idf = math.log(1 + (len(self.corpus) - len(postings) + 0.5) / (len(postings) + 0.5))
            for pid, tf in postings.items():
                if violations(self.corpus[pid], query):
                    continue
                denominator = tf + 1.2 * (0.25 + 0.75 * self.lengths[pid] / self.average_length)
                scores[pid] += idf * tf * 2.2 / denominator
        return ranked(scores, limit)


class NeuralMethods:
    """Optional exact dense reference plus hybrid/reranking; never a scale benchmark."""

    def __init__(self, corpus, local, embedding_model, embedding_revision,
                 reranker_model=None, reranker_revision=None, device="cpu"):
        import numpy as np
        from sentence_transformers import CrossEncoder, SentenceTransformer

        self.np = np
        self.corpus, self.local = corpus, local
        self.ids = list(corpus)
        self.embedding = SentenceTransformer(
            embedding_model, revision=embedding_revision, device=device,
            trust_remote_code=False,
        )
        self.vectors = self.embedding.encode_document(
            [document_text(corpus[pid]) for pid in self.ids],
            normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False,
        )
        self.reranker = CrossEncoder(
            reranker_model, revision=reranker_revision, device=device,
            trust_remote_code=False,
        ) if reranker_model else None

    def dense(self, query: dict, limit: int) -> list[dict]:
        query_text = query["text"] + " Preferred ingredients: " + ", ".join(query.get("preferred_ingredients", []))
        vector = self.embedding.encode_query(
            query_text, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False,
        )
        similarities = self.vectors @ vector
        scores = {
            pid: float(similarities[index]) for index, pid in enumerate(self.ids)
            if not violations(self.corpus[pid], query)
        }
        return ranked(scores, limit)

    def hybrid(self, query: dict, limit: int) -> list[dict]:
        return fuse([self.local.bm25(query, limit), self.dense(query, limit)], limit)

    def rerank(self, query: dict, candidates: list[dict]) -> list[dict]:
        if not candidates:
            return []
        query_text = query["text"] + " Preferred ingredients: " + ", ".join(query.get("preferred_ingredients", []))
        scores = self.reranker.predict([
            (query_text, document_text(self.corpus[hit["product_id"]])) for hit in candidates
        ], show_progress_bar=False)
        return ranked({
            hit["product_id"]: float(score) for hit, score in zip(candidates, scores)
        }, len(candidates))
