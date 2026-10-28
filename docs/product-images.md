# Product images

The demo catalog contains fictional products. When a product has no usable
catalog photograph, the frontend displays a generic image for its routine
category: Cleanser, Toner, Serum, Moisturiser, Exfoliator or Sunscreen. The
**Illustrative image** label and alternative text identify these images as
illustrations, not photographs of the named products.

The images live in `frontend/public/products/placeholders/` and are included in
the normal frontend build and deployment. They are six shared 640 × 640 WebP
files, approximately 27 KB in total. No image-generation service, API key,
external image host or per-product image generation is required at runtime.

## Using catalog photographs

1. Place licensed product photographs beneath `frontend/public/products/`,
   for example `frontend/public/products/example-cleanser.webp`.
2. Set the product's `image_url` to its same-origin path, for example
   `/products/example-cleanser.webp`, and publish the updated catalog record
   through the catalog ingestion process.
3. Rebuild and deploy the frontend to publish the image files.

The frontend accepts `.png`, `.jpg`, `.jpeg` and `.webp` paths under `/products/`
with letters, numbers, underscores, hyphens and optional subdirectories. It
rejects external URLs, query strings and traversal paths. A usable catalog photo
takes priority and does not display the illustration label.

A failed catalog photo falls back to the category illustration. If the
illustration also fails, or the category has no illustration, the original
no-image icon remains available. Placeholder selection only affects display:
it does not change catalog facts, ingredient matches, product ranking or agent
input.

## Generation record

These six original, unbranded packaging illustrations were generated on
28 October 2026 using the OpenAI Images API with
`gpt-image-2.5-sunburst`, medium quality and a 1024 × 1024 output size. The
[prompt set](product-image-prompts.jsonl) records the request for each category.
No customer photos or product reference images were used. The PNG originals
were resized with Lanczos resampling and encoded as 640 × 640 WebP images at
quality 82.

See the [official image-generation API documentation](https://developers.openai.com/api/docs/guides/image-generation)
for regenerating assets. Image generation is an optional authoring step,
separate from deploying or running this AWS sample.
