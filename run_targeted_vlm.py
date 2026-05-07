"""
Run VLM extraction with form-specific targeted prompts on all PDFs.
Also runs with generalized prompt for comparison.
"""
import fitz, base64, json, requests, os, time, sys
from prompts import get_prompt, GENERALIZED

BASE = "/home/safdar/Desktop/inevoai/new_accord_extraction_project/"
OUT_DIR = BASE + "targeted_extractions/"
os.makedirs(OUT_DIR, exist_ok=True)

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3-vl:4b-instruct-q4_K_M"

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


def call_vlm(img_b64, prompt, timeout=180):
    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt, "images": [img_b64]}],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 4096},
        }, timeout=timeout)
        content = resp.json().get("message", {}).get("content", "")
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
                    except:
                        break
    return {"_raw": content[:2000]}


def process_pdf(fname, doc_type, use_targeted=True):
    path = BASE + fname
    doc = fitz.open(path)
    total_pages = len(doc)

    result = {
        "source_file": fname, "document_type": doc_type,
        "total_pages": total_pages, "model": MODEL,
        "prompt_type": "targeted" if use_targeted else "generalized",
        "pages": [],
    }

    for pg in range(total_pages):
        pg_num = pg + 1
        pix = doc[pg].get_pixmap(dpi=150)
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

        # Retry once on failure
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


if __name__ == "__main__":
    # Process specific file or all
    target = sys.argv[1] if len(sys.argv) > 1 else None

    pdfs_to_do = {target: PDFS[target]} if target and target in PDFS else PDFS

    for fname, doc_type in pdfs_to_do.items():
        safe = fname.replace(" ", "_").replace("(", "").replace(")", "").replace(".pdf", "").replace(".PDF", "")

        # Targeted extraction
        out_targeted = OUT_DIR + safe + "_targeted.json"
        if not os.path.exists(out_targeted):
            print(f"\n{'='*70}")
            print(f"TARGETED: {fname}")
            t0 = time.time()
            result = process_pdf(fname, doc_type, use_targeted=True)
            ok = sum(1 for p in result["pages"] if "_error" not in p["data"] and "_raw" not in p["data"])
            with open(out_targeted, "w") as f:
                json.dump(result, f, indent=2)
            print(f"  {ok}/{result['total_pages']} OK | {time.time()-t0:.0f}s")
        else:
            print(f"SKIP targeted: {fname}")

        # Generalized extraction
        out_general = OUT_DIR + safe + "_generalized.json"
        if not os.path.exists(out_general):
            print(f"\n{'='*70}")
            print(f"GENERALIZED: {fname}")
            t0 = time.time()
            result = process_pdf(fname, doc_type, use_targeted=False)
            ok = sum(1 for p in result["pages"] if "_error" not in p["data"] and "_raw" not in p["data"])
            with open(out_general, "w") as f:
                json.dump(result, f, indent=2)
            print(f"  {ok}/{result['total_pages']} OK | {time.time()-t0:.0f}s")
        else:
            print(f"SKIP generalized: {fname}")

    print(f"\n{'='*70}")
    print("ALL DONE")
