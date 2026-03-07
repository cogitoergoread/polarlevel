# Polar Pulse Meter Data with Level Info

This repository targets a Python CLI for fetching Polar AccessLink heart-rate data and enriching it with level/elevation metadata for analysis.

## Project Status

Current state in this repository:
- CLI scaffold exists at `src/polarlevel/`.
- `python -m polarlevel fetch ...` is implemented with argument validation and CSV/JSON output.
- Real Polar API integration is not implemented yet; use `--dry-run` to validate end-to-end CLI flow.

## Implemented in Scaffold

- Command structure with `fetch` subcommand.
- Date/input validation (`--latest` or `--start-date` + `--end-date`).
- Schema-conformant CSV and JSON export.
- Standardized exit codes for CLI automation.
- `--dry-run` mode that writes sample records without API calls.

## Planned Next

- Integrate [Polar Open AccessLink](https://www.polar.com/accesslink-api/) API calls.
- Implement OAuth token refresh and token persistence.
- Replace dry-run placeholder records with live fetched records.
- Add retry logic for transient API failures.

## Python and Dependency Baseline

Source of truth is `pyproject.toml`:
- Python version: `>=3.14`
- Runtime dependencies: currently none declared
- Build backend: `pdm-backend`

Notes:
- Earlier drafts referenced `requests`, `pandas`, and `oauthlib`; these are expected future runtime dependencies once the CLI implementation is added.

## Installation (Current)

```bash
python -m pip install -e .
python -c "import polarlevel; print('polarlevel import ok')"
polarlevel --help
```

## CLI Usage (Current Scaffold)

Supported entrypoints:
- `python -m polarlevel`
- `polarlevel`

Examples:
- Latest available data:
  `python -m polarlevel fetch --latest --output output.json --dry-run`
- Date range data:
  `python -m polarlevel fetch --start-date YYYY-MM-DD --end-date YYYY-MM-DD --output output.csv --dry-run`

Argument and time rules:
- `--start-date` and `--end-date` use `YYYY-MM-DD` (ISO date).
- Date range is inclusive on both boundaries.
- Output timestamps are normalized to UTC in ISO-8601 format.

## OAuth2 Configuration (Scaffold Validation)

Expected environment variables:

```bash
export POLAR_CLIENT_ID="..."
export POLAR_CLIENT_SECRET="..."
export POLAR_REDIRECT_URI="http://localhost:8000/callback"
export POLAR_ACCESS_TOKEN="..."
export POLAR_REFRESH_TOKEN="..."
```

Current scaffold behavior:
- Non-dry-run mode validates these variables and fails fast if any are missing.
- Live API calls and token refresh are not implemented yet.
- Do not commit credentials or token files.

## Output Schema Contract

CSV and JSON outputs should represent the same record fields:

| Field | Type | Description |
|---|---|---|
| `user_id` | string | Polar user identifier |
| `session_id` | string | Source training/session identifier |
| `timestamp_utc` | string | ISO-8601 UTC timestamp |
| `heart_rate_bpm` | integer | Heart rate in beats per minute |
| `latitude` | number or null | WGS84 latitude |
| `longitude` | number or null | WGS84 longitude |
| `elevation_m` | number or null | Elevation/level in meters |
| `source` | string | Data source identifier (for example `polar-accesslink`) |

Serialization rules:
- CSV uses one row per sample with the column names above.
- JSON uses an array of objects with the same field names.
- Missing optional numeric fields are serialized as empty values in CSV and `null` in JSON.

## Error Handling Contract (Planned)

Behavior:
- Argument validation errors return non-zero exits.
- Missing OAuth env configuration returns an authentication error in non-dry-run mode.
- Non-dry-run fetch currently exits as API failure because live integration is still pending.
- Output write and serialization errors are surfaced as output failures.

CLI exit codes:

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Unexpected runtime error |
| `2` | Invalid CLI arguments |
| `3` | Authentication failure |
| `4` | API/network failure after retries |
| `5` | Output write/serialization failure |

## End-to-End Quickstart (Scaffold)

Use this flow to validate local setup now:

1. Install in editable mode:
	`python -m pip install -e .`
2. Run a dry-run fetch command:
	`python -m polarlevel fetch --latest --output output.csv --dry-run`
3. Inspect output file.

For non-dry-run auth validation only:

1. Export OAuth2 environment variables.
2. Run:
	`python -m polarlevel fetch --latest --output output.csv`
3. Expect an API failure exit until live integration is implemented.

## Testing and Validation

Current test coverage includes:
- CLI argument validation.
- Dry-run output file generation.
- Authentication env validation path.
- API placeholder failure path in non-dry-run mode.

Run tests:

```bash
pytest -q
```

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Unexpected runtime error |
| `2` | Invalid CLI arguments |
| `3` | Authentication failure |
| `4` | API/network failure |
| `5` | Output write/serialization failure |

