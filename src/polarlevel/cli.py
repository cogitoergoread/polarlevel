"""Command-line interface for polarlevel."""

from argparse import ArgumentParser, Namespace
from collections.abc import Sequence
import sys

from .commands.fetch import run_fetch
from .errors import PolarLevelError
from .exit_codes import ExitCode


def build_parser() -> ArgumentParser:
    """Build and return the top-level CLI parser."""

    parser = ArgumentParser(
        prog="polarlevel",
        description="Fetch and export Polar data with level information.",
    )

    subparsers = parser.add_subparsers(dest="command")

    fetch_parser = subparsers.add_parser(
        "fetch",
        help="Fetch Polar data and export it as CSV or JSON",
    )
    scope_group = fetch_parser.add_mutually_exclusive_group(required=True)
    scope_group.add_argument(
        "--latest",
        action="store_true",
        help="Fetch the latest available data window",
    )
    scope_group.add_argument(
        "--start-date",
        dest="start_date",
        help="Start date in YYYY-MM-DD format",
    )

    fetch_parser.add_argument(
        "--end-date",
        help="End date in YYYY-MM-DD format",
    )
    fetch_parser.add_argument(
        "--output",
        required=True,
        help="Output file path (.csv or .json)",
    )
    fetch_parser.add_argument(
        "--format",
        choices=("csv", "json"),
        default=None,
        help="Output format. If omitted, inferred from output extension.",
    )
    fetch_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip real API calls and write sample schema-conformant output",
    )
    fetch_parser.set_defaults(handler=run_fetch)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint. Returns a process exit code integer."""

    parser = build_parser()

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else int(ExitCode.UNEXPECTED_ERROR)
        if code == 0:
            return int(ExitCode.SUCCESS)
        return int(ExitCode.INVALID_ARGUMENTS)

    return _dispatch(args, parser)


def _dispatch(args: Namespace, parser: ArgumentParser) -> int:
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return int(ExitCode.INVALID_ARGUMENTS)

    try:
        return int(handler(args))
    except PolarLevelError as exc:
        print(str(exc), file=sys.stderr)
        return int(exc.exit_code)
    except Exception as exc:  # pragma: no cover - defensive catch-all
        print(f"Unexpected runtime error: {exc}", file=sys.stderr)
        return int(ExitCode.UNEXPECTED_ERROR)
