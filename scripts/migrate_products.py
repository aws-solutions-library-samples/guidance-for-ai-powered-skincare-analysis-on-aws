#!/usr/bin/env python3
"""Migrate product data from CSV to DynamoDB using catalog.yaml schema mapping.

Usage:
    .venv/bin/python3 scripts/migrate_products.py <table_name> [csv_path]
"""

import ast
import csv
import hashlib
import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import boto3
import yaml


def load_catalog_config(project_root: Path) -> dict:
    """Load catalog.yaml and return the raw config dict."""
    catalog_path = project_root / "data" / "catalog.yaml"
    with open(catalog_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def migrate(table_name: str, csv_path: Path | None = None) -> None:
    """Load products from CSV and insert into DynamoDB using catalog schema mapping."""
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent

    catalog = load_catalog_config(project_root)
    schema = catalog.get("schema", {})

    csv_category_field = schema.get("category_field", "product_type")
    csv_name_field = schema.get("name_field", "product_name")
    csv_ingredients_field = schema.get("ingredients_field", "ingredients")
    csv_price_field = schema.get("price_field", "price")
    csv_image_field = schema.get("image_field", "image_url")

    if csv_path is None:
        csv_path = project_root / "data" / "products.csv"

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        available_columns = reader.fieldnames or []
        products = list(reader)

    print(f"CSV columns found: {available_columns}")
    print(f"Schema mapping: category={csv_category_field}, name={csv_name_field}, "
          f"ingredients={csv_ingredients_field}, price={csv_price_field}, "
          f"image={csv_image_field}")

    required_columns = {
        "category_field": csv_category_field,
        "name_field": csv_name_field,
        "ingredients_field": csv_ingredients_field,
    }
    missing_columns = [
        f"  - '{col}' (mapped from schema.{key})"
        for key, col in required_columns.items()
        if col not in available_columns
    ]
    if missing_columns:
        print("\nERROR: Required columns missing from CSV:")
        print("\n".join(missing_columns))
        print(f"\nYour CSV has columns: {available_columns}")
        print("Update data/catalog.yaml schema to match your CSV column names.")
        sys.exit(1)

    optional_columns = {"price_field": csv_price_field, "image_field": csv_image_field}
    missing_optional = [
        f"  - '{col}' (schema.{key}) — will be skipped"
        for key, col in optional_columns.items()
        if col not in available_columns
    ]
    if missing_optional:
        print("\nNote: Optional columns not found in CSV (this is fine):")
        print("\n".join(missing_optional))
        print()

    print(f"Migrating {len(products)} products to {table_name}...")

    success = 0
    with table.batch_writer() as batch:
        for idx, row in enumerate(products, 1):
            try:
                ingredients = []
                raw_ing = row.get(csv_ingredients_field, "")
                if raw_ing:
                    try:
                        ingredients = ast.literal_eval(raw_ing)
                    except (ValueError, SyntaxError):
                        ingredients = [i.strip() for i in raw_ing.split(",") if i.strip()]

                name = row.get(csv_name_field, "").strip()
                category = row.get(csv_category_field, "").strip()
                product_id = hashlib.sha256(
                    f"{category}:{name}".lower().encode()
                ).hexdigest()[:16]

                item = {
                    "product_id": product_id,
                    csv_name_field: name,
                    csv_category_field: category,
                    csv_ingredients_field: ingredients,
                }

                price_raw = row.get(csv_price_field, "")
                if price_raw and price_raw.strip():
                    try:
                        price_str = (
                            price_raw
                            .replace("£", "")
                            .replace("$", "")
                            .replace("€", "")
                            .replace(",", "")
                            .strip()
                        )
                        item[csv_price_field] = Decimal(price_str)
                    except (ValueError, InvalidOperation):
                        pass

                image_raw = row.get(csv_image_field, "")
                if image_raw and image_raw.strip():
                    item[csv_image_field] = image_raw.strip()

                batch.put_item(Item=item)
                success += 1

                if idx % 100 == 0:
                    print(f"  Progress: {idx}/{len(products)}")

            except Exception as e:
                print(f"Row {idx}: {e}")

    print(f"Done — {success}/{len(products)} products migrated")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/migrate_products.py <table_name> [csv_path]")
        sys.exit(1)

    table = sys.argv[1]
    csv_file = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    migrate(table, csv_file)
