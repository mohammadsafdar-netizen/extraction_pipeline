"""
Loss-run merged extraction: pdfplumber tables/words + vLLM cross-check.

Loss runs lack AcroForm templates, so the bbox path used for ACORD apps
doesn't apply. Instead we use:

  1. pdfplumber.extract_tables() with multiple strategies — captures
     claim # / dates / amounts when the loss run is digital and tabular.
  2. pdfplumber.extract_words() — fallback positioned-text source.
  3. VLM full-page extraction (qwen3-vl-8b) via prompts.LOSS_RUN.
  4. Cross-validation: every claim_number / dollar amount the VLM emits
     is checked against pdfplumber's text content; mismatches flagged.

Garbled-font PDFs (e.g. CIBA) get VLM-only with a `garbled_font: true` flag.

Usage:
  python run_vllm_loss_runs.py                              # all 5 loss runs
  python run_vllm_loss_runs.py "LR_25-26_Kinsale GL_3-19-26.PDF"
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
import requests

from prompts import LOSS_RUN
from run_vllm_merged import _scrub_vlm_garbage  # reuse template-garbage scrubber

REPO = Path(__file__).resolve().parent
PDF_DIR = REPO / "pdfs"
DEFAULT_OUT = REPO / "merged_loss_runs"

VLLM_URL = "http://127.0.0.1:8000/v1/chat/completions"
DEFAULT_MODEL = "qwen3-vl-8b"
MODEL = DEFAULT_MODEL

LOSS_RUN_PDFS = [
    "Farmers LR 2020-26 (1800 North Stone LLC) VAL 2026.04.03.pdf",
    "LR_21-23 CIBA GL Loss Run 03-18-26.PDF",
    "LR_113199144_Rise Campus Quarters Loss Run.pdf",
    "LR_23-25 Richmond GL Loss Runs 3-19-2026.PDF",
    "LR_25-26_Kinsale GL_3-19-26.PDF",
]


# ── pdfplumber side ──

def extract_pdfplumber_data(pdf_path: Path) -> dict:
    """Return {pages: [{garbled, tables, raw_text, words_count}]}."""
    out = {"pages": []}
    pdf = pdfplumber.open(str(pdf_path))
    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        garbled = "(cid:" in text

        tables = []
        if not garbled:
            try:
                tables = page.extract_tables() or []
            except Exception:
                tables = []
            # If default got only headers (1-row tables), retry with text strategy
            if tables and all(len(t) <= 1 for t in tables):
                try:
                    alt = page.extract_tables({
                        "vertical_strategy": "text",
                        "horizontal_strategy": "text",
                        "snap_tolerance": 4,
                    }) or []
                    if alt and any(len(t) > 1 for t in alt):
                        tables = alt
                except Exception:
                    pass

        words_count = 0
        try:
            words_count = len(page.extract_words(
                keep_blank_chars=True, x_tolerance=2, y_tolerance=2))
        except Exception:
            pass

        out["pages"].append({
            "page": i + 1,
            "garbled_font": garbled,
            "raw_text": text if not garbled else "",
            "raw_text_chars": len(text),
            "words_count": words_count,
            "tables": [
                [[(c.strip() if isinstance(c, str) else c) for c in row]
                 for row in t]
                for t in tables
            ],
        })
    pdf.close()
    return out


def parse_pdfplumber_claims(pdf_data: dict) -> list:
    """Extract structured claim rows from pdfplumber tables when possible.
       Currently handles Richmond-style tables (multi-column claim listings)."""
    claims = []
    for pg in pdf_data["pages"]:
        for t in pg["tables"]:
            if not t or len(t) < 2:
                continue
            # Find a header row that looks like a claims-listing header
            header_idx = None
            for ri, row in enumerate(t):
                joined = " ".join(c or "" for c in row).lower()
                if ("claim #" in joined or "claim no" in joined or
                        "claim number" in joined):
                    header_idx = ri
                    break
            if header_idx is None:
                continue

            header = [c or "" for c in t[header_idx]]
            for row in t[header_idx + 1:]:
                if not any(c for c in row):
                    continue
                rec = {"_page": pg["page"]}
                for col, val in zip(header, row):
                    if not col:
                        continue
                    key = (col.strip().lower()
                           .replace(" ", "_").replace("#", "no")
                           .replace("/", "_").replace("-", "_"))
                    rec[key] = val.strip() if isinstance(val, str) else val
                if any(v for k, v in rec.items() if k != "_page"):
                    claims.append(rec)
    return claims


# ── VLM side ──

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
                if content[i] == sc: depth += 1
                elif content[i] == ec: depth -= 1
                if depth == 0:
                    try:
                        return json.loads(content[idx:i + 1])
                    except Exception:
                        break
    return {"_raw": content[:4000]}


def run_vlm(pdf_path: Path, dpi: int) -> list:
    doc = fitz.open(str(pdf_path))
    out = []
    total = len(doc)
    for pg in range(total):
        pix = doc[pg].get_pixmap(dpi=dpi)
        img_b64 = base64.b64encode(pix.tobytes("png")).decode()
        prompt = f"Page {pg+1}/{total}.\n{LOSS_RUN}"
        print(f"    p{pg+1}/{total}...", end=" ", flush=True)
        t0 = time.time()
        data = call_vlm(img_b64, prompt)
        ok = "_error" not in data and "_raw" not in data
        elapsed = time.time() - t0
        print(f"{'OK' if ok else 'FAIL'} ({elapsed:.0f}s)")
        # Scrub form-template garbage (e.g. VLM emitting form question
        # text or all-None nested dicts as if they were extracted data).
        if ok:
            scrubbed = _scrub_vlm_garbage(data)
            if scrubbed is None:
                data = {}
            else:
                data = scrubbed
        out.append({"page": pg + 1, "data": data})
    doc.close()
    return out


# ── Cross-validate ──

CLAIM_NO_RE = re.compile(r"\b[A-Z]{0,4}-?\d[\dA-Z\-]{3,}\b")
DOLLAR_RE = re.compile(r"\$?\s?[\d,]+\.\d{2}|\$?\s?[\d,]{4,}")


def collect_strings(obj):
    """Yield every leaf string/number in a nested JSON structure."""
    if isinstance(obj, dict):
        for v in obj.values():
            yield from collect_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from collect_strings(v)
    else:
        if obj is not None:
            yield str(obj)


def _norm(s: str) -> str:
    """Normalize for forgiving compare: lowercase, drop $/,, collapse all
       whitespace (including newlines) to a single space, strip leading
       zeros from M/D/Y date components ("03/19/2026" → "3/19/2026")."""
    out = re.sub(r"\s+", " ", str(s).lower().replace(",", "").replace("$", "")).strip()
    # Strip leading zeros from date components: "0X/" → "X/", "/0X" → "/X"
    out = re.sub(r"\b0(\d)/", r"\1/", out)
    out = re.sub(r"/0(\d)\b", r"/\1", out)
    return out


def cross_validate(vlm_pages: list, pdf_data: dict) -> list:
    """Return discrepancy entries: VLM-emitted data-shaped strings not present
       in raw text. Skips short or non-data strings to avoid false positives."""
    out = []
    raw_pages = {p["page"]: p["raw_text"] for p in pdf_data["pages"]}

    for p in vlm_pages:
        pg = p["page"]
        data = p.get("data") or {}
        raw = raw_pages.get(pg, "") or ""
        if not raw:
            continue  # garbled page — skip cross-check
        raw_norm = _norm(raw)

        for s in collect_strings(data):
            s_str = str(s).strip()
            if len(s_str) < 4:
                continue
            check = _norm(s_str)
            if not check:
                continue
            # Only flag strings that look like specific data values
            # (claim numbers or dollar amounts) — not free-form text fields
            looks_numeric = bool(re.search(r"\d", check)) and len(check) >= 4
            looks_claim_no = bool(CLAIM_NO_RE.search(s_str))
            if not (looks_numeric or looks_claim_no):
                continue
            # Skip if any whitespace-collapsed substring of the value is
            # in the normalized raw text
            if check in raw_norm:
                continue
            # Also try without whitespace at all (handles cases like
            # "1800 N Stone Ave\nTucson AZ" → joined string compare)
            check_nows = check.replace(" ", "")
            raw_nows = raw_norm.replace(" ", "")
            if check_nows in raw_nows:
                continue
            # Token-level fallback: if every whitespace-separated token of
            # the VLM value appears somewhere in raw_norm, accept it.
            # Handles address-layout cases where pdfplumber serializes
            # tokens in a different order than the VLM emits them.
            tokens = [t for t in check.split(" ") if len(t) >= 2]
            if tokens and all(t in raw_norm for t in tokens):
                continue
            out.append({"page": pg, "vlm_value": s,
                        "issue": "not_in_raw_text"})
    return out


# ── Main ──

def process_pdf(fname: str, pdf_dir: Path, dpi: int) -> dict:
    pdf_path = pdf_dir / fname
    if not pdf_path.exists():
        return {"source_file": fname, "_error": f"not found: {pdf_path}"}

    print(f"  pdfplumber...")
    t0 = time.time()
    pdf_data = extract_pdfplumber_data(pdf_path)
    parsed_claims = parse_pdfplumber_claims(pdf_data)
    n_garbled = sum(1 for p in pdf_data["pages"] if p["garbled_font"])
    n_tables = sum(len(p["tables"]) for p in pdf_data["pages"])
    print(f"    pdfplumber: {len(pdf_data['pages'])} pages, "
          f"{n_tables} tables, {len(parsed_claims)} parsed claim rows, "
          f"{n_garbled} garbled ({time.time()-t0:.0f}s)")

    print(f"  vLLM...")
    vlm_pages = run_vlm(pdf_path, dpi)

    print(f"  cross-validate...")
    discrepancies = cross_validate(vlm_pages, pdf_data)
    print(f"    {len(discrepancies)} VLM values not found in raw PDF text")

    return {
        "source_file": fname,
        "model": MODEL,
        "dpi": dpi,
        "pdfplumber": pdf_data,
        "pdfplumber_parsed_claims": parsed_claims,
        "vlm_pages": vlm_pages,
        "discrepancies": discrepancies,
    }


def main():
    global MODEL
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--pdf-dir", default=str(PDF_DIR))
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    MODEL = args.model

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir = Path(args.pdf_dir)

    try:
        r = requests.get("http://127.0.0.1:8000/v1/models", timeout=5)
        served = [m["id"] for m in r.json().get("data", [])]
        print(f"vLLM served: {served}")
    except Exception as e:
        print(f"ERROR: vLLM unreachable ({e})"); return 1

    targets = [args.target] if args.target else LOSS_RUN_PDFS

    for fname in targets:
        safe = (fname.replace(" ", "_").replace("(", "").replace(")", "")
                .replace(".pdf", "").replace(".PDF", ""))
        out_path = out_dir / f"{safe}_lossrun.json"
        if out_path.exists() and not args.overwrite:
            print(f"SKIP: {fname}"); continue
        print(f"\n{'='*70}\nLOSS RUN: {fname}")
        t0 = time.time()
        result = process_pdf(fname, pdf_dir, args.dpi)
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"  -> {out_path.name}  ({time.time()-t0:.0f}s)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
