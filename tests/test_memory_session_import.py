"""`agentos.memory` and `agentos.session` must stay importable in either order.

There used to be a real cycle: `memory/flush_status.py` imported from
`session/compaction_lifecycle` at module scope, and
`compaction_lifecycle.pre_compaction_flush_enabled` imported back from
`memory/flush_config` -- surviving only because that second import sat inside
a function body.

Removing `flush_status.py` broke the cycle from the memory side, so no module
under `agentos/memory` imports from `agentos/session` any more. These tests
pin that: they fail if a future change reintroduces the edge, which is what
would make the function-local import load-bearing again.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
_MEMORY = _SRC / "agentos" / "memory"


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(_SRC.parent),
    )


def test_memory_imports_cleanly():
    assert _run("import agentos.memory.manager").returncode == 0


def test_session_imports_cleanly():
    assert _run("import agentos.session.compaction_lifecycle").returncode == 0


def test_either_import_order_works():
    """Whichever package a caller reaches first must succeed."""
    assert (
        _run(
            "import agentos.session.compaction_lifecycle; import agentos.memory.manager"
        ).returncode
        == 0
    )
    assert (
        _run(
            "import agentos.memory.manager; import agentos.session.compaction_lifecycle"
        ).returncode
        == 0
    )


def test_no_memory_module_imports_session_at_module_scope():
    """The invariant that keeps the cycle gone.

    Asserted structurally rather than by string match, so reformatting or
    renaming around it cannot produce a false pass. A module-scope
    `agentos.session` import here is what previously forced
    `pre_compaction_flush_enabled` to hide its own import inside a function.
    """
    offenders: list[str] = []
    for path in sorted(_MEMORY.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:  # module scope only
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("agentos.session")
            ):
                offenders.append(f"{path.name}:{node.lineno} -> {node.module}")
            elif isinstance(node, ast.Import):
                offenders.extend(
                    f"{path.name}:{node.lineno} -> {alias.name}"
                    for alias in node.names
                    if alias.name.startswith("agentos.session")
                )

    assert not offenders, (
        "agentos.memory imports agentos.session at module scope: "
        + "; ".join(offenders)
        + " -- this reopens the memory <-> session cycle, and "
        "session/compaction_lifecycle.py would need its flush_config import "
        "kept function-local again."
    )
