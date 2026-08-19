# AgBid Label Source Plan

## First Principles

AgBid does not need every label on day one. It needs enough trusted product identity to let a grower ask for a familiar product and let a supplier bid a lawful, equivalent delivered product.

The source hierarchy is:

1. EPA PPIS for registered product, ingredient, registrant, distributor-brand, and status data.
2. EPA PPLS for accepted label PDFs by EPA registration number.
3. Texas Department of Agriculture rules for Texas sale, dealer, applicator, and label compliance gates.
4. CDMS/Agrian only as licensed enrichment or manual cross-checking, not as the canonical scraped source.

## PPIS Launch-Wedge Index

Run:

```bash
python3 scripts/build_ppis_index.py
```

This downloads official EPA PPIS files into `.cache/ppis/` and writes:

- `outputs/ppis_launch_wedge_index.json`
- `outputs/ppis_launch_wedge_summary.json`

The current index is limited to AgBid's launch wedge: glyphosate, glufosinate, 2,4-D choline/DMA, dicamba DGA/BAPMA, and clethodim. It normalizes EPA registration numbers, active-ingredient PC codes, active percentages, restricted-use flags, alternate product names, and distributor product names.

Use this index to expand product matching and operator review. Do not treat it as transaction clearance by itself; every live transaction still needs current PPLS label confirmation and Texas compliance review.

## Why Not Scrape Everything First

Scraping every CDMS/Agrian label is the wrong first move because it delays the marketplace test and adds licensing/terms risk before there is proof that distributors will bid. The MVP should seed the highest-volume active ingredients, attach EPA registration numbers, and expand only when a real grower request requires another product.

## MVP Label Fields

Every product record needs:

- Active ingredient
- Brand/product name
- Manufacturer or registrant
- EPA registration number
- Active percentage
- Default adjuvant guidance, if known
- EPA PPLS lookup URL
- Texas compliance status once verified

## Current Seed

The active seed file is `agbid_label_database.json`. It covers the first crop-input wedge: glyphosate, glufosinate, 2,4-D, dicamba, and clethodim families.

## Next Build Step

Run `python3 scripts/verify_epa_labels.py` before using seeded products in a pilot. The script writes:

- `agbid_label_database.verified.json`
- `outputs/label_verification_report.json`

For products outside the seed, use `label_review.html` or `/api/labels/live-search` to search EPA PPLS live by product name or ingredient. Save uncertain products as review candidates before adding them to the verified label database.

Build a PPIS ingestion script next that normalizes EPA product files into:

- `active_ingredients`
- `chemical_brands`
- `epa_label_refs`
- `texas_sale_gates`

The first PPIS ingestion script now exists as `scripts/build_ppis_index.py`. It is not yet a full production catalog database. Until a production catalog and Texas sale-gate workflow exist, do not pretend the label catalog is complete. Use the seeded catalog and PPIS launch-wedge index for pilots, then manually verify any requested product outside the seed before clearing money.

## Compliance Rule

AgBid must never tell a grower how to apply a pesticide. The product page and bid page should say the product must be used according to the actual label on the container and the current EPA/Texas-approved label.
