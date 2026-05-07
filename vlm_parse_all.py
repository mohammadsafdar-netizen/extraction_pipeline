"""
VLM structured parsing pipeline for all PDFs.
Sends each page to Qwen3-VL with document-type-specific prompts.
"""
import fitz, base64, json, requests, os, time, sys

BASE = "/home/safdar/Desktop/inevoai/new_accord_extraction_project/"
OUT_DIR = BASE + "vlm_extractions/"
os.makedirs(OUT_DIR, exist_ok=True)

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3-vl:8b"

# Classify each PDF
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

PROMPTS = {
    "acord_application": """Extract ALL data from this ACORD insurance application page into structured JSON.
For each field, use the ACORD field label as the key and the filled value as the value.
Include:
- Header fields (date, agency, carrier, policy number, etc.)
- All filled text fields with their values
- All checked checkboxes (mark as true)
- Table data (coverages, limits, classifications, premises info, etc.)
- Named insured info, addresses, phone numbers, entity type
Skip empty/unfilled fields. Return ONLY valid JSON. /no_think""",

    "supplemental_application": """Extract ALL data from this insurance supplemental application page into structured JSON.
Include every filled field: applicant info, property details, construction, occupancy, 
management info, financial data, loss history, and all table rows.
Skip empty fields. Return ONLY valid JSON. /no_think""",

    "questionnaire": """Extract ALL data from this insurance questionnaire page into structured JSON.
Include: applicant info, property details, all questions with their answers (yes/no/text),
management details, financial info, occupancy data, and any table data.
Skip empty fields. Return ONLY valid JSON. /no_think""",

    "loss_run": """Extract ALL data from this insurance loss run page into structured JSON.
Include:
- Header: policy number, insured name, address, carrier, dates, agent/broker
- Each claim: claim number, date of loss, type/cause, amounts (paid, reserved, expenses, recovered), status, date closed
- Summary totals if present
- "NO LOSSES OR CLAIMS REPORTED" if stated
For dollar amounts use numbers not strings. Return ONLY valid JSON. /no_think""",
}


def call_vlm(img_b64, prompt, page_num, total_pages):
    """Send image to Qwen3-VL, return parsed JSON or raw text."""
    full_prompt = f"Page {page_num} of {total_pages}.\n{prompt}"
    
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": full_prompt, "images": [img_b64]}],
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 4096},
            },
            timeout=300,
        )
        content = resp.json().get("message", {}).get("content", "")
    except Exception as e:
        return {"error": str(e)}
    
    if not content:
        return {"error": "empty response"}
    
    # Extract JSON from response
    brace_start = content.find("{")
    bracket_start = content.find("[")
    
    # Pick whichever comes first
    start = -1
    end_char = "}"
    if brace_start >= 0 and (bracket_start < 0 or brace_start < bracket_start):
        start = brace_start
        end_char = "}"
    elif bracket_start >= 0:
        start = bracket_start
        end_char = "]"
    
    if start >= 0:
        depth = 0
        open_c = "{" if end_char == "}" else "["
        close_c = end_char
        for i in range(start, len(content)):
            if content[i] == open_c: depth += 1
            elif content[i] == close_c: depth -= 1
            if depth == 0:
                try:
                    return json.loads(content[start:i+1])
                except json.JSONDecodeError:
                    break
    
    return {"raw_text": content[:3000]}


def process_pdf(fname, doc_type):
    """Process all pages of a PDF through VLM."""
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
        pix = doc[pg].get_pixmap(dpi=150)  # 150 DPI to save VRAM
        img_b64 = base64.b64encode(pix.tobytes("png")).decode()
        
        print(f"    Page {pg+1}/{num_pages}...", end=" ", flush=True)
        t0 = time.time()
        data = call_vlm(img_b64, prompt, pg + 1, num_pages)
        elapsed = time.time() - t0
        
        is_error = "error" in data or "raw_text" in data
        status = "FAIL" if is_error else "OK"
        print(f"{status} ({elapsed:.0f}s)")
        
        result["pages"].append({"page": pg + 1, "data": data})
    
    doc.close()
    return result


if __name__ == "__main__":
    # Process specific file if given as argument, otherwise all
    if len(sys.argv) > 1:
        target = sys.argv[1]
        if target in PDFS:
            pdfs_to_do = {target: PDFS[target]}
        else:
            print(f"Unknown file: {target}")
            sys.exit(1)
    else:
        pdfs_to_do = PDFS
    
    for fname, doc_type in pdfs_to_do.items():
        safe = fname.replace(" ", "_").replace("(", "").replace(")", "").replace(".pdf", "").replace(".PDF", "")
        out_path = OUT_DIR + safe + ".json"
        
        # Skip if already done
        if os.path.exists(out_path):
            with open(out_path) as f:
                existing = json.load(f)
            # Check if all pages have actual data (not errors)
            all_ok = all("error" not in p.get("data", {}) and "raw_text" not in p.get("data", {}) 
                        for p in existing.get("pages", []))
            if all_ok:
                print(f"\nSKIP (already done): {fname}")
                continue
        
        print(f"\n{'='*60}")
        print(f"Processing: {fname} ({doc_type})")
        t0 = time.time()
        
        result = process_pdf(fname, doc_type)
        
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)
        
        elapsed = time.time() - t0
        ok_count = sum(1 for p in result["pages"] if "error" not in p["data"] and "raw_text" not in p["data"])
        print(f"  Done: {ok_count}/{result['total_pages']} pages OK | {elapsed:.0f}s total")
        print(f"  Saved: {out_path}")
    
    print(f"\n{'='*60}")
    print("ALL DONE")
