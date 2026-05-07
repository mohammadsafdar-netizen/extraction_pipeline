"""
Form-specific and generalized prompts for insurance document extraction.
"""

# ── GENERALIZED PROMPT (works on any insurance document) ──

GENERALIZED = """You are an expert insurance document parser. Extract every single data field from this page into a flat JSON object.

CRITICAL RULES:
- CHECKBOXES: Only set to true if you can see an actual X mark or filled checkbox. An empty box = false or omit. Do NOT assume a field is checked just because the option label is printed on the form. Most checkboxes on blank forms are NOT checked.
- LABELS vs VALUES: Do NOT capture form labels as values. "Y/N", "SQ FT", "$", "PRODUCER'S SIGNATURE", "DATE", "PREM/OPS" are labels, not answers. Only capture actual filled-in handwritten/typed data.
- ENTITY TYPE: Only mark an entity type (Corporation, LLC, Individual, etc.) as true if an X mark is visually present next to it.
- LINES OF BUSINESS: Only include lines that have an X mark next to them. Do not list all printed options.
- ATTACHMENTS: Only include attachments that have an X mark. Do not list all printed attachment names.
- STATUS OF TRANSACTION: Only mark the one that has an X (quote/bound/issue/renew/change/cancel). Most forms have only one checked.
- COVERAGE TRIGGER: A policy is either claims-made OR occurrence, rarely both. Only mark the one with an X.
- FOOTER CODES: Text like "LBAKER", "LMOSS", page numbers, and "ACORD 125 (2016/03)" are footer/watermark codes, NOT data values. Do not capture them as field values.
- CARRIER NAME: Read the carrier name carefully and spell it exactly as printed. Do not vary spelling across pages.
- Dollar amounts: use numbers without $ sign (e.g. 5000000 not "$5,000,000")
- Dates: use MM/DD/YYYY format
- Tables: create an array of objects, one per row
- Preserve exact spelling of names, addresses, and codes

Return ONLY a valid JSON object. No explanation. /no_think"""


# ── FORM-SPECIFIC PROMPTS ──

ACORD_125_P1 = """This is ACORD 125 Page 1 — Commercial Insurance Application, Applicant Information Section.
Extract these exact fields into JSON:

HEADER: date, agency_name, agency_address, agency_city_state_zip, carrier, naic_code, company_policy_or_program_name, program_code, policy_number, contact_name, contact_phone, contact_fax, contact_email, underwriter, underwriter_office, code, subcode, agency_customer_id

STATUS_OF_TRANSACTION: quote (true/false), issue_policy (true/false), renew (true/false), bound (true/false), change (true/false), cancel (true/false), bound_date, change_date, change_time

LINES_OF_BUSINESS: For each line checked, include name and premium amount. Lines: boiler_machinery, business_auto, business_owners, commercial_general_liability, commercial_inland_marine, commercial_property, crime, cyber_and_privacy, fiduciary_liability, garage_and_dealers, liquor_liability, motor_carrier, truckers, umbrella, yacht

POLICY_INFORMATION: proposed_eff_date, proposed_exp_date, billing_plan (direct/agency), payment_plan, method_of_payment, audit, deposit, minimum_premium, policy_premium

APPLICANT_INFORMATION (for each named insured): full_name, address_line1, address_line2, city_state_zip, gl_code, sic, naics, fein_or_soc_sec, business_phone, website_address, entity_type (corporation/individual/llc/joint_venture/partnership/trust/not_for_profit/subchapter_s), number_of_members_and_managers

Only include fields with actual values. Dollar amounts as numbers. Checkboxes as true/false. Return ONLY valid JSON. /no_think"""

ACORD_125_P2 = """This is ACORD 125 Page 2 — Contact Information & Premises Information.
Extract these exact fields into JSON:

CONTACT_INFORMATION: For each contact (up to 2):
- contact_type, contact_name, primary_phone, primary_phone_type (home/bus/cell), secondary_phone, secondary_phone_type, primary_email, secondary_email

PREMISES_INFORMATION: For each premises block (up to 4):
- loc_number, bld_number, street, city, state, zip, county
- city_limits (inside/outside), interest (owner/tenant)
- full_time_employees, part_time_employees
- annual_revenues, occupied_area_sqft, open_to_public_area_sqft, total_building_area_sqft
- area_leased_to_others (Y/N)
- description_of_operations

NATURE_OF_BUSINESS: Check which applies: apartments, condominiums, contractor, institutional, manufacturing, office, restaurant, retail, service, wholesale, other (with description)
Also: date_business_started

DESCRIPTION_OF_PRIMARY_OPERATIONS: (text field)

Only include fields with actual values. Return ONLY valid JSON. /no_think"""

ACORD_125_P3 = """This is ACORD 125 Page 3 — General Information.
Extract these exact fields into JSON:

GENERAL_INFORMATION: For each question, extract the Y/N answer and any explanation text:
- q1a_subsidiary_of_another: Y/N, parent_company_name, relationship, percent_owned
- q1b_has_subsidiaries: Y/N, subsidiary_name, relationship, percent_owned
- q2_safety_program: Y/N, safety_manual (true/false), safety_position (true/false), monthly_meetings (true/false), osha (true/false)
- q3_flammables_exposure: Y/N, explanation
- q4_other_insurance: Y/N, lines_of_business and policy_numbers (array)
- q5_policy_declined_cancelled: Y/N, non_payment/agent_no_longer/non_renewal/underwriting/condition_corrected
- q6_sexual_abuse_claims: Y/N, explanation
- q7_crime_conviction: Y/N, explanation
- q8_fire_safety_violations: Y/N, occur_date, explanation, resolution, resolve_date
- q9_foreclosure_bankruptcy: Y/N, occur_date, explanation, resolution, resolve_date
- q10_judgement_or_lien: Y/N, occur_date, explanation, resolution, resolve_date
- q11_business_in_trust: Y/N, name_of_trust
- q12_foreign_operations: Y/N
- q13_other_business_ventures: Y/N
- q14_own_drones: Y/N, description
- q15_hire_drone_operators: Y/N, description

REMARKS: (text)

PRIOR_CARRIER_INFORMATION: For each year:
- year, category (carrier/policy_number/premium/effective_date/expiration_date)
- general_liability, automobile, property, other values

Only include fields with actual values. Return ONLY valid JSON. /no_think"""

ACORD_125_P4 = """This is ACORD 125 Page 4 — Prior Carrier (continued), Loss History, Signature.
Extract these exact fields into JSON:

PRIOR_CARRIER_INFORMATION_CONTINUED: Same format as page 3, additional years.

LOSS_HISTORY:
- check_if_none: true/false
- for_the_last_years: number
- total_losses: dollar amount
- claims: array of objects, each with:
  - date_of_occurrence, line, type_description, date_of_claim, amount_paid, amount_reserved, subrogation (Y/N), claim_open (Y/N)

SIGNATURE: producer_name, applicant_signature_date, national_producer_number, state_producer_license_no

Only include fields with actual values. Dollar amounts as numbers. Return ONLY valid JSON. /no_think"""

ACORD_140_P1 = """This is ACORD 140 Page 1 — Property Section.
Extract these exact fields into JSON:

HEADER: date, agency_name, carrier, naic_code, policy_number, effective_date, named_insured

BLANKET_SUMMARY: array of objects: blanket_number, amount, type

PREMISES_INFORMATION: premises_number, building_number, street_address, bldg_description

COVERAGES: array of objects, one per row:
- subject_of_insurance (e.g. "Building", "Business Personal Property", "Business Income with Extra Expense")
- amount (dollar value as number)
- coins_percent
- valuation_code (R=Replacement, A=Actual Cash Value, L=Limit, S=Stated, etc.)
- cause_of_loss (e.g. "Special (Including theft)")
- inflation_guard_percent
- deductible_amount (number)
- deductible_type
- blanket_number
- forms_and_conditions

ADDITIONAL_COVERAGES: spoilage (Y/N, description, limit, deductible), sinkhole (accept/reject, limit), mine_subsidence (accept/reject, limit), historical_landmark (true/false), open_sides_count

CONSTRUCTION: construction_type, distance_to_hydrant_ft, distance_to_fire_station_mi, fire_district, code_number, protection_class, num_stories, num_basements, year_built, total_area_sqft

BUILDING_IMPROVEMENTS: wiring (checked true/false, year), plumbing (checked, year), roofing (checked, year), heating (checked, year), other (checked, description, year), bldg_code_grade, tax_code, roof_type, other_occupancies, wind_class (resistive/semi-resistive/other)

HEATING: primary_heat (boiler/solid_fuel/other), secondary_heat (boiler/solid_fuel/other), boiler_insured_elsewhere (Y/N)

EXPOSURE: right_description, right_distance, left_description, left_distance, front_description, front_distance, rear_description, rear_distance

BURGLAR_ALARM: type, certificate_number, expiration_date, central_station (true/false), local_gong (true/false), with_keys (true/false), installed_by, extent, grade, guards_watchmen_count, clock_hourly (true/false)

FIRE_PROTECTION: description, sprinkler_percent, fire_alarm_manufacturer, central_station (true/false), local_gong (true/false)

ADDITIONAL_INTEREST: interest_type (loss_payee/mortgagee/other), name, address_line1, address_line2, city, state, zip, country, rank, certificate_required, reference_loan_number, location_number, building_number, item_class, item_number, item_description

Only include fields with actual values. Dollar amounts as numbers. Return ONLY valid JSON. /no_think"""

ACORD_140_P2 = """This is ACORD 140 Page 2 — Property Section (continued).
Extract these exact fields into JSON:

PREMISES: premises_number, street_address, building_number, bldg_description

COVERAGES: Same format as page 1 — array of coverage rows with subject, amount, valuation, cause_of_loss, deductible, etc.

ADDITIONAL_COVERAGES: spoilage, sinkhole, mine_subsidence, historical_landmark, open_sides

CONSTRUCTION: construction_type, distance_to_hydrant_ft, distance_to_fire_station_mi, fire_district, code_number, protection_class, num_stories, num_basements, year_built, total_area_sqft

BUILDING_IMPROVEMENTS: wiring (checked, year), plumbing (checked, year), roofing (checked, year), heating (checked, year), other (checked, description, year), bldg_code_grade, tax_code, roof_type, other_occupancies, wind_class

HEATING, EXPOSURE, BURGLAR_ALARM, FIRE_PROTECTION, ADDITIONAL_INTEREST: same structure as page 1.

REMARKS: text

Only include fields with actual values. Dollar amounts as numbers. Return ONLY valid JSON. /no_think"""

ACORD_140_P3 = """This is ACORD 140 Page 3 — Property Section Signature page.
Extract only the signature fields if present: producer_signature, producer_name, state_producer_license_no, applicant_signature, date, national_producer_number.
Return ONLY valid JSON. /no_think"""

ACORD_126_P1 = """This is ACORD 126 Page 1 — Commercial General Liability Section.
Extract these exact fields into JSON:

HEADER: date, agency, carrier, naic_code, policy_number, effective_date, named_insured

COVERAGES: commercial_general_liability (true/false), claims_made (true/false), occurrence (true/false), owners_contractors_protective (true/false), other_coverage (true/false, description)

LIMITS: general_aggregate, products_completed_operations_aggregate, personal_advertising_injury, each_occurrence, damage_to_rented_premises, medical_expense, employee_benefits
All as numbers.

LIMIT_APPLIES_PER: policy (true/false), location (true/false), project (true/false), other (true/false, description)

PREMIUMS: premises_operations, products, other, total

DEDUCTIBLES: property_damage (amount, per_claim/per_occurrence), bodily_injury (amount, per_claim/per_occurrence)

OTHER_COVERAGES_NOTE: text

SCHEDULE_OF_HAZARDS: array of objects:
- loc_number, haz_number, classification, class_code, premium_basis, exposure, territory
- rate_prem_ops, rate_products, premium_prem_ops, premium_products

CLAIMS_MADE: proposed_retroactive_date, entry_date, prior_coverage_excluded (Y/N, explanation), tail_coverage_purchased (Y/N, explanation)

EMPLOYEE_BENEFITS: deductible_per_claim, number_of_employees, employees_covered, retroactive_date

Only include fields with actual values. Dollar amounts as numbers. Return ONLY valid JSON. /no_think"""

ACORD_126_P2 = """This is ACORD 126 Page 2 — Contractors section.
Extract questions 1-6 (operations) and 1-10 (products) with Y/N answers and explanations.
Also extract subcontractor table and products table if present.
Return ONLY valid JSON. /no_think"""

ACORD_126_P3 = """This is ACORD 126 Page 3 — Additional Interest / Certificate Recipient and General Information.
Extract: additional_interest (type, name, address, rank, evidence, certificate, reference_loan, location, building, item),
and questions 1-15 with Y/N answers and explanations (medical facilities, radioactive, hazardous materials, operations sold, equipment rental, watercraft, parking, recreation, social events, athletic teams, structural alterations, demolition).
Return ONLY valid JSON. /no_think"""

ACORD_126_P4 = """This is ACORD 126 Page 4 — General Information (continued) and Signature.
Extract questions 16-22 with Y/N answers. Also extract remarks text and signature fields.
Return ONLY valid JSON. /no_think"""

ACORD_131_P1 = """This is ACORD 131 Page 1 — Umbrella/Excess Section.
Extract these exact fields into JSON:

HEADER: date, agency, carrier (spell exactly as printed), naic_code, policy_number, effective_date, named_insured

POLICY_INFORMATION:
- transaction_type: ONLY mark true for the one with an X mark (new OR renewal, not both)
- policy_type: ONLY mark true for the one with an X (umbrella OR excess, not both)
- coverage_trigger: ONLY mark true for the one with an X (occurrence OR claims_made, not both)
- retroactive_date_proposed (a DATE, not a dollar amount), retroactive_date_current (a DATE)
- limit_each_occurrence (dollar amount as number — from the LIMIT OF LIABILITY section, next to "EA OCC")
- limit_aggregate (dollar amount as number — next to "Aggregate")
- retained_limit (dollar amount as number — from RETAINED LIMIT column)
- first_dollar_defense (Y/N)
- expiring_policy_number

IMPORTANT: The LIMIT OF LIABILITY fields contain dollar amounts. The RETROACTIVE DATE fields contain dates. Do not put dollar amounts into date fields or vice versa.

EMPLOYEE_BENEFITS_LIABILITY: limit_per_employee, aggregate_limit, retained_limit, retroactive_date, benefit_program_name

PRIMARY_LOCATIONS: array of objects: number, name, location, description, annual_payroll, annual_gross_sales, foreign_gross_sales, num_employees

UNDERLYING_INSURANCE: array of objects for each row in the underlying insurance table:
- type (automobile_liability / general_liability / employers_liability / other)
- carrier_policy_number, policy_eff_date, policy_exp_date
- For general liability: policy_type (occur/claims_made), each_occurrence, general_aggregate, products_completed_ops_aggregate, personal_advertising_injury, damage_to_rented_premises, medical_expense
- For auto: csl_ea_acc, bi_ea_acc, bi_ea_per, pd_ea_acc
- For employers: each_accident, disease_each_employee, disease_policy_limit
- annual_renewal_premium, rating_mod

All dollar amounts as numbers. Only checked checkboxes as true. Return ONLY valid JSON. /no_think"""

ACORD_131_P2 = """This is ACORD 131 Page 2 — Underlying Insurance (continued).
Extract: underlying GL information questions (1-6 with Y/N and explanations),
coverage checklist (auto, CGL claims/occurrence, aircraft, additional interests, etc.),
underlying insurance coverage information text,
previous experience/claims,
care custody control table,
vehicles table (private passenger, light/medium/heavy/ex-heavy trucks, buses with counts and radius).
Return ONLY valid JSON. /no_think"""

ACORD_131_P3 = """This is ACORD 131 Page 3 — Additional Exposures.
Extract questions 1-19 with Y/N answers and details:
Advertisers liability (media, cost, agency), aircraft liability, auto liability (explosives, passengers, uninsured, leased, hired/non-owned), contractors liability (bridge/dam, typical jobs, agreements, cranes, subcontractors), employers liability (self-insured, jones act/FELA/stop gap), incidental malpractice (hospital, doctors, nurses, beds).
Return ONLY valid JSON. /no_think"""

ACORD_131_P4 = """This is ACORD 131 Page 4 — Additional Exposures (continued).
Extract: pollution liability (EPA#, questions 20-21, coverage types), product liability (questions 22-25, gross sales), protective liability (question 26), watercraft liability (question 27 with table), apartments/condominiums/hotels table (loc, stories, units, pools, diving boards), remarks.
Return ONLY valid JSON. /no_think"""

ACORD_131_P5 = """This is ACORD 131 Page 5 — Remarks and Signature.
Extract: remarks text, UM/UIM coverage selections (amounts and initials for each state: Louisiana, New Hampshire, Vermont, Wisconsin), signature fields (producer, applicant, dates, license numbers).
Return ONLY valid JSON. /no_think"""

ACORD_823 = """This is ACORD 823 — Additional Premises Information Schedule.
Extract: header (agency, carrier, naic_code, policy_number, effective_date, named_insured),
then for each premises block: loc_number, bld_number, street, city, state, zip, county,
city_limits, interest, full_time_employees, part_time_employees, annual_revenues,
occupied_area, open_to_public_area, total_building_area, area_leased_to_others, description_of_operations.
Return ONLY valid JSON. /no_think"""

LOSS_RUN = """Extract ALL data from this insurance loss run page into JSON.

CRITICAL RULES:
- Include ALL values even if they are zero. A row showing 0 claims and $0.00 paid is real data proving a clean loss history. Never skip zero rows.
- CARRIER vs BROKER vs AGENCY: The "Company" field is the insurance carrier (the entity that issued the policy). The "Agency" or "Broker" is the intermediary. A logo at the top is NOT the carrier — read the actual text field labeled "Company" or "Carrier". If the document is a letter (not a table), the sender/letterhead is usually the broker, not the carrier.
- INSURED: The "Named Insured" or "Account Name" is who holds the policy. If the document is addressed TO someone (e.g. "Dear Mr. Ferrara"), the addressee may be a contact, not the insured — look for the policy holder's name in the body or header.
- DATE_CLOSED vs REPORTED_DATE: These are different fields. "Date Closed" is when a claim was resolved. "Reported Date" or "Date Reported" is when the claim was first reported. Do NOT put the reported date into date_closed. If a claim status is "Open", date_closed must be empty/null.
- CLAIMS_STATUS CONSISTENCY: If actual claims are listed on the page with amounts, do NOT also say "NO LOSSES OR CLAIMS REPORTED". That phrase only applies to sections/properties that genuinely have zero claims.
- MULTI-PROPERTY LOSS RUNS: Each PID/property block has its own claims. Attribute claims to the correct property they appear under, not to the next or previous property block.
- CLAIM ATTRIBUTION: Claims listed directly under a property header belong to THAT property. Do not mix claims between properties.

Include:
- header: policy_number, company/carrier, insured_name, insured_address, agency_name, valuation_date, date_range, line_of_business
- For summary pages: array of ALL period rows with: effective_date, expiration_date, claim_count, losses_paid, reserves, gross_incurred, expenses, recoveries, net_incurred
- totals row with same fields (even if all zeros)
- For detail pages: array of claims with: claim_number, date_of_loss, reported_date, type_cause, claimant, description, amount_paid, amount_reserved, expenses, amount_recovered, status, date_closed (null if Open)
- For multi-property: PID, named_insured, property_name, insured_address for each block with their own claims array

All dollar amounts as numbers. Return ONLY valid JSON. /no_think"""

SUPPLEMENTAL = """Extract ALL filled data from this insurance supplemental application page into JSON.
Include every field with a value: applicant info, property details, construction type, year built,
square footage, number of units/stories/buildings, occupancy info, management details,
annual revenue, payroll, loss history, security features, all questions with Y/N answers.
Skip empty fields. Dollar amounts as numbers. Return ONLY valid JSON. /no_think"""

QUESTIONNAIRE = """Extract ALL filled data from this insurance questionnaire page into JSON.
Include: applicant info, property details, all questions with their answers (Y/N/text/numbers),
management details, financial info, occupancy data, any tables.
Skip empty fields. Return ONLY valid JSON. /no_think"""


# ── Page-to-prompt mapping ──

def get_prompt(pdf_name, page_num, total_pages, doc_type=None):
    """Get the best prompt for a given page."""

    # doc_type takes priority — always check it first
    if doc_type == "loss_run":
        return LOSS_RUN

    if doc_type == "supplemental_application":
        return SUPPLEMENTAL

    if doc_type == "questionnaire":
        return QUESTIONNAIRE

    # For the known 1800 North Stone ACORD app
    if ("1800 North Stone" in pdf_name or "Acord App" in pdf_name) and doc_type == "acord_application":
        page_prompts = {
            1: ACORD_125_P1, 2: ACORD_125_P2, 3: ACORD_125_P3, 4: ACORD_125_P4,
            5: ACORD_823,
            6: ACORD_140_P1, 7: ACORD_140_P2, 8: ACORD_140_P3,
            9: ACORD_140_P1, 10: ACORD_140_P2, 11: ACORD_140_P3,
            12: ACORD_140_P1, 13: ACORD_140_P2, 14: ACORD_140_P3,
            15: GENERALIZED,  # overflow page
            16: ACORD_126_P1, 17: ACORD_126_P2, 18: ACORD_126_P3, 19: ACORD_126_P4,
            20: GENERALIZED,  # overflow page
            21: ACORD_131_P1, 22: ACORD_131_P2, 23: ACORD_131_P3,
            24: ACORD_131_P4, 25: ACORD_131_P5,
        }
        return page_prompts.get(page_num, GENERALIZED)

    # For other known ACORD applications
    if doc_type == "acord_application":
        return GENERALIZED

    return GENERALIZED
