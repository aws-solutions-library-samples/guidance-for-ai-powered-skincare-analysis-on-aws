# Model configuration

| Role | Global inference profile | Adaptive reasoning effort |
|---|---|---|
| Skin analysis | `global.anthropic.claude-sonnet-5-5` | `medium` |
| Routine planning, ingredients, products | `global.anthropic.claude-haiku-5-5` | `low` |

`config.py` sets these profiles, explicit streaming, native strict tool schemas,
and an 8,192-token response ceiling per model call, including thinking tokens.
The ceiling is not a target or a guarantee that a response will finish.
No temperature, top-p, or top-k is sent: the selected models reject sampling
parameters. Terraform permits only these two model families and profiles.
Global inference can process requests outside the deployment region.

## API and structured output

Strands uses the Bedrock Runtime **ConverseStream** API. The Lambda proxy uses
**InvokeAgentRuntime** to reach the hosted agent; that is separate from model
inference. Browser progress continues over SSE.

`strict_tools=True` enables Bedrock's native schema enforcement for catalog
tool arguments and structured-output tool calls. This uses `toolSpec.strict`,
not the separate `outputConfig.textFormat` JSON-response mode. It preserves
Strands' tool execution and structured-output validation.

Bedrock supports a subset of JSON Schema. `agents/bedrock_schema.py` copies
outbound schemas, disallows additional object properties, and moves unsupported
numeric, string-length, and array-size bounds into descriptions. Pydantic models
and tool functions retain the actual constraints. Schema conformance does not
establish factual correctness, appropriate recommendations, or catalog identity.
Existing validation and trusted-catalog binding remain required.

Sonnet 5.5 rejects forced tool choices (`any` and `tool`). When Strands retries
missing structured output with a single tool, `GuardedBedrockModel` uses `auto`
and requests that tool in the system prompt. Strands retains its bounded retry
and raises if the model still omits the output. The adapter does not accept prose
as a valid result or silently reinterpret a forced choice among multiple tools.
Guardrail assessments still pass through the existing typed error handler.

New strict schemas may take approximately 90 seconds to compile on first use;
Bedrock caches compiled schemas for 24 hours. The SDK's 120-second read timeout
accommodates compilation at the model boundary, but the application's separate
60-second CloudFront idle timeout still needs a cold-schema end-to-end test.
Prewarming is useful for testing but is not a substitute for that test.

## Validation

Offline model-compatibility tests exercise the pinned Strands SDK through a
mocked AWS client. They check actual outbound requests, all application schemas,
structured-output retry and failure paths, and preservation of guardrail and
value validation.

Live testing must cover both models with deployed Guardrails, every output and
catalog-tool schema, and a multi-turn tool-result exchange. Record the exact
profiles, settings, source revision, timing, and result. These contract checks
do not evaluate recommendation quality. The real photo flow, cold-schema SSE,
representative profile evaluation, and latency/load tests remain separate gates.

Run the opt-in contracts against a test deployment:

```bash
terraform -chdir=terraform output -json > output/release-validation/outputs.json
uv run --locked python -m tests.live_models \
  --outputs output/release-validation/outputs.json \
  --expected-account YOUR_TEST_ACCOUNT_ID \
  --revision YOUR_REVIEWED_REVISION \
  --report output/release-validation/models.json \
  --allow-model-invocations
```

Use the same AWS profile as deployment. This makes billable model requests and
reads the test catalog metadata. It generates its own color swatch and uses fictional
profile data; it does not read personal photos or existing user sessions.
It runs the local model code, so record the tested revision separately from the
deployed runtime version.

The local metadata contract uses 500 ms connection/read limits and one SDK attempt
for the operator's internet connection to the regional DynamoDB API. The normal
overall metadata budget and lookup bounds still apply. The application's private
50/100 ms transport settings remain unchanged and need native VPC checks; this
local model contract is not a latency qualification.

The README cost estimate remains based on the previous models. Recalculate
costs from the selected model prices and measured token usage before production.

## Official references

- [Bedrock inference APIs](https://docs.aws.amazon.com/bedrock/latest/userguide/apis.html)
- [Bedrock native structured outputs and schema limits](https://docs.aws.amazon.com/bedrock/latest/userguide/structured-output.html)
- [Adaptive thinking and effort settings](https://docs.aws.amazon.com/bedrock/latest/userguide/claude-messages-adaptive-thinking.html)
- [Strands Bedrock provider](https://strandsagents.com/docs/user-guide/sdk/model-providers/amazon-bedrock/index.md)
- [Claude Sonnet 5.5](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-5-5.html)
- [Claude Haiku 5.5](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-haiku-5-5.html)
