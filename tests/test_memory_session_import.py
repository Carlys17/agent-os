"""`agentos.memory` and `agentos.session` import each other.

`memory/flush_status.py` imports from `session/compaction_lifecycle` at module
scope. `compaction_lifecycle.pre_compaction_flush_enabled` imports back from
`memory/flush_config`, but from *inside the function body* -- which is the only
reason the cycle does not close at import time.

Nothing marked that as load-bearing, so a routine "move imports to the top"
cleanup would break `import agentos.memory.*` outright. These tests make the
constraint executable, and the failure legible when someone trips it.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
_LIFECYCLE = _SRC / "agentos" / "session" / "compaction_lifecycle.py"


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(_SRC.parent),
    )


def test_memory_imports_cleanly():
    assert _run("import agentos.memory.flush_status").returncode == 0


def test_session_imports_cleanly():
    assert _run("import agentos.session.compaction_lifecycle").returncode == 0


def test_either_import_order_works():
    """Whichever package a caller reaches first must succeed."""
    assert (
        _run(
            "import agentos.session.compaction_lifecycle; import agentos.memory.flush_status"
        ).returncode
        == 0
    )
    assert (
        _run(
            "import agentos.memory.flush_status; import agentos.session.compaction_lifecycle"
        ).returncode
        == 0
    )


def test_the_flush_config_import_stays_inside_the_function():
    """The invariant itself: hoisting this import closes the cycle.

    Asserted structurally rather than by string match, so reformatting or
    renaming around it does not produce a false pass.
    """
    tree = ast.parse(_LIFECYCLE.read_text(encoding="utf-8"))

    module_level_memory_imports = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("agentos.memory")
    ]
    assert not module_level_memory_imports, (
        "agentos.memory imported at module scope in compaction_lifecycle.py -- "
        "this closes the memory <-> session import cycle. Keep it function-local."
    )

    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "pre_compaction_flush_enabled"
    )
    assert any(
        isinstance(node, ast.ImportFrom) and node.module == "agentos.memory.flush_config"
        for node in ast.walk(function)
    ), "pre_compaction_flush_enabled no longer imports flush_config locally"
