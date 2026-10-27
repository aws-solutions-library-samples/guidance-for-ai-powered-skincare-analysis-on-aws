# Guardrail diagnosis from the CLI

## Reproduced false positive (2026-10-19)

An ordinary-photo request completed skin analysis and routine planning, then
failed on the first model call in the ingredient agents. Replaying the captured
input with the actual ingredient agent reproduced `GUARDRAIL_PROMPT_ATTACK`.
Bedrock's trace identified **input** `PROMPT_ATTACK`, **LOW** detection confidence.
The configured filter strength was **HIGH**. Strength and confidence are different
fields.

The trigger was the application-added sentence:

> Analyze ingredients for your assigned step using the tools available.

Controlled CLI comparisons, repeated three times against the same guardrail
version, produced:

| Input | Result |
| --- | --- |
| Captured routine JSON alone | Allowed, 3/3 |
| Original application input, including the sentence | Prompt attack blocked, LOW confidence, 3/3 |
| That sentence alone, without personal data | Prompt attack blocked, LOW confidence, 3/3 |
| Same complete plan with only the sentence removed | Allowed, 3/3 |
| Corrected plan with an explicit instruction-override attack inside its rationale | Prompt attack blocked, HIGH confidence, 3/3 |

The sentence duplicated instructions already in the ingredient agent's system
prompt. `_build_prescribe_task` now sends the label and complete routine JSON
without that sentence. No plan fields are removed, no guardrail content is
excluded, and no filter strength or policy is changed.

The real ingredient agent completed after the removal. Replaying the complete
prescribe graph from the captured diagnosis also completed all six ingredient
agents, six product agents and the compiler across 27 real Bedrock calls, without
a guardrail block. An injected attack through the real agent still produced
`GUARDRAIL_PROMPT_ATTACK` on its first call.

This identifies the application text responsible for this observed block; AWS
does not expose the classifier's internal reasoning. It is not a guarantee
against future false positives on other inputs.

## Repeat the policy checks

Save a `StepAnalysisResult` JSON in a private, ignored local file. The file contains
the diagnosis and routine plan, not image bytes. Use the intended AWS profile,
region and deployed guardrail version explicitly:

```bash
.venv/bin/python scripts/check_guardrail.py \
  --profile YOUR_TEST_PROFILE \
  --region us-east-1 \
  --guardrail-id YOUR_TEST_GUARDRAIL_ID \
  --guardrail-version YOUR_DEPLOYED_VERSION \
  --plan-file .ash/remediation/your-private-plan.json \
  --repeats 3 \
  --output .ash/remediation/guardrail-check.json
```

The command sends the text to AWS and incurs guardrail API usage. It prints
input hashes, decisions, blocked categories/confidence and AWS request IDs;
it does not print plan contents or matched sensitive text. A nonzero exit
status means the corrected benign input was blocked or the injected attack
was not blocked as `PROMPT_ATTACK`. Historical false-positive cases are recorded
for comparison, not asserted as desirable behavior.

These `ApplyGuardrail` checks isolate policy behavior quickly. They do not call
the model, exercise image decoding, or prove the deployed application's complete
request path. For a model failure, also replay the affected agent with the same
input and capture `ConverseStream` metadata privately. Inspect
`inputAssessment` and `outputAssessments` separately. Keep model content and raw
traces out of public errors and tracked files.

Private evidence from this investigation is retained in `.ash/remediation/`:
`guardrail-cli-regression.json`, `exact-ingredient-replay-private.json`,
`without-suffix-ingredient-replay-private.json`,
`injected-ingredient-replay-private.json`, and `prescribe-replay-summary.json`.
The fix was deployed to isolated `test` on 2026-10-19 as runtime version 3,
artifact `b21d8d8e768643a116911dd27f77bac974ae5c50`. Fourteen authenticated
input/error smoke checks passed on that artifact. Full normal-photo request
closure remains tracked in the
[security checklist](security-checklist.md).

Official references:

- [Bedrock guardrails with Converse: message scope and trace fields](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-converse-api.html)
- [ApplyGuardrail API request and response](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ApplyGuardrail.html)
- [Strands graph orchestration](https://strandsagents.com/latest/documentation/docs/user-guide/concepts/multi-agent/graph/)
