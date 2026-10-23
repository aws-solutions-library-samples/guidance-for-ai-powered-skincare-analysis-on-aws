# Profile-based search experiments

This benchmark compares product retrieval and ranking **after a skin profile and
ingredient targets have been supplied**. It uses the production ingredient scorer
as a baseline, runs alternative methods, and evaluates result exports from other
engines. Application behavior and infrastructure are unchanged.

The included 24 profiles cover six categories, with 12 development and 12 test
cases: ingredient preferences, required ingredients, exclusions, budgets, rare
ingredients, and no eligible products. Example queries include a dry-skin barrier
serum under £30 excluding retinol, and a sensitive-skin cleanser with specified
ingredients.

**Seed judgments are assistant-authored engineering fixtures for fictional
products. They are not expert judgments, clinical advice, or customer validation.**
Grades were written before executing the experiments. The dev/test split exercises
the process but shares a tiny catalog and related intents. Do not infer a production
winner from its scores.

## Run the benchmark

From the project root, using the existing project environment:

```bash
.venv/bin/python -m experiments.search prepare-demo \
  --output output/search-benchmark/dataset

.venv/bin/python -m experiments.search run \
  --dataset output/search-benchmark/dataset \
  --split dev \
  --output output/search-benchmark/dev-local
```

Dataset and run directories must be new, preventing accidental replacement of a
frozen experiment. Outputs live under the already-ignored `output/` directory.

Every run produces:

- `report.md`: comparison table and side-by-side results for every profile.
- `report.json`: metrics, category/slice breakdowns, and paired bootstrap intervals.
- `per-query.csv`: inspectable individual failures.
- `<method>.jsonl`: candidates, final rankings, and raw latency samples.
- `<method>.manifest.json`: dataset and source hashes, configuration, package
  versions, model revisions, platform, and measurement scope.

Run the held-out split after deciding configurations using development data:

```bash
.venv/bin/python -m experiments.search run \
  --dataset output/search-benchmark/dataset \
  --split test \
  --output output/search-benchmark/test-local
```

Do not repeatedly choose configurations using the test scores. For customer data,
split by user/session and intent family, retain a later temporal test set when
possible, and keep near-duplicate profiles out of different splits.

## Methods and fair comparisons

| Method | Candidate/ranking behavior |
|---|---|
| `legacy_current` | The real production harmonic scorer; category only; top three including zero scores. CSV order resolves ties, standing in for the unspecified DynamoDB result order. |
| `harmonic_filtered` | Same scoring function, explicit hard filters, positive matches, a configurable candidate pool. This ablates eligibility and pool size, not just ranking. |
| `ingredient_coverage` | Canonical exact ingredient coverage, hard filters, deterministic product-ID tie breaks. No ingredient-position feature. |
| `bm25_filtered` | Reference BM25 over product name, category, and ingredients; hard filters before top-k. |
| `bm25_coverage_rrf` | Reciprocal rank fusion of lexical retrieval and ingredient coverage. This is not a dense semantic method. |
| `dense_exact` | Optional sentence embeddings with exact cosine search and hard filters. Small-corpus reference only. |
| `hybrid_bm25_dense_rrf` | Optional BM25 + dense retrieval fused by rank. |
| `hybrid_cross_encoder` | Optional cross-encoder reranking of a bounded hybrid shortlist. |

All alternatives receive the same profile text, category, ingredient preferences,
and constraints. The current method uses only inputs supported by its existing
interface; that difference is intentional and visible through the filtered
harmonic ablation. No method receives qrels or expected grades.

Hard filters currently cover category, `must_include`, `exclude`, and
`max_price`/`currency`. Missing or mismatched price/currency fails a price constraint.
Matching canonicalizes whitespace and case; it does not infer chemical equivalence,
SPF, concentration, allergies, or product safety from names. Customer attributes
need authoritative structured data and corresponding filter/evaluation logic.

The BM25 reference uses `k1=1.2`, `b=0.75`, positive Robertson/Lucene-style IDF,
global corpus statistics, and simple Unicode word tokenization. It is not claimed
to reproduce an OpenSearch analyzer or ranking exactly. RRF uses `k=60` with equal
weights. Use the development set for parameter experiments.

### Optional local neural experiments

The following two small, established models are architecture baselines, **not a
claim about current model leadership**. Public model commit IDs and the
Sentence Transformers package version were resolved on 2026-10-22.

This command uses an isolated environment, keeps the project lockfile fixed, and
places model/dependency caches in the ignored output directory:

```bash
HF_HOME="$PWD/output/search-benchmark/model-cache" \
UV_CACHE_DIR="$PWD/output/search-benchmark/uv-cache" \
uv run --locked --isolated --with sentence-transformers==6.2.0 \
  python -m experiments.search run \
  --dataset output/search-benchmark/dataset \
  --split dev \
  --output output/search-benchmark/dev-neural \
  --embedding-model sentence-transformers/all-MiniLM-L6-v2 \
  --embedding-revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 \
  --reranker-model cross-encoder/ms-marco-MiniLM-L6-v2 \
  --reranker-revision 233902d25c440f23af6f7d6e94d2946bac0bee0a \
  --device cpu
```

Model revisions must be exact commit hashes; remote model code is disabled. Try
other compatible embedding/reranker models by providing their pinned revisions.
Some model families require specific query prompts or instructions; inspect their
official model cards before comparing them. This adapter uses `encode_query` and
`encode_document`, including their configured prompts.

Local dense search scores the full corpus. It is a correctness reference for
approximate retrieval, not a production latency estimate. Query embedding,
retrieval, fusion, and reranking are timed within their respective method calls.
Loading models and encoding the product corpus are recorded separately.

## Metrics and choosing a winner

- **nDCG@3:** ranking quality with grades 0–3 and linear gain `grade/log2(rank+1)`.
- **P@3:** fraction of three recommendation slots containing a judged relevant
  product; denominator stays three when fewer products are returned.
- **MRR@10:** position of the first judged relevant result.
- **Candidate recall:** fraction of judged relevant products in the retrieved
  pool, before reranking. Compare actual pool sizes in the manifest and per-query
  metrics. On an eight-product category, large-pool recall is an easy ceiling.
- **Constraint violation rate:** fraction of returned top-three products violating
  stated hard constraints, averaged across queries. Also report the fraction of
  queries with any violation.
- **Correct abstention:** empty results for exhaustive, known-no-match queries.
- **Empty on answerable / unjudged fraction:** detect empty-result gaming and
  incomplete judgment coverage.
- **p50/p95/p99:** observed warmed local durations; inspect sample counts. These
  exclude AWS, network, queueing, upstream agents, and generated explanations.

Queries without positive judgments are excluded from nDCG/MRR/recall aggregates,
and reported through abstention. For pooled judgments, absence of a positive is
not proof of no match, so correct abstention is undefined. Unjudged retrieved
products receive zero gain and are also counted explicitly as unjudged; review
them before using small score differences to choose a system.

The report includes 95% paired bootstrap intervals for nDCG differences versus the
current baseline (2,000 query resamples, seed 17). These are exploratory on 12
queries, with no multiple-comparison correction. For real decisions, use enough
independent profiles to resolve the smallest improvement the customer cares about,
then confirm on a frozen test set.

Select among systems that satisfy customer-defined constraint, recall, latency,
and cost requirements. Compare relevance within that feasible set. Do not select
solely by nDCG: a system can rank one good product first while filling remaining
slots with constraint violations.

## Customer datasets and independent judging

The interchange format follows [BEIR custom datasets](https://github.com/beir-cellar/beir/wiki/Load-your-custom-dataset):

- `corpus.jsonl`: `_id`, `title`, `text`, plus `metadata` containing `category`,
  `ingredients`, `price`, and `currency`.
- `queries.jsonl`: `_id`, `text`, `split`, `category`, `profile`, and optional
  `preferred_ingredients`, `must_include`, `exclude`, `max_price`, `currency`, `tags`.
- `qrels.tsv`: header `query-id<TAB>corpus-id<TAB>score`, integer scores 0–3.
- `metadata.json`: `judgment_provenance`, `human_reviewed`,
  `judgment_scope` (`exhaustive` or `pooled`), and a customer catalog snapshot ID.

Use grades: 0 unsuitable for the stated request, 1 weak match, 2 good match,
3 excellent match. A hard-constraint violation must have grade 0. Domain reviewers
must define what suitability means for the customer before labeling; ingredient
overlap alone is not the grading rubric.

For hundreds of thousands or millions of products, label a **pooled candidate set**:
collect top results from every competing method, add known positives and sampled
negatives, deduplicate, and have reviewers judge without knowing the method or
rank. Save disagreements and adjudications. Keep at least one reviewer independent
of implementation decisions. An LLM judge can help prioritize review, but should
not be the sole ground truth.

Export a shuffled, method-blind review CSV:

```bash
.venv/bin/python -m experiments.search pool \
  --dataset output/search-benchmark/dataset \
  --split dev \
  --runs output/search-benchmark/dev-local/*.jsonl \
  --depth 20 \
  --output output/search-benchmark/review.csv
```

The CSV leaves grades blank and contains product IDs, profile text, constraints,
and product facts. After review, write the grades to a **new dataset's** qrels TSV,
record reviewer provenance, and rerun evaluation with manifests bound to that new
judgment snapshot. Do not silently relabel already-published reports.

For large indexes the evaluator can use an evaluation corpus consisting of judged
products plus every returned candidate. Record the full index snapshot in
metadata. Production retrieval must run against the full index; never retrieve
only from the judged pool. Candidate recall on pooled qrels measures recall of
known relevant items, not absolute recall of every relevant item in the catalog.

## Comparing production engines at thousands to millions of products

The local reference runner is deliberately capped at 10,000 products. Production
evaluation has two coordinated tracks:

1. **Relevance:** run identical frozen profile queries against the full customer
   index; export candidates and final rankings; evaluate with this harness.
2. **Serving performance:** load a realistic corpus into the intended deployment,
   exercise its actual query mix and concurrency, and measure throughput, errors,
   p95/p99 latency, index memory/storage, build/update time, and cost.

Suggested experiment matrix:

| Dimension | Starting experiments |
|---|---|
| Corpus | Representative 1k, 100k, and 1m snapshots, adjusted to customer size |
| Retrieval | Indexed structured baseline; BM25; dense ANN; BM25+dense hybrid |
| Candidate pool | 25, 50, 100, 200, bounded by available eligible products |
| Reranking | None; cross-encoder; optionally listwise, with identical candidate pools |
| Query slices | Popular/rare concerns, restrictive filters, exclusions, budgets, languages, no matches |
| Load | Customer QPS/concurrency targets, warm and cold runs, concurrent catalog updates |
| ANN validation | Compare ANN recall with exact vector neighbors on a tractable sample; separately measure relevance recall |

A suitable production architecture to test is:

```text
validated skin profile + preferences
  -> versioned profile/ingredient planning
  -> hard product filters
  -> indexed BM25 and ANN retrieval
  -> rank fusion
  -> bounded reranker
  -> top three + deterministic catalog binding
```

Keep embeddings and lexical indexes versioned against the same catalog snapshot.
Record analyzer settings, model/prompt revisions, ANN configuration, filtering
behavior, shards/replicas, hardware, and candidate limits. Include query embedding,
network, reranker inference, and explanation generation in customer end-to-end
latency/cost. Measure indexing and refresh costs separately.

Do not duplicate the 48 fictional products a million times and treat that as a
quality benchmark: duplicates distort term frequencies, vector neighborhoods,
filter selectivity, relevance, and caching. A generated load corpus can exercise
infrastructure, but must be labeled synthetic and cannot establish customer recall.

[OpenSearch hybrid/RRF documentation](https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/rrf/)
describes indexed fusion.
[OpenSearch Benchmark workloads](https://docs.opensearch.org/latest/benchmark/creating-custom-workloads/)
support realistic corpus/query workloads.
[Target-throughput documentation](https://docs.opensearch.org/latest/benchmark/target-throughput/)
explains the difference between service time and latency including queueing.
No index or cloud infrastructure is provisioned by this experiment.

### Import an engine's results

For each method export one JSONL record for **every selected query**, including
empty results. Arrays are already in rank order; scores need not be comparable
across methods:

```json
{"_id":"query-1","candidates":[{"product_id":"product-7","score":0.82}],"ranking":[{"product_id":"product-7","score":4.1}],"latency_ms":[47.2,48.1]}
```

`candidates` is the pre-rerank pool; `ranking` may be a reordered subset.
`latency_ms` must contain observed durations or `[]` when unmeasured, never invented
latencies. Pair `method.jsonl` with `method.manifest.json` containing:

```json
{
  "method": "customer-hybrid-rerank-v1",
  "split": "test",
  "dataset": {
    "corpus.jsonl": "<SHA256>",
    "queries.jsonl": "<SHA256>",
    "qrels.tsv": "<SHA256>",
    "metadata.json": "<SHA256>"
  },
  "timing_scope": "Describe network, embedding, ranking, queueing and generation inclusion",
  "catalog_snapshot": "<full production index snapshot>",
  "engine_configuration": {},
  "model_revisions": {}
}
```

Use `experiments.search.data.fingerprint(dataset_path)` to obtain the dataset
hashes. Add measured cost/resource data and engine settings to the manifest;
arbitrary provenance fields are preserved in the JSON report.

```bash
.venv/bin/python -m experiments.search evaluate \
  --dataset /path/to/customer-evaluation-dataset \
  --split test \
  --runs /path/to/runs/bm25.jsonl /path/to/runs/hybrid.jsonl \
  --output output/customer-search-comparison
```

Runs with missing queries, unknown/duplicate products, invalid scores, or a
mismatched dataset snapshot are rejected. If new methods retrieve unjudged items,
extend the blinded judgment pool and reevaluate every method consistently.

## End-to-end recommendation evaluation

This first harness freezes ingredient planning so retrieval changes are
attributable. Add a second track using profile-only inputs through the real agent
pipeline, with reviewed product/routine judgments as the target. Measure whether
the planner omitted useful ingredient options, consistency across repeated model
runs, cross-step compatibility under reviewed rules, and explanation grounding.
Keep prompt/model versions fixed while comparing retrievers; then test planner
changes separately. A retrieval benchmark alone does not establish routine quality.

## Verification and sources

```bash
.venv/bin/python -m pytest tests/unit/test_search_experiments.py
```

The metric tests use hand-calculated examples for linear nDCG, incomplete judgments,
abstention, candidate recall, and hard constraints. Integration checks validate
dataset exports and imported-run provenance.

- [BEIR evaluation metrics](https://github.com/beir-cellar/beir/wiki/Metrics-available)
- [trec_eval linear nDCG implementation](https://github.com/usnistgov/trec_eval/blob/main/m_ndcg_cut.c)
- [Sentence Transformers retrieve and rerank](https://sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html)
- [SentenceTransformer inference API](https://sbert.net/docs/package_reference/sentence_transformer/SentenceTransformer.html)
- [CrossEncoder inference API](https://sbert.net/docs/package_reference/cross_encoder/cross_encoder.html)
- [Embedding model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
- [Reranker model card](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2)
