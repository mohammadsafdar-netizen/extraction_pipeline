"""
Visual verifier for the bbox-merge pipeline.

For each ACORD application page that has an AcroForm template mapping,
renders the page as a PNG and overlays:
  - Every /Btn (checkbox) bbox, color-coded by detected state:
      green = true (X detected)
      red   = false (no X detected)
  - The field name labeled next to TRUE checkboxes.
  - Yellow circles around every detected "X" glyph (raw bbox sensor).

Used to spot-check whether bbox detection matches the visual form.

Usage:
  python verify_visual.py                          # all 5 ACORD apps
  python verify_visual.py "Acord App (1800 North Stone LLC) 2026.pdf"
  python verify_visual.py --merged-dir merged_qwen3vl8b --out verification/
"""
import argparse
import json
import sys
from pathlib import Path

import fitz
import pdfplumber
import pypdf
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent
PDF_DIR = REPO / "pdfs"
TEMPLATES_DIR = REPO / "templates"
DEFAULT_MERGED = REPO / "merged_qwen3vl8b"
DEFAULT_OUT = REPO / "verification"

PAGE_HEIGHT = 792.0
DPI = 150
SCALE = DPI / 72.0  # PDF point -> image pixel

PDFS = {
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


def pdf_to_image_rect(bbox_pdf, dy):
    """Convert template /Rect (PDF coords, origin bottom-left) + dy
       to image-pixel rect at DPI=150 in the filled PDF."""
    x0, y0_pdf, x1, y1_pdf = bbox_pdf
    top_pt = PAGE_HEIGHT - y1_pdf + dy
    bot_pt = PAGE_HEIGHT - y0_pdf + dy
    return (x0 * SCALE, top_pt * SCALE,
            x1 * SCALE, bot_pt * SCALE)


def compute_dy(twords, fwords):
    ANCHOR_LABELS = ["CARRIER", "NAIC CODE", "POLICY NUMBER", "EFFECTIVE DATE",
                     "NAMED INSURED(S)", "CONSTRUCTION TYPE", "PRIMARY HEAT",
                     "SECONDARY HEAT", "COVERAGES", "LIMITS", "SIGNATURE",
                     "GENERAL INFORMATION", "CONTACT INFORMATION",
                     "ADDITIONAL INTEREST", "UNDERLYING INSURANCE",
                     "BLANKET SUMMARY", "TOTAL AREA", "YR BUILT"]
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
    return sum(dys) / len(dys) if dys else 8.0


def load_template_btn_fields(tmpl_path: Path, page_idx: int):
    reader = pypdf.PdfReader(str(tmpl_path))
    annots = reader.pages[page_idx].get("/Annots", [])
    fields = []
    for annot in annots:
        obj = annot.get_object()
        ft = str(obj.get("/FT", ""))
        if ft != "/Btn":
            continue
        name = str(obj.get("/T", ""))
        rect = obj.get("/Rect", [])
        bbox = [float(r) for r in rect] if rect else None
        if name and bbox and bbox != [0.0, 1.0, 0.0, 1.0]:
            fields.append({"name": name, "bbox": bbox,
                           "tooltip": str(obj.get("/TU", ""))})
    return fields


def short_label(field_name: str, max_len: int = 40) -> str:
    """Trim AcroForm field name to a readable label."""
    s = field_name.replace("[0]", "")
    parts = s.split("_")
    # Strip the suffix like _A, _B, _C
    if parts and len(parts[-1]) <= 2:
        parts = parts[:-1]
    s = "_".join(parts)
    if len(s) > max_len:
        s = "…" + s[-(max_len - 1):]
    return s


def render_page(pdf_path: Path, page_idx: int) -> Image.Image:
    doc = fitz.open(str(pdf_path))
    pix = doc[page_idx].get_pixmap(dpi=DPI)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    doc.close()
    return img


def overlay_one_page(pdf_path: Path, pg_num: int,
                     tmpl_file: str, tmpl_page: int,
                     merged_fields: dict, templates_dir: Path) -> Image.Image:
    img = render_page(pdf_path, pg_num - 1)
    draw = ImageDraw.Draw(img, "RGBA")

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
    except Exception:
        font = ImageFont.load_default()

    # Compute dy by re-anchoring (must match runner)
    fpdf = pdfplumber.open(str(pdf_path))
    fwords = fpdf.pages[pg_num - 1].extract_words(
        keep_blank_chars=True, x_tolerance=2, y_tolerance=2)
    fpdf.close()
    tpdf = pdfplumber.open(str(templates_dir / tmpl_file))
    twords = tpdf.pages[tmpl_page].extract_words(
        keep_blank_chars=True, x_tolerance=2, y_tolerance=2)
    tpdf.close()
    dy = compute_dy(twords, fwords)

    # Yellow circles around all detected X glyphs
    for w in fwords:
        if w["text"].strip() == "X":
            cx = (w["x0"] + w["x1"]) / 2 * SCALE
            cy = (w["top"] + w["bottom"]) / 2 * SCALE
            r = 8
            draw.ellipse((cx - r, cy - r, cx + r, cy + r),
                         outline=(255, 200, 0, 255), width=2)

    # Per-field bbox overlay
    btn_fields = load_template_btn_fields(templates_dir / tmpl_file, tmpl_page)
    n_true = n_false = n_missing = 0
    for f in btn_fields:
        rect = pdf_to_image_rect(f["bbox"], dy)
        # Field state from merged JSON
        fld = merged_fields.get(f["name"])
        if fld is None:
            color = (128, 128, 128, 255)  # gray
            n_missing += 1
        else:
            v = fld.get("value")
            if v is True:
                color = (0, 200, 0, 255)  # green
                n_true += 1
            else:
                color = (220, 60, 60, 255)  # red
                n_false += 1

        draw.rectangle(rect, outline=color, width=2)

        # Label only TRUE checkboxes (avoid clutter)
        if fld and fld.get("value") is True:
            label = short_label(f["name"])
            tx = rect[2] + 4
            ty = rect[1] - 2
            # Background fill behind text for legibility
            try:
                bbox_label = draw.textbbox((tx, ty), label, font=font)
            except AttributeError:
                bbox_label = (tx, ty, tx + len(label) * 6, ty + 12)
            draw.rectangle((bbox_label[0] - 2, bbox_label[1],
                            bbox_label[2] + 2, bbox_label[3]),
                           fill=(255, 255, 255, 230))
            draw.text((tx, ty), label, fill=color[:3], font=font)

    # Title strip at top
    title = (f"{pdf_path.name}  |  page {pg_num}  |  template={tmpl_file}#{tmpl_page}  |  "
             f"true={n_true}  false={n_false}  unmapped={n_missing}")
    draw.rectangle((0, 0, img.width, 22), fill=(255, 255, 230, 255))
    draw.text((6, 4), title, fill=(0, 0, 0), font=font)
    return img


def process_pdf(pdf_path: Path, page_map: dict, merged_path: Path,
                templates_dir: Path, out_dir: Path) -> int:
    if not merged_path.exists():
        print(f"  SKIP: merged JSON not found ({merged_path.name})")
        return 0
    merged = json.load(open(merged_path))
    pages = merged.get("pages", {})

    safe_name = (pdf_path.stem.replace(" ", "_").replace("(", "").replace(")", ""))
    pdf_out_dir = out_dir / safe_name
    pdf_out_dir.mkdir(parents=True, exist_ok=True)

    n_done = 0
    for pg_num, (tmpl_file, tmpl_page) in page_map.items():
        page_obj = pages.get(f"page_{pg_num}", {})
        merged_fields = page_obj.get("fields", {})

        try:
            img = overlay_one_page(pdf_path, pg_num, tmpl_file, tmpl_page,
                                   merged_fields, templates_dir)
        except Exception as e:
            print(f"  p{pg_num} ERROR: {e}")
            continue

        out_path = pdf_out_dir / f"p{pg_num:02d}_{tmpl_file.replace('.pdf','')}.png"
        img.save(out_path, optimize=True)
        n_done += 1
        print(f"  p{pg_num} -> {out_path.relative_to(REPO)}")
    return n_done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", help="Specific PDF (default: all 5)")
    ap.add_argument("--merged-dir", default=str(DEFAULT_MERGED))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--pdf-dir", default=str(PDF_DIR))
    ap.add_argument("--templates-dir", default=str(TEMPLATES_DIR))
    args = ap.parse_args()

    merged_dir = Path(args.merged_dir)
    out_dir = Path(args.out)
    pdf_dir = Path(args.pdf_dir)
    templates_dir = Path(args.templates_dir)

    pdfs = ({args.target: PDFS[args.target]}
            if args.target and args.target in PDFS else PDFS)

    total = 0
    for fname, page_map in pdfs.items():
        pdf_path = pdf_dir / fname
        if not pdf_path.exists():
            print(f"SKIP {fname}: PDF not found")
            continue
        safe = (pdf_path.stem.replace(" ", "_").replace("(", "").replace(")", ""))
        merged_path = merged_dir / f"{safe}_merged.json"
        print(f"\n{'='*70}\n{fname}")
        n = process_pdf(pdf_path, page_map, merged_path,
                        templates_dir, out_dir)
        total += n
    print(f"\n{'='*70}\nWrote {total} verification images to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
