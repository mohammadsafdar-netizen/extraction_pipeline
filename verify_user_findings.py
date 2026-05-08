"""
Verify user's manual-analysis findings against the current merged output.

For each page+field the user flagged as problematic, look it up in the
current merged_qwen3vl8b/Acord_App_1800_North_Stone_LLC_2026_merged.json
and report whether the issue is resolved, still present, or n/a.
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent
MERGED = REPO / "merged_qwen3vl8b" / "Acord_App_1800_North_Stone_LLC_2026_merged.json"
PURE_VLM = REPO / "vllm_qwen3vl8b" / "Acord_App_1800_North_Stone_LLC_2026_targeted.json"

merged = json.load(open(MERGED))
pure = json.load(open(PURE_VLM))


def merged_page(n):
    return merged["pages"].get(f"page_{n}", {}).get("fields", {})


def pure_page(n):
    for p in pure.get("pages", []):
        if p.get("page") == n:
            return p.get("data") or {}
    return {}


def true_checkboxes_matching(p, *kw):
    return [(k, f["value"]) for k, f in p.items()
            if f.get("type") == "checkbox" and f["value"]
            and any(s.lower() in k.lower() for s in kw)]


def vlm_keys_matching(p, *kw):
    return [(k, f["value"]) for k, f in p.items()
            if k.startswith("vlm_") and any(s.lower() in k.lower() for s in kw)]


def status(label, ok, detail=""):
    mark = "✓ FIXED" if ok else "✗ STILL WRONG"
    print(f"  [{mark}] {label}{(': ' + detail) if detail else ''}")


print("=" * 70)
print("USER MANUAL ANALYSIS — VERIFICATION REPORT")
print("=" * 70)

# ── Page 1 ──
print("\n── Page 1 ──")
p1 = merged_page(1)

# 1a. 15 LOBs all listed as checked
lob_keys = [k for k in p1
            if any(s in k for s in ["LineOfBusiness_Coverage", "LineOfBusiness_Indicator"])]
true_lobs = [k for k in lob_keys if p1[k].get("type") == "checkbox" and p1[k]["value"]]
status("15 LOBs all listed", len(true_lobs) == 0,
       f"{len(true_lobs)} LOB checkboxes true (expected 0)")

# 1b. POLICY_INFORMATION.billing_plan: AGENCY (label-as-value)
billing_vlm = vlm_keys_matching(p1, "billing_plan")
billing_vlm_garbage = any("agency" in str(v).lower() or "direct" in str(v).lower()
                           for k, v in billing_vlm)
status("billing_plan: AGENCY label-leak", not billing_vlm_garbage,
       f"{len(billing_vlm)} billing_plan vlm keys: {billing_vlm}")

# 1c. entity_type: INDIVIDUAL
ent_true = true_checkboxes_matching(p1, "LegalEntity")
ent_str = ", ".join(k.split("_")[-1].replace("[0]","") for k, _ in ent_true)
status("entity_type: only LLC checked", len(ent_true) == 1 and "LimitedLiability" in ent_true[0][0],
       f"true: [{ent_str}]")

# ── Page 2 ──
print("\n── Page 2 ──")
p2 = merged_page(2)

# LBAKER as contact_name
contact_name_vlm = vlm_keys_matching(p2, "contact_name")
lbaker_leak = any("lbaker" in str(v).lower() or "lmoss" in str(v).lower()
                  for k, v in contact_name_vlm)
status("LBAKER captured as contact_name", not lbaker_leak,
       f"contact_name vlm: {[v for _, v in contact_name_vlm]}")

# contact_type: HOME (phone-type label leak)
contact_type_vlm = vlm_keys_matching(p2, "contact_type")
type_leak = any(str(v).lower() in ("home", "bus", "cell")
                for k, v in contact_type_vlm)
status("contact_type: HOME label-leak", not type_leak,
       f"contact_type vlm: {contact_type_vlm}")

# city_limits / interest label leaks
cl_vlm = vlm_keys_matching(p2, "city_limits")
in_vlm = vlm_keys_matching(p2, "interest")
cl_leak = any(str(v).lower() in ("inside", "outside") for k, v in cl_vlm)
in_leak = any(str(v).lower() in ("owner", "tenant") for k, v in in_vlm)
status("city_limits: INSIDE label-leak", not cl_leak,
       f"city_limits vlm: {cl_vlm}")
status("interest: OWNER label-leak", not in_leak,
       f"interest vlm: {in_vlm}")

# NATURE_OF_BUSINESS — only "service" should be true
nob_true = true_checkboxes_matching(p2, "NatureBusiness", "BusinessType")
status("Only NATURE_OF_BUSINESS.service true",
       len(nob_true) == 1 and "service" in nob_true[0][0].lower(),
       f"true: {[k for k, _ in nob_true]}")

# ── Page 8 (signature, empty) ──
print("\n── Page 8 (empty signature page) ──")
p8 = merged_page(8)
n_vlm_p8 = sum(1 for k in p8 if k.startswith("vlm_"))
status("Empty signature page hallucinates SIGNATURE/DATE/etc",
       n_vlm_p8 == 0,
       f"{n_vlm_p8} vlm_* keys (expected 0)")

# ── Page 11 (signature, empty) ──
print("\n── Page 11 (empty signature page) ──")
p11 = merged_page(11)
n_vlm_p11 = sum(1 for k in p11 if k.startswith("vlm_"))
status("Empty signature page hallucinates",
       n_vlm_p11 == 0,
       f"{n_vlm_p11} vlm_* keys (expected 0)")

# ── Page 16 (GL coverage trigger pair) ──
print("\n── Page 16 ──")
p16 = merged_page(16)
cm = p16.get("GeneralLiability_ClaimsMadeIndicator_A", {}).get("value")
oc = p16.get("GeneralLiability_OccurrenceIndicator_A", {}).get("value")
status("claims_made + occurrence both-true", cm is False and oc is True,
       f"claims_made={cm}, occurrence={oc}")

# ── Pages 8, 11, 14, 15, 17, 19, 20, 22, 23, 24, 25 — empty pages ──
print("\n── Empty/signature pages (no real data filled) ──")
empty_pages_user_called_out = [8, 11, 14, 15, 17, 19, 20, 22, 23, 24, 25]
for pg in empty_pages_user_called_out:
    pmerged = merged_page(pg)
    n_vlm = sum(1 for k in pmerged if k.startswith("vlm_"))
    n_cb_true = sum(1 for k, f in pmerged.items()
                    if f.get("type") == "checkbox" and f["value"])
    n_text = sum(1 for k, f in pmerged.items()
                 if f.get("type") == "text" and not k.startswith("vlm_"))
    n_total = len(pmerged)
    print(f"  page {pg:2d}: {n_vlm:2d} vlm_*  |  {n_cb_true:2d} cb-true  |  {n_text:2d} bbox-text  |  {n_total:3d} total fields")

# ── BUILDING_IMPROVEMENTS / HEATING / BURGLAR_ALARM / FIRE_PROTECTION on p7 ──
print("\n── Page 7 (improvements/heating/alarm checkboxes) ──")
p7 = merged_page(7)
bi_true = true_checkboxes_matching(p7, "BuildingImprovement")
heat_true = true_checkboxes_matching(p7, "Heating")
alarm_true = true_checkboxes_matching(p7, "BurglarAlarm", "FireProtection", "ProtectiveDevice")
print(f"  BuildingImprovement true: {len(bi_true)}  → {[k.split('_')[-2:] for k, _ in bi_true[:5]]}")
print(f"  Heating true:              {len(heat_true)}  → {[k.split('_')[-2:] for k, _ in heat_true[:5]]}")
print(f"  Alarm/Protection true:     {len(alarm_true)}  → {[k.split('_')[-2:] for k, _ in alarm_true[:5]]}")
