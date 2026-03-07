"""CLI behavior tests for the polarlevel scaffold."""

import json
from pathlib import Path

import pytest

from polarlevel.cli import main
from polarlevel.exit_codes import ExitCode


def test_help_returns_success() -> None:
    assert main(["--help"]) == int(ExitCode.SUCCESS)


def test_fetch_requires_output() -> None:
    assert main(["fetch", "--latest"]) == int(ExitCode.INVALID_ARGUMENTS)


def test_fetch_rejects_incomplete_date_range() -> None:
    code = main(
        [
            "fetch",
            "--start-date",
            "2026-01-01",
            "--output",
            "out.csv",
        ]
    )
    assert code == int(ExitCode.INVALID_ARGUMENTS)


def test_fetch_rejects_inverted_date_range() -> None:
    code = main(
        [
            "fetch",
            "--start-date",
            "2026-02-01",
            "--end-date",
            "2026-01-01",
            "--output",
            "out.csv",
        ]
    )
    assert code == int(ExitCode.INVALID_ARGUMENTS)


def test_fetch_dry_run_writes_json(tmp_path: Path) -> None:
    output_path = tmp_path / "output.json"
    code = main(
        [
            "fetch",
            "--latest",
            "--output",
            str(output_path),
            "--dry-run",
        ]
    )

    assert code == int(ExitCode.SUCCESS)
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert len(payload) > 0
    assert payload[0]["source"] == "polar-accesslink"


@pytest.fixture
def oauth_keys() -> tuple[str, ...]:
    return (
        "POLAR_CLIENT_ID",
        "POLAR_CLIENT_SECRET",
        "POLAR_REDIRECT_URI",
        "POLAR_ACCESS_TOKEN",
        "POLAR_REFRESH_TOKEN",
    )


def test_fetch_without_auth_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, oauth_keys: tuple[str, ...]) -> None:
    output_path = tmp_path / "output.csv"
    for key in oauth_keys:
        monkeypatch.delenv(key, raising=False)

    code = main(
        [
            "fetch",
            "--latest",
            "--output",
            str(output_path),
        ]
    )
    assert code == int(ExitCode.AUTHENTICATION_FAILURE)


def test_fetch_with_auth_non_dry_run_returns_api_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oauth_env = {
        "POLAR_CLIENT_ID": "id",
        "POLAR_CLIENT_SECRET": "secret",
        "POLAR_REDIRECT_URI": "http://localhost:8000/callback",
        "POLAR_ACCESS_TOKEN": "access-token",
        "POLAR_REFRESH_TOKEN": "refresh-token",
    }
    for key, value in oauth_env.items():
        monkeypatch.setenv(key, value)

    output_path = tmp_path / "output.csv"
    code = main(
        [
            "fetch",
            "--latest",
            "--output",
            str(output_path),
        ]
    )

    assert code == int(ExitCode.API_FAILURE)
