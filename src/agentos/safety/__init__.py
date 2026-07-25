"""Agent safety baseline.

Four modules form the public safety surface:

* :mod:`agentos.safety.injection_guard` — wrap untrusted content with
  ``<untrusted source='...'>...</untrusted>`` envelopes, escape XML, and
  detect tool-call refusals whose origin is traced to an untrusted block.
* :mod:`agentos.safety.tool_tiers` — ``RiskTier`` enum + declare/get tier
  API; hardcoded confirmation list for high-risk tools.
* :mod:`agentos.safety.permission_matrix` — compatibility decision API for
  the shared SAFE/CONFIRM policy.
* :mod:`agentos.safety.sandbox` — ``run_sandboxed`` subprocess runner with
  CPU/memory/wall/network limits via :mod:`resource`.

Import order: modules are side-effect-free; importing this package is safe
during engine/gateway boot.
"""

from __future__ import annotations

from agentos.safety import (
    injection_guard,
    permission_matrix,
    sandbox,
    tool_tiers,
)

__all__ = [
    "injection_guard",
    "permission_matrix",
    "sandbox",
    "tool_tiers",
]
