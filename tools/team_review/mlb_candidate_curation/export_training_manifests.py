#!/usr/bin/env python3
"""Generate reviewed audit and task-specific CSV manifests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from exports import WindowPolicy, build_exports, load_review_batches, write_exports
from stores import CandidateInventoryStore


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA = PROJECT_ROOT / "data" / "review" / "mlb_candidate_curation"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventory",
        type=Path,
        default=DEFAULT_DATA / "candidate_inventory.csv",
    )
    parser.add_argument(
        "--reviews-dir",
        type=Path,
        default=DEFAULT_DATA / "reviews",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_DATA / "exports",
    )
    parser.add_argument("--pre-contact-sec", type=float, default=1.0)
    parser.add_argument("--post-contact-sec", type=float, default=0.5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    inventory = CandidateInventoryStore(args.inventory)
    reviews = load_review_batches(args.reviews_dir)
    policy = WindowPolicy(
        pre_contact_sec=args.pre_contact_sec,
        post_contact_sec=args.post_contact_sec,
    )
    exports = build_exports(inventory.all(), reviews, policy)
    write_exports(args.output_dir, exports)
    print(
        json.dumps(
            {name: len(rows) for name, rows in exports.items()},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
