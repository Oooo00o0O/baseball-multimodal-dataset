#!/usr/bin/env python3
"""Merge independent MLB curation result ZIPs without silent overwrites."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from team_bundles import consolidate_team_bundles, write_consolidation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundles", nargs="+", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = consolidate_team_bundles(args.bundles)
    write_consolidation(args.output_dir, result)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
