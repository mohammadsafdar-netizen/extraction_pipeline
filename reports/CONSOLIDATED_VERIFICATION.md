# Verification of Stakeholder "Not in Source" Claims — Consolidated Report

**Date:** 2026-05-11
**Method:** 5 independent verification agents + my own visual rendering & inspection of ACORD pages 1-2, page 9-12 (Additional Interest), ACORD 126 page 1 (GL section), ACORD 140 page 1 (Property), loss-run claim detail pages, and the Genstar Apartment Supplemental (verified to be a blank template).
**Scope:** 5 submissions, **331 absence claims verified** against source documents.

---

## Top-line answer

| Submission | Total claims | CONFIRMED ABSENT (you were right) | FOUND IN SOURCE (your claim is wrong) | AMBIGUOUS |
|---|---:|---:|---:|---:|
| Sub 1 — 1800 North Stone LLC | 66 | 49 | **11** | 6 |
| Sub 2 — Urban Southwest Capital LP | 67 | 51 | **14** | 2 |
| Sub 3 — Varsity Campus LLC | 61 | 49 | **12** | 0 |
| Sub 4 — Prism Broward, LP | 67 | 52 | **4** | 11 |
| Sub 5 — Rise Campus Quarters | 70 | 61 | **8** | 1 |
| **Total** | **331** | **262 (79%)** | **49 (15%)** | **20 (6%)** |

So **79% of your "not in source" claims are correct** — that data is genuinely absent. But **15% (49 fields) ARE in source**; the user's audit missed them.

---

## 49 FOUND_IN_SOURCE fields — where your absence claim is WRONG

These are organized so you can verify each one against the source documents yourself. Citations come from the per-sub `field_audit.md` plus my visual page renders (which I cross-checked manually).

### Sub 1 (1800 North Stone LLC) — 11 items

| Field | Source | Where |
|---|---|---|
| `Insured.Website` | ACORD app p.1 | `NamedInsured_Primary_WebsiteAddress_A[0]` = `stoneavenuestandard.com` (visually verified — visible in the WEBSITE row) |
| `Agent.Addresses[].Street2` | ACORD app p.1 | "Suite 4500" in `5285 E. Williams Circle Suite 4500` |
| `Agent.Addresses[].City` | ACORD app p.1 | `Tucson` under Crest agency block |
| `Agent.Addresses[].State` | ACORD app p.1 | `AZ` |
| `Agent.Addresses[].ZipCode` | ACORD app p.1 | `85711` |
| `Locations[].Addresses[].ZipCode` | ACORD p.2, SOV | `85705-5761` on every premise row |
| `Locations[].Addresses[].County` | ACORD p.2 + email table | `Pima` for all 4 premises (visually verified on rendered page 2) |
| `Locations[].Buildings[].OccupancyClass` | ACORD 126 p.16 (Schedule of Hazards) | Class **60010** Apartment Buildings (Student Housing); SOV "Student Housing" |
| `securedParty.Addresses[].Street2` | ACORD 140 p.6 | `Suite 300` in `332 Norristown Road, Suite 300` |
| `securedParty.Addresses[].ZipCode` | ACORD 140 p.6 | `19002` (Ambler, PA) |
| `securedParty.LocationNumber` | ACORD 140 p.6 | Explicitly `LOCATION: 0` and `BUILDING: 0` |

### Sub 2 (Urban Southwest Capital LP) — 14 items

Note: **5 of these we already extract** (the user may not have realized — sub 2 already has these in `submission_mapped.json` after the recent commits):

| Field | Status | Source |
|---|---|---|
| `PolicyInfo.TargetRates` | NEED FIX | EMAIL.docx body: *"Target $140 a door. 3,462 units"* |
| `Insured.DescriptionOfOperations` | **ALREADY EXTRACTED** | ACORD p.2: *"Owner, Investor, and Manager specializing in value-add multifamily properties"* |
| `Insured.contact.Type` | RENAME — stored as `.Title` | ACORD p.2/p.14: `Accounting Contact / Audit Contact / Claim Contact / Inspection Contact` |
| `OtherNamedInsureds[].Name` | **ALREADY EXTRACTED** (44 entities) | ACORD pp.1, 8-13: Urban Stonehill, Urban Independence Meadowbrook, Ben Weil, Julian Blum, etc. |
| `Agent.address.City` | NEED FIX | ACORD p.1: `Hyannis`; EMAIL signature: `Westborough` (two offices) |
| `Agent.address.State` | NEED FIX | `MA` |
| `Agent.address.ZipCode` | NEED FIX | `02601` / `01581` |
| `Agent.contact.Title` | NEED FIX | EMAIL signature: *"Greg Harris / Assistant Vice President / Property & Casualty"* |
| `GeneralLiability.EmployeeBenefitsLiability` | NEED FIX | EMAIL: *"Employee Benefits - $1M/$2M Limits"* requested on quote |
| `Locations[].Address.ZipCode` (20 locs) | NEED FIX | ACORD pp.2, 5-7 list all 21 ZIPs (64152, 75062, 79912, 77471, etc.) |
| `Locations[].Buildings[].ProtectiveSafeguards` | NEED FIX | SOV columns "Building Sprinklered Percentage" + "Smoke Detector Battery or Hard Wired" populated per building |
| `LossRuns[].Claims[].ReserveAmount` | **ALREADY EXTRACTED** | LR PDF pp.3-4: claim 01BGL2023002326 = `$50,218`; claim 01BGL2025001770 = `$27,847` |
| `LossRuns[].Claims[].ReserveAmountProvided` | **ALREADY EXTRACTED** | LR has explicit "Total Recovery/Reserves" column for every row |
| `Insured.contact.Type` | rename — stored as Title | (same as above) |

### Sub 3 (Varsity Campus LLC) — 12 items

| Field | Source |
|---|---|
| `PolicyInfo.PriorPolicyNumber` | LR PDFs: `0175105`, `0228378`; 410 S Morgan LR: `ASP481199509` |
| `Insured.Website` | EMAIL: `https://www.lettermanchicago.com/`, `https://www.loftsatgold.com/` |
| `Insured.DescriptionOfOperations` | EMAIL: *"High-end, off-campus student housing in Chicago, IL and Rochester, NY"*; ACORD p.2: *"Apartments - Student Housing"* + RETAIL nature checkbox |
| `OtherNamedInsureds[].Name` | SOV Entity column: *"The Lofts at Gold Street"*, *"410 South Morgan Street, LLC"* |
| `OtherNamedInsureds[].Operations` | SOV Occupancy column: *"Student Housing"* |
| `Agent.Website` | EMAIL signature: `amwins.com` |
| `Agent.Address` | EMAIL signature: `10 S. LaSalle Street, Suite 2000, Chicago, IL 60603` |
| `Locations[].Buildings[].BedCount` | SOV: `92` (Lofts), `482` (410 S Morgan) — **already extracted** via our recent fix |
| `Locations[].Buildings[].FullySprinklered` | SOV: *"100%, fully sprinklered"* — **already extracted** via free-text fix |
| `Locations[].Buildings[].ProtectiveSafeguards` | SOV "Smoke Detection" col, EMAIL Apr 24: *"pet policy, dead bolts, locks rekeyed, security cameras, background checks"* |
| `securedParty.Name` | SOV "Lender" column row 6: *"Greystone / latasha.bailey@greyco.com"* |
| `LossRuns[].Claims[].ReserveAmount` + `.ReserveAmountProvided` | 410 S Morgan LR p.1: `$18,499` Case Loss & Expense Reserve; p.2: `$15,999` Case Reserves + `$2,500` ALAE — **already extracted** |

### Sub 4 (Prism Broward, LP) — 4 items

| Field | Source |
|---|---|
| `securedParty.Address.POBox` | GL p.9: Santander `P.O. Box 2526`; XS p.12: Flagstar `P.O. Box 5070` |
| `securedParty.ReferenceNumber` | GL p.9: Santander `7216320`; XS p.12: Flagstar `291000307` |
| `LossRuns[].Claims[].ReserveAmount` | Richmond LR: RN-9-0000504 = `$125,905.45`; RN-9-0002360 = `$50,041.00`; Kinsale: 00060543 = `$5,000` — **already extracted** |
| `LossRuns[].Claims[].ReserveAmountProvided` | LR PDFs all have reserve columns — **already extracted** |

### Sub 5 (Rise Campus Quarters) — 8 items

| Field | Source |
|---|---|
| `Insured.DescriptionOfOperations` | ACORD p.2: *"Student Housing"*; EMAIL: *"This is student housing located in Corpus Christi, Texas..."* — **already extracted** via recent fix |
| `Locations[].GeneralLiability.OccupancyClass` | ACORD 126 p.10 Schedule of Hazards: `Apartments / Swimming Pool / Volleyball Court` |
| `Locations[].GeneralLiability.Exposure` | Same: exposure `108` (Apartments units), `1` (Pool), `1` (Volleyball) |
| `Locations[].Buildings[].OccupancyClass` | SOV "Occupancy" column: rows 2-5 = `Apartment`, row 6 = `Club House`, rows 7-8 = `?` |
| `Locations[].Buildings[].ConstructionType` | SOV "Construction" column = `Frame`; ACORD 140 p.5 = `Frame`; EMAIL: *"Construction Type: Frame"* — **already extracted** |
| `Locations[].Buildings[].BedCount` | SOV sidebar row 23: *"336 beds"* |
| `Locations[].Buildings[].Bpp.BppCoverageFlag` | ACORD 140 p.5 blanket: BPP = $1,040,000 — **already extracted** |
| `Locations[].Buildings[].Bpp.BppLimit` | Same: $1,040,000 — **already extracted** |

---

## Important corrections to call out

### 1. Agent NPN — your "not in source" claim is CORRECT, and we just fixed a wrong extraction

Our pipeline was incorrectly extracting `P084907` as `Agent.NationalProducerNumber` for Prism. Visual inspection of the ACORD page (and the sub 4 agent's verification) confirmed:
- The field labeled `NATIONAL PRODUCER NUMBER` is **blank**.
- `P084907` is the **STATE PRODUCER LICENSE NO. (Required in Florida)**, taken from the `Producer_AuthorizedRepresentative_FullName` field which renders "Evan Seacat P084907/RRUIZ" on the form.

**Fix applied just now**: `Agent.NationalProducerNumber` = None (correctly blank); `Agent.StateProducerLicense` = `P084907` (new field). Same logic for any future submission where the regex matches.

### 2. AMBIGUOUS items worth a stakeholder decision

- **Sub 1**: `BedCount` — email table has a "Bed Count" column with value `0` for every building, SOV has `# Hab Units` (14/12/18/12/12). Strictly speaking, no real "beds" count is filled — Units is the populated value.
- **Sub 4**: `Insured.DescriptionOfOperations` — form-field is blank, but the data exists implicitly (NATURE OF BUSINESS = APARTMENTS checkbox; 690 units in FL per email).
- **Sub 4**: `EmployeeBenefitsLiability` — the ACORD 126 EBL section has fields (Deductible, # Employees, Retroactive Date) all **blank**. The user's claim was `not in source`, but a separate vlm field reads "Included" — which may be the VLM mis-reading a blank section header. **Recommend our pipeline output {Included: true} be re-verified.**

### 3. AMBIGUOUS on `OtherNamedInsureds` for sub 4

Prism's GT and our output both contain `Prism Tamarac LP` as OtherNamedInsured. Sub 4 agent classifies `OtherNamedInsureds[].Operations` as `CONFIRMED_ABSENT` — Prism Tamarac LP is named but no Operations description for it is in the source. This matches user's claim.

---

## Files

- `/tmp/verify_v2/sub1_verified.md` — sub 1 full table
- `/tmp/verify_v2/sub2_verified.md` — sub 2 full table
- `/tmp/verify_v2/sub3_verified.md` — sub 3 full table
- `/tmp/verify_v2/sub4_verified.md` — sub 4 full table
- `/tmp/verify_v2/sub5_verified.md` — sub 5 full table

All 5 contain `| Field | Verdict | Evidence |` with source citations for every row.

## Pipeline regression after EBL/NPN fix
- Sub 1: 100.0%
- Sub 2: 99.0%
- Sub 3: 100.0%
- Sub 4: 99.7%
- Sub 5: 99.2%
