"""Isolated PyPI client — fully mocked, never hits the network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agentos.compat import pypi_client


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _patch_get(monkeypatch: pytest.MonkeyPatch, fn: Any) -> None:
    import httpx

    monkeypatch.setattr(httpx, "get", fn)


def test_latest_version_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, **_: Any) -> _FakeResponse:
        assert "use-agent-os" in url
        return _FakeResponse(200, {"info": {"version": "2026.8.1"}})

    _patch_get(monkeypatch, fake_get)
    assert pypi_client.latest_version() == "2026.8.1"


def test_offline_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, **_: Any) -> _FakeResponse:
        raise OSError("network down")

    _patch_get(monkeypatch, fake_get)
    assert pypi_client.latest_version() is None


def test_non_200_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get(monkeypatch, lambda url, **_: _FakeResponse(404, {}))
    assert pypi_client.latest_version() is None


def test_malformed_body_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get(monkeypatch, lambda url, **_: _FakeResponse(200, ValueError("bad json")))
    assert pypi_client.latest_version() is None


def test_missing_version_field_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get(monkeypatch, lambda url, **_: _FakeResponse(200, {"info": {}}))
    assert pypi_client.latest_version() is None


def test_timeout_is_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_get(url: str, **kwargs: Any) -> _FakeResponse:
        seen.update(kwargs)
        return _FakeResponse(200, {"info": {"version": "1.0"}})

    _patch_get(monkeypatch, fake_get)
    pypi_client.latest_version(timeout=2.0)
    assert seen["timeout"] == 2.0


def test_yanked_latest_falls_back_to_last_good_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The latest upload being yanked must not be recommended (#1971)."""

    def fake_get(url: str, **_: Any) -> _FakeResponse:
        return _FakeResponse(
            200,
            {
                "info": {"version": "2026.9.14"},
                "releases": {
                    "2026.9.13": [{"yanked": False}],
                    "2026.9.14": [{"yanked": True, "yanked_reason": "critical flaw"}],
                },
            },
        )

    _patch_get(monkeypatch, fake_get)
    assert pypi_client.latest_version() == "2026.9.13"


def test_yanked_info_version_with_no_good_release_falls_back_to_canonical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All releases yanked: fall back to PyPI's canonical info.version."""

    def fake_get(url: str, **_: Any) -> _FakeResponse:
        return _FakeResponse(
            200,
            {
                "info": {"version": "2026.9.14"},
                "releases": {"2026.9.14": [{"yanked": True}]},
            },
        )

    _patch_get(monkeypatch, fake_get)
    assert pypi_client.latest_version() == "2026.9.14"


def test_missing_files_entry_treated_as_yanked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A release key with an empty/missing file list is not recommendable."""

    def fake_get(url: str, **_: Any) -> _FakeResponse:
        return _FakeResponse(
            200,
            {
                "info": {"version": "2026.9.14"},
                "releases": {"2026.9.13": [{"yanked": False}], "2026.9.14": []},
            },
        )

    _patch_get(monkeypatch, fake_get)
    assert pypi_client.latest_version() == "2026.9.13"


def test_prerelease_latest_not_recommended_over_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stable installs are never pointed at an rc/alpha/dev tail (#1970)."""

    def fake_get(url: str, **_: Any) -> _FakeResponse:
        return _FakeResponse(
            200,
            {
                "info": {"version": "2026.9.14rc1"},
                "releases": {
                    "2026.9.13": [{"yanked": False}],
                    "2026.9.14rc1": [{"yanked": False}],
                    "2026.9.14a1": [{"yanked": False}],
                    "2026.9.14.dev3": [{"yanked": False}],
                },
            },
        )

    _patch_get(monkeypatch, fake_get)
    assert pypi_client.latest_version() == "2026.9.13"


def test_prerelease_only_falls_back_to_canonical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only pre-releases exist: degrade to the canonical info.version."""

    def fake_get(url: str, **_: Any) -> _FakeResponse:
        return _FakeResponse(
            200,
            {
                "info": {"version": "2026.9.14rc1"},
                "releases": {"2026.9.14rc1": [{"yanked": False}]},
            },
        )

    _patch_get(monkeypatch, fake_get)
    assert pypi_client.latest_version() == "2026.9.14rc1"


def test_wider_release_segment_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Releases sort by version order, not dict order."""

    def fake_get(url: str, **_: Any) -> _FakeResponse:
        return _FakeResponse(
            200,
            {
                "info": {"version": "2026.9.13"},
                "releases": {
                    "2026.9.9": [{"yanked": False}],
                    "2026.9.10": [{"yanked": False}],
                    "2026.10.1": [{"yanked": False}],
                },
            },
        )

    _patch_get(monkeypatch, fake_get)
    assert pypi_client.latest_version() == "2026.10.1"


def test_no_releases_key_falls_back_to_canonical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A body without ``releases`` still answers from ``info.version``."""

    def fake_get(url: str, **_: Any) -> _FakeResponse:
        return _FakeResponse(200, {"info": {"version": "2026.8.1"}})

    _patch_get(monkeypatch, fake_get)
    assert pypi_client.latest_version() == "2026.8.1"


def test_write_state_is_atomic(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent readers never see a truncated state file (#1968)."""

    path = tmp_path / "update_notice.json"
    pypi_client.write_state(path, 100.0, "2026.9.13", "cli")
    assert pypi_client.read_state(path) == {
        "cli": {"last_checked": 100.0},
        "latest": "2026.9.13",
    }

    # Simulate a concurrent reader while the write is in flight: the real
    # file must never lose its content between read and replace.
    seen_partial: list[str] = []

    def spy_read_text(*args: Any, **kwargs: Any) -> str:
        # Bypass the patched read_text: an unbuffered open() sees exactly
        # what is on disk at this instant. It must never be empty/truncated.
        with open(path, encoding="utf-8") as fh:
            seen_partial.append(fh.read())
        return json.dumps({"cli": {"last_checked": 100.0}})

    monkeypatch.setattr(Path, "read_text", spy_read_text)
    pypi_client.write_state(path, 200.0, None, "cli")
    monkeypatch.undo()
    # The snapshot the concurrent reader saw is the COMPLETE previous state —
    # never a truncated or empty file.
    assert seen_partial == [json.dumps({"cli": {"last_checked": 100.0}, "latest": "2026.9.13"})]
    assert pypi_client.read_state(path) == {"cli": {"last_checked": 200.0}}

    # No temp files left behind.
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "update_notice.json"]
    assert leftovers == []
