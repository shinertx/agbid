# Texas Customer And Supplier Readiness

## Verdict

AgBid is ready for manual Texas pilot recruiting, not autonomous chemical transactions.

The correct first sale is concierge-operated: one real grower request, three real blind supplier bids, AgBid as clearing party, and manual payment/legal review before money moves.

## First Principles Marketplace Logic

- The grower wants delivered certainty: product, gallons, delivery date, and total delivered cost.
- The supplier wants margin and channel safety: blind bids, no public price board, and AgBid as the clearing party.
- AgBid needs transaction control: hidden reserve, must-pick rule, and payment flow that prevents immediate bypass.
- The label system exists to identify lawful equivalent products, not to become the product.

## Texas Launch Wedge

Start with large row-crop growers buying 250+ gallon lots in:

- High Plains: cotton, corn, sorghum, wheat
- Blacklands / Central Texas: corn, cotton, wheat, hay
- Coastal Bend / Rio Grande Valley: cotton, sorghum, corn, vegetables

## Grower Pilot Gate

A customer lead is real only if they provide:

- Product or brand they actually buy
- Gallons
- Delivery ZIP
- Need-by date
- Hidden target price they would lock in
- Payment path: operating line, wire, or other approved method

## Supplier Pilot Gate

A supplier lead is real only if they agree to:

- Submit blind delivered bids
- Include freight
- Include EPA registration number
- Include delivery date
- Optionally include adjuvant bundle economics
- Let AgBid be the clearing/payment party for the pilot

## Must-Pick Rule

If any delivered bid is at or below the grower's hidden target price, the grower must select a bid or pay a market-integrity fee. Without this, AgBid becomes a free price-discovery tool and suppliers will stop participating.

## Ads And Promotion

Do not put ads in the first grower quote flow. Paid supplier promotion can come later as clearly labeled optional product placement for adjuvants, nutritionals, or generics. The first product must earn trust by making the quote flow feel neutral.

## Kill Test

The business is dead or must pivot if three Texas-capable suppliers refuse to submit blind delivered bids when AgBid is the clearing party.

## Current MVP Evidence

The API now supports:

- EPA PPLS verification reports with status flags
- EPA PPIS launch-wedge index and summary for official product identity / active-ingredient coverage
- Verified-label database preference when `agbid_label_database.verified.json` exists
- Grower request creation
- 48-hour supplier bid tokens
- Blind supplier bid submission
- Delivered price and optional adjuvant bundle math
- Hidden reserve / must-pick status
- Bid selection and 2.5% AgBid fee calculation
- Automatic post-award deal review checklist before manual clearing

Current PPIS launch-wedge index coverage:

- 2,046 matching PPIS products across the target launch ingredients
- 1,062 active PPIS products
- 19 restricted-use products flagged for additional compliance review

## Recruiting Assets

- `TEXAS_PILOT_RECRUITING.md`
- `outputs/texas_pilot_supplier_targets.csv`
- `outputs/texas_pilot_grower_targets.csv`

This is enough to recruit pilots. It is not enough to process unrestricted live transactions without legal, compliance, payment, and insurance review.

## Manual Deal Review Gate

After a grower selects a bid, AgBid must complete the deal review before taking payment or clearing supplier payout. The required manual gates are:

- Current label / EPA registration confirmed
- Texas dealer status verified or not required for the selected product
- Freight-included economics confirmed
- Delivery date confirmed
- Grower payment path authorized
- AgBid clearing terms accepted
- Supplier invoice ready
- Delivery-proof plan confirmed

Until all gates are checked, the settlement remains blocked for manual review.
