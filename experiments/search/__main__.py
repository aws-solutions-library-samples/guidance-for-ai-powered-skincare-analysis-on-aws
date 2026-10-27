"""Run with python -m experiments.search --help."""

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import platform
import random
import re
import time
from pathlib import Path

from .data import fingerprint, load_dataset, prepare_demo, read_jsonl, write_jsonl
from .methods import LocalMethods, NeuralMethods, fuse
from .metrics import evaluate_query, paired_interval, summarize

ROOT = Path(__file__).resolve().parents[2]


def validate_run(records, queries, corpus):
    if set(records) != set(queries):
        raise ValueError("Run must contain exactly one record for every selected query, including empty results")
    for qid, record in records.items():
        for field in ("candidates", "ranking"):
            if not isinstance(record.get(field), list):
                raise ValueError(f"{qid}: {field} must be a list")
            ids = []
            for hit in record[field]:
                pid = hit["product_id"]
                if pid not in corpus or not math.isfinite(hit["score"]):
                    raise ValueError(f"{qid}: unknown product or nonfinite score")
                ids.append(pid)
            if len(ids) != len(set(ids)):
                raise ValueError(f"{qid}: duplicate product in {field}")
        if not {h["product_id"] for h in record["ranking"]} <= {h["product_id"] for h in record["candidates"]}:
            raise ValueError(f"{qid}: ranked products must come from candidates")
        samples = record.get("latency_ms")
        if not isinstance(samples, list) or any(not math.isfinite(s) or s < 0 for s in samples):
            raise ValueError("latency_ms must be a list of finite nonnegative durations, or [] if unmeasured")


def write_report(dataset, split, run_paths, output):
    corpus, queries, qrels, metadata = load_dataset(dataset, split)
    report = {
        "split": split, "dataset": fingerprint(dataset),
        "dataset_metadata": metadata, "methods": {}, "per_query": {},
        "paired_ndcg_at_3_vs_legacy_current": {},
    }
    all_rows = []
    for path in run_paths:
        records = read_jsonl(path)
        validate_run(records, queries, corpus)
        manifest = json.loads(path.with_suffix(".manifest.json").read_text())
        if manifest["dataset"] != fingerprint(dataset) or manifest["split"] != split:
            raise ValueError(f"Run fingerprint/split mismatch: {path}")
        method = manifest["method"]
        if method in report["methods"]:
            raise ValueError(f"Duplicate method: {method}")
        rows = []
        for qid, query in queries.items():
            record = records[qid]
            metrics = evaluate_query(
                query, corpus, qrels[qid], record,
                exhaustive=metadata.get("judgment_scope") == "exhaustive",
            )
            row = {
                "query_id": qid, "method": method, "metrics": metrics,
                "latency_ms": record["latency_ms"],
                "top_3": [{
                    "product_id": hit["product_id"],
                    "name": corpus[hit["product_id"]]["title"],
                    "grade": qrels[qid].get(hit["product_id"]),
                } for hit in record["ranking"][:3]],
            }
            rows.append(row)
        report["methods"][method] = {
            "summary": summarize(rows), "manifest": manifest,
            "by_category": {
                category: summarize([row for row in rows if queries[row["query_id"]]["category"] == category])
                for category in sorted({q["category"] for q in queries.values()})
            },
            "by_slice": {
                tag: summarize([row for row in rows if tag in queries[row["query_id"]].get("tags", [])])
                for tag in sorted({tag for q in queries.values() for tag in q.get("tags", [])})
            },
        }
        report["per_query"][method] = rows
        all_rows.extend(rows)
    baseline = {
        row["query_id"]: row["metrics"]["ndcg_at_3"]
        for row in report["per_query"].get("legacy_current", [])
    }
    for method, rows in report["per_query"].items():
        if method != "legacy_current" and baseline:
            report["paired_ndcg_at_3_vs_legacy_current"][method] = paired_interval(
                baseline, {row["query_id"]: row["metrics"]["ndcg_at_3"] for row in rows}
            )
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    with (output / "per-query.csv").open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=[
            "query_id", "method", *all_rows[0]["metrics"], "top_3",
        ])
        writer.writeheader()
        for row in all_rows:
            writer.writerow({
                "query_id": row["query_id"], "method": row["method"], **row["metrics"],
                "top_3": " | ".join(f'{hit["name"]} (grade {hit["grade"]})' for hit in row["top_3"]),
            })

    def fmt(number):
        return "—" if number is None else f"{number:.3f}"

    lines = [
        "# Search experiment report", "",
        f"Split: **{split}**. Queries: **{len(queries)}**. Evaluation corpus: **{len(corpus)}** products.",
        f"Judgments: {metadata.get('judgment_provenance', 'unspecified')}. "
        f"Human reviewed: **{metadata.get('human_reviewed', False)}**.", "",
        "These results describe the frozen dataset and configured methods. "
        "They do not establish medical suitability or performance at customer scale.", "",
        "| Method | nDCG@3 ↑ | P@3 ↑ | Candidate recall ↑ | Constraint violations ↓ | No-match abstention ↑ | p95 ms ↓ |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for method, result in report["methods"].items():
        summary = result["summary"]
        columns = ("ndcg_at_3", "precision_at_3", "candidate_recall",
                   "constraint_violation_rate", "correct_abstention", "latency_p95_ms")
        lines.append(f"| {method} | " + " | ".join(fmt(summary[key]) for key in columns) + " |")
    lines.extend([
        "", "nDCG uses linear graded gains. nDCG, MRR, and recall exclude queries with no judged positives. "
        "P@3 divides by 3 even if fewer results are returned. Constraint violations are averaged per query. "
        "Correct abstention is scored only for exhaustive no-positive queries; it is undefined for pooled judgments.",
        "", "Local timings include query processing and ranking, after warmup, excluding model/index loading. "
        "They are single-process measurements; no network, queueing, DynamoDB, upstream agent, or explanation generation is included. "
        "Imported runs retain their own measurement scope in the manifest.",
        "", "## Paired nDCG@3 differences", "",
        "95% percentile bootstrap intervals versus legacy_current; queries are the sampling unit. "
        "Intervals on the small, unreviewed seed set are exploratory. No multiple-comparison correction is applied.", "",
    ])
    for method, interval in report["paired_ndcg_at_3_vs_legacy_current"].items():
        if interval:
            lines.append(
                f"- {method}: {interval['mean_delta']:+.3f} "
                f"[{interval['ci95_low']:+.3f}, {interval['ci95_high']:+.3f}], "
                f"{interval['paired_queries']} paired queries."
            )
    lines.extend(["", "## Profile examples", ""])
    for qid, query in queries.items():
        lines.extend([f"### {qid}", "", query["text"], ""])
        for method, rows in report["per_query"].items():
            row = next(row for row in rows if row["query_id"] == qid)
            products = "; ".join(f'{hit["name"]} [grade {hit["grade"]}]' for hit in row["top_3"])
            lines.append(f"- **{method}**: {products or '(abstained)'}. nDCG@3: {fmt(row['metrics']['ndcg_at_3'])}")
        lines.append("")
    (output / "report.md").write_text("\n".join(lines) + "\n")
    return report


def run_experiment(args):
    corpus, queries, _, _ = load_dataset(args.dataset, args.split)
    if len(corpus) > 10000:
        raise ValueError("Local reference runner is capped at 10,000 products. Use an indexed engine and evaluate its exported runs.")
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    local = LocalMethods(corpus)
    local_build_ms = (time.perf_counter() - start) * 1000
    k = args.candidate_k
    methods = {
        "legacy_current": lambda q: (r := local.legacy(q, 3), r),
        "harmonic_filtered": lambda q: (r := local.legacy(q, k, filtered=True), r),
        "ingredient_coverage": lambda q: (r := local.coverage(q, k), r),
        "bm25_filtered": lambda q: (r := local.bm25(q, k), r),
        # This is lexical + structured fusion, explicitly not dense hybrid search.
        "bm25_coverage_rrf": lambda q: (r := fuse([local.bm25(q, k), local.coverage(q, k)], k), r),
    }
    neural_build_ms = None
    if args.embedding_model:
        revisions = [args.embedding_revision]
        if args.reranker_model:
            revisions.append(args.reranker_revision)
        if any(not re.fullmatch(r"[a-f0-9]{40}", revision or "") for revision in revisions):
            raise ValueError("Neural experiments require exact 40-character model commit revisions")
        start = time.perf_counter()
        neural = NeuralMethods(
            corpus, local, args.embedding_model, args.embedding_revision,
            args.reranker_model, args.reranker_revision, args.device,
        )
        neural_build_ms = (time.perf_counter() - start) * 1000
        methods["dense_exact"] = lambda q: (r := neural.dense(q, k), r)
        methods["hybrid_bm25_dense_rrf"] = lambda q: (r := neural.hybrid(q, k), r)
        if args.reranker_model:
            def rerank(query):
                candidates = neural.hybrid(query, k)
                return candidates, neural.rerank(query, candidates[:args.rerank_k])
            methods["hybrid_cross_encoder"] = rerank
    elif args.reranker_model:
        raise ValueError("--reranker-model requires --embedding-model")
    manifests = {
        "dataset": fingerprint(args.dataset), "split": args.split,
        "implementation_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [
                *sorted(Path(__file__).parent.glob("*.py")),
                ROOT / "experiments/search/legacy_repository.py",
            ]
        },
        "candidate_k": k, "rerank_k": args.rerank_k,
        "repetitions": args.repetitions, "warmup": args.warmup, "seed": args.seed,
        "local_index_build_ms": local_build_ms,
        "neural_load_and_document_encoding_ms": neural_build_ms,
        "platform": platform.platform(), "python": platform.python_version(),
        "packages": {dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions()},
        "embedding_model": args.embedding_model, "embedding_revision": args.embedding_revision,
        "reranker_model": args.reranker_model, "reranker_revision": args.reranker_revision,
        "device": args.device,
        "timing_scope": "local warmed sequential query processing; excludes model/index loading, AWS and LLM agents",
        "ranking_scope": "post-profile-planning retrieval/ranking; frozen manually supplied ingredient targets",
    }
    records = {name: {} for name in methods}
    jobs = [(name, qid) for name in methods for qid in queries]
    generator = random.Random(args.seed)
    for iteration in range(args.warmup + args.repetitions):
        generator.shuffle(jobs)
        for name, qid in jobs:
            start = time.perf_counter()
            candidates, ranking = methods[name](queries[qid])
            elapsed = (time.perf_counter() - start) * 1000
            if iteration < args.warmup:
                continue
            record = records[name].setdefault(qid, {
                "_id": qid, "candidates": candidates, "ranking": ranking, "latency_ms": [],
            })
            if [h["product_id"] for h in record["ranking"]] != [h["product_id"] for h in ranking]:
                raise ValueError(f"Non-reproducible ranking for {name}/{qid}; run stochastic trials separately")
            record["latency_ms"].append(elapsed)
    paths = []
    for name, method_records in records.items():
        path = output / f"{name}.jsonl"
        paths.append(path)
        write_jsonl(path, method_records.values())
        path.with_suffix(".manifest.json").write_text(json.dumps({
            **manifests, "method": name,
            "candidate_k": 3 if name == "legacy_current" else k,
        }, indent=2) + "\n")
    write_report(args.dataset, args.split, paths, output)
    print(output / "report.md")


def export_pool(args):
    corpus, queries, _, _ = load_dataset(args.dataset, args.split)
    pools = {qid: set() for qid in queries}
    for path in args.runs:
        records = read_jsonl(path)
        validate_run(records, queries, corpus)
        manifest = json.loads(path.with_suffix(".manifest.json").read_text())
        if manifest["dataset"] != fingerprint(args.dataset) or manifest["split"] != args.split:
            raise ValueError(f"Run fingerprint/split mismatch: {path}")
        for qid, record in records.items():
            pools[qid].update(hit["product_id"] for hit in record["ranking"][:args.depth])
    generator = random.Random(args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", newline="") as target:
        writer = csv.writer(target)
        writer.writerow(["query_id", "profile_query", "constraints", "product_id", "product_name", "product_text", "grade_0_to_3", "reviewer_notes"])
        for qid, query in queries.items():
            ids = sorted(pools[qid])
            generator.shuffle(ids)
            constraints = {key: query[key] for key in ("category", "must_include", "exclude", "max_price", "currency") if key in query}
            for pid in ids:
                product = corpus[pid]
                writer.writerow([qid, query["text"], json.dumps(constraints), pid,
                                 product["title"], json.dumps(product["metadata"]), "", ""])
    print(args.output)


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare-demo", help="Export frozen demo profiles and judgments to BEIR files")
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--catalog", type=Path, default=ROOT / "data/products.csv")
    prepare.add_argument("--cases", type=Path, default=Path(__file__).with_name("demo_cases.json"))
    run = commands.add_parser("run", help="Run local reference methods and write a comparison report")
    evaluate = commands.add_parser("evaluate", help="Compare exported runs from any retrieval engine")
    pool = commands.add_parser("pool", help="Export a shuffled review sheet with method identities hidden")
    for command in (run, evaluate, pool):
        command.add_argument("--dataset", type=Path, required=True)
        command.add_argument("--split", choices=["dev", "test", "all"], default="dev")
        command.add_argument("--output", type=Path, required=True)
    for command in (evaluate, pool):
        command.add_argument("--runs", type=Path, nargs="+", required=True)
    run.add_argument("--candidate-k", type=positive_int, default=50)
    run.add_argument("--rerank-k", type=positive_int, default=50)
    run.add_argument("--repetitions", type=positive_int, default=3)
    run.add_argument("--warmup", type=positive_int, default=1)
    run.add_argument("--seed", type=int, default=17)
    run.add_argument("--embedding-model")
    run.add_argument("--embedding-revision")
    run.add_argument("--reranker-model")
    run.add_argument("--reranker-revision")
    run.add_argument("--device", default="cpu")
    pool.add_argument("--depth", type=positive_int, default=20)
    pool.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    try:
        if args.command == "prepare-demo":
            prepare_demo(args.catalog, args.cases, args.output)
            print(args.output)
        elif args.command == "run":
            run_experiment(args)
        elif args.command == "evaluate":
            write_report(args.dataset, args.split, args.runs, args.output)
            print(args.output / "report.md")
        elif args.command == "pool":
            export_pool(args)
    except (ValueError, FileExistsError, ImportError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
