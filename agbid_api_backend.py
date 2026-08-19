"""
AgBid Texas MVP API.

First-principles rule: the app is a transaction system, not a price-checking
toy. Product labels come from authoritative registration data; supplier bids
must be delivered totals; qualifying bids trigger a must-pick commitment.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from csv import DictWriter
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parent
LABEL_DB_PATH = ROOT / "agbid_label_database.json"
VERIFIED_LABEL_DB_PATH = ROOT / "agbid_label_database.verified.json"
STATE_PATH = ROOT / "agbid_market_state.json"
if os.environ.get("VERCEL"):
    STATE_PATH = Path("/tmp/agbid_market_state.json")
PPIS_INDEX_PATH = ROOT / "outputs" / "ppis_launch_wedge_index.json"
PPIS_SUMMARY_PATH = ROOT / "outputs" / "ppis_launch_wedge_summary.json"
TAKE_RATE = 0.025
AUCTION_WINDOW_HOURS = 48
STATE_LOCK = threading.RLock()

SOURCE_SYSTEMS = {
    "epa_ppls": {
        "name": "EPA Pesticide Product and Label System",
        "purpose": "Authoritative accepted label PDFs by EPA registration number.",
        "api_pattern": "https://ordspub.epa.gov/ords/pesticides/cswu/ppls/{epa_registration}",
        "reference": "https://www.epa.gov/pesticide-labels/pesticide-product-label-system-ppls-application-program-interface-api",
    },
    "epa_ppis": {
        "name": "EPA Pesticide Product Information System",
        "purpose": "Registered product, ingredient, registrant, distributor-brand, and status data.",
        "reference": "https://www.epa.gov/ingredients-used-pesticide-products/pesticide-product-information-system-ppis",
    },
    "texas_tda": {
        "name": "Texas Department of Agriculture pesticide rules",
        "purpose": "Texas dealer/applicator/license and label compliance gates.",
        "reference": "https://texasagriculture.gov/Regulatory-Programs/Pesticides",
        "dealer_reference": "https://texasagriculture.gov/Regulatory-Programs/Pesticides/Pesticide-Dealer",
    },
}

PPLS_REG_URL = "https://ordspub.epa.gov/ords/pesticides/cswu/ppls/{reg}"
PPLS_NAME_URL = (
    "https://ordspub.epa.gov/ords/pesticides/cswu/ProductSearch/"
    "partialprodsearch/v2/riname/{name}"
)
PPLS_INGREDIENT_URL = (
    "https://ordspub.epa.gov/ords/pesticides/cswu/ProductSearch/"
    "searchWithIngName/v1/{name}"
)
PPLS_PDF_URL = "https://www3.epa.gov/pesticides/chem_search/ppls/{pdf}"
PPLS_SEARCH_TIMEOUT_SECONDS = 6
PPLS_ENRICH_TIMEOUT_SECONDS = 2
PPLS_MAX_ENRICHED_CANDIDATES = 3

TEXAS_COMPLIANCE_GATES = [
    {
        "gate": "dealer_license_required_for_restricted_state_limited_regulated_herbicides",
        "source": "Texas Department of Agriculture Pesticide Dealer",
        "rule": "A person distributing state-limited-use or restricted-use pesticides or regulated herbicides must obtain a pesticide dealer license from TDA.",
        "app_check": "Supplier must provide Texas dealer license status before live restricted/state-limited/regulated-herbicide transactions.",
    },
    {
        "gate": "two_year_distribution_records",
        "source": "Texas Department of Agriculture Pesticide Dealer",
        "rule": "Records of sale or distribution for state-limited-use or restricted-use pesticides must be kept for two years.",
        "app_check": "Supplier must acknowledge two-year record retention before live transactions.",
    },
    {
        "gate": "license_per_texas_location_or_out_of_state_agent",
        "source": "Texas Department of Agriculture Pesticide Dealer",
        "rule": "A dealer must license each Texas distribution location; out-of-state dealers may use one license with a resident agent.",
        "app_check": "Supplier onboarding must capture Texas location or out-of-state/resident-agent status.",
    },
    {
        "gate": "label_and_epa_registration_on_every_bid",
        "source": "EPA PPLS / PPIS",
        "rule": "Every bid must identify the product and EPA registration number so the current accepted label can be checked.",
        "app_check": "Supplier bid form requires EPA registration number and API stores label verification status.",
    },
]

TEXAS_LAUNCH_REGIONS = [
    {
        "region": "High Plains",
        "anchor_crops": ["cotton", "corn", "sorghum", "wheat"],
        "example_cities": ["Lubbock", "Plainview", "Hereford", "Amarillo"],
    },
    {
        "region": "Blacklands / Central Texas",
        "anchor_crops": ["corn", "cotton", "wheat", "hay"],
        "example_cities": ["Waco", "Temple", "Waxahachie", "Taylor"],
    },
    {
        "region": "Coastal Bend / Rio Grande Valley",
        "anchor_crops": ["cotton", "sorghum", "corn", "vegetables"],
        "example_cities": ["Corpus Christi", "Victoria", "Harlingen", "McAllen"],
    },
]

SEED_DISTRIBUTORS = [
    {
        "id": "nutrien-lubbock",
        "name": "Nutrien Ag Solutions - Lubbock",
        "service_zips": ["794", "793", "790", "791"],
        "verified_texas_dealer": False,
        "texas_dealer_license_number": None,
        "dealer_license_expires_on": None,
        "can_sell_restricted_state_limited_or_regulated_herbicides": False,
        "records_retention_acknowledged": False,
        "contact": "recruiting-needed",
    },
    {
        "id": "helena-central-tx",
        "name": "Helena - Central Texas",
        "service_zips": ["765", "766", "767", "768"],
        "verified_texas_dealer": False,
        "texas_dealer_license_number": None,
        "dealer_license_expires_on": None,
        "can_sell_restricted_state_limited_or_regulated_herbicides": False,
        "records_retention_acknowledged": False,
        "contact": "recruiting-needed",
    },
    {
        "id": "independent-coastal-bend",
        "name": "Independent Coastal Bend Supplier",
        "service_zips": ["779", "783", "784", "785"],
        "verified_texas_dealer": False,
        "texas_dealer_license_number": None,
        "dealer_license_expires_on": None,
        "can_sell_restricted_state_limited_or_regulated_herbicides": False,
        "records_retention_acknowledged": False,
        "contact": "recruiting-needed",
    },
]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def load_label_database() -> dict[str, Any]:
    source_path = VERIFIED_LABEL_DB_PATH if VERIFIED_LABEL_DB_PATH.exists() else LABEL_DB_PATH
    if not source_path.exists():
        return {}
    with source_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_ppis_summary() -> dict[str, Any] | None:
    if not PPIS_SUMMARY_PATH.exists():
        return None
    return json.loads(PPIS_SUMMARY_PATH.read_text(encoding="utf-8"))


def load_ppis_index() -> dict[str, Any]:
    if not PPIS_INDEX_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="PPIS launch-wedge index is missing. Run scripts/build_ppis_index.py.",
        )
    return json.loads(PPIS_INDEX_PATH.read_text(encoding="utf-8"))


def active_label_source_path() -> Path:
    return VERIFIED_LABEL_DB_PATH if VERIFIED_LABEL_DB_PATH.exists() else LABEL_DB_PATH


def default_state() -> dict[str, Any]:
    return {
        "version": 1,
        "created_at": iso(now_utc()),
        "distributors": SEED_DISTRIBUTORS,
        "requests": {},
        "bid_sessions": {},
        "bids": {},
        "settlements": {},
        "deal_reviews": {},
        "label_review_candidates": {},
        "pilot_leads": {},
    }


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        state = default_state()
        save_state(state)
        return state
    with STATE_PATH.open("r", encoding="utf-8") as f:
        state = json.load(f)
    for key, value in default_state().items():
        state.setdefault(key, value)
    return state


def save_state(state: dict[str, Any]) -> None:
    payload = json.dumps(state, indent=2, sort_keys=True) + "\n"
    tmp_path = STATE_PATH.with_suffix(f"{STATE_PATH.suffix}.tmp")
    with STATE_LOCK:
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(STATE_PATH)


def fetch_epa_json(url: str, timeout: int = 8) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "AgBidTexasMVP/0.2"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


LABEL_DATABASE = load_label_database()
STATE = load_state()

app = FastAPI(
    title="AgBid Texas MVP API",
    description="Grower request, blind supplier bid, delivered total, and clearing flow for Texas crop inputs.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8888", "http://127.0.0.1:8888"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GrowerRequestCreate(BaseModel):
    grower_name: str = Field(..., min_length=2, examples=["Ben Jones Farms"])
    phone: str = Field(..., min_length=7, examples=["806-555-0101"])
    farm_county: str = Field(..., min_length=2, examples=["Lubbock"])
    delivery_zip: str = Field(..., min_length=5, max_length=10, examples=["79401"])
    product_query: str = Field(..., min_length=2, examples=["Roundup PowerMAX 3"])
    gallons: float = Field(..., ge=250, examples=[1000])
    need_by: date
    reserve_price_per_gal: float = Field(..., gt=0, examples=[32.0])
    financing_method: str = Field("operating_line", examples=["operating_line"])


class SupplierRegister(BaseModel):
    name: str = Field(..., min_length=2)
    contact: str = Field(..., min_length=3)
    service_zips: list[str] = Field(default_factory=list)
    texas_regions: list[str] = Field(default_factory=list)
    verified_texas_dealer: bool = False
    texas_dealer_license_number: Optional[str] = None
    dealer_license_expires_on: Optional[date] = None
    texas_location_or_resident_agent: Optional[str] = None
    can_sell_restricted_state_limited_or_regulated_herbicides: bool = False
    records_retention_acknowledged: bool = False
    can_include_freight_in_bid: bool = False
    accepts_agbid_as_clearing_party: bool = False
    product_lines: list[str] = Field(default_factory=list)


class SupplierBidSubmit(BaseModel):
    supplier_contact_name: str = Field(..., min_length=2)
    product_name: str = Field(..., min_length=2)
    epa_registration: str = Field(..., min_length=3)
    price_per_gallon: float = Field(..., gt=0)
    freight_total: float = Field(..., ge=0)
    delivery_date: date
    adjuvant_name: Optional[str] = None
    adjuvant_price_per_gallon: float = Field(0, ge=0)
    notes: Optional[str] = None


class SelectBid(BaseModel):
    request_id: str
    bid_id: str
    grower_key: str = Field(..., min_length=1)
    payment_method: str = Field("agbid_clearing_account")


class DealReviewUpdate(BaseModel):
    label_confirmed: bool = False
    texas_dealer_verified_or_not_required: bool = False
    freight_included_confirmed: bool = False
    delivery_date_confirmed: bool = False
    grower_payment_authorized: bool = False
    clearing_terms_accepted: bool = False
    supplier_invoice_ready: bool = False
    delivery_proof_plan_confirmed: bool = False
    reviewed_by: str = Field("operator")
    notes: Optional[str] = None


class LabelReviewCandidateCreate(BaseModel):
    product_query: str = Field(..., min_length=2)
    active_ingredient_hint: Optional[str] = None
    requested_by: str = Field("operator")
    notes: Optional[str] = None


class PilotLeadCreate(BaseModel):
    lead_type: str = Field(..., pattern="^(grower|supplier)$")
    name: str = Field(..., min_length=2)
    contact: str = Field(..., min_length=3)
    region: str = Field(..., min_length=2)
    source: str = Field("manual")
    status: str = Field("new")
    priority: str = Field("normal")
    product_interest: Optional[str] = None
    gallons: Optional[float] = Field(None, ge=0)
    delivery_zip: Optional[str] = None
    target_price_per_gal: Optional[float] = Field(None, ge=0)
    can_include_freight: bool = False
    accepts_agbid_clearing: bool = False
    texas_dealer_status: Optional[str] = None
    next_action: str = Field(..., min_length=3)
    notes: Optional[str] = None


class PilotLeadUpdate(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    next_action: Optional[str] = None
    notes: Optional[str] = None


def label_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for active_name, item in LABEL_DATABASE.items():
        for alt in item.get("generic_alternatives", []):
            records.append(
                {
                    "active_ingredient": item.get("active_ingredient", active_name),
                    "common_uses": item.get("common_uses", []),
                    "brand_name": alt.get("brand_name", ""),
                    "manufacturer": alt.get("manufacturer", ""),
                    "epa_registration": alt.get("epa_registration", ""),
                    "original_epa_registration": alt.get("original_epa_registration"),
                    "active_percentage": alt.get("active_percentage"),
                    "default_adjuvant": alt.get("default_adjuvant", ""),
                    "epa_ppls_url": alt.get("epa_verification", {}).get("ppls_registration_url")
                    or f"https://ordspub.epa.gov/ords/pesticides/cswu/ppls/{alt.get('epa_registration', '')}",
                    "epa_verification": alt.get("epa_verification", {"status": "unverified"}),
                    "label_pdf_url": alt.get("epa_verification", {}).get("pdf_url"),
                }
            )
    return records


def verification_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in label_records():
        status = record.get("epa_verification", {}).get("status", "unverified")
        counts[status] = counts.get(status, 0) + 1
    return counts


def normalized_text(text: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in text).split())


def ppis_product_search_text(product: dict[str, Any]) -> str:
    parts = [
        product.get("product_name", ""),
        product.get("epa_registration", ""),
        " ".join(product.get("launch_groups", [])),
    ]
    parts.extend(item.get("name", "") for item in product.get("active_ingredients", []))
    parts.extend(item.get("name", "") for item in product.get("alternate_product_names", []))
    parts.extend(item.get("name", "") for item in product.get("distributor_product_names", []))
    return normalized_text(" ".join(parts))


def latest_pdf_url(ppls_item: dict[str, Any]) -> str | None:
    pdfs = ppls_item.get("pdffiles") or []
    if not pdfs:
        return None
    return PPLS_PDF_URL.format(pdf=pdfs[0].get("pdffile"))


def candidate_from_name_item(item: dict[str, Any]) -> dict[str, Any]:
    registration = item.get("eparegno") or item.get("eparegnumber") or ""
    return {
        "product_name": item.get("productname") or "",
        "epa_registration": registration,
        "product_status": item.get("product_status")
        or item.get("registrationstatus")
        or item.get("productnamestatus"),
        "alternate_brand_name": item.get("altrntbrndnames") or item.get("alternatebrandname"),
        "ppls_registration_url": PPLS_REG_URL.format(reg=urllib.parse.quote(registration)),
        "source": "epa_ppls_product_search",
    }


def enrich_candidate_with_registration(
    candidate: dict[str, Any],
    timeout: int = PPLS_ENRICH_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    registration = candidate.get("epa_registration", "")
    if not registration:
        candidate["label_gate"] = {"status": "not_found", "action": "manual_label_review_required"}
        return candidate
    try:
        payload = fetch_epa_json(PPLS_REG_URL.format(reg=urllib.parse.quote(registration)), timeout=timeout)
        items = payload.get("items") or []
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        candidate["lookup_error"] = str(exc)
        items = []
    if not items:
        candidate["label_gate"] = {"status": "not_found", "action": "manual_label_review_required"}
        return candidate

    item = items[0]
    candidate.update(
        {
            "registration_lookup_product_name": item.get("productname"),
            "cancel_flag": item.get("cancel_flag"),
            "rup": item.get("rup_yn"),
            "formulations": item.get("formulations", []),
            "active_ingredients": item.get("active_ingredients", []),
            "label_pdf_url": latest_pdf_url(item),
            "companyinfo": item.get("companyinfo", []),
        }
    )
    is_active = str(candidate.get("product_status") or item.get("product_status") or "").lower() in {
        "active",
        "registered",
    }
    if item.get("cancel_flag") == "Yes":
        is_active = False
    candidate["label_gate"] = (
        {"status": "epa_active_match", "action": "operator_review_then_pilot_allowed"}
        if is_active
        else {"status": "inactive_or_cancelled", "action": "do_not_use_without_manual_review"}
    )
    return candidate


def live_epa_product_search(query: str, mode: str = "product") -> dict[str, Any]:
    query = query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Search query is required.")
    if mode == "ingredient":
        url = PPLS_INGREDIENT_URL.format(name=urllib.parse.quote(query))
    else:
        url = PPLS_NAME_URL.format(name=urllib.parse.quote(query))
    try:
        payload = fetch_epa_json(url, timeout=PPLS_SEARCH_TIMEOUT_SECONDS)
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"EPA lookup failed: {exc}") from exc

    raw_items = payload.get("items") or []
    candidates = [candidate_from_name_item(item) for item in raw_items[:20]]
    enriched = [
        enrich_candidate_with_registration(candidate)
        for candidate in candidates[:PPLS_MAX_ENRICHED_CANDIDATES]
    ]
    return {
        "query": query,
        "mode": mode,
        "source_url": url,
        "count": len(raw_items),
        "candidates": enriched,
        "operator_rule": "Use live EPA matches to create review candidates; do not auto-approve a live transaction without label and Texas compliance review.",
    }


def match_product(query: str) -> dict[str, Any]:
    needle = query.strip().lower()
    if not needle:
        raise HTTPException(status_code=400, detail="Product search is required.")

    ranked: list[tuple[int, dict[str, Any]]] = []
    for record in label_records():
        haystack = " ".join(
            [
                record["active_ingredient"],
                record["brand_name"],
                record["manufacturer"],
                record["epa_registration"],
            ]
        ).lower()
        if needle in haystack:
            score = 0
            if needle == record["brand_name"].lower():
                score += 100
            if needle in record["brand_name"].lower():
                score += 50
            if needle in record["active_ingredient"].lower():
                score += 25
            ranked.append((score, record))

    if not ranked:
        raise HTTPException(status_code=404, detail=f"No seeded EPA-label match for '{query}'.")

    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked[0][1]


def label_gate(product: dict[str, Any]) -> dict[str, str]:
    status = product.get("epa_verification", {}).get("status", "unverified")
    if status == "verified":
        return {"status": "verified", "action": "pilot_allowed"}
    if status == "registration_mismatch_suggested_fix":
        return {"status": status, "action": "pilot_allowed_after_manual_confirmation"}
    return {"status": status, "action": "manual_label_review_required_before_live_transaction"}


def supplier_readiness(supplier: dict[str, Any]) -> dict[str, Any]:
    missing: list[str] = []
    if not supplier.get("service_zips"):
        missing.append("service ZIP prefixes")
    if not supplier.get("can_include_freight_in_bid"):
        missing.append("freight-included bid commitment")
    if not supplier.get("accepts_agbid_as_clearing_party"):
        missing.append("AgBid clearing-party acceptance")
    if supplier.get("can_sell_restricted_state_limited_or_regulated_herbicides"):
        if not supplier.get("verified_texas_dealer"):
            missing.append("verified Texas pesticide dealer status")
        if not supplier.get("texas_dealer_license_number"):
            missing.append("Texas dealer license number")
        if not supplier.get("records_retention_acknowledged"):
            missing.append("two-year distribution record retention acknowledgement")

    status = "pilot_ready" if not missing else "recruiting_needed"
    if (
        supplier.get("can_include_freight_in_bid")
        and supplier.get("accepts_agbid_as_clearing_party")
        and not supplier.get("can_sell_restricted_state_limited_or_regulated_herbicides")
    ):
        status = "general_use_pilot_ready"
    return {
        "status": status,
        "missing": missing,
        "can_bid_general_use_pilots": supplier.get("can_include_freight_in_bid")
        and supplier.get("accepts_agbid_as_clearing_party"),
        "can_bid_restricted_state_limited_regulated": supplier.get("verified_texas_dealer")
        and supplier.get("texas_dealer_license_number")
        and supplier.get("records_retention_acknowledged"),
    }


def lead_summary() -> dict[str, Any]:
    leads = list(STATE["pilot_leads"].values())
    by_type: dict[str, int] = {"grower": 0, "supplier": 0}
    by_status: dict[str, int] = {}
    real_grower_leads = 0
    real_supplier_leads = 0
    for lead in leads:
        lead_type = lead.get("lead_type", "unknown")
        if lead_type in by_type:
            by_type[lead_type] += 1
        status = lead.get("status", "new")
        by_status[status] = by_status.get(status, 0) + 1
        if lead_type == "grower" and lead.get("product_interest") and lead.get("gallons"):
            real_grower_leads += 1
        if (
            lead_type == "supplier"
            and lead.get("can_include_freight")
            and lead.get("accepts_agbid_clearing")
        ):
            real_supplier_leads += 1
    return {
        "total": len(leads),
        "by_type": by_type,
        "by_status": by_status,
        "real_grower_leads": real_grower_leads,
        "real_supplier_leads": real_supplier_leads,
        "pilot_gate": {
            "grower_ready": real_grower_leads >= 1,
            "supplier_ready": real_supplier_leads >= 3,
            "ready_for_live_manual_auction": real_grower_leads >= 1 and real_supplier_leads >= 3,
        },
    }


def store_pilot_lead(data: dict[str, Any]) -> dict[str, Any]:
    lead_id = f"lead-{uuid.uuid4().hex[:12]}"
    timestamp = iso(now_utc())
    lead = {
        "lead_type": data.get("lead_type"),
        "name": data.get("name"),
        "contact": data.get("contact"),
        "region": data.get("region"),
        "source": data.get("source", "manual"),
        "status": data.get("status", "new"),
        "priority": data.get("priority", "normal"),
        "product_interest": data.get("product_interest"),
        "gallons": data.get("gallons"),
        "delivery_zip": data.get("delivery_zip"),
        "target_price_per_gal": data.get("target_price_per_gal"),
        "can_include_freight": bool(data.get("can_include_freight", False)),
        "accepts_agbid_clearing": bool(data.get("accepts_agbid_clearing", False)),
        "texas_dealer_status": data.get("texas_dealer_status"),
        "next_action": data.get("next_action"),
        "notes": data.get("notes"),
        "id": lead_id,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    STATE["pilot_leads"][lead_id] = lead
    return lead


def sorted_leads() -> list[dict[str, Any]]:
    leads = list(STATE["pilot_leads"].values())
    leads.sort(key=lambda item: item.get("updated_at") or item.get("created_at"), reverse=True)
    return leads


def leads_as_csv(leads: list[dict[str, Any]]) -> str:
    fieldnames = [
        "id",
        "lead_type",
        "name",
        "contact",
        "region",
        "source",
        "status",
        "priority",
        "product_interest",
        "gallons",
        "delivery_zip",
        "target_price_per_gal",
        "can_include_freight",
        "accepts_agbid_clearing",
        "texas_dealer_status",
        "next_action",
        "notes",
        "created_at",
        "updated_at",
    ]
    output = StringIO()
    writer = DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(leads)
    return output.getvalue()


DEAL_REVIEW_GATES = [
    "label_confirmed",
    "texas_dealer_verified_or_not_required",
    "freight_included_confirmed",
    "delivery_date_confirmed",
    "grower_payment_authorized",
    "clearing_terms_accepted",
    "supplier_invoice_ready",
    "delivery_proof_plan_confirmed",
]


def get_settlement_bundle(settlement_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    settlement = STATE["settlements"].get(settlement_id)
    if not settlement:
        raise HTTPException(status_code=404, detail="Settlement not found.")
    request = STATE["requests"].get(settlement["request_id"])
    bid = STATE["bids"].get(settlement["bid_id"])
    if not request or not bid:
        raise HTTPException(status_code=404, detail="Settlement request or bid is missing.")
    supplier = next(
        (item for item in STATE["distributors"] if item.get("id") == bid.get("distributor_id")),
        None,
    )
    return settlement, request, bid, supplier


def deal_review_status(review: dict[str, Any]) -> str:
    missing = [gate for gate in DEAL_REVIEW_GATES if not review.get(gate)]
    review["missing_gates"] = missing
    if missing:
        return "manual_review_blocked"
    return "ready_for_manual_clearing"


def create_initial_deal_review(settlement: dict[str, Any], request: dict[str, Any], bid: dict[str, Any]) -> dict[str, Any]:
    timestamp = iso(now_utc())
    review = {
        "id": f"review-{uuid.uuid4().hex[:12]}",
        "settlement_id": settlement["id"],
        "request_id": request["id"],
        "bid_id": bid["id"],
        "created_at": timestamp,
        "updated_at": timestamp,
        "reviewed_by": None,
        "notes": None,
        "label_gate_status": (request.get("label_gate") or {}).get("status"),
        "epa_registration": bid.get("epa_registration"),
        "product_name": bid.get("product_name"),
        "supplier_name": bid.get("distributor_name"),
        "total_due_from_grower": settlement.get("total_due_from_grower"),
        "supplier_payout_pending_delivery_proof": settlement.get("supplier_payout_pending_delivery_proof"),
    }
    for gate in DEAL_REVIEW_GATES:
        review[gate] = False
    review["status"] = deal_review_status(review)
    return review


def deal_review_summary() -> dict[str, Any]:
    reviews = list(STATE["deal_reviews"].values())
    by_status: dict[str, int] = {}
    for review in reviews:
        status = review.get("status", "manual_review_blocked")
        by_status[status] = by_status.get(status, 0) + 1
    return {
        "total": len(reviews),
        "by_status": by_status,
        "ready_for_manual_clearing": by_status.get("ready_for_manual_clearing", 0),
        "blocked": by_status.get("manual_review_blocked", 0),
    }


def sorted_deal_reviews() -> list[dict[str, Any]]:
    reviews = list(STATE["deal_reviews"].values())
    reviews.sort(key=lambda item: item.get("updated_at") or item.get("created_at"), reverse=True)
    return reviews


def foundry_gate() -> dict[str, Any]:
    leads = lead_summary()
    pilot_gate = leads["pilot_gate"]
    deals = deal_review_summary()
    requests = list(STATE["requests"].values())
    bids = list(STATE["bids"].values())
    settlements = list(STATE["settlements"].values())
    open_requests = [request for request in requests if request.get("status") == "open"]
    requests_with_bids = {
        bid["request_id"]
        for bid in bids
        if STATE["requests"].get(bid.get("request_id"))
    }
    must_pick_requests = [
        request
        for request in requests
        if request_status(
            request,
            [bid for bid in bids if bid["request_id"] == request["id"]],
        )["must_pick"]
    ]

    distribution_ready = pilot_gate["ready_for_live_manual_auction"]
    transaction_started = bool(open_requests or settlements)
    transaction_proof = bool(must_pick_requests or settlements)
    cash_flow_ready = deals["ready_for_manual_clearing"] > 0

    if cash_flow_ready:
        verdict = "manual_clearing_ready"
    elif transaction_proof:
        verdict = "transaction_proof_running"
    elif distribution_ready:
        verdict = "field_test_ready"
    else:
        verdict = "demo_mode"

    gates = [
        {
            "gate": "G1 Structural moat",
            "mechanism": "EPA label and active-ingredient transaction graph",
            "status": "software_ready",
            "evidence": "Verified-label database and PPIS launch-wedge index are wired into product search and operator review.",
            "proof_needed": "Repeated live requests must create proprietary price, freight, timing, and supplier reliability data.",
        },
        {
            "gate": "G2 Bypass prevention",
            "mechanism": "Must-pick commitment plus AgBid clearing",
            "status": "field_proof_required" if not transaction_proof else "active",
            "evidence": f"{len(must_pick_requests)} open request(s) currently force pick-after-qualifying-bid behavior; {len(settlements)} settlement(s) created.",
            "proof_needed": "A grower must accept the rule on a real purchase instead of using AgBid as a free price check.",
        },
        {
            "gate": "G3 Incumbent vulnerability",
            "mechanism": "Distributor channel conflict",
            "status": "reasonable_inference",
            "evidence": "Incumbents benefit from opaque local relationships and cannot easily run neutral blind clearing without angering channel partners.",
            "proof_needed": "Supplier interviews must confirm they will bid through AgBid for incremental volume.",
        },
        {
            "gate": "G4 Distribution architecture",
            "mechanism": "Grower request recruits suppliers; supplier commitments unlock the first manual auction",
            "status": "ready" if distribution_ready else "blocked",
            "evidence": f"{leads['real_grower_leads']} real grower ask(s), {leads['real_supplier_leads']} supplier bid commitment(s).",
            "proof_needed": "Minimum live gate is 1 committed grower request and 3 suppliers willing to bid freight-included through AgBid.",
        },
        {
            "gate": "G5 Cash-flow proof",
            "mechanism": "Manual clearing review before payment capture and supplier payout",
            "status": "ready" if cash_flow_ready else "blocked",
            "evidence": f"{deals['ready_for_manual_clearing']} deal(s) ready for manual clearing; {len(settlements)} settlement(s) created.",
            "proof_needed": "First buyer payment authorization and supplier invoice must clear manually.",
        },
    ]

    blockers = [
        gate["gate"]
        for gate in gates
        if gate["status"] in {"blocked", "field_proof_required"}
    ]
    next_actions = []
    if not distribution_ready:
        next_actions.append("Qualify 1 grower with product, gallons, ZIP, and target price, then qualify 3 suppliers for freight-included AgBid clearing.")
    if distribution_ready and not transaction_started:
        next_actions.append("Run the first real grower request through supplier bid links within the 48-hour window.")
    if transaction_started and not transaction_proof:
        next_actions.append("Get at least one delivered bid at or below the hidden reserve so the must-pick rule activates.")
    if transaction_proof and not cash_flow_ready:
        next_actions.append("Finish the deal desk checklist: label, Texas dealer status, freight, payment authorization, terms, invoice, and delivery proof.")
    if cash_flow_ready:
        next_actions.append("Manually clear the first transaction only after legal/payment/compliance approval.")

    return {
        "codename": "AgBid Clearing Wedge",
        "verdict": verdict,
        "score": 9 if cash_flow_ready else 8 if distribution_ready else 6,
        "evidence_standard": "Do not count this as launched until a real grower and real suppliers complete a live, freight-included, must-pick transaction.",
        "distribution_ready": distribution_ready,
        "transaction_proof_running": transaction_proof,
        "cash_flow_ready": cash_flow_ready,
        "request_count": len(requests),
        "request_with_bid_count": len(requests_with_bids),
        "settlement_count": len(settlements),
        "blockers": blockers,
        "gates": gates,
        "next_actions": next_actions,
    }


def distributor_matches(zip_code: str) -> list[dict[str, Any]]:
    prefix3 = zip_code[:3]
    matches = [
        d for d in STATE["distributors"] if prefix3 in {z[:3] for z in d.get("service_zips", [])}
    ]
    if len(matches) >= 3:
        return matches
    seen = {d["id"] for d in matches}
    for distributor in STATE["distributors"]:
        if distributor["id"] not in seen:
            matches.append(distributor)
            seen.add(distributor["id"])
        if len(matches) >= 3:
            break
    return matches


def request_status(request: dict[str, Any], bids: list[dict[str, Any]]) -> dict[str, Any]:
    reserve = request["reserve_price_per_gal"]
    qualifying = [b for b in bids if b["delivered_price_per_gallon"] <= reserve]
    return {
        "bid_count": len(bids),
        "has_qualifying_bid": bool(qualifying),
        "must_pick": bool(qualifying) and request["status"] == "open",
        "lowest_delivered_price_per_gallon": min(
            [b["delivered_price_per_gallon"] for b in bids], default=None
        ),
        "reserve_price_per_gal": reserve,
        "closes_at": request["closes_at"],
    }


def public_request_summary(request: dict[str, Any]) -> dict[str, Any]:
    bids = [b for b in STATE["bids"].values() if b["request_id"] == request["id"]]
    return {
        "id": request["id"],
        "grower_name": request["grower_name"],
        "farm_county": request["farm_county"],
        "delivery_zip": request["delivery_zip"],
        "active_ingredient": request["active_ingredient"],
        "matched_product": request["matched_product"],
        "label_gate": request.get("label_gate"),
        "gallons": request["gallons"],
        "need_by": request["need_by"],
        "status": request["status"],
        "created_at": request["created_at"],
        "closes_at": request["closes_at"],
        "bid_status": request_status(request, bids),
    }


@app.get("/")
def read_root() -> dict[str, Any]:
    return {
        "status": "online",
        "service": "AgBid Texas MVP",
        "take_rate": TAKE_RATE,
        "auction_window_hours": AUCTION_WINDOW_HOURS,
        "source_systems": SOURCE_SYSTEMS,
        "texas_compliance_gates": TEXAS_COMPLIANCE_GATES,
    }


@app.get("/api/labels/source-plan")
def label_source_plan() -> dict[str, Any]:
    ppis_summary = load_ppis_summary()
    return {
        "principle": "Use official registration data first; use CDMS/Agrian only as licensed enrichment, not as the canonical scraped source.",
        "systems": SOURCE_SYSTEMS,
        "texas_compliance_gates": TEXAS_COMPLIANCE_GATES,
        "active_label_database": str(active_label_source_path()),
        "seeded_records": len(label_records()),
        "seeded_active_ingredients": sorted(LABEL_DATABASE.keys()),
        "verification_counts": verification_counts(),
        "ppis_launch_wedge": ppis_summary,
        "next_ingestion_step": "Pull EPA PPIS product files, normalize active ingredients and distributor brand names, then call PPLS by EPA registration number for label URLs.",
    }


@app.get("/api/labels/verification-report")
def label_verification_report() -> dict[str, Any]:
    report_path = ROOT / "outputs" / "label_verification_report.json"
    report = []
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    return {
        "active_label_database": str(active_label_source_path()),
        "report_path": str(report_path),
        "verification_counts": verification_counts(),
        "records": report,
    }


@app.get("/api/labels/ppis-summary")
def ppis_summary() -> dict[str, Any]:
    summary = load_ppis_summary()
    if not summary:
        raise HTTPException(
            status_code=404,
            detail="PPIS launch-wedge summary is missing. Run scripts/build_ppis_index.py.",
        )
    return summary


@app.get("/api/labels/ppis-products")
def ppis_products(
    q: str = "",
    ingredient: str = "",
    active_only: bool = True,
    limit: int = 50,
) -> dict[str, Any]:
    index = load_ppis_index()
    limit = max(1, min(limit, 100))
    query = normalized_text(q)
    ingredient_query = normalized_text(ingredient)
    matched: list[dict[str, Any]] = []
    for product in index.get("products", []):
        if active_only and product.get("product_status") != "Active":
            continue
        if ingredient_query and ingredient_query not in normalized_text(
            " ".join(product.get("launch_groups", []))
        ):
            continue
        if query and query not in ppis_product_search_text(product):
            continue
        matched.append(product)
        if len(matched) >= limit:
            break
    return {
        "source": index.get("source"),
        "summary": index.get("summary"),
        "count_returned": len(matched),
        "limit": limit,
        "products": matched,
        "operator_rule": "Use PPIS for product identity and active-ingredient parity; still confirm the current PPLS label and Texas gates before clearing a transaction.",
    }


@app.get("/api/labels/live-search")
def labels_live_search(q: str, mode: str = "product") -> dict[str, Any]:
    if mode not in {"product", "ingredient"}:
        raise HTTPException(status_code=400, detail="mode must be 'product' or 'ingredient'.")
    return live_epa_product_search(q, mode=mode)


@app.get("/api/labels/review-candidates")
def label_review_candidates() -> dict[str, Any]:
    candidates = list(STATE["label_review_candidates"].values())
    candidates.sort(key=lambda item: item["created_at"], reverse=True)
    return {"count": len(candidates), "candidates": candidates}


@app.post("/api/labels/review-candidates")
def create_label_review_candidate(payload: LabelReviewCandidateCreate) -> dict[str, Any]:
    with STATE_LOCK:
        candidate_id = f"label-{uuid.uuid4().hex[:12]}"
        candidate = {
            "id": candidate_id,
            "created_at": iso(now_utc()),
            "product_query": payload.product_query,
            "active_ingredient_hint": payload.active_ingredient_hint,
            "requested_by": payload.requested_by,
            "notes": payload.notes,
            "status": "manual_review_required",
            "live_lookup": {
                "query": payload.product_query,
                "status": "not_run",
                "operator_endpoint": f"/api/labels/live-search?q={urllib.parse.quote(payload.product_query)}",
            },
            "recommended_next_action": "Pick the correct EPA registration, confirm current label/Texas sale gates, then add it to the verified label database if appropriate.",
        }
        STATE["label_review_candidates"][candidate_id] = candidate
        save_state(STATE)
    return {"candidate": candidate}


@app.get("/api/products")
def search_products(q: str = "") -> dict[str, Any]:
    records = label_records()
    if q:
        needle = q.lower()
        records = [
            r
            for r in records
            if needle
            in " ".join(
                [r["active_ingredient"], r["brand_name"], r["manufacturer"], r["epa_registration"]]
            ).lower()
        ]
    return {"count": len(records), "products": records[:50]}


@app.get("/api/parity/lookup")
def parity_lookup(ingredient_name: str) -> dict[str, Any]:
    match = match_product(ingredient_name)
    active = match["active_ingredient"]
    return {
        "matched": match,
        "active_ingredient_group": LABEL_DATABASE.get(active, {}),
        "source_systems": ["epa_ppis", "epa_ppls"],
    }


@app.post("/api/suppliers/register")
def register_supplier(supplier: SupplierRegister) -> dict[str, Any]:
    with STATE_LOCK:
        supplier_id = f"supplier-{uuid.uuid4().hex[:10]}"
        record = supplier.model_dump(mode="json")
        record["id"] = supplier_id
        STATE["distributors"].append(record)
        readiness = supplier_readiness(record)
        lead = store_pilot_lead(
            {
                "lead_type": "supplier",
                "name": record["name"],
                "contact": record["contact"],
                "region": ", ".join(record.get("texas_regions") or []) or "Texas",
                "source": "supplier_onboarding",
                "status": "pilot_ready"
                if readiness["can_bid_general_use_pilots"]
                or readiness["can_bid_restricted_state_limited_regulated"]
                else "new",
                "product_interest": ", ".join(record.get("product_lines") or []),
                "can_include_freight": record.get("can_include_freight_in_bid", False),
                "accepts_agbid_clearing": record.get("accepts_agbid_as_clearing_party", False),
                "texas_dealer_status": "verified"
                if record.get("verified_texas_dealer")
                else "manual verification needed",
                "next_action": "Send first blind bid invite"
                if readiness["can_bid_general_use_pilots"]
                or readiness["can_bid_restricted_state_limited_regulated"]
                else "Finish freight, clearing, and Texas readiness review",
                "notes": "; ".join(readiness.get("missing") or []),
            }
        )
        save_state(STATE)
    return {"supplier": record, "readiness": readiness, "pilot_lead": lead}


@app.get("/api/suppliers")
def list_suppliers() -> dict[str, Any]:
    suppliers = []
    for supplier in STATE["distributors"]:
        suppliers.append({**supplier, "readiness": supplier_readiness(supplier)})
    return {"count": len(suppliers), "suppliers": suppliers}


@app.get("/api/operator/leads")
def list_pilot_leads(lead_type: str = "", status: str = "") -> dict[str, Any]:
    leads = sorted_leads()
    if lead_type:
        leads = [lead for lead in leads if lead.get("lead_type") == lead_type]
    if status:
        leads = [lead for lead in leads if lead.get("status") == status]
    return {"summary": lead_summary(), "count": len(leads), "leads": leads}


@app.post("/api/operator/leads")
def create_pilot_lead(payload: PilotLeadCreate) -> dict[str, Any]:
    with STATE_LOCK:
        lead = store_pilot_lead(payload.model_dump(mode="json"))
        save_state(STATE)
    return {"lead": lead, "summary": lead_summary()}


@app.patch("/api/operator/leads/{lead_id}")
def update_pilot_lead(lead_id: str, payload: PilotLeadUpdate) -> dict[str, Any]:
    with STATE_LOCK:
        lead = STATE["pilot_leads"].get(lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Pilot lead not found.")
        updates = payload.model_dump(exclude_none=True)
        lead.update(updates)
        lead["updated_at"] = iso(now_utc())
        save_state(STATE)
    return {"lead": lead, "summary": lead_summary()}


@app.get("/api/operator/leads/export")
def export_pilot_leads(lead_type: str = "", status: str = "") -> Response:
    leads = sorted_leads()
    if lead_type:
        leads = [lead for lead in leads if lead.get("lead_type") == lead_type]
    if status:
        leads = [lead for lead in leads if lead.get("status") == status]
    return Response(
        content=leads_as_csv(leads),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=agbid_pilot_leads.csv"},
    )


@app.get("/api/operator/deal-reviews")
def list_deal_reviews(status: str = "") -> dict[str, Any]:
    reviews = sorted_deal_reviews()
    if status:
        reviews = [review for review in reviews if review.get("status") == status]
    return {"summary": deal_review_summary(), "count": len(reviews), "reviews": reviews}


@app.get("/api/operator/deal-reviews/{settlement_id}")
def get_deal_review(settlement_id: str) -> dict[str, Any]:
    review = STATE["deal_reviews"].get(settlement_id)
    if not review:
        raise HTTPException(status_code=404, detail="Deal review not found.")
    settlement, request, bid, supplier = get_settlement_bundle(settlement_id)
    return {
        "review": review,
        "settlement": settlement,
        "request": public_request_summary(request),
        "selected_bid": bid,
        "supplier": supplier,
    }


@app.patch("/api/operator/deal-reviews/{settlement_id}")
def update_deal_review(settlement_id: str, payload: DealReviewUpdate) -> dict[str, Any]:
    with STATE_LOCK:
        review = STATE["deal_reviews"].get(settlement_id)
        if not review:
            raise HTTPException(status_code=404, detail="Deal review not found.")
        updates = payload.model_dump()
        review.update(updates)
        review["updated_at"] = iso(now_utc())
        review["status"] = deal_review_status(review)
        settlement = STATE["settlements"].get(settlement_id)
        if settlement:
            settlement["review_status"] = review["status"]
            if review["status"] == "ready_for_manual_clearing":
                settlement["status"] = "manual_clearing_ready"
            else:
                settlement["status"] = "payment_authorization_required"
        save_state(STATE)
    return {"review": review, "summary": deal_review_summary(), "settlement": settlement}


@app.post("/api/grower/requests")
def create_grower_request(payload: GrowerRequestCreate, http_request: Request) -> dict[str, Any]:
    with STATE_LOCK:
        product = match_product(payload.product_query)
        request_id = f"req-{uuid.uuid4().hex[:12]}"
        created_at = now_utc()
        closes_at = created_at + timedelta(hours=AUCTION_WINDOW_HOURS)
        request = payload.model_dump(mode="json")
        grower_key = secrets.token_urlsafe(18)
        request.update(
            {
                "id": request_id,
                "grower_key": grower_key,
                "status": "open",
                "created_at": iso(created_at),
                "closes_at": iso(closes_at),
                "matched_product": product,
                "label_gate": label_gate(product),
                "active_ingredient": product["active_ingredient"],
            }
        )
        STATE["requests"][request_id] = request
        grower_lead = store_pilot_lead(
            {
                "lead_type": "grower",
                "name": payload.grower_name,
                "contact": payload.phone,
                "region": payload.farm_county,
                "source": "grower_request",
                "status": "qualified",
                "product_interest": payload.product_query,
                "gallons": payload.gallons,
                "delivery_zip": payload.delivery_zip,
                "target_price_per_gal": payload.reserve_price_per_gal,
                "next_action": "Run supplier bids and complete deal review if awarded",
                "notes": f"Request {request_id}; financing: {payload.financing_method}",
            }
        )

        base_url = str(http_request.base_url).rstrip("/")
        sessions = []
        for distributor in distributor_matches(payload.delivery_zip):
            token = secrets.token_urlsafe(18)
            session = {
                "token": token,
                "request_id": request_id,
                "distributor_id": distributor["id"],
                "distributor_name": distributor["name"],
                "created_at": iso(created_at),
                "expires_at": iso(closes_at),
                "submitted": False,
                "bid_url": f"{base_url}/supplier_bid.html?token={token}",
            }
            STATE["bid_sessions"][token] = session
            sessions.append(
                {
                    "distributor_id": distributor["id"],
                    "distributor_name": distributor["name"],
                    "bid_url": f"{base_url}/supplier_bid.html?token={token}",
                    "api_url": f"{base_url}/api/supplier/bid/{token}",
                }
            )

        save_state(STATE)
    return {
        "request": request,
        "grower_key": grower_key,
        "pilot_lead": grower_lead,
        "supplier_invites": sessions,
        "must_pick_rule": "If any delivered bid is at or below the hidden reserve, the grower must select a bid or pay the market-integrity fee.",
    }


@app.get("/api/grower/requests/{request_id}")
def get_grower_request(request_id: str, key: str = "") -> dict[str, Any]:
    request = STATE["requests"].get(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found.")
    stored_key = request.get("grower_key")
    if not stored_key or not key or not secrets.compare_digest(key, stored_key):
        raise HTTPException(status_code=403, detail="A valid access key is required to view this request.")
    bids = [b for b in STATE["bids"].values() if b["request_id"] == request_id]
    bids.sort(key=lambda b: (b["delivered_total"], b["delivery_date"]))
    return {"request": request, "bids": bids, "status": request_status(request, bids)}


@app.get("/api/operator/pilot-board")
def pilot_board() -> dict[str, Any]:
    requests = []
    for r in STATE["requests"].values():
        summary = public_request_summary(r)
        invites = []
        for session in STATE["bid_sessions"].values():
            if session.get("request_id") != r["id"]:
                continue
            bid = STATE["bids"].get(session.get("bid_id", ""))
            bid_summary = None
            if bid:
                bid_summary = {
                    "id": bid["id"],
                    "delivered_total": bid["delivered_total"],
                    "delivered_price_per_gallon": bid["delivered_price_per_gallon"],
                    "freight_total": bid["freight_total"],
                    "delivery_date": bid["delivery_date"],
                    "submitted_at": bid["submitted_at"],
                }
            invites.append(
                {
                    "supplier_name": session["distributor_name"],
                    "bid_url": session.get("bid_url") or f"/supplier_bid.html?token={session['token']}",
                    "submitted": bool(session.get("submitted")),
                    "bid": bid_summary,
                }
            )
        summary["invites"] = invites
        requests.append(summary)
    requests.sort(key=lambda item: item["created_at"], reverse=True)
    suppliers = [{**s, "readiness": supplier_readiness(s)} for s in STATE["distributors"]]
    ready_suppliers = [
        s
        for s in suppliers
        if s["readiness"]["can_bid_general_use_pilots"]
        or s["readiness"]["can_bid_restricted_state_limited_regulated"]
    ]
    return {
        "label_database": str(active_label_source_path()),
        "verification_counts": verification_counts(),
        "ppis_launch_wedge": load_ppis_summary(),
        "label_review_candidate_count": len(STATE["label_review_candidates"]),
        "lead_summary": lead_summary(),
        "foundry_gate": foundry_gate(),
        "recent_leads": sorted_leads()[:10],
        "deal_review_summary": deal_review_summary(),
        "recent_deal_reviews": sorted_deal_reviews()[:10],
        "texas_compliance_gates": TEXAS_COMPLIANCE_GATES,
        "requests": requests,
        "supplier_count": len(suppliers),
        "ready_supplier_count": len(ready_suppliers),
        "suppliers": suppliers,
        "next_actions": [
            "Register at least three suppliers that accept freight-included blind bids and AgBid clearing.",
            "Manually confirm labels for products marked needs_manual_review before live transactions.",
            "Verify Texas dealer status before restricted-use, state-limited-use, or regulated herbicide transactions.",
            "Complete the deal review checklist before taking payment or clearing supplier payout.",
            "Run one real grower request with a hidden reserve and require bid selection if reserve is beaten.",
        ],
    }


@app.get("/api/operator/foundry-gate")
def operator_foundry_gate() -> dict[str, Any]:
    return foundry_gate()


@app.get("/api/supplier/bid/{token}")
def get_supplier_bid_session(token: str) -> dict[str, Any]:
    session = STATE["bid_sessions"].get(token)
    if not session:
        raise HTTPException(status_code=404, detail="Invalid or expired bid link.")
    request = STATE["requests"].get(session["request_id"])
    if not request:
        raise HTTPException(status_code=404, detail="Request not found.")
    return {
        "session": session,
        "request": {
            "active_ingredient": request["active_ingredient"],
            "matched_product": request["matched_product"],
            "gallons": request["gallons"],
            "need_by": request["need_by"].isoformat() if isinstance(request["need_by"], date) else request["need_by"],
            "delivery_zip": request["delivery_zip"],
            "farm_county": request["farm_county"],
            "closes_at": request["closes_at"],
        },
        "blind_bid_rule": "You cannot see other supplier bids or the grower's hidden reserve.",
    }


@app.post("/api/supplier/bid/{token}")
def submit_supplier_bid(token: str, bid: SupplierBidSubmit) -> dict[str, Any]:
    with STATE_LOCK:
        session = STATE["bid_sessions"].get(token)
        if not session:
            raise HTTPException(status_code=404, detail="Invalid or expired bid link.")
        if session["submitted"]:
            raise HTTPException(status_code=400, detail="This supplier link already submitted a bid.")

        request = STATE["requests"].get(session["request_id"])
        if not request or request["status"] != "open":
            raise HTTPException(status_code=400, detail="This request is no longer open.")

        if now_utc() > datetime.fromisoformat(request["closes_at"].replace("Z", "+00:00")):
            request["status"] = "expired"
            save_state(STATE)
            raise HTTPException(status_code=400, detail="The 48-hour bid window has closed.")

        need_by = request.get("need_by")
        if need_by and bid.delivery_date:
            need_by_date = need_by if isinstance(need_by, date) else date.fromisoformat(str(need_by)[:10])
            if bid.delivery_date > need_by_date:
                raise HTTPException(
                    status_code=400,
                    detail="That delivery date is after the date the farmer needs the product. Please pick a delivery date on or before the need-by date.",
                )

        gallons = float(request["gallons"])
        product_total = bid.price_per_gallon * gallons
        adjuvant_total = bid.adjuvant_price_per_gallon * gallons
        delivered_total = product_total + bid.freight_total
        bundle_total = delivered_total + adjuvant_total
        delivered_price_per_gallon = delivered_total / gallons
        bundle_price_per_gallon = bundle_total / gallons
        bid_id = f"bid-{uuid.uuid4().hex[:12]}"

        record = bid.model_dump(mode="json")
        record.update(
            {
                "id": bid_id,
                "request_id": request["id"],
                "distributor_id": session["distributor_id"],
                "distributor_name": session["distributor_name"],
                "submitted_at": iso(now_utc()),
                "product_total": round(product_total, 2),
                "freight_total": round(bid.freight_total, 2),
                "adjuvant_total": round(adjuvant_total, 2),
                "delivered_total": round(delivered_total, 2),
                "bundle_total": round(bundle_total, 2),
                "delivered_price_per_gallon": round(delivered_price_per_gallon, 4),
                "bundle_price_per_gallon": round(bundle_price_per_gallon, 4),
                "meets_hidden_reserve": delivered_price_per_gallon <= request["reserve_price_per_gal"],
            }
        )
        STATE["bids"][bid_id] = record
        session["submitted"] = True
        session["bid_id"] = bid_id
        save_state(STATE)
    public_bid = {k: v for k, v in record.items() if k != "meets_hidden_reserve"}
    return {"bid": public_bid}


@app.post("/api/grower/select-bid")
def select_bid(selection: SelectBid) -> dict[str, Any]:
    with STATE_LOCK:
        request = STATE["requests"].get(selection.request_id)
        bid = STATE["bids"].get(selection.bid_id)
        if not request:
            raise HTTPException(status_code=404, detail="Request not found.")
        stored_key = request.get("grower_key")
        if not stored_key or not secrets.compare_digest(selection.grower_key, stored_key):
            raise HTTPException(status_code=403, detail="A valid access key is required to pick a bid on this request.")
        if not bid or bid["request_id"] != selection.request_id:
            raise HTTPException(status_code=404, detail="Bid not found for this request.")
        if request["status"] != "open":
            raise HTTPException(status_code=400, detail="Request cannot be awarded from its current status.")
        if now_utc() > datetime.fromisoformat(request["closes_at"].replace("Z", "+00:00")):
            request["status"] = "expired"
            save_state(STATE)
            raise HTTPException(status_code=400, detail="The 48-hour bid window has closed; this request can no longer be awarded.")

        subtotal = bid["bundle_total"] if bid.get("adjuvant_name") else bid["delivered_total"]
        service_fee = round(subtotal * TAKE_RATE, 2)
        total_due = round(subtotal + service_fee, 2)
        settlement_id = f"set-{uuid.uuid4().hex[:12]}"
        settlement = {
            "id": settlement_id,
            "request_id": request["id"],
            "bid_id": bid["id"],
            "payment_method": selection.payment_method,
            "merchant_of_record": "AgBid",
            "supplier_payout_pending_delivery_proof": round(subtotal, 2),
            "agbid_fee": service_fee,
            "total_due_from_grower": total_due,
            "status": "payment_authorization_required",
            "review_status": "manual_review_blocked",
            "created_at": iso(now_utc()),
        }
        STATE["settlements"][settlement_id] = settlement
        STATE["deal_reviews"][settlement_id] = create_initial_deal_review(settlement, request, bid)
        request["status"] = "awarded"
        request["selected_bid_id"] = bid["id"]
        request["settlement_id"] = settlement_id
        save_state(STATE)
    return {
        "settlement": settlement,
        "selected_bid": bid,
        "deal_review": STATE["deal_reviews"][settlement_id],
    }


@app.get("/api/operator/texas-readiness")
def texas_readiness() -> dict[str, Any]:
    return {
        "verdict": "Recruiting-ready for manual concierge pilots; not compliance-complete for autonomous chemical transactions.",
        "launch_regions": TEXAS_LAUNCH_REGIONS,
        "texas_compliance_gates": TEXAS_COMPLIANCE_GATES,
        "customer_gate": "One real grower submits a 250+ gallon request with delivery zip, need-by date, and hidden reserve.",
        "supplier_gate": "Three Texas-capable suppliers submit blind delivered bids, including freight and optional adjuvant bundle.",
        "compliance_gates": [
            "Verify supplier Texas pesticide dealer status before restricted-use or state-limited-use transactions.",
            "Store EPA registration number and PPLS label URL on every bid.",
            "Do not recommend application rates; require users to follow the actual product label.",
            "Use AgBid clearing/payment flow to prevent immediate bypass before scaling.",
        ],
        "manual_first_customer_motion": [
            "Call 10 large growers in High Plains cotton/corn and ask for one real pre-pay chemical request.",
            "Call 10 regional distributors and ask if they will bid blindly when AgBid is buyer/clearing party.",
            "Run the first auction manually in the API; do not automate payments until legal/compliance review is complete.",
        ],
    }


PUBLIC_STATIC_SUFFIXES = {
    ".html", ".css", ".js", ".png", ".jpg", ".jpeg",
    ".gif", ".svg", ".ico", ".webp", ".woff", ".woff2",
}


class PublicStaticFiles(StaticFiles):
    """Serve only whitelisted web assets; never state, data, or source files."""

    async def get_response(self, path: str, scope):
        if Path(path).suffix.lower() not in PUBLIC_STATIC_SUFFIXES:
            raise HTTPException(status_code=404, detail="Not found")
        return await super().get_response(path, scope)


app.mount("/", PublicStaticFiles(directory=str(ROOT), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
