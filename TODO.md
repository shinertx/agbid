# AgBid TODO

## Open Business Proof TODOs

Roles updated 2026-08-20: Nathan Burson is cofounder, supply-side (works at Wilbur-Ellis). He is supplier #1 candidate, not the pilot grower. The grower slot is open.

- [ ] Nathan completes supplier onboarding (freight-included, EPA numbers, Texas regions, AgBid clearing acceptance).
- [ ] Find the pilot grower (was Nathan's slot): one Texas row-crop operator with a real buy — product or brand, gallons, delivery ZIP, need-by date, hidden delivered target price, payment path.
- [ ] Get that grower's must-pick answer: if a supplier beats the hidden delivered target, will they pick through AgBid?
- [ ] Recruit two more Texas-capable suppliers beyond Nathan (his bid proves mechanics; arms-length bids prove the market).
- [ ] For each supplier, confirm freight-included bid, EPA registration number, delivery date, and AgBid clearing acceptance.
- [ ] Run the first real blind bid cycle.
- [ ] Complete manual label, Texas compliance, freight, payment, supplier invoice, clearing terms, and delivery-proof review before money moves.
- [ ] Decide proceed/narrow/kill after the first bid cycle using the kill standards in `FIRST_TRANSACTION_PROOF.md`.

## Open Product/Engineering TODOs

- [ ] Create a stable deploy target before sharing public links again. Temporary Cloudflare links expire.
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
- [x] Clean repo boundary: own git repo, public at github.com/shinertx/agbid (2026-08-19).
- [x] Honest demo: fabricated bids and fake fallback removed; real auction with grower-key blindness (2026-08-19).
