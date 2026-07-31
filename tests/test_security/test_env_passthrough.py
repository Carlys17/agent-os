"""What a child process inherits, and who may widen it."""

from __future__ import annotations

import asyncio

import pytest

from agentos.tools import env_passthrough
from agentos.tools.types import ToolContext, current_tool_context


@pytest.fixture(autouse=True)
def _isolate_registry() -> None:
    env_passthrough.clear_env_passthrough(all_sessions=True)
    env_passthrough.reset_managed_credentials_cache()
    yield
    env_passthrough.clear_env_passthrough(all_sessions=True)
    env_passthrough.reset_managed_credentials_cache()


class TestSubprocessEnv:
    def test_the_gateway_token_never_reaches_a_child(self) -> None:
        """It authenticates to the control plane; nothing a command runs needs it."""
        base = {"PATH": "/usr/bin", "AGENTOS_GATEWAY_TOKEN": "tok"}
        assert env_passthrough.build_subprocess_env(base) == {"PATH": "/usr/bin"}

    @pytest.mark.parametrize(
        "name",
        [
            "AGENTOS_SENSITIVE_PATHS_DISABLED",
            "AGENTOS_SENSITIVE_PAYLOAD_DISABLED",
            "AGENTOS_REDACT_SECRETS",
        ],
    )
    def test_guard_switches_never_reach_a_child(self, name: str) -> None:
        """A child that reads them learns the posture; one that writes them changes it."""
        assert name not in env_passthrough.build_subprocess_env({name: "1", "PATH": "/usr/bin"})

    def test_the_extra_argument_cannot_reintroduce_a_stripped_name(self) -> None:
        """``env=`` on a tool call is model input like any other."""
        result = env_passthrough.build_subprocess_env(
            {"PATH": "/usr/bin"}, {"AGENTOS_GATEWAY_TOKEN": "tok", "MY_VAR": "v"}
        )
        assert result == {"PATH": "/usr/bin", "MY_VAR": "v"}

    def test_the_users_own_credentials_still_cross(self) -> None:
        """The local shell is the operator's; breaking gh and aws protects nothing."""
        base = {"GITHUB_TOKEN": "gh", "AWS_ACCESS_KEY_ID": "ak", "DOCKER_HOST": "unix://x"}
        assert env_passthrough.build_subprocess_env(base) == base

    def test_provider_keys_cross_by_default(self) -> None:
        """Bundled skill scripts read them straight out of os.environ."""
        base = {"OPENROUTER_API_KEY": "sk-or-v1-x", "AGENTOS_LLM_API_KEY": "k"}
        assert env_passthrough.build_subprocess_env(base) == base

    def test_provider_keys_are_stripped_when_the_operator_opts_in(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTOS_STRIP_PROVIDER_ENV", "1")
        base = {"OPENROUTER_API_KEY": "sk-or-v1-x", "PATH": "/usr/bin", "GITHUB_TOKEN": "gh"}
        result = env_passthrough.build_subprocess_env(base)
        assert "OPENROUTER_API_KEY" not in result
        assert result["PATH"] == "/usr/bin"
        assert result["GITHUB_TOKEN"] == "gh"


class TestRegistration:
    def test_a_skill_declaration_reaches_the_allowlist_sandbox(self) -> None:
        assert env_passthrough.register_env_passthrough(["CAP_API_KEY"]) == []
        assert env_passthrough.is_env_passthrough("CAP_API_KEY")

    def test_an_untrusted_skill_cannot_ask_for_a_runtime_credential(self) -> None:
        """A skill must not be able to tunnel the runtime's own key into a sandbox."""
        refused = env_passthrough.register_env_passthrough(
            ["OPENROUTER_API_KEY", "AGENTOS_LLM_API_KEY", "CAP_API_KEY"]
        )
        assert set(refused) == {"OPENROUTER_API_KEY", "AGENTOS_LLM_API_KEY"}
        assert not env_passthrough.is_env_passthrough("OPENROUTER_API_KEY")
        assert env_passthrough.is_env_passthrough("CAP_API_KEY")

    def test_a_bundled_skill_may_ask_for_one(self) -> None:
        """Its frontmatter ships in the wheel and was reviewed as ours."""
        assert env_passthrough.register_env_passthrough(["OPENROUTER_API_KEY"], trusted=True) == []
        assert env_passthrough.is_env_passthrough("OPENROUTER_API_KEY")

    def test_not_even_a_bundled_skill_may_ask_for_a_guard_switch(self) -> None:
        refused = env_passthrough.register_env_passthrough(
            ["AGENTOS_SENSITIVE_PATHS_DISABLED"], trusted=True
        )
        assert refused == ["AGENTOS_SENSITIVE_PATHS_DISABLED"]
        assert not env_passthrough.is_env_passthrough("AGENTOS_SENSITIVE_PATHS_DISABLED")

    def test_malformed_names_are_dropped_rather_than_registered(self) -> None:
        assert env_passthrough.register_env_passthrough(["", "  ", "not-a-name", "9LEADING"]) == []
        assert not env_passthrough.is_env_passthrough("not-a-name")

    def test_the_catalog_covers_every_provider_family(self) -> None:
        managed = env_passthrough.agentos_managed_credentials()
        assert "OPENROUTER_API_KEY" in managed  # LLM
        assert "TAVILY_API_KEY" in managed  # search
        assert "ELEVENLABS_API_KEY" in managed  # audio
        assert "GITHUB_TOKEN" not in managed  # the user's own


class TestRegistrationSurvivesTheToolBoundary:
    """A registration is only useful if the *next* tool call can see it.

    Every tool call runs in its own asyncio task, and a task gets a copy of the
    context — so anything stored per-context in the ``skill_view`` call is
    invisible to the ``execute_code`` call that follows. Registering in one
    task and reading in the same task, as a naive test does, hides that
    completely.
    """

    @staticmethod
    def _in_session(session_key: str, fn):
        async def run():
            current_tool_context.set(ToolContext(session_key=session_key))
            return fn()

        return run

    def test_a_later_tool_call_sees_it(self) -> None:
        async def scenario() -> tuple[bool, bool]:
            registered = await asyncio.create_task(
                self._in_session(
                    "s1", lambda: env_passthrough.register_env_passthrough(["CAP_API_KEY"]) == []
                )()
            )
            seen = await asyncio.create_task(
                self._in_session("s1", lambda: env_passthrough.is_env_passthrough("CAP_API_KEY"))()
            )
            return registered, seen

        registered, seen = asyncio.run(scenario())
        assert registered
        assert seen, "a skill's declaration must survive to the tool it exists to serve"

    def test_another_session_does_not_see_it(self) -> None:
        async def scenario() -> bool:
            await asyncio.create_task(
                self._in_session(
                    "s1", lambda: env_passthrough.register_env_passthrough(["CAP_API_KEY"])
                )()
            )
            return await asyncio.create_task(
                self._in_session("s2", lambda: env_passthrough.is_env_passthrough("CAP_API_KEY"))()
            )

        assert asyncio.run(scenario()) is False

    def test_old_sessions_are_evicted_rather_than_accumulating(self) -> None:
        async def scenario() -> tuple[bool, bool]:
            for index in range(env_passthrough._MAX_SESSIONS + 5):
                await asyncio.create_task(
                    self._in_session(
                        f"s{index}",
                        lambda: env_passthrough.register_env_passthrough(["CAP_API_KEY"]),
                    )()
                )
            oldest = await asyncio.create_task(
                self._in_session("s0", lambda: env_passthrough.is_env_passthrough("CAP_API_KEY"))()
            )
            newest = await asyncio.create_task(
                self._in_session(
                    f"s{env_passthrough._MAX_SESSIONS + 4}",
                    lambda: env_passthrough.is_env_passthrough("CAP_API_KEY"),
                )()
            )
            return oldest, newest

        oldest, newest = asyncio.run(scenario())
        assert newest
        assert not oldest
        assert len(env_passthrough._registry) <= env_passthrough._MAX_SESSIONS


def test_sandboxed_code_sees_registered_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """execute_code forwards almost nothing; a declaration is how a skill reaches its key."""
    from agentos.tools.builtin import code_exec

    monkeypatch.setenv("CAP_API_KEY", "cap_live_value")
    monkeypatch.setenv("UNRELATED_SECRET", "nope")

    assert "CAP_API_KEY" not in code_exec._build_safe_env()

    env_passthrough.register_env_passthrough(["CAP_API_KEY"])
    safe_env = code_exec._build_safe_env()
    assert safe_env["CAP_API_KEY"] == "cap_live_value"
    assert "UNRELATED_SECRET" not in safe_env
