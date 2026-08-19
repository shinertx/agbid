#!/usr/bin/env python3
"""
Verify AgBid seed products against EPA PPLS.

This does not scrape CDMS or Agrian. It uses the official EPA PPLS API:
  - /cswu/ppls/{epa_registration}
  - /cswu/ProductSearch/partialprodsearch/v2/riname/{product_name}

Outputs:
  - outputs/label_verification_report.json
  - agbid_label_database.verified.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "agbid_label_database.json"
DEFAULT_OUTPUT = ROOT / "agbid_label_database.verified.json"
DEFAULT_REPORT = ROOT / "outputs" / "label_verification_report.json"
PPLS_REG_URL = "https://ordspub.epa.gov/ords/pesticides/cswu/ppls/{reg}"
PPLS_NAME_URL = (
    "https://ordspub.epa.gov/ords/pesticides/cswu/ProductSearch/"
    "partialprodsearch/v2/riname/{name}"
)
PDF_BASE_URL = "https://www3.epa.gov/pesticides/chem_search/ppls/{pdf}"


def fetch_json(url: str, timeout: int = 8) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "AgBidLabelVerifier/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize(text: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in text).split())


def product_score(seed_name: str, candidate_name: str) -> int:
    seed = normalize(seed_name)
    candidate = normalize(candidate_name)
    if not seed or not candidate:
        return 0
    if seed == candidate:
        return 100
    score = 0
    seed_tokens = set(seed.split())
    candidate_tokens = set(candidate.split())
    overlap = len(seed_tokens & candidate_tokens)
    score += overlap * 10
    if seed in candidate or candidate in seed:
        score += 40
    first_words = " ".join(seed.split()[:2])
    if first_words and first_words in candidate:
        score += 15
    return score


def is_standard_epa_registration(registration: str) -> bool:
    parts = registration.split("-")
    return len(parts) in {2, 3} and all(part.isdigit() for part in parts)


def is_active_status(status: str | None) -> bool:
    return (status or "").strip().lower() in {"active", "registered"}


def best_name_candidate(seed_name: str, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    scored = [(product_score(seed_name, item.get("productname", "")), item) for item in items]
    scored = [pair for pair in scored if pair[0] > 0]
    if not scored:
        return None
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[0][1]


def latest_pdf_url(ppls_item: dict[str, Any]) -> str | None:
    pdfs = ppls_item.get("pdffiles") or []
    if not pdfs:
        return None
    latest = pdfs[0]
    return PDF_BASE_URL.format(pdf=latest.get("pdffile"))


def verify_product(product: dict[str, Any], delay: float = 0.15) -> dict[str, Any]:
    brand_name = product.get("brand_name", "")
    original_reg = product.get("epa_registration", "")
    result: dict[str, Any] = {
        "brand_name": brand_name,
        "original_epa_registration": original_reg,
        "status": "unverified",
        "errors": [],
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "ppls_registration_url": PPLS_REG_URL.format(reg=urllib.parse.quote(original_reg)),
        "ppls_name_search_url": PPLS_NAME_URL.format(name=urllib.parse.quote(brand_name)),
    }

    reg_items: list[dict[str, Any]] = []
    try:
        reg_payload = fetch_json(result["ppls_registration_url"])
        reg_items = reg_payload.get("items") or []
        if reg_items:
            reg_item = reg_items[0]
            result.update(
                {
                    "registration_lookup_product_name": reg_item.get("productname"),
                    "registration_lookup_status": reg_item.get("product_status"),
                    "registration_lookup_cancel_flag": reg_item.get("cancel_flag"),
                    "registration_lookup_rup": reg_item.get("rup_yn"),
                    "registration_lookup_active_ingredients": reg_item.get("active_ingredients", []),
                    "registration_lookup_pdf_url": latest_pdf_url(reg_item),
                }
            )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        result["errors"].append(f"registration_lookup_failed: {exc}")

    time.sleep(delay)

    name_candidate: dict[str, Any] | None = None
    try:
        name_payload = fetch_json(result["ppls_name_search_url"])
        name_items = name_payload.get("items") or []
        name_candidate = best_name_candidate(brand_name, name_items)
        if name_candidate:
            result.update(
                {
                    "name_lookup_product_name": name_candidate.get("productname"),
                    "name_lookup_epa_registration": name_candidate.get("eparegno"),
                    "name_lookup_product_status": name_candidate.get("product_status")
                    or name_candidate.get("registrationstatus"),
                    "name_lookup_score": product_score(brand_name, name_candidate.get("productname", "")),
                }
            )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        result["errors"].append(f"name_lookup_failed: {exc}")

    verified_reg = original_reg
    verification_note = "EPA registration lookup matched seeded product."
    registration_product_name = result.get("registration_lookup_product_name") or ""
    reg_name_score = product_score(brand_name, registration_product_name)
    result["registration_name_score"] = reg_name_score

    if name_candidate and name_candidate.get("eparegno") != original_reg:
        candidate_score = int(result.get("name_lookup_score") or 0)
        candidate_reg = name_candidate.get("eparegno") or ""
        candidate_status = result.get("name_lookup_product_status")
        if (
            candidate_score >= max(50, reg_name_score + 20)
            and is_standard_epa_registration(candidate_reg)
            and is_active_status(candidate_status)
        ):
            verified_reg = name_candidate["eparegno"]
            result["status"] = "registration_mismatch_suggested_fix"
            verification_note = (
                f"Seeded registration {original_reg} appears to map to "
                f"{registration_product_name!r}; product-name search suggests {verified_reg}."
            )
        elif not is_standard_epa_registration(candidate_reg):
            result["status"] = "needs_manual_review"
            verification_note = (
                f"Product-name search suggests state/local registration {candidate_reg}; "
                "do not use for Texas marketplace without manual compliance review."
            )
        elif not is_active_status(candidate_status):
            result["status"] = "needs_manual_review"
            verification_note = (
                f"Product-name search suggests {candidate_reg}, but its status is {candidate_status!r}."
            )
        elif reg_name_score >= 50:
            result["status"] = "verified"
        else:
            result["status"] = "needs_manual_review"
            verification_note = "EPA lookups returned conflicting or weak matches."
    elif reg_items and reg_name_score >= 50:
        result["status"] = "verified"
    elif name_candidate and not reg_items:
        verified_reg = name_candidate.get("eparegno") or original_reg
        result["status"] = "registration_missing_suggested_fix"
        verification_note = f"Registration lookup failed; product-name search suggests {verified_reg}."
    elif reg_items:
        result["status"] = "needs_manual_review"
        verification_note = "EPA registration exists but product name does not match seed strongly."
    else:
        result["status"] = "not_found"
        verification_note = "No useful EPA PPLS registration or product-name match found."

    result["verified_epa_registration"] = verified_reg
    result["verification_note"] = verification_note
    return result


def apply_result(product: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    enriched = deepcopy(product)
    enriched.setdefault("original_epa_registration", product.get("epa_registration"))
    enriched["epa_registration"] = result["verified_epa_registration"]
    enriched["epa_verification"] = {
        "status": result["status"],
        "checked_at": result["checked_at"],
        "note": result["verification_note"],
        "original_epa_registration": result["original_epa_registration"],
        "ppls_registration_url": PPLS_REG_URL.format(
            reg=urllib.parse.quote(result["verified_epa_registration"])
        ),
        "ppls_name_search_url": result["ppls_name_search_url"],
        "registration_lookup_product_name": result.get("registration_lookup_product_name"),
        "name_lookup_product_name": result.get("name_lookup_product_name"),
        "name_lookup_epa_registration": result.get("name_lookup_epa_registration"),
        "pdf_url": result.get("registration_lookup_pdf_url"),
        "rup": result.get("registration_lookup_rup"),
        "product_status": result.get("registration_lookup_status")
        or result.get("name_lookup_product_status"),
    }
    return enriched


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--delay", type=float, default=0.05)
    args = parser.parse_args()

    seed = json.loads(args.input.read_text(encoding="utf-8"))
    verified = deepcopy(seed)
    report: list[dict[str, Any]] = []

    for active_name, group in seed.items():
        updated_alternatives = []
        for product in group.get("generic_alternatives", []):
            result = verify_product(product, delay=args.delay)
            result["active_ingredient_group"] = active_name
            report.append(result)
            updated_alternatives.append(apply_result(product, result))
            print(
                f"{result['status']}: {product.get('brand_name')} "
                f"{result['original_epa_registration']} -> {result['verified_epa_registration']}",
                flush=True,
            )
        verified[active_name]["generic_alternatives"] = updated_alternatives

    args.output.write_text(json.dumps(verified, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    counts: dict[str, int] = {}
    for item in report:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    print(json.dumps({"counts": counts, "report": str(args.report), "output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
