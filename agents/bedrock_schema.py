"""Adapt tool schemas to Bedrock's supported strict JSON Schema subset.

Pydantic and tool code remain responsible for value and business constraints.
https://docs.aws.amazon.com/bedrock/latest/userguide/structured-output.html
"""

from copy import deepcopy


def strict_tool_schema(schema: dict) -> dict:
    """Copy a schema, retaining unsupported bounds as descriptive guidance."""
    result = deepcopy(schema)
    _adapt(result)
    return result


def _adapt(schema: dict) -> None:
    bounds = {}
    for key in (
        "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
        "minLength", "maxLength", "maxItems",
    ):
        if key in schema:
            bounds[key] = schema.pop(key)
    if schema.get("minItems", 0) > 1:
        bounds["minItems"] = schema.pop("minItems")
    if bounds:
        guidance = ", ".join(f"{key}={value}" for key, value in bounds.items())
        schema["description"] = (
            f"{schema.get('description', '')} Application validation requires {guidance}."
        ).strip()

    schema_type = schema.get("type")
    if schema_type == "object" or isinstance(schema_type, list) and "object" in schema_type:
        if schema.get("additionalProperties", False) is not False:
            raise ValueError("Strict tool schemas cannot contain open-ended object properties")
        schema["additionalProperties"] = False

    # Walk schema locations, not arbitrary values or property names.
    for key in ("properties", "$defs", "definitions"):
        for child in schema.get(key, {}).values():
            _adapt(child)
    if isinstance(schema.get("items"), dict):
        _adapt(schema["items"])
    for key in ("anyOf", "allOf", "oneOf", "prefixItems"):
        for child in schema.get(key, []):
            _adapt(child)
