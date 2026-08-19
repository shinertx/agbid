# AgBid TODO

## Open Business Proof TODOs

- [ ] Get Nathan's real request: product or brand, gallons, delivery ZIP, need-by date, hidden delivered target price, and payment path.
- [ ] Get Nathan's must-pick answer: if a supplier beats the hidden delivered target, will he pick through AgBid?
- [ ] Recruit three Texas-capable suppliers for the first request.
- [ ] For each supplier, confirm freight-included bid, EPA registration number, delivery date, and AgBid clearing acceptance.
- [ ] Run the first real blind bid cycle.
- [ ] Complete manual label, Texas compliance, freight, payment, supplier invoice, clearing terms, and delivery-proof review before money moves.
- [ ] Decide proceed/narrow/kill after the first bid cycle using the kill standards in `FIRST_TRANSACTION_PROOF.md`.

## Open Product/Engineering TODOs

- [ ] Create a stable deploy target before sharing public links again. Temporary Cloudflare links expire.
- [ ] Put AgBid in a clean repo boundary before committing or shipping. The current parent `Playground` git status treats the project folder as untracked.
- [ ] Replace file-backed state with production persistence before any real multi-user pilot.
- [ ] Add authentication/authorization before exposing operator, deal desk, or label review pages beyond local/demo use.
- [ ] Keep using verified EPA seed data and PPIS/PPLS review. Do not treat live EPA search availability as guaranteed.
- [ ] Review Texas dealer/applicator/compliance requirements with qualified counsel before live restricted-use or state-limited-use transactions.
- [ ] Define payment, refund, cancellation, delivery failure, and dispute handling before accepting real money.

## Done

- [x] Farmer-facing request prototype exists.
- [x] Supplier blind-bid prototype exists.
- [x] Supplier onboarding exists.
- [x] Operator board exists.
- [x] Pilot lead desk exists.
- [x] Label review page exists.
- [x] Deal desk exists.
- [x] First transaction proof doctrine exists in `FIRST_TRANSACTION_PROOF.md`.
- [x] Texas pilot recruiting packet exists in `TEXAS_PILOT_RECRUITING.md`.
- [x] Product genome v1 and v2 artifacts exist under `.run/product-genome/`.
- [x] Python compile check passed on 2026-08-03.
- [x] Smoke test passed on 2026-08-03 using temporary local state.
