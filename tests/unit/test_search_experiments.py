"""Evaluation correctness matters: an incorrect metric can select the wrong system."""

import json
import math

import pytest

from experiments.search.__main__ import validate_run, write_report
from experiments.search.data import (
    fingerprint, load_dataset, prepare_demo, read_jsonl, violations, write_jsonl,
)
from experiments.search.methods import LocalMethods, fuse
from experiments.search.metrics import dcg, evaluate_query, paired_interval


def product(pid, ingredients, price=10, category="Serum", currency="GBP"):
    return {
        "_id": pid, "title": pid, "text": ", ".join(ingredients),
        "metadata": {"category": category, "ingredients": ingredients, "price": price, "currency": currency},
    }


def query(**kwargs):
    return {
        "_id": "q", "text": "serum containing target", "category": "Serum",
        "preferred_ingredients": ["target"], "split": "dev", **kwargs,
    }


def hits(*ids):
    return [{"product_id": pid, "score": 1.0} for pid in ids]


def record(ranking, candidates=None):
    return {"_id": "q", "ranking": hits(*ranking), "candidates": hits(*(candidates or ranking)), "latency_ms": []}


def test_linear_ndcg_matches_hand_calculation():
    corpus = {pid: product(pid, ["target"]) for pid in ["a", "b", "c"]}
    result = evaluate_query(query(), corpus, {"a": 3, "b": 1, "c": 0}, record(["b", "a", "c"]), True)
    expected = (1 + 3 / math.log2(3)) / (3 + 1 / math.log2(3))
    assert result["ndcg_at_3"] == pytest.approx(expected)
    assert dcg([3, 1]) == pytest.approx(3 + 1 / math.log2(3))
    assert result["precision_at_3"] == pytest.approx(2 / 3)


def test_candidate_recall_is_independent_of_final_ranking():
    corpus = {pid: product(pid, ["target"]) for pid in ["a", "b", "c"]}
    result = evaluate_query(query(), corpus, {"a": 3, "b": 2, "c": 0}, record(["c"], ["a", "b", "c"]), True)
    assert result["candidate_recall"] == 1
    assert result["ndcg_at_3"] == 0


def test_empty_results_cannot_win_answerable_queries():
    result = evaluate_query(query(), {"a": product("a", [])}, {"a": 3}, record([]), True)
    assert result["ndcg_at_3"] == 0
    assert result["candidate_recall"] == 0
    assert result["empty_on_answerable"] == 1
    assert result["correct_abstention"] is None


def test_no_match_abstention_requires_exhaustive_judgments():
    corpus = {"a": product("a", [])}
    no_match = evaluate_query(query(), corpus, {"a": 0}, record([]), True)
    assert no_match["ndcg_at_3"] is None
    assert no_match["correct_abstention"] == 1
    assert evaluate_query(query(), corpus, {"a": 0}, record([]), False)["correct_abstention"] is None
    assert evaluate_query(query(), corpus, {"a": 0}, record(["a"]), True)["correct_abstention"] == 0


def test_unjudged_results_are_visible_and_do_not_disappear_from_ranking():
    corpus = {pid: product(pid, []) for pid in ["a", "b"]}
    result = evaluate_query(query(), corpus, {"a": 3}, record(["b", "a"]), False)
    assert result["unjudged_fraction"] == 0.5
    assert result["ndcg_at_3"] == pytest.approx(1 / math.log2(3))


def test_constraints_use_exact_canonical_ingredients_and_fail_closed_on_price():
    q = query(must_include=[" TARGET "], exclude=["retinol"], max_price=15, currency="GBP")
    assert violations(product("a", ["target"], price=0), q) == []
    assert "excluded_ingredient" in violations(product("a", ["target", "RETINOL"]), q)
    assert "missing_required_ingredient" in violations(product("a", ["target derivative"]), q)
    assert "price_or_currency" in violations(product("a", ["target"], price=None), q)
    assert "price_or_currency" in violations(product("a", ["target"], currency="USD"), q)
    assert "category" in violations(product("a", ["target"], category="Toner"), q)


@pytest.mark.parametrize("mutate", [
    lambda r: r.update({"ranking": hits("missing")}),
    lambda r: r.update({"ranking": hits("a", "a")}),
    lambda r: r.update({"ranking": [{"product_id": "a", "score": float("nan")}]}),
    lambda r: r.update({"candidates": [], "ranking": hits("a")}),
    lambda r: r.update({"latency_ms": [-1]}),
])
def test_invalid_runs_are_rejected(mutate):
    r = record(["a"])
    mutate(r)
    with pytest.raises(ValueError):
        validate_run({"q": r}, {"q": query()}, {"a": product("a", [])})


def test_missing_queries_are_not_silently_excluded():
    with pytest.raises(ValueError, match="every selected query"):
        validate_run({}, {"q": query()}, {"a": product("a", [])})


def test_coverage_canonicalizes_duplicates_without_matching_derivatives():
    corpus = {"a": product("a", ["target"]), "b": product("b", ["target derivative"])}
    results = LocalMethods(corpus).coverage(query(preferred_ingredients=["target", " TARGET "]), 10)
    assert results == [{"product_id": "a", "score": 1.0}]


def test_bm25_applies_constraints_before_top_k():
    corpus = {
        "a": product("a", ["target", "target", "target"], price=100),
        "b": product("b", ["target"], price=10),
    }
    results = LocalMethods(corpus).bm25(query(max_price=15, currency="GBP"), 1)
    assert [r["product_id"] for r in results] == ["b"]


def test_legacy_preserves_zero_fillers_and_filtered_ablation_removes_them():
    corpus = {"a": product("a", ["target"]), "b": product("b", ["different"])}
    methods = LocalMethods(corpus)
    assert len(methods.legacy(query(), 3)) == 2
    assert methods.legacy(query(), 3)[1]["score"] == 0
    assert len(methods.legacy(query(), 3, filtered=True)) == 1


def test_rrf_combines_ranks_not_score_magnitudes():
    first = [{"product_id": "a", "score": 1000}, {"product_id": "b", "score": 1}]
    second = [{"product_id": "b", "score": 0.9}]
    assert fuse([first, second], 2)[0]["product_id"] == "b"


def test_paired_bootstrap_is_reproducible_and_excludes_unscorable_queries():
    result = paired_interval({"a": 0.5, "b": None}, {"a": 0.75, "b": None}, samples=100)
    assert result["mean_delta"] == result["ci95_low"] == result["ci95_high"] == 0.25
    assert result["paired_queries"] == 1


@pytest.fixture
def demo_dataset(tmp_path):
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    output = tmp_path / "dataset"
    prepare_demo(root / "data/products.csv", root / "experiments/search/demo_cases.json", output)
    return output


def test_demo_exports_valid_disjoint_splits_and_exhaustive_judgments(demo_dataset):
    corpus, dev, qrels, metadata = load_dataset(demo_dataset, "dev")
    _, test, _, _ = load_dataset(demo_dataset, "test")
    assert len(corpus) == 48
    assert len(dev) == len(test) == 12
    assert not dev.keys() & test.keys()
    assert all(len(judgments) == len(corpus) for judgments in qrels.values())
    assert metadata["human_reviewed"] is False
    assert any(not any(j.values()) for j in qrels.values())


def test_report_rejects_wrong_snapshot_and_supports_external_runs(demo_dataset, tmp_path):
    corpus, queries, _, _ = load_dataset(demo_dataset, "dev")
    path = tmp_path / "external.jsonl"
    write_jsonl(path, [
        {"_id": qid, "ranking": [], "candidates": [], "latency_ms": []} for qid in queries
    ])
    manifest = {"method": "external", "dataset": fingerprint(demo_dataset), "split": "dev"}
    path.with_suffix(".manifest.json").write_text(json.dumps(manifest))
    report = write_report(demo_dataset, "dev", [path], tmp_path / "report")
    assert report["methods"]["external"]["summary"]["latency_p95_ms"] is None
    assert report["methods"]["external"]["summary"]["ndcg_at_3"] == 0
    manifest["dataset"]["corpus.jsonl"] = "wrong"
    path.with_suffix(".manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="fingerprint"):
        write_report(demo_dataset, "dev", [path], tmp_path / "bad-report")


def test_duplicate_dataset_ids_are_rejected(tmp_path):
    path = tmp_path / "duplicates.jsonl"
    write_jsonl(path, [{"_id": "a"}, {"_id": "a"}])
    with pytest.raises(ValueError, match="duplicate"):
        read_jsonl(path)
