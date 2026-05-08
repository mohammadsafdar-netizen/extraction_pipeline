"""
Unified extraction runner for the Input/ folder.

Handles the four document classes you typically get with an insurance
submission package:

  - .pdf  ACORD application, supplemental, loss run, community map →
          existing merged or loss-run pipeline (or pure-VLM for unknowns)
  - .docx narrative attachments / emails / underwriter notes →
          python-docx structured text extraction
  - .xls  / .xlsx Statement of Values, exposure schedules →
          pandas-based per-sheet/row extraction

Output: one JSON file per input doc in input_extracted/, plus a master
input_extracted/ALL.json with everything in a single file.
"""
import argparse
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import fitz  # for PDF page count + classification
import pandas as pd

# Lazy-import the heavy pipelines only when needed
REPO = Path(__file__).resolve().parent
INPUT_DIR_DEFAULT = REPO / "input_docs" / "Input"
OUT_DIR_DEFAULT = REPO / "input_extracted"
PDF_DIR = REPO / "pdfs"


# ── docx ──

def extract_docx(path: Path) -> dict:
    """Extract structured content from a .docx file:
       - paragraphs (with style)
       - tables (rows of cells)
       - section count
       - inline images (count only)"""
    from docx import Document

    doc = Document(str(path))
    paragraphs = []
    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        paragraphs.append({
            "style": p.style.name if p.style else "Normal",
            "text": text,
        })

    tables = []
    for ti, t in enumerate(doc.tables):
        rows = []
        for row in t.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                rows.append(cells)
        if rows:
            tables.append({"index": ti, "rows": rows})

    n_images = sum(1 for s in doc.inline_shapes)

    return {
        "source_file": path.name,
        "type": "docx",
        "n_paragraphs": len(paragraphs),
        "n_tables": len(tables),
        "n_inline_images": n_images,
        "paragraphs": paragraphs,
        "tables": tables,
    }


# ── xls / xlsx ──

def extract_excel(path: Path) -> dict:
    """Extract every sheet of an Excel file as a list of row records.
       Uses pandas with openpyxl (xlsx) or xlrd (xls)."""
    suffix = path.suffix.lower()
    engine = "openpyxl" if suffix == ".xlsx" else "xlrd"

    out_sheets = []
    try:
        xls = pd.ExcelFile(str(path), engine=engine)
        for sheet_name in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet_name, header=None,
                                dtype=object)
            # Drop fully-empty rows + columns
            df = df.dropna(how="all", axis=0).dropna(how="all", axis=1)
            df = df.fillna("")

            # Find first non-empty row to use as header
            rows = df.values.tolist()
            header = None
            data_rows = []
            for r in rows:
                if header is None and any(str(c).strip() for c in r):
                    header = [str(c).strip() for c in r]
                    continue
                if header:
                    record = {}
                    for k, v in zip(header, r):
                        if k:
                            record[k] = ("" if v == "" else
                                         (v.isoformat() if hasattr(v, "isoformat")
                                          else str(v).strip()))
                    data_rows.append(record)

            out_sheets.append({
                "sheet_name": sheet_name,
                "n_rows": len(rows),
                "header": header or [],
                "records": data_rows,
                "raw_grid": rows,  # full grid (untruncated)
            })
    except Exception as e:
        return {
            "source_file": path.name,
            "type": "excel",
            "_error": f"{type(e).__name__}: {e}",
        }

    return {
        "source_file": path.name,
        "type": "excel",
        "n_sheets": len(out_sheets),
        "sheets": out_sheets,
    }


# ── pdf classification + dispatch ──

LOSS_RUN_PATTERNS = re.compile(r"\b(loss[\s_-]?run|LR[_\s-]|claims?[\s_-]history)",
                                re.IGNORECASE)


def classify_pdf(path: Path) -> str:
    """Return one of {acord_application, loss_run, supplemental, other}."""
    name = path.name.lower()
    if LOSS_RUN_PATTERNS.search(name) or name.startswith("lr_"):
        return "loss_run"
    if "acord" in name and "app" in name:
        return "acord_application"
    if "supp" in name or "supplemental" in name:
        return "supplemental"
    if "questionnaire" in name:
        return "questionnaire"
    return "other"


def extract_pdf(path: Path, out_dir: Path) -> dict:
    """Route PDF to appropriate pipeline:
       - acord_application → merged bbox+VLM (run_vllm_merged.process_pdf)
       - loss_run → pdfplumber+VLM cross-check (run_vllm_loss_runs.process_pdf)
       - other → pure-VLM extraction"""
    doc_type = classify_pdf(path)
    print(f"  type: {doc_type}")

    # Ensure the PDF is in pdfs/ since the pipeline runners read from there
    pdf_target = PDF_DIR / path.name
    if not pdf_target.exists():
        PDF_DIR.mkdir(exist_ok=True)
        shutil.copy(str(path), str(pdf_target))

    if doc_type == "acord_application":
        # Use a default 4-page acord_125 mapping for unknown ACORD apps
        # (matches PDFS dict in run_vllm_merged for these named files).
        from run_vllm_merged import (PDFS as MERGED_PDFS, process_pdf as merged_process,
                                       PAGE_MAP_125_ONLY)
        mapping = MERGED_PDFS.get(path.name)
        if mapping:
            doc_type, page_map = mapping
        else:
            page_map = PAGE_MAP_125_ONLY
        return merged_process(
            path.name, "acord_application", page_map,
            PDF_DIR, REPO / "templates", dpi=150,
        )

    if doc_type == "loss_run":
        from run_vllm_loss_runs import process_pdf as loss_process
        return loss_process(path.name, PDF_DIR, dpi=150)

    # Other: render each page, send to VLM with GENERALIZED prompt
    print(f"  using pure-VLM extraction for unknown PDF type")
    from run_vllm_merged import run_vlm_extraction
    vlm_result, total_pages = run_vlm_extraction(
        path, doc_type or "other", dpi=150,
        page_map=None, templates_dir=REPO / "templates",
    )
    return {
        "source_file": path.name,
        "type": "pdf",
        "document_type": doc_type,
        "total_pages": total_pages,
        "model": "qwen3-vl-8b",
        "pages": [
            {"page": pg, "data": vlm_result.get(pg)}
            for pg in sorted(vlm_result)
        ],
    }


# ── main ──

def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", default=str(INPUT_DIR_DEFAULT))
    ap.add_argument("--out", default=str(OUT_DIR_DEFAULT))
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    input_dir = Path(args.input_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted([f for f in input_dir.rglob("*") if f.is_file()])
    if not files:
        print(f"No files in {input_dir}")
        return 1

    all_extractions = []
    for path in files:
        suffix = path.suffix.lower()
        out_path = out_dir / f"{safe_name(path.stem)}.json"

        print(f"\n{'='*70}\n{path.name}  ({suffix})")
        if out_path.exists() and not args.overwrite:
            print(f"  SKIP: {out_path.name} already exists")
            with open(out_path) as f:
                all_extractions.append(json.load(f))
            continue

        try:
            if suffix == ".pdf":
                result = extract_pdf(path, out_dir)
            elif suffix == ".docx":
                result = extract_docx(path)
            elif suffix in (".xls", ".xlsx"):
                result = extract_excel(path)
            else:
                result = {"source_file": path.name, "type": suffix.lstrip("."),
                           "_error": "unsupported file type"}
        except Exception as e:
            import traceback
            traceback.print_exc()
            result = {"source_file": path.name, "type": suffix.lstrip("."),
                       "_error": f"{type(e).__name__}: {e}"}

        with open(out_path, "w") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"  -> {out_path.name}")
        all_extractions.append(result)

    master = {
        "input_dir": str(input_dir),
        "n_files": len(all_extractions),
        "by_type": {},
        "files": all_extractions,
    }
    for r in all_extractions:
        t = r.get("type") or r.get("document_type") or "unknown"
        master["by_type"][t] = master["by_type"].get(t, 0) + 1

    with open(out_dir / "ALL.json", "w") as f:
        json.dump(master, f, indent=2, default=str)
    print(f"\n{'='*70}\nSUMMARY")
    print(f"  total: {len(all_extractions)} files")
    for t, n in master["by_type"].items():
        print(f"    {t}: {n}")
    print(f"  master: {out_dir / 'ALL.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
