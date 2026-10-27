# Input and catalog validation

Legacy v1 accepts only `job_id` and `images`. V2 adds `api_version: 2` and optional
validated preferences; unsupported fields, unknown identities, conflicting
exclusions/must-haves and invalid price caps return `INVALID_PREFERENCES`.
A request contains one
to three base64 images. Each decoded image must be at most 1 MiB, with each side
at most 2048 pixels. The encoded length is checked before base64 allocation.
JPEG, PNG, static GIF and static WebP are supported; animations, corrupt images
and unexpected request fields are rejected by the runtime before constructing
an agent or its AWS clients. The Lambda proxy performs separate payload and
identity checks before invoking the runtime.

Pillow verifies the file, then reopens and fully decodes it. Accepted images are
normalized to JPEG, without EXIF metadata or appended file content. The normalized
file must also fit the byte limit. Limit violations return `REQUEST_TOO_LARGE`;
invalid files or schemas return `INVALID_INPUT`. The browser already resizes
uploads to at most 1280 pixels; the server checks remain necessary for clients
that bypass the browser.

Server code selects stable product IDs from a bounded exact-ingredient query and
strong canonical reads. The product agent may explain only that ordered list.
Its fabricated, duplicate, omitted or reordered IDs invalidate the explanation;
they do not change the server's selection. Canonical facts supply names, prices,
coverage, ingredients and images. Finalization rereads at most 24 products,
removes changed matching records, refreshes display facts and drops stale generated
explanations. See the [search specification](search-spec/README.md).

Every explicit must-have is required within its named category. Exclusions apply
to every step and require both a complete source ingredient list and complete
identity resolution. Unknown constrained facts fail eligibility. Match counts
do not imply concentration, stock or effectiveness.

Product pictures must be local assets with paths such as
`/products/cleanser/front.webp`. Publish them under `frontend/public/products/`.
Only PNG, JPEG and WebP paths with letters, digits, underscores and hyphens are
accepted. Absolute URLs, query strings, traversal, encoded paths and SVGs are
discarded. Missing or disallowed pictures use the existing product placeholder.
The bundled sample catalog has no external image dependency.

The deployed CSP permits scripts from the application's origin, product and
photo images from the same origin or local data/blob URLs, and connections to
the application and its regional Cognito endpoint. Inline styles remain necessary
for the current animation and UI components. Inline scripts, evaluated scripts,
arbitrary HTTPS image hosts, objects and base-URL changes are not permitted.

The Lambda proxy separately enforces per-user allowances and active-analysis
leases, and the runtime resource policy restricts invocation to the proxy role.
Their deployed behavior must be checked with the [release validation runbook](release-validation.md).
These controls do not make model explanations factual. The
[security checklist](security-checklist.md) tracks the remaining release evidence.

Implementation references:

- [Pillow image verification and decoding](https://pillow.readthedocs.io/en/stable/reference/Image.html)
- [Pillow 13.0.0 image decoder source](https://github.com/python-pillow/Pillow/blob/13.0.0/src/PIL/Image.py)
- [Bedrock image formats](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ImageBlock.html)
- [Strands tool context](https://strandsagents.com/latest/documentation/docs/user-guide/concepts/tools/custom-tools/)
- [CloudFront response headers policies](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/adding-response-headers.html)
