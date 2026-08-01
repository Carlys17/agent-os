from __future__ import annotations

import pytest

from agentos.engine.verification_ledger import (
    VerificationLedger,
    build_verification_nudge,
    is_code_path,
    looks_like_verification,
)

# ---------------------------------------------------------------------------
# what counts as code
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["src/app.py", "index.ts", "main.go", "Makefile", "Dockerfile", "scripts/deploy", "a/b/c.rs"],
)
def test_source_files_are_code(path: str) -> None:
    assert is_code_path(path) is True


@pytest.mark.parametrize(
    "path",
    ["README.md", "docs/guide.mdx", "notes.txt", "data.csv", "config.yaml", "logo.png"],
)
def test_prose_and_data_files_are_not_code(path: str) -> None:
    # Demanding a test run for a README edit teaches the model to ignore the nudge.
    assert is_code_path(path) is False


def test_windows_separators_are_understood() -> None:
    assert is_code_path(r"src\app.py") is True
    assert is_code_path(r"docs\guide.md") is False


def test_empty_path_is_not_code() -> None:
    assert is_code_path("") is False
    assert is_code_path("   ") is False


# ---------------------------------------------------------------------------
# what counts as verification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "pytest -q",
        "uv run pytest tests/",
        "npm test",
        "pnpm check",
        "yarn lint",
        "make test",
        "cargo test",
        "go test ./...",
        "npx tsc --noEmit",
        "ruff check src",
        "uv run mypy src/agentos",
        "/usr/local/bin/pytest",
        "dotnet test",
    ],
)
def test_verification_commands_are_recognised(command: str) -> None:
    assert looks_like_verification(command) is True


@pytest.mark.parametrize(
    "command",
    [
        "ls -la",
        "git status",
        "cat README.md",
        "go run main.go",
        "cargo run",
        "echo done",
        "",
    ],
)
def test_ordinary_commands_are_not_verification(command: str) -> None:
    assert looks_like_verification(command) is False


def test_a_build_counts_as_evidence_but_running_the_program_does_not() -> None:
    # A build fails on code that does not compile, which is the most common way
    # an edit breaks something — that is evidence. Executing the program is not:
    # it says nothing about the paths the edit touched.
    assert looks_like_verification("cargo build --release") is True
    assert looks_like_verification("cargo check") is True
    assert looks_like_verification("cargo run") is False
    assert looks_like_verification("go run main.go") is False


def test_an_unparseable_command_does_not_raise() -> None:
    assert looks_like_verification("pytest 'unclosed") is True


# ---------------------------------------------------------------------------
# the ledger
# ---------------------------------------------------------------------------


def test_a_turn_that_changed_nothing_needs_nothing() -> None:
    assert VerificationLedger().decide().needs_verification is False


def test_editing_code_without_checking_is_flagged() -> None:
    ledger = VerificationLedger()
    ledger.record_mutation(["src/app.py"])

    decision = ledger.decide()

    assert decision.needs_verification is True
    assert decision.reason == "unverified_code_changes"
    assert decision.changed_paths == ("src/app.py",)


def test_running_a_check_after_the_edit_clears_it() -> None:
    ledger = VerificationLedger()
    ledger.record_mutation(["src/app.py"])
    ledger.record_command("uv run pytest -q")

    assert ledger.decide().needs_verification is False


def test_a_check_before_the_last_edit_does_not_count() -> None:
    # Evidence gathered before an edit says nothing about that edit — this is
    # the whole reason the ledger tracks order rather than mere presence.
    ledger = VerificationLedger()
    ledger.record_mutation(["src/app.py"])
    ledger.record_command("pytest -q")
    ledger.record_mutation(["src/other.py"])

    assert ledger.decide().needs_verification is True


def test_editing_only_prose_is_never_flagged() -> None:
    ledger = VerificationLedger()
    ledger.record_mutation(["README.md", "docs/guide.md"])

    decision = ledger.decide()

    assert decision.needs_verification is False
    assert decision.reason == "no_code_changes"


def test_a_prose_edit_after_a_verified_code_edit_does_not_reopen_it() -> None:
    ledger = VerificationLedger()
    ledger.record_mutation(["src/app.py"])
    ledger.record_command("pytest -q")
    ledger.record_mutation(["CHANGELOG.md"])

    assert ledger.decide().needs_verification is False


def test_messaging_surfaces_are_exempt() -> None:
    ledger = VerificationLedger()
    ledger.record_mutation(["src/app.py"])

    decision = ledger.decide(is_messaging_surface=True)

    assert decision.needs_verification is False
    assert decision.reason == "messaging_surface"


def test_the_same_file_edited_twice_is_listed_once() -> None:
    ledger = VerificationLedger()
    ledger.record_mutation(["src/app.py"])
    ledger.record_mutation(["src/app.py"])

    assert ledger.decide().changed_paths == ("src/app.py",)


# ---------------------------------------------------------------------------
# the nudge
# ---------------------------------------------------------------------------


def test_the_nudge_names_the_files_that_changed() -> None:
    ledger = VerificationLedger()
    ledger.record_mutation(["src/app.py", "src/other.py"])

    nudge = build_verification_nudge(ledger.decide())

    assert "src/app.py" in nudge
    assert "src/other.py" in nudge


def test_a_long_change_list_is_summarised() -> None:
    ledger = VerificationLedger()
    ledger.record_mutation([f"src/f{i}.py" for i in range(20)])

    nudge = build_verification_nudge(ledger.decide())

    assert "and 12 more" in nudge
    assert len(nudge) < 600


def test_no_nudge_when_nothing_is_owed() -> None:
    assert build_verification_nudge(VerificationLedger().decide()) == ""
