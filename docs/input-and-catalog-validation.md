# Input and catalog validation

The analysis endpoint accepts only `job_id` and `images`. A request contains one
to three base64 images. Each decoded image must be at most 1 MiB, with each side
at most 2048 pixels. The encoded length is checked before base64 allocation.
JPEG, PNG, static GIF and static WebP are supported; animations, corrupt images
and unexpected request fields are rejected before constructing an agent or an
AWS client.

Pillow verifies the file, then reopens and fully decodes it. Accepted images are
normalized to JPEG, without EXIF metadata or appended file content. The normalized
file must also fit the byte limit. Limit violations return `REQUEST_TOO_LARGE`;
invalid files or schemas return `INVALID_INPUT`. The browser already resizes
uploads to at most 1280 pixels; the server checks remain necessary for clients
that bypass the browser.

Product agents select stable `product_id` values returned by their own successful
catalog query. A selection from another step, a fabricated ID, or a duplicate ID
fails validation. Before either an intermediate product event or the final routine
is sent, the server resolves the name, price, score, matched ingredients and image
path from the trusted query results. Model-supplied values cannot override those
facts. The compiler repeats that validation.

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

These controls do not themselves establish per-user usage budgets, prevent direct
runtime access, or make model explanations factual. Those concerns remain open
in the [security checklist](security-checklist.md) until separately verified.

Implementation references:

- [Pillow image verification and decoding](https://pillow.readthedocs.io/en/stable/reference/Image.html)
- [Pillow 13.0.0 image decoder source](https://github.com/python-pillow/Pillow/blob/13.0.0/src/PIL/Image.py)
- [Bedrock image formats](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ImageBlock.html)
- [Strands tool context](https://strandsagents.com/latest/documentation/docs/user-guide/concepts/tools/custom-tools/)
- [CloudFront response headers policies](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/adding-response-headers.html)
