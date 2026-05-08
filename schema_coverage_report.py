"""
Compute schema coverage + accuracy assessment for submission_mapped.json
against the user-provided submission schema.

Coverage = (populated fields / total schema fields) per section.
Accuracy = three tiers per field:
  HIGH    — verified by bbox truth-table or pdfplumber direct read
  MEDIUM  — VLM gap-fill cross-validated against raw text
  LOW     — VLM-only, no cross-check (rare in our pipeline)
  UNKNOWN — field is in schema but not in any source doc
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent
MAPPED = json.load(open(REPO / "input_extracted" / "submission_mapped.json"))

# Schema field inventory (subset that's relevant to insurance submissions
# of this kind — not every theoretically-defined field).
# Format: {section: {field_path: (expected_source, accuracy_tier)}}
SCHEMA = {
    "Submission": {
        "SubmissionNumber":          ("(internal — assigned post-clearance)", "n/a"),
        "Status":                    ("hardcoded='Cleared'",                  "n/a"),
        "DateReceived":              ("email.docx first table timestamp",     "HIGH"),
        "QuoteNeededBy":             ("email subject 'Need asap'",            "MEDIUM"),
        "GLSelected":                ("derived from PolicyInfo.LOB",          "HIGH"),
        "PropertySelected":          ("derived from PolicyInfo.LOB",          "HIGH"),
        "MasterCarrierRecordName":   ("(carrier-side, post-quote)",           "n/a"),
        "ProductType":               ("hardcoded='HabGen'",                    "n/a"),
        "AssignedTo":                ("(internal underwriter)",                "n/a"),
        "Notes":                     ("email.docx subject line",              "HIGH"),
    },
    "PolicyInfo": {
        "RenewalFlag":               ("hardcoded='New' (no prior policy info)","MEDIUM"),
        "EffectiveDate":             ("ACORD p1 Policy_EffectiveDate_A",       "HIGH"),
        "ExpirationDate":            ("ACORD p1 Policy_ExpirationDate_A",      "HIGH"),
        "PriorPolicyNumber":         ("not in source docs",                    "UNKNOWN"),
        "TargetQuoteDate":           ("not in source docs",                    "UNKNOWN"),
        "LOB":                       ("ACORD p1 LineOfBusinessIndicator + email", "MEDIUM"),
        "TargetRates":               ("not in source docs",                    "UNKNOWN"),
    },
    "Insured": {
        "Name":                      ("VLM gap-fill + ACORD bbox",             "HIGH"),
        "DBANames":                  ("not in source docs",                    "UNKNOWN"),
        "Website":                   ("ACORD p1 NamedInsured_WebsiteAddressUrl_A","HIGH"),
        "EntityType":                ("ACORD p1 LegalEntity bbox checkboxes",  "HIGH"),
        "NAICSCode":                 ("ACORD p1 NamedInsured_NAICSCode_A (blank)", "UNKNOWN"),
        "SICCode":                   ("ACORD p1 NamedInsured_SICCode_A",       "HIGH"),
        "DescriptionOfOperations":   ("1800_North_Stone.docx narrative",       "HIGH"),
        "Addresses":                 ("ACORD p1 + VLM gap-fill + parser",      "HIGH"),
        "Contacts":                  ("ACORD p1 (none extracted yet)",         "MEDIUM"),
    },
    "OtherNamedInsureds": {
        "(none in this submission)":  ("not in source docs",                   "UNKNOWN"),
    },
    "BrokerRef": {
        "BrokerId":                  ("internal carrier ID",                   "n/a"),
        "ProducerId":                ("internal carrier ID",                   "n/a"),
    },
    "Agent": {
        "Name":                      ("VLM HEADER_agency_name",                "HIGH"),
        "NationalProducerNumber":    ("ACORD p1 (blank)",                      "UNKNOWN"),
        "FEIN":                      ("not in source docs",                    "UNKNOWN"),
        "OtherName":                 ("not in source docs",                    "UNKNOWN"),
        "Description":               ("not in source docs",                    "UNKNOWN"),
        "Website":                   ("not in source docs",                    "UNKNOWN"),
        "Hierarchy":                 ("(internal)",                            "n/a"),
        "Addresses":                 ("ACORD p1 Producer_MailingAddress_*",    "HIGH"),
        "Contacts":                  ("ACORD p1 Producer_ContactPerson_*",     "HIGH"),
    },
    "GeneralLiability": {
        "CoverageSelected":          ("derived from LOB",                      "HIGH"),
        "EmployeeBenefitsLiability": ("not requested",                          "UNKNOWN"),
    },
    "Property": {
        "CoverageSelected":          ("derived from LOB",                      "HIGH"),
        "PerLocationTimeElementReporting": ("not in source docs",              "UNKNOWN"),
        "AggregateBusinessIncomeLimit":     ("could derive from SOV BI sum",   "MEDIUM"),
    },
    "Locations[]": {
        "LocationNumber":            ("SOV Loc.# column",                      "HIGH"),
        "LocationName":              ("derived 'Location N' (no name in SOV)", "MEDIUM"),
        "Address":                   ("SOV Street/City/State/Zip",             "HIGH"),
        "GeneralLiability":          ("ACORD p1 GL exposure (not yet mapped)", "MEDIUM"),
    },
    "Buildings[]": {
        "BuildingNumber":            ("SOV Building # column",                 "HIGH"),
        "Description":               ("SOV occupancy description",             "MEDIUM"),
        "OccupancyClass":            ("not in SOV",                            "UNKNOWN"),
        "OccupancyType":             ("SOV Occupancy column ('Student Housing')", "HIGH"),
        "YearOfConstruction":        ("SOV Year Built column",                 "HIGH"),
        "ConstructionType":          ("SOV Construction Type column ('Frame')","HIGH"),
        "RoofType":                  ("SOV Type of Roof column ('Flat')",      "HIGH"),
        "TotalSqFt":                 ("SOV # Sq. Ft. Bldg column",             "HIGH"),
        "NoOfStories":               ("SOV # of stories column",               "HIGH"),
        "TotalUnits":                ("SOV # Hab Units column",                "HIGH"),
        "BedCount":                  ("not in SOV (just unit count)",          "UNKNOWN"),
        "FullySprinklered":          ("SOV Sprinklered % == 100",              "HIGH"),
        "ProtectiveSafeguards":      ("not explicitly in SOV",                 "UNKNOWN"),
        "P9Description":             ("not in source docs",                    "UNKNOWN"),
        "Building.BuildingCoverageFlag": ("derived (Building RCV present)",    "HIGH"),
        "Building.BuildingLimit":    ("SOV Building RCV column",                "HIGH"),
        "Building.Building100RcValue": ("SOV Building RCV column",              "HIGH"),
        "Building.Rate":             ("not in SOV (carrier-computed)",         "n/a"),
        "Bpp.BppCoverageFlag":       ("derived (BPP > 0)",                     "HIGH"),
        "Bpp.BppLimit":              ("SOV BPP column",                        "HIGH"),
        "Bpp.Rate":                  ("not in SOV (carrier-computed)",         "n/a"),
        "BusinessIncomeLimit":       ("SOV Loss of Rents column",              "HIGH"),
    },
    "SecuredParties": {
        "(none in this submission)":  ("not in source docs (no mortgagee data)","UNKNOWN"),
    },
    "LossRuns[]": {
        "Carrier":                   ("Farmers LR header.company",             "HIGH"),
        "PolicyNumber":              ("Farmers LR header.policy_number",       "HIGH"),
        "LOB":                       ("inferred from filename / line_of_business","HIGH"),
        "EvaluationDate":            ("Farmers LR header.valuation_date",      "HIGH"),
        "PolicyEffectiveDate":       ("not extracted (no per-policy term)",    "UNKNOWN"),
        "PolicyExpirationDate":      ("not extracted",                         "UNKNOWN"),
        "NoKnownLossesLast5Years":   ("derived (Claims is empty)",             "HIGH"),
        "Claims[]":                  ("pdfplumber tables + VLM detail rows",   "HIGH"),
    },
    "Attachments[]": {
        "Type":                      ("inferred from filename pattern",        "HIGH"),
        "FileName":                  ("input_docs/Input/* listing",            "HIGH"),
        "MimeType":                  ("from extension",                        "HIGH"),
        "Description":               ("from filename stem",                    "HIGH"),
        "AttachmentId":              ("(internal)",                            "n/a"),
        "DestinationFolder":         ("(internal)",                            "n/a"),
        "Source":                    ("(internal)",                            "n/a"),
        "UploadedDate":              ("(internal)",                            "n/a"),
    },
}


def is_populated(d, path):
    """Check if a dotted path is populated in the mapped JSON."""
    parts = path.split(".")
    cur = d
    for p in parts:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return False
    return cur not in (None, "", [], {})


def populated_section(submission, section, schema_fields):
    """Count how many schema fields are populated in this section."""
    if section.endswith("[]"):
        # Check each item in array
        section_name = section[:-2]
        if section_name == "Buildings":
            # Buildings live under Locations[].Buildings[]
            items = []
            for loc in submission.get("Locations", []):
                items.extend(loc.get("Buildings", []))
        else:
            items = submission.get(section_name, [])
        if not items:
            return 0, len(schema_fields)
        # For arrays, count avg coverage across items
        total_pop = 0
        total_fields = len(schema_fields) * len(items)
        for item in items:
            for fp in schema_fields:
                if "." in fp:
                    parent, child = fp.split(".", 1)
                    if isinstance(item.get(parent), dict) and is_populated(
                            item[parent], child):
                        total_pop += 1
                else:
                    if is_populated(item, fp):
                        total_pop += 1
        return total_pop, total_fields
    else:
        sec = submission.get(section, {})
        pop = sum(1 for fp in schema_fields if is_populated(sec, fp))
        return pop, len(schema_fields)


# ── Build report ──

print("=" * 80)
print(" SUBMISSION SCHEMA COVERAGE & ACCURACY REPORT")
print(" Source: input_extracted/submission_mapped.json")
print("=" * 80)

total_pop = 0
total_fields = 0

for section, fields in SCHEMA.items():
    pop, n = populated_section(MAPPED, section, fields)
    total_pop += pop
    total_fields += n
    cov = (pop / n * 100) if n else 0

    print(f"\n── {section} — {pop}/{n} ({cov:.0f}% coverage) ──")
    for fp, (source, tier) in fields.items():
        if section.endswith("[]"):
            section_name = section[:-2]
            if section_name == "Buildings":
                items = [b for loc in MAPPED.get("Locations", [])
                         for b in loc.get("Buildings", [])]
            else:
                items = MAPPED.get(section_name, [])
            if not items:
                p_count = 0; total = 0
            else:
                total = len(items)
                p_count = 0
                for item in items:
                    if "." in fp:
                        parent, child = fp.split(".", 1)
                        if isinstance(item.get(parent), dict) and is_populated(
                                item[parent], child):
                            p_count += 1
                    else:
                        if is_populated(item, fp):
                            p_count += 1
            mark = "✓" if p_count == total and total > 0 else "○" if p_count > 0 else "✗"
            count_str = f"{p_count}/{total}"
        else:
            ok = is_populated(MAPPED.get(section, {}), fp)
            mark = "✓" if ok else "✗"
            count_str = "    "
        print(f"    {mark} [{tier:8}] {count_str:6} {fp:38} ← {source}")

print("\n" + "=" * 80)
print(f" OVERALL: {total_pop}/{total_fields} fields populated "
      f"({total_pop/total_fields*100:.1f}% schema coverage)")
print("=" * 80)

# Tier summary
tier_counts = {"HIGH": [0, 0], "MEDIUM": [0, 0], "LOW": [0, 0],
               "UNKNOWN": [0, 0], "n/a": [0, 0]}
for section, fields in SCHEMA.items():
    for fp, (_, tier) in fields.items():
        if section.endswith("[]"):
            section_name = section[:-2]
            if section_name == "Buildings":
                items = [b for loc in MAPPED.get("Locations", [])
                         for b in loc.get("Buildings", [])]
            else:
                items = MAPPED.get(section_name, [])
            for item in items:
                if "." in fp:
                    parent, child = fp.split(".", 1)
                    populated = (isinstance(item.get(parent), dict) and
                                 is_populated(item[parent], child))
                else:
                    populated = is_populated(item, fp)
                tier_counts[tier][1] += 1
                if populated:
                    tier_counts[tier][0] += 1
        else:
            populated = is_populated(MAPPED.get(section, {}), fp)
            tier_counts[tier][1] += 1
            if populated:
                tier_counts[tier][0] += 1

print(f"\n ACCURACY-TIER BREAKDOWN (populated / total)")
print(f"    HIGH     {tier_counts['HIGH'][0]:3d} / {tier_counts['HIGH'][1]:3d}  "
      f"(verified by bbox truth-table or direct read)")
print(f"    MEDIUM   {tier_counts['MEDIUM'][0]:3d} / {tier_counts['MEDIUM'][1]:3d}  "
      f"(VLM gap-fill cross-validated)")
print(f"    LOW      {tier_counts['LOW'][0]:3d} / {tier_counts['LOW'][1]:3d}  "
      f"(VLM-only, no cross-check)")
print(f"    UNKNOWN  {tier_counts['UNKNOWN'][0]:3d} / {tier_counts['UNKNOWN'][1]:3d}  "
      f"(field in schema but no source data)")
print(f"    n/a      {tier_counts['n/a'][0]:3d} / {tier_counts['n/a'][1]:3d}  "
      f"(carrier-internal: assigned post-clearance, not in incoming docs)")

# Reachable coverage = exclude n/a + unknown
reachable = sum(tier_counts[t][1] for t in ["HIGH", "MEDIUM", "LOW"])
populated_reachable = sum(tier_counts[t][0] for t in ["HIGH", "MEDIUM", "LOW"])
print(f"\n REACHABLE COVERAGE (excluding n/a + unknown):")
print(f"    {populated_reachable} / {reachable} = "
      f"{populated_reachable/reachable*100:.1f}%")
