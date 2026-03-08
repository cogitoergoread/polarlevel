# Polar Pulse Meter Data with Level Info

This repository targets a Python CLI for fetching Polar AccessLink heart-rate data and enriching it with level/elevation metadata for analysis.

## Project Status

Current state in this repository:
- CLI scaffold exists at `src/polarlevel/`.
- `python -m polarlevel fetch ...` is implemented with argument validation and CSV/JSON output.
- Polar AccessLink exercise transaction flow is implemented for non-dry-run mode.
- OAuth token refresh and token persistence are implemented.

## Implemented in Scaffold

- Command structure with `fetch` subcommand.
- Date/input validation (`--latest` or `--start-date` + `--end-date`).
- Schema-conformant CSV and JSON export.
- Standardized exit codes for CLI automation.
- `--dry-run` mode that writes sample records without API calls.
- Live API flow: create transaction, list exercises, download exercise details, commit transaction.
- Retry handling for transient HTTP failures (`429`, `5xx`).
- Token handling flow: load from store/env, refresh on `401`, persist rotated tokens.

## Planned Next

- Improve sample extraction coverage for additional AccessLink payload variants.

## Python and Dependency Baseline

Source of truth is `pyproject.toml`:
- Python version: `>=3.14`
- Runtime dependencies: `requests`
- Build backend: `pdm-backend`

## Installation (Current)

```bash
python -m pip install -e .
python -c "import polarlevel; print('polarlevel import ok')"
polarlevel --help
```

## CLI Usage

Supported entrypoints:
- `python -m polarlevel`
- `polarlevel`

Examples:
- Latest available data:
	`python -m polarlevel fetch --latest --output output.json`
- Date range data:
	`python -m polarlevel fetch --start-date YYYY-MM-DD --end-date YYYY-MM-DD --output output.csv`
- Dry-run serialization check:
	`python -m polarlevel fetch --latest --output output.json --dry-run`

Argument and time rules:
- `--start-date` and `--end-date` use `YYYY-MM-DD` (ISO date).
- Date range is inclusive on both boundaries.
- Output timestamps are normalized to UTC in ISO-8601 format.

## OAuth2 Configuration

Required environment variables:

```bash
export POLAR_USER_ID="..."
export POLAR_CLIENT_ID="..."
export POLAR_CLIENT_SECRET="..."
export POLAR_REDIRECT_URI="http://localhost:8000/callback"
```

Token input options:

```bash
# Option A: direct environment tokens
export POLAR_ACCESS_TOKEN="..."
export POLAR_REFRESH_TOKEN="..."

# Option B: token store file containing
# {"access_token": "...", "refresh_token": "...", "access_token_expires_at_utc": "2026-03-09T12:00:00Z"}
export POLAR_TOKEN_STORE_PATH=".secrets/polar_tokens.json"
```

Optional environment variables:

```bash
export POLAR_ACCESS_TOKEN_EXPIRES_AT_UTC="2026-03-09T12:00:00Z"
export POLAR_ACCESSLINK_BASE_URL="https://www.polaraccesslink.com"
export POLAR_OAUTH_TOKEN_URL="https://polarremote.com/v2/oauth2/token"
export POLAR_ACCESSLINK_TIMEOUT_SECONDS="30"
export POLAR_ACCESSLINK_RETRY_COUNT="3"
```

Current behavior:
- Non-dry-run mode validates required OAuth settings and token source availability.
- Access token and refresh token are loaded from token store when present, otherwise from environment.
- Access token expiry metadata is loaded from token store or `POLAR_ACCESS_TOKEN_EXPIRES_AT_UTC` when available.
- If expiry metadata shows the access token is near expiry, the CLI refreshes proactively before the first AccessLink request.
- Non-dry-run mode performs live API calls using the exercise transaction flow.
- On HTTP `401`, the CLI refreshes the access token via refresh-token grant and retries the request.
- Refreshed tokens are persisted to `POLAR_TOKEN_STORE_PATH`.
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

## Error Handling

Behavior:
- Argument validation errors return non-zero exits.
- Missing OAuth env configuration returns an authentication error in non-dry-run mode.
- Token refresh failures return an authentication error.
- Transient HTTP failures (`429`, `5xx`) are retried with exponential backoff.
- Invalid AccessLink responses or exhausted retries return API failure.
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
2. Export OAuth2 environment variables.
3. Run a live fetch command:
	`python -m polarlevel fetch --latest --output output.csv`
4. Inspect output columns.

Dry-run mode remains available when you want to validate output serialization without API calls:

1. Run:
	`python -m polarlevel fetch --latest --output output.csv --dry-run`
2. Inspect output file.

## Testing and Validation

Current test coverage includes:
- CLI argument validation.
- Dry-run output file generation.
- Authentication env validation path.
- API failure path handling in non-dry-run mode.
- Mocked AccessLink transaction flow and date-range filtering.
- OAuth config loading and token-store fallback.
- OAuth token refresh and persistence.

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

