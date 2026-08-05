"""The bundled cron-watcher scripts.

Their whole contract is "print only what is new, print nothing otherwise" —
that is what makes a cron script job stay quiet — so these drive each script
end to end over ``file://`` URLs and assert on stdout and exit code.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "agentos"
    / "skills"
    / "bundled"
    / "cron-watchers"
    / "scripts"
)

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>First post</title><link>https://example.com/1</link><guid>1</guid></item>
<item><title>Second post</title><link>https://example.com/2</link><guid>2</guid></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id>tag:a</id><title>Atom one</title><link href="https://example.com/a"/></entry>
</feed>"""


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTOS_STATE_DIR", str(tmp_path / "state"))
    return tmp_path


def _run(script: str, *args: str, env_home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "AGENTOS_STATE_DIR": str(env_home / "state"),
            "HOME": str(env_home),
        },
        timeout=60,
    )


def _feed(tmp_path: Path, name: str, body: str) -> str:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path.as_uri()


# ── watch_rss ───────────────────────────────────────────────────────────────


def test_rss_first_run_is_silent(state_dir):
    url = _feed(state_dir, "feed.xml", RSS)

    result = _run("watch_rss.py", "--url", url, "--name", "t", env_home=state_dir)

    assert result.returncode == 0
    assert result.stdout == ""


def test_rss_first_run_can_report_everything(state_dir):
    url = _feed(state_dir, "feed.xml", RSS)

    result = _run(
        "watch_rss.py", "--url", url, "--name", "t", "--first-run-reports", env_home=state_dir
    )

    assert result.returncode == 0
    assert "First post" in result.stdout
    assert "Second post" in result.stdout


def test_rss_reports_only_what_is_new(state_dir):
    url = _feed(state_dir, "feed.xml", RSS)
    _run("watch_rss.py", "--url", url, "--name", "t", env_home=state_dir)

    _feed(
        state_dir,
        "feed.xml",
        RSS.replace(
            "</channel>",
            "<item><title>Third post</title><link>https://example.com/3</link>"
            "<guid>3</guid></item></channel>",
        ),
    )
    result = _run("watch_rss.py", "--url", url, "--name", "t", env_home=state_dir)

    assert result.returncode == 0
    assert "Third post" in result.stdout
    assert "First post" not in result.stdout


def test_rss_unchanged_feed_stays_silent(state_dir):
    url = _feed(state_dir, "feed.xml", RSS)
    _run("watch_rss.py", "--url", url, "--name", "t", env_home=state_dir)

    result = _run("watch_rss.py", "--url", url, "--name", "t", env_home=state_dir)

    assert result.returncode == 0
    assert result.stdout == ""


def test_rss_reads_atom_entries(state_dir):
    url = _feed(state_dir, "atom.xml", ATOM)

    result = _run(
        "watch_rss.py", "--url", url, "--name", "a", "--first-run-reports", env_home=state_dir
    )

    assert result.returncode == 0
    assert "Atom one" in result.stdout


def test_rss_fails_loudly_on_a_broken_feed(state_dir):
    url = _feed(state_dir, "broken.xml", "not xml at all")

    result = _run("watch_rss.py", "--url", url, "--name", "b", env_home=state_dir)

    assert result.returncode == 1
    assert "not valid XML" in result.stderr


def test_watermarks_are_per_name(state_dir):
    url = _feed(state_dir, "feed.xml", RSS)
    _run("watch_rss.py", "--url", url, "--name", "one", env_home=state_dir)

    result = _run(
        "watch_rss.py", "--url", url, "--name", "two", "--first-run-reports", env_home=state_dir
    )

    assert "First post" in result.stdout


# ── watch_http_json ─────────────────────────────────────────────────────────


def _events(tmp_path: Path, items: list[dict]) -> str:
    return _feed(tmp_path, "events.json", json.dumps({"data": {"events": items}}))


def test_json_reports_only_new_items(state_dir):
    url = _events(state_dir, [{"event_id": "a1", "title": "Deploy finished"}])
    args = ("--url", url, "--name", "j", "--id-field", "event_id", "--items-path", "data.events")
    _run("watch_http_json.py", *args, env_home=state_dir)

    _events(state_dir, [{"event_id": "a2", "title": "Alert cleared"}])
    result = _run("watch_http_json.py", *args, env_home=state_dir)

    assert result.returncode == 0
    assert result.stdout.strip() == "- Alert cleared"


def test_json_accepts_a_top_level_list(state_dir):
    url = _feed(state_dir, "list.json", json.dumps([{"id": "x", "name": "thing"}]))

    result = _run(
        "watch_http_json.py",
        "--url",
        url,
        "--name",
        "l",
        "--first-run-reports",
        env_home=state_dir,
    )

    assert result.returncode == 0
    assert "thing" in result.stdout


def test_json_reports_the_requested_fields(state_dir):
    url = _events(state_dir, [{"event_id": "a1", "title": "t", "sev": "high"}])

    result = _run(
        "watch_http_json.py",
        "--url",
        url,
        "--name",
        "f",
        "--id-field",
        "event_id",
        "--items-path",
        "data.events",
        "--field",
        "sev",
        "--first-run-reports",
        env_home=state_dir,
    )

    assert "sev='high'" in result.stdout


def test_json_fails_when_the_path_holds_no_list(state_dir):
    url = _events(state_dir, [])

    result = _run(
        "watch_http_json.py",
        "--url",
        url,
        "--name",
        "n",
        "--items-path",
        "data.missing",
        env_home=state_dir,
    )

    assert result.returncode == 1
    assert "Expected a list" in result.stderr


# ── watch_github ────────────────────────────────────────────────────────────


def test_github_rejects_a_malformed_repo(state_dir):
    result = _run("watch_github.py", "--repo", "not-a-repo", env_home=state_dir)

    assert result.returncode == 1
    assert "owner/name" in result.stderr


def test_github_rejects_an_unknown_scope(state_dir):
    result = _run("watch_github.py", "--repo", "o/n", "--scope", "stars", env_home=state_dir)

    assert result.returncode == 2  # argparse rejects the choice
