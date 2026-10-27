#!/usr/bin/env python3
"""Publish explicit supplier facts through canonical+outbox transactions.

Bundled CSV mode is a fictional fixture with explicit GB/GBP facts. Real feeds
use JSONL and must supply stable product_id, source_revision, category_id,
source_updated_at, source_provenance, active, is_deleted, and raw_ingredients.
Completeness, stock, market, and price are never inferred for real feeds.
"""

import argparse
import ast
import csv
import json
import sys
import time
from collections import Counter
from decimal import Decimal
from pathlib import Path

import boto3
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.search.clients import dynamodb_resource
from agents.search.contracts import SearchConfiguration
from agents.search.normalization import IngredientRegistry, normalize_product
from agents.search.publication import CatalogPublisher, ControlStore, shard_key, source_watermarks, source_is_healthy


def source_rows(path: Path, *, demo: bool):
    if not demo:
        with path.open() as stream:
            for line in stream:
                if line.strip():
                    yield json.loads(line)
        return
    schema = yaml.safe_load((ROOT / "data/catalog.yaml").read_text())["schema"]
    with path.open() as stream:
        for row in csv.DictReader(stream):
            price = Decimal(row[schema["price_field"]]) * 100
            if price != price.to_integral_value():
                raise ValueError("Price has fractional minor units")
            yield {
                "product_id": row["product_id"], "source_revision": int(row["source_revision"]),
                "category_id": row[schema["category_field"]], "name": row[schema["name_field"]],
                "raw_ingredients": ast.literal_eval(row[schema["ingredients_field"]]),
                "price_minor": int(price), "currency": "GBP", "market_ids": ["GB"],
                "image_path": row.get(schema["image_field"], ""),
                "active": True, "is_deleted": False, "ingredient_list_complete": True,
                "source_updated_at": "2026-10-26T00:00:00Z",
                "source_provenance": "Bundled fictional catalog, revision 1; not customer inventory",
            }


def wait_until_ready(control, *, timeout=300):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        config, progress, source = control.get("CONFIG"), control.get("PROJECTION"), control.get("SOURCE")
        ready = control.get(f"READINESS#{config['index_generation']}")
        generation = config["index_generation"]
        caught_up = all(
            control.get(shard_key("PROJECTION", shard))["generations"][generation]["sequence"] == watermark
            for shard, watermark in source_watermarks(control).items()
        )
        if (
            caught_up and source_is_healthy(source)
            and ready and ready["healthy"] is True and ready["source_healthy"] is True
            and ready["configuration_id"] == config["configuration_id"]
            and ready["oldest_pending_at"] is None and 0 <= time.time() - ready["checked_at"] <= 60
        ):
            return
        time.sleep(5)
    raise RuntimeError("Index publication did not become ready within five minutes")


def migrate(args):
    config = SearchConfiguration.model_validate_json(args.config.read_text())
    registry = IngredientRegistry(json.loads(args.registry.read_text()), config.taxonomy_version)
    client = dynamodb_resource(boto3.Session(), background=True).client
    control = ControlStore(client, args.metadata_table, config.catalog_id)
    publisher = CatalogPublisher(client, products_table=args.products_table, outbox_table=args.outbox_table, control=control)
    if args.admin_function:
        admin_client = boto3.Session().client("lambda")
        response = admin_client.invoke(
            FunctionName=args.admin_function, Payload=json.dumps({"action": "initialize"}).encode(),
        )
        if response.get("FunctionError"):
            raise RuntimeError("Catalog initialization failed; inspect the admin function logs")
        response["Payload"].read()
    source = control.get("SOURCE")
    populated = any(source_watermarks(control).values())
    if args.demo_if_empty and populated and source_is_healthy(source):
        print("Canonical catalog is already initialized; preserving its products.")
        if args.wait_ready:
            wait_until_ready(control)
        return
    if args.demo_if_empty:
        previous = control.get("DEMO_IMPORT")
        if populated and previous != {"status": "in_progress"}:
            raise ValueError("Existing catalog is unhealthy; replay its supplier feed instead of importing the demo")
        control.put("DEMO_IMPORT", {"status": "in_progress"})
    publisher.set_source_health(False, mode=args.feed_mode)
    outcomes = Counter()
    try:
        for values in source_rows(args.source, demo=args.demo_if_empty):
            product = normalize_product(values, registry, config)
            outcomes[publisher.publish(product)] += 1
    except Exception:
        # Keep source health false on incomplete imports; replay the same source
        # after repairing it. Stable revisions make that replay idempotent.
        raise
    publisher.set_source_health(True, mode=args.feed_mode)
    if args.demo_if_empty:
        control.put("DEMO_IMPORT", {"status": "complete"})
    if args.wait_ready:
        wait_until_ready(control)
    # Maintenance owns replacement summaries from a fixed index snapshot.
    # Import-local counts must not overwrite a newer, generation-bound snapshot.
    print(json.dumps({"publication": dict(outcomes)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("products_table")
    parser.add_argument("--metadata-table", required=True)
    parser.add_argument("--outbox-table", required=True)
    parser.add_argument("--config", type=Path, default=ROOT / "data/search-config.json")
    parser.add_argument("--registry", type=Path, default=ROOT / "data/ingredient-registry.json")
    parser.add_argument("--source", type=Path, default=ROOT / "data/products.csv")
    parser.add_argument("--admin-function")
    parser.add_argument("--demo-if-empty", action="store_true")
    parser.add_argument("--wait-ready", action="store_true")
    parser.add_argument("--feed-mode", choices=("snapshot", "live"), default="snapshot",
                        help="Live feeds must refresh source health at least every 60 seconds after import")
    migrate(parser.parse_args())
