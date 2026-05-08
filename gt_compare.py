"""
Ground-truth comparison harness.

Compares submission_mapped.json vs a hand-curated GT JSON, field by
field. Reports per-field correct / wrong / missing / extra and an
overall accuracy number.

Usage:
  python gt_compare.py path/to/gt.json [path/to/output.json]

Comparison rules:
  - Strings: case-insensitive, whitespace-collapsed
  - Numbers: equal within 0.5% relative tolerance OR within ±$1 absolute
  - Dates: parsed and compared as dates (M/D/YYYY ↔ YYYY-MM-DD ok)
  - Booleans: strict equality
  - Arrays: element-wise comparison after sorting (when items have a
    'Name' or 'BuildingNumber' or similar key) OR positional otherwise
  - null in GT means "field can be absent or null in output"
  - "*" in GT means "any non-empty value is acceptable"

Each leaf comparison is one of:
  CORRECT   GT value matches output value
  WRONG     GT and output both populated, but disagree
  MISSING   GT has a value, output is missing/null
  EXTRA     output has a value, GT says "should be empty/null"
  N/A       GT marked as unverifiable
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parent
DEFAULT_OUTPUT = REPO / "input_extracted" / "submission_mapped.json"


def _norm_str(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _try_parse_date(s) -> str | None:
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%m-%d-%Y",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(s.split("T")[0] if "T" in s else s,
                                       fmt.split("T")[0] if "T" in s else fmt
                                       ).strftime("%Y-%m-%d")
        except Exception:
            pass
    return None


def _compare_leaf(gt_val, out_val) -> str:
    """Return verdict for two leaf values."""
    if gt_val is None or gt_val == "":
        if out_val in (None, "", [], {}, False):
            return "CORRECT"  # both absent
        return "EXTRA"
    if gt_val == "*":
        return "CORRECT" if out_val not in (None, "", [], {}) else "MISSING"
    if gt_val == "N/A":
        return "N/A"

    if out_val in (None, ""):
        return "MISSING"

    # Boolean
    if isinstance(gt_val, bool) or isinstance(out_val, bool):
        return "CORRECT" if bool(gt_val) == bool(out_val) else "WRONG"

    # Numeric
    if isinstance(gt_val, (int, float)) and not isinstance(gt_val, bool):
        try:
            ov = float(str(out_val).replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            return "WRONG"
        gv = float(gt_val)
        if abs(gv - ov) < 1.0:  # within $1 absolute
            return "CORRECT"
        if gv != 0 and abs(gv - ov) / abs(gv) < 0.005:  # 0.5% relative
            return "CORRECT"
        return "WRONG"

    # Date
    gt_date = _try_parse_date(str(gt_val))
    out_date = _try_parse_date(str(out_val))
    if gt_date and out_date:
        return "CORRECT" if gt_date == out_date else "WRONG"

    # String — case-insensitive, whitespace-collapsed
    if _norm_str(gt_val) == _norm_str(out_val):
        return "CORRECT"
    # Substring tolerance for long descriptions
    if (len(str(gt_val)) > 30
            and _norm_str(gt_val) in _norm_str(out_val)):
        return "CORRECT"
    return "WRONG"


def _walk_compare(gt, out, path: str = "", results: list = None) -> list:
    """Walk gt and out together, recording per-leaf verdicts."""
    if results is None:
        results = []

    if isinstance(gt, dict):
        if not isinstance(out, dict):
            out = {}
        for k, v in gt.items():
            new_path = f"{path}.{k}" if path else k
            _walk_compare(v, out.get(k), new_path, results)
        return results

    if isinstance(gt, list):
        if not isinstance(out, list):
            out = []
        # If items are dicts with a clear key, sort by it for matching
        sort_keys = ["Name", "BuildingNumber", "ClaimNumber", "FileName",
                     "LocationNumber", "Email"]
        sort_key = None
        if gt and isinstance(gt[0], dict):
            for k in sort_keys:
                if k in gt[0]:
                    sort_key = k; break

        gt_items = list(gt)
        out_items = list(out)
        if sort_key:
            def _k(d):
                v = d.get(sort_key) if isinstance(d, dict) else None
                return _norm_str(str(v)) if v else ""
            gt_items = sorted(gt_items, key=_k)
            out_items = sorted(out_items, key=_k)

        # Pair by index
        for i, gt_item in enumerate(gt_items):
            out_item = out_items[i] if i < len(out_items) else None
            new_path = f"{path}[{i}]"
            _walk_compare(gt_item, out_item, new_path, results)
        # Extra items in output (not in gt)
        for i in range(len(gt_items), len(out_items)):
            new_path = f"{path}[{i}]"
            results.append({"path": new_path, "gt": None,
                             "out": "(extra item)", "verdict": "EXTRA"})
        return results

    verdict = _compare_leaf(gt, out)
    results.append({"path": path, "gt": gt, "out": out, "verdict": verdict})
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gt", help="Ground-truth JSON file")
    ap.add_argument("output", nargs="?", default=str(DEFAULT_OUTPUT))
    ap.add_argument("--show-correct", action="store_true",
                     help="Also list CORRECT fields (default: only show issues)")
    args = ap.parse_args()

    gt = json.load(open(args.gt))
    out = json.load(open(args.output))

    # Strip metadata keys from GT (anything starting with _)
    def _clean(d):
        if isinstance(d, dict):
            return {k: _clean(v) for k, v in d.items() if not k.startswith("_")}
        if isinstance(d, list):
            return [_clean(x) for x in d]
        return d
    gt = _clean(gt)

    results = _walk_compare(gt, out)

    counts = {"CORRECT": 0, "WRONG": 0, "MISSING": 0, "EXTRA": 0, "N/A": 0}
    for r in results:
        counts[r["verdict"]] += 1

    print(f"Comparing  GT: {args.gt}")
    print(f"  vs OUTPUT: {args.output}")
    print()
    print("=" * 70)
    print("ISSUES")
    print("=" * 70)
    for r in results:
        v = r["verdict"]
        if v == "CORRECT" and not args.show_correct:
            continue
        if v == "N/A":
            continue
        marker = {"CORRECT": "✓", "WRONG": "✗", "MISSING": "?", "EXTRA": "!"}[v]
        gt_s = repr(r["gt"])[:50]
        out_s = repr(r["out"])[:50]
        print(f"  {marker} [{v:8s}] {r['path']}")
        print(f"            GT:  {gt_s}")
        print(f"            OUT: {out_s}")

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    total = sum(counts.values()) - counts["N/A"]
    if total == 0:
        print("  (no fields scored)")
        return
    correct_pct = counts["CORRECT"] / total * 100
    print(f"  CORRECT  : {counts['CORRECT']:3d} / {total} ({correct_pct:.1f}%)")
    print(f"  WRONG    : {counts['WRONG']:3d}")
    print(f"  MISSING  : {counts['MISSING']:3d}  (in GT but not output)")
    print(f"  EXTRA    : {counts['EXTRA']:3d}  (in output but GT says empty)")
    print(f"  N/A      : {counts['N/A']:3d}  (skipped)")
    print()
    populated = counts["CORRECT"] + counts["WRONG"]
    if populated:
        precision = counts["CORRECT"] / populated * 100
        print(f"  PRECISION (correct / [correct + wrong]) = {precision:.1f}%")
    if counts["CORRECT"] + counts["MISSING"]:
        recall = counts["CORRECT"] / (counts["CORRECT"] + counts["MISSING"]) * 100
        print(f"  RECALL    (correct / [correct + missing]) = {recall:.1f}%")


if __name__ == "__main__":
    sys.exit(main())
