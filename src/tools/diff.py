"""Unified diff parsing.

The reviewers see the diff annotated with real line numbers, so every finding can
point at an exact line of the new file, and the code can then check that it does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


@dataclass
class DiffLine:
    kind: str  # "+" added, "-" removed, " " context
    text: str
    old_no: int | None
    new_no: int | None


@dataclass
class Hunk:
    header: str
    lines: list[DiffLine] = field(default_factory=list)


@dataclass
class FileDiff:
    path: str
    old_path: str
    status: str = "modified"  # added | deleted | modified | renamed
    hunks: list[Hunk] = field(default_factory=list)
    binary: bool = False

    @property
    def additions(self) -> int:
        return sum(1 for h in self.hunks for l in h.lines if l.kind == "+")

    @property
    def deletions(self) -> int:
        return sum(1 for h in self.hunks for l in h.lines if l.kind == "-")

    def added_lines(self) -> list[int]:
        return [l.new_no for h in self.hunks for l in h.lines if l.kind == "+"]

    def visible_lines(self) -> set[int]:
        """New-file line numbers that appear in the diff (added or context)."""
        return {l.new_no for h in self.hunks for l in h.lines if l.new_no is not None}

    def line_text(self, new_no: int) -> str | None:
        for h in self.hunks:
            for l in h.lines:
                if l.new_no == new_no:
                    return l.text
        return None

    def to_dict(self) -> dict:
        return {
            "path": self.path, "old_path": self.old_path, "status": self.status, "binary": self.binary,
            "additions": self.additions, "deletions": self.deletions,
            "hunks": [{"header": h.header, "lines": [vars(l) for l in h.lines]} for h in self.hunks],
        }


class DiffError(ValueError):
    pass


def _strip_prefix(path: str) -> str:
    path = path.strip().split("\t")[0]
    if path == "/dev/null":
        return path
    return path[2:] if path[:2] in ("a/", "b/") else path


def parse_diff(text: str) -> list[FileDiff]:
    """Parse a unified diff (git diff / GitHub .diff format) into files, hunks and numbered lines."""
    files: list[FileDiff] = []
    current: FileDiff | None = None
    hunk: Hunk | None = None
    old_no = new_no = 0

    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            parts = raw.split(" ")
            a = _strip_prefix(parts[2]) if len(parts) > 3 else ""
            b = _strip_prefix(parts[3]) if len(parts) > 3 else a
            current = FileDiff(path=b, old_path=a)
            files.append(current)
            hunk = None
            continue
        if raw.startswith("--- ") and (hunk is None or not _in_hunk(hunk, old_no, new_no)):
            if current is None:  # plain diff without the "diff --git" line
                current = FileDiff(path="", old_path="")
                files.append(current)
            current.old_path = _strip_prefix(raw[4:])
            continue
        if raw.startswith("+++ ") and current is not None and (hunk is None or not _in_hunk(hunk, old_no, new_no)):
            new_path = _strip_prefix(raw[4:])
            if new_path == "/dev/null":
                current.status = "deleted"
                current.path = current.old_path
            else:
                current.path = new_path
                if current.old_path == "/dev/null":
                    current.status = "added"
                elif current.old_path and current.old_path != new_path:
                    current.status = "renamed"
            hunk = None
            continue
        if current is None:
            continue
        if raw.startswith("new file mode"):
            current.status = "added"
        elif raw.startswith("deleted file mode"):
            current.status = "deleted"
        elif raw.startswith("rename to "):
            current.status, current.path = "renamed", raw[len("rename to "):]
        elif raw.startswith("Binary files"):
            current.binary = True
        elif m := _HUNK.match(raw):
            old_no, new_no = int(m.group(1)), int(m.group(3))
            hunk = Hunk(header=raw)
            hunk._old_end = old_no + int(m.group(2) or 1)  # type: ignore[attr-defined]
            hunk._new_end = new_no + int(m.group(4) or 1)  # type: ignore[attr-defined]
            current.hunks.append(hunk)
        elif hunk is not None and raw.startswith("+"):
            hunk.lines.append(DiffLine("+", raw[1:], None, new_no))
            new_no += 1
        elif hunk is not None and raw.startswith("-"):
            hunk.lines.append(DiffLine("-", raw[1:], old_no, None))
            old_no += 1
        elif hunk is not None and (raw.startswith(" ") or raw == ""):
            hunk.lines.append(DiffLine(" ", raw[1:], old_no, new_no))
            old_no += 1
            new_no += 1
        # "\ No newline at end of file" and other metadata lines are ignored

    files = [f for f in files if f.path and (f.hunks or f.binary or f.status != "modified")]
    if not files:
        raise DiffError("No file changes found. Paste a unified diff (e.g. the output of `git diff`).")
    return files


def _in_hunk(hunk: Hunk, old_no: int, new_no: int) -> bool:
    """True while a hunk still expects lines (so '--- x' inside a hunk is a removed line)."""
    return old_no < getattr(hunk, "_old_end", 0) or new_no < getattr(hunk, "_new_end", 0)


def render_for_review(files: list[FileDiff]) -> str:
    """Diff text annotated with new-file line numbers, for the reviewers to cite."""
    out = []
    for f in files:
        out.append(f"=== {f.path} ({f.status}, +{f.additions} -{f.deletions})")
        if f.binary:
            out.append("(binary file)")
            continue
        for h in f.hunks:
            out.append(h.header)
            for l in h.lines:
                num = f"{l.new_no:>5}" if l.new_no is not None else "     "
                out.append(f"{num} {l.kind} {l.text}")
        out.append("")
    return "\n".join(out)


def find_file(files: list[FileDiff], path: str) -> FileDiff | None:
    path = path.strip().lstrip("./")
    for f in files:
        if f.path == path:
            return f
    matches = [f for f in files if f.path.endswith("/" + path) or path.endswith("/" + f.path)]
    return matches[0] if len(matches) == 1 else None
