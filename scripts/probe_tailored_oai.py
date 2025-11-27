#!/usr/bin/env python
"""Utility to exercise tailored OAI resumption tokens via the CLI."""

from __future__ import annotations

import argparse
import sys
from typing import Optional

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe tailored OAI resumption tokens against a live endpoint.")
    parser.add_argument("base_url", help="Base service URL, e.g. https://dev.arkumu.org")
    parser.add_argument("--verb", default="ListIdentifiers", choices=["ListIdentifiers", "ListRecords"], help="OAI verb to test")
    parser.add_argument("--metadata-prefix", default="oai_dc", help="Metadata prefix to request")
    parser.add_argument("--set-spec", dest="set_spec", help="Optional set parameter")
    parser.add_argument("--from-date", dest="from_date", help="Optional 'from' datestamp")
    parser.add_argument("--until-date", dest="until_date", help="Optional 'until' datestamp")
    parser.add_argument("--basic-auth", metavar="USER:PASS", help="HTTP Basic credentials to include in the requests.")
    parser.add_argument("--internal-bypass", action="store_true", help="Send X-INTERNAL-OAI-BYPASS=1 header")
    parser.add_argument("--pause-for-dataset-change", action="store_true", help="Pause so you can mutate data, then retry the stored token")
    parser.add_argument("--skip-tailored-resume", action="store_true", help="Skip the follow-up /oai/tailored/ request using the resumption token")
    parser.add_argument("--skip-db", action="store_true", help="Skip replaying the tailored token against /oai/db/")
    parser.add_argument("--skip-snapshot", action="store_true", help="Skip replaying the tailored token against /oai/")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        from arkumu.oaipmh.tailored_probe import TailoredProbeOptions, run_probe

        run_probe(
            TailoredProbeOptions(
                base_url=args.base_url,
                verb=args.verb,
                metadata_prefix=args.metadata_prefix,
                set_spec=args.set_spec,
                from_date=args.from_date,
                until_date=args.until_date,
                basic_auth=args.basic_auth,
                internal_bypass=args.internal_bypass,
                pause_for_dataset_change=args.pause_for_dataset_change,
                run_tailored_resume=not args.skip_tailored_resume,
                run_db_check=not args.skip_db,
                run_snapshot_check=not args.skip_snapshot,
            )
        )
    except Exception as exc:  # pragma: no cover - CLI helper
        print(f"Probe failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
