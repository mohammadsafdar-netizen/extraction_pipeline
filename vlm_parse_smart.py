"""
Smart VLM parsing — lower DPI, shorter timeout, retry logic.
Skip already-completed files.
"""
import fitz, base64, json, requests, os, time

BASE = "/home/safdar/Desktop/inevoai/new_accord_extraction_project/"
OUT_DIR = BASE + "vlm_extractions/"
os.makedirs(OUT_DIR, exist_ok=True)

MODEL = "qwen3-vl:4b-instruct-q4_K_M"

PDFS = {
    # Loss runs first (small, high value)
    "Farmers LR 2020-26 (1800 North Stone LLC) VAL 2026.04.03.pdf": "loss_run",
    "LR_21-23 CIBA GL Loss Run 03-18-26.PDF": "loss_run",
    "LR_113199144_Rise Campus Quarters Loss Run.pdf": "loss_run",
    "LR_23-25 Richmond GL Loss Runs 3-19-2026.PDF": "loss_run",
    "LR_25-26_Kinsale GL_3-19-26.PDF": "loss_run",
    # Supplemental / questionnaire (small)
    "113199142_Genstar Apartment Supp (8).pdf": "supplemental_application",
    "NREPG Questionnaire (01-26).pdf": "questionnaire",
    # ACORD applications (large - do last)
    "ACORD_112322108_125.pdf": "acord_application",
    "26 GL Application for Prism Broward.pdf": "acord_application",
    "26 XS Application for Prism Broward.pdf": "acord_application",
    "26-27 Acord 125.pdf": "acord_application",
    "Acord App (1800 North Stone LLC) 2026.pdf": "acord_application",
}

PROMPTS = {
    "acord_application": """Extract ALL filled data from this ACORD insurance application page into JSON.
Use field labels as keys, filled values as values. Include:
- Header: date, agency, carrier, policy number, named insured, address
- All filled text fields, all checked checkboxes (true), all table rows with data
- Coverages, limits, premiums, classifications, premises/building info
- Skip empty/blank fields entirely.
Return ONLY a valid JSON object. /no_think""",

    "supplemental_application": """Extract ALL filled data from this supplemental insurance application into JSON.
Include: applicant info, property details, construction, occupancy, management,
financial data, loss history, all questions with answers, all table rows.
Skip empty fields. Return ONLY valid JSON. /no_think""",

    "questionnaire": """Extract ALL filled data from this insurance questionnaire page into JSON.
Include: applicant info, property details, all Q&A, management, financials,
occupancy data, tables. Skip empty fields. Return ONLY valid JSON. /no_think""",

    "loss_run": """Extract ALL data from this loss run page into JSON.
Include:
- Header: policy#, insured, address, carrier, agent, dates
- Claims: claim#, date_of_loss, type, paid, reserved, expenses, recovered, status, date_closed
- Summary totals. Use numbers for dollar amounts.
- Note "NO LOSSES OR CLAIMS REPORTED" if stated.
Return ONLY valid JSON. /no_think""",
}


def call_vlm(img_b64, prompt, page_num, total_pages, timeout=180):
    full_prompt = f"Page {page_num}/{total_pages}.\n{prompt}"
    try:
        resp = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": full_prompt, "images": [img_b64]}],
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 4096},
            },
            timeout=timeout,
        )
        content = resp.json().get("message", {}).get("content", "")
    except Exception as e:
        return {"_error": str(e)}

    if not content:
        return {"_error": "empty_response"}

    # Find JSON object or array
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        idx = content.find(start_char)
        if idx >= 0:
            depth = 0
            for i in range(idx, len(content)):
                if content[i] == start_char: depth += 1
                elif content[i] == end_char: depth -= 1
                if depth == 0:
                    try:
                        return json.loads(content[idx:i+1])
                    except:
                        break

    return {"_raw": content[:2000]}


def process_pdf(fname, doc_type):
    path = BASE + fname
    doc = fitz.open(path)
    num_pages = len(doc)
    prompt = PROMPTS[doc_type]

    result = {
        "source_file": fname,
        "document_type": doc_type,
        "total_pages": num_pages,
        "method": "qwen3-vl-8b",
        "pages": [],
    }

    for pg in range(num_pages):
        # Use 150 DPI for forms, 200 for loss runs (smaller pages)
        dpi = 200 if doc_type == "loss_run" else 150
        pix = doc[pg].get_pixmap(dpi=dpi)
        img_b64 = base64.b64encode(pix.tobytes("png")).decode()

        print(f"    Page {pg+1}/{num_pages}...", end=" ", flush=True)
        t0 = time.time()

        # Try up to 2 times
        data = None
        for attempt in range(2):
            data = call_vlm(img_b64, prompt, pg + 1, num_pages)
            if "_error" not in data and "_raw" not in data:
                break
            if attempt == 0:
                print("retry...", end=" ", flush=True)
                time.sleep(3)

        elapsed = time.time() - t0
        ok = "_error" not in data and "_raw" not in data
        print(f"{'OK' if ok else 'FAIL'} ({elapsed:.0f}s)")

        result["pages"].append({"page": pg + 1, "data": data})

    doc.close()
    return result


def is_complete(out_path):
    """Check if output file exists and all pages parsed OK."""
    if not os.path.exists(out_path):
        return False
    with open(out_path) as f:
        data = json.load(f)
    return all(
        "_error" not in p.get("data", {}) and "_raw" not in p.get("data", {})
        for p in data.get("pages", [])
    )


total_start = time.time()
done = 0
skipped = 0

for fname, doc_type in PDFS.items():
    safe = fname.replace(" ", "_").replace("(", "").replace(")", "").replace(".pdf", "").replace(".PDF", "")
    out_path = OUT_DIR + safe + ".json"

    if is_complete(out_path):
        skipped += 1
        print(f"SKIP: {fname}")
        continue

    print(f"\n{'='*60}")
    print(f"{fname} ({doc_type})")
    t0 = time.time()

    result = process_pdf(fname, doc_type)

    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    ok = sum(1 for p in result["pages"] if "_error" not in p["data"] and "_raw" not in p["data"])
    print(f"  {ok}/{result['total_pages']} OK | {time.time()-t0:.0f}s | {out_path}")
    done += 1

total_elapsed = time.time() - total_start
print(f"\n{'='*60}")
print(f"DONE: {done} processed, {skipped} skipped | {total_elapsed:.0f}s total")
