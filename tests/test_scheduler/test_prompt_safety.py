from __future__ import annotations

import pytest

from agentos.scheduler.prompt_safety import scan_cron_prompt


@pytest.mark.parametrize(
    "task",
    [
        "Tóm tắt email lúc 8 giờ",
        "To\u0301m ta\u0306\u0301t email lu\u0301c 8 gio\u031b\u0300",
        "זָכַר לִי מָחָר",
        "स्मरण दिलाना",
        "เตือนฉันพรุ่งนี้",
    ],
)
def test_combining_marks_are_allowed(task: str) -> None:
    blocked, reason = scan_cron_prompt(task)

    assert blocked is False
    assert reason == ""


@pytest.mark.parametrize(
    ("task", "character"),
    [
        ("hidden\u200btext", "\u200b"),
        ("control\x00text", "\x00"),
    ],
)
def test_invisible_format_and_control_characters_remain_blocked(task: str, character: str) -> None:
    blocked, reason = scan_cron_prompt(task)

    assert blocked is True
    assert repr(character) in reason


@pytest.mark.parametrize("character", ["\n", "\r", "\t"])
def test_allowed_whitespace_controls_remain_allowed(character: str) -> None:
    blocked, reason = scan_cron_prompt(f"first{character}second")

    assert blocked is False
    assert reason == ""
