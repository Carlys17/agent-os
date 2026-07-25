from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from agentos.gateway.config import GatewayConfig
from agentos.gateway.rpc import RpcContext, get_dispatcher
from agentos.tools.registry import ToolRegistry
from agentos.tools.types import ToolSpec


async def _handler() -> str:
    return "ok"


def _ctx(*, tool_registry: Any) -> RpcContext:
    return RpcContext(
        conn_id="test",
        config=GatewayConfig(),
        tool_registry=tool_registry,
        session_manager=object(),
        task_runtime=object(),
    )


def _tool_names(payload: dict[str, Any]) -> set[str]:
    return {tool["name"] for tool in payload["tools"]}


def test_tools_rpc_delegates_payloads_to_tools_boundary() -> None:
    from agentos.gateway import rpc_tools
    from agentos.tools import registry

    source = Path(rpc_tools.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    registry_tree = ast.parse(Path(registry.__file__).read_text(encoding="utf-8"))
    boundary_path = Path(registry.__file__).with_name("rpc_payload.py")

    assert boundary_path.exists()

    boundary_tree = ast.parse(boundary_path.read_text(encoding="utf-8"))
    imports = {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }
    registry_defs = {
        node.name
        for node in registry_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    boundary_defs = {
        node.name
        for node in boundary_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert {
        ("agentos.tools.rpc_payload", "tools_catalog_payload"),
        ("agentos.tools.rpc_payload", "tools_effective_payload"),
    } <= imports
    assert {
        "tools_catalog_payload",
        "tools_effective_payload",
    } <= registry_defs
    assert {
        "tool_rpc_params",
        "tool_surface_capabilities_for_runtime",
        "tools_catalog_payload",
        "tools_effective_payload",
    } <= boundary_defs


def _registry_with_configured_probe() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="ordinary_probe",
            description="ordinary probe",
            parameters={},
        ),
        _handler,
    )
    registry.register(
        ToolSpec(
            name="configured_probe",
            description="configured probe",
            parameters={},
            exposed_by_default=False,
        ),
        _handler,
    )
    return registry


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["tools.catalog", "tools.effective"])
async def test_tools_rpc_visibility_comes_from_tool_configuration(method: str) -> None:
    registry = _registry_with_configured_probe()

    result = await get_dispatcher().dispatch(
        "r1",
        method,
        {"callerKind": "agent"},
        _ctx(tool_registry=registry),
    )

    assert result.error is None, result.error
    assert _tool_names(result.payload) == {"ordinary_probe"}


@pytest.mark.asyncio
async def test_tools_catalog_without_runtime_params_uses_configured_surface() -> None:
    registry = _registry_with_configured_probe()

    result = await get_dispatcher().dispatch(
        "r1",
        "tools.catalog",
        {},
        _ctx(tool_registry=registry),
    )

    assert result.error is None, result.error
    assert _tool_names(result.payload) == {"ordinary_probe"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"callerKind": "subagent"},
        {"sessionKey": "subagent:test"},
    ],
)
@pytest.mark.parametrize("method", ["tools.catalog", "tools.effective"])
async def test_tools_rpc_subagent_visibility_uses_runtime_policy(
    method: str,
    params: dict[str, str],
) -> None:
    registry = _registry_with_configured_probe()

    result = await get_dispatcher().dispatch(
        "r1",
        method,
        params,
        _ctx(tool_registry=registry),
    )

    assert result.error is None, result.error
    assert _tool_names(result.payload) == {"ordinary_probe"}


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["tools.catalog", "tools.effective"])
async def test_default_tools_rpc_has_no_owner_dependent_visibility(method: str) -> None:
    import agentos.tools.builtin  # noqa: F401
    from agentos.gateway.config import ImageGenerationConfig, LlmProviderConfig
    from agentos.tools.builtin.media import configure_image_generation
    from agentos.tools.registry import get_default_registry

    configure_image_generation(
        ImageGenerationConfig(enabled=True),
        llm_config=LlmProviderConfig(provider="openrouter", api_key="sk-or-configured"),
    )
    try:
        first = await get_dispatcher().dispatch(
            "r1",
            method,
            {"callerKind": "agent"},
            _ctx(tool_registry=get_default_registry()),
        )
        second = await get_dispatcher().dispatch(
            "r2",
            method,
            {"callerKind": "agent"},
            _ctx(tool_registry=get_default_registry()),
        )
    finally:
        configure_image_generation(ImageGenerationConfig())

    assert first.error is None, first.error
    assert second.error is None, second.error

    first_names = _tool_names(first.payload)
    second_names = _tool_names(second.payload)

    assert first_names == second_names
    assert "http_request" in first_names
    assert "git_commit" not in first_names
    assert {"image_generate", "sessions_spawn", "sessions_send"} <= first_names
    assert "spawn_subagent" not in first_names
    assert "send_message" not in first_names
    assert "generate_image" not in first_names


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["tools.catalog", "tools.effective"])
async def test_default_channel_tools_rpc_uses_configured_agent_surface(method: str) -> None:
    import agentos.tools.builtin  # noqa: F401
    from agentos.tools.registry import get_default_registry

    result = await get_dispatcher().dispatch(
        "r1",
        method,
        {"callerKind": "channel"},
        _ctx(tool_registry=get_default_registry()),
    )

    assert result.error is None, result.error
    names = _tool_names(result.payload)

    assert {"create_csv", "create_xlsx", "create_pdf_report"} <= names
    assert "create_pptx" not in names
    assert {"write_file", "execute_code", "apply_patch"} <= names
    assert "cron" not in names
