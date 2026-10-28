# Goods pilot source

Selected by the repository owner for reuse on 2026-10-18.
Source: mori-memory-pilot, commit fb5a3418d2191734d10fcdcb546a77298b57a9f0.
Original local checkout: /Users/choijimin/Downloads/mori-memory-pilot (reference only; never a runtime dependency).

- examples/: original public/examples/products (keyring) and its magnet subdirectory.
- mockup/: original public/mockup/silver-hardware-v1.webp.
- Source README describes product examples as generated demonstration mockups, not customer work or actual manufactured products. Do not label these as real customer reviews or guaranteed manufacturing results.
- manifest.json records original relative paths and SHA-256 values.
- No top-level project LICENSE was present. This transfer is based on the owner's explicit reuse instruction, not an inferred open-source license.
- Original shadcn components/vendor CSS and fonts are not included. Their separate license notices must accompany any later reuse.

Related code: frontend/src/features/goods/mockup/geometry.ts and renderer.ts derive from lib/charm-geometry.ts and lib/charm-renderer.ts. Geometry now retains exact alpha bounds, validates inputs and accepts physical width. Renderer validates pixel limits and accepts physical width; application state is independently implemented in preview.ts.
