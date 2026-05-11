"""
Streamlit visual verifier — explore extractions across all model runs side-by-side.

Run:
  streamlit run app.py --server.headless true

What it shows:
  - Source PDF page (rendered at DPI 150)
  - Bbox-checkbox overlay (green=true, red=false, gray=unmapped, yellow X glyphs)
  - Extracted JSON from any of the model runs
  - Comparison mode: two models side-by-side
"""
import io
import json
import os
import subprocess
import zipfile
from pathlib import Path

import fitz
import pdfplumber
import pypdf
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

st.set_page_config(page_title="ACORD Extractor — Visual Verifier", layout="wide")

BASE = Path(__file__).parent
PDF_DIR = BASE / "pdfs"
TEMPLATES_DIR = BASE / "templates"

PAGE_HEIGHT = 792.0
DPI = 150
SCALE = DPI / 72.0

PAGE_MAPS = {
    "Acord App (1800 North Stone LLC) 2026.pdf": {
        1: ("acord_125.pdf", 0), 2: ("acord_125.pdf", 1),
        3: ("acord_125.pdf", 2), 4: ("acord_125.pdf", 3),
        6: ("acord_140.pdf", 0), 7: ("acord_140.pdf", 1), 8: ("acord_140.pdf", 2),
        9: ("acord_140.pdf", 0), 10: ("acord_140.pdf", 1), 11: ("acord_140.pdf", 2),
        12: ("acord_140.pdf", 0), 13: ("acord_140.pdf", 1), 14: ("acord_140.pdf", 2),
        16: ("acord_126_2014.pdf", 0), 17: ("acord_126_2014.pdf", 1),
        18: ("acord_126_2014.pdf", 2), 19: ("acord_126_2014.pdf", 3),
        21: ("acord_131.pdf", 0), 22: ("acord_131.pdf", 1), 23: ("acord_131.pdf", 2),
        24: ("acord_131.pdf", 3), 25: ("acord_131.pdf", 4),
    },
    "26-27 Acord 125.pdf": {pg: ("acord_125.pdf", pg - 1) for pg in range(1, 5)},
    "26 GL Application for Prism Broward.pdf": {pg: ("acord_125.pdf", pg - 1) for pg in range(1, 5)},
    "26 XS Application for Prism Broward.pdf": {pg: ("acord_125.pdf", pg - 1) for pg in range(1, 5)},
    "ACORD_112322108_125.pdf": {pg: ("acord_125.pdf", pg - 1) for pg in range(1, 5)},
}

MODEL_RUNS = {
    "merged_qwen3vl8b (bbox+VLM)":          {"dir": "merged_qwen3vl8b",   "suffix": "_merged",   "shape": "merged"},
    "merged_loss_runs (pdfplumber+VLM)":    {"dir": "merged_loss_runs",   "suffix": "_lossrun",  "shape": "lossrun"},
    "qwen3-vl-8b (pure VLM)":               {"dir": "vllm_qwen3vl8b",     "suffix": "_targeted", "shape": "vlm"},
    "qwen2.5-vl-7b":                        {"dir": "vllm_qwen2_5vl_7b",  "suffix": "_targeted", "shape": "vlm"},
    "internvl3-8b":                         {"dir": "vllm_internvl3_8b",  "suffix": "_targeted", "shape": "vlm"},
    "qwen2.5-vl-32b-awq (partial, DPI100)": {"dir": "vllm_qwen2_5vl_32b", "suffix": "_targeted", "shape": "vlm"},
    "qwen3-vl:4b (Ollama baseline)":        {"dir": "targeted_extractions", "suffix": "_targeted", "shape": "vlm"},
}

ANCHOR_LABELS = ["CARRIER", "NAIC CODE", "POLICY NUMBER", "EFFECTIVE DATE",
                 "NAMED INSURED(S)", "CONSTRUCTION TYPE", "PRIMARY HEAT",
                 "SECONDARY HEAT", "COVERAGES", "LIMITS", "SIGNATURE",
                 "GENERAL INFORMATION", "CONTACT INFORMATION",
                 "ADDITIONAL INTEREST", "UNDERLYING INSURANCE",
                 "BLANKET SUMMARY", "TOTAL AREA", "YR BUILT"]


def safe_name(pdf_name: str) -> str:
    return (pdf_name.replace(" ", "_").replace("(", "").replace(")", "")
            .replace(".pdf", "").replace(".PDF", ""))


@st.cache_data
def list_pdfs():
    if not PDF_DIR.exists():
        return []
    return sorted([f.name for f in PDF_DIR.iterdir() if f.suffix.lower() == ".pdf"])


@st.cache_data
def get_pdf_page_count(pdf_name):
    doc = fitz.open(str(PDF_DIR / pdf_name))
    n = len(doc)
    doc.close()
    return n


@st.cache_data
def render_pdf_page(pdf_name, page_num, dpi=DPI):
    doc = fitz.open(str(PDF_DIR / pdf_name))
    pix = doc[page_num - 1].get_pixmap(dpi=dpi)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    doc.close()
    return img


def _file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except Exception:
        return 0.0


# Map of submission folders → (extraction_dir, gt_filename_stem) for the
# all-submissions bundle. Add new submissions here as they're processed.
SUBMISSIONS_BUNDLE = [
    ("sub1_1800_north_stone",       "input_extracted",   "gt_1800_north_stone"),
    ("sub2_urban_southwest",        "input_extracted_2", "gt_urban_southwest"),
    ("sub3_varsity_campus",         "input_extracted_3", "gt_varsity_campus"),
    ("sub4_prism_broward",          "input_extracted_4", "gt_prism_broward"),
    ("sub5_rise_campus_quarters",   "input_extracted_5", "gt_rise_campus_quarters"),
]


def _bundle_cache_key() -> tuple:
    """Tuple of mtimes across mapped, GT, and every per-doc JSON in each
       extraction dir — cache busts when any source changes."""
    mtimes = []
    for _, ext_dir, gt_stem in SUBMISSIONS_BUNDLE:
        ext_path = BASE / ext_dir
        if ext_path.exists():
            for f in sorted(ext_path.iterdir()):
                if f.is_file():
                    mtimes.append((f.name, _file_mtime(f)))
        mtimes.append(("gt/" + gt_stem,
                        _file_mtime(BASE / "gt" / f"{gt_stem}.json")))
    return tuple(mtimes)


@st.cache_data
def _build_submissions_bundle_cached(cache_key: tuple):
    """Build a zip bundle of all submissions' full extraction trees +
       mapped JSON + GT + compare reports, in-memory. Returns
       (bytes, summary_string) or (None, "")."""
    py = (BASE.parent.parent / ".venv/bin/python")
    if not py.exists():
        py = "python"
    rows = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for sub_name, ext_dir, gt_stem in SUBMISSIONS_BUNDLE:
            mapped = BASE / ext_dir / "submission_mapped.json"
            gt = BASE / "gt" / f"{gt_stem}.json"
            ext_path = BASE / ext_dir
            if not (mapped.exists() and gt.exists() and ext_path.exists()):
                continue
            # Per-doc extraction JSONs (everything in input_extracted_*/)
            for f in sorted(ext_path.iterdir()):
                if not f.is_file():
                    continue
                zf.write(f, f"{sub_name}/extracted/{f.name}")
            # GT + mapped at the submission root for quick access
            zf.write(gt, f"{sub_name}/{gt.name}")
            # Run gt_compare to produce a fresh report
            try:
                proc = subprocess.run(
                    [str(py), str(BASE / "gt_compare.py"), str(gt), str(mapped)],
                    capture_output=True, text=True, timeout=30, cwd=str(BASE),
                )
                report = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
            except Exception as e:
                report = f"(gt_compare failed: {e})"
            zf.writestr(f"{sub_name}/gt_compare_report.txt", report)
            import re as _re
            m = _re.search(r"CORRECT\s*:\s*(\d+)\s*/\s*(\d+)\s*\(([\d.]+)%\)", report)
            if m:
                rows.append((sub_name, int(m.group(1)), int(m.group(2)),
                              float(m.group(3))))
            else:
                rows.append((sub_name, 0, 0, 0.0))
        # README with accuracy table
        if rows:
            tot_c = sum(r[1] for r in rows)
            tot_t = sum(r[2] for r in rows)
            tot_pct = (tot_c / tot_t * 100) if tot_t else 0.0
            lines = [
                "# Insurance Submission Extraction — Bundle",
                "",
                "## Contents",
                "Each `sub*/` folder contains:",
                "- `extracted/` — per-document extraction JSONs (one per",
                "  source PDF / xlsx / docx) plus `submission_mapped.json` and",
                "  `ALL.json` master",
                "- `gt_*.json` — hand-curated ground truth from source documents",
                "- `gt_compare_report.txt` — field-by-field comparison",
                "",
                "## Accuracy",
                "| Submission | CORRECT | TOTAL | Accuracy |",
                "|---|---|---|---|",
            ]
            for name, c, t, pct in rows:
                lines.append(f"| {name} | {c} | {t} | {pct:.1f}% |")
            lines.append(f"| **Overall** | **{tot_c}** | **{tot_t}** | **{tot_pct:.1f}%** |")
            zf.writestr("README.md", "\n".join(lines) + "\n")
    if not rows:
        return None, ""
    summary = f"{len(rows)} subs, overall " + (
        f"{sum(r[1] for r in rows)}/{sum(r[2] for r in rows)} "
        f"({sum(r[1] for r in rows) / max(sum(r[2] for r in rows), 1) * 100:.1f}%)"
    )
    return buf.getvalue(), summary


def _build_submissions_bundle():
    return _build_submissions_bundle_cached(_bundle_cache_key())


@st.cache_data
def _load_extraction_cached(pdf_name, model_label, mtime):
    """mtime is part of the cache key — busts cache automatically when
       the underlying JSON file changes on disk."""
    cfg = MODEL_RUNS[model_label]
    json_path = BASE / cfg["dir"] / f"{safe_name(pdf_name)}{cfg['suffix']}.json"
    if not json_path.exists():
        return None
    return json.load(open(json_path))


def load_extraction(pdf_name, model_label):
    cfg = MODEL_RUNS[model_label]
    json_path = BASE / cfg["dir"] / f"{safe_name(pdf_name)}{cfg['suffix']}.json"
    return _load_extraction_cached(pdf_name, model_label, _file_mtime(json_path))


def page_data_from_extraction(extraction, page_num, model_label):
    if extraction is None:
        return None
    cfg = MODEL_RUNS[model_label]
    shape = cfg.get("shape", "vlm")
    if shape == "merged":
        return extraction.get("pages", {}).get(f"page_{page_num}")
    if shape == "lossrun":
        # Re-shape into a single per-page bundle:
        #   {vlm, pdfplumber_page, parsed_claims, discrepancies}
        vlm = None
        for p in extraction.get("vlm_pages", []) or []:
            if p.get("page") == page_num:
                vlm = p.get("data"); break
        pdfp = None
        for p in (extraction.get("pdfplumber", {}) or {}).get("pages", []):
            if p.get("page") == page_num:
                pdfp = p; break
        parsed = [c for c in extraction.get("pdfplumber_parsed_claims", [])
                  if c.get("_page") == page_num]
        discs = [d for d in extraction.get("discrepancies", [])
                 if d.get("page") == page_num]
        return {"vlm": vlm, "pdfplumber_page": pdfp,
                "parsed_claims": parsed, "discrepancies": discs}
    pages = extraction.get("pages", [])
    if isinstance(pages, list):
        for p in pages:
            if p.get("page") == page_num:
                return p.get("data")
    return None


@st.cache_data
def compute_dy_for_page(pdf_name, page_num, tmpl_file, tmpl_page):
    fpdf = pdfplumber.open(str(PDF_DIR / pdf_name))
    fwords = fpdf.pages[page_num - 1].extract_words(
        keep_blank_chars=True, x_tolerance=2, y_tolerance=2)
    fpdf.close()
    tpdf = pdfplumber.open(str(TEMPLATES_DIR / tmpl_file))
    twords = tpdf.pages[tmpl_page].extract_words(
        keep_blank_chars=True, x_tolerance=2, y_tolerance=2)
    tpdf.close()

    dys = []
    for label in ANCHOR_LABELS:
        t_y = f_y = None
        for w in twords:
            if w["text"].strip() == label:
                t_y = w["top"]; break
        for w in fwords:
            if w["text"].strip() == label:
                f_y = w["top"]; break
        if t_y is not None and f_y is not None:
            dys.append(f_y - t_y)
    return (sum(dys) / len(dys) if dys else 8.0), fwords


@st.cache_data
def load_template_btn_fields(tmpl_file, tmpl_page):
    reader = pypdf.PdfReader(str(TEMPLATES_DIR / tmpl_file))
    annots = reader.pages[tmpl_page].get("/Annots", []) or []
    fields = []
    for annot in annots:
        obj = annot.get_object()
        if str(obj.get("/FT", "")) != "/Btn":
            continue
        rect = obj.get("/Rect", [])
        bbox = [float(r) for r in rect] if rect else None
        name = str(obj.get("/T", ""))
        if name and bbox and bbox != [0.0, 1.0, 0.0, 1.0]:
            fields.append({"name": name, "bbox": bbox,
                           "tooltip": str(obj.get("/TU", ""))})
    return fields


def short_label(field_name: str, max_len: int = 40) -> str:
    s = field_name.replace("[0]", "")
    parts = s.split("_")
    if parts and len(parts[-1]) <= 2:
        parts = parts[:-1]
    s = "_".join(parts)
    if len(s) > max_len:
        s = "…" + s[-(max_len - 1):]
    return s


def overlay_image(pdf_name, page_num, merged_fields, show_text_fields=True):
    """Render page with ALL extracted fields' bboxes overlaid:
       - Green rectangle: /Btn checkbox detected as TRUE
       - Red rectangle (faint): /Btn checkbox detected as FALSE
       - Blue rectangle + value: /Tx text field with extracted value
       - Yellow circle: raw 'X' glyph detected by pdfplumber
       Hover/inspect a single field via the Field Inspector mode."""
    img = render_pdf_page(pdf_name, page_num).copy()
    if pdf_name not in PAGE_MAPS or page_num not in PAGE_MAPS[pdf_name]:
        return img

    tmpl_file, tmpl_page = PAGE_MAPS[pdf_name][page_num]
    dy, fwords = compute_dy_for_page(pdf_name, page_num, tmpl_file, tmpl_page)
    all_fields = get_all_template_fields(tmpl_file, tmpl_page)
    btn_fields = [f for f in all_fields if f["type"] == "/Btn"]
    text_fields = [f for f in all_fields if f["type"] == "/Tx"]

    draw = ImageDraw.Draw(img, "RGBA")
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
        font_small = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
    except Exception:
        font = ImageFont.load_default()
        font_small = font

    # Yellow circles around raw X glyphs
    for w in fwords:
        if w["text"].strip() == "X":
            cx = (w["x0"] + w["x1"]) / 2 * SCALE
            cy = (w["top"] + w["bottom"]) / 2 * SCALE
            draw.ellipse((cx - 8, cy - 8, cx + 8, cy + 8),
                         outline=(255, 200, 0, 255), width=2)

    # Checkbox bboxes
    n_t = n_f = n_m = 0
    for f in btn_fields:
        x0, y0_pdf, x1, y1_pdf = f["bbox"]
        top = PAGE_HEIGHT - y1_pdf + dy
        bot = PAGE_HEIGHT - y0_pdf + dy
        rect = (x0 * SCALE, top * SCALE, x1 * SCALE, bot * SCALE)

        fld = merged_fields.get(f["name"]) if merged_fields else None
        if fld is None:
            color = (140, 140, 140, 255); n_m += 1
            width = 1
        elif fld.get("value") is True:
            color = (0, 200, 0, 255); n_t += 1
            width = 2
        else:
            color = (220, 60, 60, 200); n_f += 1
            width = 1
        draw.rectangle(rect, outline=color, width=width)

        if fld and fld.get("value") is True:
            label = short_label(f["name"])
            tx, ty = rect[2] + 4, rect[1] - 2
            try:
                bb = draw.textbbox((tx, ty), label, font=font)
            except AttributeError:
                bb = (tx, ty, tx + len(label) * 6, ty + 12)
            draw.rectangle((bb[0] - 2, bb[1], bb[2] + 2, bb[3]),
                           fill=(255, 255, 255, 230))
            draw.text((tx, ty), label, fill=color[:3], font=font)

    # Text-field bboxes (only those with extracted values)
    n_text = 0
    if show_text_fields:
        for f in text_fields:
            fld = merged_fields.get(f["name"]) if merged_fields else None
            if not fld:
                continue
            v = fld.get("value")
            if v is None or v == "" or v is False:
                continue
            x0, y0_pdf, x1, y1_pdf = f["bbox"]
            top = PAGE_HEIGHT - y1_pdf + dy
            bot = PAGE_HEIGHT - y0_pdf + dy
            rect = (x0 * SCALE, top * SCALE, x1 * SCALE, bot * SCALE)

            # Color: blue for bbox-source, orange for VLM gap-fill
            src = fld.get("source", "")
            if src.startswith("bbox"):
                color = (40, 100, 240, 220)  # blue
            else:
                color = (250, 140, 0, 220)  # orange = VLM
            draw.rectangle(rect, outline=color, width=1)
            n_text += 1

            # Show value snippet INSIDE-or-just-above the bbox (truncated)
            v_str = str(v)[:50]
            if v_str:
                tx = rect[0] + 2
                ty = max(0, rect[1] - 11)  # above the bbox
                try:
                    bb = draw.textbbox((tx, ty), v_str, font=font_small)
                except AttributeError:
                    bb = (tx, ty, tx + len(v_str) * 5, ty + 10)
                draw.rectangle((bb[0] - 1, bb[1], bb[2] + 1, bb[3]),
                               fill=(255, 255, 255, 220))
                draw.text((tx, ty), v_str, fill=color[:3], font=font_small)

    title = (f"cb_true={n_t}  cb_false={n_f}  cb_unmapped={n_m}  "
             f"text={n_text}  |  template={tmpl_file}#{tmpl_page}  "
             f"|  green=cb-true  red=cb-false  blue=text-bbox  "
             f"orange=text-vlm  yellow=raw-X")
    draw.rectangle((0, 0, img.width, 22), fill=(255, 255, 230, 255))
    draw.text((6, 4), title[:160], fill=(0, 0, 0), font=font_small)
    return img


def get_all_template_fields(tmpl_file, tmpl_page):
    """Return list of every AcroForm field on this template page (Btn + Tx)
       with name, type, bbox, tooltip — for the field inspector dropdown."""
    reader = pypdf.PdfReader(str(TEMPLATES_DIR / tmpl_file))
    annots = reader.pages[tmpl_page].get("/Annots", []) or []
    out = []
    for annot in annots:
        obj = annot.get_object()
        rect = obj.get("/Rect", [])
        bbox = [float(r) for r in rect] if rect else None
        name = str(obj.get("/T", ""))
        ft = str(obj.get("/FT", ""))
        if name and bbox and bbox != [0.0, 1.0, 0.0, 1.0]:
            out.append({
                "name": name, "type": ft, "bbox": bbox,
                "tooltip": str(obj.get("/TU", ""))
            })
    return out


def inspector_image(pdf_name, page_num, focus_field_name):
    """Render page with ONE field's bbox highlighted in magenta — the
       'inspector' view for verifying which spot on the form a value
       came from."""
    img = render_pdf_page(pdf_name, page_num).copy()
    if pdf_name not in PAGE_MAPS or page_num not in PAGE_MAPS[pdf_name]:
        return img, None

    tmpl_file, tmpl_page = PAGE_MAPS[pdf_name][page_num]
    dy, _ = compute_dy_for_page(pdf_name, page_num, tmpl_file, tmpl_page)
    all_fields = get_all_template_fields(tmpl_file, tmpl_page)
    field = next((f for f in all_fields if f["name"] == focus_field_name), None)
    if not field:
        return img, None

    draw = ImageDraw.Draw(img, "RGBA")
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
    except Exception:
        font = ImageFont.load_default()

    # Dim the page slightly so the highlight pops
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 50))
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"))
    draw = ImageDraw.Draw(img, "RGBA")

    x0, y0_pdf, x1, y1_pdf = field["bbox"]
    top = PAGE_HEIGHT - y1_pdf + dy
    bot = PAGE_HEIGHT - y0_pdf + dy
    rect = (x0 * SCALE, top * SCALE, x1 * SCALE, bot * SCALE)

    # Bright magenta highlight, thick border
    draw.rectangle(rect, outline=(255, 0, 200, 255), width=4)
    # Cross-hair lines extending out for visibility
    cx = (rect[0] + rect[2]) / 2
    cy = (rect[1] + rect[3]) / 2
    draw.line([(0, cy), (rect[0] - 4, cy)], fill=(255, 0, 200, 80), width=1)
    draw.line([(rect[2] + 4, cy), (img.width, cy)], fill=(255, 0, 200, 80), width=1)
    draw.line([(cx, 0), (cx, rect[1] - 4)], fill=(255, 0, 200, 80), width=1)
    draw.line([(cx, rect[3] + 4), (cx, img.height)], fill=(255, 0, 200, 80), width=1)

    # Label
    label = short_label(field["name"])
    tx = min(rect[2] + 6, img.width - 200)
    ty = max(0, rect[1] - 18)
    try:
        bb = draw.textbbox((tx, ty), label, font=font)
    except AttributeError:
        bb = (tx, ty, tx + len(label) * 7, ty + 14)
    draw.rectangle((bb[0] - 3, bb[1] - 1, bb[2] + 3, bb[3] + 1),
                   fill=(255, 255, 255, 240),
                   outline=(255, 0, 200, 255), width=1)
    draw.text((tx, ty), label, fill=(180, 0, 140), font=font)

    return img, field


def main():
    st.title("Insurance Document Extractor — Visual Verifier")

    # Top-of-page bundle download — per-source-file extractions for all
    # submissions + GT + compare reports.
    bundle_bytes, bundle_summary = _build_submissions_bundle()
    if bundle_bytes:
        c1, c2 = st.columns([3, 1])
        c1.markdown(
            f"**📦 All submissions extraction bundle** "
            f"&nbsp;·&nbsp; {bundle_summary} "
            f"&nbsp;·&nbsp; per-source-file JSONs + mapped + GT + reports"
        )
        c2.download_button(
            "Download zip",
            data=bundle_bytes,
            file_name="all_submissions_extraction.zip",
            mime="application/zip",
            key="dl_submissions_bundle_top",
            type="primary",
            use_container_width=True,
        )
        st.markdown("---")

    pdfs = list_pdfs()
    if not pdfs:
        st.error(f"No PDFs found under {PDF_DIR}. Unzip ALL_Docs.zip first.")
        return

    st.sidebar.header("Document")
    pdf_name = st.sidebar.selectbox("PDF", pdfs)
    n_pages = get_pdf_page_count(pdf_name)
    page_num = st.sidebar.number_input(
        f"Page (1–{n_pages})", 1, n_pages, 1)

    st.sidebar.header("Display")
    show_overlay = st.sidebar.checkbox("Bbox overlay (all extracted fields)", True)
    show_text_fields = st.sidebar.checkbox(
        "Include text-field bboxes (in addition to checkboxes)", True,
        help="Off = only checkboxes. On = also draws each text field with "
             "an extracted value (blue=bbox, orange=VLM).")
    compare_mode = st.sidebar.checkbox("Compare two models", False)
    inspector_mode = st.sidebar.checkbox(
        "🔍 Field Inspector (highlight one field)", False,
        help="Pick a field to see exactly where on the page its value came from.")

    available = [m for m in MODEL_RUNS if (BASE / MODEL_RUNS[m]["dir"]).exists()]
    if not available:
        st.error("No model run dirs found.")
        return

    if compare_mode:
        ca, cb = st.sidebar.columns(2)
        model_a = ca.selectbox("Left model", available, key="left", index=0)
        model_b = cb.selectbox("Right model", available, key="right",
                                index=min(1, len(available) - 1))
    else:
        model_a = st.sidebar.selectbox("Model output", available, index=0)
        model_b = None

    ext_a = load_extraction(pdf_name, model_a)
    page_a = page_data_from_extraction(ext_a, page_num, model_a)

    # Sidebar: downloads
    st.sidebar.header("Downloads")
    safe = safe_name(pdf_name)
    cfg_a = MODEL_RUNS[model_a]
    json_path_a = BASE / cfg_a["dir"] / f"{safe}{cfg_a['suffix']}.json"
    if json_path_a.exists():
        with open(json_path_a) as f:
            content_a = f.read()
        st.sidebar.download_button(
            f"📄 Full JSON ({model_a.split(' ')[0]})",
            data=content_a,
            file_name=json_path_a.name,
            mime="application/json",
            key="dl_full_a",
        )
        if page_a is not None:
            st.sidebar.download_button(
                f"📄 Page {page_num} only",
                data=json.dumps(page_a, indent=2),
                file_name=f"{safe}{cfg_a['suffix']}_page_{page_num}.json",
                mime="application/json",
                key="dl_page_a",
            )

    # Bulk: latest extractions zip for the merged-pipeline output
    merged_zip = BASE / "merged_qwen3vl8b_extractions.zip"
    if merged_zip.exists():
        with open(merged_zip, "rb") as f:
            st.sidebar.download_button(
                "📦 ALL ACORD merged (zip)",
                data=f.read(),
                file_name=merged_zip.name,
                mime="application/zip",
                key="dl_merged_zip",
            )
    lossrun_zip = BASE / "merged_loss_runs_extractions.zip"
    if lossrun_zip.exists():
        with open(lossrun_zip, "rb") as f:
            st.sidebar.download_button(
                "📦 ALL loss runs merged (zip)",
                data=f.read(),
                file_name=lossrun_zip.name,
                mime="application/zip",
                key="dl_lossrun_zip",
            )
    all_zip = BASE / "ALL_MODEL_RESULTS.zip"
    if all_zip.exists():
        with open(all_zip, "rb") as f:
            st.sidebar.download_button(
                "📦 ALL_MODEL_RESULTS.zip",
                data=f.read(),
                file_name=all_zip.name,
                mime="application/zip",
                key="dl_all_zip",
            )

    # ── All-submissions extraction bundle (mapped + GT + reports) ──
    bundle_bytes, bundle_summary = _build_submissions_bundle()
    if bundle_bytes:
        st.sidebar.markdown("---")
        st.sidebar.markdown("**All submissions (mapped + GT + reports)**")
        if bundle_summary:
            st.sidebar.caption(bundle_summary)
        st.sidebar.download_button(
            "📦 all_submissions_extraction.zip",
            data=bundle_bytes,
            file_name="all_submissions_extraction.zip",
            mime="application/zip",
            key="dl_submissions_bundle",
        )

    # ── FIELD INSPECTOR MODE ──
    # Pick a field, see its bbox highlighted on the page + its extracted value.
    if inspector_mode:
        if pdf_name not in PAGE_MAPS or page_num not in PAGE_MAPS[pdf_name]:
            st.warning("Field Inspector requires a page with an AcroForm "
                       "template. This page has none.")
            return

        tmpl_file, tmpl_page = PAGE_MAPS[pdf_name][page_num]
        all_fields = get_all_template_fields(tmpl_file, tmpl_page)

        # Pull merged extraction so we can show the extracted value
        merged_label = "merged_qwen3vl8b (bbox+VLM)"
        merged_ext = load_extraction(pdf_name, merged_label)
        merged_page = page_data_from_extraction(merged_ext, page_num, merged_label)
        merged_fields = (merged_page or {}).get("fields") if merged_page else {}

        # Build human-readable options: "Btn ✓ NamedInsured_LegalEntity_LLC..."
        def _opt(f):
            ext = merged_fields.get(f["name"])
            if ext is None:
                marker = "—"; val_preview = "(no extracted value)"
            else:
                v = ext.get("value")
                if v is True:
                    marker = "✓"
                elif v is False:
                    marker = "·"
                else:
                    marker = "📝"
                val_preview = "✓ true" if v is True else "✗ false" if v is False \
                    else (str(v)[:50] + "…" if len(str(v)) > 50 else str(v))
            kind = "Btn" if f["type"] == "/Btn" else "Tx "
            return f"[{kind}] {marker} {f['name']}  →  {val_preview}"

        sorted_fields = sorted(all_fields, key=lambda f: (
            0 if merged_fields.get(f["name"]) and
                 merged_fields[f["name"]].get("value") not in (False, None) else 1,
            f["name"]))
        labels = [_opt(f) for f in sorted_fields]
        idx = st.sidebar.selectbox(
            f"Field on page {page_num} ({len(sorted_fields)} total)",
            range(len(labels)),
            format_func=lambda i: labels[i],
        )
        focus_field = sorted_fields[idx]
        img, _ = inspector_image(pdf_name, page_num, focus_field["name"])

        ext = merged_fields.get(focus_field["name"])
        c1, c2 = st.columns([3, 2])
        c1.image(img, caption=f"{pdf_name} — page {page_num} · "
                              f"highlight: {focus_field['name']}",
                 use_container_width=True)
        with c2:
            st.subheader("Field details")
            st.markdown(f"**Field name:** `{focus_field['name']}`")
            st.markdown(f"**Type:** `{focus_field['type']}` "
                        f"({'checkbox' if focus_field['type']=='/Btn' else 'text'})")
            st.markdown(f"**Tooltip:** {focus_field.get('tooltip','(none)')[:200]}")
            st.markdown(f"**Template bbox (PDF coords):** `{focus_field['bbox']}`")
            st.markdown("---")
            if ext is None:
                st.info("This field is in the template but not in the merged "
                        "JSON. For a /Btn this means it's the unchecked default "
                        "(was filtered out before the explicit-false fix). "
                        "For a /Tx this means pdfplumber found no text inside "
                        "the bbox AND VLM didn't gap-fill it.")
            else:
                v = ext.get("value")
                src = ext.get("source", "?")
                st.markdown(f"**Extracted value:** `{v!r}`")
                st.markdown(f"**Source:** `{src}`")
                if focus_field["type"] == "/Btn":
                    st.caption("Source 'bbox' = X-glyph or pixel-density at the "
                               "bbox center. 'bbox:pixel:0.42' = pixel-density "
                               "fallback (no X-glyph but >18% dark pixels).")
                else:
                    st.caption("Source 'bbox' = pdfplumber word-extraction inside "
                               "the bbox. 'vlm' = VLM gap-fill (no spatial provenance).")
        return  # skip the normal flow

    overlay_supported = (show_overlay and pdf_name in PAGE_MAPS
                         and page_num in PAGE_MAPS[pdf_name])
    if overlay_supported:
        merged_label = "merged_qwen3vl8b (bbox+VLM)"
        merged_ext = load_extraction(pdf_name, merged_label)
        merged_page = page_data_from_extraction(merged_ext, page_num, merged_label)
        merged_fields = (merged_page or {}).get("fields") if merged_page else None
        img = overlay_image(pdf_name, page_num, merged_fields,
                            show_text_fields=show_text_fields)
    else:
        img = render_pdf_page(pdf_name, page_num)
        if show_overlay:
            st.info(f"No bbox template for {pdf_name} page {page_num} "
                    f"(loss runs / supplementals are pure-VLM only).")

    if compare_mode:
        ext_b = load_extraction(pdf_name, model_b)
        page_b = page_data_from_extraction(ext_b, page_num, model_b)
        c1, c2, c3 = st.columns([3, 2, 2])
        c1.image(img, caption=f"{pdf_name} — page {page_num}",
                 use_container_width=True)
        c2.subheader(model_a)
        c2.json(page_a or {"_": "no data"}, expanded=False)
        c3.subheader(model_b)
        c3.json(page_b or {"_": "no data"}, expanded=False)
    else:
        c1, c2 = st.columns([3, 2])
        c1.image(img, caption=f"{pdf_name} — page {page_num}",
                 use_container_width=True)
        c2.subheader(model_a)
        if page_a is None:
            c2.warning("No extraction for this page.")
        else:
            shape = MODEL_RUNS[model_a].get("shape", "vlm")
            if shape == "merged":
                fields = page_a.get("fields", {})
                t1, t2, t3 = c2.tabs(["Checkboxes", "Text fields", "All JSON"])
                with t1:
                    cbs = {n: f for n, f in fields.items()
                           if f.get("type") == "checkbox"}
                    true_cbs = {n: f for n, f in cbs.items() if f["value"]}
                    st.write(f"**True**: {len(true_cbs)} / {len(cbs)} checkboxes")
                    for n, f in sorted(true_cbs.items()):
                        st.markdown(f"- `{short_label(n)}` "
                                    f"<sub>{f.get('tooltip','')[:80]}</sub>",
                                    unsafe_allow_html=True)
                with t2:
                    txts = {n: f for n, f in fields.items()
                            if f.get("type") == "text"}
                    for n, f in sorted(txts.items())[:80]:
                        v = str(f["value"])[:120]
                        st.markdown(
                            f"- **{short_label(n)}** = `{v}`  "
                            f"<sub>[{f['source']}] {f.get('tooltip','')[:60]}</sub>",
                            unsafe_allow_html=True)
                    if len(txts) > 80:
                        st.caption(f"… {len(txts) - 80} more")
                with t3:
                    st.json(page_a, expanded=False)
                discrep = page_a.get("discrepancies", [])
                if discrep:
                    with c2.expander(f"⚠ {len(discrep)} discrepancies"):
                        st.json(discrep)
            elif shape == "lossrun":
                pdfp = page_a.get("pdfplumber_page") or {}
                parsed = page_a.get("parsed_claims") or []
                discs = page_a.get("discrepancies") or []
                vlm = page_a.get("vlm") or {}

                # Header chip line
                garbled = pdfp.get("garbled_font", False)
                n_tables = len(pdfp.get("tables") or [])
                c2.caption(
                    f"garbled_font: **{garbled}** &nbsp;|&nbsp; "
                    f"raw_text_chars: **{pdfp.get('raw_text_chars', 0)}** &nbsp;|&nbsp; "
                    f"tables: **{n_tables}** &nbsp;|&nbsp; "
                    f"parsed_claims: **{len(parsed)}** &nbsp;|&nbsp; "
                    f"discrepancies: **{len(discs)}**",
                    unsafe_allow_html=True)

                t1, t2, t3, t4, t5 = c2.tabs([
                    "VLM JSON",
                    f"Parsed claims ({len(parsed)})",
                    f"pdfplumber tables ({n_tables})",
                    f"Discrepancies ({len(discs)})",
                    "Raw text",
                ])
                with t1:
                    st.json(vlm or {"_": "no VLM data"}, expanded=False)
                with t2:
                    if not parsed:
                        st.caption("No structured claim rows parsed for this page.")
                    for i, c in enumerate(parsed):
                        st.markdown(f"**claim {i+1}** — page {c.get('_page')}")
                        st.json({k: v for k, v in c.items() if k != "_page"},
                                expanded=False)
                with t3:
                    tables = pdfp.get("tables") or []
                    if not tables:
                        st.caption("pdfplumber found no tables on this page.")
                    for ti, t in enumerate(tables):
                        st.write(f"**table {ti}** — {len(t)} rows × {len(t[0]) if t else 0} cols")
                        st.dataframe(t, use_container_width=True)
                with t4:
                    if not discs:
                        st.caption("✅ No VLM values flagged as missing from raw text.")
                    for d in discs:
                        st.markdown(
                            f"- VLM emitted `{d['vlm_value']}` "
                            f"<sub>not found in raw page text "
                            f"({d.get('issue','')})</sub>",
                            unsafe_allow_html=True)
                with t5:
                    raw = pdfp.get("raw_text") or ""
                    if garbled:
                        st.warning("Garbled font — raw text not extractable.")
                    elif not raw:
                        st.caption("(empty)")
                    else:
                        st.code(raw[:6000], language=None)
            else:
                c2.json(page_a, expanded=False)


if __name__ == "__main__":
    main()
