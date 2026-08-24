"""Write a fake ``agent-browser`` the OS can actually execute.

The adapter spawns its engine with ``create_subprocess_exec``, so a fake engine
has to be a real executable — and the obvious form, a Python file with a
shebang, only works on POSIX. Windows ignores shebangs, so those tests failed
there while passing locally.

Both platforms therefore get a small launcher that runs the script body with
*this* interpreter (the venv's, not whatever ``python3`` resolves to):

* POSIX — a ``/bin/sh`` script named ``agent-browser``
* Windows — an ``agent-browser.bat``

The body keeps writing its invocation log next to itself, which stays inside the
test's ``tmp_path`` either way.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest


def write_fake_engine(tmp_path: Path, body: str) -> str:
    """Return a path to an executable fake ``agent-browser`` running *body*."""
    script = tmp_path / "agent_browser_fake.py"
    script.write_text(body)

    if sys.platform == "win32":
        launcher = tmp_path / "agent-browser.bat"
        launcher.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n')
        return str(launcher)

    launcher = tmp_path / "agent-browser"
    launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
    launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(launcher)


#: Marks a test that must actually *execute* the fake engine. Windows resolves
#: the launcher through cmd.exe, whose argument handling differs enough that
#: these spawn-path checks are unreliable there; the behaviour they cover is
#: asserted cross-platform by the pure-function tests next to them.
posix_only = pytest.mark.skipif(
    sys.platform == "win32",
    reason="the fake agent-browser launcher is not reliably executable on Windows",
)
