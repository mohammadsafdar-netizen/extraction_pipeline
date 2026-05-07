import streamlit as st
import pdfplumber
import json
import fitz
import io
import os
from PIL import Image, ImageDraw
from pathlib import Path

st.set_page_config(page_title="ACORD PDF Extractor — Visual Verifier", layout="wide")

BASE = Path(__file__).parent
TARGETED_DIR = BASE / "targeted_extractions"
VLM_DIR = BASE / "vlm_extractions"

# All PDFs
PDFS = sorted([
    f for f in os.listdir(BASE)
    if f.lower().endswith(".pdf") and "template" not in f.lower()
])


@st.cache_data
def get_pdf_pages(pdf_name):
    doc = fitz.open(str(BASE / pdf_name))
    count = len(doc)
    doc.close()
    return count


@st.cache_data
def render_page(pdf_name, page_num, dpi=150):
    doc = fitz.open(str(BASE / pdf_name))
    page = doc[page_num - 1]
    pix = page.get_pixmap(dpi=dpi)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    doc.close()
    return img


@st.cache_data
def load_vlm_data(pdf_name):
    safe = pdf_name.replace(" ", "_").replace("(", "").replace(")", "").replace(".pdf", "").replace(".PDF", "")
    # Try targeted first
    tp = TARGETED_DIR / (safe + "_targeted.json")
    if tp.exists():
        with open(tp) as f:
            return json.load(f), "targeted"
    # Try vlm_extractions
    vp = VLM_DIR / (safe + ".json")
    if vp.exists():
        with open(vp) as f:
            return json.load(f), "vlm"
    return None, None


@st.cache_data
def get_raw_text(pdf_name, page_num):
    try:
        pdf = pdfplumber.open(str(BASE / pdf_name))
        page = pdf.pages[page_num - 1]
        words = page.extract_words(keep_blank_chars=True, x_tolerance=2, y_tolerance=2)
        words.sort(key=lambda w: (round(w["top"], 0), w["x0"]))
        text = page.extract_text() or ""
        pdf.close()
        if "(cid:" in text:
            return [], "(garbled font — use OCR)"
        return words, text
    except:
        return [], ""


def draw_word_boxes(img, words, scale=150 / 72):
    """Draw bounding boxes around each word on the page image."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for w in words:
        x0 = w["x0"] * scale
        top = w["top"] * scale
        x1 = w["x1"] * scale
        bottom = w["bottom"] * scale
        draw.rectangle([x0, top, x1, bottom], outline=(0, 150, 255, 180), width=1)
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def flatten_json(obj, prefix=""):
    items = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.startswith("_"):
                continue
            new_key = f"{prefix}.{k}" if prefix else k
            items.extend(flatten_json(v, new_key))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            items.extend(flatten_json(v, f"{prefix}[{i}]"))
    else:
        if obj is not None and str(obj).strip():
            items.append((prefix, obj))
    return items


def main():
    st.title("Insurance Document Extractor — Visual Verifier")

    # Sidebar — zip download at top
    zip_path = BASE / "all_extractions.zip"
    if zip_path.exists():
        with open(zip_path, "rb") as zf:
            st.sidebar.download_button(
                "Download ALL Extractions (ZIP)",
                data=zf.read(),
                file_name="all_extractions.zip",
                mime="application/zip",
                use_container_width=True,
            )

    st.sidebar.markdown("---")
    st.sidebar.header("Select Document")
    selected_pdf = st.sidebar.selectbox("PDF File", PDFS)
    total_pages = get_pdf_pages(selected_pdf)

    page_num = st.sidebar.number_input("Page", min_value=1, max_value=total_pages, value=1)

    st.sidebar.markdown("---")
    show_word_boxes = st.sidebar.checkbox("Show word bounding boxes", value=False)
    dpi = st.sidebar.selectbox("Render DPI", [100, 150, 200], index=1)

    # Load VLM data
    vlm_data, vlm_source = load_vlm_data(selected_pdf)
    vlm_page = None
    if vlm_data:
        for p in vlm_data.get("pages", []):
            if p["page"] == page_num:
                vlm_page = p.get("data", {})
                break

    st.sidebar.markdown("---")
    if vlm_source:
        st.sidebar.success(f"VLM: {vlm_source}")
    else:
        st.sidebar.warning("No VLM extraction")

    # Stats
    if vlm_page and "_error" not in vlm_page and "_raw" not in vlm_page:
        fields = flatten_json(vlm_page)
        st.sidebar.metric("Fields on this page", len(fields))
    else:
        fields = []

    # Full JSON download
    if vlm_data:
        st.sidebar.download_button(
            "Download Full JSON",
            data=json.dumps(vlm_data, indent=2),
            file_name=f"{selected_pdf}_extraction.json",
            mime="application/json",
        )

    # Main content
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader(f"PDF — Page {page_num}/{total_pages}")
        img = render_page(selected_pdf, page_num, dpi)

        if show_word_boxes:
            words, _ = get_raw_text(selected_pdf, page_num)
            if words:
                scale = dpi / 72
                img = draw_word_boxes(img, words, scale)

        st.image(img, use_container_width=True)

    with col2:
        st.subheader("Extracted Fields")

        if vlm_page and "_error" not in vlm_page and "_raw" not in vlm_page:
            # Get raw text for cross-validation
            _, raw_text = get_raw_text(selected_pdf, page_num)
            raw_lower = raw_text.lower().replace(" ", "").replace(",", "")

            tab1, tab2, tab3 = st.tabs(["Fields", "Verification", "Raw JSON"])

            with tab1:
                for key, value in fields:
                    val_str = str(value)
                    if isinstance(value, bool):
                        st.markdown(f"**{key}:** {'[X]' if value else '[ ]'}")
                    elif val_str in ("", "0", "0.0", "None"):
                        continue
                    else:
                        st.markdown(f"**{key}:** `{val_str}`")

            with tab2:
                st.markdown("**Cross-validation: VLM value vs raw text**")
                ok_count = 0
                fail_count = 0
                skip_count = 0

                for key, value in fields:
                    val_str = str(value)
                    val_clean = val_str.lower().replace(" ", "").replace(",", "").replace("$", "")

                    if len(val_clean) < 2 or val_str in ("0", "0.0", "None", ""):
                        skip_count += 1
                        continue

                    if isinstance(value, bool):
                        # Can't verify checkboxes in raw text
                        st.markdown(f"- :blue[[CHECKBOX]] **{key}** = {value}")
                        skip_count += 1
                        continue

                    if val_clean in raw_lower.replace("$", ""):
                        st.markdown(f"- :green[[OK]] **{key}** = `{val_str}`")
                        ok_count += 1
                    else:
                        # Partial match
                        words_in_val = val_str.split()
                        if len(words_in_val) > 2:
                            matches = sum(1 for w in words_in_val
                                         if w.lower().replace(",", "") in raw_lower)
                            if matches >= len(words_in_val) * 0.6:
                                st.markdown(f"- :orange[[PARTIAL]] **{key}** = `{val_str}`")
                                ok_count += 1
                                continue

                        st.markdown(f"- :red[[UNCONFIRMED]] **{key}** = `{val_str}`")
                        fail_count += 1

                st.markdown("---")
                total = ok_count + fail_count + skip_count
                st.markdown(f"**Confirmed:** {ok_count} | **Unconfirmed:** {fail_count} | **Skipped:** {skip_count} | **Total:** {total}")

            with tab3:
                st.json(vlm_page)

        elif vlm_page and "_error" in vlm_page:
            st.error(f"VLM error: {vlm_page['_error']}")
        elif vlm_page and "_raw" in vlm_page:
            st.warning("VLM returned raw text (no JSON)")
            st.text(vlm_page["_raw"][:1000])
        else:
            st.info("No VLM extraction for this page")

    # Bottom: All documents download section
    st.markdown("---")
    st.subheader("Download Extractions — All Documents")

    # Build download buttons for every PDF
    dl_cols = st.columns(3)
    col_idx = 0
    for pdf_name in PDFS:
        vdata, vsrc = load_vlm_data(pdf_name)
        if not vdata:
            continue

        total_f = 0
        for p in vdata.get("pages", []):
            pg_data = p.get("data", {})
            if "_error" not in pg_data and "_raw" not in pg_data:
                total_f += len(flatten_json(pg_data))

        label = f"{pdf_name[:45]}... ({vdata.get('total_pages', '?')}pg, {total_f} fields)"
        safe = pdf_name.replace(" ", "_").replace("(", "").replace(")", "")

        with dl_cols[col_idx % 3]:
            st.download_button(
                label=label,
                data=json.dumps(vdata, indent=2),
                file_name=f"{safe}_extraction.json",
                mime="application/json",
                key=f"dl_{safe}",
                use_container_width=True,
            )
        col_idx += 1


if __name__ == "__main__":
    main()
