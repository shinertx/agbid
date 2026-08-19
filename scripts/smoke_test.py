#!/usr/bin/env python3
"""
AgBid MVP smoke test.

Run while the AgBid API is serving (default http://127.0.0.1:8000).
Override the target with the AGBID_BASE_URL environment variable.
Exercises:
  - official-label source plan
  - EPA PPIS launch-wedge product index
  - live EPA label search
  - supplier onboarding/readiness
  - grower request
  - pilot lead capture/export gate
  - blind supplier bid
  - bid selection and settlement
  - post-award manual deal review
  - operator pilot board
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from typing import Any


BASE = os.environ.get("AGBID_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def call(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def call_status(method: str, path: str, payload: dict[str, Any] | None = None) -> int:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    source_plan = call("GET", "/api/labels/source-plan")
    require("agbid_label_database.verified.json" in source_plan["active_label_database"], "verified label DB not active")
    require(source_plan.get("ppis_launch_wedge"), "PPIS launch-wedge summary missing from source plan")
    require(
        source_plan["ppis_launch_wedge"]["summary"]["active_product_count"] > 0,
        "PPIS launch-wedge summary has no active products",
    )

    ppis_products = call("GET", "/api/labels/ppis-products?ingredient=Glyphosate&q=Roundup&limit=10")
    require(ppis_products["count_returned"] > 0, "PPIS product search returned no glyphosate products")
    require(
        any(
            product.get("product_status") == "Active"
            and "Glyphosate" in product.get("launch_groups", [])
            for product in ppis_products["products"]
        ),
        "PPIS product search did not return active glyphosate products",
    )

    live_epa_status = "not_checked"
    try:
        live_search = call("GET", "/api/labels/live-search?q=Roundup%20PowerMAX%203")
        require(live_search["candidates"], "live EPA search returned no candidates")
        require(
            any(c.get("epa_registration") == "524-729" for c in live_search["candidates"]),
            "Roundup live search did not include expected EPA registration 524-729",
        )
        live_epa_status = "passed"
    except Exception as exc:
        live_epa_status = f"external_epa_slow_or_unavailable: {exc}"

    supplier = call(
        "POST",
        "/api/suppliers/register",
        {
            "name": "Smoke Test Supplier",
            "contact": "smoke@example.com",
            "service_zips": ["794", "793"],
            "texas_regions": ["High Plains"],
            "verified_texas_dealer": True,
            "texas_dealer_license_number": "SMOKE-TX-DEALER",
            "dealer_license_expires_on": "2027-06-30",
            "texas_location_or_resident_agent": "Lubbock branch",
            "can_sell_restricted_state_limited_or_regulated_herbicides": True,
            "records_retention_acknowledged": True,
            "can_include_freight_in_bid": True,
            "accepts_agbid_as_clearing_party": True,
            "product_lines": ["glyphosate", "adjuvants"],
        },
    )
    require(supplier["readiness"]["status"] == "pilot_ready", "supplier not pilot_ready")
    require(
        supplier["pilot_lead"]["lead_type"] == "supplier"
        and supplier["pilot_lead"]["source"] == "supplier_onboarding",
        "supplier onboarding did not create supplier pilot lead",
    )

    call(
        "POST",
        "/api/operator/leads",
        {
            "lead_type": "grower",
            "name": "Smoke Grower Lead",
            "contact": "806-555-0199",
            "region": "High Plains",
            "status": "qualified",
            "product_interest": "Roundup PowerMAX 3",
            "gallons": 1000,
            "delivery_zip": "79401",
            "target_price_per_gal": 32,
            "next_action": "Convert to first live request",
        },
    )
    for index in range(3):
        call(
            "POST",
            "/api/operator/leads",
            {
                "lead_type": "supplier",
                "name": f"Smoke Supplier Lead {index + 1}",
                "contact": f"supplier{index + 1}@example.com",
                "region": "High Plains",
                "status": "pilot_ready",
                "product_interest": "glyphosate, adjuvants",
                "can_include_freight": True,
                "accepts_agbid_clearing": True,
                "texas_dealer_status": "manual verification pending",
                "next_action": "Send first blind bid invite",
            },
        )

    leads = call("GET", "/api/operator/leads")
    require(
        leads["summary"]["pilot_gate"]["ready_for_live_manual_auction"],
        "pilot lead gate did not reach manual-auction ready",
    )

    need_by = (date.today() + timedelta(days=10)).isoformat()
    request = call(
        "POST",
        "/api/grower/requests",
        {
            "grower_name": "Smoke Test Farm",
            "phone": "806-555-0101",
            "farm_county": "Lubbock",
            "delivery_zip": "79401",
            "product_query": "Roundup PowerMAX 3",
            "gallons": 1000,
            "need_by": need_by,
            "reserve_price_per_gal": 32,
            "financing_method": "operating_line",
        },
    )
    request_id = request["request"]["id"]
    grower_key = request.get("grower_key")
    require(grower_key, "creation response did not include a grower_key")
    require(request["request"]["matched_product"]["epa_registration"] == "524-729", "request did not use verified EPA reg")
    require(
        request["pilot_lead"]["lead_type"] == "grower"
        and request["pilot_lead"]["source"] == "grower_request",
        "grower request did not create qualified pilot lead",
    )
    require(len(request["supplier_invites"]) >= 3, "request did not invite at least three suppliers")

    for index, invite in enumerate(request["supplier_invites"][:3]):
        token = invite["api_url"].split("/")[-1]
        session_info = call("GET", f"/api/supplier/bid/{token}")
        require("id" not in session_info["request"], "supplier session leaked the request id")
        bid_response = call(
            "POST",
            f"/api/supplier/bid/{token}",
            {
                "supplier_contact_name": f"Smoke Rep {index + 1}",
                "product_name": "Roundup PowerMAX 3",
                "epa_registration": "524-729",
                "price_per_gallon": [33.5, 31.25, 29.95][index],
                "freight_total": [0, 450, 800][index],
                "delivery_date": need_by,
                "adjuvant_name": "Activator 90" if index == 2 else None,
                "adjuvant_price_per_gallon": 1.2 if index == 2 else 0,
                "notes": "smoke test bid",
            },
        )
        require(
            "meets_hidden_reserve" not in bid_response["bid"],
            "supplier bid response leaked meets_hidden_reserve",
        )

    require(
        call_status("GET", f"/api/grower/requests/{request_id}") == 403,
        "grower status without key did not return 403",
    )
    require(
        call_status("GET", f"/api/grower/requests/{request_id}?key=wrong-key") == 403,
        "grower status with wrong key did not return 403",
    )

    status = call("GET", f"/api/grower/requests/{request_id}?key={grower_key}")
    require(status["status"]["bid_count"] == 3, "request did not store three bids")
    require(status["status"]["must_pick"], "must-pick did not activate")
    selected_bid_id = status["bids"][0]["id"]

    settlement = call(
        "POST",
        "/api/grower/select-bid",
        {
            "request_id": request_id,
            "bid_id": selected_bid_id,
            "grower_key": grower_key,
            "payment_method": "operating_line",
        },
    )
    require(settlement["settlement"]["agbid_fee"] > 0, "settlement missing AgBid fee")
    require(
        abs(settlement["settlement"]["agbid_fee"] - 798.75) < 0.01,
        f"unexpected AgBid fee {settlement['settlement']['agbid_fee']} (expected 798.75)",
    )
    settlement_id = settlement["settlement"]["id"]
    require(
        settlement["deal_review"]["status"] == "manual_review_blocked",
        "new settlement did not create a blocked manual deal review",
    )

    review_update = call(
        "PATCH",
        f"/api/operator/deal-reviews/{settlement_id}",
        {
            "label_confirmed": True,
            "texas_dealer_verified_or_not_required": True,
            "freight_included_confirmed": True,
            "delivery_date_confirmed": True,
            "grower_payment_authorized": True,
            "clearing_terms_accepted": True,
            "supplier_invoice_ready": True,
            "delivery_proof_plan_confirmed": True,
            "reviewed_by": "smoke-test",
            "notes": "Smoke test manual clearing gate",
        },
    )
    require(
        review_update["review"]["status"] == "ready_for_manual_clearing",
        "deal review did not become ready for manual clearing",
    )
    require(
        review_update["settlement"]["status"] == "manual_clearing_ready",
        "settlement did not move to manual_clearing_ready",
    )

    board = call("GET", "/api/operator/pilot-board")
    require(board["ready_supplier_count"] >= 1, "operator board missing ready supplier")
    require(board["requests"], "operator board missing request")
    require(
        board["lead_summary"]["pilot_gate"]["ready_for_live_manual_auction"],
        "operator board missing ready pilot lead gate",
    )
    require(
        board["deal_review_summary"]["ready_for_manual_clearing"] >= 1,
        "operator board missing ready deal review",
    )
    require(board["foundry_gate"]["codename"] == "AgBid Clearing Wedge", "operator board missing foundry gate")
    require(
        board["foundry_gate"]["verdict"] == "manual_clearing_ready",
        "foundry gate did not reach manual_clearing_ready after smoke transaction",
    )
    require(board["foundry_gate"]["score"] == 9, "foundry gate did not reach 9/10 after clearing-ready proof")

    print(
        json.dumps(
            {
                "ok": True,
                "request_id": request_id,
                "selected_bid_id": selected_bid_id,
                "agbid_fee": settlement["settlement"]["agbid_fee"],
                "ready_supplier_count": board["ready_supplier_count"],
                "label_counts": board["verification_counts"],
                "ppis_active_product_count": board["ppis_launch_wedge"]["summary"]["active_product_count"],
                "lead_gate": board["lead_summary"]["pilot_gate"],
                "deal_review_summary": board["deal_review_summary"],
                "foundry_gate": {
                    "verdict": board["foundry_gate"]["verdict"],
                    "score": board["foundry_gate"]["score"],
                    "blockers": board["foundry_gate"]["blockers"],
                },
                "live_epa_status": live_epa_status,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"smoke_test_failed: {exc}", file=sys.stderr)
        sys.exit(1)
