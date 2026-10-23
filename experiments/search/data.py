"""BEIR-compatible data with additional product and profile metadata."""

import ast
import csv
import hashlib
import json
import math
from pathlib import Path


def read_jsonl(path: Path) -> dict[str, dict]:
    records = {}
    with path.open() as source:
        for line in source:
            record = json.loads(line)
            key = record["_id"]
            if not isinstance(key, str) or not key or key in records:
                raise ValueError(f"Invalid or duplicate ID in {path}: {key!r}")
            records[key] = record
    return records


def write_jsonl(path: Path, records) -> None:
    with path.open("w") as target:
        for record in records:
            target.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")


def canonical(value: str) -> str:
    """Normalize spelling mechanics; do not equate different chemicals."""
    return " ".join(value.casefold().split())


def violations(product: dict, query: dict) -> list[str]:
    metadata = product["metadata"]
    ingredients = {canonical(i) for i in metadata["ingredients"]}
    reasons = []
    if metadata["category"] != query["category"]:
        reasons.append("category")
    if any(canonical(i) not in ingredients for i in query.get("must_include", [])):
        reasons.append("missing_required_ingredient")
    if any(canonical(i) in ingredients for i in query.get("exclude", [])):
        reasons.append("excluded_ingredient")
    if query.get("max_price") is not None:
        price = metadata.get("price")
        if (
            price is None
            or metadata.get("currency") != query.get("currency")
            or price > query["max_price"]
        ):
            reasons.append("price_or_currency")
    return reasons


def document_text(product: dict) -> str:
    return f'{product["title"]}. {product["text"]}'


def prepare_demo(catalog_path: Path, cases_path: Path, output: Path) -> None:
    """Export the local CSV and frozen seed cases without deriving judgments from rankers."""
    output.mkdir(parents=True, exist_ok=False)
    corpus = {}
    names = {}
    with catalog_path.open(newline="") as source:
        for row in csv.DictReader(source):
            category, name = row["product_type"], row["product_name"]
            product_id = hashlib.sha256(f"{category}:{name}".lower().encode()).hexdigest()[:16]
            if product_id in corpus or name in names:
                raise ValueError(f"Duplicate product: {name}")
            ingredients = ast.literal_eval(row["ingredients"])
            corpus[product_id] = {
                "_id": product_id,
                "title": name,
                "text": f"Category: {category}. Ingredients: {', '.join(ingredients)}.",
                "metadata": {
                    "category": category, "ingredients": ingredients,
                    "price": float(row["price"]), "currency": "GBP",
                },
            }
            names[name] = product_id
    bundle = json.loads(cases_path.read_text())
    queries = []
    qrels = []
    for case in bundle["cases"]:
        case = dict(case)
        grades = case.pop("grades")
        query = {"_id": case.pop("id"), **case}
        queries.append(query)
        unknown = set(grades) - names.keys()
        if unknown:
            raise ValueError(f"Unknown judged products: {unknown}")
        for product_id, product in corpus.items():
            grade = grades.get(product["title"], 0)
            if grade > 0 and violations(product, query):
                raise ValueError(f"Positive judgment violates constraints: {query['_id']}, {product_id}")
            qrels.append((query["_id"], product_id, grade))
    write_jsonl(output / "corpus.jsonl", corpus.values())
    write_jsonl(output / "queries.jsonl", queries)
    with (output / "qrels.tsv").open("w", newline="") as target:
        writer = csv.writer(target, delimiter="\t")
        writer.writerow(["query-id", "corpus-id", "score"])
        writer.writerows(qrels)
    (output / "metadata.json").write_text(json.dumps({
        "judgment_provenance": bundle["judgment_provenance"],
        "human_reviewed": False,
        "judgment_scope": "exhaustive",
        "catalog_sha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
        "cases_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        "limitations": bundle["limitations"],
    }, indent=2) + "\n")


def load_dataset(path: Path, split: str):
    corpus = read_jsonl(path / "corpus.jsonl")
    all_queries = read_jsonl(path / "queries.jsonl")
    queries = {key: q for key, q in all_queries.items() if split == "all" or q["split"] == split}
    if not corpus or not queries:
        raise ValueError("Dataset must contain products and queries for the requested split")
    for product in corpus.values():
        metadata = product["metadata"]
        if not isinstance(metadata["ingredients"], list) or any(
            not isinstance(i, str) or not i.strip() for i in metadata["ingredients"]
        ):
            raise ValueError("Product ingredients must be a list of nonempty strings")
        price = metadata.get("price")
        if price is not None and (not math.isfinite(price) or price < 0):
            raise ValueError("Product prices must be finite and nonnegative")
    for query in queries.values():
        if not query.get("text") or not query.get("category"):
            raise ValueError("Queries require text and category")
        for field in ("preferred_ingredients", "must_include", "exclude"):
            if not isinstance(query.get(field, []), list) or any(
                not isinstance(i, str) or not i.strip() for i in query.get(field, [])
            ):
                raise ValueError(f"Invalid query {field}")
        price = query.get("max_price")
        if price is not None and (
            not math.isfinite(price) or price < 0 or not query.get("currency")
        ):
            raise ValueError("Price constraints require a finite nonnegative price and currency")
    qrels = {key: {} for key in queries}
    with (path / "qrels.tsv").open(newline="") as source:
        reader = csv.DictReader(source, delimiter="\t")
        if reader.fieldnames != ["query-id", "corpus-id", "score"]:
            raise ValueError("qrels.tsv requires query-id, corpus-id, score columns")
        for row in reader:
            qid, pid, grade = row["query-id"], row["corpus-id"], int(row["score"])
            if qid not in all_queries or pid not in corpus or grade not in range(4):
                raise ValueError(f"Invalid judgment: {row}")
            if qid in queries:
                if pid in qrels[qid]:
                    raise ValueError(f"Duplicate judgment: {qid}, {pid}")
                if grade > 0 and violations(corpus[pid], queries[qid]):
                    raise ValueError(f"Positive judgment violates hard constraints: {qid}, {pid}")
                qrels[qid][pid] = grade
    if any(not judgments for judgments in qrels.values()):
        raise ValueError("Every selected query needs judgments; unjudged queries cannot be scored")
    metadata = json.loads((path / "metadata.json").read_text())
    if metadata.get("judgment_scope") == "exhaustive":
        if any(len(judgments) != len(corpus) for judgments in qrels.values()):
            raise ValueError("Exhaustive judgments must cover every query-product pair")
    return corpus, queries, qrels, metadata


def fingerprint(path: Path) -> dict[str, str]:
    return {
        name: hashlib.sha256((path / name).read_bytes()).hexdigest()
        for name in ("corpus.jsonl", "queries.jsonl", "qrels.tsv", "metadata.json")
    }
