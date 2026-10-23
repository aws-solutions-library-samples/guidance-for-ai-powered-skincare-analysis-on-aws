"""Explicit metric definitions and paired query bootstrap intervals."""

import math
import random
import statistics

from .data import violations


def percentile(values: list[float], probability: float):
    if not values:
        return None
    ordered = sorted(values)
    offset = (len(ordered) - 1) * probability
    lower = int(offset)
    return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (offset - lower)


def dcg(grades: list[int]) -> float:
    # Linear gain, matching trec_eval ndcg. Explicitly not the 2**grade-1 variant.
    return sum(grade / math.log2(rank + 2) for rank, grade in enumerate(grades))


def evaluate_query(query, corpus, judgments, run, exhaustive: bool):
    hits, candidates = run["ranking"], run["candidates"]
    top = [hit["product_id"] for hit in hits[:3]]
    relevant = {pid for pid, grade in judgments.items() if grade > 0}
    ideal = dcg(sorted(judgments.values(), reverse=True)[:3])
    returned_violations = sum(bool(violations(corpus[pid], query)) for pid in top)
    # Unjudged results get zero gain, but remain visibly unjudged in the report.
    return {
        "ndcg_at_3": dcg([judgments.get(pid, 0) for pid in top]) / ideal if ideal else None,
        "precision_at_3": sum(pid in relevant for pid in top) / 3,
        "mrr_at_10": next(
            (1 / rank for rank, hit in enumerate(hits[:10], 1) if hit["product_id"] in relevant),
            0.0,
        ) if relevant else None,
        "candidate_recall": len(relevant & {hit["product_id"] for hit in candidates}) / len(relevant) if relevant else None,
        "constraint_violation_rate": returned_violations / len(top) if top else 0.0,
        "query_has_constraint_violation": float(returned_violations > 0),
        "unjudged_fraction": sum(pid not in judgments for pid in top) / len(top) if top else 0.0,
        "correct_abstention": float(not top) if not relevant and exhaustive else None,
        "empty_on_answerable": float(not top) if relevant else None,
        "returned_at_3": len(top),
        "candidate_count": len(candidates),
    }


def summarize(rows: list[dict]) -> dict:
    result = {"query_count": len(rows)}
    if rows:
        for metric in rows[0]["metrics"]:
            values = [row["metrics"][metric] for row in rows if row["metrics"][metric] is not None]
            result[metric] = statistics.mean(values) if values else None
    latencies = [sample for row in rows for sample in row["latency_ms"]]
    for quantile in (0.5, 0.95, 0.99):
        result[f"latency_p{int(quantile * 100)}_ms"] = percentile(latencies, quantile)
    result["latency_sample_count"] = len(latencies)
    return result


def paired_interval(baseline: dict, candidate: dict, samples: int = 2000, seed: int = 17):
    differences = [
        candidate[key] - value for key, value in baseline.items()
        if value is not None and candidate.get(key) is not None
    ]
    if not differences:
        return None
    generator = random.Random(seed)
    means = [
        statistics.mean(generator.choices(differences, k=len(differences))) for _ in range(samples)
    ]
    return {
        "mean_delta": statistics.mean(differences),
        "ci95_low": percentile(means, 0.025),
        "ci95_high": percentile(means, 0.975),
        "paired_queries": len(differences),
        "bootstrap_samples": samples,
        "seed": seed,
    }
