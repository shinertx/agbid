# AgBid Project Closeout

Date: 2026-08-03

## Status

Local project packet closed.

AgBid is demo-ready and operator-ready for a manual pilot test. It is not customer-live, paid, legally cleared, or transaction-proven.

## Desired Outcome

Prove or kill AgBid as a transaction-first concierge marketplace for crop inputs.

The decisive proof is one real grower request that produces three blind delivered supplier bids, with AgBid as the clearing party.

## Binding Constraint

The binding constraint is not more software. It is supplier and grower behavior:

- A grower must give product, gallons, ZIP, need-by date, hidden target price, and a must-pick commitment.
- Three Texas-capable suppliers must submit blind delivered bids including freight, EPA registration, and delivery date.
- AgBid must complete manual label, freight, payment, Texas compliance, supplier invoice, and delivery-proof review before money moves.

## Proof Rung Achieved

Built and locally verified prototype.

Not achieved:

- customer-live
- supplier-live
- paid
- settled
- compliance-cleared
- production-deployed

## Verified Facts

- Farmer request flow exists at `index.html`.
- Supplier blind bid flow exists at `supplier_bid.html`.
- Supplier onboarding exists at `supplier_onboarding.html`.
- Operator board exists at `operator.html`.
- Pilot lead desk exists at `pilot_leads.html`.
- Label review exists at `label_review.html`.
- Deal desk exists at `deal_desk.html`.
- Backend exists at `agbid_api_backend.py`.
- First transaction doctrine exists at `FIRST_TRANSACTION_PROOF.md`.
- Texas recruiting packet exists at `TEXAS_PILOT_RECRUITING.md`.
- Product-genome artifacts exist under `.run/product-genome/`.

## Verification Run

Commands run on 2026-08-03:

```text
python3 -m py_compile agbid_api_backend.py api/index.py scripts/smoke_test.py scripts/build_ppis_index.py scripts/verify_epa_labels.py
python3 scripts/smoke_test.py
```

Result:

- Python compile: pass
- Smoke test: pass
- Smoke request ID: `req-ee769b75dd32`
- Smoke selected bid ID: `bid-cd06e4dbd5b8`
- AgBid fee calculation: `798.75`
- Operator foundry gate: `manual_clearing_ready`
- Foundry score: `9`
- PPIS active product count: `1062`

Nonfatal caveat:

- Live EPA search was slow or unavailable for the Roundup check during smoke test. The verified seed database path still passed.

## Completed Local Artifacts

- `FIRST_TRANSACTION_PROOF.md`
- `TODO.md`
- `.run/product-genome/agbid-marketplace.pdl`
- `.run/product-genome/agbid-marketplace-v2.pdl`
- `.run/product-genome/regulated-b2b-auction.mgl`
- `.run/product-genome/agbid-proof-report.md`
- `.run/product-genome/agbid-v2-proof-report.md`
- `.run/product-genome/rejected-mutations.md`

## Current Operating Rule

Do not sell AgBid as an app yet.

Sell it as a managed buying desk:

```text
Tell us what you need, how many gallons, where it goes, when you need it, and the delivered price where you would lock it in. We will bring back blind delivered bids from Texas-capable suppliers.
```

Farmers get one intake. Suppliers get tokenized bid links. Operators get the board. Compliance gets label review.

## Closeout Decision

Stop building new product surface until the first transaction proof is attempted.

The next value move is external and authority-gated: get the named grower request details and supplier bid commitments.
