"""
Merged extraction pipeline.
Combines anchor-aligned bbox extraction (good at structured amounts/checkboxes)
with VLM extraction (good at text fields/addresses/descriptions).
Flags discrepancies for review.
"""
import pdfplumber, pypdf, fitz, json, os, base64, requests, time, re, io
from PIL import Image

BASE = "/home/safdar/Desktop/inevoai/new_accord_extraction_project/"
PAGE_HEIGHT = 792.0
BBOX_EXPAND = 5
OLLAMA_URL = "http://localhost:11434/api/chat"
VLM_MODEL = "qwen3-vl:4b-instruct-q4_K_M"

ANCHOR_LABELS = [
    "CARRIER", "NAIC CODE", "POLICY NUMBER", "EFFECTIVE DATE",
    "NAMED INSURED(S)", "CONSTRUCTION TYPE", "PRIMARY HEAT",
    "SECONDARY HEAT", "COVERAGES", "LIMITS", "SIGNATURE",
    "GENERAL INFORMATION", "CONTACT INFORMATION",
    "ADDITIONAL INTEREST", "UNDERLYING INSURANCE",
    "BLANKET SUMMARY", "TOTAL AREA", "YR BUILT",
]

PAGE_MAP = {
    1: ("templates/acord_125.pdf", 0),
    2: ("templates/acord_125.pdf", 1),
    3: ("templates/acord_125.pdf", 2),
    4: ("templates/acord_125.pdf", 3),
    6: ("templates/acord_140.pdf", 0),
    7: ("templates/acord_140.pdf", 1),
    8: ("templates/acord_140.pdf", 2),
    9: ("templates/acord_140.pdf", 0),
    10: ("templates/acord_140.pdf", 1),
    11: ("templates/acord_140.pdf", 2),
    12: ("templates/acord_140.pdf", 0),
    13: ("templates/acord_140.pdf", 1),
    14: ("templates/acord_140.pdf", 2),
    16: ("templates/acord_126_2014.pdf", 0),
    17: ("templates/acord_126_2014.pdf", 1),
    18: ("templates/acord_126_2014.pdf", 2),
    19: ("templates/acord_126_2014.pdf", 3),
    21: ("templates/acord_131.pdf", 0),
    22: ("templates/acord_131.pdf", 1),
    23: ("templates/acord_131.pdf", 2),
    24: ("templates/acord_131.pdf", 3),
    25: ("templates/acord_131.pdf", 4),
}

# ── BBOX helpers ──

def compute_dy(twords, fwords):
    dys = []
    for label in ANCHOR_LABELS:
        t_y = f_y = None
        for w in twords:
            if w["text"].strip() == label: t_y = w["top"]; break
        for w in fwords:
            if w["text"].strip() == label: f_y = w["top"]; break
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
    x0, y0_pdf, x1, y1_pdf = bbox_pdf
    top = PAGE_HEIGHT - y1_pdf + dy
    bottom = PAGE_HEIGHT - y0_pdf + dy + BBOX_EXPAND
    tol = 5
    for w in fwords:
        if w["text"].strip() == "X":
            if (w["x0"] >= x0 - tol and w["x1"] <= x1 + tol
                and w["top"] >= top - tol and w["bottom"] <= bottom + tol):
                return True
    return False


def run_bbox_extraction(flat_path):
    """Run anchor-aligned bbox extraction on all mapped pages."""
    # Load template fields
    tmpl_fields_cache = {}
    tmpl_words_cache = {}

    for pg_num, (tmpl_file, tmpl_pg) in PAGE_MAP.items():
        if tmpl_file not in tmpl_fields_cache:
            reader = pypdf.PdfReader(BASE + tmpl_file)
            by_page = {}
            for pn, page in enumerate(reader.pages):
                annots = page.get("/Annots", [])
                if not annots: continue
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
            tmpl_fields_cache[tmpl_file] = by_page

    fpdf = pdfplumber.open(flat_path)
    result = {}

    for pg_num, (tmpl_file, tmpl_pg) in PAGE_MAP.items():
        cache_key = f"{tmpl_file}_{tmpl_pg}"
        if cache_key not in tmpl_words_cache:
            tpdf = pdfplumber.open(BASE + tmpl_file)
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

        page_fields = {}
        for field in tmpl_fields:
            bbox = field["bbox"]
            name = field["name"]
            ftype = field["type"]
            tooltip = field["tooltip"]

            if ftype == "/Btn":
                if bbox_check_checkbox(fwords, bbox, dy):
                    page_fields[name] = {
                        "value": True, "tooltip": tooltip, "type": "checkbox", "source": "bbox"
                    }
            else:
                text = bbox_extract_text(fwords, bbox, dy)
                if text:
                    page_fields[name] = {
                        "value": text, "tooltip": tooltip, "type": "text", "source": "bbox"
                    }

        result[pg_num] = {"dy": dy, "fields": page_fields}

    fpdf.close()
    return result


# ── VLM helpers ──

def vlm_extract_page(img_b64, pg_num, total_pages):
    prompt = f"""Page {pg_num}/{total_pages}. Extract ALL filled data from this insurance document page into JSON.
Use field labels as keys, filled values as values. Include all text fields, checked checkboxes (true),
table data, amounts, dates, addresses. Skip empty fields. Return ONLY valid JSON. /no_think"""

    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": VLM_MODEL,
            "messages": [{"role": "user", "content": prompt, "images": [img_b64]}],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 4096},
        }, timeout=180)
        content = resp.json().get("message", {}).get("content", "")
    except Exception as e:
        return {"_error": str(e)}

    if not content:
        return {"_error": "empty"}

    # Parse JSON
    for sc, ec in [("{", "}"), ("[", "]")]:
        idx = content.find(sc)
        if idx >= 0:
            depth = 0
            for i in range(idx, len(content)):
                if content[i] == sc: depth += 1
                elif content[i] == ec: depth -= 1
                if depth == 0:
                    try:
                        return json.loads(content[idx:i + 1])
                    except:
                        break
    return {"_raw": content[:2000]}


def run_vlm_extraction(flat_path, total_pages):
    """Run VLM extraction on all pages."""
    doc = fitz.open(flat_path)
    result = {}

    for pg_num in range(1, total_pages + 1):
        page = doc[pg_num - 1]
        pix = page.get_pixmap(dpi=150)
        img_b64 = base64.b64encode(pix.tobytes("png")).decode()

        print(f"  VLM page {pg_num}/{total_pages}...", end=" ", flush=True)
        t0 = time.time()
        data = vlm_extract_page(img_b64, pg_num, total_pages)
        ok = "_error" not in data and "_raw" not in data
        print(f"{'OK' if ok else 'FAIL'} ({time.time()-t0:.0f}s)")

        result[pg_num] = data

    doc.close()
    return result


# ── Merge logic ──

def is_dollar_amount(val):
    if isinstance(val, (int, float)):
        return True
    if isinstance(val, str):
        return bool(re.match(r'^[\$]?[\d,]+\.?\d*$', val.replace(" ", "")))
    return False


def is_label_not_value(val):
    """Heuristic: check if a string looks like a form label rather than data."""
    if not isinstance(val, str):
        return False
    if len(val) < 3:
        return False
    # Labels are typically ALL CAPS and long
    if val.isupper() and len(val) > 25:
        # Exceptions: known data values that are uppercase
        exceptions = ["LLC", "LP", "INC", "STONE", "TUCSON", "MIAMI", "PLANTATION"]
        if not any(e in val for e in exceptions):
            return True
    # Check for question patterns
    if re.match(r'^\d+\.?\s+[A-Z]', val):
        return True
    return False


def merge_extractions(bbox_result, vlm_result, total_pages):
    """Merge bbox and VLM extractions. Prefer bbox for amounts/checkboxes, VLM for text."""
    merged = {"pages": {}}

    for pg_num in range(1, total_pages + 1):
        bbox_pg = bbox_result.get(pg_num, {}).get("fields", {})
        vlm_pg = vlm_result.get(pg_num, {})
        vlm_str = json.dumps(vlm_pg).lower()

        page_out = {"page": pg_num, "fields": {}, "discrepancies": []}

        # Step 1: Take all bbox fields
        for fname, fdata in bbox_pg.items():
            val = fdata["value"]
            tooltip = fdata.get("tooltip", "")

            # Skip if it's a label captured as value
            if isinstance(val, str) and is_label_not_value(val):
                # Check if VLM has a better value for this tooltip
                page_out["discrepancies"].append({
                    "field": fname,
                    "bbox_value": val,
                    "issue": "label_as_value",
                    "note": "BBOX captured label text; skipped",
                })
                continue

            page_out["fields"][fname] = {
                "value": val,
                "tooltip": tooltip,
                "type": fdata["type"],
                "source": "bbox",
            }

        # Step 2: Check VLM for values bbox missed
        if isinstance(vlm_pg, dict) and "_error" not in vlm_pg and "_raw" not in vlm_pg:
            for vkey, vval in vlm_pg.items():
                if isinstance(vval, dict):
                    # Nested object (e.g. named_insured: {name, address})
                    for nk, nv in vval.items():
                        merged_key = f"vlm_{vkey}_{nk}"
                        if nv and not any(str(nv).lower() in str(f["value"]).lower()
                                         for f in page_out["fields"].values()
                                         if isinstance(f["value"], str)):
                            page_out["fields"][merged_key] = {
                                "value": nv, "tooltip": f"{vkey}.{nk}", "type": "text", "source": "vlm",
                            }
                elif isinstance(vval, list):
                    for i, item in enumerate(vval):
                        if isinstance(item, dict):
                            for nk, nv in item.items():
                                merged_key = f"vlm_{vkey}_{i}_{nk}"
                                if nv and str(nv) not in ("", "0", "0.0", "$0.00"):
                                    if not any(str(nv).lower() in str(f["value"]).lower()
                                              for f in page_out["fields"].values()
                                              if isinstance(f["value"], str)):
                                        page_out["fields"][merged_key] = {
                                            "value": nv, "tooltip": f"{vkey}[{i}].{nk}",
                                            "type": "text", "source": "vlm",
                                        }
                elif vval and str(vval) not in ("", "None", "null"):
                    # Check if this value already exists in bbox fields
                    val_str = str(vval).lower()
                    already_have = any(
                        val_str in str(f["value"]).lower()
                        for f in page_out["fields"].values()
                        if isinstance(f["value"], str)
                    )
                    if not already_have:
                        merged_key = f"vlm_{vkey}"
                        page_out["fields"][merged_key] = {
                            "value": vval, "tooltip": vkey, "type": "text", "source": "vlm",
                        }

        # Step 3: Cross-validate — flag where bbox and VLM disagree on amounts
        for fname, fdata in page_out["fields"].items():
            if fdata["source"] == "bbox" and is_dollar_amount(fdata["value"]):
                val_str = str(fdata["value"]).replace(",", "").replace("$", "")
                if val_str and val_str not in vlm_str.replace(",", ""):
                    page_out["discrepancies"].append({
                        "field": fname,
                        "bbox_value": fdata["value"],
                        "issue": "amount_not_in_vlm",
                        "note": "Dollar amount in BBOX not confirmed by VLM",
                    })

        if not page_out["discrepancies"]:
            del page_out["discrepancies"]

        merged["pages"][f"page_{pg_num}"] = page_out

    return merged


# ── Main ──

def run_merged_pipeline(flat_path):
    """Run the full merged pipeline."""
    doc = fitz.open(flat_path)
    total_pages = len(doc)
    doc.close()

    print(f"Source: {flat_path}")
    print(f"Pages: {total_pages}")

    # Step 1: BBOX extraction
    print("\n[1/3] Running bbox extraction...")
    t0 = time.time()
    bbox_result = run_bbox_extraction(flat_path)
    bbox_fields = sum(len(p["fields"]) for p in bbox_result.values())
    print(f"  Done: {bbox_fields} fields in {time.time()-t0:.1f}s")

    # Step 2: VLM extraction
    print("\n[2/3] Running VLM extraction...")
    t0 = time.time()
    vlm_result = run_vlm_extraction(flat_path, total_pages)
    vlm_ok = sum(1 for v in vlm_result.values()
                 if isinstance(v, dict) and "_error" not in v and "_raw" not in v)
    print(f"  Done: {vlm_ok}/{total_pages} pages OK in {time.time()-t0:.0f}s")

    # Step 3: Merge
    print("\n[3/3] Merging...")
    merged = merge_extractions(bbox_result, vlm_result, total_pages)

    # Stats
    total_fields = sum(len(p["fields"]) for p in merged["pages"].values())
    bbox_sourced = sum(1 for p in merged["pages"].values()
                       for f in p["fields"].values() if f.get("source") == "bbox")
    vlm_sourced = sum(1 for p in merged["pages"].values()
                      for f in p["fields"].values() if f.get("source") == "vlm")
    discrepancies = sum(len(p.get("discrepancies", [])) for p in merged["pages"].values())

    merged["metadata"] = {
        "source_file": os.path.basename(flat_path),
        "total_pages": total_pages,
        "total_fields": total_fields,
        "bbox_sourced": bbox_sourced,
        "vlm_sourced": vlm_sourced,
        "discrepancies": discrepancies,
        "method": "merged_bbox+vlm",
    }

    print(f"\n  Total fields: {total_fields}")
    print(f"  From BBOX: {bbox_sourced}")
    print(f"  From VLM: {vlm_sourced}")
    print(f"  Discrepancies: {discrepancies}")

    return merged


if __name__ == "__main__":
    import sys

    flat_path = sys.argv[1] if len(sys.argv) > 1 else \
        BASE + "Acord App (1800 North Stone LLC) 2026.pdf"

    merged = run_merged_pipeline(flat_path)

    out_path = BASE + "merged_extraction.json"
    with open(out_path, "w") as f:
        json.dump(merged, f, indent=2)

    print(f"\nSaved to {out_path}")
