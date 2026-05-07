# Agent Handoff — Insurance Document Extraction Pipeline

## Where We Are Right Now

### Status: Prompt engineering on 4B model hit a ceiling. Need to test 8B model with improved prompts.

The pipeline works end-to-end. 12 PDFs (87 pages) are processed. The core issue is the **Qwen3-VL 4B quantized model doesn't reliably follow detailed prompt instructions**, leading to:

1. **Checkbox hallucination** — lists all checkbox options as checked even when they're not (Lines of Business, Attachments, entity types)
2. **Label-as-value** — captures form labels ("Y/N", "$", "PRODUCER'S SIGNATURE") as data values
3. **Footer code confusion** — "LBAKER", "LMOSS" (user ID watermarks) captured as contact names
4. **Field swaps** — SIC↔GL code, FEIN↔NAICS, class_code↔premium_basis, reported_date↔date_closed
5. **Carrier name spelling drift** — same carrier spelled differently across pages
6. **Date format flips** — MM/DD/YYYY becoming DD/MM/YYYY or ISO format inconsistently

### Immediate Next Step

**Run the 8B model (`qwen3-vl:8b`) with the current improved prompts in `prompts.py`.** The prompts are well-written with explicit rules against all the above issues. The 4B model is too small to follow them. The 8B model showed 100% accuracy on the CIBA loss run when tested earlier, but was abandoned because it caused timeouts on 6GB VRAM. Options:

1. Try 8B again — it loaded at 32%/68% CPU/GPU split. Slower (~60-100s/page) but may follow prompts better.
2. Try a different VLM (e.g., `minicpm-v`, `internvl2`, or the latest `qwen2.5-vl` if available on ollama)
3. Use a cloud API (Claude vision, GPT-4V) for accuracy-critical pages

---

## Project Structure

```
/home/safdar/Desktop/inevoai/new_accord_extraction_project/
├── app.py                          # Streamlit visual verifier UI
├── prompts.py                      # All prompts (CRITICAL — this is where accuracy lives)
├── run_targeted_vlm.py             # Main VLM extraction runner (targeted + generalized)
├── extractor.py                    # Coordinate-based extractor for ACORD forms
├── merged_extractor.py             # Merged pipeline (bbox + VLM)
├── vlm_parse_smart.py              # Bulk VLM runner for all PDFs
├── ACCURACY_REPORT.md              # Full accuracy report from earlier today
├── AGENT_HANDOFF.md                # THIS FILE
│
├── *.pdf / *.PDF                   # 12 source PDFs (not in git)
├── all_extractions.zip             # All extraction JSONs packaged
│
├── targeted_extractions/           # Latest VLM outputs (targeted + generalized prompts)
│   ├── *_targeted.json             # Form-specific prompt results
│   └── *_generalized.json          # Universal prompt results
│
├── vlm_extractions/                # Older VLM outputs (8B model, generic prompt)
├── extractions/                    # pdfplumber raw text extractions
│
├── templates/                      # Blank fillable ACORD template PDFs
│   ├── acord_125.pdf               # 551 AcroForm fields
│   ├── acord_126.pdf               # 279 fields (2009 edition — wrong)
│   ├── acord_126_2014.pdf          # 255 fields (correct edition)
│   ├── acord_131.pdf               # 405 fields
│   ├── acord_140.pdf               # 355 fields
│   ├── acord_823.pdf               # 884 fields
│   └── template_fields.json        # All field definitions with bbox/tooltip
│
├── bbox_extracted_fields.json      # Adaptive-offset bbox extraction
├── aligned_bbox_extracted.json     # Anchor-aligned bbox extraction
├── merged_extraction.json          # Merged (bbox + VLM) extraction
├── cross_validation_report.json    # Cross-validation results
├── loss_run_extracted.json         # Farmers LR (regex extraction)
└── ciba_loss_run_extracted.json    # CIBA LR (regex extraction)
```

---

## The 12 Source PDFs

| # | File | Type | Pages | Text Extractable? |
|---|------|------|-------|-------------------|
| 1 | Acord App (1800 North Stone LLC) 2026.pdf | ACORD 125+140+126+131 | 25 | Yes (flattened) |
| 2 | 26-27 Acord 125.pdf | ACORD 125 + supplements | 14 | Yes |
| 3 | 26 GL Application for Prism Broward.pdf | ACORD 125+126 | 12 | Yes |
| 4 | 26 XS Application for Prism Broward.pdf | ACORD 125+131 | 12 | Yes |
| 5 | ACORD_112322108_125.pdf | ACORD 125 (blank) | 4 | NO — garbled font, needs OCR/VLM |
| 6 | 113199142_Genstar Apartment Supp (8).pdf | Supplemental (blank) | 4 | Yes |
| 7 | NREPG Questionnaire (01-26).pdf | Questionnaire | 6 | Yes |
| 8 | Farmers LR 2020-26 (1800 North Stone LLC).pdf | Loss Run | 4 | Yes |
| 9 | LR_21-23 CIBA GL Loss Run 03-18-26.PDF | Loss Run (multi-property) | 2 | NO — garbled font |
| 10 | LR_113199144_Rise Campus Quarters Loss Run.pdf | Loss Run (letter format) | 1 | Yes |
| 11 | LR_23-25 Richmond GL Loss Runs 3-19-2026.PDF | Loss Run (tabular) | 2 | Yes |
| 12 | LR_25-26_Kinsale GL_3-19-26.PDF | Loss Run (tabular) | 1 | Yes |

---

## Extraction Methods Tested (in order of accuracy)

### 1. VLM with Targeted Prompts — BEST but needs bigger model
- **How:** Render page as image → send to VLM with form-specific prompt from `prompts.py` → get JSON
- **Model tested:** Qwen3-VL 4B q4_K_M (3.3GB, fits 100% on 6GB GPU)
- **Speed:** ~10-30s/page
- **Issue:** 4B model doesn't follow complex prompt instructions. Needs 8B or cloud model.

### 2. VLM with Generalized Prompt — Good for unknown forms
- **How:** Same as above but one universal prompt for any document
- **Accuracy:** ~1-2% below targeted prompts
- **Advantage:** Zero maintenance, works on any layout

### 3. Anchor-Aligned BBOX Template Mapping
- **How:** Use blank ACORD template field bboxes → compute dy offset from label anchors → extract text
- **Accuracy:** 80.6% — good for amounts/checkboxes, bad for text fields
- **Code:** `extractor.py`, `aligned_bbox_extracted.json`

### 4. pdfplumber + Regex
- **How:** Extract text → regex parse
- **Accuracy:** 95-100% on digital PDFs, 0% on garbled fonts
- **Best for:** Cross-validation against VLM output

---

## Known Issues (Current State)

### Still broken on 4B model:
1. **All 15 Lines of Business listed on 1800 N Stone p1** — prompt says "only with X" but model ignores
2. **LBAKER footer code as contact name** — prompt explicitly warns against this, model ignores
3. **Entity type "INDIVIDUAL" on 1800 N Stone** — should be "LLC" (X is next to LLC)
4. **Both claims_made AND occurrence = true** on p16 — should be occurrence only
5. **Richmond: date_closed = date_of_loss for closed claims** — hallucinated (no close date column exists)
6. **Carrier name "Aeternity"** on 26-27 Acord — correct spelling is "Ategrity"
7. **CIBA: claims still attributed to wrong property block** on page 2

### Fixed in latest prompts (but untested on 8B):
- Loss run schema now has separate `reported_date` and `date_closed` fields
- Explicit rules against checkbox hallucination
- Explicit rules against label-as-value capture
- Carrier name instruction to spell exactly as printed
- Multi-property claim attribution rules

---

## Hardware

- **GPU:** NVIDIA RTX 4050 Laptop, 6GB VRAM
- **RAM:** 24GB
- **CPU:** AMD Ryzen 7 7435HS
- **Ollama models available:**
  - `qwen3-vl:8b` (6.1GB — loads 32/68 CPU/GPU split, slow but potentially more accurate)
  - `qwen3-vl:4b-instruct-q4_K_M` (3.3GB — fits 100% GPU, fast but misses prompt instructions)
  - `qwen2.5:7b` (text-only LLM, used for OCR→LLM pipeline test)
  - `llama3.2:3b` (text-only)

---

## How to Run

```bash
cd /home/safdar/Desktop/inevoai/new_accord_extraction_project

# Start Streamlit visual verifier
streamlit run app.py --server.headless true

# Run VLM extraction on a specific PDF (both targeted + generalized)
python3 run_targeted_vlm.py "LR_25-26_Kinsale GL_3-19-26.PDF"

# Run on all PDFs
python3 run_targeted_vlm.py

# To switch models, edit MODEL in run_targeted_vlm.py or vlm_parse_smart.py
```

---

## What To Do Next

1. **Test 8B model with current prompts** — swap `MODEL = "qwen3-vl:8b"` in `run_targeted_vlm.py` and re-run the 7 problematic files. If VRAM timeouts occur, try reducing DPI to 100 or processing one page at a time with cooldown.

2. **If 8B still hallucinates checkboxes** — the VLM approach may need a two-pass strategy: first pass extracts all text, second pass specifically asks about checkboxes with "Is there an X mark next to [field]? Answer ONLY yes or no."

3. **Consider cloud VLM for accuracy-critical forms** — Claude vision or GPT-4V would likely solve all hallucination issues. Cost is the tradeoff.

4. **The 5 unchanged files need re-running** — Genstar, GL Prism, XS Prism, ACORD 112322108, NREPG still have the old 8B generic-prompt extractions. Re-run with new prompts.

5. **Build a post-processing validator** — cross-check VLM output against pdfplumber raw text, flag any value that doesn't appear in the raw text. This catches hallucinations automatically.
