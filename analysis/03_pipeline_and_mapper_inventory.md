# Pipeline & Mapper Inventory Report

## Overview

This report inventories:
1. **Currently Extracted Fields**: All distinct field names populated in the merged ACORD JSON
2. **Currently Mapped Schema Paths**: Every schema path our mapper produces and its source fields
3. **Gap Analysis**: Unmapped extraction fields and missing schema paths

Data sources:
- Merged JSON: `merged_qwen3vl8b/Acord_App_1800_North_Stone_LLC_2026_merged.json` (253 KB, 25 pages)
- Mapper: `map_to_schema.py` (553 lines)
- Analysis Date: 2026-05-08

---

## Section 1: Currently Extracted Fields

### 1.1 Field Counts

- **BBOX /Btn (checkboxes) marked TRUE**: 19 fields
- **BBOX /Btn (checkboxes) marked FALSE**: 312 fields
- **BBOX /Tx (text fields)**: 134 fields
- **VLM gap-fill fields**: 125 fields
- **TOTAL DISTINCT FIELDS**: 583 fields

### 1.2 BBOX /Btn Fields Marked TRUE (checked)

AcroForm checkbox fields (/Btn type) where bbox detected a checked mark:

- `AdditionalInterest_CertificateRequiredIndicator_A`
- `AdditionalInterest_Interest_AdditionalInsuredIndicator_A`
- `AdditionalInterest_Interest_LossPayeeIndicator_A`
- `AthleticTeam_AgeGroup_TwelveAndUnderIndicator_B`
- `BuildingImprovement_RoofingIndicator_A`
- `BuildingImprovement_RoofingIndicator_B`
- `BusinessInformation_BusinessType_OtherIndicator_A[0]`
- `Check3[0]`
- `Check5[0]`
- `Check7[0]`
- `Check9[0]`
- `CommercialInlandMarineProperty_PropertySubClass_LargeEquipmentIndicator_A`
- `GeneralLiability_CoverageIndicator_A`
- `GeneralLiability_GeneralAggregate_LimitAppliesPerLocationIndicator_A`
- `GeneralLiability_OccurrenceIndicator_A`
- `NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A[0]`
- `SwimmingPool_ApprovedFenceIndicator_A`
- `SwimmingPool_DivingBoardIndicator_A`
- `SwimmingPool_LimitedAccessIndicator_A`

### 1.3 BBOX /Btn Fields Marked FALSE (unchecked)

Checkbox fields extracted but unchecked (first 30 of 312):

- `AdditionalInterest_CertificateRequiredIndicator_A`
- `AdditionalInterest_CertificateRequiredIndicator_A[0]`
- `AdditionalInterest_CertificateRequiredIndicator_B`
- `AdditionalInterest_Interest_AdditionalInsuredIndicator_A[0]`
- `AdditionalInterest_Interest_BreachOfWarrantyIndicator_A[0]`
- `AdditionalInterest_Interest_CoOwnerIndicator_A[0]`
- `AdditionalInterest_Interest_EmployeeAsLessorIndicator_A`
- `AdditionalInterest_Interest_EmployeeAsLessorIndicator_A[0]`
- `AdditionalInterest_Interest_LeasebackOwnerIndicator_A[0]`
- `AdditionalInterest_Interest_LendersLossPayableIndicator_A`
- `AdditionalInterest_Interest_LendersLossPayableIndicator_A[0]`
- `AdditionalInterest_Interest_LendersLossPayableIndicator_B`
- `AdditionalInterest_Interest_LienholderIndicator_A`
- `AdditionalInterest_Interest_LienholderIndicator_A[0]`
- `AdditionalInterest_Interest_LossPayeeIndicator_A`
- `AdditionalInterest_Interest_LossPayeeIndicator_A[0]`
- `AdditionalInterest_Interest_LossPayeeIndicator_B`
- `AdditionalInterest_Interest_MortgageeIndicator_A`
- `AdditionalInterest_Interest_MortgageeIndicator_A[0]`
- `AdditionalInterest_Interest_MortgageeIndicator_B`
- `AdditionalInterest_Interest_OtherIndicator_A`
- `AdditionalInterest_Interest_OtherIndicator_A[0]`
- `AdditionalInterest_Interest_OtherIndicator_B`
- `AdditionalInterest_Interest_OwnerIndicator_A[0]`
- `AdditionalInterest_Interest_RegistrantIndicator_A[0]`
- `AdditionalInterest_Interest_TrusteeIndicator_A[0]`
- `AdditionalInterest_PolicyRequiredIndicator_A[0]`
- `AdditionalInterest_SendBillIndicator_A[0]`
- `Alarm_Burglar_CentralStationIndicator_A`
- `Alarm_Burglar_CentralStationIndicator_B`
- ... and 282 more

### 1.4 BBOX /Tx Fields (text values) — First 30 of 134

- `AdditionalInterest_FullName_A`
- `AdditionalInterest_ItemDescription_A`
- `AdditionalInterest_Item_BuildingProducerIdentifier_A`
- `AdditionalInterest_Item_LocationProducerIdentifier_A`
- `AdditionalInterest_MailingAddress_LineOne_A`
- `AdditionalInterest_MailingAddress_LineTwo_A`
- `AthleticTeam_SponsorshipExtentDescription_A`
- `AthleticTeam_SponsorshipExtentDescription_B`
- `BuildingExposure_RearDescription_A`
- `BuildingExposure_RearDescription_B`
- `BuildingExposure_RearDistance_A`
- `BuildingExposure_RearDistance_B`
- `BuildingImprovement_RoofingYear_A`
- `BuildingImprovement_RoofingYear_B`
- `BuildingOccupancy_ApartmentCount_A`
- `BusinessInformation_BusinessType_OtherDescription_A[0]`
- `CommercialProperty_Premises_CauseOfLossCode_A`
- `CommercialProperty_Premises_CauseOfLossCode_B`
- `CommercialProperty_Premises_CauseOfLossCode_C`
- `CommercialProperty_Premises_DeductibleAmount_A`
- `CommercialProperty_Premises_DeductibleAmount_B`
- `CommercialProperty_Premises_DeductibleAmount_C`
- `CommercialProperty_Premises_DeductibleTypeCode_C`
- `CommercialProperty_Premises_LimitAmount_A`
- `CommercialProperty_Premises_LimitAmount_B`
- `CommercialProperty_Premises_RemarkText_A`
- `CommercialProperty_Premises_SubjectOfInsuranceCode_A`
- `CommercialProperty_Premises_SubjectOfInsuranceCode_B`
- `CommercialProperty_Premises_SubjectOfInsuranceCode_C`
- `CommercialProperty_Premises_ValuationCode_A`
- ... and 104 more

### 1.5 VLM Gap-Fill Fields — First 30 of 125

- `vlm_ADDITIONAL_COVERAGES_historical_landmark`
- `vlm_ADDITIONAL_COVERAGES_mine_subsidence`
- `vlm_ADDITIONAL_COVERAGES_open_sides_count`
- `vlm_ADDITIONAL_COVERAGES_sinkhole`
- `vlm_ADDITIONAL_COVERAGES_spoilage`
- `vlm_ADDITIONAL_INTEREST_address_line1`
- `vlm_ADDITIONAL_INTEREST_certificate_required`
- `vlm_ADDITIONAL_INTEREST_city`
- `vlm_ADDITIONAL_INTEREST_name`
- `vlm_ADDITIONAL_INTEREST_zip`
- `vlm_AGENCY CUSTOMER ID`
- `vlm_AGENCY_CUSTOMER_ID`
- `vlm_APPLICANT_INFORMATION_0_address_line1`
- `vlm_APPLICANT_INFORMATION_0_full_name`
- `vlm_BUILDING_IMPROVEMENTS_heating`
- `vlm_BUILDING_IMPROVEMENTS_other`
- `vlm_BUILDING_IMPROVEMENTS_plumbing`
- `vlm_BUILDING_IMPROVEMENTS_roofing`
- `vlm_BUILDING_IMPROVEMENTS_wiring`
- `vlm_BURGLAR_ALARM_central_station`
- `vlm_BURGLAR_ALARM_clock_hourly`
- `vlm_BURGLAR_ALARM_guards_watchmen_count`
- `vlm_BURGLAR_ALARM_local_gong`
- `vlm_BURGLAR_ALARM_with_keys`
- `vlm_CLAIMS_MADE_prior_coverage_excluded`
- `vlm_CLAIMS_MADE_tail_coverage_purchased`
- `vlm_CONSTRUCTION_distance_to_fire_station_mi`
- `vlm_CONSTRUCTION_distance_to_hydrant_ft`
- `vlm_COVERAGES_claims_made`
- `vlm_COVERAGES_commercial_general_liability`
- ... and 95 more


---

## Section 2: Currently Mapped Schema Paths

### 2.1 Mapper Functions

The mapper reads extracted fields and writes to `submission_mapped.json`. Key functions:

- **`map_acord()`**: Reads ACORD merged JSON (page 1 primarily)
  - **Source fields mapped**:
    - `NamedInsured_FullName_A[0]` OR `vlm_APPLICANT_INFORMATION_0_full_name` → Insured.Name
    - Entity-type checkboxes → Insured.EntityType
    - `NamedInsured_NAICSCode_A[0]` → Insured.NAICSCode
    - `NamedInsured_SICCode_A[0]` → Insured.SICCode
    - `NamedInsured_FEINOrSocSecNumberIdentifier_A[0]` → Insured.FEIN
    - `NamedInsured_BusinessPhoneNumber_A[0]` OR `vlm_APPLICANT_INFORMATION_0_business_phone` → Insured.BusinessPhone
    - `NamedInsured_WebsiteAddressUrl_A[0]` OR `vlm_APPLICANT_INFORMATION_0_website_address` → Insured.Website
    - `vlm_APPLICANT_INFORMATION_0_address_line1` → Insured.Addresses[0].Street
    - `Producer_FullName_A[0]` OR `vlm_HEADER_agency_name` → Agent.Name
    - `Producer_NationalProducerNumber_A[0]` → Agent.NationalProducerNumber
    - `Policy_EffectiveDate_A[0]` → PolicyInfo.EffectiveDate (parsed)
    - `Policy_ExpirationDate_A[0]` → PolicyInfo.ExpirationDate (parsed)
    - `Policy_PolicyNumberIdentifier_A[0]` → PolicyInfo.PriorPolicyNumber
    - LOB checkboxes → PolicyInfo.LOB

- **`map_sov()`**: Reads SOV Excel extraction
  - **Source columns**: Loc.#, Building #, Year Built, Construction Type, Type of Roof, # Sq. Ft. Bldg, # of stories, Occupancy, etc.

- **`map_loss_run()`**: Reads Loss Run extraction
  - **Source fields**: company, carrier, policy_number, claim_number, status, date_of_loss, amount_paid

- **`map_email()`**: Reads email.docx extraction
  - **Source**: Subject line, table timestamp

- **`list_attachments()`**: Scans input_docs/Input/ directory (no field mapping)

### 2.2 Top-Level Schema Keys Produced

- Submission (7 fields)
- PolicyInfo (5 fields)
- Insured (9 fields + nested Addresses)
- Agent (4 fields + nested Addresses, Contacts)
- GeneralLiability (1 field)
- Property (1 field)
- Locations[] (4 fields + nested Buildings[])
- LossRuns[] (5 fields + nested Claims[])
- Attachments[] (4 fields)

---

## Section 3: Gap Analysis

### 3.1 Extracted Fields NOT Referenced in Mapper

**Total extracted fields: 583**
**Fields referenced in mapper: 18**
**Fields extracted but UNMAPPED: 565 (96%)**

#### Unmapped by Category:

- **BBOX /Btn TRUE (checked)**: All 19 are unmapped
- **BBOX /Btn FALSE (unchecked)**: All 312 are unmapped
- **BBOX /Tx (text)**: 120 of 134 unmapped
- **VLM fields**: 121 of 125 unmapped

### 3.2 Biggest Gap: Checkbox State Enumeration

The mapper **reads only ONE checkbox**: `_entity_type_from_acord()` which converts 5 entity-type indicators on page 1 into a single enum.

All other checkbox fields are extracted but never written to the schema.

**Examples of unmapped checkboxes**:
- Building improvement indicators (roofing, wiring, plumbing, heating)
- Additional insured / interested party indicators
- Athletic field / swimming pool indicators
- Coverage type selections (GL, Property, CIM, Crime, etc.)
- Building exposure indicators (front, rear, side distance)

### 3.3 Major Missing Schema Paths

The mapper does **not** populate:
- Per-coverage limit/deductible detail (only GLSelected/PropertySelected boolean)
- Additional insured/interested party data (no name, address, or role capture)
- Building improvement types (roofing, HVAC, wiring, plumbing details)
- Building exposure/hazard data (frontage, rear distance, side exposure)
- Premium allocation by coverage
- Producer commission or fee structure
- Supplemental questionnaire answers
- Multi-carrier loss history (only Farmers LR, not ACORD 131)

---

## Summary

| Metric | Value |
|--------|-------|
| Total distinct extracted fields | 583 |
| Fields mapped to schema | 18 |
| Fields extracted but unmapped | 565 |
| Unmapped percentage | 96% |
| Top-level schema keys produced | 9 |
| Nested schema objects | 4 |

### Key Findings

1. **583 fields extracted**, but **only 18 referenced** in mapper (3% utilization)
2. **565 fields go unused** (97% extraction waste)
3. **All checkbox states extracted**, but **only entity-type checkboxes mapped**
4. **All ACORD form pages parsed**, but **only page 1 mapped** (agent/insured/policy)
5. **Schema is minimal**: 9 top-level keys supporting ~35 leaf fields total
6. **Design is intentional**: Built for "minimum viable submission", not comprehensive insurance app

### Recommendations for Future Work

If expanding mapper coverage:
1. **Priority 1**: Map Additional Insured data (page 16-19, ACORD 126)
2. **Priority 2**: Map Building Improvements/Exposures (page 6-14, ACORD 140)
3. **Priority 3**: Map Coverage selections with limits/deductibles (requires schema expansion)
4. **Priority 4**: Enumerate all checkbox states for audit trail / discrepancy detection
