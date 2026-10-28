# Product images

The demo catalog contains fictional products. When a product has no usable
catalog photograph, the frontend displays a generic AI-generated image for its
routine category: Cleanser, Toner, Serum, Moisturiser, Exfoliator or Sunscreen.
The **Illustrative image** label identifies these as illustrations, not
photographs of the named products.

The six shared 640 × 640 WebP files live in
`frontend/public/products/placeholders/` and ship with the frontend build. No
image-generation service or external image host is required at runtime.

## Using catalog photographs

1. Place licensed product photographs beneath `frontend/public/products/`,
   for example `frontend/public/products/example-cleanser.webp`.
2. Set the product's `image_url` to its same-origin path, for example
   `/products/example-cleanser.webp`, and publish the updated catalog record
   through the catalog ingestion process.
3. Rebuild and deploy the frontend.

The frontend accepts `.png`, `.jpg`, `.jpeg` and `.webp` paths under `/products/`.
It rejects external URLs, query strings and traversal paths. A usable catalog
photo takes priority and does not display the illustration label. If a photo
fails to load, the category illustration is shown instead.
