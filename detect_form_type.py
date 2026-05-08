"""
Auto-detect document type PER PAGE. Generalizes the pipeline to handle
ANY uploaded PDF including:
  - Multi-form ACORD packets (125 + 140 + 126 + 131 + 823 in one PDF)
  - Mixed packets: ACORD app pages + loss run pages + narrative pages
  - Any insured / broker / carrier (no hardcoded names)

Per page, returns a `kind`:

  ACORD_FORM    ← ACORD 125/126/131/140/823 (use bbox+VLM merge)
                  Carries (template_filename, template_page_index)
  LOSS_RUN      ← claim listing table (use pdfplumber+VLM cross-check)
  SOV_TABLE     ← Schedule of Values / property listing (rare in PDFs)
  NARRATIVE     ← cover letter / underwriter notes / email body
  EMPTY         ← blank or near-blank page
  UNKNOWN       ← couldn't classify with confidence

Two complementary methods for ACORD identification:

  1. **Footer-text matching** — every ACORD page has a footer like
     "ACORD 125 (2016/03)" / "ACORD 140 (2016/09)" / "ACORD 131 (2014/12)".
     Pulled via pdfplumber bottom-of-page text. Fast and deterministic
     when the form is digital (not garbled).

  2. **Anchor-label fingerprint** — for each ACORD template, we know
     a set of section-header words that uniquely identify it (e.g.
     "GENERAL LIABILITY SECTION" → ACORD 126; "PROPERTY SECTION" →
     ACORD 140; "UMBRELLA / EXCESS" → ACORD 131). For a filled page,
     count keyword overlaps with each template's fingerprint. Highest
     score wins. Used as fallback when footer is unreadable.

Loss-run / SOV / narrative detection uses content-based heuristics
(claim-table header signatures, SOV column names, vs free-prose).
"""
from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pdfplumber


# ── Footer-text patterns ──
# Maps regex → (template_filename, can_span_multi_page)
FOOTER_PATTERNS = [
    (re.compile(r"ACORD\s*125\s*\([\d/]+\)", re.IGNORECASE), "acord_125.pdf"),
    (re.compile(r"ACORD\s*126\s*\(2014/\d+\)", re.IGNORECASE), "acord_126_2014.pdf"),
    (re.compile(r"ACORD\s*126\s*\(\s*\d+/\d+\s*\)", re.IGNORECASE), "acord_126.pdf"),
    (re.compile(r"ACORD\s*131\s*\(\s*\d+/\d+\s*\)", re.IGNORECASE), "acord_131.pdf"),
    (re.compile(r"ACORD\s*140\s*\(\s*\d+/\d+\s*\)", re.IGNORECASE), "acord_140.pdf"),
    (re.compile(r"ACORD\s*823\s*\(\s*\d+/\d+\s*\)", re.IGNORECASE), "acord_823.pdf"),
]


# ── Anchor-label fingerprints (per template, NOT per customer) ──
# These are SECTION HEADERS printed on the form — not user-fillable text.
# Different from the bbox extraction's ANCHOR_LABELS (which are for dy
# computation). Here we use them for CONTENT identification.
TEMPLATE_FINGERPRINTS = {
    "acord_125.pdf": {
        # ACORD 125 — Commercial Insurance Application, Applicant Information
        "strong": [
            "APPLICANT INFORMATION SECTION",
            "INDICATE LINES OF BUSINESS",
            "STATUS OF TRANSACTION",
            "POLICY INFORMATION",
            "NATURE OF BUSINESS",
            "PREMISES INFORMATION",
            "SCHEDULE OF HAZARDS",
            "GENERAL INFORMATION",
            "PRIOR CARRIER INFORMATION",
            "LOSS HISTORY",
        ],
        "weak": [
            "AGENCY", "CARRIER", "NAIC CODE", "POLICY NUMBER",
            "AGENCY CUSTOMER ID", "PROPOSED EFF DATE",
        ],
    },
    "acord_140.pdf": {
        # ACORD 140 — Property Section
        "strong": [
            "PROPERTY SECTION",
            "BLANKET SUMMARY",
            "PREMISES INFORMATION",
            "COVERAGE INFORMATION",
            "ADDITIONAL COVERAGES",
            "CONSTRUCTION",
            "BUILDING IMPROVEMENTS",
            "FIRE PROTECTION",
            "BURGLAR ALARM",
            "ADDITIONAL INTEREST",
        ],
        "weak": [
            "YEAR BUILT", "TOTAL AREA", "ROOF TYPE", "WIRING", "PLUMBING",
            "PROTECTION CLASS", "DEDUCTIBLE",
        ],
    },
    "acord_126_2014.pdf": {
        # ACORD 126 (2014) — Commercial General Liability Section
        "strong": [
            "COMMERCIAL GENERAL LIABILITY SECTION",
            "SCHEDULE OF HAZARDS",
            "CLAIMS MADE",
            "OWNERS & CONTRACTORS PROTECTIVE",
            "CONTRACTORS",
            "PRODUCTS / COMPLETED OPERATIONS",
            "DEDUCTIBLES",
        ],
        "weak": [
            "OCCURRENCE", "GENERAL AGGREGATE", "PREMISES / OPERATIONS",
            "CLASSIFICATION", "EXPOSURE",
        ],
    },
    "acord_126.pdf": {
        # Same form, older edition. Use 126_2014 first; fall through here.
        "strong": [
            "COMMERCIAL GENERAL LIABILITY SECTION",
            "SCHEDULE OF HAZARDS",
        ],
        "weak": ["OCCURRENCE", "GENERAL AGGREGATE"],
    },
    "acord_131.pdf": {
        # ACORD 131 — Umbrella / Excess
        "strong": [
            "UMBRELLA",
            "EXCESS LIABILITY",
            "UNDERLYING INSURANCE",
            "FOLLOWING FORM",
        ],
        "weak": [
            "RETROACTIVE DATE", "EACH OCCURRENCE",
            "AGGREGATE", "SELF-INSURED RETENTION",
        ],
    },
    "acord_823.pdf": {
        # ACORD 823 — Additional Premises Information Schedule
        "strong": [
            "ADDITIONAL PREMISES INFORMATION SCHEDULE",
            "ADDITIONAL PREMISES",
            "PREMISES SCHEDULE",
        ],
        "weak": ["LOC #", "BLD #", "STREET", "OCCUPIED AREA"],
    },
}


def _get_page_text(pdf_path: Path, page_num: int) -> str:
    """Extract all text from a page (top-to-bottom). Used for footer match
       and anchor-label fingerprinting."""
    with pdfplumber.open(str(pdf_path)) as pdf:
        if page_num - 1 >= len(pdf.pages):
            return ""
        return pdf.pages[page_num - 1].extract_text() or ""


def _footer_match(page_text: str) -> Optional[str]:
    """Return template filename if footer matches a known ACORD form."""
    # Look at the last ~200 chars (footer area)
    tail = page_text[-300:] if len(page_text) > 300 else page_text
    for pattern, template_name in FOOTER_PATTERNS:
        if pattern.search(tail):
            return template_name
    return None


def _fingerprint_score(page_text: str, fp: dict) -> float:
    """Score how well a page matches a template's section-header fingerprint."""
    text_upper = page_text.upper()
    score = 0.0
    for kw in fp.get("strong", []):
        if kw in text_upper:
            score += 1.0
    for kw in fp.get("weak", []):
        if kw in text_upper:
            score += 0.3
    return score


def _fingerprint_match(page_text: str) -> Optional[str]:
    """Return best-scoring template (or None if all scores low)."""
    if not page_text.strip():
        return None
    scores = {tmpl: _fingerprint_score(page_text, fp)
              for tmpl, fp in TEMPLATE_FINGERPRINTS.items()}
    best = max(scores, key=scores.get)
    if scores[best] < 1.0:  # need at least one strong header
        return None
    # Ambiguity check: best must beat second-best by ≥ 1.0
    second = sorted(scores.values(), reverse=True)[1]
    if scores[best] - second < 1.0:
        return None
    return best


def _detect_template_page_index(template_path: Path,
                                  page_text: str) -> int:
    """Given a candidate template, find which page of THAT TEMPLATE this
       filled page corresponds to. Compares anchor-label sets per
       template page, picks the page with the most overlap."""
    text_upper = page_text.upper()
    # Cache template page texts
    tpl_texts = _read_template_pages(str(template_path))
    best_idx = 0
    best_score = -1
    for idx, tpl_text in enumerate(tpl_texts):
        # Use the strongest / longest unique words as anchors
        words = set(re.findall(r"\b[A-Z][A-Z0-9 \-/&]{6,}\b", tpl_text.upper()))
        if not words:
            continue
        score = sum(1 for w in words if w in text_upper)
        if score > best_score:
            best_score = score
            best_idx = idx
    return best_idx


@lru_cache(maxsize=None)
def _read_template_pages(template_path: str) -> tuple:
    out = []
    with pdfplumber.open(template_path) as pdf:
        for p in pdf.pages:
            out.append(p.extract_text() or "")
    return tuple(out)


# ── Public API ──

def detect_form_type_for_page(pdf_path: Path, page_num: int,
                                templates_dir: Path) -> Optional[tuple]:
    """Identify which ACORD template this filled-PDF page corresponds to.

       Returns (template_filename, template_page_index) or None.

       Strategy:
         1. Try footer-text match (fast, deterministic).
         2. If footer unreadable, try fingerprint match.
         3. For matched template, determine page index by max-overlap.
    """
    text = _get_page_text(pdf_path, page_num)
    if not text.strip():
        return None

    template = _footer_match(text) or _fingerprint_match(text)
    if not template:
        return None

    template_path = templates_dir / template
    if not template_path.exists():
        # Fall back if specific edition missing (e.g. acord_126_2014 → acord_126)
        if template == "acord_126_2014.pdf":
            template_path = templates_dir / "acord_126.pdf"
            template = "acord_126.pdf"
        if not template_path.exists():
            return None

    page_idx = _detect_template_page_index(template_path, text)
    return (template, page_idx)


def detect_form_type_for_pdf(pdf_path: Path,
                              templates_dir: Path) -> dict:
    """Scan every page of a filled PDF and build a complete page map.

       Returns {page_num (1-indexed): (template_filename, template_page_idx)}
       for pages that match a known template. Pages with no match are
       omitted (caller can fall through to pure-VLM extraction).
    """
    page_map = {}
    with pdfplumber.open(str(pdf_path)) as pdf:
        n_pages = len(pdf.pages)
    for p in range(1, n_pages + 1):
        match = detect_form_type_for_page(pdf_path, p, templates_dir)
        if match:
            page_map[p] = match
    return page_map


# ── Per-page document-kind classification (ACORD / loss-run / SOV / narrative) ──

LOSS_RUN_HEADER_PATTERNS = [
    re.compile(r"\bloss\s+run", re.IGNORECASE),
    re.compile(r"\bclaim\s*(summary|listing|history|details?|count)\b", re.IGNORECASE),
    re.compile(r"\bclaim\s*(#|number|no\.?|id)\b", re.IGNORECASE),
    re.compile(r"\b(date\s+of\s+loss|loss\s+date)\b", re.IGNORECASE),
    re.compile(r"\b(total\s+)?(reserve|reserves|incurred|paid|recover(ed|y))\b",
               re.IGNORECASE),
    re.compile(r"\bvaluation\s+date\b", re.IGNORECASE),
    re.compile(r"\b(claimant|policy\s*term)\b", re.IGNORECASE),
    re.compile(r"\bcause\s+of\s+loss\b", re.IGNORECASE),
    re.compile(r"\beffective\s+date.*claim\s+count", re.IGNORECASE),
]

LOSS_RUN_NAME_PATTERNS = re.compile(
    r"\b(loss[\s_-]?run|claims?[\s_-]history|loss[\s_-]?history)\b",
    re.IGNORECASE)

SOV_HEADER_PATTERNS = [
    re.compile(r"\bschedule\s+of\s+values\b", re.IGNORECASE),
    re.compile(r"\bloc\.?\s*#", re.IGNORECASE),
    re.compile(r"\bbuilding\s*#", re.IGNORECASE),
    re.compile(r"\b(building|bpp|tiv|loss\s+of\s+rents)\b.*\b(building|bpp|tiv|loss)\b",
               re.IGNORECASE),
]


def classify_page_kind(pdf_path: Path, page_num: int,
                        templates_dir: Path) -> dict:
    """Classify a single page into a document kind. Returns:
         {'kind': str, 'detail': dict}
       where kind ∈ {ACORD_FORM, LOSS_RUN, SOV_TABLE, NARRATIVE,
                     EMPTY, UNKNOWN}
       and detail carries kind-specific info."""
    text = _get_page_text(pdf_path, page_num)
    text_chars = len(text.strip())

    if text_chars < 30:
        return {"kind": "EMPTY", "detail": {"text_chars": text_chars}}

    # 1. Try ACORD form
    acord_match = detect_form_type_for_page(pdf_path, page_num, templates_dir)
    if acord_match:
        return {
            "kind": "ACORD_FORM",
            "detail": {
                "template": acord_match[0],
                "template_page_index": acord_match[1],
            },
        }

    # 2. Loss-run page detection
    loss_run_signals = sum(1 for p in LOSS_RUN_HEADER_PATTERNS if p.search(text))
    if loss_run_signals >= 3:
        return {
            "kind": "LOSS_RUN",
            "detail": {"signals": loss_run_signals},
        }

    # 3. SOV table page
    sov_signals = sum(1 for p in SOV_HEADER_PATTERNS if p.search(text))
    if sov_signals >= 2:
        return {
            "kind": "SOV_TABLE",
            "detail": {"signals": sov_signals},
        }

    # 4. Narrative — free-text page (cover letter, underwriter notes, email)
    # Heuristic: has paragraphs, low table-like structure
    if text_chars > 300:
        return {
            "kind": "NARRATIVE",
            "detail": {"text_chars": text_chars},
        }

    return {"kind": "UNKNOWN", "detail": {"text_chars": text_chars}}


def classify_pdf_pages(pdf_path: Path, templates_dir: Path) -> dict:
    """Classify every page of a multi-form PDF.
       Returns:
         {
           'n_pages': int,
           'pages': {page_num: {'kind': ..., 'detail': ...}},
           'groups': [
             {'kind': 'ACORD_FORM', 'pages': [1,2,3,4]},
             {'kind': 'LOSS_RUN', 'pages': [26,27]},
             ...
           ],
         }
       The 'groups' field collapses consecutive same-kind pages so the
       caller can route each group to the appropriate sub-pipeline."""
    with pdfplumber.open(str(pdf_path)) as pdf:
        n_pages = len(pdf.pages)

    pages = {}
    for p in range(1, n_pages + 1):
        pages[p] = classify_page_kind(pdf_path, p, templates_dir)

    # Group consecutive same-kind pages
    groups = []
    cur_kind = None
    cur_pages = []
    for p in range(1, n_pages + 1):
        kind = pages[p]["kind"]
        if kind == cur_kind:
            cur_pages.append(p)
        else:
            if cur_kind is not None:
                groups.append({"kind": cur_kind, "pages": cur_pages})
            cur_kind = kind
            cur_pages = [p]
    if cur_kind is not None:
        groups.append({"kind": cur_kind, "pages": cur_pages})

    return {"n_pages": n_pages, "pages": pages, "groups": groups}


# ── CLI ──

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--templates-dir",
                     default=str(Path(__file__).parent / "templates"))
    ap.add_argument("--all-kinds", action="store_true",
                     help="Classify EVERY page (ACORD/LOSS_RUN/SOV/NARRATIVE/EMPTY)")
    args = ap.parse_args()

    pdf_path = Path(args.pdf)
    templates_dir = Path(args.templates_dir)

    if args.all_kinds:
        result = classify_pdf_pages(pdf_path, templates_dir)
        print(f"PDF: {pdf_path.name}  ({result['n_pages']} pages)")
        print(f"\nPer-page kinds:")
        for pg in range(1, result["n_pages"] + 1):
            entry = result["pages"][pg]
            kind = entry["kind"]
            d = entry["detail"]
            extra = ""
            if kind == "ACORD_FORM":
                extra = f"  → {d['template']} #{d['template_page_index']}"
            elif kind == "LOSS_RUN":
                extra = f"  signals={d['signals']}"
            elif kind == "SOV_TABLE":
                extra = f"  signals={d['signals']}"
            print(f"  page {pg:2d}: {kind:14s}{extra}")
        print(f"\nPage groups (consecutive same-kind):")
        for g in result["groups"]:
            ps = g["pages"]
            rng = f"{ps[0]}–{ps[-1]}" if len(ps) > 1 else f"{ps[0]}"
            print(f"  pages {rng:8s}  ({len(ps)} pgs)  {g['kind']}")
        return

    page_map = detect_form_type_for_pdf(pdf_path, templates_dir)
    print(f"PDF: {pdf_path.name}")
    print(f"Pages with template match: {len(page_map)}")
    for pg, (tmpl, idx) in sorted(page_map.items()):
        print(f"  page {pg:2d}: {tmpl} #{idx}")


if __name__ == "__main__":
    sys.exit(main())
