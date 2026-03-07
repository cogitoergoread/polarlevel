"""Output serialization for CSV and JSON exports."""

import csv
import json
from pathlib import Path

from .errors import OutputWriteError
from .models import TelemetryRecord

RECORD_FIELDS = (
    "user_id",
    "session_id",
    "timestamp_utc",
    "heart_rate_bpm",
    "latitude",
    "longitude",
    "elevation_m",
    "source",
)


def write_records(
    records: list[TelemetryRecord],
    output_path: Path,
    output_format: str,
) -> None:
    """Serialize records to output path in CSV or JSON format."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [record.to_dict() for record in records]

    try:
        if output_format == "csv":
            _write_csv(rows, output_path)
            return

        if output_format == "json":
            _write_json(rows, output_path)
            return

        raise OutputWriteError(f"Unsupported output format: {output_format}")
    except OutputWriteError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise OutputWriteError(f"Failed writing output file '{output_path}': {exc}") from exc


def _write_csv(rows: list[dict[str, object]], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RECORD_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_json(rows: list[dict[str, object]], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2)
        handle.write("\n")
