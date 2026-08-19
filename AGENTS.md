# AgBid — Agent Instructions

<!-- CODEX_PROJECT_ROUTER_POINTER_START -->
## Project Router

- This is project-local instruction scope. Read `/Users/benjijmac/WORKSPACE_INDEX.md` for global operating rules before substantive project work.
- Project routing lives in `/Users/benjijmac/workspace-audits/PROJECT_REGISTRY.json`; the readable map is `/Users/benjijmac/workspace-audits/PROJECT_CONVERSATION_MAP.md`.
- This file only adds local repo/workspace instructions. More specific local instructions still win inside this folder.
- Do not create competing project maps or move/delete folders from this local adapter.
<!-- CODEX_PROJECT_ROUTER_POINTER_END -->
This is the AgBid project: a grower-facing reverse-auction marketplace for farm crop protection inputs.

## Source of Truth

- Operating rules: `/Users/benjijmac/WORKSPACE_INDEX.md`
- Project home: `/Users/benjijmac/Documents/Playground/agbid`
- Product requirements: `PRD.md` in this directory
- Pressure test / validation: `PRESSURE_TEST.md` in this directory
- Label source plan: `LABEL_SOURCE_PLAN.md` in this directory
- Texas pilot readiness: `TEXAS_CUSTOMER_SUPPLIER_READINESS.md` in this directory
- Texas recruiting packet: `TEXAS_PILOT_RECRUITING.md` in this directory

## Project Context

- **Stage:** Interactive prototype / validation phase
- **Stack:** Vanilla HTML/CSS/JS (`index.html`, `supplier_bid.html`, `supplier_onboarding.html`, `operator.html`, `label_review.html`), FastAPI backend (`agbid_api_backend.py`)
- **Design philosophy:** Mobile-first, farmer-first, zero jargon, 3-tap UX
- **Business model:** 2.5% take-rate clearinghouse (Merchant of Record)

## Key Rules

- Keep the UI dead simple. Farmers use phones from truck cabs.
- Never use jargon: no "RFQ", "CDMS Parity", "Clearinghouse Network". Use plain English.
- Active ingredient mapping happens behind the scenes — the farmer just searches by product name.
- All changes must preserve the step-by-step wizard flow (search → specify → get quotes → pick → confirm).
- Do not add dashboard chrome, admin panels, or ads to the farmer-facing experience.
- Operator/admin pages are allowed only outside the farmer-facing flow.
- Use EPA PPIS/PPLS as the first canonical label-data path; treat CDMS/Agrian as licensed enrichment or manual verification, not the default scrape target.
- Run `python3 scripts/verify_epa_labels.py` when seed label records change; the app prefers `agbid_label_database.verified.json` if present.
- Run `python3 scripts/smoke_test.py` against a running local API after backend, label, supplier, or operator-flow changes.
- For Texas pilots, verify dealer/applicator/compliance gates before live restricted-use or state-limited-use transactions.
