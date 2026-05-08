# System Analysis — Schema Coverage & Mapping Roadmap

**Question**: For the system (not just one submission), how many of the schema fields can we map from the documents we extract? What are we extracting but not mapping? What's missing in either direction? What's the best next move?

This synthesizes three parallel inventories:
- `01_schema_inventory.md` — 167 leaf fields in your submission schema
- `02_acord_acroform_inventory.md` (+`.json`) — 3,120 AcroForm fields across 7 ACORD templates
- `03_pipeline_and_mapper_inventory.md` — what our pipeline actually extracts and maps

---

## Headline numbers

| Quantity | Count |
|---|---|
| **Schema leaf fields total** | 167 |
| **Schema FROM_DOC fields** (extractable from incoming docs) | 135 |
| **Schema INTERNAL fields** (carrier-assigned post-clearance, never extractable) | 22 |
| **Schema DERIVED fields** (computed from other schema fields) | 2 |
| | |
| **AcroForm fields across 7 ACORD templates** | **3,120** (661 /Btn + 2,459 /Tx) |
| **Distinct fields the pipeline extracted from a single ACORD app run** | 583 |
| | |
| **Schema paths the mapper writes today** | ~18 |
| **Schema paths systemically achievable with current extraction** | **~110 of 135** |
| **Best-next-move achievable in ~2 hours of mapper work** | **+~50 fields** (raises us from 18 → ~68 mapped) |

---

## Where the 135 FROM_DOC schema fields come from

| Source document | Schema fields it supplies | Currently mapped? |
|---|---|---|
| **ACORD 125 (App)** p1 — agency/insured/policy header | 35–40 (Insured.*, Agent.*, PolicyInfo.Eff/ExpDate) | mostly mapped (~12 fields) |
| **ACORD 125** p2 — premises + contact info + nature_of_business | ~15 (Insured.Contacts, location info) | NOT mapped |
| **ACORD 125** p3 — general info questions, prior carrier | ~10 (RenewalFlag context, prior policy #) | partially mapped |
| **ACORD 125** p4 — additional interests / mortgagees | ~12 (SecuredParties.*) | NOT mapped |
| **ACORD 140 (Property)** — building details, exposures | ~12 (Buildings details — overlaps with SOV) | NOT mapped (we use SOV instead) |
| **ACORD 126 (CGL)** p1 — coverage selection, limits, claims-made/occurrence | ~5 (GL.CoverageSelected, EBL, etc.) | partially mapped |
| **ACORD 131 (Umbrella)** — underlying insurance | ~8 (TargetRates, LOB context) | NOT mapped |
| **SOV.xls** | ~25 (Locations[].Address + all Buildings[]) | mostly mapped (~22 fields) |
| **Farmers LR / loss-run PDFs** | ~12 (LossRuns.*, Claims.*) | mostly mapped (~7 fields) |
| **Broker email (.docx)** | ~5 (DateReceived, Notes, TargetPremium) | mostly mapped (~3 fields) |
| **Cover note (.docx narrative)** | ~3 (DescriptionOfOperations, deductibles, conditions) | partially mapped (~1 field) |
| **Internal/derivable** (e.g. GLSelected) | 22 | hardcoded/derived |
| **Total achievable** | **~110/135** | — |

Note: some schema fields can come from multiple sources (e.g. `Insured.Addresses` is on ACORD 125 p1, SOV, and email signatures); we should pick the highest-quality source per field.

---

## What we're extracting but NOT mapping (the 96% waste)

The pipeline extracts 583 distinct fields from a single ACORD app, but the mapper consumes only 18. Breakdown of what's wasted:

| Category | Count | Examples | Why these matter |
|---|---|---|---|
| **/Btn checkboxes that are TRUE** | 19 of 19 unmapped | `GeneralLiability_OccurrenceIndicator_A`, `AdditionalInterest_Interest_LossPayeeIndicator_A`, `BuildingImprovement_RoofingIndicator_A`, `SwimmingPool_ApprovedFenceIndicator_A` | Tell us coverage triggers, additional-insured roles, building hazards |
| **/Btn checkboxes that are FALSE** | 312 of 312 unmapped | every other indicator | Audit trail; "we know these AREN'T checked" is positive information |
| **/Tx text fields with values** | 120 of 134 unmapped | `AdditionalInterest_FullName_A`, `AdditionalInterest_MailingAddress_LineOne_A`, `Alarm_Burglar_GuardCount_A`, `BuildingExposure_RearDistance_A`, `CommercialProperty_Premises_LimitAmount_A` | Mortgagee data, alarm details, building exposures, per-coverage limits |
| **VLM gap-fill values** | 121 of 125 unmapped | `vlm_BUILDING_IMPROVEMENTS_*`, `vlm_HEATING_*`, `vlm_BURGLAR_ALARM_*`, `vlm_COVERAGES_*`, `vlm_LIMITS_*` | Free-form narrative answers + nested objects the VLM could spot |

**The biggest concrete waste:**
1. **Mortgagee/loss-payee data** — every `AdditionalInterest_*` field on ACORD 125 p4 maps cleanly to `SecuredParties[]` in your schema. We extract names, addresses, "Mortgagee/Loss Payee/Lender" indicators — but the mapper has zero `SecuredParties` logic.
2. **Building exposures** — `BuildingExposure_RearDescription_*`, `BuildingExposure_FrontDistance_*` (4 sides per building) — your schema has no slot for these.
3. **All 19 true checkboxes other than entity_type** — including the GL Occurrence Indicator (which we worked hard to fix earlier!), per-location aggregate, OCP coverage, etc.

---

## What we extract but the schema HAS NO PLACE for (3,120 AcroForm fields → 135 schema slots)

The schema is intentionally narrow. Of the 3,120 fields in the templates, only roughly **30** have a direct schema home. The rest are either:

| Bucket | Count | What we do with it |
|---|---|---|
| **No schema slot — never queried** | ~2,000 | Ignored. (Building improvement subdetails, athletic team age groups, sponsorship descriptions, swimming pool details, alarm-system subtypes…) |
| **Could go in a `notes` or `additional_data` field** | ~600 | Currently lost; could roll up into `Insured.DescriptionOfOperations` or a new `RawAcroFormFields` audit dump |
| **Has schema home but not yet mapped** | ~50 | The high-value gap (see "Best next move") |
| **Has schema home AND mapped** | ~30 | Already wired |

**Examples of fields with no schema slot (not your fault — schema doesn't ask for them):**
- All `BuildingImprovement_*`, `Heating_*`, `Roofing_*`, `Wiring_*` — dozens of fields about construction details (`Buildings[].Description` could capture this as text but loses structure)
- All `Alarm_Burglar_*`, `Alarm_Fire_*` — could go in `Buildings[].ProtectiveSafeguards[]`, but we don't currently map them
- All `BuildingExposure_*` (4 sides × multiple buildings)
- All `AthleticTeam_*`, `SwimmingPool_*` (hazard-specific schedule data)
- All `CommercialProperty_Premises_*Code_*`, `CommercialProperty_Premises_*LimitAmount_*` — per-premise property coverage detail

If you want a richer schema, this is where to extend it.

---

## Reverse: schema fields where the data is in docs but we DON'T extract

| Schema field | Should be in… | Why we don't extract it now |
|---|---|---|
| `Insured.DBANames[]` | ACORD 125 p1 (no AcroForm field) | Not in standard ACORD; would need email/note parsing |
| `Insured.NAICSCode` | ACORD 125 p1 `NamedInsured_NAICSCode_A` | We DO extract; field was empty in this PDF |
| `Insured.Contacts[]` | ACORD 125 p2 contacts table | We extract bbox text; not yet wired into mapper |
| `OtherNamedInsureds[]` | ACORD 125 p1 secondary applicant block | We extract bbox text; not yet wired |
| `Agent.NationalProducerNumber` | ACORD 125 p1 footer (signature page) | Field exists in template but typically blank on the form |
| `Agent.FEIN` | Not in standard ACORD | Would need email signature parsing |
| `PolicyInfo.PriorPolicyNumber` | ACORD 125 p3 prior carrier section | We extract; mapper reads wrong field |
| `Property.AggregateBusinessIncomeLimit` | sum of SOV `Loss of Rents` column | Trivial computation, not yet done |
| `Property.PerLocationTimeElementReporting` | not in standard ACORD | Underwriter-side election |
| `SecuredParties[].Name` + Address | ACORD 125 p4 AdditionalInterest section | We extract bbox text; not yet wired |
| `Locations[].LocationName` | not in SOV by default | Would need to derive (e.g. "1800 N Stone — Building 1") |
| `Locations[].GeneralLiability[]` | ACORD 125 p3 (premium operations) + ACORD 126 hazard schedule | We extract; not yet wired |
| `LossRuns[].PolicyEffectiveDate/ExpirationDate` | Loss run header | Some loss runs include policy term; we don't currently parse it |
| `LossRuns[].Claims[].ClaimStatus`, `LossDate`, etc. | Loss run claim rows (Richmond has these clean) | We extract; mapper has it for Richmond format only |
| `Buildings[].ProtectiveSafeguards[]` | Could derive from `Alarm_*Indicator_*` checkboxes | Not yet wired |

---

## Best next move

### Tier 1 — High-value, ready-to-map (no new extraction needed)

These are schema fields where **we already extract the data**; we just don't write it to `submission_mapped.json`. Add to `map_to_schema.py`:

| Schema target | Source we already have | Effort |
|---|---|---|
| `SecuredParties[]` | ACORD 125 p4 `AdditionalInterest_*` fields (FullName, Address, Mortgagee/LossPayee/Lender indicator) | ~30 lines |
| `Insured.Contacts[]` | ACORD 125 p2 `vlm_CONTACT_INFORMATION_*` | ~15 lines |
| `OtherNamedInsureds[]` | ACORD 125 p1 secondary applicant block | ~10 lines |
| `Property.AggregateBusinessIncomeLimit` | sum of SOV `Loss of Rents` column | 1 line |
| `Buildings[].ProtectiveSafeguards[]` | bbox `Alarm_*Indicator_*` true → list | ~10 lines |
| `Buildings[].Description` | derived from OccupancyType + YearBuilt + Stories | 1 line |
| `LossRuns[].Claims[]` for non-Richmond formats | broaden VLM-side fall-through | ~20 lines |
| `Locations[].GeneralLiability[]` (per-location exposure) | ACORD 125 p2 premises + ACORD 126 hazard | ~25 lines |
| `Submission.QuoteNeededBy` | parse "Need asap" / specific date in email | ~10 lines |

**Net effect**: ~120 lines of mapper work. Lifts schema-path mapping from 18 → ~68 (~50% of FROM_DOC fields).

### Tier 2 — Requires extending what we extract

| Schema target | Where to get it | Effort |
|---|---|---|
| `Insured.DBANames[]`, `Agent.FEIN`, `Agent.OtherName` | parse email signature blocks (python-docx already gets paragraphs) | ~1 hour |
| Multi-loss-run pipeline | currently only parses Farmers + Richmond formats well; CIBA/Rise/Kinsale need more table heuristics | half-day |
| Per-coverage limit/deductible breakdown | extend ACORD 126 / ACORD 140 mapper paths | half-day |
| Building rate fields (`Building.Rate`, `Bpp.Rate`) | not in incoming docs — would need to be `INTERNAL` | n/a |

### Tier 3 — Schema-side decisions

A lot of what we extract has nowhere to go in the current schema. Two options:

**Option A**: Add an `AcroFormDump` field to each Location/Building/Insured that captures the raw fields we didn't map. This loses no information but doesn't help downstream consumers who expect the structured schema.

**Option B**: Extend the schema to add:
- `Buildings[].HazardSchedule[]` (swimming pool, athletic teams, etc.)
- `Buildings[].Improvements[]` (roofing year, wiring year, plumbing year, etc.)
- `Buildings[].Exposures[]` (front/rear/left/right description + distance)
- `Buildings[].ProtectiveSystems` (alarm types, distance to fire station/hydrant)

If you want a richer model, my recommendation is to **add `Buildings[].Improvements`, `Buildings[].Exposures`, and `Buildings[].ProtectiveSystems` to the schema** — that's where ~80% of the unmapped /Btn data has natural homes.

---

## Summary table — coverage today and after Tier 1

| Metric | Today | After Tier 1 | After Tier 1+2 | Theoretical max |
|---|---|---|---|---|
| Schema FROM_DOC fields populated | 18 of 135 (13%) | ~68 of 135 (50%) | ~95 of 135 (70%) | ~110 of 135 (81%) |
| Reachable coverage on a typical submission | 92.6% on data-bearing fields | 95%+ | 97%+ | 100% |
| Distinct AcroForm fields used | ~30 of 3,120 (1%) | ~120 of 3,120 (4%) | ~250 of 3,120 (8%) | ~400 of 3,120 (13%) |

The "schema field" coverage and "AcroForm field" coverage are different metrics — the schema is intentionally selective, so the bottleneck is the **mapper** (~120 lines to write), not the **extractor** (already pulls 583 fields per ACORD app).

---

## Recommended order of operations

1. **Now (1-2 hours)**: Implement Tier 1 mapper extensions. Start with `SecuredParties[]` and `Insured.Contacts[]` — biggest user-visible jumps.
2. **Then (half-day)**: Tier 2 — multi-format loss-run table parsing + email-signature parsing for FEIN/OtherName.
3. **Then (decision)**: Discuss schema extension (Tier 3) for the ~80% of AcroForm data that currently has no schema home.
4. **In parallel**: build a manual GT for 1-2 PDFs so we can quote real field-level accuracy numbers (currently we only have spot-check accuracy).
