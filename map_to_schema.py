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


def _find_all_by_pattern(extracted_dir: Path, *substrings) -> list:
    """Like _find_by_pattern but returns ALL matches as list of (filename, json)."""
    out = []
    if not extracted_dir.exists():
        return out
    for f in sorted(extracted_dir.iterdir()):
        if f.suffix != ".json":
            continue
        name_lower = f.name.lower()
        if any(s.lower() in name_lower for s in substrings):
            try:
                out.append((f.name, json.load(open(f))))
            except Exception:
                continue
    return out


def _find_acord_files(extracted_dir: Path) -> list:
    """Discover all ACORD-app JSONs by inspecting `document_type`. Filename-
       agnostic — handles names like `26_GL_Application_for_Prism_Broward.json`
       that don't contain 'acord'. Returns list of (filename, json) sorted
       so files with more 'real' (bbox) pages come first."""
    if not extracted_dir.exists():
        return []
    candidates = []
    for f in sorted(extracted_dir.iterdir()):
        if f.suffix != ".json":
            continue
        if f.name in ("ALL.json", "submission_mapped.json"):
            continue
        try:
            data = json.load(open(f))
        except Exception:
            continue
        if data.get("document_type") == "acord_application":
            # Score by number of populated bbox fields across all pages —
            # the GL/CGL app usually has the canonical page-1 applicant info
            score = 0
            for pg in (data.get("pages") or {}).values() if isinstance(data.get("pages"), dict) else []:
                for fv in (pg.get("fields") or {}).values():
                    if fv.get("source") == "bbox" and fv.get("value"):
                        score += 1
            candidates.append((-score, f.name, data))
    candidates.sort()
    return [(name, data) for _, name, data in candidates]


def _merge_acord_files(files: list) -> dict | None:
    """Merge multiple ACORD JSONs into a single dict.

       Strategy: walk each file's pages in order; reorder so applicant-info
       pages (acord_125) come first (so map_acord's p1=page_1 lookup works),
       then 126/127/130/131/137/140/163/823. Within each (template,
       page_idx) group, fields are union-merged: first non-empty value wins.
       This handles GL+XS combos where both ACORD apps duplicate the
       applicant-info page (acord_125 #0). Returns merged dict in the
       canonical merged-shape (pages: {page_1, page_2, ...})."""
    if not files:
        return None
    if len(files) == 1:
        return files[0][1]

    # Template priority — acord_125 (applicant info) must be page_1
    TPL_ORDER = ["acord_125", "acord_126", "acord_127", "acord_130",
                  "acord_131", "acord_137", "acord_140", "acord_163",
                  "acord_823"]

    def _tpl_key(tpl: str) -> tuple:
        # tpl looks like 'acord_125.pdf#0' or 'acord_126_2014.pdf#1'
        base = tpl.split(".")[0] if tpl else "zzz"
        # Strip any year suffix so acord_126_2014 → acord_126
        for canonical in TPL_ORDER:
            if base.startswith(canonical):
                base_canonical = canonical
                break
        else:
            base_canonical = base
        try:
            order_idx = TPL_ORDER.index(base_canonical)
        except ValueError:
            order_idx = len(TPL_ORDER)
        page_idx = int(tpl.split("#")[-1]) if "#" in (tpl or "") else 0
        return (order_idx, base, page_idx)

    # Bucket fields by (template, page_idx) — merge across files
    buckets: dict = {}
    for fname, data in files:
        for pn, pg in (data.get("pages") or {}).items():
            tpl = pg.get("template") or "unknown"
            key = _tpl_key(tpl)
            if key not in buckets:
                buckets[key] = {"template": tpl, "fields": {}, "_orig_page": pn}
            for fk, fv in (pg.get("fields") or {}).items():
                existing = buckets[key]["fields"].get(fk)
                # Prefer non-empty bbox fields, then non-empty vlm
                new_val = fv.get("value")
                if existing is None:
                    buckets[key]["fields"][fk] = fv
                elif existing.get("value") in (None, "", False) and new_val not in (None, "", False):
                    buckets[key]["fields"][fk] = fv

    # Emit pages in canonical order
    new_pages = {}
    for i, (key, bucket) in enumerate(sorted(buckets.items()), start=1):
        new_pages[f"page_{i}"] = {
            "page": i,
            "template": bucket["template"],
            "fields": bucket["fields"],
        }

    # Pick first file's metadata as base, replace pages
    merged = dict(files[0][1])
    merged["pages"] = new_pages
    merged["_merged_from"] = [f for f, _ in files]
    return merged


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
    if fallback_name and isinstance(fallback_name, str):
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
    # Strip leading "as of" / "valued" / "valuation" prefixes
    s = re.sub(r"^(?:as\s+of|valued|valuation)\s*[:\-]?\s*",
                "", s, flags=re.IGNORECASE).strip()
    # Strip leading day-of-week ("Wednesday, March 18, 2026" → "March 18, 2026")
    s = re.sub(r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s*,?\s*",
                "", s, flags=re.IGNORECASE).strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%d/%m/%Y", "%m-%d-%Y",
                 "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y",
                 "%d %B %Y", "%d %b %Y", "%Y/%m/%d"):
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
    parties = list(seen.values())

    # Fallback: VLM-extracted "Additional Interest" name+address blocks. Some
    # ACORD pages have non-AcroForm text (e.g. acord_126 page 2 — Santander
    # block) where bbox AdditionalInterest_FullName fields are mismapped to
    # adjacent labels. The VLM key contains the full multi-line block.
    VLM_KEYS = re.compile(
        r"vlm_(?:ADDITIONAL_INTEREST(?:_\d+)?_NAME_AND_ADDRESS|"
        r"additional_interest_certificate_recipient_name_and_address|"
        r"additional_interest_\d+_name_and_address)",
        re.IGNORECASE)
    seen_names = {p.get("Name", "").lower() for p in parties}
    for pname, pg in pages.items():
        for k, f in (pg.get("fields") or {}).items():
            if not VLM_KEYS.search(k):
                continue
            val = f.get("value")
            if not val or not isinstance(val, str):
                continue
            lines = [l.strip() for l in val.split("\n") if l.strip()]
            if len(lines) < 2:
                continue
            name = lines[0].rstrip(",.")
            if name.lower() in seen_names:
                continue
            # Parse remaining lines as address. Common shapes:
            #   ["Street", "City, ST ZIP"]
            #   ["Street", "City", "ST ZIP"]
            #   ["Street", "City", "State", "ZIP"]
            addr = {"Type": "Mailing"}
            rest = lines[1:]
            # Try last-line CSZ
            csz_match = None
            for i in range(len(rest) - 1, -1, -1):
                m = re.search(r"([A-Za-z .'-]+),?\s+([A-Z]{2})\s+(\d{5}(?:-\d{4})?)",
                                rest[i])
                if m:
                    csz_match = (i, m)
                    break
            if csz_match:
                idx_csz, m = csz_match
                addr["City"] = m.group(1).strip().rstrip(",")
                addr["State"] = m.group(2)
                addr["ZipCode"] = m.group(3)
                # Lines before the CSZ line are street/street2
                street_lines = rest[:idx_csz]
                if street_lines:
                    addr["Street"] = street_lines[0]
                    if len(street_lines) > 1:
                        addr["Street2"] = " ".join(street_lines[1:])
            else:
                # Fallback: try multi-line
                if len(rest) >= 1:
                    addr["Street"] = rest[0]
                if len(rest) >= 2:
                    # Could be City alone or "ST ZIP"
                    m2 = re.match(r"([A-Z]{2})\s+(\d{5})", rest[-1])
                    if m2:
                        addr["State"] = m2.group(1)
                        addr["ZipCode"] = m2.group(2)
                        if len(rest) >= 3:
                            addr["City"] = rest[1]
                    else:
                        addr["City"] = rest[1]
            try:
                pg_num = int(pname.split("_")[1])
            except Exception:
                pg_num = None
            party = {
                "Name": name,
                "Interest": "Mortgagee",  # most common; ACORD 125 default
                "Addresses": [{k: v for k, v in addr.items() if v}],
            }
            if pg_num is not None:
                party["_source_page"] = pg_num
            parties.append(party)
            seen_names.add(name.lower())

    return parties


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
    """Parse 'Need asap', 'Need by: 5/15/26', 'deadline 5/15', etc. from
       email subject/body. Returns ISO date string OR 'ASAP' / None."""
    if not email_data:
        return None
    text = ""
    for p in email_data.get("paragraphs", []):
        text += " " + p.get("text", "")
    text_l = text.lower()
    if "asap" in text_l or "need asap" in text_l or "rush" in text_l:
        return "ASAP"
    # Variants: "need by 5/15/26", "need by: 5/15/26", "deadline 5/15",
    # "by 5/15/26", "due 5/15/26"
    m = re.search(
        r"(?:need\s+by|deadline|due|by)[:\s]+(\d{1,2}/\d{1,2}(?:/\d{2,4})?)",
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


def _pick_fuzzy(fields: dict, *keyword_groups) -> str | None:
    """Find a field value by keyword-substring matching. Each arg is a
       tuple of keywords ALL of which must be present in the field-name
       (case-insensitive). First matching field with a non-empty value wins.
       Used as a fallback when the VLM emits non-standard key names.
       Example: _pick_fuzzy(p1, ('agency', 'name'), ('agent', 'name'),
                                   ('producer', 'fullname')) """
    for kws in keyword_groups:
        kws_l = [kw.lower() for kw in kws]
        # Anti-keyword filtering. Skip fields whose name contains markers
        # for compound/secondary attributes the caller didn't ask for.
        # E.g. searching for `("vlm_agency",)` shouldn't match
        # `vlm_agency_address` (mailing-block dump) or
        # `vlm_other_named_insured_entity_type_checked` (boolean indicator).
        looking_for_name = (
            any(kw in ("name", "fullname", "full_name") for kw in kws_l)
            or any(kw in ("vlm_agency", "vlm_agent", "vlm_producer",
                          "vlm_broker", "vlm_insured", "vlm_applicant",
                          "vlm_namedinsured", "vlm_named_insured",
                          "vlm_header") for kw in kws_l)
        ) and not any("address" in kw for kw in kws_l)
        anti = []
        if looking_for_name:
            anti = ["address", "city_state_zip", "mailing", "indicator",
                    "_checked", "entity_type", "_code", "phone", "_email",
                    "_zip", "_state", "_city", "_street"]
        for fname, f in fields.items():
            if not isinstance(f, dict):
                continue
            name_l = fname.lower()
            if all(kw in name_l for kw in kws_l):
                if anti and any(a in name_l for a in anti):
                    continue
                v = f.get("value")
                if v in (None, "", False, "False"):
                    continue
                # When looking for a name, reject non-string values
                # (booleans, numbers from indicator/code fields).
                if looking_for_name and not isinstance(v, str):
                    continue
                return v
    return None


def _looks_like_concat_with_address(v):
    """Heuristic: bbox value bled into the address (e.g.
       '1800 North Stone LLC 1800 N Stone Ave')."""
    if not isinstance(v, str):
        return False
    return bool(re.search(r"\b\d+\s+[NSEW]?\s*\w+\s+(Ave|Street|St|Rd|Road|Blvd|Drive|Dr|Lane|Ln|Way|Circle|Cir|Suite|Ste)\b",
                          v, re.IGNORECASE))


def _normalize_acord_pages(acord) -> dict:
    """Normalize ACORD JSON's `pages` to the merged-pipeline shape:
       {"page_N": {"fields": {field_name: {value, source, type, tooltip}}}}.
       The merged pipeline produces this shape natively. Pure-VLM fall-back
       produces {"pages": [{"page": N, "data": {...}}]} which we adapt
       here so the mapper can read both."""
    if not acord:
        return {}
    pages = acord.get("pages")
    if isinstance(pages, dict):
        return acord  # already in merged shape
    if isinstance(pages, list):
        # Convert list-shape (pure VLM) to merged-shape stub. Each VLM
        # page's `data` dict becomes a fields dict where each top-level
        # key is treated as a vlm_<key> entry. This lets the mapper's
        # _pick("vlm_HEADER_agency_name", ...) lookups still work.
        new_pages = {}
        for entry in pages:
            pn = entry.get("page")
            if pn is None:
                continue
            data = entry.get("data") or {}
            fields = {}
            def _flatten(prefix, val):
                if isinstance(val, dict):
                    for k, v in val.items():
                        sub = f"{prefix}_{k}" if prefix else f"vlm_{k}"
                        _flatten(sub, v)
                elif isinstance(val, list):
                    for i, v in enumerate(val):
                        sub = f"{prefix}_{i}"
                        _flatten(sub, v)
                else:
                    if val not in (None, "", False):
                        fields[prefix] = {
                            "value": val, "source": "vlm",
                            "type": "text", "tooltip": prefix,
                        }
            _flatten("", data)
            new_pages[f"page_{pn}"] = {"fields": fields}
        out = dict(acord)
        out["pages"] = new_pages
        return out
    return {"pages": {}}


def map_acord(acord) -> dict:
    acord = _normalize_acord_pages(acord)
    if not acord or "pages" not in acord:
        return {}
    insured = {}
    agent = {}
    policy = {}

    p1 = acord["pages"].get("page_1", {}).get("fields", {})

    # Insured.Name — prefer VLM, fall back to bbox if not bled
    bbox_name = _pick(p1, "NamedInsured_FullName_A[0]", "NamedInsured_FullName_B[0]")
    vlm_name = (_pick(p1, "vlm_APPLICANT_INFORMATION_0_full_name",
                          "vlm_NamedInsured_FullName_A")
                or _pick_fuzzy(p1,
                    ("vlm_", "applicant", "full_name"),
                    ("vlm_", "applicant", "name"),
                    ("vlm_", "namedinsured", "full"),
                    ("vlm_", "named_insured", "name"),
                    ("vlm_", "insured", "name")))
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
    # Collect address pieces from many possible sources, in priority order.
    addr1 = {
        "Type": "Mailing",
        "Street": _pick(p1,
            "vlm_APPLICANT_INFORMATION_0_address_line1",
            "vlm_applicant_address_line1",
            "vlm_APPLICANT_INFORMATION_0_street",
            "NamedInsured_AddressLine_StreetName_A[0]"),
        "Street2": None,
        "City": _pick(p1,
            "NamedInsured_AddressLine_CityName_A[0]",
            "vlm_APPLICANT_INFORMATION_0_city"),
        "State": _pick(p1,
            "NamedInsured_AddressLine_StateOrProvinceCode_A[0]",
            "vlm_APPLICANT_INFORMATION_0_state"),
        "ZipCode": _pick(p1,
            "NamedInsured_AddressLine_PostalCode_A[0]",
            "vlm_APPLICANT_INFORMATION_0_zip"),
    }
    # Many submissions have a single combined 'address' field from the VLM
    # like "3625 N Hall Street, Suite 610, Dallas, TX 75219" — parse it.
    if not (addr1["Street"] and addr1["City"]):
        combined = (_pick(p1,
            "vlm_applicant_address",
            "vlm_APPLICANT_INFORMATION_0_full_address",
            "vlm_APPLICANT_INFORMATION_0_address")
            or _pick_fuzzy(p1,
                ("vlm_", "applicant", "mailing_address"),
                ("vlm_", "applicant", "address"),
                ("vlm_", "namedinsured", "address"),
                ("vlm_", "named_insured", "address"),
                ("vlm_", "insured", "address")))
        if combined and isinstance(combined, str):
            # Strip newlines (multi-line addresses → single line)
            combined_norm = re.sub(r"\s*\n\s*", ", ", combined.strip())
            # "Street[, Suite N], City, ST ZIP"
            m = re.match(
                r"^(.+?),\s*([A-Za-z .'-]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)\s*$",
                combined_norm)
            if m:
                street_part = m.group(1).strip()
                # Split off "Suite/Ste/Unit/Apt N" into Street2
                sm = re.match(
                    r"^(.+?),\s*((?:Suite|Ste|Unit|Apt|Floor|Fl|#)\s*[\w-]+)\s*$",
                    street_part, re.IGNORECASE)
                if sm:
                    if not addr1.get("Street"):
                        addr1["Street"] = sm.group(1).strip()
                    if not addr1.get("Street2"):
                        addr1["Street2"] = sm.group(2).strip()
                else:
                    if not addr1["Street"]:
                        addr1["Street"] = street_part
                if not addr1["City"]:
                    addr1["City"] = m.group(2).strip()
                if not addr1["State"]:
                    addr1["State"] = m.group(3)
                if not addr1["ZipCode"]:
                    addr1["ZipCode"] = m.group(4)
    # Parse single-line "City, ST 12345-6789" if needed
    if not addr1["City"]:
        line_csz = _pick(p1, "NamedInsured_MailingAddress_LineOne_A[0]",
                              "NamedInsured_MailingAddress_LineTwo_A[0]",
                              "vlm_APPLICANT_INFORMATION_0_city_state_zip")
        if line_csz:
            m = re.match(r"([A-Za-z\s.]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)", line_csz)
            if m:
                addr1["City"] = m.group(1).strip()
                addr1["State"] = m.group(2)
                addr1["ZipCode"] = m.group(3)
    # Last resort: extract street from bled FullName (which we already
    # stripped to set Insured.Name; the suffix had the address)
    if not addr1["Street"] and bbox_name:
        m = re.search(
            r"\b(\d+\s+[NSEW]?\s*[A-Z][a-zA-Z .'-]+\s+"
            r"(?:Ave|Avenue|Street|St|Rd|Road|Blvd|Boulevard|Drive|Dr|"
            r"Lane|Ln|Way|Circle|Cir|Court|Ct|Place|Pl|Highway|Hwy|"
            r"Parkway|Pkwy)(?:\s+(?:Suite|Ste)\s+\d+)?)",
            bbox_name, re.IGNORECASE)
        if m:
            addr1["Street"] = m.group(1).strip()
    # If LineOne has a suite/unit number and we already have a street,
    # roll it into Street2
    line_one = _pick(p1, "NamedInsured_MailingAddress_LineOne_A[0]")
    if (line_one and addr1.get("Street") and not addr1.get("Street2")
            and not re.search(r"\d{5}", str(line_one))):
        if "suite" in str(line_one).lower() or "ste" in str(line_one).lower() \
                or "unit" in str(line_one).lower() or "apt" in str(line_one).lower():
            addr1["Street2"] = str(line_one).strip()
    if any(v for v in addr1.values() if v and v != "Mailing"):
        insured["Addresses"].append({k: v for k, v in addr1.items() if v})

    # Agent / Producer — same VLM-prefer pattern
    bbox_agent = _pick(p1, "Producer_FullName_A[0]")
    vlm_agent = (_pick(p1, "vlm_HEADER_agency_name", "vlm_AGENCY")
                 or _pick_fuzzy(p1,
                     ("vlm_", "header", "agency"),
                     ("vlm_agency",),  # bare AGENCY key
                     ("vlm_", "agency_name"),
                     ("vlm_", "agent", "name"),
                     ("vlm_", "producer_name"),
                     ("vlm_", "broker_name")))
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
        _pick(p1, "Policy_EffectiveDate_A[0]")
        or _pick_fuzzy(p1, ("vlm_", "proposed_eff"),
                            ("vlm_", "effective_date"),
                            ("vlm_", "policy_information", "proposed_eff"),
                            ("vlm_", "policy", "effective"))
    )
    policy["ExpirationDate"] = _parse_date(
        _pick(p1, "Policy_ExpirationDate_A[0]")
        or _pick_fuzzy(p1, ("vlm_", "proposed_exp"),
                            ("vlm_", "expiration_date"),
                            ("vlm_", "policy_information", "proposed_exp"),
                            ("vlm_", "policy", "expiration"))
    )
    policy["PriorPolicyNumber"] = (
        _pick(p1, "Policy_PolicyNumberIdentifier_A[0]")
        or _pick_fuzzy(p1, ("vlm_", "policy_number"),
                             ("vlm_", "policy_no"))
    )

    # LOB from p1 Policy_LineOfBusiness_* checkboxes (and legacy
    # LineOfBusinessIndicator forms). Each checked LOB → entry in list.
    # Primary LOBs only — Umbrella/Excess are coverage extensions on top of
    # GL, not separate lines for our schema's purpose.
    LOB_CHECKBOX_MAP = [
        ("CommercialGeneralLiability", "General Liability"),
        ("GeneralLiability", "General Liability"),
        ("CommercialProperty", "Property"),
        ("Property", "Property"),
        ("CommercialAuto", "Commercial Auto"),
        ("BusinessAuto", "Commercial Auto"),
        ("WorkersComp", "Workers Compensation"),
        ("WorkersCompensation", "Workers Compensation"),
        ("InlandMarine", "Inland Marine"),
        ("Crime", "Crime"),
        ("Garage", "Garage"),
        ("EquipmentBreakdown", "Equipment Breakdown"),
    ]
    lobs = []
    for k, f in p1.items():
        if not (k.startswith("Policy_LineOfBusiness_")
                or "LineOfBusinessIndicator" in k):
            continue
        if f.get("value") is not True:
            continue
        for substr, label in LOB_CHECKBOX_MAP:
            if substr in k and label not in lobs:
                lobs.append(label)
                break
    if not lobs:
        # Form has no detectable LOB checkboxes — assume both GL and
        # Property (the most common combo for habitational submissions).
        # This matches the historical default and works for sub 1 / sub 3.
        lobs = ["General Liability", "Property"]
    policy["LOB"] = lobs

    # Insured-side contacts from ACORD page 2 (NamedInsured_Contact_*).
    # Walk every page since these fields can appear on different pages
    # depending on the form variant.
    insured_contacts = []
    for pname, pg in acord.get("pages", {}).items():
        fields = pg.get("fields", {})
        # Group contact fields by suffix letter (A, B, C, ...)
        by_suffix = {}
        for k, f in fields.items():
            m = re.match(r"NamedInsured_Contact_(\w+?)_([A-Z])\[0\]", k)
            if not m:
                continue
            attr, suf = m.groups()
            by_suffix.setdefault(suf, {})[attr] = f.get("value")
        for suf, attrs in by_suffix.items():
            full_name = attrs.get("FullName")
            if not full_name or not isinstance(full_name, str):
                continue
            # Strip trailing/leading PRIMARY/SECONDARY tags + extra noise
            clean_name = re.sub(r"\b(PRIMARY|SECONDARY)\b", "",
                                  full_name, flags=re.IGNORECASE).strip()
            if not clean_name or clean_name.upper() in ("PRIMARY", "SECONDARY"):
                continue
            c = {"Name": clean_name}
            phone = attrs.get("PrimaryPhoneNumber") or attrs.get("PhoneNumber")
            email_addr = attrs.get("PrimaryEmailAddress") or attrs.get("EmailAddress")
            title = attrs.get("ContactDescription") or attrs.get("Title")
            if phone: c["Phone"] = str(phone).strip()
            if email_addr: c["Email"] = str(email_addr).strip()
            if title: c["Title"] = str(title).strip()
            # Avoid duplicates on Name
            if not any(x.get("Name") == clean_name for x in insured_contacts):
                insured_contacts.append(c)

    return {"insured": insured, "agent": agent, "policy": policy,
             "insured_contacts": insured_contacts}


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
        ("entity", "address"),       # Varsity-style SOV (Entity per row)
        ("occupancy", "address"),    # Mixed format
        ("street address", "city"),  # Generic property table
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

    # Tolerant column lookup — tries multiple possible header names per field.
    # Falls back to substring matching when no exact name matches (handles
    # header variations like "Business Personal Property (RC)" vs the bare
    # "Business Personal Property" we stored).
    def _col(row, *names, exact_only=False):
        """Return first non-empty cell value matching any header name
           (exact match preferred, substring match as fallback).
           If exact_only=True, skip the substring fallback — used for
           ambiguous lookups like BuildingNumber where "Bldg" would
           wrongly match "Bldg Value"."""
        # 1. Try exact case-sensitive match
        for n in names:
            if n in idx:
                v = row[idx[n]]
                if v not in (None, ""):
                    return v
        if exact_only:
            return None
        # 2. Case-insensitive substring match with WORD BOUNDARIES (one-way,
        # punctuation-stripped). "Total Sq Ft" search matches "Total Sq.Ft"
        # header. Word-boundary required so "St" doesn't match "Street".
        def _norm(s):
            return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()
        for n in names:
            n_norm = _norm(n)
            if not n_norm:
                continue
            pattern = r"\b" + re.escape(n_norm) + r"\b"
            for header_name, col_idx in idx.items():
                if re.search(pattern, _norm(header_name)):
                    v = row[col_idx]
                    if v not in (None, ""):
                        return v
        return None

    LOC_COLS = ("Loc.#", "Loc #", "Location #", "Location#", "Location Number",
                  "Location ID", "Loc ID")
    BLDG_COLS = ("Building #", "Building#", "Bldg #", "Bldg#")
    OCCUPANCY_COLS = ("Occupancy", "Occupancy Type", "Occupancy Class")
    NAMED_INSURED_COLS = ("Location Named Insured", "Entity",
                            "Location Name", "Property Name", "Name")
    STREET_COLS = ("Street Address", "Address", "Premise Address",
                    "Property Address", "Property Street", "Site Address",
                    "Address1", "Address 1", "Street")
    CITY_COLS = ("City",)
    STATE_COLS = ("State", "St")
    ZIP_COLS = ("Zip", "Zip Code", "ZIP", "Postal Code")
    COUNTY_COLS = ("County",)
    YEAR_COLS = ("Year Built", "Year of Construction", "Construction Year",
                   "Built", "Year")
    CONSTRUCTION_COLS = ("Construction Type", "Construction")
    ROOF_TYPE_COLS = ("Type of Roof", "Roof Type")
    SQFT_COLS = ("# Sq. Ft. Bldg", "Sq Ft", "Square Feet", "Total Sq Ft",
                   "Total Square Feet", "Total Sq.Ft", "TotalSqFt",
                   "Total SqFt", "Square Footage", "Sq Footage", "SqFt",
                   "Bldg Sq Ft", "Building Sq Ft", "Building Square Footage")
    STORIES_COLS = ("# of stories", "# Stories", "Stories", "No of Stories",
                       "Number of Stories")
    UNITS_COLS = ("# Hab Units", "# Units", "Units", "Total Units",
                    "Number of Units", "Unit Count")
    SPRINKLER_COLS = ("Sprinklered %", "Sprinkler %", "Sprinklered",
                         "Sprinkler", "Fully Sprinklered")
    RCV_COLS = ("Building RCV", "Building", "Bldg RCV", "Bldg",
                  "Building Value", "Building Value (RC)", "Bldg Value",
                  "Building Limit", " Building Value (R", "Building (RC)",
                  "Real Property Value", "Real Property", "Property Value")
    BPP_COLS = ("BPP", "Contents", "Business Personal Property",
                  "Business Personal", "Personal Property", "Contents Value",
                  "Personal Property Value")
    BI_COLS = ("Loss of Rents", "Business Income", "BI", "Loss of Rents/BI",
                  " Business \nIncome ", "Business Income/Loss of Rents",
                  "Rents", "Annual Rent", "Annual Rents",
                  "BI/Rental Income Value", "BI/Rental Income", "Rental Income")

    has_loc_col = any(c in idx for c in LOC_COLS)
    locs = {}  # loc_num → location dict
    addr_to_loc = {}  # (street_lower, city_lower) → loc_num for same-address
    auto_loc_counter = 0
    for row in grid[header_idx + 1:]:
        if not any(str(c).strip() for c in row):
            continue
        # Skip rows without enough data
        if sum(1 for c in row if str(c).strip()) < 3:
            continue

        loc_num = None
        if has_loc_col:
            # Loc # column exists — if the cell is empty for this row,
            # SKIP rather than auto-number. (Otherwise we pick up section-
            # header rows like 'Great Point Location' that have data in
            # other columns but no Loc#.)
            loc_num_raw = _col(row, *LOC_COLS)
            loc_num = _safe_int(loc_num_raw)
            if loc_num is None:
                continue
        else:
            # No Loc # column at all → group by (street, city). Same address
            # = same location, multiple rows = multiple buildings under that
            # location. (E.g. campus-style SOVs where 7 building rows all
            # share the same physical address.)
            if not _col(row, *NAMED_INSURED_COLS, *STREET_COLS):
                continue
            row_street = _col(row, *STREET_COLS)
            row_city = _col(row, *CITY_COLS)
            addr_key = (str(row_street or "").strip().lower(),
                         str(row_city or "").strip().lower())
            if addr_key in addr_to_loc and addr_key != ("", ""):
                loc_num = addr_to_loc[addr_key]
            else:
                auto_loc_counter += 1
                loc_num = auto_loc_counter
                if addr_key != ("", ""):
                    addr_to_loc[addr_key] = loc_num

        b = {}
        # If no explicit Building# column, auto-number per location based on
        # the count of buildings already attached to that location.
        # exact_only because "Bldg" search would wrongly match "Bldg Value".
        bldg_num_raw = _safe_int(_col(row, *BLDG_COLS, exact_only=True))
        if bldg_num_raw is not None:
            b["BuildingNumber"] = bldg_num_raw
        else:
            b["BuildingNumber"] = len(locs.get(loc_num, {}).get("Buildings", [])) + 1
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
        # Sprinklered: handle both percent ("100", "100%") and Y/N forms.
        # When SOV has both "Percent Sprinklered" AND "Sprinklered (Y/N)"
        # columns, prefer the Y/N column (more reliable — percent is often
        # left as 0 even when sprinklers exist).
        spr_yn = _col(row, "Sprinklered (Y/N)", "Sprinklered Y/N",
                        "Fully Sprinklered (Y/N)")
        if spr_yn is not None and str(spr_yn).strip().upper() in ("Y", "N",
                                                                     "YES", "NO"):
            b["FullySprinklered"] = str(spr_yn).strip().upper() in ("Y", "YES")
        else:
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
            # Clean location name: split off any \n continuations, strip
            # whitespace + trailing punctuation
            if loc_name:
                clean_name = str(loc_name).split("\n")[0].strip()
                clean_name = re.sub(r"[;,\s]+$", "", clean_name)
            else:
                clean_name = f"Location {loc_num}"
            locs[loc_num] = {
                "LocationNumber": loc_num,
                "LocationName": clean_name or f"Location {loc_num}",
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

    # Per-policy-term dates. Heuristic: if the loss-run evaluation date
    # falls inside one of the reported policy terms, that's the CURRENT
    # policy — use just that term (sub 1: 5 yrs of history but reporting
    # the 2025-2026 policy). Otherwise the loss run reports a closed
    # multi-year window (sub 4 CIBA: 2021-2023 policy period evaluated
    # in 2026) — use the full earliest→latest window.
    policy_terms = parse_loss_run_policy_terms(lr)
    most_recent_eff = None
    most_recent_exp = None
    if policy_terms:
        eval_d = _parse_date(h.get("valuation_date"))
        containing = None
        if eval_d:
            for t in policy_terms:
                eff = t.get("effective")
                exp = t.get("expiration")
                if eff and exp and eff <= eval_d <= exp:
                    containing = t
                    break
        if containing:
            most_recent_eff = containing.get("effective")
            most_recent_exp = containing.get("expiration")
        else:
            eff_dates = [t.get("effective") for t in policy_terms if t.get("effective")]
            exp_dates = [t.get("expiration") for t in policy_terms if t.get("expiration")]
            most_recent_eff = min(eff_dates) if eff_dates else None
            most_recent_exp = max(exp_dates) if exp_dates else None

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

    # Normalize claim "Status" to schema title-case form. The parser emits
    # "Closed W/Payment" but ACORD style is "Closed w/Payment" (lowercase w).
    def _norm_status(s):
        if not s:
            return None
        s = str(s).strip()
        # Title-case + lowercase the "w" in "w/Payment"
        s = re.sub(r"\bW/", "w/", s, flags=re.IGNORECASE)
        return s.title().replace("W/", "w/")

    # Claims from pdfplumber-parsed rows OR from VLM detail rows. Field names
    # match the schema: Status, DateOfLoss, TotalPaid, TotalIncurred. When
    # TotalIncurred isn't separately reported, derive as Paid + Reserves.
    # Pre-filter pdfplumber rows: when the parser misaligned columns (some
    # carrier formats don't match the regex), claim_no is empty/truncated and
    # everything is fragmented — fall back to VLM in that case.
    parsed = lr.get("pdfplumber_parsed_claims") or []
    valid_parsed = [c for c in parsed
                     if (c.get("claim_no") or c.get("claim_number"))
                     and len(str(c.get("claim_no") or c.get("claim_number") or "")) >= 4
                     and (c.get("loss_date") or c.get("date_of_loss"))]
    if not valid_parsed:
        parsed = []  # force VLM fallback
    else:
        parsed = valid_parsed
    def _clean_desc(s):
        if not s:
            return None
        # Strip newlines + collapse extra whitespace
        return re.sub(r"\s+", " ", str(s)).strip()

    if parsed:
        for c in parsed:
            paid = _safe_float(c.get("total_paid") or c.get("paid"))
            reserves = _safe_float(c.get("total_reserves") or c.get("reserves"))
            incurred = _safe_float(c.get("total_incurred") or c.get("incurred"))
            if incurred is None and (paid is not None or reserves is not None):
                incurred = (paid or 0) + (reserves or 0)
            desc_raw = c.get("cause_of_loss") or c.get("description")
            desc = _clean_desc(desc_raw)
            # Some parsers put a stray space before "/" — normalize "Slip /Trip / fall" → "Slip/Trip/fall"
            if desc:
                desc = re.sub(r"\s*/\s*", "/", desc)
            entry["Claims"].append({
                "ClaimNumber": c.get("claim_no") or c.get("claim_number"),
                "Status": _norm_status(c.get("status")),
                "DateOfLoss": _parse_date(c.get("loss_date") or c.get("date_of_loss")),
                "Description": desc,
                "TotalPaid": paid,
                "TotalIncurred": incurred,
            })
    else:
        # Fall back to VLM claims
        for p in vlm_pages:
            data = p.get("data", {}) or {}
            for c in (data.get("claims") or data.get("detail") or []):
                if not isinstance(c, dict):
                    continue
                paid = _safe_float(c.get("amount_paid"))
                reserves = _safe_float(c.get("amount_reserved"))
                incurred = _safe_float(c.get("net_incurred"))
                if incurred is None and (paid is not None or reserves is not None):
                    incurred = (paid or 0) + (reserves or 0)
                entry["Claims"].append({
                    "ClaimNumber": c.get("claim_number"),
                    "Status": _norm_status(c.get("status")),
                    "DateOfLoss": _parse_date(c.get("date_of_loss")),
                    "Description": c.get("type_cause") or c.get("description"),
                    "TotalPaid": paid,
                    "TotalIncurred": incurred,
                })

    # Drop None values from each claim, then drop entirely-empty claims
    entry["Claims"] = [
        {k: v for k, v in c.items() if v is not None} for c in entry["Claims"]
    ]
    entry["Claims"] = [c for c in entry["Claims"] if c]
    entry["NoKnownLossesLast5Years"] = (len(entry["Claims"]) == 0)
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

    # First table row often has timestamp (Gmail header table)
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
    # Reply-quoted timestamps in paragraphs: "On Fri, Apr 24, 2026 at 1:50 PM".
    # When email is a forward/reply chain, prefer EARLIEST quoted date
    # (the original broker send) over the table timestamp (which may be
    # the most-recent reply).
    on_date_pat = re.compile(
        r"On\s+\w+,\s+(\w+ \d+, \d+)\s+at\s+(\d+:\d+)\s*[\s ]*([AP]M)",
        re.IGNORECASE)
    candidates = []
    for p in email.get("paragraphs") or []:
        for m in on_date_pat.finditer(p.get("text", "")):
            try:
                dstr = f"{m.group(1)} {m.group(2)} {m.group(3).upper()}"
                d = datetime.strptime(dstr, "%b %d, %Y %I:%M %p")
                candidates.append(d)
            except Exception:
                pass
    if candidates:
        earliest = min(candidates).date().isoformat()
        existing = sub.get("DateReceived", "")
        if not existing or existing[:10] > earliest:
            sub["DateReceived"] = earliest
    return sub


# ── Attachments ──

def list_attachments() -> list:
    if not INPUT_DIR.exists():
        return []
    out = []
    # Filename → Attachments.Type. Order matters: more-specific patterns first.
    # The default for .pdf is "Other", not "ACORD" — only files matching
    # ACORD-specific patterns get tagged ACORD.
    # Defaults are conservative — files only get tagged with a specific
    # Type when a filename pattern matches below; otherwise "Other".
    type_map_default = {
        ".pdf": "Other",
        ".docx": "Email",
        ".xls": "Other", ".xlsx": "Other",
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
        elif "acord" in name or (suffix == ".pdf" and re.search(
                r"\b(application|app)\b", name, re.IGNORECASE)):
            # ACORD files: explicit "acord" in name, or PDFs with
            # "application"/"app" (Prism's "26 GL Application for Prism
            # Broward.pdf" doesn't contain "acord" but is an ACORD app).
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

    # ACORD discovery: prefer document_type-based (filename-agnostic, handles
    # multi-app submissions like Prism's 26_GL_Application + 26_XS_Application).
    # Fall back to filename pattern for legacy/edge cases.
    acord_files = _find_acord_files(extracted_dir)
    if acord_files:
        if len(acord_files) > 1:
            print(f"  Merging {len(acord_files)} ACORD apps: "
                  f"{[n for n,_ in acord_files]}")
        acord = _merge_acord_files(acord_files)
    else:
        acord = _find_by_pattern(extracted_dir, "Acord", "ACORD")
    sov = _find_by_pattern(extracted_dir, "SOV", "Statement_of_Values", "Master",
                              "Liability_Renewal_Exposures",
                              "Renewal_Exposures", "Schedule_of_Values")
    # Multiple loss-run files may exist (one master + per-location LRs)
    lr_files = _find_all_by_pattern(extracted_dir,
        "Loss_Run", "LossRun", "_LR_", "_LR-", "CGL-Ategrity",
        "Loss-Run", "LR_", "_GL_Loss")
    email = _find_by_pattern(extracted_dir, "email", "EMAIL")
    # Insured-specific narrative .docx (e.g. "1800_North_Stone_LLC.docx").
    # Excludes 'claude_chat.docx' which is internal AI deliberation, not
    # underwriting context.
    def _find_note_doc(d: Path):
        for f in sorted(d.iterdir()) if d.exists() else []:
            if f.suffix != ".json":
                continue
            n_lower = f.name.lower()
            if "claude" in n_lower:  # exclude AI-chat dumps
                continue
            if any(s in n_lower for s in ("_llc", "_lp", "_inc", "_corp",
                                            "narrative", "note")):
                try:
                    return json.load(open(f))
                except Exception:
                    continue
        return None
    note_doc = _find_note_doc(extracted_dir)

    # Normalize once so every downstream mapper sees dict-shape pages
    if acord:
        acord = _normalize_acord_pages(acord)
    acord_mapped = map_acord(acord)
    locations = map_sov(sov)
    # Map ALL loss-run files (some submissions ship multiple)
    loss_runs = []
    for fname, lr_json in lr_files:
        lr_mapped = map_loss_run(lr_json)
        for entry in lr_mapped:
            entry["_source_file"] = fname
        loss_runs.extend(lr_mapped)
    # Drop empty LR records (no carrier, no policy number, no claims) —
    # parse_loss_run_policy_terms can emit a stub second record when a
    # loss run has only one real policy term.
    loss_runs = [lr for lr in loss_runs
                  if (lr.get("Carrier") or lr.get("PolicyNumber")
                      or (lr.get("Claims") or []))]
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
    # Underwriter platforms / carriers / MGAs that author the submission
    # workspace but are NEITHER broker nor insured. Their email signatures
    # belong nowhere on the submission. (HabGen is the platform whose
    # workbook drives this entire pipeline.)
    underwriter_platform_signal = re.compile(
        r"\b(habgen|hab\s*gen)\b|@habgen\.com", re.IGNORECASE)
    agent_contacts_from_email = []
    insured_contacts_from_email = []
    for sig in email_signatures:
        c = {"Type": "Producer"}
        if sig.get("Name"): c["Name"] = sig["Name"]
        if sig.get("Title"): c["Title"] = sig["Title"]
        if sig.get("Email"): c["Email"] = sig["Email"]
        if sig.get("Phone"): c["Phone"] = sig["Phone"]
        company = (sig.get("Company") or "").lower()
        email_addr = (sig.get("Email") or "").lower()
        # Skip underwriter-platform signatures entirely — they're not
        # parties to the submission.
        if (underwriter_platform_signal.search(company)
                or underwriter_platform_signal.search(email_addr)):
            continue
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

    # ACORD-derived insured contacts (NamedInsured_Contact_*) take priority
    # over email signatures — they're the named contacts on the application,
    # whereas email signatures often pick up underwriter/AI replies.
    insured_contacts_from_acord = acord_mapped.get("insured_contacts") or []
    insured_contacts_combined = list(insured_contacts_from_acord)
    seen_emails = {c.get("Email") for c in insured_contacts_combined
                    if c.get("Email")}
    seen_names = {c.get("Name", "").lower() for c in insured_contacts_combined
                   if c.get("Name")}
    for c in insured_contacts_from_email:
        if c.get("Email") in seen_emails:
            continue
        if c.get("Name", "").lower() in seen_names:
            continue
        insured_contacts_combined.append(c)
    if insured_contacts_combined:
        insured["Contacts"] = insured_contacts_combined

    # RenewalFlag: ACORD 125 has no consistent "Type of Policy" checkboxes
    # filled in across submissions — derive from PriorPolicyNumber form.
    # "R/O" / "RO " / "Renewal" prefix on the prior policy number means
    # the same carrier is renewing; treat as Renewal. Bare policy numbers
    # without that prefix indicate the prior is just a reference (e.g.
    # for proof-of-coverage), not a same-carrier renewal — treat as New.
    policy_data = {k: v for k, v in acord_mapped.get("policy", {}).items() if v}
    prior_pn = (policy_data.get("PriorPolicyNumber") or "").strip()
    PLACEHOLDER_PN = re.compile(r"^(?:pending|n/?a|tbd|to follow|none)$",
                                  re.IGNORECASE)
    if prior_pn and PLACEHOLDER_PN.match(prior_pn):
        policy_data.pop("PriorPolicyNumber", None)
        prior_pn = ""
    RENEWAL_PREFIX = re.compile(r"^\s*(R/O|RO[\s-]|Renewal[\s-]|Ren[\s-])",
                                  re.IGNORECASE)
    renewal_flag = "Renewal" if (prior_pn and RENEWAL_PREFIX.match(prior_pn)) else "New"

    submission = {
        "Submission": submission_block,
        "PolicyInfo": {
            "RenewalFlag": renewal_flag,
            **policy_data,
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
