"""Fetch command implementation."""

from argparse import Namespace
from datetime import date
from pathlib import Path

from ..config import load_oauth_config_from_env
from ..errors import InvalidArgumentsError
from ..exit_codes import ExitCode
from ..fetcher import fetch_records
from ..models import FetchRequest
from ..output import write_records


def run_fetch(args: Namespace) -> int:
    """Run the `fetch` subcommand."""

    request = build_fetch_request(args)
    oauth_config = None if request.dry_run else load_oauth_config_from_env()
    records = fetch_records(request, oauth_config)
    write_records(records, request.output_path, request.output_format)
    return int(ExitCode.SUCCESS)


def build_fetch_request(args: Namespace) -> FetchRequest:
    """Validate and normalize fetch arguments into a request object."""

    latest = bool(args.latest)
    start_raw = args.start_date
    end_raw = args.end_date

    if latest and (start_raw or end_raw):
        raise InvalidArgumentsError(
            "--latest cannot be combined with --start-date/--end-date"
        )

    if not latest and (not start_raw or not end_raw):
        raise InvalidArgumentsError(
            "Provide both --start-date and --end-date when --latest is not used"
        )

    start_date = _parse_iso_date(start_raw, "--start-date") if start_raw else None
    end_date = _parse_iso_date(end_raw, "--end-date") if end_raw else None

    if start_date and end_date and start_date > end_date:
        raise InvalidArgumentsError("--start-date must be earlier than or equal to --end-date")

    output_path = Path(args.output).expanduser()
    output_format = _resolve_output_format(args.format, output_path)

    return FetchRequest(
        latest=latest,
        start_date=start_date,
        end_date=end_date,
        output_path=output_path,
        output_format=output_format,
        dry_run=bool(args.dry_run),
    )


def _parse_iso_date(value: str, argument_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidArgumentsError(
            f"Invalid value for {argument_name}: '{value}'. Expected YYYY-MM-DD"
        ) from exc


def _resolve_output_format(explicit_format: str | None, output_path: Path) -> str:
    if explicit_format:
        return explicit_format

    suffix = output_path.suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix == ".json":
        return "json"

    raise InvalidArgumentsError(
        "Could not infer output format from filename extension. "
        "Use --format csv|json or provide a .csv/.json output file."
    )
