#!/usr/bin/env python3
"""Checks every document has a valid <file>.metadata.json sidecar before upload.

A document without "department" or "classification" metadata is invisible to
non-admin users (the access filter requires both), so catch it here.

Usage: python3 scripts/validate_metadata.py sample-docs/documents
"""

import json
import sys
from pathlib import Path

SUPPORTED = {".pdf", ".md", ".txt", ".html", ".htm", ".doc", ".docx", ".csv", ".xls", ".xlsx"}
DEPARTMENTS = {"hr", "finance", "it", "projects", "training"}
CLASSIFICATIONS = {"public", "internal", "confidential"}
MAX_METADATA_BYTES = 10 * 1024


def check(root: Path) -> list:
    problems = []
    docs = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED and not p.name.endswith(".metadata.json")]
    if not docs:
        problems.append(f"No supported documents found under {root}")
    for doc in sorted(docs):
        rel = doc.relative_to(root)
        sidecar = doc.with_name(doc.name + ".metadata.json")
        if not sidecar.exists():
            problems.append(f"{rel}: missing {sidecar.name}")
            continue
        if sidecar.stat().st_size > MAX_METADATA_BYTES:
            problems.append(f"{rel}: metadata file is larger than 10 KB")
        try:
            attrs = json.loads(sidecar.read_text())["metadataAttributes"]
        except (json.JSONDecodeError, KeyError, TypeError):
            problems.append(f"{rel}: metadata must be JSON with a 'metadataAttributes' object")
            continue
        dept = attrs.get("department")
        if dept not in DEPARTMENTS:
            problems.append(f"{rel}: department '{dept}' must be one of {sorted(DEPARTMENTS)}")
        elif rel.parts[0] != dept:
            problems.append(f"{rel}: stored in folder '{rel.parts[0]}' but department is '{dept}'")
        if attrs.get("classification") not in CLASSIFICATIONS:
            problems.append(f"{rel}: classification must be one of {sorted(CLASSIFICATIONS)}")
    for orphan in root.rglob("*.metadata.json"):
        if not orphan.with_name(orphan.name[: -len(".metadata.json")]).exists():
            problems.append(f"{orphan.relative_to(root)}: no matching document")
    return problems


if __name__ == "__main__":
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "sample-docs/documents")
    issues = check(folder)
    if issues:
        print("Metadata problems found:")
        for issue in issues:
            print(f"  - {issue}")
        sys.exit(1)
    print(f"Metadata OK for all documents under {folder}")
