"""Management command to probe tailored OAI endpoints using live data."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from arkumu.oaipmh.tailored_probe import TailoredProbeOptions, run_probe


class Command(BaseCommand):
    help = "Probe the tailored OAI endpoint and resumption tokens against a live base URL."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--base-url",
            required=True,
            help="Base service URL, e.g. https://dev.arkumu.org",
        )
        parser.add_argument(
            "--verb",
            default="ListIdentifiers",
            choices=["ListIdentifiers", "ListRecords"],
            help="OAI-PMH verb to request",
        )
        parser.add_argument(
            "--metadata-prefix",
            default="oai_dc",
            help="Metadata prefix to request",
        )
        parser.add_argument("--set-spec", dest="set_spec", help="Optional OAI set spec")
        parser.add_argument("--from-date", dest="from_date", help="Optional 'from' datestamp")
        parser.add_argument("--until-date", dest="until_date", help="Optional 'until' datestamp")
        parser.add_argument(
            "--basic-auth",
            metavar="USER:PASS",
            help="HTTP Basic credentials used for the requests",
        )
        parser.add_argument(
            "--internal-bypass",
            action="store_true",
            help="Send X-INTERNAL-OAI-BYPASS=1 header",
        )
        parser.add_argument(
            "--pause-for-dataset-change",
            action="store_true",
            help="Pause to allow manual dataset tweaks before re-playing the token",
        )
        parser.add_argument(
            "--skip-tailored-resume",
            action="store_true",
            help="Skip the follow-up /oai/tailored/ call using the returned resumption token",
        )
        parser.add_argument(
            "--skip-db",
            action="store_true",
            help="Skip replaying the tailored token against /oai/db/",
        )
        parser.add_argument(
            "--skip-snapshot",
            action="store_true",
            help="Skip replaying the tailored token against /oai/",
        )

    def handle(self, *unused_args, **options):
        try:
            run_probe(
                TailoredProbeOptions(
                    base_url=options["base_url"],
                    verb=options["verb"],
                    metadata_prefix=options["metadata_prefix"],
                    set_spec=options.get("set_spec"),
                    from_date=options.get("from_date"),
                    until_date=options.get("until_date"),
                    basic_auth=options.get("basic_auth"),
                    internal_bypass=options.get("internal_bypass", False),
                    pause_for_dataset_change=options.get("pause_for_dataset_change", False),
                    run_tailored_resume=not options.get("skip_tailored_resume", False),
                    run_db_check=not options.get("skip_db", False),
                    run_snapshot_check=not options.get("skip_snapshot", False),
                )
            )
        except Exception as exc:  # pragma: no cover - CLI helper
            raise CommandError(str(exc))
