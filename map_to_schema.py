"""
Map the per-document extractions in input_extracted/ to the target
insurance-submission schema (provided by user).

Sources:
  ACORD app merged JSON  → Insured, Agent, PolicyInfo, GeneralLiability
  SOV Excel              → Locations + Buildings (5 buildings at 1 loc)
  Farmers LR             → LossRuns + Claims
  email.docx             → Submission metadata (date received, broker)
  1800_North_Stone.docx  → DescriptionOfOperations (narrative)
  Community Map          → Attachment only (map image)

Output: input_extracted/submission_mapped.json
"""
import json
import re
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent
EXTRACTED_DIR = REPO / "input_extracted"
INPUT_DIR = REPO / "input_docs" / "Input"


def _load(name: str) -> dict | None:
    p = EXTRACTED_DIR / name
    if not p.exists():
        return None
    return json.load(open(p))


def _bbox_field(acord_data: dict, page_num: int, field_name: str):
    """Look up a /Tx field's extracted value from the merged ACORD JSON."""
    page = acord_data.get("pages", {}).get(f"page_{page_num}", {})
    for k, f in page.get("fields", {}).items():
        if k == field_name and f.get("source", "").startswith("bbox"):
            return f.get("value")
    return None


def _checkbox(acord_data: dict, page_num: int, field_name: str) -> bool:
    page = acord_data.get("pages", {}).get(f"page_{page_num}", {})
    f = page.get("fields", {}).get(field_name)
    if not f or f.get("type") != "checkbox":
        return False
    return f.get("value") is True


def _entity_type_from_acord(acord_data: dict) -> str | None:
    """Read the /Btn LegalEntity indicators on p1, return matching enum."""
    page = acord_data.get("pages", {}).get("page_1", {})
    fields = page.get("fields", {})
    mapping = {
        "Individual": "NamedInsured_LegalEntity_IndividualIndicator_A",
        "Corporation": "NamedInsured_LegalEntity_CorporationIndicator_A",
        "Limited Liability Company":
            "NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A",
        "Partnership": "NamedInsured_LegalEntity_PartnershipIndicator_A",
        "Joint Venture": "NamedInsured_LegalEntity_JointVentureIndicator_A",
    }
    for label, base_name in mapping.items():
        for k, f in fields.items():
            if k.startswith(base_name) and f.get("value") is True:
                return label
    return "Other"


def _safe_int(v):
    try: return int(float(str(v).replace(",", "")))
    except (ValueError, TypeError): return None


def _safe_float(v):
    try: return float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError): return None


def _parse_date(s):
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%d/%m/%Y", "%m-%d-%Y"):
        try:
            d = datetime.strptime(s, fmt)
            return d.strftime("%Y-%m-%d")
        except Exception:
            pass
    return s


# ── ACORD merged → Insured + Agent + PolicyInfo ──

def _pick(p1: dict, *names) -> str | None:
    """Get the first non-empty extracted value matching any of the given keys.
       Pulls value out of the {value, source, ...} field-record structure."""
    for n in names:
        f = p1.get(n)
        if isinstance(f, dict):
            v = f.get("value")
            if v not in (None, "", False):
                return v
    return None


def _looks_like_concat_with_address(v):
    """Heuristic: bbox value bled into the address (e.g.
       '1800 North Stone LLC 1800 N Stone Ave')."""
    if not isinstance(v, str):
        return False
    return bool(re.search(r"\b\d+\s+[NSEW]?\s*\w+\s+(Ave|Street|St|Rd|Road|Blvd|Drive|Dr|Lane|Ln|Way|Circle|Cir|Suite|Ste)\b",
                          v, re.IGNORECASE))


def map_acord(acord) -> dict:
    if not acord:
        return {}
    insured = {}
    agent = {}
    policy = {}

    p1 = acord["pages"].get("page_1", {}).get("fields", {})

    # Insured.Name — prefer VLM, fall back to bbox if not bled
    bbox_name = _pick(p1, "NamedInsured_FullName_A[0]", "NamedInsured_FullName_B[0]")
    vlm_name = _pick(p1, "vlm_APPLICANT_INFORMATION_0_full_name",
                       "vlm_NamedInsured_FullName_A")
    if vlm_name:
        insured["Name"] = vlm_name
    elif bbox_name and not _looks_like_concat_with_address(bbox_name):
        insured["Name"] = bbox_name
    elif bbox_name:
        # Strip the bled address pattern off the end
        m = re.search(r"^(.*?)\s+\d+\s+[NSEW]?\s*\w+\s+(Ave|Street|St|Rd)",
                      bbox_name, re.IGNORECASE)
        insured["Name"] = m.group(1).strip() if m else bbox_name

    insured["EntityType"] = _entity_type_from_acord(acord)
    insured["NAICSCode"] = _pick(p1, "NamedInsured_NAICSCode_A[0]")
    insured["SICCode"] = _pick(p1, "NamedInsured_SICCode_A[0]")
    insured["FEIN"] = _pick(p1, "NamedInsured_FEINOrSocSecNumberIdentifier_A[0]")
    insured["BusinessPhone"] = _pick(p1,
        "NamedInsured_BusinessPhoneNumber_A[0]",
        "NamedInsured_Primary_PhoneNumber_A[0]",
        "NamedInsured_BusinessNumberContactPoint_A[0]",
        "vlm_APPLICANT_INFORMATION_0_business_phone")
    insured["Website"] = _pick(p1,
        "NamedInsured_WebsiteAddressUrl_A[0]",
        "NamedInsured_Primary_WebsiteAddress_A[0]",
        "vlm_APPLICANT_INFORMATION_0_website_address")
    insured["Addresses"] = []
    addr1 = {
        "Type": "Mailing",
        "Street": _pick(p1, "vlm_APPLICANT_INFORMATION_0_address_line1",
                            "NamedInsured_AddressLine_StreetName_A[0]"),
        "City": _pick(p1, "NamedInsured_AddressLine_CityName_A[0]"),
        "State": _pick(p1, "NamedInsured_AddressLine_StateOrProvinceCode_A[0]"),
        "ZipCode": _pick(p1, "NamedInsured_AddressLine_PostalCode_A[0]"),
    }
    # Try to parse "Tucson, AZ 85705-5761" if City/State/Zip aren't separately filled
    if not addr1["City"]:
        line_csz = _pick(p1, "NamedInsured_MailingAddress_LineOne_A[0]",
                              "vlm_APPLICANT_INFORMATION_0_city_state_zip")
        if line_csz:
            m = re.match(r"([A-Za-z\s.]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)", line_csz)
            if m:
                addr1["City"] = m.group(1).strip()
                addr1["State"] = m.group(2)
                addr1["ZipCode"] = m.group(3)
    if any(v for v in addr1.values() if v and v != "Mailing"):
        insured["Addresses"].append({k: v for k, v in addr1.items() if v})

    # Agent / Producer — same VLM-prefer pattern
    bbox_agent = _pick(p1, "Producer_FullName_A[0]")
    vlm_agent = _pick(p1, "vlm_HEADER_agency_name")
    if vlm_agent:
        agent["Name"] = vlm_agent
    elif bbox_agent and not _looks_like_concat_with_address(bbox_agent):
        agent["Name"] = bbox_agent
    elif bbox_agent:
        m = re.search(r"^(.*?)\s+\d+\s+[NSEW]?\s*\w+\s+(Ave|Street|St|Rd)",
                      bbox_agent, re.IGNORECASE)
        agent["Name"] = m.group(1).strip() if m else bbox_agent

    agent["NationalProducerNumber"] = _pick(p1,
        "Insurer_ProducerIdentifier_A[0]",
        "Producer_NationalProducerNumber_A[0]")
    agent["Addresses"] = []
    a_addr = {
        "Type": "Mailing",
        "Street": _pick(p1, "vlm_HEADER_agency_address",
                            "Producer_MailingAddress_LineOne_A[0]"),
        "Street2": _pick(p1, "Producer_MailingAddress_LineTwo_A[0]"),
        "City": _pick(p1, "Producer_MailingAddress_CityName_A[0]"),
        "State": _pick(p1, "Producer_MailingAddress_StateOrProvinceCode_A[0]"),
        "ZipCode": _pick(p1, "Producer_MailingAddress_PostalCode_A[0]"),
    }
    # vlm_HEADER_agency_city_state_zip parse
    if not a_addr["City"]:
        line_csz = _pick(p1, "vlm_HEADER_agency_city_state_zip")
        if line_csz:
            m = re.match(r"([A-Za-z\s.]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)", line_csz)
            if m:
                a_addr["City"] = m.group(1).strip()
                a_addr["State"] = m.group(2)
                a_addr["ZipCode"] = m.group(3)
    if any(v for v in a_addr.values() if v and v != "Mailing"):
        agent["Addresses"].append({k: v for k, v in a_addr.items() if v})

    agent["Contacts"] = []
    contact = {
        "Type": "Producer",
        "Name": _pick(p1, "Producer_ContactPerson_FullName_A[0]",
                          "vlm_HEADER_contact_name"),
        "Phone": _pick(p1, "Producer_ContactPerson_PhoneNumber_A[0]",
                            "vlm_HEADER_contact_phone"),
        "Email": _pick(p1, "Producer_ContactPerson_EmailAddress_A[0]",
                            "vlm_HEADER_contact_email"),
    }
    if any(v for v in contact.values() if v and v != "Producer"):
        agent["Contacts"].append({k: v for k, v in contact.items() if v})

    # PolicyInfo
    policy["EffectiveDate"] = _parse_date(
        p1.get("Policy_EffectiveDate_A[0]", {}).get("value"))
    policy["ExpirationDate"] = _parse_date(
        p1.get("Policy_ExpirationDate_A[0]", {}).get("value"))
    policy["PriorPolicyNumber"] = p1.get(
        "Policy_PolicyNumberIdentifier_A[0]", {}).get("value")

    # LOB from p1 LineOfBusinessIndicator checkboxes
    lobs = []
    for k, f in p1.items():
        if "LineOfBusinessIndicator" in k or "Coverage" in k and "_A" in k:
            if f.get("value") is True:
                # naive extraction
                if "GeneralLiability" in k or "CommercialGeneralLiability" in k:
                    if "General Liability" not in lobs:
                        lobs.append("General Liability")
                elif "Property" in k or "CommercialProperty" in k:
                    if "Property" not in lobs:
                        lobs.append("Property")
    if not lobs:
        # Default per the form
        lobs = ["General Liability", "Property"]
    policy["LOB"] = lobs

    return {"insured": insured, "agent": agent, "policy": policy}


# ── SOV → Locations + Buildings ──

def map_sov(sov) -> list:
    """Return list of Locations with embedded Buildings."""
    if not sov or "sheets" not in sov:
        return []
    sheet = sov["sheets"][0]
    grid = sheet.get("raw_grid", [])

    # Find header row by signature: contains "Loc" and "Building"
    header_idx = None
    for i, row in enumerate(grid):
        joined = " ".join(str(c) for c in row).lower()
        if "loc" in joined and ("building #" in joined or "building#" in joined):
            header_idx = i; break
    if header_idx is None:
        return []
    header = [str(c).strip() for c in grid[header_idx]]
    # Index column → header label
    idx = {h: i for i, h in enumerate(header) if h}

    locs = {}  # loc_num → location dict
    for row in grid[header_idx + 1:]:
        if not any(str(c).strip() for c in row):
            continue
        loc_num_raw = str(row[idx.get("Loc.#", 0)]).strip() if "Loc.#" in idx else ""
        if not loc_num_raw:
            continue
        loc_num = _safe_int(loc_num_raw)
        if loc_num is None:
            continue

        b = {}
        b["BuildingNumber"] = _safe_int(row[idx["Building #"]]) if "Building #" in idx else None
        b["YearOfConstruction"] = _safe_int(row[idx["Year Built"]]) if "Year Built" in idx else None
        b["ConstructionType"] = (row[idx["Construction Type"]] or None) if "Construction Type" in idx else None
        b["RoofType"] = (row[idx["Type of Roof"]] or None) if "Type of Roof" in idx else None
        b["TotalSqFt"] = _safe_float(row[idx["# Sq. Ft. Bldg"]]) if "# Sq. Ft. Bldg" in idx else None
        b["NoOfStories"] = _safe_int(row[idx["# of stories"]]) if "# of stories" in idx else None
        b["TotalUnits"] = _safe_int(row[idx["# Hab Units"]]) if "# Hab Units" in idx else None
        b["OccupancyType"] = (row[idx["Occupancy"]] or None) if "Occupancy" in idx else None
        # Sprinklered: 100% means fully sprinklered
        spr = _safe_float(row[idx["Sprinklered %"]]) if "Sprinklered %" in idx else None
        if spr is not None:
            b["FullySprinklered"] = spr >= 100
        # Limits
        rcv = _safe_float(row[idx["Building RCV"]]) if "Building RCV" in idx else None
        bpp = _safe_float(row[idx["BPP"]]) if "BPP" in idx else None
        bi = _safe_float(row[idx["Loss of Rents"]]) if "Loss of Rents" in idx else None
        if rcv is not None:
            b["Building"] = {"BuildingCoverageFlag": True, "BuildingLimit": rcv,
                             "Building100RcValue": rcv}
        if bpp is not None and bpp > 0:
            b["Bpp"] = {"BppCoverageFlag": True, "BppLimit": bpp}
        if bi is not None and bi > 0:
            b["BusinessIncomeLimit"] = bi

        # Drop None values
        b = {k: v for k, v in b.items() if v is not None}

        # Address (location-level, but stored on first building for now)
        zip_raw = row[idx["Zip"]] if "Zip" in idx else None
        addr = {
            "Type": "Physical",
            "Street": str(row[idx["Street Address"]]).strip() if "Street Address" in idx and row[idx["Street Address"]] else None,
            "City": str(row[idx["City"]]).strip() if "City" in idx and row[idx["City"]] else None,
            "State": str(row[idx["State"]]).strip() if "State" in idx and row[idx["State"]] else None,
            "ZipCode": (str(int(float(str(zip_raw))))
                         if zip_raw not in (None, "") else None),
        }
        addr = {k: v for k, v in addr.items() if v}

        if loc_num not in locs:
            locs[loc_num] = {
                "LocationNumber": loc_num,
                "LocationName": f"Location {loc_num}",
                "Address": addr if addr else None,
                "Buildings": [],
            }
        locs[loc_num]["Buildings"].append(b)

    return [locs[k] for k in sorted(locs)]


# ── Farmers LR → LossRuns ──

def map_loss_run(lr) -> list:
    if not lr:
        return []
    pdf = lr.get("pdfplumber") or {}
    pages = pdf.get("pages") or []

    # Pull header info from VLM extraction page 1
    vlm_pages = lr.get("vlm_pages") or []
    h = (vlm_pages[0] or {}).get("data", {}).get("header", {}) if vlm_pages else {}

    # Build a single LossRun entry covering this carrier
    entry = {
        "Carrier": h.get("company") or h.get("carrier") or h.get("company/carrier"),
        "PolicyNumber": h.get("policy_number"),
        "EvaluationDate": _parse_date(h.get("valuation_date")),
        "LOB": "General Liability",  # Farmers LR is for GL
        "Claims": [],
    }

    # Claims from pdfplumber-parsed rows OR from VLM detail rows
    parsed = lr.get("pdfplumber_parsed_claims") or []
    if parsed:
        for c in parsed:
            entry["Claims"].append({
                "ClaimNumber": c.get("claim_no") or c.get("claim_number"),
                "ClaimStatus": (c.get("status") or "").title() or None,
                "LossDate": _parse_date(c.get("loss_date") or c.get("date_of_loss")),
                "Description": c.get("cause_of_loss") or c.get("description"),
                "AmountPaid": _safe_float(c.get("total_paid") or c.get("paid")),
                "ReserveAmount": _safe_float(c.get("total_reserves") or c.get("reserves")),
                "TotalIncurred": _safe_float(c.get("total_incurred") or c.get("incurred")),
            })
    else:
        # Fall back to VLM claims
        for p in vlm_pages:
            data = p.get("data", {}) or {}
            for c in (data.get("claims") or data.get("detail") or []):
                if not isinstance(c, dict):
                    continue
                entry["Claims"].append({
                    "ClaimNumber": c.get("claim_number"),
                    "ClaimStatus": (c.get("status") or "").title() or None,
                    "LossDate": _parse_date(c.get("date_of_loss")),
                    "Description": c.get("type_cause") or c.get("description"),
                    "AmountPaid": _safe_float(c.get("amount_paid")),
                    "ReserveAmount": _safe_float(c.get("amount_reserved")),
                    "TotalIncurred": _safe_float(c.get("net_incurred")),
                })

    # Drop None values from each claim
    entry["Claims"] = [
        {k: v for k, v in c.items() if v is not None} for c in entry["Claims"]
    ]
    if not entry["Claims"]:
        entry["NoKnownLossesLast5Years"] = True
    entry = {k: v for k, v in entry.items() if v is not None}
    return [entry]


# ── email.docx → Submission metadata ──

def map_email(email) -> dict:
    if not email:
        return {}
    sub = {}
    paragraphs = email.get("paragraphs", [])
    if not paragraphs:
        return {}
    # First paragraph often is the subject line
    subject = paragraphs[0]["text"] if paragraphs else ""
    sub["Notes"] = subject

    # Parse "TARGET: $55K" / "TARGET: $XX" from subject
    target_match = re.search(r"TARGET[:\s]*\$([\d,]+)([KMkm]?)", subject)
    if target_match:
        amt = float(target_match.group(1).replace(",", ""))
        unit = target_match.group(2).upper()
        if unit == "K":
            amt *= 1000
        elif unit == "M":
            amt *= 1_000_000
        sub["TargetPremium"] = amt

    # First table row often has timestamp
    if email.get("tables"):
        for row in email["tables"][0].get("rows", []):
            for cell in row:
                m = re.search(r"(\w+ \d+, \d+, \d+:\d+\s* ?\s*[AP]M)", cell)
                if m:
                    try:
                        d = datetime.strptime(m.group(1).replace(" ", " "),
                                                "%b %d, %Y, %I:%M %p")
                        sub["DateReceived"] = d.isoformat()
                    except Exception:
                        pass
    return sub


# ── Attachments ──

def list_attachments() -> list:
    if not INPUT_DIR.exists():
        return []
    out = []
    type_map = {
        ".pdf": "ACORD",  # default; refined below
        ".docx": "Email",
        ".xls": "SOV", ".xlsx": "SOV",
    }
    for f in sorted(INPUT_DIR.iterdir()):
        if not f.is_file():
            continue
        suffix = f.suffix.lower()
        a_type = type_map.get(suffix, "Other")
        name = f.name.lower()
        if "loss" in name or "lr_" in name or name.startswith("lr "):
            a_type = "LossRun"
        elif "acord" in name and ("125" in name or "126" in name or "131" in name or
                                    "140" in name or "823" in name or "app" in name):
            a_type = "ACORD"
        elif "sov" in name or "schedule" in name:
            a_type = "SOV"
        elif "supp" in name or "supplemental" in name:
            a_type = "Supplemental"
        elif "email" in name or suffix == ".docx":
            a_type = "Email"
        elif "map" in name:
            a_type = "Other"

        mime_map = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xls": "application/vnd.ms-excel",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        out.append({
            "Type": a_type,
            "FileName": f.name,
            "MimeType": mime_map.get(suffix, "application/octet-stream"),
            "Description": f.stem,
        })
    return out


# ── Main ──

def main():
    acord = _load("Acord_App_1800_North_Stone_LLC_2026.json")
    sov = _load("SOV_updated_1800_North_Stone_LLC_2026.04.23.json")
    lr = _load("Farmers_LR_2020-26_1800_North_Stone_LLC_VAL_2026.04.03.json")
    email = _load("email.json")
    note_doc = _load("1800_North_Stone_LLC.json")

    acord_mapped = map_acord(acord)
    locations = map_sov(sov)
    loss_runs = map_loss_run(lr)
    submission_extras = map_email(email)
    attachments = list_attachments()

    # Build full submission
    insured = acord_mapped.get("insured", {})
    # Fold note_doc text into DescriptionOfOperations if present
    if note_doc and not insured.get("DescriptionOfOperations"):
        paras = note_doc.get("paragraphs") or []
        text = " ".join(p["text"] for p in paras if p["text"])
        if text:
            insured["DescriptionOfOperations"] = text[:2000]

    submission = {
        "Submission": {
            "Status": "Cleared",
            "GLSelected": "General Liability" in (acord_mapped.get("policy", {}).get("LOB") or []),
            "PropertySelected": "Property" in (acord_mapped.get("policy", {}).get("LOB") or []),
            "ProductType": "HabGen",
            **{k: v for k, v in submission_extras.items() if v},
        },
        "PolicyInfo": {
            "RenewalFlag": "New",
            **{k: v for k, v in acord_mapped.get("policy", {}).items() if v},
        },
        "Insured": {k: v for k, v in insured.items() if v},
        "Agent": {k: v for k, v in acord_mapped.get("agent", {}).items() if v},
        "GeneralLiability": {
            "CoverageSelected":
                "General Liability" in (acord_mapped.get("policy", {}).get("LOB") or []),
        },
        "Property": {
            "CoverageSelected":
                "Property" in (acord_mapped.get("policy", {}).get("LOB") or []),
        },
        "Locations": locations,
        "LossRuns": loss_runs,
        "Attachments": attachments,
    }

    out_path = EXTRACTED_DIR / "submission_mapped.json"
    with open(out_path, "w") as f:
        json.dump(submission, f, indent=2, default=str)
    print(f"Wrote {out_path}")
    print(f"  Insured.Name: {submission['Insured'].get('Name')}")
    print(f"  Insured.EntityType: {submission['Insured'].get('EntityType')}")
    print(f"  Insured.NAICS / SIC: "
          f"{submission['Insured'].get('NAICSCode')} / "
          f"{submission['Insured'].get('SICCode')}")
    print(f"  Agent.Name: {submission['Agent'].get('Name')}")
    print(f"  PolicyInfo: {submission['PolicyInfo'].get('EffectiveDate')} → "
          f"{submission['PolicyInfo'].get('ExpirationDate')}, "
          f"LOB={submission['PolicyInfo'].get('LOB')}")
    print(f"  Locations: {len(locations)}")
    for loc in locations:
        print(f"    Loc {loc['LocationNumber']}: {len(loc['Buildings'])} buildings")
    print(f"  LossRuns: {len(loss_runs)} ({sum(len(lr['Claims']) for lr in loss_runs)} claims)")
    print(f"  Attachments: {len(attachments)}")


if __name__ == "__main__":
    main()
