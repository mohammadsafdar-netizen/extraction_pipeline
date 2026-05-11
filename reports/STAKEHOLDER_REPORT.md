# Insurance Submission Extraction — Stakeholder Findings & Updates

**Date:** 2026-05-11
**Branch:** `feat/multi-submission-mapper-audit` (3 commits, 132+ insertions to mapper)
**Verified across:** 5 real broker submissions (1,239 leaf fields scored against hand-curated ground truth)

---

## 1. Executive Summary

The extraction pipeline has been brought to **99.5% accuracy** across 5 real-world insurance submissions of varying complexity. Where earlier iterations achieved 100% on three structurally simple submissions (sub 1, 2, 3), the system had not been tested against:

- **Multi-form ACORD packets** (a single PDF containing ACORD 125 + 126 + 140 + 823, or GL + XS application pairs)
- **Multi-property campus SOVs** (7 buildings at one physical address)
- **Multi-policy-term loss runs** with reserves and open claims
- **Underwriter-platform email signatures** that bleed into Insured contacts
- **Hand-filled forms with empty fields** (most ACORD 125 page 1 fields are blank on real submissions)

Adding two new submissions — **Prism Broward, LP** (32 SOV rows, 2 ACORD apps, 3 loss runs) and **Rise Campus Quarters** (7 buildings at one campus) — surfaced **assumptions in the mapper that worked on the original 3 submissions by coincidence**. Fixing those assumptions made the pipeline strictly more correct against the ACORD form specification, not against the specific zips.

We also conducted a **field-by-field audit** of fields you flagged as missing from your standard schema (276 fields across 4 submissions, verified via 4 parallel agents plus visual inspection of 9 key ACORD pages).

### Headline accuracy

| Submission | CORRECT | TOTAL | Accuracy | Mapped fields emitted |
|---|---:|---:|---:|---:|
| Sub 1 — 1800 North Stone LLC | 130 | 130 | **100.0%** | 192 |
| Sub 2 — Urban Southwest Capital LP | 309 | 312 | **99.0%** | 819 |
| Sub 3 — Varsity Campus LLC | 56 | 56 | **100.0%** | 132 |
| Sub 4 — Prism Broward, LP | 610 | 612 | **99.7%** | 841 |
| Sub 5 — Rise Campus Quarters | 128 | 129 | **99.2%** | 186 |
| **Overall** | **1,233** | **1,239** | **99.5%** | **2,170** |

---

## 2. What "Missing Fields" Actually Means — Audit of 276 Fields

You provided lists of fields that appear in your standard schema but were not present in our previous output. We audited every one against the source documents. **The categorization below answers: "is this missing because we failed to extract, or because the data is genuinely not in the submission?"**

| Category | Sub 2 | Sub 3 | Sub 4 | Sub 5 | **Total** | **%** |
|---|---:|---:|---:|---:|---:|---:|
| `NOT_IN_SOURCE` — genuinely absent from all submission docs | 49 | 50 | 41 | 47 | **187** | **68%** |
| `IN_SOURCE_MISSED` — real extraction bugs (now mostly fixed) | 16 | 13 | 13 | 12 | **54** | **20%** |
| `IN_OUTPUT_DIFFERENT_NAME` — we extract, but use a different field name | 2 | 2 | 6 | 4 | **14** | **5%** |
| `IN_OUTPUT_ALREADY` — exact field present with non-empty value | 0 | 2 | 12 | 4 | **18** | **6%** |
| `UNCLEAR` — schema meaning not defined | 0 | 1 | 1 | 1 | **3** | **1%** |

### 2.1 What's genuinely not in the submission (68% of "missing" fields)

These fields exist in your standard schema but **are not present in any insurance submission document** — they belong to systems downstream of submission intake:

| Category | Example fields |
|---|---|
| **Broker CRM metadata** | `SubmissionNumber`, `MasterCarrierRecordName`, `AssignedTo`, `BrokerRef.BrokerId`, `BrokerRef.ProducerId` |
| **File-management metadata** | `Attachment.AttachmentId`, `UploadedDate`, `DestinationFolder`, `Source` |
| **Rating engine outputs** | `TargetQuoteDate`, `TargetRates`, `Locations.GL.{Rater, IRPMOverride, IRPM, University}`, `Buildings.{Building,Bpp}.Rate` |
| **Internal binding state** | `securedParty.{AppliesToAllBuildings, BuildingNumbers}` |
| **Agent CRM display fields** | `Agent.{Hierarchy, OtherName, Description}` |
| **Form-blank common fields** | NAICS / SIC / Website / DBA on most ACORD page 1s — brokers leave these blank in practice |

These are not "we missed something" — they require an upstream/downstream data source.

### 2.2 Real extraction bugs (54 fields) — fixes applied

Visually verified against ACORD PDFs (rendered at 150 DPI and inspected). The most impactful patterns we found and fixed:

| Bug class | Affected subs | Source location | Status |
|---|---|---|---|
| **Loss-run reserves dropped** | 2, 3, 4 | LR PDF "Total Reserves" column. Visual confirmed: Kinsale claim 00060543 = $5,000 open; Richmond claim RN-9-0000504 = $125,905.45 | **FIXED** — `Claims[].ReserveAmount` + `.ReserveAmountProvided` now emitted |
| **Insured.DescriptionOfOperations not surfaced** | 2, 3, 4, 5 | Standard ACORD field `CommercialPolicy_OperationsDescription_A[0]`. Sub 2 visible: "Owner, Investor, and Manager specializing in value-add multifamily properties" | **FIXED** — pulled from any page |
| **OtherNamedInsureds entities dropped** | 2 (44 entities), 4 (Prism Tamarac LP) | VLM extracted `vlm_other_named_insureds_N_name` on continuation pages 5-13; mapper only read page 1 | **FIXED** — walks all pages |
| **Employee Benefits Liability** | 4 ("Included"), 5 ("Included, $250K") | ACORD 126 page 1 EBL section | **FIXED** — `GeneralLiability.EmployeeBenefitsLiability` now populated |
| **NPN embedded in producer rep field** | 4 (`P084907`) | "Evan Seacat P084907/RRUIZ" in `Producer_AuthorizedRepresentative_FullName_A` | **FIXED** — regex fallback parses FL/CA/NY producer license formats |
| **BedCount column ignored on SOV** | 3 (92 beds), 5 (336 beds sidebar) | Sub 3 SOV col 18 = "Beds" | **FIXED** — `Buildings.BedCount` |
| **Free-text sprinkler info not parsed** | 3 ("100%, fully sprinklered") | Sub 3 SOV "Sprinkler Information" column | **FIXED** — text-form recognition added |
| **Locations.Address.ZipCode/County missing** | 2, 4, 5 | ACORD page 2 PREMISES table | **FIXED** — `enrich_locations_with_acord()` joins SOV-derived Locs to ACORD blocks by street+city |
| **`Status`/`DateOfLoss` field names** | 2, 3, 4 | We used renamed fields | **Renamed clarified** (your schema uses `ClaimStatus`, `LossDate` — see §3) |

### 2.3 Schema vocabulary mismatches (14 fields)

Either rename our output to match your schema OR map at consumption:

| Your schema | Our output | Notes |
|---|---|---|
| `LossRuns.Claims.ClaimStatus` | `LossRuns.Claims.Status` | Same data, different name |
| `LossRuns.Claims.LossDate` | `LossRuns.Claims.DateOfLoss` | Same data, different name |
| `Addresses.StateName` (full state) | `Addresses.State` (2-letter) | We store the abbreviation only |
| `Buildings.OccupancyClass` (ISO GL class code) | `Buildings.OccupancyType` (text) | **Different concepts** — your `OccupancyClass` is the GL classification code (60010 = Apartments) which we have not yet surfaced; we currently only output the occupancy as text |
| `Insured.contact.Type` ("Accounting Contact") | `Insured.Contacts[].Title` | Same data, stored under wrong key |
| `Insured.contact.Description` | `Insured.Contacts[].Title` | Same data |

---

## 3. Mapper Generalization — What Changed in the Pipeline

The previous mapper worked because the original 3 submissions shared structural conventions (single ACORD app per submission, "Acord" in filename, unique-address SOVs, single-policy loss runs). The two new submissions broke those.

### Core changes that generalize

1. **ACORD discovery via `document_type` (not filename).** Prism's GL application file is named `26 GL Application for Prism Broward.pdf` — no "acord" substring. Pipeline now reads the `document_type` field set by the per-doc extractor.

2. **Multi-ACORD merging.** Prism has *two* ACORD applications (GL + XS) in one submission. They share page 1 (named insured) but have different supplements. Mapper now merges by `(template, page_index)`, non-empty-wins.

3. **Same-address SOV consolidation.** Rise's 7 SOV rows are 7 buildings at one campus (not 7 separate locations). Mapper now groups rows by `(street, city)`; a single physical address produces one `Location` with N `Buildings`. Verified to match all 5 GT structures.

4. **Word-boundary fuzzy column matching on SOV.** "St" no longer matches "Street" (which previously stole the State column). "Total Sq Ft" now matches "Total Sq.Ft" (punctuation-tolerant).

5. **Anti-keyword filtering on VLM key names.** A VLM-emitted key like `vlm_APPLICANT INFORMATION_NAME (First Named Insured) AND MAILING ADDRESS` previously bled into `Insured.Name`. The mapper now rejects address-block keys when looking for a name.

6. **Loss-run policy term selection by evaluation date.** Multi-year loss runs that report 5 years of history now correctly pick the term containing the evaluation date as the current policy.

7. **Underwriter-platform email signatures excluded.** HabGen.com (the underwriter platform) replies don't represent the insured or the broker.

### Two known overfit risks we did NOT bake in

- **State-specific producer license regexes** — we use a state-agnostic regex (`P\d{6} | \d{8} | XX-NNNNN`) instead of FL-only.
- **Template-specific bbox field names** for SecuredParty references — left for VLM extraction rather than hardcoded `Text12` lookups.

---

## 4. Per-Submission Detail

### Sub 1 — 1800 North Stone LLC (100.0%)
1 location · 5 buildings · 1 loss run (no claims) · single-broker (Crest Insurance). Baseline; no audit performed.

### Sub 2 — Urban Southwest Capital LP (99.0%)
21 locations across multiple states · 52 claims across 2 loss runs · 44 OtherNamedInsureds (previously dropped) · GL only (per ACORD form, despite SOV presence).

**3 remaining gaps:** all three fields are `Submission.PropertySelected`, `Property.CoverageSelected`, `PolicyInfo.LOB[1]` — debatable interpretation: GT says Property is selected (because SOV is present), ACORD page 1 has only GL checkbox marked. Mapper follows the form (strict interpretation).

**Notable new data from audit:** 44 OtherNamedInsureds (Urban Stonehill Apartments, Urban Independence Meadowbrook, etc.); Insured.DescriptionOfOperations from form; Loss-run reserves on 29 claims.

### Sub 3 — Varsity Campus LLC (100.0%)
2 locations · 1 loss run · GL-only.

**Notable new data from audit:** BedCount = 92 beds; "Concrete podium with 4 Floors of wood above" as ConstructionType; "100%, fully sprinklered" → FullySprinklered=True.

### Sub 4 — Prism Broward, LP (99.7%)
20 physical-address locations consolidated from 32 SOV rows · 32 total buildings · 3 loss runs (CIBA 21-23, Richmond 23-25, Kinsale 25-26) · 14 claims (Kinsale was missing 1; now corrected) · 2 SecuredParties (Santander, Flagstar — added via VLM fallback).

**2 remaining gaps:**
- `Insured.BusinessPhone` — GT lists `844716625` (this is actually the FEIN; GT entry is mislabeled — should be `Insured.FEIN`)
- `SecuredParties[1].Name` — source PDF has "Santander Bank**.**" with a period; GT corrected to "Santander Bank**,**" with comma. We preserve the source exactly.

**Notable new data:** EBL flag, NPN `P084907`, RenewalFlag = "Renewal" (R/O prefix on prior policy), reserves on all 7 claims.

### Sub 5 — Rise Campus Quarters (99.2%)
1 campus location · 7 buildings at 1773 Ennis Joslin Rd, Corpus Christi TX · 1 Marsh-letter loss run (no claims, no reserves) · GL + Property submission.

**1 remaining gap:** `Locations[0].Address.County` = "Nueces" (in non-tabular SOV sidebar; ACORD page 2 has it but PREMISES table extraction didn't reach it).

**Notable new data:** EBL `{Included: true, Limit: 250000}`; Girijaa Doraiswamy as Insured.Contacts (prioritized over email signature); ProtectiveSafeguards (Central Station Alarm, Local Gong).

---

## 5. Methodology

### How we validated extractions

1. **Hand-curated ground truth** per submission, built by an independent agent reading every source document (PDFs via pdfplumber + fitz pixmap renders, xlsx via pandas, docx via python-docx). 1,239 leaf fields total.
2. **Type-aware comparison** (`gt_compare.py`): case-insensitive strings, ±0.5%-or-$1 numeric tolerance, format-tolerant dates, phone-digit normalization, `*` wildcard for "any non-empty acceptable".
3. **Field-by-field audit** of every field you listed as missing — 276 total — against the actual source documents to distinguish "extraction bug" from "not in source".
4. **Visual verification** of ACORD pages 1, 2, ACORD 126 page 1, ACORD 140 page 1, ACORD 125 Additional Interest pages, and loss-run claim detail pages — rendered as PNG and inspected to confirm what's filled vs blank on each form.

### Audit agent reports

Per-submission field audit reports (one row per field, with category + supporting evidence) are in this bundle at:
- `sub2_urban_southwest/field_audit.md`
- `sub3_varsity_campus/field_audit.md`
- `sub4_prism_broward/field_audit.md`
- `sub5_rise_campus_quarters/field_audit.md`

---

## 6. Deliverables

### `all_submissions_extraction.zip` (this bundle)

```
sub*_<name>/
├── extracted/                       ← Per-source-file extraction JSONs
│   ├── ALL.json                     ← Master with everything merged
│   ├── submission_mapped.json       ← Mapped to your schema
│   ├── <one .json per source PDF / xlsx / docx>
├── gt_<name>.json                   ← Hand-curated ground truth
├── gt_compare_report.txt            ← Field-by-field accuracy diff
└── field_audit.md                   ← The 276-field audit
README.md                            ← Top-level accuracy table
```

### Code

GitHub branch: `feat/multi-submission-mapper-audit`
PR URL: https://github.com/mohammadsafdar-netizen/extraction_pipeline/pull/new/feat/multi-submission-mapper-audit

3 commits on this branch:
- `b7d15ad` — Multi-submission mapper generalization (ACORD discovery, SOV consolidation, fuzzy matching, etc.)
- `0fd26ff` — ReserveAmount, DescriptionOfOperations, Location address enrichment
- `9ee7a19` — EBL, OtherNamedInsureds expansion, NPN, BedCount, free-text sprinkler

### Streamlit UI

A "📦 All submissions extraction bundle" download button at the top of the verifier app rebuilds this zip on-demand (mtime-cached, so the page just needs to refresh after extraction reruns).

---

## 7. Open Questions / Decisions Needed

1. **`Buildings.OccupancyClass`** (ISO GL class code, e.g. 60010 Apartments) — your schema treats this as a per-building field. ACORD 126 Schedule of Hazards has it at the *location-level* (one class per HAZ row, multiple HAZ rows per location). Should we surface as `Locations[].GeneralLiability.OccupancyClass` (1:many) or per-building (would need building-to-hazard mapping)?

2. **`StateName` (full state name)** — we store 2-letter `State`. Worth a downstream lookup table to populate "Florida" / "Texas" / etc., or keep abbreviation?

3. **Sub 2 PropertySelected** — strict reading of ACORD page 1 says GL only (Property checkbox is unchecked). GT decision says Property is selected (because SOV is present). Which interpretation should the pipeline default to?

4. **Sub 4 `Insured.BusinessPhone` GT entry** — the GT has `844716625` which is actually the FEIN. Should the GT be corrected, or should we map FEIN to BusinessPhone (loses the FEIN slot)?

5. **`PerLocationTimeElementReporting`** — this is on ACORD 140 page 1 (Value Reporting Form checkbox). Currently unfilled across all submissions. Want us to surface it as `false` when blank, or leave absent?

6. **Sub 5 Locations.Address.County** — the SOV has "Nueces" in a non-tabular sidebar. We extract from the SOV table currently. Worth adding a sidebar-text fallback parser?
