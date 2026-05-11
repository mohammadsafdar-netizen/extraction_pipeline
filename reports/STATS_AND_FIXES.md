# Extraction Pipeline — Final Stats & Verification (2026-05-11)

## Headline Numbers

### How accurate is the pipeline?

| Submission | Correctly Mapped | Total Scored | Accuracy |
|---|---:|---:|---:|
| Sub 1 — 1800 North Stone LLC | 130 | 130 | **100.0%** |
| Sub 2 — Urban Southwest Capital LP | 309 | 312 | **99.0%** |
| Sub 3 — Varsity Campus LLC | 56 | 56 | **100.0%** |
| Sub 4 — Prism Broward, LP | 611 | 612 | **99.8%** |
| Sub 5 — Rise Campus Quarters | 128 | 129 | **99.2%** |
| **Overall** | **1,234** | **1,239** | **99.60%** |

### How much data does the pipeline produce?

| Submission | Mapped JSON Fields (leaf-level) |
|---|---:|
| Sub 1 | 192 |
| Sub 2 | 821 |
| Sub 3 | 132 |
| Sub 4 | 842 |
| Sub 5 | 186 |
| **Total** | **2,173** |

### Verification of your "not present" claims

You provided lists totaling **328 fields** you believed were absent from the submissions. Each was triple-verified against:
1. Our final mapped JSON (`submission_mapped.json`)
2. The per-doc extraction layer (raw bbox + VLM output)
3. The actual source document (PDF/xlsx/docx via direct text & visual)

| Verdict | Count | % of 328 |
|---|---:|---:|
| ✅ **User correct — truly absent in all three sources** | **278** | **85%** |
| ⚠️ **Mapping problem — extraction has it, mapper drops it** | **36** | **11%** |
| ❌ **Already correctly mapped — user just missed it** | **14** | **4%** |

So **15% of your absence claims (50 fields) were wrong** — that data IS in the submissions. Of those: 36 are mapping bugs we should fix; 14 are already correctly extracted.

---

## Categorized Counts (the user's questions)

| Metric | Count |
|---|---:|
| **Total fields user audited** | 328 |
| **Total fields in our mapped JSONs** (leaf-level) | 2,173 |
| **Total fields scored against ground truth** | 1,239 |
| **Correctly mapped (vs GT)** | 1,234 (99.6%) |
| **Mapping problems / mapping challenges** (extraction has data, mapper drops) | **36** |
| **Extraction errors** (we extract WRONG values) | **1** (Prism EBL — now FIXED) |
| **Fields truly not in source** (user's absence claim correct) | **278** |
| **Real extraction bugs found** during audit | **3** (EBL inversion, agent address bled into Street, missing POBox split) |

### What is a "mapping challenge"?

A field where the per-doc extraction layer (`input_extracted_N/*.json`) captured the data correctly — bbox or VLM picked it up — but the mapper logic in `map_to_schema.py` failed to propagate it into the final `submission_mapped.json`. Examples:

- Sub 2: 19 distinct ZIP codes captured from ACORD pages 2,5-7 → mapped JSON has none
- Sub 3: SOV "Lender" column has "Greystone" → mapped JSON has empty SecuredParties
- Sub 4: ACORD 126 Schedule of Hazards has GL class codes (60010, 61217, 48925) for Loc 1 → not joined to Locations
- Sub 5: SOV sidebar text "336 beds" → mapper doesn't parse non-tabular SOV regions

These are NOT extraction errors — the underlying extraction did its job. They're transformation gaps in the schema mapping layer.

### What is an "extraction error"?

The extraction layer (bbox/VLM) produced a value that's WRONG vs the source document. Found exactly 1 of these in this audit:

- **Sub 4 GL.EmployeeBenefitsLiability** — VLM returned `vlm_EMPLOYEE BENEFITS = "Included"` but the ACORD form's EBL line is **blank** (no limit, no deductible, no retro date). The VLM misread the section header presence as the value. **Now FIXED**: mapper requires corroborating evidence (numeric limit, deductible, or retro date) before emitting `Included: true`.

---

## What Was Fixed in This Pass

| # | Fix | Affects | Status |
|---|---|---|---|
| 1 | LossRuns.Claims.ReserveAmount + ReserveAmountProvided | Subs 2, 3, 4 (≥30 claims) | ✅ Fixed |
| 2 | Insured.DescriptionOfOperations from ACORD page 2 | All 4 subs | ✅ Fixed |
| 3 | Locations.Address.County/State/ZipCode enrichment from ACORD PREMISES | Subs 4, 5 | ✅ Fixed |
| 4 | OtherNamedInsureds from VLM continuation pages | Sub 2 (44 entities), Sub 4 (1) | ✅ Fixed |
| 5 | GL.EmployeeBenefitsLiability with corroborating evidence (limit/deductible) | Subs 4, 5 | ✅ Fixed |
| 6 | NPN: prefer `Producer_NationalProducerNumber_A`; separate state license field | Sub 4 | ✅ Fixed |
| 7 | SOV BedCount column + free-text sprinkler parsing | Sub 3 | ✅ Fixed |
| 8 | Agent.Addresses: split City/State/ZipCode when stuck in Street | Subs 1, 2 | ✅ Fixed |
| 9 | SecuredParty.Address.POBox: split "P.O. Box NNNN" from Street | Sub 4 | ✅ Fixed |
| 10 | SecuredParty.ReferenceNumber: pull from `vlm_*_REFERENCE_LOAN` / Text12 | Sub 4 (Santander 7216320, Flagstar 291000307) | ✅ Fixed |

## Still Open (Lower Leverage)

| Field | Sub | Why deferred |
|---|---|---|
| `PolicyInfo.PriorPolicyNumber` from loss-run policy_number | 1, 3 | Semantic ambiguity: the LR policy # is the CURRENT/expiring policy, not necessarily the "prior" |
| `Insured.Website` from email body URLs (`lettermanchicago.com`) | 3 | Email URL parsing — small fix |
| `Agent.Website` / `Agent.Address` from email signature | 3 | Email signature parsing |
| `Locations.Buildings.OccupancyClass` from ACORD 126 Schedule of Hazards | 1, 4, 5 | GL class codes are per-LOCATION (not per-building) on ACORD; needs schema decision on where to place |
| `Locations.GL.OccupancyClass + Exposure` per location | 4, 5 | Same — needs location-to-hazard mapping |
| `Locations.Buildings.BedCount` for sub 5 (sidebar "336 beds") | 5 | Non-tabular SOV parsing |
| `Locations.Buildings.ProtectiveSafeguards` semantic codes from SOV | 2, 3 | Map "Sprinkler %" + "Smoke Detector" strings → standardized codes |
| `Insured.contact.Type` vs `.Title` rename | 2 | Schema decision — store contact role as Type or Title |
| All 20 `Locations.ZipCode` for sub 2 | 2 | Need extraction on additional ACORD pages 5-13 (not just page 2) |

---

## Deliverables in this Bundle

```
stakeholder_delivery_2026-05-11.zip
├── STAKEHOLDER_REPORT.md / .html      (full writeup)
├── STATS_AND_FIXES.md                 (this file)
├── all_submissions_extraction.zip     (extraction bundle)
│   ├── sub*_<name>/
│   │   ├── extracted/                 (per-source-file JSONs)
│   │   │   ├── ALL.json
│   │   │   ├── submission_mapped.json (updated with all fixes)
│   │   │   └── <one .json per source PDF/xlsx/docx>
│   │   ├── gt_<name>.json             (hand-curated ground truth)
│   │   ├── gt_compare_report.txt      (field-by-field diff)
│   │   ├── field_audit.md             (276-field categorization)
│   │   └── triple_check.md            (per-field 3-way verification)
│   └── README.md
```

## Code

Branch: `feat/multi-submission-mapper-audit`
Latest commit: `7d29f21` (Triple-verification fixes)
Commits on branch:
- `b7d15ad` — Multi-submission mapper generalization
- `0fd26ff` — ReserveAmount, DescriptionOfOperations, Location address enrichment
- `9ee7a19` — EBL, OtherNamedInsureds expansion, NPN, BedCount, sprinkler
- `3f08583` — Stakeholder report + audit reports in bundle
- `e44af5d` — Fix wrong NPN extraction; separate state producer license
- `7d29f21` — Triple-verification fixes (EBL, agent address, POBox, ref numbers)
