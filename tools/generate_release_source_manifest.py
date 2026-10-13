#!/usr/bin/env python3
"""Generate a source manifest from an explicit reviewed/tested Git commit.

This reads immutable Git blobs, never the working tree, and writes a new
artifact outside the checkout by default caller choice. It does not establish
that tests passed, deploy services, or alter historical manifests/receipts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


def git_read(project: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(project), *args],
        check=False,
        capture_output=True,
    )
    if result.returncode:
        raise ValueError("The requested committed source is unavailable in this Git repository")
    return result.stdout


def generate_source_manifest(project: Path, reviewed_commit: str) -> dict:
    from tools.telegram_release_inspect import (
        CURRENT_SOURCE_ANCHORS,
        SOURCE_MANIFEST_TYPE,
        SOURCE_MANIFEST_VERSION,
        validate_source_manifest,
    )

    if not re.fullmatch(r"[0-9a-f]{40}", reviewed_commit):
        raise ValueError("--source-commit must be a full lowercase Git commit SHA")
    if git_read(project, "cat-file", "-t", reviewed_commit).strip() != b"commit":
        raise ValueError("--source-commit must identify a commit, not a tree, tag, or blob")
    tree = git_read(project, "rev-parse", "--verify", f"{reviewed_commit}^{{tree}}").decode().strip()
    anchors = {}
    for path in CURRENT_SOURCE_ANCHORS:
        metadata = git_read(project, "ls-tree", reviewed_commit, "--", path).decode().split()
        if not metadata or metadata[0] not in ("100644", "100755") or metadata[1] != "blob":
            raise ValueError("Committed release source is missing a regular runtime anchor file")
        anchors[path] = hashlib.sha256(git_read(project, "cat-file", "blob", f"{reviewed_commit}:{path}")).hexdigest()
    return validate_source_manifest(
        {
            "record_type": SOURCE_MANIFEST_TYPE,
            "schema_version": SOURCE_MANIFEST_VERSION,
            "reviewed_source_commit": reviewed_commit,
            "reviewed_source_tree": tree,
            "source_anchors": anchors,
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--source-commit", required=True, help="Full immutable SHA of the reviewed and tested source")
    parser.add_argument(
        "--output", type=Path, required=True, help="New manifest artifact; existing files are not overwritten"
    )
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        manifest = generate_source_manifest(args.project.resolve(), args.source_commit)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    except (OSError, ValueError):
        parser.error("Cannot generate manifest: require a complete committed source and a new writable output path")
    print(
        f"Source manifest generated from commit {manifest['reviewed_source_commit']} ({len(manifest['source_anchors'])} anchors)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
