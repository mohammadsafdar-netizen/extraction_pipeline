"""
Merged BBOX-anchor + vLLM extraction runner.

Combines:
  1) Anchor-aligned bbox extraction (pdfplumber-based) for structured fields
     and X-mark checkbox detection — strongest on amounts and checkboxes.
  2) vLLM full-page extraction (qwen3-vl-8b et al.) for free-text fields,
     addresses, descriptions, and any pages not in the ACORD template map.
  3) Merge: bbox is primary; VLM gap-fills; dollar amounts are
     cross-validated and disagreements flagged.

Usage:
  python run_vllm_merged.py                                  # all 5 ACORD apps
  python run_vllm_merged.py "Acord App (1800 North Stone LLC) 2026.pdf"
  python run_vllm_merged.py --model qwen3-vl-8b --out merged_qwen3vl8b
"""
import argparse
import base64
import json
import re
import sys
import time
from pathlib import Path

import fitz
import pdfplumber
import pypdf
import requests
from PIL import Image

from prompts import GENERALIZED, get_prompt

REPO = Path(__file__).resolve().parent
PDF_DIR = REPO / "pdfs"
TEMPLATES_DIR = REPO / "templates"
DEFAULT_OUT = REPO / "merged_qwen3vl8b"

VLLM_URL = "http://127.0.0.1:8000/v1/chat/completions"
DEFAULT_MODEL = "qwen3-vl-8b"
MODEL = DEFAULT_MODEL  # overridden by --model

PAGE_HEIGHT = 792.0
BBOX_EXPAND = 5

# Pixel-density checkbox detector — ported from positional_matcher.py.
# Used as a fallback when text-X detection misses a non-"X" glyph (e.g.
# ✓, hand-drawn check, filled-in pen stroke). Threshold tuned from
# `< 0.08 empty, > 0.35 checked` per the broader project's memory; we
# pick a conservative single threshold that minimizes false positives.
PIXEL_CHECKBOX_DPI = 200
PIXEL_CHECKBOX_SCALE = PIXEL_CHECKBOX_DPI / 72.0
PIXEL_CHECKBOX_THRESHOLD = 0.18  # dark-pixel ratio above this = "checked"
PIXEL_DARK_VALUE = 140            # grayscale 0-255; below = "dark"

ANCHOR_LABELS = [
    "CARRIER", "NAIC CODE", "POLICY NUMBER", "EFFECTIVE DATE",
    "NAMED INSURED(S)", "CONSTRUCTION TYPE", "PRIMARY HEAT",
    "SECONDARY HEAT", "COVERAGES", "LIMITS", "SIGNATURE",
    "GENERAL INFORMATION", "CONTACT INFORMATION",
    "ADDITIONAL INTEREST", "UNDERLYING INSURANCE",
    "BLANKET SUMMARY", "TOTAL AREA", "YR BUILT",
]

# Per-document page → (template_filename, template_page_index) mapping.
# Currently scoped to 1800 N Stone (the canonical 25-page composite).
# For other docs we share the ACORD-125 sub-map.
PAGE_MAP_1800 = {
    1: ("acord_125.pdf", 0),
    2: ("acord_125.pdf", 1),
    3: ("acord_125.pdf", 2),
    4: ("acord_125.pdf", 3),
    6: ("acord_140.pdf", 0),
    7: ("acord_140.pdf", 1),
    8: ("acord_140.pdf", 2),
    9: ("acord_140.pdf", 0),
    10: ("acord_140.pdf", 1),
    11: ("acord_140.pdf", 2),
    12: ("acord_140.pdf", 0),
    13: ("acord_140.pdf", 1),
    14: ("acord_140.pdf", 2),
    16: ("acord_126_2014.pdf", 0),
    17: ("acord_126_2014.pdf", 1),
    18: ("acord_126_2014.pdf", 2),
    19: ("acord_126_2014.pdf", 3),
    21: ("acord_131.pdf", 0),
    22: ("acord_131.pdf", 1),
    23: ("acord_131.pdf", 2),
    24: ("acord_131.pdf", 3),
    25: ("acord_131.pdf", 4),
}

# For ACORD-125-only docs: pages 1..N each map sequentially to acord_125.
PAGE_MAP_125_ONLY = {pg: ("acord_125.pdf", pg - 1) for pg in range(1, 5)}

PDFS = {
    "Acord App (1800 North Stone LLC) 2026.pdf": ("acord_application", PAGE_MAP_1800),
    "26-27 Acord 125.pdf": ("acord_application", PAGE_MAP_125_ONLY),
    "26 GL Application for Prism Broward.pdf": ("acord_application", PAGE_MAP_125_ONLY),
    "26 XS Application for Prism Broward.pdf": ("acord_application", PAGE_MAP_125_ONLY),
    "ACORD_112322108_125.pdf": ("acord_application", PAGE_MAP_125_ONLY),
}


# ── BBOX helpers ──

def compute_dy(twords, fwords):
    dys = []
    for label in ANCHOR_LABELS:
        t_y = f_y = None
        for w in twords:
            if w["text"].strip() == label:
                t_y = w["top"]
                break
        for w in fwords:
            if w["text"].strip() == label:
                f_y = w["top"]
                break
        if t_y is not None and f_y is not None:
            dys.append(f_y - t_y)
    return sum(dys) / len(dys) if dys else 8.0


def bbox_extract_text(fwords, bbox_pdf, dy):
    x0, y0_pdf, x1, y1_pdf = bbox_pdf
    top = PAGE_HEIGHT - y1_pdf + dy
    bottom = PAGE_HEIGHT - y0_pdf + dy + BBOX_EXPAND
    hits = [w for w in fwords
            if w["x0"] >= x0 - 4 and w["x1"] <= x1 + 4
            and w["top"] >= top - 2 and w["bottom"] <= bottom + 2]
    hits.sort(key=lambda w: (round(w["top"], 0), w["x0"]))
    return " ".join(w["text"] for w in hits).strip() or None


def bbox_check_checkbox(fwords, bbox_pdf, dy):
    """An X is treated as belonging to a checkbox only when its CENTER is
       inside the RAW (dy-shifted) bbox — no BBOX_EXPAND padding."""
    x0, y0_pdf, x1, y1_pdf = bbox_pdf
    top = PAGE_HEIGHT - y1_pdf + dy
    bottom = PAGE_HEIGHT - y0_pdf + dy
    for w in fwords:
        if w["text"].strip() != "X":
            continue
        cx = (w["x0"] + w["x1"]) / 2.0
        cy = (w["top"] + w["bottom"]) / 2.0
        if x0 <= cx <= x1 and top <= cy <= bottom:
            return True
    return False


def checkbox_pixel_ratio(page_img_l, bbox_pdf, dy, scale=PIXEL_CHECKBOX_SCALE):
    """Crop the (dy-shifted) bbox from a grayscale page image, apply 20%
       inset to exclude the printed checkbox border, return dark-pixel
       ratio (0.0..1.0). Catches ✓/hand-drawn/filled-in marks that
       pdfplumber doesn't tokenize as 'X'.
       Returns None if the crop is too small to analyze."""
    if page_img_l is None:
        return None
    x0, y0_pdf, x1, y1_pdf = bbox_pdf
    top_pt = PAGE_HEIGHT - y1_pdf + dy
    bot_pt = PAGE_HEIGHT - y0_pdf + dy
    fx0 = max(0, int(x0 * scale))
    fy0 = max(0, int(top_pt * scale))
    fx1 = min(page_img_l.size[0], int(x1 * scale))
    fy1 = min(page_img_l.size[1], int(bot_pt * scale))
    if fx1 <= fx0 or fy1 <= fy0:
        return None
    crop = page_img_l.crop((fx0, fy0, fx1, fy1))
    cw, ch = crop.size
    if cw < 4 or ch < 4:
        return None
    inset_x = max(1, int(cw * 0.2))
    inset_y = max(1, int(ch * 0.2))
    inner = crop.crop((inset_x, inset_y, cw - inset_x, ch - inset_y))
    iw, ih = inner.size
    if iw < 2 or ih < 2:
        return None
    pixels = list(inner.getdata())
    total = len(pixels)
    if total == 0:
        return 0.0
    dark = sum(1 for p in pixels if p < PIXEL_DARK_VALUE)
    return dark / total


def bbox_check_checkbox_combined(fwords, bbox_pdf, dy, page_img_l):
    """Returns (is_checked, source) where source is 'text_x', 'pixel',
       or None. is_checked = True if EITHER text-X glyph found inside
       bbox OR pixel-density above threshold."""
    if bbox_check_checkbox(fwords, bbox_pdf, dy):
        return True, "text_x"
    ratio = checkbox_pixel_ratio(page_img_l, bbox_pdf, dy)
    if ratio is not None and ratio > PIXEL_CHECKBOX_THRESHOLD:
        return True, f"pixel:{ratio:.2f}"
    return False, None


def load_template_fields(tmpl_path: Path):
    """Return {page_index: [{name, type, tooltip, bbox}, ...]} for one template."""
    reader = pypdf.PdfReader(str(tmpl_path))
    by_page = {}
    for pn, page in enumerate(reader.pages):
        annots = page.get("/Annots", [])
        if not annots:
            continue
        fields = []
        for annot in annots:
            obj = annot.get_object()
            name = str(obj.get("/T", ""))
            ft = str(obj.get("/FT", ""))
            tu = str(obj.get("/TU", ""))
            rect = obj.get("/Rect", [])
            bbox = [float(r) for r in rect] if rect else None
            if name and bbox and bbox != [0.0, 1.0, 0.0, 1.0]:
                fields.append({"name": name, "type": ft, "tooltip": tu, "bbox": bbox})
        by_page[pn] = fields
    return by_page


def run_bbox_extraction(flat_path: Path, page_map: dict, templates_dir: Path):
    """Run anchor-aligned bbox extraction on all mapped pages of one PDF."""
    tmpl_fields_cache = {}
    tmpl_words_cache = {}

    fpdf = pdfplumber.open(str(flat_path))
    # Render each mapped page ONCE at PIXEL_CHECKBOX_DPI for pixel-density
    # checkbox detection. Avoids re-rendering per field.
    fitz_doc = fitz.open(str(flat_path))
    page_images = {}
    result = {}

    for pg_num, (tmpl_file, tmpl_pg) in page_map.items():
        if tmpl_file not in tmpl_fields_cache:
            tmpl_fields_cache[tmpl_file] = load_template_fields(templates_dir / tmpl_file)

        cache_key = f"{tmpl_file}_{tmpl_pg}"
        if cache_key not in tmpl_words_cache:
            tpdf = pdfplumber.open(str(templates_dir / tmpl_file))
            tmpl_words_cache[cache_key] = tpdf.pages[tmpl_pg].extract_words(
                keep_blank_chars=True, x_tolerance=2, y_tolerance=2)
            tpdf.close()

        twords = tmpl_words_cache[cache_key]
        tmpl_fields = tmpl_fields_cache.get(tmpl_file, {}).get(tmpl_pg, [])

        if pg_num - 1 >= len(fpdf.pages):
            continue
        fwords = fpdf.pages[pg_num - 1].extract_words(
            keep_blank_chars=True, x_tolerance=2, y_tolerance=2)
        dy = compute_dy(twords, fwords)

        # Lazy-render the page in grayscale at PIXEL_CHECKBOX_DPI for
        # pixel-density checkbox detection.
        if pg_num not in page_images:
            try:
                pix = fitz_doc[pg_num - 1].get_pixmap(dpi=PIXEL_CHECKBOX_DPI)
                page_images[pg_num] = Image.frombytes(
                    "RGB", [pix.width, pix.height], pix.samples).convert("L")
            except Exception:
                page_images[pg_num] = None
        page_img_l = page_images[pg_num]

        page_fields = {}
        for field in tmpl_fields:
            bbox = field["bbox"]
            name = field["name"]
            ftype = field["type"]
            tooltip = field["tooltip"]

            if ftype == "/Btn":
                is_checked, src_kind = bbox_check_checkbox_combined(
                    fwords, bbox, dy, page_img_l)
                src = "bbox" if src_kind is None else f"bbox:{src_kind}"
                page_fields[name] = {
                    "value": is_checked, "tooltip": tooltip,
                    "type": "checkbox", "source": src
                }
            else:
                text = bbox_extract_text(fwords, bbox, dy)
                if text:
                    page_fields[name] = {
                        "value": text, "tooltip": tooltip,
                        "type": "text", "source": "bbox"
                    }

        result[pg_num] = {"dy": dy, "fields": page_fields,
                          "template": f"{tmpl_file}#{tmpl_pg}"}

    fpdf.close()
    fitz_doc.close()
    return result


# ── VLM helpers ──

def call_vlm(img_b64: str, prompt: str, timeout: int = 240) -> dict:
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
        ]}],
        "temperature": 0.1,
        "max_tokens": 4096,
    }
    try:
        resp = requests.post(VLLM_URL, json=payload, timeout=timeout)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"] or ""
    except Exception as e:
        return {"_error": str(e)}

    if not content:
        return {"_error": "empty"}

    for sc, ec in [("{", "}"), ("[", "]")]:
        idx = content.find(sc)
        if idx >= 0:
            depth = 0
            for i in range(idx, len(content)):
                if content[i] == sc:
                    depth += 1
                elif content[i] == ec:
                    depth -= 1
                if depth == 0:
                    try:
                        return json.loads(content[idx:i + 1])
                    except Exception:
                        break
    return {"_raw": content[:4000]}


def get_page_schema(template_file, template_page_idx, templates_dir: Path):
    """Returns {'text_fields': [...], 'checkbox_fields': [...]} from the
       AcroForm template for the given page. Each entry is
       {name, tooltip, bbox}."""
    fields_by_page = load_template_fields(templates_dir / template_file)
    fields = fields_by_page.get(template_page_idx, [])
    text_fields = [f for f in fields if f["type"] == "/Tx"]
    btn_fields = [f for f in fields if f["type"] == "/Btn"]
    return {"text_fields": text_fields, "checkbox_fields": btn_fields}


# Common abbreviations / aliases that VLMs use for checkbox option labels.
# Built once globally; combined per-page with template-derived labels.
_CHECKBOX_LABEL_SYNONYMS = {
    "limitedliabilitycorporation": ["llc", "l.l.c", "limited liability corp"],
    "limitedpartnership": ["lp", "l.p", "limited partnership"],
    "subchapterscorporation": ["subchapter s", "subchapter \"s\"", "s-corp", "s corp"],
    "notforprofitorg": ["non-profit", "nonprofit", "not for profit"],
    "jointventure": ["joint venture", "jv"],
    "ownerscontractorsprotective": ["ocp"],
    "claimsmade": ["claims made", "claims-made"],
    "occurrence": ["occurrence", "per occurrence"],
    "perclaim": ["per claim"],
    "deductible": [],
    "perpolicy": ["per policy"],
    "perproject": ["per project"],
    "perlocation": ["per location"],
    "directbill": ["direct", "direct bill"],
    "agencybill": ["agency", "agency bill"],
    "producerbill": ["agency", "producer", "agency bill", "producer bill"],
    "inside": ["inside"],
    "outside": ["outside"],
    "owner": ["owner"],
    "tenant": ["tenant"],
    "individual": ["individual"],
    "corporation": ["corporation", "corp", "corp."],
    "partnership": ["partnership"],
    "trust": ["trust"],
}


def _camel_split(s: str) -> str:
    """CamelCase → space-separated words. 'LimitedLiabilityCorporation' → 'limited liability corporation'."""
    return re.sub(r"([a-z])([A-Z])", r"\1 \2", s).lower()


def get_checkbox_labels_for_page(schema: dict) -> set:
    """Build a set of normalized option-label strings that the VLM
       might emit for any /Btn field on this page. Sources:
         - The last camel-cased segment of each field name, e.g.
           'NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A'
           → 'limited liability corporation'
         - Hardcoded synonyms (LLC, LP, OCP, etc.)
       This is the template-driven label set used to filter VLM gap-fills."""
    labels = set()
    for f in schema.get("checkbox_fields", []):
        name = f["name"]
        # Strip [0], trailing _A/_B/_C, trailing 'Indicator'
        s = re.sub(r"\[\d+\]$", "", name)
        s = re.sub(r"_[A-Z]$", "", s)
        s = re.sub(r"Indicator$", "", s)
        # Take last underscore-separated segment
        last = s.split("_")[-1]
        # Add the camel-split version
        words = _camel_split(last).strip()
        if words:
            labels.add(words)
            # Add synonyms keyed on the camel-flat string
            key = last.lower()
            for syn in _CHECKBOX_LABEL_SYNONYMS.get(key, []):
                labels.add(syn.lower())
        # Also handle compound names like "AcceptCoverage" / "RejectCoverage"
        # by adding individual significant words
    # Add common forms that aren't always derivable:
    labels.update({"y", "n", "y/n", "yes", "no",
                   "[ ]", "[x]", "x", "✓", "☐", "☑"})
    return labels


def build_schema_prompt_block(schema: dict, max_text_fields: int = 0) -> str:
    """Build a SHORT prompt-injection block telling the VLM:
         - N CHECKBOX fields are bbox-handled — DO NOT emit checkbox values
         - For checkbox-fields, NEVER emit option-label strings
       Field-name listing is omitted by default to keep prompts short
       (was overloading the VLM on dense pages with 100+ fields).
       Set max_text_fields > 0 to include the listing."""
    btn_count = len(schema["checkbox_fields"])
    text_count = len(schema["text_fields"])

    lines = [
        "",
        f"=== TEMPLATE-DRIVEN CHECKBOX RULE ===",
        f"This page has {btn_count} checkboxes and {text_count} text fields.",
        "The bbox pipeline already determined every checkbox state.",
        "",
        "CHECKBOX HANDLING: NEVER emit a JSON value that is a checkbox-option",
        "LABEL. The forbidden patterns include (but are not limited to):",
        "  Y, N, Y/N, [ ], [X]",
        "  CORPORATION, LLC, INDIVIDUAL, PARTNERSHIP, TRUST, JOINT VENTURE",
        "  DIRECT, AGENCY (billing plan)",
        "  INSIDE, OUTSIDE (city limits)",
        "  OWNER, TENANT (interest)",
        "  PER CLAIM, PER OCCURRENCE (deductible basis)",
        "  ACCEPT COVERAGE, REJECT COVERAGE",
        "  BOILER, SOLID FUEL, RESISTIVE, SEMI-RESISTIVE, COMBUSTIBLE",
        "  CENTRAL STATION, LOCAL GONG, WITH KEYS, CLOCK HOURLY",
        "  CLAIMS MADE, OCCURRENCE",
        "  HOME, BUS, CELL (phone-type)",
        "  PRIMARY, SECONDARY",
        "",
        "If a value belongs to a checkbox, OMIT the field entirely from your JSON.",
        "Boolean checkbox values (true/false) are also unnecessary — bbox handles them.",
        "",
        "Focus your extraction on TEXT fields the user has filled in (names,",
        "addresses, phone numbers, dates, dollar amounts, descriptions).",
        "Skip blank fields. Never invent values for empty fields.",
        "",
    ]
    # Optional field-name listing (off by default to keep prompts short)
    if max_text_fields > 0 and schema["text_fields"]:
        lines.append("Text-field names (use these as JSON keys):")
        for f in schema["text_fields"][:max_text_fields]:
            tt = (f.get("tooltip") or "").strip()
            if tt.startswith("Enter "):
                tt = tt[6:]
            lines.append(f"  {f['name']} — {tt[:40]}")
        if len(schema["text_fields"]) > max_text_fields:
            lines.append(f"  (+{len(schema['text_fields']) - max_text_fields} more)")
        lines.append("")
    return "\n".join(lines)


def run_vlm_extraction(flat_path: Path, doc_type: str, dpi: int,
                       page_map: dict = None, templates_dir: Path = None):
    doc = fitz.open(str(flat_path))
    total_pages = len(doc)
    result = {}

    for pg in range(total_pages):
        pg_num = pg + 1
        pix = doc[pg].get_pixmap(dpi=dpi)
        img_b64 = base64.b64encode(pix.tobytes("png")).decode()

        # Hybrid prompt: legacy per-page prompt + a SHORT template-driven
        # checkbox-rule block. Tells the VLM that the bbox pipeline owns
        # checkboxes and not to emit option-label strings as values, but
        # keeps the well-tuned page-specific extraction guidance from
        # prompts.py. Short block avoids overloading the VLM on dense
        # multi-hundred-field pages.
        prompt = get_prompt(flat_path.name, pg_num, total_pages, doc_type)
        prompt = f"Page {pg_num}/{total_pages}.\n{prompt}"
        if page_map and pg_num in page_map and templates_dir:
            tmpl_file, tmpl_idx = page_map[pg_num]
            try:
                schema = get_page_schema(tmpl_file, tmpl_idx, templates_dir)
                # Short checkbox-rule block only (no field-name listing).
                # Tested: full schema with field listing (max_text_fields=200)
                # caused the VLM to hallucinate plausible-looking data for
                # listed fields when the page is blank — net negative.
                prompt = prompt + "\n" + build_schema_prompt_block(schema)
            except Exception as e:
                print(f"  (schema-block skipped: {e})", end="")

        print(f"    p{pg_num}/{total_pages}...", end=" ", flush=True)
        t0 = time.time()
        data = call_vlm(img_b64, prompt)
        ok = "_error" not in data and "_raw" not in data
        print(f"{'OK' if ok else 'FAIL'} ({time.time()-t0:.0f}s)", end="")
        if not ok:
            print(" retry...", end=" ", flush=True)
            time.sleep(2)
            data = call_vlm(img_b64, prompt)
            ok = "_error" not in data and "_raw" not in data
            print(f"{'OK' if ok else 'FAIL'}", end="")
        print()
        result[pg_num] = data

    doc.close()
    return result, total_pages


# ── Merge logic ──

def is_dollar_amount(val):
    # bool is a subclass of int — exclude explicitly so checkbox booleans
    # don't get mistaken for amounts.
    if isinstance(val, bool):
        return False
    if isinstance(val, (int, float)):
        return True
    if isinstance(val, str):
        return bool(re.match(r'^[\$]?[\d,]+\.?\d*$', val.replace(" ", "")))
    return False


def _norm_for_dedup(v) -> str:
    """Normalize a value for cross-source dedup: lowercase, strip $/,/whitespace."""
    return re.sub(r"\s+", " ",
                  str(v).lower().replace("$", "").replace(",", "")).strip()


# VLM commonly emits these exact strings when no real data exists in a field
# (it's reading the form's template/placeholder text and treating it as the
# value). We drop any VLM gap-fill whose normalized value matches.
_VLM_TEMPLATE_GARBAGE = {
    # Signature page placeholders
    "signature", "producer's signature", "applicant's signature",
    "producer's name (please print)", "producer's name", "applicant's name",
    "national producer number", "state producer license no",
    "state producer license no (required in florida)",
    "agency customer id", "policy number", "date",
    # Field-type labels captured as values
    "y/n", "[ ]", "[x]", "x", "yes/no",
    # Choice-field labels (these belong as boolean checkboxes, not values)
    "accept coverage", "reject coverage", "accept", "reject",
    "per claim", "per occurrence", "per claim per occurrence",
    "prem / ops", "prem/ops", "premium / operations", "products / completed operations",
    "claims made", "occurrence",
    # Phone-type / contact-type label leaks
    "home", "bus", "cell", "primary", "secondary",
    # Premises label leaks
    "inside", "outside", "owner", "tenant",
    # Heating/improvements label leaks
    "boiler", "solid fuel", "wood-fired", "wood fired",
    "resistive", "semi-resistive", "non-resistive", "combustible",
    "central station", "local gong", "with keys", "clock hourly",
    # Status of transaction label leaks
    "quote", "issue policy", "renew", "change", "cancel", "bound",
    # Misc form template
    "see attached", "see attached additional coverages overflow.",
}


def _is_all_none_dict(v) -> bool:
    """True if v is a (possibly nested) dict/list whose every leaf is None/empty."""
    if v is None:
        return True
    if isinstance(v, dict):
        return all(_is_all_none_dict(x) for x in v.values()) and len(v) > 0
    if isinstance(v, list):
        return all(_is_all_none_dict(x) for x in v) and len(v) > 0
    if isinstance(v, str):
        return v.strip() == ""
    return False


def _is_vlm_string_garbage(s_str: str) -> bool:
    """Pure-string check: True if a string is form template text not real data."""
    if not isinstance(s_str, str):
        return False
    s_str = s_str.strip()
    if not s_str:
        return True
    s_norm = _norm_for_dedup(s_str)
    if s_norm in _VLM_TEMPLATE_GARBAGE:
        return True
    if s_norm in ("☐", "☑", "□", "■", "◯"):
        return True
    # Numbered question: "1. DOES APPLICANT..." / "12. HAS APPLICANT..."
    if re.match(r"^\d+\.\s+[A-Z]", s_str):
        return True
    # Ends with "?" — form question
    if s_str.endswith("?") and len(s_str) > 12:
        return True
    # All-caps long phrase without digits/colons — form instruction
    if (s_str.isupper() and len(s_str) > 25
            and not any(c.isdigit() for c in s_str)
            and ":" not in s_str):
        return True
    # "I SELECT ..." / "I HAVE SELECTED ..." choice option labels
    if re.match(r"^I\s+(SELECT|HAVE\s+SELECTED|REJECT|ACCEPT)\b", s_str, re.IGNORECASE):
        return True
    return False


def _scrub_vlm_garbage(v):
    """Recursively replace template-garbage strings with None and drop
       branches that become empty. Returns the scrubbed value (or None
       if everything in this branch was garbage)."""
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, str):
        return None if _is_vlm_string_garbage(v) else v
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, list):
        out = [_scrub_vlm_garbage(x) for x in v]
        out = [x for x in out
               if x is not None and not _is_all_none_dict(x)]
        return out if out else None
    if isinstance(v, dict):
        out = {k: _scrub_vlm_garbage(x) for k, x in v.items()}
        out = {k: x for k, x in out.items()
               if x is not None and not _is_all_none_dict(x)}
        return out if out else None
    return v


def _is_vlm_template_garbage(v) -> bool:
    """True if a VLM-emitted value is purely form template text (not real data).
       Uses recursive scrub: if scrubbing returns None or an all-None dict, drop."""
    if v is None or isinstance(v, bool):
        return False
    scrubbed = _scrub_vlm_garbage(v)
    if scrubbed is None:
        return True
    if isinstance(scrubbed, (dict, list)) and _is_all_none_dict(scrubbed):
        return True
    return False


_BUSINESS_SUFFIXES = re.compile(
    r"\b(LLC|L\.?L\.?C|LP|L\.?P|INC|CORP|CO|LTD|GROUP|HOLDINGS|"
    r"PROPERTIES|APARTMENTS|PARTNERS|TRUST|ASSOCIATES|MANAGEMENT|"
    r"REALTY|VENTURES|ENTERPRISES)\b", re.IGNORECASE)
_STREET_ADDR = re.compile(r"^\d+\s+[A-Z]")  # "1800 North Stone..."


def is_label_not_value(val):
    """Heuristic that flags pdfplumber-extracted text as form-label noise
       rather than real data. Errs toward FALSE — never delete real data.

    Recognizes label SHAPE, not client identity:
      - Numbered-question prefix with literal period: "1. ANY..." / "12. HAS..."
      - Trailing colon labels: "PRODUCER'S SIGNATURE:"
      - All-caps text > 25 chars that doesn't look like a business name or
        a street address.
    """
    if not isinstance(val, str):
        return False
    s = val.strip()
    if len(s) < 3:
        return False

    # Numbered-question prefix REQUIRES period — "1." not just "1"
    if re.match(r"^\d+\.\s+[A-Z]", s):
        return True

    # Trailing colon: "PRODUCER'S SIGNATURE:" / "FEIN OR SOC SEC #:"
    if s.endswith(":") and len(s) > 5 and s.replace(":", "").strip().isupper():
        return True

    # All-caps long strings: only flag if no business-suffix and no street-addr
    if s.isupper() and len(s) > 25:
        if _BUSINESS_SUFFIXES.search(s):
            return False  # looks like a business name → keep
        if _STREET_ADDR.match(s):
            return False  # looks like a street address → keep
        # Real labels are typically pure text; data rows often contain
        # internal digits (codes/amounts/years). After stripping any leading
        # "12. " numbered prefix, if internal digits remain it's probably
        # data (e.g. "SWIMMING POOL 0 2 48925 T 1" = Schedule of Hazards row).
        stripped = re.sub(r"^\d+\.\s+", "", s)
        if any(c.isdigit() for c in stripped):
            return False
        return True

    return False


def _value_is_checkbox_label(v, labels: set) -> bool:
    """True if VLM-emitted string matches any template-derived checkbox
       option label (or known synonym)."""
    if not isinstance(v, str):
        return False
    s = _norm_for_dedup(v)
    if not s:
        return False
    if s in labels:
        return True
    # Also check tokenized: e.g. "PER OCCURRENCE" → tokens ["per","occurrence"]
    tokens = s.split()
    if len(tokens) <= 4:
        joined = " ".join(tokens)
        if joined in labels:
            return True
    return False


def merge_extractions(bbox_result, vlm_result, total_pages,
                      page_checkbox_labels: dict = None):
    merged = {"pages": {}}

    page_checkbox_labels = page_checkbox_labels or {}

    for pg_num in range(1, total_pages + 1):
        bbox_pg = bbox_result.get(pg_num, {}).get("fields", {})
        bbox_template = bbox_result.get(pg_num, {}).get("template", None)
        vlm_pg = vlm_result.get(pg_num, {})
        vlm_str = json.dumps(vlm_pg).lower()
        cb_labels = page_checkbox_labels.get(pg_num, set())

        page_out = {"page": pg_num,
                    "template": bbox_template,
                    "fields": {},
                    "discrepancies": []}

        # 1: bbox fields
        for fname, fdata in bbox_pg.items():
            val = fdata["value"]
            if isinstance(val, str) and is_label_not_value(val):
                page_out["discrepancies"].append({
                    "field": fname, "bbox_value": val,
                    "issue": "label_as_value",
                    "note": "BBOX captured label text; skipped",
                })
                continue
            page_out["fields"][fname] = {
                "value": val, "tooltip": fdata.get("tooltip", ""),
                "type": fdata["type"], "source": "bbox",
            }

        # 2: VLM fills gaps. We add a VLM-extracted value only if no bbox
        # field already has the SAME value (normalized). Substring containment
        # (the previous check) silently dropped short codes like "NY", "CA",
        # "100" whenever any bbox text contained those characters.
        bbox_values_norm = {_norm_for_dedup(f["value"])
                            for f in page_out["fields"].values()
                            if isinstance(f["value"], str)}

        def _vlm_already_has(v):
            """True if a bbox field with the same normalized value exists.
               For short values (< 4 chars) require word-boundary match in
               any bbox text rather than equality (state codes, claim suffixes)."""
            v_norm = _norm_for_dedup(v)
            if not v_norm:
                return False
            if v_norm in bbox_values_norm:
                return True
            if len(v_norm) >= 4:
                return False
            # Short value: word-boundary check across all bbox texts
            pat = re.compile(rf"\b{re.escape(v_norm)}\b")
            for f in page_out["fields"].values():
                tv = f.get("value")
                if isinstance(tv, str) and pat.search(tv.lower()):
                    return True
            return False

        if isinstance(vlm_pg, dict) and "_error" not in vlm_pg and "_raw" not in vlm_pg:
            for vkey, vval in vlm_pg.items():
                if isinstance(vval, dict):
                    for nk, nv in vval.items():
                        # Scrub recursively. If the result is None or empty,
                        # skip — the value was pure template garbage.
                        scrubbed = _scrub_vlm_garbage(nv)
                        if scrubbed in (None, "", [], {}):
                            continue
                        if _vlm_already_has(scrubbed):
                            continue
                        # Template-derived: drop if value matches a known
                        # checkbox option label on this page.
                        if _value_is_checkbox_label(scrubbed, cb_labels):
                            continue
                        page_out["fields"][f"vlm_{vkey}_{nk}"] = {
                            "value": scrubbed, "tooltip": f"{vkey}.{nk}",
                            "type": "text", "source": "vlm",
                        }
                elif isinstance(vval, list):
                    for i, item in enumerate(vval):
                        if isinstance(item, dict):
                            for nk, nv in item.items():
                                scrubbed = _scrub_vlm_garbage(nv)
                                if scrubbed in (None, "", [], {}, "0", "0.0", "$0.00"):
                                    continue
                                if _vlm_already_has(scrubbed):
                                    continue
                                if _value_is_checkbox_label(scrubbed, cb_labels):
                                    continue
                                page_out["fields"][f"vlm_{vkey}_{i}_{nk}"] = {
                                    "value": scrubbed, "tooltip": f"{vkey}[{i}].{nk}",
                                    "type": "text", "source": "vlm",
                                }
                else:
                    scrubbed = _scrub_vlm_garbage(vval)
                    if scrubbed in (None, "", "None", "null"):
                        continue
                    if _vlm_already_has(scrubbed):
                        continue
                    if _value_is_checkbox_label(scrubbed, cb_labels):
                        continue
                    page_out["fields"][f"vlm_{vkey}"] = {
                        "value": scrubbed, "tooltip": vkey,
                        "type": "text", "source": "vlm",
                    }

        # 3: cross-validate amounts
        for fname, fdata in page_out["fields"].items():
            if fdata["source"] == "bbox" and is_dollar_amount(fdata["value"]):
                val_str = str(fdata["value"]).replace(",", "").replace("$", "")
                if val_str and val_str not in vlm_str.replace(",", ""):
                    page_out["discrepancies"].append({
                        "field": fname, "bbox_value": fdata["value"],
                        "issue": "amount_not_in_vlm",
                        "note": "Dollar amount in BBOX not confirmed by VLM",
                    })

        if not page_out["discrepancies"]:
            del page_out["discrepancies"]

        merged["pages"][f"page_{pg_num}"] = page_out

    return merged


def process_pdf(fname: str, doc_type: str, page_map: dict,
                pdf_dir: Path, templates_dir: Path, dpi: int):
    flat_path = pdf_dir / fname
    if not flat_path.exists():
        return {"source_file": fname, "_error": f"PDF not found: {flat_path}"}

    print(f"  bbox extraction...")
    t0 = time.time()
    bbox_result = run_bbox_extraction(flat_path, page_map, templates_dir)
    bbox_pages = sum(1 for v in bbox_result.values() if v.get("fields"))
    bbox_field_count = sum(len(v.get("fields", {})) for v in bbox_result.values())
    print(f"    bbox: {bbox_pages} pages, {bbox_field_count} fields ({time.time()-t0:.0f}s)")

    print(f"  vlm extraction...")
    vlm_result, total_pages = run_vlm_extraction(
        flat_path, doc_type, dpi,
        page_map=page_map, templates_dir=templates_dir)

    print(f"  merging...")
    # Build per-page checkbox-label sets from the template (used by merge
    # step 2 to drop VLM gap-fills that are option labels).
    page_checkbox_labels = {}
    for pg_num, (tmpl_file, tmpl_idx) in page_map.items():
        try:
            schema = get_page_schema(tmpl_file, tmpl_idx, templates_dir)
            page_checkbox_labels[pg_num] = get_checkbox_labels_for_page(schema)
        except Exception:
            page_checkbox_labels[pg_num] = set()

    merged = merge_extractions(bbox_result, vlm_result, total_pages,
                                page_checkbox_labels=page_checkbox_labels)
    merged["source_file"] = fname
    merged["document_type"] = doc_type
    merged["model"] = MODEL
    merged["dpi"] = dpi
    merged["bbox_pages_with_data"] = bbox_pages
    merged["bbox_field_count"] = bbox_field_count
    return merged


def main():
    global MODEL
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?",
                    help="Specific PDF filename (default: all 5 ACORD apps)")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help="vLLM served-model-name (default: qwen3-vl-8b)")
    ap.add_argument("--pdf-dir", default=str(PDF_DIR))
    ap.add_argument("--templates-dir", default=str(TEMPLATES_DIR))
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    MODEL = args.model

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir = Path(args.pdf_dir)
    templates_dir = Path(args.templates_dir)

    # Sanity check vLLM
    try:
        r = requests.get("http://127.0.0.1:8000/v1/models", timeout=5)
        served = [m["id"] for m in r.json().get("data", [])]
        print(f"vLLM reachable. Models served: {served}")
        if MODEL not in served:
            print(f"WARNING: model id {MODEL} not in served list {served}")
    except Exception as e:
        print(f"ERROR: vLLM not reachable on 127.0.0.1:8000 ({e})")
        return 1

    pdfs = ({args.target: PDFS[args.target]} if args.target and args.target in PDFS
            else PDFS)

    summary = []
    for fname, (doc_type, page_map) in pdfs.items():
        safe = (fname.replace(" ", "_").replace("(", "").replace(")", "")
                .replace(".pdf", "").replace(".PDF", ""))
        out_path = out_dir / f"{safe}_merged.json"
        if out_path.exists() and not args.overwrite:
            print(f"SKIP merged: {fname}")
            continue

        print(f"\n{'='*70}\nMERGED: {fname}")
        t0 = time.time()
        result = process_pdf(fname, doc_type, page_map, pdf_dir, templates_dir, args.dpi)
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)
        elapsed = time.time() - t0
        bbox_n = result.get("bbox_field_count", 0)
        print(f"  -> {out_path.name} | bbox={bbox_n} fields | {elapsed:.0f}s")
        summary.append((fname, bbox_n, elapsed))

    print(f"\n{'='*70}\nSUMMARY")
    for fname, n, el in summary:
        print(f"  bbox={n:4d}  {el:5.0f}s  {fname}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
