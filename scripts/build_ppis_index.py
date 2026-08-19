#!/usr/bin/env python3
"""
Build an official EPA PPIS launch-wedge index for AgBid.

This uses EPA PPIS fixed-width files, not CDMS/Agrian scraping. It outputs a
small product index for the active-ingredient wedge AgBid can pilot first.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = ROOT / ".cache" / "ppis"
DEFAULT_OUTPUT = ROOT / "outputs" / "ppis_launch_wedge_index.json"
DEFAULT_SUMMARY = ROOT / "outputs" / "ppis_launch_wedge_summary.json"

PPIS_DOWNLOAD_PAGE = (
    "https://www.epa.gov/ingredients-used-pesticide-products/"
    "ppis-download-product-information-data"
)
PPIS_DATA_DICTIONARY = (
    "https://www.epa.gov/sites/default/files/2021-01/documents/"
    "ppis-data-dictionary.pdf"
)
PPLS_REG_URL = "https://ordspub.epa.gov/ords/pesticides/cswu/ppls/{reg}"

PPIS_FILES = {
    "product": {
        "url": "https://www3.epa.gov/pesticides/PPISdata/product.zip",
        "zip_name": "product.zip",
        "member": "product.txt",
    },
    "formula": {
        "url": "https://www3.epa.gov/pesticides/PPISdata/formula.zip",
        "zip_name": "formula.zip",
        "member": "formula.txt",
    },
    "alt_names": {
        "url": "https://www3.epa.gov/pesticides/PPISdata/alt_prod_nm.zip",
        "zip_name": "alt_prod_nm.zip",
        "member": "alt_prod_nm.txt",
    },
    "distributors": {
        "url": "https://www3.epa.gov/pesticides/PPISdata/dist.zip",
        "zip_name": "dist.zip",
        "member": "dist.txt",
    },
    "chemical_names": {
        "url": "https://www3.epa.gov/pesticides/PPISdata/chemname.zip",
        "zip_name": "chemname.zip",
        "member": "chemname.txt",
    },
}

LAUNCH_WEDGE_PC_CODES = {
    "Glyphosate": [
        "103601",
        "103603",
        "103604",
        "103605",
        "103607",
        "103608",
        "103613",
        "128501",
        "417300",
    ],
    "Glufosinate-ammonium": ["128300", "128812", "128850"],
    "2,4-D choline salt": ["051505"],
    "2,4-D dimethylamine salt": ["030019"],
    "Dicamba diglycolamine salt": ["128931"],
    "Dicamba BAPMA salt": ["100094"],
    "Clethodim": ["121011"],
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def field(line: str, start: int, end: int) -> str:
    return line[start - 1 : end].strip()


def clean(text: str) -> str:
    return " ".join(text.split())


def reg_display(raw_reg: str) -> str:
    company = raw_reg[:6].lstrip("0") or "0"
    product = raw_reg[6:11].lstrip("0") or "0"
    return f"{company}-{product}"


def dist_reg_display(raw_reg: str, raw_dist: str) -> str:
    dist = raw_dist.lstrip("0") or "0"
    return f"{reg_display(raw_reg)}-{dist}"


def pct_display(raw_pct: str) -> float:
    raw_pct = raw_pct.strip()
    if not raw_pct:
        return 0.0
    return int(raw_pct) / 10000


def download(url: str, path: Path, refresh: bool) -> None:
    if path.exists() and not refresh:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "AgBidPPISImporter/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        path.write_bytes(response.read())


def iter_zip_lines(cache_dir: Path, spec: dict[str, str]):
    zip_path = cache_dir / spec["zip_name"]
    with zipfile.ZipFile(zip_path) as archive:
        with archive.open(spec["member"]) as handle:
            for raw in handle:
                yield raw.decode("latin-1").rstrip("\r\n")


def load_chemical_names(cache_dir: Path) -> dict[str, dict[str, Any]]:
    names: dict[str, dict[str, Any]] = defaultdict(lambda: {"display_name": None, "names": []})
    for line in iter_zip_lines(cache_dir, PPIS_FILES["chemical_names"]):
        pc_code = field(line, 1, 6)
        name_type = field(line, 7, 26)
        name = clean(field(line, 27, 296))
        display_ind = field(line, 297, 297)
        if not name:
            continue
        row = {"type": name_type, "name": name, "display": display_ind == "Y"}
        names[pc_code]["names"].append(row)
        if display_ind == "Y" or names[pc_code]["display_name"] is None:
            names[pc_code]["display_name"] = name
    return dict(names)


def load_formula(cache_dir: Path, target_codes: set[str]) -> dict[str, list[dict[str, Any]]]:
    formulas: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for line in iter_zip_lines(cache_dir, PPIS_FILES["formula"]):
        pc_code = field(line, 12, 17)
        if pc_code not in target_codes:
            continue
        reg_nr = field(line, 1, 11)
        formulas[reg_nr].append(
            {
                "pc_code": pc_code,
                "percent": pct_display(field(line, 18, 24)),
            }
        )
    return dict(formulas)


def load_products(cache_dir: Path, formula_by_reg: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    products: dict[str, Any] = {}
    for line in iter_zip_lines(cache_dir, PPIS_FILES["product"]):
        reg_nr = field(line, 1, 11)
        if reg_nr not in formula_by_reg:
            continue
        can_date = field(line, 23, 30)
        products[reg_nr] = {
            "reg_nr_raw": reg_nr,
            "epa_registration": reg_display(reg_nr),
            "product_name": clean(field(line, 33, 102)),
            "product_status": "Active" if can_date == "00000000" else "Inactive",
            "approval_date": field(line, 15, 22),
            "cancellation_date": None if can_date == "00000000" else can_date,
            "form_code": field(line, 12, 13),
            "tox_code": field(line, 14, 14),
            "restricted_use": field(line, 103, 103) == "T",
            "conditional_registration": field(line, 106, 106) == "T",
            "ppls_registration_url": PPLS_REG_URL.format(reg=reg_display(reg_nr)),
        }
    return products


def load_alt_names(cache_dir: Path, target_regs: set[str]) -> dict[str, list[dict[str, str]]]:
    names: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen: set[tuple[str, str, str]] = set()
    for line in iter_zip_lines(cache_dir, PPIS_FILES["alt_names"]):
        reg_nr = field(line, 1, 11)
        if reg_nr not in target_regs:
            continue
        product_name = clean(field(line, 12, 81))
        name_type = field(line, 82, 91)
        key = (reg_nr, product_name.lower(), name_type.lower())
        if product_name and key not in seen:
            names[reg_nr].append({"name": product_name, "status": name_type})
            seen.add(key)
    return dict(names)


def load_distributor_names(cache_dir: Path, target_regs: set[str]) -> dict[str, list[dict[str, str]]]:
    distributors: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen: set[tuple[str, str, str]] = set()
    for line in iter_zip_lines(cache_dir, PPIS_FILES["distributors"]):
        reg_nr = field(line, 1, 11)
        if reg_nr not in target_regs:
            continue
        dist_nr = field(line, 12, 17)
        product_name = clean(field(line, 34, 103))
        status = field(line, 104, 113)
        key = (reg_nr, dist_nr, product_name.lower())
        if product_name and key not in seen:
            distributors[reg_nr].append(
                {
                    "distributor_registration": dist_reg_display(reg_nr, dist_nr),
                    "name": product_name,
                    "status": status,
                    "product_status": field(line, 114, 134),
                }
            )
            seen.add(key)
    return dict(distributors)


def build_index(cache_dir: Path) -> dict[str, Any]:
    target_codes = {code for codes in LAUNCH_WEDGE_PC_CODES.values() for code in codes}
    chemical_names = load_chemical_names(cache_dir)
    formula_by_reg = load_formula(cache_dir, target_codes)
    products = load_products(cache_dir, formula_by_reg)
    alt_names = load_alt_names(cache_dir, set(products))
    distributor_names = load_distributor_names(cache_dir, set(products))

    code_to_group: dict[str, str] = {}
    for group, codes in LAUNCH_WEDGE_PC_CODES.items():
        for code in codes:
            code_to_group[code] = group

    records: list[dict[str, Any]] = []
    counts_by_group: dict[str, int] = defaultdict(int)
    active_counts_by_group: dict[str, int] = defaultdict(int)
    restricted_counts_by_group: dict[str, int] = defaultdict(int)
    for reg_nr, product in products.items():
        ingredients = []
        groups = set()
        for ingredient in formula_by_reg[reg_nr]:
            pc_code = ingredient["pc_code"]
            group = code_to_group[pc_code]
            groups.add(group)
            ingredient_names = chemical_names.get(pc_code, {})
            ingredients.append(
                {
                    "launch_group": group,
                    "pc_code": pc_code,
                    "name": ingredient_names.get("display_name") or pc_code,
                    "percent": ingredient["percent"],
                    "known_names": ingredient_names.get("names", [])[:8],
                }
            )
        for group in groups:
            counts_by_group[group] += 1
            if product["product_status"] == "Active":
                active_counts_by_group[group] += 1
            if product["restricted_use"]:
                restricted_counts_by_group[group] += 1
        records.append(
            {
                **product,
                "launch_groups": sorted(groups),
                "active_ingredients": sorted(
                    ingredients, key=lambda item: (item["launch_group"], item["pc_code"])
                ),
                "alternate_product_names": alt_names.get(reg_nr, [])[:20],
                "distributor_product_names": distributor_names.get(reg_nr, [])[:20],
            }
        )

    records.sort(key=lambda item: (item["product_status"] != "Active", item["product_name"]))
    return {
        "generated_at": utc_now(),
        "source": {
            "name": "EPA Pesticide Product Information System",
            "download_page": PPIS_DOWNLOAD_PAGE,
            "data_dictionary": PPIS_DATA_DICTIONARY,
            "files": {name: spec["url"] for name, spec in PPIS_FILES.items()},
            "rule": "PPIS is used as official product identity and active-ingredient data; PPLS remains the label-PDF check by EPA registration.",
        },
        "target_pc_codes": LAUNCH_WEDGE_PC_CODES,
        "summary": {
            "target_active_ingredient_groups": len(LAUNCH_WEDGE_PC_CODES),
            "matching_product_count": len(records),
            "active_product_count": sum(1 for record in records if record["product_status"] == "Active"),
            "restricted_use_product_count": sum(1 for record in records if record["restricted_use"]),
            "counts_by_group": dict(sorted(counts_by_group.items())),
            "active_counts_by_group": dict(sorted(active_counts_by_group.items())),
            "restricted_counts_by_group": dict(sorted(restricted_counts_by_group.items())),
        },
        "products": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--refresh", action="store_true", help="Download fresh EPA PPIS zip files.")
    args = parser.parse_args()

    for spec in PPIS_FILES.values():
        download(spec["url"], args.cache_dir / spec["zip_name"], refresh=args.refresh)

    index = build_index(args.cache_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary = {
        "generated_at": index["generated_at"],
        "source": index["source"],
        "target_pc_codes": index["target_pc_codes"],
        "summary": index["summary"],
        "output": str(args.output),
    }
    args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(summary["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
