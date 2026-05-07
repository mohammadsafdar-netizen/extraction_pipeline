"""
Run VLM extraction on the 12 source PDFs through a vLLM OpenAI-compatible
endpoint. Mirrors run_targeted_vlm.py but talks to vLLM instead of Ollama,
reads PDFs from a local directory, and writes outputs to a model-tagged
directory so 4B/8B/32B runs don't overwrite each other.

Usage:
  python run_vllm_extraction.py                      # all 12 PDFs, both prompt modes
  python run_vllm_extraction.py "26-27 Acord 125.pdf"
  python run_vllm_extraction.py --only-targeted
  python run_vllm_extraction.py --dpi 200
"""
import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

import fitz
import requests

from prompts import GENERALIZED, get_prompt

REPO = Path(__file__).resolve().parent
PDF_DIR = REPO / "pdfs"
DEFAULT_OUT = REPO / "vllm_qwen3vl8b"

VLLM_URL = "http://127.0.0.1:8000/v1/chat/completions"
MODEL = "qwen3-vl-8b"

PDFS = {
    "Acord App (1800 North Stone LLC) 2026.pdf": "acord_application",
    "26-27 Acord 125.pdf": "acord_application",
    "26 GL Application for Prism Broward.pdf": "acord_application",
    "26 XS Application for Prism Broward.pdf": "acord_application",
    "ACORD_112322108_125.pdf": "acord_application",
    "113199142_Genstar Apartment Supp (8).pdf": "supplemental_application",
    "NREPG Questionnaire (01-26).pdf": "questionnaire",
    "Farmers LR 2020-26 (1800 North Stone LLC) VAL 2026.04.03.pdf": "loss_run",
    "LR_21-23 CIBA GL Loss Run 03-18-26.PDF": "loss_run",
    "LR_113199144_Rise Campus Quarters Loss Run.pdf": "loss_run",
    "LR_23-25 Richmond GL Loss Runs 3-19-2026.PDF": "loss_run",
    "LR_25-26_Kinsale GL_3-19-26.PDF": "loss_run",
}


def call_vlm(img_b64: str, prompt: str, timeout: int = 240) -> dict:
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                    },
                ],
            }
        ],
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


def process_pdf(fname: str, doc_type: str, use_targeted: bool, dpi: int) -> dict:
    path = PDF_DIR / fname
    if not path.exists():
        return {"source_file": fname, "_error": f"PDF not found: {path}"}

    doc = fitz.open(path)
    total_pages = len(doc)

    result = {
        "source_file": fname,
        "document_type": doc_type,
        "total_pages": total_pages,
        "model": MODEL,
        "dpi": dpi,
        "prompt_type": "targeted" if use_targeted else "generalized",
        "pages": [],
    }

    for pg in range(total_pages):
        pg_num = pg + 1
        pix = doc[pg].get_pixmap(dpi=dpi)
        img_b64 = base64.b64encode(pix.tobytes("png")).decode()

        if use_targeted:
            prompt = get_prompt(fname, pg_num, total_pages, doc_type)
        else:
            prompt = GENERALIZED
        prompt = f"Page {pg_num}/{total_pages}.\n{prompt}"

        print(f"    p{pg_num}/{total_pages}...", end=" ", flush=True)
        t0 = time.time()
        data = call_vlm(img_b64, prompt)
        ok = "_error" not in data and "_raw" not in data
        elapsed = time.time() - t0
        print(f"{'OK' if ok else 'FAIL'} ({elapsed:.0f}s)", end="")

        if not ok:
            print(" retry...", end=" ", flush=True)
            time.sleep(2)
            data = call_vlm(img_b64, prompt)
            ok = "_error" not in data and "_raw" not in data
            print(f"{'OK' if ok else 'FAIL'}", end="")

        print()
        result["pages"].append({"page": pg_num, "data": data})

    doc.close()
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", help="Specific PDF filename to run (default: all 12)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="Output directory")
    ap.add_argument("--dpi", type=int, default=150, help="Render DPI (default: 150)")
    ap.add_argument("--only-targeted", action="store_true", help="Skip generalized run")
    ap.add_argument("--only-generalized", action="store_true", help="Skip targeted run")
    ap.add_argument("--overwrite", action="store_true", help="Re-run even if output exists")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Sanity: vLLM up?
    try:
        r = requests.get("http://127.0.0.1:8000/v1/models", timeout=5)
        served = [m["id"] for m in r.json().get("data", [])]
        print(f"vLLM reachable. Models served: {served}")
        if MODEL not in served:
            print(f"WARNING: model id {MODEL} not in served list {served}")
    except Exception as e:
        print(f"ERROR: vLLM not reachable on 127.0.0.1:8000 ({e})")
        return 1

    pdfs = {args.target: PDFS[args.target]} if args.target and args.target in PDFS else PDFS

    do_targeted = not args.only_generalized
    do_general = not args.only_targeted

    summary = []
    for fname, doc_type in pdfs.items():
        safe = (fname.replace(" ", "_").replace("(", "").replace(")", "")
                .replace(".pdf", "").replace(".PDF", ""))

        for mode, do_it in (("targeted", do_targeted), ("generalized", do_general)):
            if not do_it:
                continue
            out_path = out_dir / f"{safe}_{mode}.json"
            if out_path.exists() and not args.overwrite:
                print(f"SKIP {mode}: {fname}")
                continue

            print(f"\n{'='*70}\n{mode.upper()}: {fname}")
            t0 = time.time()
            result = process_pdf(fname, doc_type, use_targeted=(mode == "targeted"), dpi=args.dpi)
            ok = sum(1 for p in result.get("pages", [])
                     if "_error" not in p["data"] and "_raw" not in p["data"])
            with open(out_path, "w") as f:
                json.dump(result, f, indent=2)
            tot = result.get("total_pages", 0)
            elapsed = time.time() - t0
            print(f"  {ok}/{tot} OK | {elapsed:.0f}s -> {out_path.name}")
            summary.append((mode, fname, ok, tot, elapsed))

    print(f"\n{'='*70}\nSUMMARY")
    for mode, fname, ok, tot, el in summary:
        print(f"  [{mode:11}] {ok}/{tot}  {el:5.0f}s  {fname}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
