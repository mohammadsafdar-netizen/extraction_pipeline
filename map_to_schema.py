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
EXTRACTED_DIR = REPO / "input_extracted"  # default; overridable via --extracted-dir
INPUT_DIR = REPO / "input_docs" / "Input"  # default; overridable via --input-dir


def _load(name: str, extracted_dir: Path = None) -> dict | None:
    base = extracted_dir or EXTRACTED_DIR
    p = base / name
    if not p.exists():
        return None
    return json.load(open(p))


def _find_by_pattern(extracted_dir: Path, *substrings) -> dict | None:
    """Find an extraction JSON whose filename contains any of the given
       substrings (case-insensitive). Returns the loaded JSON or None.
       Used for pattern-based file discovery so the mapper doesn't need
       to hardcode customer-specific filenames."""
    if not extracted_dir.exists():
        return None
    for f in sorted(extracted_dir.iterdir()):
        if f.suffix != ".json":
            continue
        name_lower = f.name.lower()
        if any(s.lower() in name_lower for s in substrings):
            try:
                return json.load(open(f))
            except Exception:
                continue
    return None


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


def _entity_type_from_acord(acord_data: dict, fallback_name: str = "") -> str | None:
    """Read the /Btn LegalEntity indicators on p1, return matching enum.
       If no checkbox is True (broker oversight or detection miss),
       fall back to deriving from the insured Name suffix."""
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

    # Fallback: derive from Insured Name suffix
    if fallback_name:
        name_norm = re.sub(r"[.,]", "", fallback_name.upper())
        suffix_map = [
            (r"\b(LLC|LIMITED LIABILITY (?:COMPANY|CORPORATION))\b",
                "Limited Liability Company"),
            (r"\b(LP|LIMITED PARTNERSHIP|L\.P)\b",         "Partnership"),
            (r"\b(LLP|LIMITED LIABILITY PARTNERSHIP)\b",   "Partnership"),
            (r"\b(LIMITED PARTNERS?HIP)\b",                "Partnership"),
            (r"\b(GENERAL PARTNERSHIP|GP)\b",              "Partnership"),
            (r"\bPARTNERSHIP\b",                            "Partnership"),
            (r"\b(INC|INCORPORATED|CORP|CORPORATION|CO)\b","Corporation"),
            (r"\bTRUST\b",                                  "Other"),  # schema has no Trust
            (r"\bJOINT VENTURE\b",                          "Joint Venture"),
        ]
        for pat, label in suffix_map:
            if re.search(pat, name_norm):
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


# ── Tier 1 helpers (added 2026-05-08) ──

# Mapping from AcroForm Interest indicator name → schema enum
_INTEREST_NAME_MAP = {
    "MortgageeIndicator": "Mortgagee",
    "LossPayeeIndicator": "Loss Payee",
    "LendersLossPayableIndicator": "Lenders Loss Payable",
    "LienholderIndicator": "Lienholder",
    "AdditionalInsuredIndicator": "Additional Insured",
    "OwnerIndicator": "Owner",
    "CoOwnerIndicator": "Co-Owner",
    "BreachOfWarrantyIndicator": "Breach of Warranty",
    "EmployeeAsLessorIndicator": "Employee as Lessor",
    "LeasebackOwnerIndicator": "Leaseback Owner",
    "RegistrantIndicator": "Registrant",
    "TrusteeIndicator": "Trustee",
    "OtherIndicator": "Other",
    "BailmentIndicator": "Bailment",
}


def _parse_csz(line: str) -> dict:
    """Parse 'City, ST 12345-6789' or 'City, ST 12345' → {City,State,ZipCode}."""
    if not line:
        return {}
    m = re.match(r"^([A-Za-z .'-]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)\s*$", line.strip())
    if m:
        return {"City": m.group(1).strip(),
                "State": m.group(2),
                "ZipCode": m.group(3)}
    return {}


def map_secured_parties(acord) -> list:
    """Extract SecuredParties from AdditionalInterest_* fields across all pages.
       Each block has: FullName + MailingAddress_LineOne + LineTwo +
       one or more Interest indicators (Mortgagee/LossPayee/etc.)
       Multi-property forms have separate _A and _B blocks per location."""
    if not acord:
        return []
    pages = acord.get("pages", {})
    parties = []

    for pname, p in pages.items():
        fields = p.get("fields", {})
        # Find every AdditionalInterest block by suffix (_A, _B, _C, etc.)
        # We look for any non-empty FullName in the block.
        for suffix in ("_A", "_B", "_C", "_A[0]", "_B[0]", "_C[0]"):
            name_field = fields.get(f"AdditionalInterest_FullName{suffix}")
            if not name_field:
                continue
            name_val = name_field.get("value")
            if not name_val or not isinstance(name_val, str):
                continue
            # Strip pdfplumber bled-address ("Berkadia Commercial Mortgage, LLC 332 Norristown R")
            # Take only the LLC/Inc/Corp prefix as the name
            m = re.match(r"^(.+?(?:LLC|Inc\.?|Corporation|Corp\.?|Group|Trust|Bank|"
                          r"Mortgage[a-z]*|Holdings|Co\.?|Company))\s+\d+\s",
                          name_val, re.IGNORECASE)
            clean_name = m.group(1).strip() if m else name_val.strip()
            # Try to capture trailing street if it bled (after the name part)
            street = None
            if m:
                tail = name_val[m.end():].strip()
                if tail:
                    street = tail.split("\n")[0].strip()

            # Address — LineOne is often city/state/zip; LineTwo is county
            line1 = (fields.get(f"AdditionalInterest_MailingAddress_LineOne{suffix}") or {}).get("value")
            line2 = (fields.get(f"AdditionalInterest_MailingAddress_LineTwo{suffix}") or {}).get("value")
            addr = {"Type": "Mailing"}
            if street:
                addr["Street"] = street
            csz = _parse_csz(line1 or "")
            if csz:
                addr.update(csz)
            elif line1:
                addr["Street2"] = line1
            if line2:
                addr["County"] = line2 if not csz else line2

            # Determine interest type from which indicator is True
            interest = None
            for indicator_key, label in _INTEREST_NAME_MAP.items():
                ind_name = f"AdditionalInterest_Interest_{indicator_key}{suffix}"
                ind_field = fields.get(ind_name)
                if ind_field and ind_field.get("value") in (True, "True"):
                    interest = label
                    break

            cert_field = fields.get(f"AdditionalInterest_CertificateRequiredIndicator{suffix}")
            cert_required = (cert_field or {}).get("value") in (True, "True")

            # Parse page number for LocationNumber link
            try:
                pg_num = int(pname.split("_")[1])
            except Exception:
                pg_num = None

            party = {
                "Name": clean_name,
                "Addresses": [{k: v for k, v in addr.items() if v}],
            }
            if interest:
                party["Interest"] = interest
            if cert_required:
                party["CertificateRequired"] = True
            if pg_num is not None:
                party["_source_page"] = pg_num
            parties.append(party)

    # Dedupe by name (multi-property forms list the same mortgagee per loc)
    seen = {}
    for p in parties:
        key = (p["Name"], p.get("Interest", ""))
        if key not in seen:
            seen[key] = p
        else:
            # Merge — append source pages
            existing = seen[key]
            existing.setdefault("_source_pages", [existing.pop("_source_page", None)])
            sp = p.get("_source_page")
            if sp and sp not in existing["_source_pages"]:
                existing["_source_pages"].append(sp)
    return list(seen.values())


def map_other_named_insureds(acord) -> list:
    """Look for secondary/tertiary NamedInsured blocks on p1 (the _B and
       _C suffix blocks). Return list of {Name, Operations}."""
    if not acord:
        return []
    p1 = acord.get("pages", {}).get("page_1", {}).get("fields", {})
    others = []
    for suffix in ("_B[0]", "_C[0]", "_D[0]"):
        name_f = p1.get(f"NamedInsured_FullName{suffix}")
        if not name_f:
            continue
        v = name_f.get("value")
        if v and isinstance(v, str) and v.strip().upper() not in ("SECONDARY", "TERTIARY"):
            others.append({"Name": v.strip()})
    return others


def map_location_gl_from_acord(acord) -> list:
    """Extract GL hazard schedule (class code, exposure) from ACORD 126
       pages. Returns list of {OccupancyClass, Exposure} dicts that
       can be attached to Locations[].GeneralLiability[]."""
    if not acord:
        return []
    out = []
    for pname, p in acord.get("pages", {}).items():
        fields = p.get("fields", {})
        for suffix in ("_A", "_B", "_C", "_A[0]", "_B[0]"):
            cls = fields.get(f"GeneralLiability_Hazard_Classification{suffix}")
            exp = fields.get(f"GeneralLiability_Hazard_Exposure{suffix}")
            if cls and exp:
                cls_v = cls.get("value")
                exp_v = exp.get("value")
                if not cls_v or not exp_v:
                    continue
                # Parse "60010 U" → exposure 60010, type letter U (Units)
                exp_match = re.match(r"^([\d,]+)\s*([A-Z]?)$", str(exp_v).strip())
                exposure_num = None
                if exp_match:
                    try:
                        exposure_num = float(exp_match.group(1).replace(",", ""))
                    except ValueError:
                        pass
                # Parse "SWIMMING POOL 0 2 48925 T 1" — class code is the
                # 5-digit number (ISO GL class codes are 5 digits)
                cls_str = str(cls_v).strip()
                code_match = re.search(r"\b(\d{5})\b", cls_str)
                class_code = code_match.group(1) if code_match else None
                # Description = leading text (everything before the digits)
                desc_match = re.match(r"^([A-Z][A-Z\s/&-]+?)(?:\s+\d|\s*$)",
                                       cls_str, re.IGNORECASE)
                class_description = desc_match.group(1).strip() if desc_match else cls_str
                out.append({
                    "OccupancyClass": class_code or class_description,
                    "OccupancyDescription": class_description,
                    "Exposure": exposure_num,
                    "ExposureRaw": str(exp_v),
                    "ClassRaw": cls_str,
                })
    return out


def derive_aggregate_business_income_limit(locations: list) -> float:
    """Sum BusinessIncomeLimit across every building of every location."""
    total = 0.0
    for loc in locations:
        for b in loc.get("Buildings", []):
            v = b.get("BusinessIncomeLimit")
            if isinstance(v, (int, float)):
                total += v
    return total or None


def derive_building_description(b: dict) -> str:
    """Synthesize a human-readable building description from structured
       fields. E.g. 'Student Housing — 3-story Frame, built 2003 (14 units)'"""
    bits = []
    if b.get("OccupancyType"):
        bits.append(b["OccupancyType"])
    structural = []
    if b.get("NoOfStories"):
        structural.append(f"{b['NoOfStories']}-story")
    if b.get("ConstructionType"):
        structural.append(b["ConstructionType"])
    if structural:
        bits.append(" ".join(structural))
    if b.get("YearOfConstruction"):
        bits.append(f"built {b['YearOfConstruction']}")
    if b.get("TotalUnits"):
        bits.append(f"{b['TotalUnits']} units")
    return " — ".join(bits[:2]) + (f" ({', '.join(bits[2:])})" if len(bits) > 2 else "")


def parse_quote_needed_by(email_data: dict) -> str:
    """Parse 'Need asap', 'Need by 5/15', etc. from email subject/body.
       Returns ISO date string OR 'ASAP' / None."""
    if not email_data:
        return None
    text = ""
    for p in email_data.get("paragraphs", []):
        text += " " + p.get("text", "")
    text_l = text.lower()
    if "asap" in text_l or "need asap" in text_l:
        return "ASAP"
    # Look for 'need by 5/15/2026' / 'by 5/15' / 'deadline 5/15'
    m = re.search(r"(?:need\s+by|deadline|by)\s+(\d{1,2}/\d{1,2}(?:/\d{2,4})?)",
                   text_l)
    if m:
        return _parse_date(m.group(1)) or m.group(1)
    return None


# ── Tier 2 helpers ──

_PHONE_RE = re.compile(
    r"(?:T|D|Direct|Cell|Mobile|Office|Phone|Tel)?\s*[:.]?\s*"
    r"(\+?\d?\s*\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
_LICENSE_RE = re.compile(r"(?:CA\s+)?License\s*#?\s*([A-Z0-9]+)", re.IGNORECASE)
_TITLE_RE = re.compile(
    r"\b(Founder|CEO|CFO|President|Director|Manager|Broker|Underwriter|"
    r"Producer|Specialist|Agent|Marketing|VP|Vice\s+President|Sr\.?\s*|"
    r"Senior\s+|Owner|Partner)", re.IGNORECASE)


def _parse_signature_block(lines: list) -> dict:
    """Parse a list of consecutive paragraph texts that constitute a
       signature block. Returns {Name, Title, Phone, Email, Company,
       License, Address} — only fields detected."""
    sig = {}
    name = None
    title = None
    company = None
    address_lines = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        # Email
        em = _EMAIL_RE.search(s)
        if em and "Email" not in sig:
            sig["Email"] = em.group(1)
        # Phone
        ph = _PHONE_RE.search(s)
        if ph and "Phone" not in sig:
            sig["Phone"] = ph.group(1).strip()
        # License
        lic = _LICENSE_RE.search(s)
        if lic:
            sig["License"] = lic.group(1)
        # Name detection: line in form "First Last" / "First Last | Title"
        # OR "First Last, Title"
        if not name:
            m = re.match(r"^([A-Z][a-z]+\s+[A-Z][a-zA-Z'-]+)(\s*[|,-]\s*(.+))?$", s)
            if m:
                name = m.group(1).strip()
                if m.group(3):
                    title = m.group(3).strip()
        # Title detection: bare title-like line
        if not title and _TITLE_RE.search(s) and len(s) < 80 and "@" not in s:
            title = s
        # Company: lines with LLC/Inc/Group/Brokerage
        if not company and re.search(
                r"\b(LLC|Inc\.?|Insurance|Brokerage|Group|Agency|Holdings|"
                r"Corporation|Co\.?|Company)\b", s):
            if "@" not in s and len(s) < 80:
                company = s
        # Address: lines with state abbreviation or zip
        if (re.search(r"\b[A-Z]{2}\s+\d{5}", s)
                or re.search(r"\d+\s+[A-Z][a-z]+\s+(Rd|Road|St|Street|Ave|"
                              r"Avenue|Blvd|Boulevard|Way|Suite|Ste)", s)):
            address_lines.append(s)

    if name:
        sig["Name"] = name
    if title:
        sig["Title"] = title
    if company:
        sig["Company"] = company
    if address_lines:
        sig["AddressLines"] = address_lines
    return sig if sig else None


def parse_email_signatures(email_data: dict) -> list:
    """Walk paragraphs looking for signature blocks. A signature block
       starts after 'Thank You' / 'Thanks' / '--' / 'Best regards' / 'Sincerely'
       and ends at the next email-thread divider ('From:', 'Sent:', 'To:',
       'Subject:') or at next signature."""
    if not email_data:
        return []
    paragraphs = [p["text"] for p in email_data.get("paragraphs", [])
                  if p.get("text")]

    signatures = []
    in_sig = False
    sig_lines = []
    SIG_START_RE = re.compile(
        r"^(thank you|thanks|--|best regards|sincerely|kind regards|cheers|"
        r"warm regards)[,.!]?\s*$", re.IGNORECASE)
    SIG_END_RE = re.compile(
        r"^(from:|sent:|to:|subject:|cc:|bcc:|date:|on\s+\w+,\s+\w+|"
        r"this e-mail|this email|please send|to unsubscribe|"
        r"please consider|disclaimer|confidentiality|wrote:)",
        re.IGNORECASE)

    for line in paragraphs:
        if SIG_START_RE.match(line.strip()):
            if in_sig and sig_lines:
                sig = _parse_signature_block(sig_lines)
                if sig:
                    signatures.append(sig)
            in_sig = True
            sig_lines = []
            continue
        if in_sig:
            if SIG_END_RE.match(line.strip()):
                sig = _parse_signature_block(sig_lines)
                if sig:
                    signatures.append(sig)
                in_sig = False
                sig_lines = []
                continue
            if line.strip():
                sig_lines.append(line)

    if in_sig and sig_lines:
        sig = _parse_signature_block(sig_lines)
        if sig:
            signatures.append(sig)

    # Dedupe by Name primarily; merge non-conflicting fields. Two signatures
    # with the same Name and any field overlap (or no conflicting field)
    # are merged into one record.
    by_name = {}
    no_name = []
    for s in signatures:
        n = s.get("Name")
        if not n:
            no_name.append(s)
            continue
        if n in by_name:
            existing = by_name[n]
            for k, v in s.items():
                if v and not existing.get(k):
                    existing[k] = v
        else:
            by_name[n] = dict(s)
    return list(by_name.values()) + no_name


def parse_loss_run_policy_terms(lr) -> list:
    """Extract per-policy-term effective/expiration dates from VLM summary
       rows. Returns list of {effective: ISO, expiration: ISO} for each
       policy period in the loss run."""
    if not lr:
        return []
    terms = []
    for vp in lr.get("vlm_pages", []) or []:
        data = vp.get("data") or {}
        summary = data.get("summary")
        if not isinstance(summary, list):
            continue
        for row in summary:
            if not isinstance(row, dict):
                continue
            eff_raw = row.get("effective_date") or ""
            exp_raw = row.get("expiration_date") or ""
            # "05/01/2025 - 05/01/2026" pattern → split
            range_match = re.match(
                r"(\d{1,2}/\d{1,2}/\d{2,4})\s*[-–to]+\s*(\d{1,2}/\d{1,2}/\d{2,4})",
                eff_raw.strip())
            if range_match:
                eff_iso = _parse_date(range_match.group(1))
                exp_iso = _parse_date(range_match.group(2))
            else:
                eff_iso = _parse_date(eff_raw)
                exp_iso = _parse_date(exp_raw)
            if eff_iso or exp_iso:
                terms.append({
                    "effective": eff_iso,
                    "expiration": exp_iso,
                    "claim_count": row.get("claim_count"),
                })
    return terms


def map_protective_safeguards_for_page(p_fields: dict) -> list:
    """Walk all Alarm_*Indicator_* and FireProtection_*Indicator_* on a
       page. Return list of human-readable safeguard labels for any True.
       Returns deduped list."""
    safeguards = set()
    label_map = {
        "CentralStation": "Central Station Alarm",
        "LocalGong": "Local Gong",
        "WithKeys": "With Keys",
        "ClockHourly": "Clock Hourly",
        "GuardWatchman": "Guard / Watchman",
        "FireExtinguisher": "Fire Extinguisher",
        "Sprinkler": "Sprinkler",
        "SmokeDetector": "Smoke Detector",
        "Hydrant": "Hydrant Nearby",
    }
    for k, f in p_fields.items():
        if (("Alarm" in k or "FireProtection" in k or "Protective" in k)
                and f.get("type") == "checkbox" and f.get("value") is True):
            for needle, label in label_map.items():
                if needle in k:
                    safeguards.add(label)
                    break
    return sorted(safeguards)


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
        m = re.search(r"^(.*?)\s+\d+\s+[NSEW]?\s*\w+\s+"
                       r"(Ave|Avenue|Street|St|Rd|Road|Blvd|Boulevard|"
                       r"Drive|Dr|Lane|Ln|Way|Circle|Cir|Court|Ct|"
                       r"Place|Pl|Highway|Hwy|Parkway|Pkwy|Suite|Ste)",
                      bbox_name, re.IGNORECASE)
        insured["Name"] = m.group(1).strip() if m else bbox_name

    insured["EntityType"] = _entity_type_from_acord(acord, insured.get("Name", ""))
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
        m = re.search(r"^(.*?)\s+\d+\s+[NSEW]?\s*\w+\s+"
                       r"(Ave|Avenue|Street|St|Rd|Road|Blvd|Boulevard|"
                       r"Drive|Dr|Lane|Ln|Way|Circle|Cir|Court|Ct|"
                       r"Place|Pl|Highway|Hwy|Parkway|Pkwy|Suite|Ste)",
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
    """Return list of Locations with embedded Buildings.
       Handles two SOV layouts:
         (a) per-building rows with 'Loc.#' + 'Building #' columns
         (b) per-location rows with 'Location #' + 'Street Address' + Building/
             Contents/Business Income value columns (one row = one location
             with a single building — common Master SOV format)"""
    if not sov or "sheets" not in sov:
        return []

    # Try every sheet — pick the one with the most building-like data
    best_sheet = None
    best_count = 0
    for sheet in sov["sheets"]:
        grid = sheet.get("raw_grid", [])
        # Count rows that have multiple non-empty cells (data rows)
        data_count = sum(1 for row in grid
                          if sum(1 for c in row if str(c).strip()) >= 5)
        if data_count > best_count:
            best_count = data_count
            best_sheet = sheet
    if not best_sheet:
        return []
    grid = best_sheet.get("raw_grid", [])

    # Find header row by signature
    HEADER_KEYWORDS = [
        ("loc", "building #"),     # 1800 N Stone style
        ("loc", "building#"),
        ("location", "address"),    # Master SOV style (per-location rows)
        ("location #", "street"),
        ("location#", "street"),
        ("premises", "address"),    # ACORD 823 style
    ]
    header_idx = None
    for i, row in enumerate(grid):
        joined = " ".join(str(c) for c in row).lower()
        if any(all(kw in joined for kw in pair) for pair in HEADER_KEYWORDS):
            header_idx = i; break
    if header_idx is None:
        return []
    header = [str(c).strip() for c in grid[header_idx]]
    # Index column → header label
    idx = {h: i for i, h in enumerate(header) if h}

    # Tolerant column lookup — tries multiple possible header names per field
    def _col(row, *names):
        """Return first non-empty cell value matching any header name."""
        for n in names:
            if n in idx:
                v = row[idx[n]]
                if v not in (None, ""):
                    return v
        return None

    LOC_COLS = ("Loc.#", "Loc #", "Location #", "Location#", "Location Number")
    BLDG_COLS = ("Building #", "Building#", "Bldg #", "Bldg#")
    OCCUPANCY_COLS = ("Occupancy", "Occupancy Type", "Occupancy Class")
    NAMED_INSURED_COLS = ("Location Named Insured",)
    STREET_COLS = ("Street Address", "Address", "Premise Address",
                    "Property Address")
    CITY_COLS = ("City",)
    STATE_COLS = ("State",)
    ZIP_COLS = ("Zip", "Zip Code", "ZIP")
    COUNTY_COLS = ("County",)
    YEAR_COLS = ("Year Built",)
    CONSTRUCTION_COLS = ("Construction Type", "Construction")
    ROOF_TYPE_COLS = ("Type of Roof", "Roof Type")
    SQFT_COLS = ("# Sq. Ft. Bldg", "Sq Ft", "Square Feet", "Total Sq Ft")
    STORIES_COLS = ("# of stories", "# Stories", "Stories", "No of Stories")
    UNITS_COLS = ("# Hab Units", "# Units", "Units", "Total Units")
    SPRINKLER_COLS = ("Sprinklered %", "Sprinkler %", "Sprinklered")
    RCV_COLS = ("Building RCV", "Building", "Bldg RCV", "Bldg",
                  "Building Value")
    BPP_COLS = ("BPP", "Contents", "Business Personal Property")
    BI_COLS = ("Loss of Rents", "Business Income", "BI", "Loss of Rents/BI")

    locs = {}  # loc_num → location dict
    for row in grid[header_idx + 1:]:
        if not any(str(c).strip() for c in row):
            continue
        loc_num_raw = _col(row, *LOC_COLS)
        loc_num = _safe_int(loc_num_raw)
        if loc_num is None:
            continue

        b = {}
        b["BuildingNumber"] = _safe_int(_col(row, *BLDG_COLS)) or 1
        b["YearOfConstruction"] = _safe_int(_col(row, *YEAR_COLS))
        ct = _col(row, *CONSTRUCTION_COLS)
        b["ConstructionType"] = str(ct).strip() if ct else None
        rt = _col(row, *ROOF_TYPE_COLS)
        b["RoofType"] = str(rt).strip() if rt else None
        b["TotalSqFt"] = _safe_float(_col(row, *SQFT_COLS))
        b["NoOfStories"] = _safe_int(_col(row, *STORIES_COLS))
        b["TotalUnits"] = _safe_int(_col(row, *UNITS_COLS))
        oc = _col(row, *OCCUPANCY_COLS)
        b["OccupancyType"] = str(oc).strip() if oc else None
        # Sprinklered: 100% means fully sprinklered
        spr = _safe_float(_col(row, *SPRINKLER_COLS))
        if spr is not None:
            b["FullySprinklered"] = spr >= 100
        # Limits
        rcv = _safe_float(_col(row, *RCV_COLS))
        bpp = _safe_float(_col(row, *BPP_COLS))
        bi = _safe_float(_col(row, *BI_COLS))
        if rcv is not None and rcv > 0:
            b["Building"] = {"BuildingCoverageFlag": True, "BuildingLimit": rcv,
                             "Building100RcValue": rcv}
        if bpp is not None and bpp > 0:
            b["Bpp"] = {"BppCoverageFlag": True, "BppLimit": bpp}
        if bi is not None and bi > 0:
            b["BusinessIncomeLimit"] = bi

        # Drop None values
        b = {k: v for k, v in b.items() if v is not None}

        # Address per row
        street = _col(row, *STREET_COLS)
        city = _col(row, *CITY_COLS)
        state = _col(row, *STATE_COLS)
        zip_raw = _col(row, *ZIP_COLS)
        county = _col(row, *COUNTY_COLS)
        addr = {"Type": "Physical"}
        if street:
            addr["Street"] = str(street).strip()
        if city:
            addr["City"] = str(city).strip()
        if state:
            addr["State"] = str(state).strip()
        if zip_raw not in (None, ""):
            try:
                addr["ZipCode"] = str(int(float(str(zip_raw))))
            except (ValueError, TypeError):
                addr["ZipCode"] = str(zip_raw).strip()
        if county:
            addr["County"] = str(county).strip()

        # Location name from named insured if present
        loc_name = _col(row, *NAMED_INSURED_COLS) or f"Location {loc_num}"

        if loc_num not in locs:
            locs[loc_num] = {
                "LocationNumber": loc_num,
                "LocationName": str(loc_name).strip().split("\n")[0]
                                  if loc_name else f"Location {loc_num}",
                "Address": addr if len(addr) > 1 else None,
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

    # Per-policy-term dates from VLM summary rows. Use most-recent term
    # as the policy effective/expiration to populate the schema fields.
    policy_terms = parse_loss_run_policy_terms(lr)
    most_recent_eff = None
    most_recent_exp = None
    if policy_terms:
        # Pick the term with the most recent expiration date
        sorted_terms = sorted(policy_terms,
                               key=lambda t: t.get("expiration") or "",
                               reverse=True)
        most_recent_eff = sorted_terms[0].get("effective")
        most_recent_exp = sorted_terms[0].get("expiration")

    # Build a single LossRun entry covering this carrier
    entry = {
        "Carrier": h.get("company") or h.get("carrier") or h.get("company/carrier"),
        "PolicyNumber": h.get("policy_number"),
        "EvaluationDate": _parse_date(h.get("valuation_date")),
        "PolicyEffectiveDate": most_recent_eff,
        "PolicyExpirationDate": most_recent_exp,
        "LOB": "General Liability",  # Farmers LR is for GL
        "Claims": [],
        "PolicyTerms": policy_terms if policy_terms else None,
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
    # Filename → Attachments.Type. Order matters: more-specific patterns first.
    # The default for .pdf is "Other", not "ACORD" — only files matching
    # ACORD-specific patterns get tagged ACORD.
    type_map_default = {
        ".pdf": "Other",
        ".docx": "Email",
        ".xls": "SOV", ".xlsx": "SOV",
    }
    LOSS_RUN_FNAME_PATS = re.compile(
        r"\b(loss[\s_-]?run|claims?[\s_-]history|lr[\s_-])", re.IGNORECASE)

    for f in sorted(INPUT_DIR.iterdir()):
        if not f.is_file():
            continue
        suffix = f.suffix.lower()
        a_type = type_map_default.get(suffix, "Other")
        name = f.name.lower()
        if LOSS_RUN_FNAME_PATS.search(name) or name.startswith("lr "):
            a_type = "LossRun"
        elif "acord" in name and ("125" in name or "126" in name or "131" in name or
                                    "140" in name or "823" in name or "app" in name):
            a_type = "ACORD"
        elif "sov" in name or "schedule of values" in name or "statement of values" in name:
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
    global INPUT_DIR
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--extracted-dir", default=str(EXTRACTED_DIR),
                     help="Per-doc JSONs from run_input_extraction.py")
    ap.add_argument("--input-dir", default=str(INPUT_DIR),
                     help="Original input docs (for Attachments listing)")
    ap.add_argument("--out", default=None,
                     help="Output path for submission_mapped.json (default: <extracted_dir>/submission_mapped.json)")
    args = ap.parse_args()

    extracted_dir = Path(args.extracted_dir)
    INPUT_DIR = Path(args.input_dir)

    # Pattern-based discovery — works for any insured/broker/file naming
    acord = _find_by_pattern(extracted_dir, "Acord", "ACORD")
    sov = _find_by_pattern(extracted_dir, "SOV", "Statement_of_Values", "Master")
    lr = _find_by_pattern(extracted_dir, "Loss_Run", "LossRun", "_LR_", "_LR-",
                            "CGL-Ategrity", "Loss-Run")
    email = _find_by_pattern(extracted_dir, "email", "EMAIL")
    note_doc = _find_by_pattern(extracted_dir, "_LLC", "_LP", "_Inc", "_Corp",
                                   "narrative", "note", "claude")

    acord_mapped = map_acord(acord)
    locations = map_sov(sov)
    loss_runs = map_loss_run(lr)
    submission_extras = map_email(email)
    attachments = list_attachments()

    # ── Tier 1 expansions ──
    secured_parties = map_secured_parties(acord)
    other_named = map_other_named_insureds(acord)
    location_gl = map_location_gl_from_acord(acord)
    quote_needed_by = parse_quote_needed_by(email)

    # ── Tier 2: email signatures → Agent.Contacts (broker side) ──
    email_signatures = parse_email_signatures(email)
    # Heuristic: signatures with broker-side companies (Insurance, Brokerage,
    # Agency, Underwriter, Wholesale, MGA) get attached to Agent.Contacts.
    # Signatures with insured-side companies (LLC, Properties, Holdings,
    # Realty, etc.) optionally go to Insured.Contacts.
    broker_signal = re.compile(
        r"\b(insurance|brokerage|underwriter|broker|wholesale|mga|"
        r"agency|specialty|amwins|crc|crest)\b", re.IGNORECASE)
    agent_contacts_from_email = []
    insured_contacts_from_email = []
    for sig in email_signatures:
        c = {"Type": "Producer"}
        if sig.get("Name"): c["Name"] = sig["Name"]
        if sig.get("Title"): c["Title"] = sig["Title"]
        if sig.get("Email"): c["Email"] = sig["Email"]
        if sig.get("Phone"): c["Phone"] = sig["Phone"]
        company = (sig.get("Company") or "").lower()
        if broker_signal.search(company) or broker_signal.search(
                (sig.get("Title") or "").lower()):
            agent_contacts_from_email.append(c)
        else:
            ic = {k: v for k, v in c.items() if k != "Type"}
            insured_contacts_from_email.append(ic)

    # Per-building enrichment: Description, ProtectiveSafeguards
    if acord:
        # Get protective safeguards from ACORD 140 pages (per location).
        # Build a list of safeguards by source page.
        sg_by_page = {}
        for pname, p in acord.get("pages", {}).items():
            sg = map_protective_safeguards_for_page(p.get("fields", {}))
            if sg:
                try:
                    pn = int(pname.split("_")[1])
                except Exception:
                    pn = None
                if pn is not None:
                    sg_by_page[pn] = sg
        # Apply: union of all 140 pages' safeguards across all buildings (a
        # form-level signal — doesn't differentiate per location yet)
        all_sg = sorted({s for sgs in sg_by_page.values() for s in sgs})
    else:
        all_sg = []

    for loc in locations:
        if location_gl:
            loc["GeneralLiability"] = location_gl
        for b in loc.get("Buildings", []):
            if not b.get("Description"):
                desc = derive_building_description(b)
                if desc:
                    b["Description"] = desc
            if all_sg:
                b["ProtectiveSafeguards"] = list(all_sg)

    # Property.AggregateBusinessIncomeLimit
    agg_bi = derive_aggregate_business_income_limit(locations)

    # Build full submission
    insured = acord_mapped.get("insured", {})
    # Fold note_doc text into DescriptionOfOperations if present
    if note_doc and not insured.get("DescriptionOfOperations"):
        paras = note_doc.get("paragraphs") or []
        text = " ".join(p["text"] for p in paras if p["text"])
        if text:
            insured["DescriptionOfOperations"] = text[:2000]

    submission_block = {
        "Status": "Cleared",
        "GLSelected": "General Liability" in (acord_mapped.get("policy", {}).get("LOB") or []),
        "PropertySelected": "Property" in (acord_mapped.get("policy", {}).get("LOB") or []),
        "ProductType": "HabGen",
        **{k: v for k, v in submission_extras.items() if v},
    }
    if quote_needed_by:
        submission_block["QuoteNeededBy"] = quote_needed_by

    property_block = {
        "CoverageSelected":
            "Property" in (acord_mapped.get("policy", {}).get("LOB") or []),
    }
    if agg_bi:
        property_block["AggregateBusinessIncomeLimit"] = agg_bi

    # Merge email-derived signatures into the Agent + Insured contact lists
    agent_block = {k: v for k, v in acord_mapped.get("agent", {}).items() if v}
    if agent_contacts_from_email:
        existing = agent_block.get("Contacts", [])
        existing_emails = {c.get("Email") for c in existing if c.get("Email")}
        for c in agent_contacts_from_email:
            if c.get("Email") not in existing_emails:
                existing.append(c)
        agent_block["Contacts"] = existing

    if insured_contacts_from_email:
        existing = insured.get("Contacts", []) if isinstance(insured.get("Contacts"), list) else []
        existing_emails = {c.get("Email") for c in existing if c.get("Email")}
        for c in insured_contacts_from_email:
            if c.get("Email") not in existing_emails:
                existing.append(c)
        insured["Contacts"] = existing

    submission = {
        "Submission": submission_block,
        "PolicyInfo": {
            "RenewalFlag": "New",
            **{k: v for k, v in acord_mapped.get("policy", {}).items() if v},
        },
        "Insured": {k: v for k, v in insured.items() if v},
        "OtherNamedInsureds": other_named,
        "Agent": agent_block,
        "GeneralLiability": {
            "CoverageSelected":
                "General Liability" in (acord_mapped.get("policy", {}).get("LOB") or []),
        },
        "Property": property_block,
        "Locations": locations,
        "SecuredParties": secured_parties,
        "LossRuns": loss_runs,
        "Attachments": attachments,
    }
    # Drop empty arrays
    if not submission["OtherNamedInsureds"]:
        del submission["OtherNamedInsureds"]
    if not submission["SecuredParties"]:
        del submission["SecuredParties"]

    out_path = Path(args.out) if args.out else (extracted_dir / "submission_mapped.json")
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
