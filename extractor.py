"""
ACORD Flattened PDF Field Extractor
Extracts structured data from flattened ACORD forms using coordinate-based text mapping.
"""

import pdfplumber
import json
import re
from pathlib import Path


# ── Helpers ──────────────────────────────────────────────────────────────────

KNOWN_LABELS = {
    "AGENCY", "CARRIER", "NAIC CODE", "COMPANY POLICY OR PROGRAM NAME",
    "PROGRAM CODE", "POLICY NUMBER", "CONTACT", "NAME:", "PHONE", "FAX",
    "E-MAIL", "ADDRESS:", "UNDERWRITER", "UNDERWRITER OFFICE", "CODE:",
    "SUBCODE:", "AGENCY CUSTOMER ID:", "STATUS OF", "TRANSACTION",
    "QUOTE", "ISSUE POLICY", "RENEW", "CHANGE", "CANCEL", "DATE", "TIME",
    "AM", "PM", "BOUND (Give Date and/or Attach Copy):",
    "LINES OF BUSINESS", "INDICATE LINES OF BUSINESS", "PREMIUM",
    "ATTACHMENTS", "POLICY INFORMATION", "APPLICANT INFORMATION",
    "PROPOSED EFF DATE", "PROPOSED EXP DATE", "BILLING PLAN",
    "PAYMENT PLAN", "METHOD OF PAYMENT", "AUDIT", "DEPOSIT",
    "MINIMUM", "PREMIUM", "POLICY PREMIUM", "DIRECT", "AGENCY",
    "GL CODE", "SIC", "NAICS", "FEIN OR SOC SEC #",
    "BUSINESS PHONE #:", "WEBSITE ADDRESS", "CORPORATION",
    "JOINT VENTURE", "NOT FOR PROFIT ORG", "SUBCHAPTER \"S\" CORPORATION",
    "INDIVIDUAL", "LLC", "PARTNERSHIP", "TRUST", "NO. OF MEMBERS",
    "AND MANAGERS:", "(A/C, No, Ext):", "(A/C, No):",
    "LOC #", "BLD #", "STREET", "CITY:", "STATE:", "COUNTY:", "ZIP:",
    "CITY LIMITS", "INSIDE", "OUTSIDE", "INTEREST", "OWNER", "TENANT",
    "# FULL TIME EMPL", "# PART TIME EMPL", "ANNUAL REVENUES:", "$",
    "OCCUPIED AREA:", "OPEN TO PUBLIC AREA:", "TOTAL BUILDING AREA:",
    "SQ FT", "DESCRIPTION OF OPERATIONS:",
    "ANY AREA LEASED TO OTHERS? Y / N",
    "CONTACT TYPE:", "CONTACT NAME:", "PRIMARY", "SECONDARY",
    "PHONE #", "HOME", "BUS", "CELL",
    "PRIMARY E-MAIL ADDRESS:", "SECONDARY E-MAIL ADDRESS:",
    "PREMISES INFORMATION", "NATURE OF BUSINESS",
    "DESCRIPTION OF PRIMARY OPERATIONS",
}


def get_words(page):
    """Extract and sort words from page."""
    words = page.extract_words(keep_blank_chars=True, x_tolerance=2, y_tolerance=2)
    words.sort(key=lambda w: (round(w["top"], 0), w["x0"]))
    return words


def region_text(words, x0, y0, x1, y1, exclude=None):
    """Get concatenated text from words within a bounding box."""
    hits = [
        w for w in words
        if w["x0"] >= x0 - 3 and w["x1"] <= x1 + 3
        and w["top"] >= y0 - 3 and w["bottom"] <= y1 + 3
    ]
    hits.sort(key=lambda w: (round(w["top"], 0), w["x0"]))
    text = " ".join(w["text"] for w in hits).strip()
    if exclude:
        for ex in exclude:
            text = text.replace(ex, "").strip()
    # Clean up multiple spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def value_right_of(words, label, max_gap=200, y_tol=5):
    """Find text immediately to the right of a label word."""
    for w in words:
        if w["text"].strip() == label:
            candidates = [
                c for c in words
                if c["x0"] > w["x1"] - 2
                and c["x0"] < w["x1"] + max_gap
                and abs(c["top"] - w["top"]) < y_tol
                and c["text"].strip() not in KNOWN_LABELS
            ]
            if candidates:
                candidates.sort(key=lambda c: c["x0"])
                return " ".join(c["text"] for c in candidates).strip()
    return None


def checked_box(words, label, y_tol=6, x_range=30):
    """Check if there's an 'X' near a label (indicating a checked checkbox)."""
    for w in words:
        if label.lower() in w["text"].lower():
            for c in words:
                if c["text"].strip() == "X" and abs(c["top"] - w["top"]) < y_tol:
                    if abs(c["x0"] - w["x0"]) < x_range or abs(c["x1"] - w["x0"]) < x_range:
                        return True
    return False


# ── Page-specific extractors ────────────────────────────────────────────────

def extract_page1(page):
    """ACORD 125 Page 1 of 4: Applicant Information Section"""
    w = get_words(page)
    d = {"form": "ACORD 125", "section": "Applicant Information (Page 1 of 4)"}

    # Header
    d["date"] = region_text(w, 520, 48, 580, 62)

    # Agency block
    d["agency"] = region_text(w, 15, 70, 300, 105, ["AGENCY"])
    d["carrier"] = region_text(w, 300, 70, 540, 88, ["CARRIER"])
    d["naic_code"] = region_text(w, 540, 70, 612, 88, ["NAIC CODE"])
    d["company_policy_or_program_name"] = region_text(w, 300, 96, 530, 114, ["COMPANY POLICY OR PROGRAM NAME"])
    d["program_code"] = region_text(w, 530, 96, 612, 114, ["PROGRAM CODE"])
    d["policy_number"] = region_text(w, 300, 114, 530, 136, ["POLICY NUMBER"])

    # Contact
    d["contact_phone"] = region_text(w, 60, 143, 300, 158, ["PHONE", "(A/C, No, Ext):"])
    d["contact_fax"] = region_text(w, 60, 155, 300, 170, ["FAX", "(A/C, No):"])
    d["contact_email"] = region_text(w, 50, 167, 300, 182, ["E-MAIL", "ADDRESS:"])
    d["underwriter"] = region_text(w, 350, 136, 455, 158, ["UNDERWRITER"])
    d["underwriter_office"] = region_text(w, 453, 136, 612, 158, ["UNDERWRITER OFFICE"])

    d["code"] = region_text(w, 42, 184, 165, 200, ["CODE:"])
    d["subcode"] = region_text(w, 198, 184, 395, 200, ["SUBCODE:"])
    d["agency_customer_id"] = region_text(w, 90, 192, 310, 208, ["AGENCY CUSTOMER ID:"])

    # Lines of business - look for premium values next to each line
    lines_of_biz = {}
    biz_lines = [
        ("boiler_machinery", 36, 234), ("business_auto", 36, 246),
        ("business_owners", 36, 258), ("commercial_general_liability", 36, 270),
        ("commercial_inland_marine", 36, 282), ("commercial_property", 36, 294),
        ("crime", 36, 306),
        ("cyber_and_privacy", 230, 234), ("fiduciary_liability", 230, 246),
        ("garage_and_dealers", 230, 258), ("liquor_liability", 230, 270),
        ("motor_carrier", 230, 282), ("truckers", 230, 294),
        ("umbrella", 230, 306),
        ("yacht", 421, 234),
    ]
    for name, x, y in biz_lines:
        # Check for premium value in the premium column for this row
        prem = region_text(w, 151 if x < 200 else (345 if x < 400 else 536), y - 2,
                          (225 if x < 200 else (420 if x < 400 else 612)), y + 10,
                          ["$", "PREMIUM"])
        if prem and prem != "$":
            lines_of_biz[name] = prem
    d["lines_of_business"] = lines_of_biz if lines_of_biz else None

    # Policy Information
    d["proposed_eff_date"] = region_text(w, 20, 470, 95, 488)
    d["proposed_exp_date"] = region_text(w, 95, 470, 175, 488)
    d["billing_plan_direct"] = checked_box(w, "DIRECT")
    d["billing_plan_agency"] = checked_box(w, "AGENCY")
    d["deposit"] = region_text(w, 420, 470, 480, 484, ["$"])
    d["minimum_premium"] = region_text(w, 478, 470, 540, 484, ["$"])
    d["policy_premium"] = region_text(w, 536, 470, 612, 484, ["$"])

    # Named Insured
    d["named_insured"] = region_text(w, 15, 508, 310, 542)
    d["gl_code"] = region_text(w, 340, 508, 382, 525, ["GL CODE"])
    d["sic"] = region_text(w, 375, 508, 455, 525, ["SIC"])
    d["naics"] = region_text(w, 453, 508, 528, 525, ["NAICS"])
    d["fein_or_soc_sec"] = region_text(w, 525, 508, 612, 525, ["FEIN OR SOC SEC #"])
    d["business_phone"] = region_text(w, 368, 520, 530, 538, ["BUSINESS PHONE #:"])
    d["website_address"] = region_text(w, 305, 543, 530, 558, ["WEBSITE ADDRESS"])

    # Entity type
    entity_types = []
    if checked_box(w, "CORPORATION"): entity_types.append("Corporation")
    if checked_box(w, "INDIVIDUAL"): entity_types.append("Individual")
    if checked_box(w, "LLC"): entity_types.append("LLC")
    if checked_box(w, "PARTNERSHIP"): entity_types.append("Partnership")
    if checked_box(w, "TRUST"): entity_types.append("Trust")
    if checked_box(w, "JOINT VENTURE"): entity_types.append("Joint Venture")
    if checked_box(w, "NOT FOR PROFIT"): entity_types.append("Not For Profit Org")
    if checked_box(w, "SUBCHAPTER"): entity_types.append("Subchapter S Corporation")
    d["entity_type"] = entity_types if entity_types else None

    return {k: v for k, v in d.items() if v is not None}


def extract_page2(page):
    """ACORD 125 Page 2 of 4: Contact & Premises Information"""
    w = get_words(page)
    d = {"form": "ACORD 125", "section": "Contact & Premises Info (Page 2 of 4)"}

    d["agency_customer_id"] = region_text(w, 410, 28, 470, 45)

    # Premises - 4 repeating blocks (each ~60pt tall)
    premises = []
    # y positions from actual coordinate dump:
    # Block1: street@141, loc@146, city@159, bld@170, county@170, zip@170
    # Block2: street@201, loc@206, city@219, bld@230, county@230, zip@230
    # Block3: street@261, loc@266, city@279, bld@290, county@290, zip@290
    # Block4: street@321, loc@326, city@339, bld@350, county@350, zip@350
    block_y = [
        (136, 141, 146, 159, 170),  # street_y, loc_y, bld_top, city_y, county_y
        (196, 201, 206, 219, 230),
        (256, 261, 266, 279, 290),
        (316, 321, 326, 339, 350),
    ]
    for street_y, loc_top, loc_bottom, city_y, county_y in block_y:
        p = {}
        p["street"] = region_text(w, 44, street_y, 200, street_y + 14)
        p["loc_num"] = region_text(w, 26, loc_top, 42, loc_bottom + 12)
        p["city"] = region_text(w, 62, city_y - 2, 130, city_y + 12)
        p["state"] = region_text(w, 220, city_y - 2, 250, city_y + 12)
        p["bld_num"] = region_text(w, 26, county_y - 2, 42, county_y + 12)
        p["county"] = region_text(w, 62, county_y - 2, 130, county_y + 12)
        p["zip"] = region_text(w, 210, county_y - 2, 265, county_y + 12)
        p = {k: v for k, v in p.items() if v is not None}
        if p.get("street") or p.get("city"):
            premises.append(p)
    d["premises"] = premises if premises else None

    # Nature of Business - "68 Unit Student Housing Apartment Complex"
    d["nature_of_business"] = region_text(w, 405, 383, 510, 406,
        ["DATE BUSINESS", "STARTED (MM/DD/YYYY)"])

    return {k: v for k, v in d.items() if v is not None}


def extract_page3(page):
    """ACORD 125 Page 3 of 4: General Information"""
    w = get_words(page)
    d = {"form": "ACORD 125", "section": "General Information (Page 3 of 4)"}

    d["agency_customer_id"] = region_text(w, 410, 28, 470, 45)

    # Questions 1-15 (Y/N answers would be in the right margin ~576-590)
    questions = {
        "1a_subsidiary_of_another": (65, 80),
        "1b_has_subsidiaries": (101, 115),
        "2_safety_program": (137, 152),
        "3_flammables_exposure": (161, 196),
        "4_other_insurance": (197, 245),
        "5_policy_declined_cancelled": (245, 287),
        "6_sexual_abuse_claims": (287, 323),
        "7_crime_conviction": (323, 383),
        "8_fire_safety_violations": (383, 431),
        "9_foreclosure_bankruptcy": (431, 479),
        "10_judgement_or_lien": (479, 526),
        "11_business_in_trust": (526, 538),
        "12_foreign_operations": (538, 557),
        "13_other_business_ventures": (557, 593),
        "14_own_drones": (593, 617),
        "15_hire_drone_operators": (617, 640),
    }
    general_info = {}
    for qname, (y_start, y_end) in questions.items():
        # Check for Y/N answer in far right column
        answer = region_text(w, 570, y_start - 3, 612, y_end + 3)
        if answer and answer in ("Y", "N", "Y / N"):
            if answer != "Y / N":
                general_info[qname] = answer
    d["general_information_answers"] = general_info if general_info else None

    # Prior Carrier Information (bottom of page 3)
    d["prior_carrier_year"] = region_text(w, 22, 695, 46, 770, ["YEAR"])
    d["prior_carrier_gl"] = region_text(w, 118, 706, 237, 770, ["$", "GENERAL LIABILITY"])
    d["prior_carrier_auto"] = region_text(w, 237, 706, 356, 770, ["$", "AUTOMOBILE"])
    d["prior_carrier_property"] = region_text(w, 356, 706, 475, 770, ["$", "PROPERTY"])

    return {k: v for k, v in d.items() if v is not None}


def extract_page4(page):
    """ACORD 125 Page 4 of 4: Prior Carrier (cont'd), Loss History, Signature"""
    w = get_words(page)
    d = {"form": "ACORD 125", "section": "Prior Carrier / Loss History / Signature (Page 4 of 4)"}

    d["agency_customer_id"] = region_text(w, 410, 28, 470, 45)

    # Loss History
    d["total_losses"] = region_text(w, 515, 200, 612, 214, ["TOTAL LOSSES:", "$"])
    d["loss_history_years"] = region_text(w, 64, 200, 92, 214, ["FOR THE LAST", "YEARS"])

    return {k: v for k, v in d.items() if v is not None}


def extract_page5_acord823(page):
    """ACORD 823: Additional Premises Information Schedule"""
    w = get_words(page)
    d = {"form": "ACORD 823", "section": "Additional Premises Information Schedule"}

    d["agency_customer_id"] = region_text(w, 410, 29, 470, 46)
    d["agency"] = region_text(w, 18, 78, 275, 92, ["AGENCY"])
    d["carrier"] = region_text(w, 275, 78, 540, 92, ["CARRIER"])
    d["effective_date"] = region_text(w, 218, 100, 278, 118, ["EFFECTIVE DATE"])
    d["named_insured"] = region_text(w, 275, 100, 530, 118, ["NAMED INSURED(S)"])

    # First premises block (has data)
    p = {}
    p["loc_num"] = region_text(w, 26, 138, 42, 155)
    p["bld_num"] = region_text(w, 26, 162, 42, 178)
    p["street"] = region_text(w, 44, 132, 260, 152, ["STREET", "LOC #"])
    p["city"] = region_text(w, 62, 150, 200, 168, ["CITY:"])
    p["state"] = region_text(w, 230, 150, 265, 168, ["STATE:"])
    p["county"] = region_text(w, 46, 162, 200, 180, ["COUNTY:"])
    p["zip"] = region_text(w, 198, 162, 265, 180, ["ZIP:"])
    d["premises_5"] = {k: v for k, v in p.items() if v is not None}

    return {k: v for k, v in d.items() if v is not None}


def extract_property_section(page, page_num):
    """ACORD 140: Property Section (Page 1 of 3 for each building)"""
    w = get_words(page)
    d = {"form": "ACORD 140", "section": f"Property Section (Page {page_num})"}

    d["agency_customer_id"] = region_text(w, 410, 29, 470, 46)
    d["date"] = region_text(w, 520, 58, 580, 75)
    d["agency_name"] = region_text(w, 15, 82, 300, 100, ["AGENCY NAME"])
    d["carrier"] = region_text(w, 300, 82, 540, 100, ["CARRIER"])
    d["effective_date"] = region_text(w, 250, 105, 310, 122)
    d["named_insured"] = region_text(w, 305, 105, 530, 122, ["NAMED INSURED(S)"])

    # Premises/Building - these come as "PREMISES #:0" concatenated
    prem_raw = region_text(w, 135, 168, 210, 186)
    if prem_raw and ":" in prem_raw:
        d["premises_num"] = prem_raw.split(":")[-1].strip()
    else:
        d["premises_num"] = prem_raw
    d["building_num"] = region_text(w, 175, 180, 210, 198)
    street_raw = region_text(w, 208, 168, 530, 186)
    if street_raw and ":" in street_raw:
        d["street_address"] = street_raw.split(":", 1)[1].strip()
    else:
        d["street_address"] = street_raw
    bldg_raw = region_text(w, 208, 180, 530, 198)
    if bldg_raw and ":" in bldg_raw:
        d["bldg_description"] = bldg_raw.split(":", 1)[1].strip()
    else:
        d["bldg_description"] = bldg_raw

    # Coverage items - from actual coords:
    # Building@206, R@239, Special Including theft@261, 12591761@162, 5000@376
    # BPP@230, R@239, Special Including theft@261, 1413213@167, 5000@376
    # BI/EE@254, L@239, Special Including theft@261, 72 Hours@388-427
    coverages = []
    cov_rows = [
        (202, 228),
        (226, 252),
        (250, 276),
    ]
    for y_start, y_end in cov_rows:
        subj = region_text(w, 15, y_start, 155, y_end)
        amt = region_text(w, 155, y_start + 5, 212, y_end + 5)
        valuation = region_text(w, 235, y_start, 258, y_end)
        cause = region_text(w, 258, y_start, 370, y_end)
        ded = region_text(w, 370, y_start, 432, y_end)
        if subj and "SUBJECT OF INSURANCE" not in subj:
            cov = {"subject": subj}
            if amt: cov["amount"] = amt
            if valuation: cov["valuation"] = valuation
            if cause: cov["causes_of_loss"] = cause
            if ded: cov["deductible"] = ded
            coverages.append(cov)
    d["coverages"] = coverages if coverages else None

    # Construction info — pages 9,12 have this at y~476 instead of the details page
    d["construction_type"] = region_text(w, 15, 472, 145, 492)
    d["num_stories"] = region_text(w, 425, 472, 455, 492)
    d["year_built"] = region_text(w, 490, 472, 525, 492)
    d["total_area"] = region_text(w, 525, 472, 570, 492)
    d["roofing_year"] = region_text(w, 70, 510, 120, 530)
    d["wiring_updated"] = checked_box(w, "WIRING")

    # Additional Interest
    d["additional_interest_name"] = region_text(w, 122, 688, 340, 730)
    interest_type = []
    if checked_box(w, "LOSS PAYEE"): interest_type.append("Loss Payee")
    if checked_box(w, "MORTGAGEE"): interest_type.append("Mortgagee")
    d["additional_interest_type"] = interest_type if interest_type else None
    d["additional_interest_location"] = region_text(w, 484, 688, 500, 706)
    d["additional_interest_building"] = region_text(w, 554, 688, 570, 706)

    return {k: v for k, v in d.items() if v is not None}


def extract_property_details(page, page_num):
    """ACORD 140 Additional Premises Details (Page 2 of 3 for each building)"""
    w = get_words(page)
    d = {"form": "ACORD 140", "section": f"Property Details (Page {page_num})"}

    d["agency_customer_id"] = region_text(w, 410, 29, 470, 46)
    d["premises_num"] = region_text(w, 175, 47, 195, 64)
    d["building_num"] = region_text(w, 175, 60, 195, 77)
    # These are concatenated in the PDF like "STREET ADDRESS:1800 N Stone Ave..."
    street_raw = region_text(w, 208, 47, 530, 64)
    if street_raw and ":" in street_raw:
        d["street_address"] = street_raw.split(":", 1)[1].strip()
    else:
        d["street_address"] = street_raw
    bldg_raw = region_text(w, 208, 60, 530, 77)
    if bldg_raw and ":" in bldg_raw:
        d["bldg_description"] = bldg_raw.split(":", 1)[1].strip()
    else:
        d["bldg_description"] = bldg_raw

    # Construction info (same coords as property section but shifted for page 2)
    # From coords: Frame@356, stories=3@429, yr_built=2003@496, total_area=21836@528
    d["construction_type"] = region_text(w, 15, 352, 145, 370)
    d["num_stories"] = region_text(w, 425, 352, 455, 370)
    d["year_built"] = region_text(w, 490, 352, 525, 370)
    d["total_area"] = region_text(w, 525, 352, 570, 370)

    # Roofing year (from coords: "2025" at x=78, y=395)
    d["roofing_year"] = region_text(w, 70, 390, 120, 410)

    # Wiring update checkbox - X at (22, 393) near "WIRING, YR:"
    d["wiring_updated"] = checked_box(w, "WIRING")

    # Additional interest on this page
    d["additional_interest_name"] = region_text(w, 122, 570, 340, 630)

    return {k: v for k, v in d.items() if v is not None}


def extract_cgl_section(page, page_num):
    """ACORD 126: Commercial General Liability Section"""
    w = get_words(page)
    d = {"form": "ACORD 126", "section": f"Commercial General Liability (Page {page_num})"}

    d["agency_customer_id"] = region_text(w, 410, 28, 470, 45)
    d["date"] = region_text(w, 520, 58, 580, 75)
    d["agency"] = region_text(w, 15, 82, 300, 95, ["AGENCY"])
    d["carrier"] = region_text(w, 300, 82, 540, 100, ["CARRIER"])
    d["effective_date"] = region_text(w, 250, 105, 310, 122)
    d["named_insured"] = region_text(w, 305, 105, 530, 122, ["APPLICANT / FIRST NAMED INSURED"])

    # Coverage type
    d["cgl_coverage"] = True  # X marked at (22,165)
    d["coverage_type_occurrence"] = checked_box(w, "OCCURRENCE")
    d["coverage_type_claims_made"] = checked_box(w, "CLAIMS MADE")

    # Limits from actual coords
    d["general_aggregate"] = region_text(w, 445, 163, 498, 180)
    d["products_completed_ops_aggregate"] = region_text(w, 445, 196, 498, 214)
    d["personal_advertising_injury"] = region_text(w, 445, 213, 498, 228)
    d["each_occurrence"] = region_text(w, 445, 220, 498, 240)
    d["damage_to_rented_premises"] = region_text(w, 445, 232, 498, 252)
    d["medical_expense"] = region_text(w, 445, 244, 498, 262)

    # Limit applies per
    d["limit_applies_per_policy"] = checked_box(w, "POLICY")
    d["limit_applies_per_location"] = checked_box(w, "LOCATION")

    # Schedule of Hazards - classifications
    # From coords: APARTMENT BUILDINGS - STUDENT HOUSING @69,381-386
    # code 60010 @194,386; basis U @252,386; exposure 68 @319,386
    classifications = []
    class_rows = [(376, 400), (400, 424)]
    for y_start, y_end in class_rows:
        desc = region_text(w, 60, y_start, 192, y_end)
        code = region_text(w, 188, y_start, 225, y_end)
        basis = region_text(w, 248, y_start, 265, y_end)
        exposure = region_text(w, 310, y_start, 340, y_end)
        if desc:
            cls = {"description": desc}
            if code: cls["class_code"] = code
            if basis: cls["premium_basis"] = basis
            if exposure: cls["exposure"] = exposure
            classifications.append(cls)
    d["classifications"] = classifications if classifications else None

    # Other coverages note
    d["other_coverages_note"] = region_text(w, 15, 290, 530, 310)

    return {k: v for k, v in d.items() if v is not None}


def extract_umbrella_section(page, page_num):
    """ACORD 131: Umbrella / Excess Section"""
    w = get_words(page)
    d = {"form": "ACORD 131", "section": f"Umbrella/Excess Section (Page {page_num})"}

    d["agency_customer_id"] = region_text(w, 374, 30, 435, 48)
    d["date"] = region_text(w, 520, 60, 580, 78)
    d["agency"] = region_text(w, 15, 102, 300, 120, ["AGENCY"])
    d["carrier"] = region_text(w, 300, 102, 540, 120, ["CARRIER"])
    d["effective_date"] = region_text(w, 250, 126, 310, 144)
    d["named_insured"] = region_text(w, 305, 126, 530, 144, ["NAMED INSURED(S)"])

    # Transaction type - X NEW, X UMBRELLA, X OCCURRENCE
    d["transaction_new"] = checked_box(w, "NEW")
    d["transaction_renewal"] = checked_box(w, "RENEWAL")
    d["type_umbrella"] = checked_box(w, "UMBRELLA")
    d["type_excess"] = checked_box(w, "EXCESS")
    d["type_occurrence"] = checked_box(w, "OCCURRENCE")
    d["type_claims_made"] = checked_box(w, "CLAIMS MADE")

    # Limits from coords: 5,000,000 @364,167 EA OCC; 5,000,000 @333,179 Aggregate; 0 @588,167 retained
    d["limit_each_occurrence"] = region_text(w, 358, 162, 410, 180)
    d["limit_aggregate"] = region_text(w, 326, 174, 380, 192)
    d["retained_limit"] = region_text(w, 580, 162, 600, 180)

    # Underlying GL info
    # TBD@70,587; each occ $1M @453,587; gen agg $2M @453,599
    d["underlying_gl_carrier"] = region_text(w, 60, 582, 200, 600)
    d["underlying_gl_each_occurrence"] = region_text(w, 445, 582, 498, 600)
    d["underlying_gl_general_aggregate"] = region_text(w, 445, 594, 498, 612)
    d["underlying_gl_products_aggregate"] = region_text(w, 445, 606, 498, 624)
    d["underlying_gl_personal_injury"] = region_text(w, 445, 618, 498, 636)
    d["underlying_gl_damage_rented"] = region_text(w, 445, 630, 498, 648)
    d["underlying_gl_medical"] = region_text(w, 445, 642, 498, 660)

    # GL policy dates
    d["underlying_gl_eff_date"] = region_text(w, 220, 618, 280, 636)
    d["underlying_gl_exp_date"] = region_text(w, 285, 618, 345, 636)
    d["underlying_gl_occurrence"] = checked_box(w, "OCCUR")

    return {k: v for k, v in d.items() if v is not None}


def extract_additional_coverages(page, page_num):
    """Additional Coverages Overflow page"""
    w = get_words(page)
    d = {"form": "Overflow", "section": f"Additional Coverages Overflow (Page {page_num})"}

    d["agency_customer_id"] = region_text(w, 310, 35, 375, 52)

    # These pages have structured "* Code XXX; Description YYY" lines
    # From coords: "* Code XTEND; Description Property Enhancement Endorsement;" @26,55
    #              "* Code EV; Description Electric Vehicle Charging Stations;" @26,113
    coverages = []
    skip = {"ADDITIONAL COVERAGES OVERFLOW", "LBAKER", "APPLIED 98 (2001/01)"}
    for word in w:
        text = word["text"].strip()
        if text.startswith("* Code"):
            coverages.append(text)
        elif text.startswith("*") and "Code" not in text and "Description" in text:
            coverages.append(text)

    # Fallback: get all non-header content
    if not coverages:
        lines = []
        if w:
            current_line = [w[0]]
            for word in w[1:]:
                if abs(word["top"] - current_line[0]["top"]) < 4:
                    current_line.append(word)
                else:
                    current_line.sort(key=lambda x: x["x0"])
                    text = " ".join(ww["text"] for ww in current_line).strip()
                    if text and text not in skip and "PAGE" not in text and "OF" not in text:
                        lines.append(text)
                    current_line = [word]
            if current_line:
                current_line.sort(key=lambda x: x["x0"])
                text = " ".join(ww["text"] for ww in current_line).strip()
                if text and text not in skip:
                    lines.append(text)
        d["content_lines"] = lines if lines else None
    else:
        d["additional_coverages"] = coverages

    return {k: v for k, v in d.items() if v is not None}


def extract_signature_page(page, page_num):
    """Signature page (mostly legal disclaimers)"""
    w = get_words(page)
    d = {"form": "ACORD 140 Signature", "section": f"Signature (Page {page_num})"}
    d["agency_customer_id"] = region_text(w, 410, 28, 470, 45)
    # These are mostly boilerplate legal text, not much data to extract
    d["note"] = "Legal disclaimer / signature page - no fillable data fields"
    return d


def extract_contractors(page, page_num):
    """Contractors section"""
    w = get_words(page)
    d = {"form": "ACORD 126 Contractors", "section": f"Contractors (Page {page_num})"}

    d["agency_customer_id"] = region_text(w, 410, 28, 470, 45)

    tables = page.extract_tables()
    d["tables"] = []
    for t in tables:
        clean = [[(c.strip() if c else "") for c in row] for row in t]
        clean = [r for r in clean if any(r)]
        if clean:
            d["tables"].append(clean)

    return {k: v for k, v in d.items() if v is not None}


def extract_additional_interest(page, page_num):
    """Additional Interest / Certificate Recipient"""
    w = get_words(page)
    d = {"form": "ACORD 126 Add'l Interest", "section": f"Additional Interest (Page {page_num})"}

    d["agency_customer_id"] = region_text(w, 410, 28, 470, 45)

    tables = page.extract_tables()
    d["tables"] = []
    for t in tables:
        clean = [[(c.strip() if c else "") for c in row] for row in t]
        clean = [r for r in clean if any(r)]
        if clean:
            d["tables"].append(clean)

    return {k: v for k, v in d.items() if v is not None}


def extract_general_info_continued(page, page_num):
    """General Information Continued"""
    w = get_words(page)
    d = {"form": "ACORD 126 Gen Info", "section": f"General Info Continued (Page {page_num})"}

    d["agency_customer_id"] = region_text(w, 410, 28, 470, 45)

    tables = page.extract_tables()
    d["tables"] = []
    for t in tables:
        clean = [[(c.strip() if c else "") for c in row] for row in t]
        clean = [r for r in clean if any(r)]
        if clean:
            d["tables"].append(clean)

    return {k: v for k, v in d.items() if v is not None}


def extract_underlying_insurance(page, page_num):
    """Underlying Insurance"""
    w = get_words(page)
    d = {"form": "ACORD 131 Underlying", "section": f"Underlying Insurance (Page {page_num})"}

    d["agency_customer_id"] = region_text(w, 410, 28, 470, 45)

    tables = page.extract_tables()
    d["tables"] = []
    for t in tables:
        clean = [[(c.strip() if c else "") for c in row] for row in t]
        clean = [r for r in clean if any(r)]
        if clean:
            d["tables"].append(clean)

    return {k: v for k, v in d.items() if v is not None}


def extract_additional_exposures(page, page_num):
    """Additional Exposures"""
    w = get_words(page)
    d = {"form": "ACORD 131 Exposures", "section": f"Additional Exposures (Page {page_num})"}

    d["agency_customer_id"] = region_text(w, 410, 28, 470, 45)

    tables = page.extract_tables()
    d["tables"] = []
    for t in tables:
        clean = [[(c.strip() if c else "") for c in row] for row in t]
        clean = [r for r in clean if any(r)]
        if clean:
            d["tables"].append(clean)

    return {k: v for k, v in d.items() if v is not None}


def extract_remarks(page, page_num):
    """Remarks page"""
    w = get_words(page)
    d = {"form": "ACORD 101 Remarks", "section": f"Remarks (Page {page_num})"}

    d["agency_customer_id"] = region_text(w, 410, 28, 470, 45)

    # Extract all non-label text as remarks content
    lines = []
    if w:
        current_line = [w[0]]
        for word in w[1:]:
            if abs(word["top"] - current_line[0]["top"]) < 4:
                current_line.append(word)
            else:
                current_line.sort(key=lambda x: x["x0"])
                text = " ".join(ww["text"] for ww in current_line).strip()
                if text:
                    lines.append(text)
                current_line = [word]
        if current_line:
            current_line.sort(key=lambda x: x["x0"])
            lines.append(" ".join(ww["text"] for ww in current_line).strip())
    d["remarks_lines"] = lines if lines else None

    return {k: v for k, v in d.items() if v is not None}


# ── Main extraction orchestrator ────────────────────────────────────────────

PAGE_HANDLERS = {
    1: extract_page1,
    2: extract_page2,
    3: extract_page3,
    4: extract_page4,
    5: extract_page5_acord823,
    6: lambda p: extract_property_section(p, 6),
    7: lambda p: extract_property_details(p, 7),
    8: lambda p: extract_signature_page(p, 8),
    9: lambda p: extract_property_section(p, 9),
    10: lambda p: extract_property_details(p, 10),
    11: lambda p: extract_signature_page(p, 11),
    12: lambda p: extract_property_section(p, 12),
    13: lambda p: extract_property_details(p, 13),
    14: lambda p: extract_signature_page(p, 14),
    15: lambda p: extract_additional_coverages(p, 15),
    16: lambda p: extract_cgl_section(p, 16),
    17: lambda p: extract_contractors(p, 17),
    18: lambda p: extract_additional_interest(p, 18),
    19: lambda p: extract_general_info_continued(p, 19),
    20: lambda p: extract_additional_coverages(p, 20),
    21: lambda p: extract_umbrella_section(p, 21),
    22: lambda p: extract_underlying_insurance(p, 22),
    23: lambda p: extract_additional_exposures(p, 23),
    24: lambda p: extract_additional_exposures(p, 24),
    25: lambda p: extract_remarks(p, 25),
}


def extract_all(pdf_path: str) -> dict:
    """Extract all fields from all pages of the ACORD PDF."""
    pdf = pdfplumber.open(pdf_path)
    result = {
        "metadata": {
            "source_file": str(pdf_path),
            "total_pages": len(pdf.pages),
            "extractor": "acord_coordinate_extractor_v1",
        },
        "pages": {},
    }

    for pg_num, page in enumerate(pdf.pages):
        pg = pg_num + 1
        handler = PAGE_HANDLERS.get(pg)
        if handler:
            result["pages"][f"page_{pg}"] = handler(page)
        else:
            # Fallback generic
            result["pages"][f"page_{pg}"] = {"section": f"Unknown (Page {pg})"}

    pdf.close()
    return result


if __name__ == "__main__":
    pdf_path = Path(__file__).parent / "Acord App (1800 North Stone LLC) 2026.pdf"
    data = extract_all(str(pdf_path))

    output = Path(__file__).parent / "acord_extracted_fields.json"
    with open(output, "w") as f:
        json.dump(data, f, indent=2)

    # Print summary
    print("=== EXTRACTION COMPLETE ===\n")
    for key, page_data in data["pages"].items():
        section = page_data.get("section", "Unknown")
        fields = [k for k, v in page_data.items() if v is not None and k not in ("form", "section", "tables", "note")]
        print(f"{key}: {section} ({len(fields)} fields)")

    print(f"\n=== PAGE 1 DETAIL ===\n")
    p1 = data["pages"]["page_1"]
    for k, v in p1.items():
        if k not in ("form", "section"):
            print(f"  {k}: {v}")

    print(f"\n=== PAGE 2 PREMISES ===\n")
    p2 = data["pages"]["page_2"]
    for p in p2.get("premises", []):
        print(f"  {p}")

    print(f"\n=== PAGE 5 (ACORD 823) ===\n")
    p5 = data["pages"]["page_5"]
    for k, v in p5.items():
        if k not in ("form", "section"):
            print(f"  {k}: {v}")

    print(f"\n=== PAGE 6 (PROPERTY) ===\n")
    p6 = data["pages"]["page_6"]
    for k, v in p6.items():
        if k not in ("form", "section", "tables"):
            print(f"  {k}: {v}")

    print(f"\nSaved to: {output}")
