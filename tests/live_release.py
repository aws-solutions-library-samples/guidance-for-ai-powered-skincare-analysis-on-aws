"""Explicit AWS release checks, excluded from default pytest discovery.

See README.md and --help. Creates only a fresh test user/client and that
user's limit records; never deploys infrastructure or uses existing identities.
"""

import argparse
import base64
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import time
from urllib.parse import urlsplit
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
import requests

from tests.live_sse import extract_routine, iter_events, validate_events, validate_timings


class CheckFailure(Exception):
    """Only locally authored, non-sensitive descriptions belong in this error."""


def require(condition, message):
    if not condition:
        raise CheckFailure(message)


def validate_target(outputs, expected_account, caller_account):
    require(re.fullmatch(r"\d{12}", expected_account), "Expected account must have 12 digits")
    require(expected_account == caller_account == outputs["deployment_account_id"], "Account mismatch")
    require(outputs["deployment_environment"] == "test", "Only the test environment is allowed")
    arn = outputs["agentcore_runtime_arn"].split(":")
    require(len(arn) >= 6 and arn[4] == expected_account and arn[3] == outputs["aws_region"],
            "Runtime account or region mismatch")
    for key in ("app_url", "api_url"):
        parsed = urlsplit(outputs[key])
        require(parsed.scheme == "https" and parsed.hostname and not parsed.username
                and not parsed.password and not parsed.query and not parsed.fragment,
                "Expected an HTTPS deployment URL")


def post_case(url, token, payload, status, code=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with requests.post(f"{url.rstrip('/')}/analyze", headers=headers, json=payload,
                       timeout=(10, 30), allow_redirects=False) as response:
        require(response.status_code == status, f"Expected HTTP {status}; received {response.status_code}")
        if code:
            require(response.json().get("code") == code, f"Expected public code {code}")
        if status == 429:
            require(response.headers.get("Retry-After", "").isdigit(), "Missing retry delay")


def lookup_case(url, token, payload, status=200, code=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with requests.post(
        f"{url.rstrip('/')}/ingredients/lookup", headers=headers, json=payload,
        timeout=(10, 30), allow_redirects=False,
    ) as response:
        require(response.status_code == status,
                f"Ingredient lookup expected HTTP {status}; received {response.status_code}")
        if code:
            require(response.json().get("code") == code, f"Expected public code {code}")
        return response.json()


def runtime_rejects_corrupt_image(url, token, payload):
    """Exercise the container and SSE transport without starting model work."""
    with requests.post(
        f"{url.rstrip('/')}/analyze",
        headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
        json=payload, stream=True, timeout=(10, 65), allow_redirects=False,
    ) as response:
        require(response.status_code == 200, "Runtime validation did not return HTTP 200")
        require(response.headers.get("Content-Type", "").startswith("text/event-stream"),
                "Runtime validation did not return SSE")
        events = list(iter_events(response))
    require(len(events) == 1 and events[0].get("type") == "error"
            and events[0].get("code") == "INVALID_INPUT",
            "Corrupt image did not stop at runtime input validation")


@contextmanager
def seeded_item(table, item, run_id):
    """Never replace existing state; delete only the record created by this run."""
    marked = {**item, "validation_run": run_id}
    table.put_item(Item=marked, ConditionExpression="attribute_not_exists(pk)")
    try:
        yield
    finally:
        table.delete_item(
            Key={"pk": marked["pk"]},
            ConditionExpression="validation_run = :run",
            ExpressionAttributeValues={":run": run_id},
        )


def direct_runtime_denied(client, runtime_arn):
    # Invalid application input ensures an accidentally permitted call cannot
    # start the model workflow. SDK retries are disabled by the caller.
    try:
        response = client.invoke_agent_runtime(
            agentRuntimeArn=runtime_arn, qualifier="DEFAULT",
            runtimeSessionId=str(uuid.uuid4()), contentType="application/json",
            accept="text/event-stream", payload=b'{"job_id":"release-denial","images":[]}',
        )
    except ClientError as exc:
        require(exc.response["Error"]["Code"] == "AccessDeniedException",
                "Direct invocation failed for a reason other than access denial")
        return
    body = response.get("response")
    if body is not None:
        body.close()
    raise CheckFailure("Direct runtime invocation was permitted")


def run(args, report):
    raw = json.loads(args.outputs.read_text())
    outputs = {key: entry["value"] for key, entry in raw.items()}
    session = boto3.Session(region_name=outputs["aws_region"])
    config = Config(connect_timeout=10, read_timeout=30, retries={"total_max_attempts": 1})

    def client(service):
        return session.client(service, config=config)

    def check(name, action):
        row = {"name": name, "status": "RUNNING"}
        report["checks"].append(row)
        try:
            value = action()
        except Exception as exc:
            row.update(status="FAIL", reason=str(exc) if isinstance(exc, CheckFailure) else type(exc).__name__)
            raise
        row["status"] = "PASS"
        return value

    caller = client("sts").get_caller_identity()
    check("target_account_and_environment",
          lambda: validate_target(outputs, args.expected_account, caller["Account"]))
    report["agent_source_hash"] = outputs["agent_source_hash"]
    cf = client("cloudfront").get_distribution(Id=outputs["cloudfront_distribution_id"])["Distribution"]
    check("cloudfront_ready", lambda: require(cf["Status"] == "Deployed", "CloudFront is not deployed"))
    allowed_hosts = [cf["DomainName"], *cf["DistributionConfig"].get("Aliases", {}).get("Items", [])]
    require(urlsplit(outputs["app_url"]).hostname in allowed_hosts, "App URL does not belong to this distribution")
    runtime = client("bedrock-agentcore-control").get_agent_runtime(agentRuntimeId=outputs["agentcore_runtime_id"])
    check("runtime_ready", lambda: require(runtime["status"] == "READY", "Runtime is not ready"))
    report["runtime_version"] = runtime["agentRuntimeVersion"]
    image_uri = runtime["agentRuntimeArtifact"]["containerConfiguration"]["containerUri"]
    require(image_uri == f"{outputs['agentcore_ecr_repo_uri']}:{outputs['agent_source_hash']}",
            "Runtime image differs from the image selected by Terraform")
    function = client("lambda").get_function_configuration(FunctionName=outputs["api_proxy_function_name"])
    settings = function["Environment"]["Variables"]
    require(function["FunctionArn"].split(":")[4] == args.expected_account, "Proxy account mismatch")
    require(settings["AGENT_RUNTIME_ARN"] == outputs["agentcore_runtime_arn"]
            and settings["LIMITS_TABLE_NAME"] == outputs["analysis_limits_table_name"]
            and settings["COGNITO_CLIENT_ID"] == outputs["cognito_user_pool_client_id"]
            and settings["COGNITO_ISSUER"] == f"https://cognito-idp.{outputs['aws_region']}.amazonaws.com/{outputs['cognito_user_pool_id']}",
            "Proxy settings do not match the selected state")
    report["proxy_code_sha256"] = function["CodeSha256"]
    window_seconds = int(settings["USER_WINDOW_SECONDS"])
    limit = int(settings["USER_REQUESTS_PER_WINDOW"])
    require(window_seconds == 3600 and limit >= 1, "Unexpected admission configuration")

    url = outputs["app_url"].rstrip("/") + "/api"
    empty = {"job_id": report["run_id"], "images": []}
    check("anonymous_rejected", lambda: post_case(url, None, empty, 401))
    check("anonymous_ingredient_lookup_rejected", lambda: lookup_case(url, None, {}, 401))
    check("direct_runtime_denied", lambda: direct_runtime_denied(client("bedrock-agentcore"), outputs["agentcore_runtime_arn"]))

    cognito = client("cognito-idp")
    pool = outputs["cognito_user_pool_id"]
    username = f"release-{report['run_id']}@example.invalid"
    password = f"Aa1!{secrets.token_urlsafe(32)}"
    table = session.resource("dynamodb", config=config).Table(outputs["analysis_limits_table_name"])
    with ExitStack() as cleanup:
        def clean(name, action):
            # Cleanup errors are recorded without preventing other cleanup.
            try:
                check(name, action)
            except Exception:
                report["cleanup_failed"] = True

        created = cognito.admin_create_user(
            UserPoolId=pool, Username=username, MessageAction="SUPPRESS",
            TemporaryPassword=password,
            UserAttributes=[{"Name": "email", "Value": username}],
        )
        cleanup.callback(clean, "delete_test_user",
                         lambda: cognito.admin_delete_user(UserPoolId=pool, Username=username))
        subject = next(a["Value"] for a in created["User"]["Attributes"] if a["Name"] == "sub")
        cognito.admin_set_user_password(UserPoolId=pool, Username=username, Password=password, Permanent=True)

        def sign_in(client_id):
            result = cognito.initiate_auth(
                ClientId=client_id, AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters={"USERNAME": username, "PASSWORD": password},
            )
            require("AuthenticationResult" in result, "Unexpected sign-in challenge")
            return result["AuthenticationResult"]

        tokens = check("test_user_sign_in", lambda: sign_in(outputs["cognito_user_pool_client_id"]))
        token = tokens["IdToken"]
        other = cognito.create_user_pool_client(
            UserPoolId=pool, ClientName=f"release-{report['run_id']}",
            GenerateSecret=False, ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"],
        )["UserPoolClient"]["ClientId"]
        cleanup.callback(clean, "delete_test_client",
                         lambda: cognito.delete_user_pool_client(UserPoolId=pool, ClientId=other))
        wrong = sign_in(other)["IdToken"]
        check("wrong_audience_rejected", lambda: post_case(url, wrong, empty, 401))
        check("access_token_rejected", lambda: post_case(url, tokens["AccessToken"], empty, 401))
        check("empty_images_rejected", lambda: post_case(url, token, empty, 400, "INVALID_INPUT"))
        check("extra_fields_rejected", lambda: post_case(
            url, token, {**empty, "images": ["aGVsbG8="], "user_id": "other"}, 400, "INVALID_INPUT"))
        check("four_images_rejected", lambda: post_case(
            url, token, {**empty, "images": ["aGVsbG8="] * 4}, 413, "REQUEST_TOO_LARGE"))
        check("conflicting_v2_preferences_rejected", lambda: post_case(
            url, token, {
                **empty, "images": ["aGVsbG8="], "api_version": 2,
                "preferences": {
                    "excluded_ingredient_ids": ["synthetic-constraint"],
                    "must_have_by_category": [{
                        "category_id": "Cleanser", "ingredient_ids": ["synthetic-constraint"],
                    }],
                },
            }, 400, "INVALID_PREFERENCES"))
        check("free_text_lookup_rejected", lambda: lookup_case(
            url, token, {"query": "semantically similar ingredient"}, 400, "INVALID_PREFERENCES"))

        def lookup_contract():
            catalog = lookup_case(url, token, {})
            require(bool(catalog.get("taxonomy_version")) and len(catalog.get("categories", [])) >= 2,
                    "Missing exact ingredient catalog configuration")
            summary = lookup_case(url, token, {"category_id": catalog["categories"][0]})
            require(summary.get("advisory") is True and 0 < len(summary.get("ingredients", [])) <= 30,
                    "Expected a bounded, published ingredient summary")
            # Resolve actual catalog entries both by exact ID and by display
            # name, so this contract does not assume a particular supplier.
            entry = summary["ingredients"][0]
            references = [
                {"ingredient_id": entry["ingredient_id"]},
                {"name": entry["display_name"]},
                {"ingredient_id": "synthetic-absent-ingredient-20261027"},
            ]
            results = lookup_case(url, token, {"references": references})["results"]
            require(len(results) == 3 and results[0].get("status") == "resolved"
                    and results[1].get("status") == "resolved"
                    and results[0].get("ingredient_id") == results[1].get("ingredient_id") == entry["ingredient_id"]
                    and results[2].get("status") == "unresolved",
                    "Exact identities or absent ingredient handling differed from the catalog")
            return catalog

        check("exact_ingredient_lookup_and_summary", lookup_contract)

        identity = f"{settings['COGNITO_ISSUER']}\0{subject}"
        prefix = "USER#" + hashlib.sha256(identity.encode()).hexdigest()
        # This payload passes proxy syntax checks, but is not a decodable image.
        # If admission fails open, the runtime rejects it before model invocation.
        probe = {**empty, "images": ["aGVsbG8="]}
        now = int(time.time())
        require((now % window_seconds) < window_seconds - 90, "Rerun away from the hourly boundary")
        counter_key = f"{prefix}#WINDOW#{now // window_seconds}"
        lease_key = f"{prefix}#ACTIVE"
        with seeded_item(table, {"pk": counter_key, "request_count": limit, "expires_at": now + 1800}, report["run_id"]):
            check("hourly_limit_enforced", lambda: post_case(url, token, probe, 429, "USER_RATE_LIMITED"))
        with seeded_item(table, {"pk": lease_key, "lease_owner": report["run_id"], "expires_at": now + 1200}, report["run_id"]):
            check("active_lease_enforced", lambda: post_case(url, token, probe, 429, "ANALYSIS_IN_PROGRESS"))
            require("Item" not in table.get_item(Key={"pk": counter_key}, ConsistentRead=True),
                    "Rejected lease request consumed the hourly allowance")

        if args.image:
            image = args.image.read_bytes()
            require(0 < len(image) <= 1024 * 1024, "Photo must be between 1 byte and 1 MiB")
            start = time.monotonic()
            events, arrivals = [], []
            concurrency_checked = False
            with requests.post(
                f"{url}/analyze", headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
                json={**empty, "images": [base64.b64encode(image).decode("ascii")]},
                stream=True, timeout=(10, 65), allow_redirects=False,
            ) as response:
                require(response.status_code == 200, "Normal analysis did not return HTTP 200")
                require(response.headers.get("Content-Type", "").startswith("text/event-stream"),
                        "Normal analysis did not return SSE")
                for event in iter_events(response):
                    arrivals.append(time.monotonic() - start)
                    events.append(event)
                    require(arrivals[-1] < 900 and len(events) <= 10000, "Live analysis exceeded test bounds")
                    if not concurrency_checked and event.get("type") == "multiagent_node_start":
                        expected_code = "ANALYSIS_IN_PROGRESS" if limit > 1 else "USER_RATE_LIMITED"
                        check("second_request_rejected_during_analysis",
                              lambda: post_case(url, token, probe, 429, expected_code))
                        concurrency_checked = True
            errors = validate_events(events) + validate_timings(events, arrivals)
            check("normal_photo_incremental_sse",
                  lambda: require(not errors, f"Stream contract or timing failed ({len(errors)} checks)"))
            report["stream"] = {
                "event_count": len(events), "first_event_seconds": round(arrivals[0], 3),
                "total_seconds": round(arrivals[-1], 3),
                "max_event_gap_seconds": round(max(b-a for a, b in zip(arrivals, arrivals[1:])), 3),
            }
            routine = extract_routine(events)
            products = session.resource("dynamodb", config=config).Table(outputs["products_table_name"])
            def check_products():
                for step in routine["routine_steps"]:
                    for product in step["products"]:
                        item = products.get_item(Key={"product_id": product["product_id"]}, ConsistentRead=True).get("Item")
                        require(item is not None, "Recommended product is absent from the deployed catalog")
            check("recommended_product_ids_exist", check_products)
            # Normal requests create counters with TTL. Retain their audit trail;
            # deleting the test user makes its remaining allowance unusable.
        else:
            check("runtime_corrupt_image_sse",
                  lambda: runtime_rejects_corrupt_image(
                      url, token, {**probe, "api_version": 2, "preferences": {}}))
            report["checks"].append({"name": "normal_photo_incremental_sse", "status": "SKIPPED"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs", type=Path, required=True, help="terraform output -json file")
    parser.add_argument("--expected-account", required=True)
    parser.add_argument("--revision", required=True, help="Reviewed Git revision being tested")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--allow-test-resources", action="store_true", help="Allow isolated user/client and limit-record creation")
    parser.add_argument("--image", type=Path)
    parser.add_argument("--allow-model-invocations", action="store_true")
    args = parser.parse_args()
    if not args.allow_test_resources:
        parser.error("--allow-test-resources is required; use only a dedicated test deployment")
    if args.image and not args.allow_model_invocations:
        parser.error("--image requires --allow-model-invocations and a photo you may send to AWS")
    report = {"run_id": uuid.uuid4().hex, "revision": args.revision,
              "started_at": datetime.now(timezone.utc).isoformat(), "checks": [], "release_ready": False}
    status = 0
    try:
        run(args, report)
    except Exception as exc:
        # Never serialize SDK messages, tokens, photos or profile/routine text.
        report["failure"] = str(exc) if isinstance(exc, CheckFailure) else type(exc).__name__
        status = 1
    if report.get("cleanup_failed"):
        status = 1
    report["automated_scope_status"] = "PASS" if status == 0 else "FAIL"
    report["manual_and_operational_checks"] = "PENDING"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(f"{report['automated_scope_status']}: report written to {args.report}")
    raise SystemExit(status)


if __name__ == "__main__":
    main()
