"""
compliance_rules.py
--------------------
Rule-based compliance engine for the Legal Metrology (Packaged Commodities)
Rules, 2011 (as amended). Implements automated checks for the mandatory
declarations required under Rule 6, and the minimum font-size / letter
height requirements linked to the area of the principal display panel
(PDP), read with the Rules' schedule for size of declarations.

IMPORTANT (prototype disclaimer):
The numeric thresholds below (font sizes, PDP slabs) are encoded from the
publicly available text of the LMPC Rules, 2011 as commonly cited by the
Department of Consumer Affairs, and are kept in one place (RULE_CONFIG) so
a Legal Metrology domain expert can verify/update them before production
use. This module is built to be data-driven so rule updates/amendments do
not require touching the detection logic.
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional


# ---------------------------------------------------------------------------
# 1. Configurable rule definitions (Rule 6 mandatory declarations + Rule 5
#    principal display panel font-size schedule)
# ---------------------------------------------------------------------------

RULE_CONFIG = {
    "mandatory_declarations": [
        {
            "code": "MFR_NAME_ADDRESS",
            "label": "Name and address of manufacturer/packer/importer",
            "rule_ref": "Rule 6(1)(a)",
            "required": True,
        },
        {
            "code": "COMMON_NAME",
            "label": "Common / generic name of the commodity",
            "rule_ref": "Rule 6(1)(b)",
            "required": True,
        },
        {
            "code": "NET_QUANTITY",
            "label": "Net quantity (in standard units)",
            "rule_ref": "Rule 6(1)(c) / Rule 8",
            "required": True,
        },
        {
            "code": "MFG_DATE",
            "label": "Month and year of manufacture / packing / import",
            "rule_ref": "Rule 6(1)(e)",
            "required": True,
        },
        {
            "code": "MRP",
            "label": "Maximum Retail Price (inclusive of all taxes)",
            "rule_ref": "Rule 6(1)(f)",
            "required": True,
        },
        {
            "code": "CONSUMER_CARE",
            "label": "Consumer care / customer complaint details",
            "rule_ref": "Rule 6(1)(g)",
            "required": True,
        },
        {
            "code": "COUNTRY_OF_ORIGIN",
            "label": "Country of origin (for imported packages)",
            "rule_ref": "Rule 6(1)(h) / Rule 27",
            "required": False,  # only mandatory for imported goods
        },
        {
            "code": "BEST_BEFORE",
            "label": "Best before / use by date (where applicable)",
            "rule_ref": "Rule 6(1)(e) proviso",
            "required": False,  # applicable to perishable/shelf-life goods
        },
    ],

    # Rule 5 read with Second Schedule: minimum standard letter/numeral
    # height for declarations based on area of the principal display panel
    # (PDP), in sq. cm -> minimum letter height in mm.
    "font_size_slabs": [
        {"max_area_cm2": 100, "min_letter_height_mm": 1},
        {"max_area_cm2": 500, "min_letter_height_mm": 2},
        {"max_area_cm2": 2500, "min_letter_height_mm": 4},
        {"max_area_cm2": float("inf"), "min_letter_height_mm": 6},
    ],
}


def get_min_font_size_mm(pdp_area_cm2: float) -> float:
    """Return the minimum required letter height (mm) for a given PDP area."""
    for slab in RULE_CONFIG["font_size_slabs"]:
        if pdp_area_cm2 <= slab["max_area_cm2"]:
            return slab["min_letter_height_mm"]
    return RULE_CONFIG["font_size_slabs"][-1]["min_letter_height_mm"]


# ---------------------------------------------------------------------------
# 2. Detection patterns for each declaration (regex based, tuned for OCR
#    output which is often noisy — patterns are intentionally lenient)
# ---------------------------------------------------------------------------

PATTERNS = {
    "MRP": [
        r"\bM\s*\.?\s*R\s*\.?\s*P\b",
        r"MAXIMUM\s+RETAIL\s+PRICE",
        r"(?:RS|₹|INR)\s*\.?\s*\d+(?:[.,]\d{1,2})?",
    ],
    "MRP_VALUE": r"(?:RS|₹|INR|M\s*\.?\s*R\s*\.?\s*P\.?)\s*\.?\s*(\d+(?:[.,]\d{1,2})?)",
    "MRP_INCL_TAX": r"INCL(?:USIVE|\.)?\s+(?:OF\s+)?ALL\s+TAX",

    "NET_QUANTITY": [
        r"\bNET\s*(?:QTY|QUANTITY|WT|WEIGHT|VOL|VOLUME|CONTENT)\b",
        r"\b\d+(?:\.\d+)?\s*(?:G|GM|GMS|KG|ML|L|LTR|MG|N|PCS|PIECES|COUNT)\b",
    ],

    "MFG_DATE": [
        r"\b(?:MFG|MFD|MANUFACTURED|PACKED|PKD|PACKING)\b",
        r"\b(0[1-9]|1[0-2])\s*[\/\-\.]\s*(19|20)\d{2}\b",
        r"\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s*'?(\d{2,4})\b",
    ],

    "BEST_BEFORE": [
        r"\bBEST\s*BEFORE\b",
        r"\bUSE\s*BY\b",
        r"\bEXPIRY\b",
        r"\bEXP\.?\s*DATE\b",
    ],

    "CONSUMER_CARE": [
        r"\bCONSUMER\s+CARE\b",
        r"\bCUSTOMER\s+CARE\b",
        r"\bTOLL\s*FREE\b",
        r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",  # email
        r"\b(?:\+91[\s-]?)?[6-9]\d{9}\b",           # Indian mobile number
        r"\b1800[\s-]?\d{3}[\s-]?\d{4}\b",           # toll-free
    ],

    "MFR_NAME_ADDRESS": [
        r"\b(?:MFD|MANUFACTURED|MARKETED|PACKED|MKTD)\s+BY\b",
        r"\bIMPORTED\s+BY\b",
        r"\bPIN\s*[:\-]?\s*\d{6}\b",
        r"\b\d{6}\b",  # bare 6-digit PIN code as fallback
    ],

    "COUNTRY_OF_ORIGIN": [
        r"\bCOUNTRY\s+OF\s+ORIGIN\b",
        r"\bMADE\s+IN\s+[A-Z]+\b",
    ],

    "COMMON_NAME": [],  # handled heuristically (largest text block near top)
}


@dataclass
class DeclarationResult:
    code: str
    label: str
    rule_ref: str
    required: bool
    found: bool
    extracted_text: Optional[str] = None
    matched_snippets: List[str] = field(default_factory=list)
    font_ok: Optional[bool] = None
    font_height_mm: Optional[float] = None
    min_required_mm: Optional[float] = None
    notes: str = ""


def _search_patterns(text_upper: str, patterns: List[str]) -> List[str]:
    hits = []
    for pat in patterns:
        for m in re.finditer(pat, text_upper):
            hits.append(m.group(0))
    return hits


def check_declarations(full_text: str) -> List[DeclarationResult]:
    """
    Run every configured mandatory-declaration check against the OCR'd
    label text and return a structured result per declaration.
    """
    text_upper = full_text.upper()
    results = []

    for decl in RULE_CONFIG["mandatory_declarations"]:
        code = decl["code"]
        patterns = PATTERNS.get(code, [])
        hits = _search_patterns(text_upper, patterns) if patterns else []
        found = len(hits) > 0

        extracted = None
        notes = ""

        if code == "MRP" and found:
            m = re.search(PATTERNS["MRP_VALUE"], text_upper)
            extracted = m.group(0) if m else None
            if not re.search(PATTERNS["MRP_INCL_TAX"], text_upper):
                notes = ('MRP found, but the mandatory phrase "inclusive of '
                         'all taxes" was not detected near it — verify manually.')

        if code == "COMMON_NAME":
            # Heuristic: cannot reliably auto-detect generic/common name via
            # regex alone — flagged for manual confirmation in every scan.
            found = False
            notes = ("Common/generic name cannot be auto-verified with "
                     "certainty; please confirm manually against the "
                     "product listing.")

        if code in ("NET_QUANTITY", "MFG_DATE", "CONSUMER_CARE",
                     "MFR_NAME_ADDRESS", "COUNTRY_OF_ORIGIN", "BEST_BEFORE") and found:
            extracted = hits[0]

        results.append(DeclarationResult(
            code=code,
            label=decl["label"],
            rule_ref=decl["rule_ref"],
            required=decl["required"],
            found=found,
            extracted_text=extracted,
            matched_snippets=hits[:5],
            notes=notes,
        ))

    return results


def summarize_compliance(declaration_results: List[DeclarationResult],
                          font_violations: int = 0) -> Dict:
    """Roll up per-declaration results into an overall compliance verdict."""
    missing_required = [d for d in declaration_results
                         if d.required and not d.found]
    needs_review = [d for d in declaration_results if d.notes and d.found]

    if missing_required or font_violations > 0:
        status = "NON_COMPLIANT"
    elif needs_review:
        status = "NEEDS_REVIEW"
    else:
        status = "COMPLIANT"

    return {
        "status": status,
        "total_checks": len(declaration_results),
        "passed": sum(1 for d in declaration_results if d.found or not d.required),
        "missing_required": [d.label for d in missing_required],
        "needs_review": [d.label for d in needs_review],
        "font_violations": font_violations,
    }
