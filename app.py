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
import json
import os
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


def overlay_image(pdf_name, page_num, merged_fields):
    img = render_pdf_page(pdf_name, page_num).copy()
    if pdf_name not in PAGE_MAPS or page_num not in PAGE_MAPS[pdf_name]:
        return img

    tmpl_file, tmpl_page = PAGE_MAPS[pdf_name][page_num]
    dy, fwords = compute_dy_for_page(pdf_name, page_num, tmpl_file, tmpl_page)
    btn_fields = load_template_btn_fields(tmpl_file, tmpl_page)

    draw = ImageDraw.Draw(img, "RGBA")
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
    except Exception:
        font = ImageFont.load_default()

    for w in fwords:
        if w["text"].strip() == "X":
            cx = (w["x0"] + w["x1"]) / 2 * SCALE
            cy = (w["top"] + w["bottom"]) / 2 * SCALE
            draw.ellipse((cx - 8, cy - 8, cx + 8, cy + 8),
                         outline=(255, 200, 0, 255), width=2)

    n_t = n_f = n_m = 0
    for f in btn_fields:
        x0, y0_pdf, x1, y1_pdf = f["bbox"]
        top = PAGE_HEIGHT - y1_pdf + dy
        bot = PAGE_HEIGHT - y0_pdf + dy
        rect = (x0 * SCALE, top * SCALE, x1 * SCALE, bot * SCALE)

        fld = merged_fields.get(f["name"]) if merged_fields else None
        if fld is None:
            color = (140, 140, 140, 255); n_m += 1
        else:
            color = ((0, 200, 0, 255) if fld.get("value") is True
                     else (220, 60, 60, 255))
            if fld.get("value") is True:
                n_t += 1
            else:
                n_f += 1
        draw.rectangle(rect, outline=color, width=2)

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

    title = (f"true={n_t}  false={n_f}  unmapped={n_m}  |  "
             f"template={tmpl_file}#{tmpl_page}")
    draw.rectangle((0, 0, img.width, 22), fill=(255, 255, 230, 255))
    draw.text((6, 4), title, fill=(0, 0, 0), font=font)
    return img


def main():
    st.title("Insurance Document Extractor — Visual Verifier")

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
    show_overlay = st.sidebar.checkbox("Bbox checkbox overlay", True)
    compare_mode = st.sidebar.checkbox("Compare two models", False)

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

    overlay_supported = (show_overlay and pdf_name in PAGE_MAPS
                         and page_num in PAGE_MAPS[pdf_name])
    if overlay_supported:
        merged_label = "merged_qwen3vl8b (bbox+VLM)"
        merged_ext = load_extraction(pdf_name, merged_label)
        merged_page = page_data_from_extraction(merged_ext, page_num, merged_label)
        merged_fields = (merged_page or {}).get("fields") if merged_page else None
        img = overlay_image(pdf_name, page_num, merged_fields)
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
