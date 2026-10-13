#!/usr/bin/env python3
"""Derive the optional BuildKit CA-secret recipe from the canonical Dockerfile."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

GENERATED_HEADER = (
    "# Generated from Dockerfile by tools/generate_cloud_dockerfile.py; do not edit.\n"
    "# Optional CA trust is supplied only through the build_ca_bundle BuildKit secret.\n"
)
TRANSFORMATIONS = (
    (
        "RUN cd theme/static_src && npm ci\n",
        "RUN --mount=type=secret,id=build_ca_bundle \\\n"
        "    if [ -f /run/secrets/build_ca_bundle ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca_bundle; fi; \\\n"
        "    cd theme/static_src && npm ci\n",
    ),
    (
        "RUN pip install --no-cache-dir --require-hashes -r requirements.lock\n",
        "RUN --mount=type=secret,id=build_ca_bundle \\\n"
        "    if [ -f /run/secrets/build_ca_bundle ]; then export PIP_CERT=/run/secrets/build_ca_bundle; fi; \\\n"
        "    pip install --no-cache-dir --require-hashes -r requirements.lock\n",
    ),
)


def render_cloud_dockerfile(canonical: str) -> str:
    """Fail on recipe drift instead of silently omitting or duplicating trust."""
    if "--mount=type=secret" in canonical:
        raise ValueError("The canonical Dockerfile must not contain secret mounts")
    generated = canonical
    for original, replacement in TRANSFORMATIONS:
        pattern = re.compile("^" + re.escape(original), re.MULTILINE)
        if len(pattern.findall(canonical)) != 1:
            raise ValueError("Expected exactly one canonical installation block for each CA-secret transformation")
        match = pattern.search(generated)
        if match is None:
            raise ValueError("The generated recipe lost a required installation block")
        generated = generated[: match.start()] + replacement + generated[match.end() :]
    return GENERATED_HEADER + generated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Fail if Dockerfile.cloud is missing or differs; do not write"
    )
    args = parser.parse_args()
    project = Path(__file__).resolve().parent.parent
    destination = project / "Dockerfile.cloud"
    try:
        generated = render_cloud_dockerfile((project / "Dockerfile").read_text(encoding="utf-8")).encode("utf-8")
        if args.check:
            if not destination.is_file() or destination.read_bytes() != generated:
                parser.exit(1, "Dockerfile.cloud is missing or stale; run python tools/generate_cloud_dockerfile.py\n")
        else:
            destination.write_bytes(generated)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Cannot generate Dockerfile.cloud: {error}\n")
    print("Dockerfile.cloud matches Dockerfile" if args.check else "Generated Dockerfile.cloud from Dockerfile")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
