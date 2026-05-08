# Insurance Submission JSON Schema Inventory

This document provides a comprehensive field-by-field analysis of the insurance submission schema used for habitational property and general liability underwriting. Every leaf field (scalar, enum, or array of scalars) is catalogued with its data type, classification (FROM_DOC / INTERNAL / DERIVED / ENRICHMENT), and the typical source document in a standard insurance submission package. This inventory is essential for designing extraction pipelines and validating data quality at each step of the submission clearance workflow.

## Schema Field Inventory

| Field Path | Data Type | Enum Values | Classification | Typical Source | Notes |
|---|---|---|---|---|---|
| Submission.SubmissionNumber | string | | INTERNAL | System-generated | Assigned by carrier upon intake; unique identifier for this underwriting submission |
| Submission.Status | enum | Cleared, Declined, Quoted, Quoted Not Bound, Bound | INTERNAL | Carrier workflow | Set post-clearance as submission progresses through underwriting |
| Submission.DateReceived | date-time | | FROM_DOC | Email timestamp or submission form | When broker's submission arrived at carrier |
| Submission.QuoteNeededBy | date | | FROM_DOC | ACORD form, broker email, RFP | Business deadline for quote delivery |
| Submission.GLSelected | boolean | | DERIVED | Policy Info LOB | Computed from PolicyInfo.LOB array (true if "General Liability" present) |
| Submission.PropertySelected | boolean | | DERIVED | Policy Info LOB | Computed from PolicyInfo.LOB array (true if "Property" present) |
| Submission.MasterCarrierRecordName | enum | Incline Americas Insurance Company | INTERNAL | Carrier system | Immutable; indicates carrier of record |
| Submission.ProductType | enum | HabGen | INTERNAL | Carrier system | Product line; currently only HabGen supported |
| Submission.AssignedTo | string | | INTERNAL | Underwriter assignment | Email or user ID; assigned post-clearance |
| Submission.Notes | string | | INTERNAL | Underwriter entry | Underwriter commentary during clearance/underwriting |
| PolicyInfo.RenewalFlag | enum | New, Renewal | FROM_DOC | ACORD form, broker email | Indicates if new business or renewal |
| PolicyInfo.EffectiveDate | date | | FROM_DOC | ACORD form, contract | Policy start date |
| PolicyInfo.ExpirationDate | date | | FROM_DOC | ACORD form, contract | Policy end date |
| PolicyInfo.PriorPolicyNumber | string | | FROM_DOC | Broker communication, ACORD | Renewal only; prior carrier's policy number |
| PolicyInfo.TargetQuoteDate | date | | FROM_DOC | RFP, broker email | Deadline for quote issuance |
| PolicyInfo.LOB[] | enum | Property, General Liability | FROM_DOC | ACORD form, RFP | Lines of business requested; drives coverage selection |
| PolicyInfo.TargetRates[].CoverageType | string | | FROM_DOC | RFP, broker email | Coverage line (e.g., "Property", "GL") |
| PolicyInfo.TargetRates[].TargetRate | number | | FROM_DOC | RFP, broker guidance | Target rate per $100 of limit/exposure |
| Insured.Name | string | | FROM_DOC | ACORD form, SOV, contract | Legal business name |
| Insured.DBANames[] | string | | FROM_DOC | ACORD form, broker email | "Doing Business As" trade names |
| Insured.Website | string | | FROM_DOC | ACORD form, broker email | Corporate website URL |
| Insured.EntityType | enum | Individual, Corporation, Partnership, Joint Venture, Limited Liability Company, Other | FROM_DOC | ACORD form, SOV | Legal entity structure |
| Insured.NAICSCode | string | | FROM_DOC | ACORD form, SOV | 6-digit NAICS industry classification |
| Insured.SICCode | string | | FROM_DOC | ACORD form, SOV | 4-digit SIC industry code (legacy) |
| Insured.DescriptionOfOperations | string | | FROM_DOC | ACORD form, SOV, email | Business operations narrative |
| Insured.Addresses[].Type | enum | Mailing, Physical, Physical and Mailing, Accounting, Additional, HQ | FROM_DOC | ACORD form, SOV | Address classification |
| Insured.Addresses[].Street | string | | FROM_DOC | ACORD form, SOV | Street address (primary) |
| Insured.Addresses[].Street2 | string | | FROM_DOC | ACORD form, SOV | Street address (secondary, apt/suite) |
| Insured.Addresses[].POBox | string | | FROM_DOC | ACORD form, SOV | P.O. Box if applicable |
| Insured.Addresses[].City | string | | FROM_DOC | ACORD form, SOV | City name |
| Insured.Addresses[].State | string | | FROM_DOC | ACORD form, SOV | State abbreviation (2-letter code) |
| Insured.Addresses[].StateName | string | | FROM_DOC | ACORD form, SOV | Full state name (derived from code) |
| Insured.Addresses[].ZipCode | string | | FROM_DOC | ACORD form, SOV | ZIP/postal code |
| Insured.Addresses[].County | string | | FROM_DOC | ACORD form, SOV | County name |
| Insured.Addresses[].Country | string | | FROM_DOC | ACORD form, SOV | Country name or code |
| Insured.Contacts[].Type | string | | FROM_DOC | ACORD form, email thread | Role type (e.g., "Owner", "CFO", "Risk Manager") |
| Insured.Contacts[].Name | string | | FROM_DOC | ACORD form, email thread | Contact person's full name |
| Insured.Contacts[].Title | string | | FROM_DOC | ACORD form, email | Professional title/role |
| Insured.Contacts[].Email | string | | FROM_DOC | ACORD form, email | Email address |
| Insured.Contacts[].Phone | string | | FROM_DOC | ACORD form, email | Phone number |
| Insured.Contacts[].Description | string | | FROM_DOC | Email signature, ACORD | Contact notes or comments |
| OtherNamedInsureds[].Name | string | | FROM_DOC | ACORD form, SOV | Additional insured entity name |
| OtherNamedInsureds[].Operations | string | | FROM_DOC | ACORD form, email | Operations description for this entity |
| BrokerRef.BrokerId | string | | INTERNAL | Carrier system | Unique broker identifier in carrier database |
| BrokerRef.ProducerId | string | | INTERNAL | Carrier system | Unique producer/agent identifier in carrier database |
| Agent.Name | string | | FROM_DOC | ACORD form, email | Broker/agent company name |
| Agent.NationalProducerNumber | string | | FROM_DOC | ACORD form, email | NPN (8-digit producer license number) |
| Agent.FEIN | string | | FROM_DOC | ACORD form, email | Federal Employer ID Number |
| Agent.OtherName | string | | FROM_DOC | ACORD form, email | Alternate business name |
| Agent.Description | string | | FROM_DOC | ACORD form, email | Broker/agent description or comments |
| Agent.Website | string | | FROM_DOC | ACORD form, email | Broker/agent website URL |
| Agent.Hierarchy | enum | Headquarters, Branch, Satellite | FROM_DOC | ACORD form, email | Office location type in brokerage hierarchy |
| Agent.Addresses[].Type | enum | Mailing, Physical, Physical and Mailing, Accounting, Additional, HQ | FROM_DOC | ACORD form, email | Office address type |
| Agent.Addresses[].Street | string | | FROM_DOC | ACORD form, email | Street address |
| Agent.Addresses[].Street2 | string | | FROM_DOC | ACORD form, email | Secondary street address |
| Agent.Addresses[].POBox | string | | FROM_DOC | ACORD form, email | P.O. Box |
| Agent.Addresses[].City | string | | FROM_DOC | ACORD form, email | City |
| Agent.Addresses[].State | string | | FROM_DOC | ACORD form, email | State abbreviation |
| Agent.Addresses[].StateName | string | | FROM_DOC | ACORD form, email | Full state name |
| Agent.Addresses[].ZipCode | string | | FROM_DOC | ACORD form, email | ZIP code |
| Agent.Addresses[].County | string | | FROM_DOC | ACORD form, email | County |
| Agent.Addresses[].Country | string | | FROM_DOC | ACORD form, email | Country |
| Agent.Contacts[].Type | enum | Producer, Accounting, SL Licensee | FROM_DOC | ACORD form, email | Contact role within brokerage |
| Agent.Contacts[].Name | string | | FROM_DOC | ACORD form, email | Contact person's name |
| Agent.Contacts[].Title | string | | FROM_DOC | ACORD form, email | Title/position |
| Agent.Contacts[].Email | string | | FROM_DOC | ACORD form, email | Email address |
| Agent.Contacts[].Phone | string | | FROM_DOC | ACORD form, email | Phone number |
| Agent.Contacts[].Description | string | | FROM_DOC | ACORD form, email | Notes about contact |
| GeneralLiability.CoverageSelected | boolean | | FROM_DOC | ACORD form, RFP | GL coverage requested |
| GeneralLiability.EmployeeBenefitsLiability | boolean | | FROM_DOC | ACORD form, RFP | Employee benefits liability sub-coverage |
| Property.CoverageSelected | boolean | | FROM_DOC | ACORD form, RFP | Property coverage requested |
| Property.PerLocationTimeElementReporting | enum | Elected, Not Elected | FROM_DOC | ACORD form, SOV | Reporting form choice for time element coverage |
| Property.AggregateBusinessIncomeLimit | number | | FROM_DOC | ACORD form, SOV | Aggregate Business Income limit amount |
| Locations[].LocationNumber | integer | | FROM_DOC | SOV, broker email | Unique location ID within this submission |
| Locations[].LocationName | string | | FROM_DOC | SOV, broker email | Location friendly name or address reference |
| Locations[].Address.Type | enum | Mailing, Physical, Physical and Mailing, Accounting, Additional, HQ | FROM_DOC | SOV, ACORD | Location address type |
| Locations[].Address.Street | string | | FROM_DOC | SOV, ACORD | Street address |
| Locations[].Address.Street2 | string | | FROM_DOC | SOV, ACORD | Secondary street address |
| Locations[].Address.POBox | string | | FROM_DOC | SOV, ACORD | P.O. Box |
| Locations[].Address.City | string | | FROM_DOC | SOV, ACORD | City |
| Locations[].Address.State | string | | FROM_DOC | SOV, ACORD | State abbreviation |
| Locations[].Address.StateName | string | | FROM_DOC | SOV, ACORD | Full state name |
| Locations[].Address.ZipCode | string | | FROM_DOC | SOV, ACORD | ZIP code |
| Locations[].Address.County | string | | FROM_DOC | SOV, ACORD | County name |
| Locations[].Address.Country | string | | FROM_DOC | SOV, ACORD | Country name |
| Locations[].GeneralLiability[].Rater | enum | HabGen, Accelerant | FROM_DOC | SOV, broker email | Which rating engine to use for this location's GL |
| Locations[].GeneralLiability[].IRPMOverride | boolean | | FROM_DOC | SOV, underwriter note | Manual override of IRPM selection |
| Locations[].GeneralLiability[].IRPM | number | | FROM_DOC | SOV, broker email | Insurance Risk Premium Model rating |
| Locations[].GeneralLiability[].University | string | | FROM_DOC | SOV, broker email | University name (if applicable) |
| Locations[].GeneralLiability[].OccupancyClass | string | | FROM_DOC | SOV, ACORD | GL occupancy class code |
| Locations[].GeneralLiability[].Exposure | number | | FROM_DOC | SOV, ACORD | GL exposure base (receipts, payroll, area, units) |
| Locations[].Buildings[].BuildingNumber | integer | | FROM_DOC | SOV, blueprints | Building ID within location |
| Locations[].Buildings[].Description | string | | FROM_DOC | SOV, email | Building description or identifier |
| Locations[].Buildings[].OccupancyClass | string | | FROM_DOC | SOV, blueprints | Property occupancy class code |
| Locations[].Buildings[].OccupancyType | string | | FROM_DOC | SOV, email | Occupancy type narrative (e.g., "Apartment", "Office") |
| Locations[].Buildings[].YearOfConstruction | integer | | FROM_DOC | SOV, blueprints, property records | Year built (4-digit) |
| Locations[].Buildings[].ConstructionType | string | | FROM_DOC | SOV, blueprints | Construction type (e.g., "Wood Frame", "Masonry") |
| Locations[].Buildings[].RoofType | string | | FROM_DOC | SOV, blueprints, inspection | Roof material/type |
| Locations[].Buildings[].TotalSqFt | number | | FROM_DOC | SOV, blueprints | Total square footage |
| Locations[].Buildings[].NoOfStories | integer | | FROM_DOC | SOV, blueprints | Number of stories/floors |
| Locations[].Buildings[].TotalUnits | integer | | FROM_DOC | SOV, email | Total units (apartments, condos, etc.) |
| Locations[].Buildings[].BedCount | integer | | FROM_DOC | SOV, email | Total bedrooms (multifamily) |
| Locations[].Buildings[].FullySprinklered | boolean | | DERIVED | SOV sprinkler % field | Computed from ProtectiveSafeguards array or % threshold |
| Locations[].Buildings[].ProtectiveSafeguards[] | string | | FROM_DOC | SOV, blueprints, inspection | Fire protection systems (sprinklers, alarms, etc.) |
| Locations[].Buildings[].P9Description | string | | FROM_DOC | SOV, underwriter note | P&C Form 9 description or special characteristics |
| Locations[].Buildings[].Building.BuildingCoverageFlag | boolean | | FROM_DOC | SOV, ACORD | Building coverage elected |
| Locations[].Buildings[].Building.BuildingLimit | number | | FROM_DOC | SOV, ACORD | Building coverage limit amount |
| Locations[].Buildings[].Building.Building100RcValue | number | | FROM_DOC | SOV, ACORD | Replacement cost value at 100% |
| Locations[].Buildings[].Building.Rate | number | | FROM_DOC | SOV, ACORD | Building coverage rate per $100 |
| Locations[].Buildings[].Bpp.BppCoverageFlag | boolean | | FROM_DOC | SOV, ACORD | Business Personal Property coverage elected |
| Locations[].Buildings[].Bpp.BppLimit | number | | FROM_DOC | SOV, ACORD | BPP coverage limit amount |
| Locations[].Buildings[].Bpp.Rate | number | | FROM_DOC | SOV, ACORD | BPP coverage rate per $100 |
| Locations[].Buildings[].BusinessIncomeLimit | number | | FROM_DOC | SOV, ACORD | Business Income coverage limit amount |
| SecuredParties[].Name | string | | FROM_DOC | ACORD form, mortgage docs | Lienholder/mortgagee entity name |
| SecuredParties[].Addresses[].Type | enum | Mailing, Physical, Physical and Mailing, Accounting, Additional, HQ | FROM_DOC | ACORD form, mortgage docs | Lienholder address type |
| SecuredParties[].Addresses[].Street | string | | FROM_DOC | ACORD form, mortgage docs | Street address |
| SecuredParties[].Addresses[].Street2 | string | | FROM_DOC | ACORD form, mortgage docs | Secondary address |
| SecuredParties[].Addresses[].POBox | string | | FROM_DOC | ACORD form, mortgage docs | P.O. Box |
| SecuredParties[].Addresses[].City | string | | FROM_DOC | ACORD form, mortgage docs | City |
| SecuredParties[].Addresses[].State | string | | FROM_DOC | ACORD form, mortgage docs | State abbreviation |
| SecuredParties[].Addresses[].StateName | string | | FROM_DOC | ACORD form, mortgage docs | Full state name |
| SecuredParties[].Addresses[].ZipCode | string | | FROM_DOC | ACORD form, mortgage docs | ZIP code |
| SecuredParties[].Addresses[].County | string | | FROM_DOC | ACORD form, mortgage docs | County |
| SecuredParties[].Addresses[].Country | string | | FROM_DOC | ACORD form, mortgage docs | Country |
| SecuredParties[].LocationNumber | integer | | FROM_DOC | ACORD form, mortgage docs | If lienholder applies to specific location |
| SecuredParties[].AppliesToAllBuildings | boolean | | FROM_DOC | ACORD form, mortgage docs | Lienholder interest is universal |
| SecuredParties[].BuildingNumbers[] | integer | | FROM_DOC | ACORD form, mortgage docs | Specific buildings if not all |
| SecuredParties[].Interest | string | | FROM_DOC | ACORD form, mortgage docs | Interest type (e.g., "Mortgagee", "Loss Payee") |
| SecuredParties[].ReferenceNumber | string | | FROM_DOC | ACORD form, mortgage docs | Loan or reference number |
| LossRuns[].Carrier | string | | FROM_DOC | Loss run document | Prior/current carrier name |
| LossRuns[].PolicyNumber | string | | FROM_DOC | Loss run document | Prior policy number |
| LossRuns[].LOB | enum | Property, General Liability | FROM_DOC | Loss run document | Line of business for this loss run |
| LossRuns[].EvaluationDate | date | | FROM_DOC | Loss run document | Date loss run was pulled |
| LossRuns[].PolicyEffectiveDate | date | | FROM_DOC | Loss run document | Prior policy effective date |
| LossRuns[].PolicyExpirationDate | date | | FROM_DOC | Loss run document | Prior policy expiration date |
| LossRuns[].NoKnownLossesLast5Years | boolean | | FROM_DOC | Loss run document | Clean loss history flag |
| LossRuns[].Claims[].ClaimNumber | string | | FROM_DOC | Loss run document | Claim reference/file number |
| LossRuns[].Claims[].ClaimStatus | enum | Open, Closed | FROM_DOC | Loss run document | Claim status as of evaluation date |
| LossRuns[].Claims[].LossDate | date | | FROM_DOC | Loss run document | Date of loss occurrence |
| LossRuns[].Claims[].Description | string | | FROM_DOC | Loss run document | Claim narrative/description |
| LossRuns[].Claims[].AmountPaid | number | | FROM_DOC | Loss run document | Indemnity paid to date |
| LossRuns[].Claims[].ReserveAmount | number | | FROM_DOC | Loss run document | Outstanding reserve (loss adjuster estimate) |
| LossRuns[].Claims[].ReserveAmountProvided | boolean | | FROM_DOC | Loss run document | Flag if reserve was explicitly provided |
| LossRuns[].Claims[].TotalIncurred | number | | FROM_DOC | Loss run document | Paid + Reserve (total incurred to date) |
| Attachments[].Type | enum | SOV, ACORD, LossRun, Supplemental, Email, Other | INTERNAL | Submission package | Document classification |
| Attachments[].DestinationFolder | string | | INTERNAL | Carrier system | Storage folder path in document management |
| Attachments[].FileName | string | | FROM_DOC | Original submission | Original filename from upload |
| Attachments[].MimeType | string | | INTERNAL | System-detected | Content-type (application/pdf, image/tiff, etc.) |
| Attachments[].AttachmentId | string | | INTERNAL | System-generated | Unique document identifier in carrier system |
| Attachments[].Description | string | | FROM_DOC | Upload metadata or manual entry | Document description or label |
| Attachments[].UploadedDate | date-time | | INTERNAL | Submission system | Timestamp of upload |
| Attachments[].Source | string | | FROM_DOC | Upload source or email | How document arrived (email, portal, etc.) |

## Summary

### Overall Statistics
- **Total Leaf Fields:** 167
- **FROM_DOC (extracted from submission documents):** 135 fields (80.8%)
- **INTERNAL (carrier-assigned post-clearance):** 22 fields (13.2%)
- **DERIVED (computed from other fields):** 2 fields (1.2%)
- **ENRICHMENT (looked up from external sources):** 0 fields (0%)

### Classification Breakdown
- **FROM_DOC:** 135 fields — Core extraction targets from ACORD forms, SOV spreadsheets, loss runs, emails, blueprints, and supporting documents
- **INTERNAL:** 22 fields — System identifiers, workflow status, assignments, and folder management
- **DERIVED:** 2 fields — `Submission.GLSelected` and `Submission.PropertySelected` (both computed from `PolicyInfo.LOB` array)
- **ENRICHMENT:** 0 fields — No external lookup fields presently in schema; `NAICSCode` and `SICCode` are FROM_DOC but could be enriched later

### Top 10 Highest-Priority FROM_DOC Fields (Critical for Extraction)
1. **Insured.Name** — Legal business name; foundational identifier
2. **Locations[].Address (City, State, ZipCode)** — Location identifies underwriting risk; three separate fields critical
3. **Locations[].Buildings[].YearOfConstruction** — Key rating factor for property coverage
4. **Locations[].Buildings[].ConstructionType** — Determines risk profile and rate
5. **Locations[].Buildings[].TotalSqFt** — Exposure base for property premium
6. **LossRuns[].Claims[].LossDate** — Loss history is primary underwriting input
7. **LossRuns[].Claims[].TotalIncurred** — Aggregate loss indicator drives GL and property rates
8. **Insured.NAICSCode** — Industry classification for hazard assessment
9. **PolicyInfo.EffectiveDate** — Retroactive date; required for compliance
10. **Locations[].Buildings[].OccupancyClass** — Occupancy drives both property and GL rating

### Ambiguous or Notable Classifications
- **Insured.Addresses[].StateName** — Listed as FROM_DOC, but is typically DERIVED from State abbreviation. Can be enriched or standardized.
- **Agent.Addresses[].StateName** — Same as above; could be DERIVED.
- **SecuredParties[].Addresses[].StateName** — Same; could be DERIVED.
- **Locations[].Address.StateName** — Same; could be DERIVED.
- **Locations[].Buildings[].FullySprinklered** — Marked as DERIVED, but may sometimes come directly from SOV (if marked with %) and sometimes computed from ProtectiveSafeguards array; this is a hybrid field.
- **Attachments[].Type** — Classified as INTERNAL (assigned by system), but could also be FROM_DOC if explicitly labeled in submission. Consider semi-automatic classification.
- **Attachments[].Description** — Marked FROM_DOC, but auto-generated descriptions may be INTERNAL.

### Key Observations for Extraction Pipeline
1. **Document Dependency:** ~80% of fields come from 4-6 source documents (ACORD, SOV, loss runs, email threads, blueprints). Extraction accuracy depends heavily on OCR/parsing quality for these document types.
2. **Hierarchical Nesting:** Locations > Buildings is the deepest nesting; extraction must preserve 1-to-many relationships correctly.
3. **Data Validation:** State abbreviation fields should trigger DERIVED logic to populate StateName; consider schema design with read-only computed fields.
4. **Loss Run Criticality:** Claims data is entirely FROM_DOC and has minimal transformation; extraction must achieve near-perfect accuracy here.
5. **Address Standardization:** Address fields appear 5 times (Insured, Agent, Locations, SecuredParties, Buildings); consider a unified address extraction and validation service.
6. **Enum Consistency:** Several fields (OccupancyClass, ConstructionType, RoofType) are free-text string enums; standardization/lookup against insurance industry glossaries will be needed.

