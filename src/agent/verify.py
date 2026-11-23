"""Deterministic checks on the lead reviewer's report, plus a fallback merge.

Models can cite a wrong line or a file that isn't in the diff. Before a finding is
shown, code checks it against the parsed diff:
  exact       the line exists in the diff
  adjusted    moved to the nearest changed line (within 3 lines)
  unverified  the line could not be matched; kept, but flagged
Findings for files that aren't in the diff are dismissed.
"""

from __future__ import annotations

from ..tools import FileDiff, find_file
from .schemas import SEVERITY_ORDER

SNAP_DISTANCE = 3


def ground_report(report: dict, files: list[FileDiff]) -> dict:
    kept, dismissed = [], list(report.get("dismissed", []))
    for finding in report.get("findings", []):
        f = find_file(files, finding["file"])
        if f is None:
            dismissed.append({"title": finding["title"], "raised_by": finding.get("raised_by", []),
                              "reason": f"'{finding['file']}' is not part of this diff."})
            continue
        kept.append({**finding, "file": f.path, **_locate(f, finding["line"])})

    kept.sort(key=lambda x: (SEVERITY_ORDER.get(x["severity"], 9), x["file"], x["line"]))
    for i, finding in enumerate(kept, 1):
        finding["id"] = f"F{i}"

    verdict = report.get("verdict", "comment")
    serious = any(f["severity"] in ("critical", "high") for f in kept)
    if serious and verdict != "request_changes":
        verdict = "request_changes"  # keep the verdict consistent with what was found
    elif not kept and verdict == "request_changes":
        verdict = "approve"
    return {**report, "verdict": verdict, "findings": kept, "dismissed": dismissed}


def _locate(f: FileDiff, line: int) -> dict:
    if line <= 0:
        return {"line": 0, "location": "file", "code": None}
    if line in f.visible_lines():
        return {"line": line, "location": "exact", "code": f.line_text(line)}
    added = f.added_lines()
    nearest = min(added, key=lambda n: abs(n - line), default=None)
    if nearest is not None and abs(nearest - line) <= SNAP_DISTANCE:
        return {"line": nearest, "location": "adjusted", "code": f.line_text(nearest)}
    return {"line": line, "location": "unverified", "code": None}


def fallback_report(reviews: list[dict], reason: str) -> dict:
    """If the lead reviewer fails, merge specialist findings mechanically (exact duplicates only)."""
    merged: dict[tuple, dict] = {}
    for review in reviews:
        for f in review.get("findings", []):
            key = (f["file"], f["line"], f["title"].lower())
            if key in merged:
                merged[key]["raised_by"].append(review["reviewer"])
            else:
                merged[key] = {**f, "category": review["reviewer"], "raised_by": [review["reviewer"]]}
    findings = list(merged.values())
    serious = any(f["severity"] in ("critical", "high") for f in findings)
    return {
        "verdict": "request_changes" if serious else ("comment" if findings else "approve"),
        "summary": f"The lead reviewer was unavailable ({reason}), so specialist findings are listed unmerged.",
        "findings": findings,
        "dismissed": [],
    }
