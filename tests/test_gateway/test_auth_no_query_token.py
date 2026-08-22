from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from starlette.requests import Request
from starlette.testclient import TestClient

from agentos.gateway.app import create_gateway_app
from agentos.gateway.config import AuthConfig, GatewayConfig
from agentos.gateway.middleware import AuthMiddleware


def test_auth_middleware_extract_token_rejects_query_param() -> None:
    """AuthMiddleware._extract_token extracts from headers only, not query params."""
    middleware = AuthMiddleware(
        app=MagicMock(),
        config=GatewayConfig(auth=AuthConfig(mode="token", token="my-secret")),
    )

    # 1. Query parameter only -> None
    scope_query: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/api/sessions",
        "query_string": b"token=my-secret",
        "headers": [],
    }
    req_query = Request(scope_query)
    assert middleware._extract_token(req_query) is None

    # 2. Authorization: Bearer header -> extracted
    scope_bearer: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/api/sessions",
        "query_string": b"",
        "headers": [(b"authorization", b"Bearer my-secret")],
    }
    req_bearer = Request(scope_bearer)
    assert middleware._extract_token(req_bearer) == "my-secret"

    # 3. x-agentos-token header -> extracted
    scope_custom: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/api/sessions",
        "query_string": b"",
        "headers": [(b"x-agentos-token", b"my-secret")],
    }
    req_custom = Request(scope_custom)
    assert middleware._extract_token(req_custom) == "my-secret"


def test_gateway_endpoints_reject_query_token() -> None:
    """REST and RPC endpoints reject ?token= query parameter and require headers."""
    config = GatewayConfig(auth=AuthConfig(mode="token", token="secret-123"))
    app = create_gateway_app(config=config)

    with TestClient(app, base_url="http://localhost") as client:
        # 1. Query token is rejected with 401 Unauthorized
        res_query = client.get("/api/sessions?token=secret-123")
        assert res_query.status_code == 401
        assert res_query.json().get("code") == "UNAUTHORIZED"

        res_config_query = client.get("/api/config?token=secret-123")
        assert res_config_query.status_code == 401

        # 2. Bearer header is accepted
        res_bearer = client.get(
            "/api/sessions",
            headers={"Authorization": "Bearer secret-123"},
        )
        assert res_bearer.status_code == 200

        # 3. x-agentos-token header is accepted
        res_header = client.get(
            "/api/sessions",
            headers={"x-agentos-token": "secret-123"},
        )
        assert res_header.status_code == 200


@pytest.mark.asyncio
async def test_boot_gateway_disables_uvicorn_access_log() -> None:
    """Gateway boot sequence configures uvicorn with access_log=False to prevent URL leaks."""
    from agentos.gateway.boot import start_gateway_server

    config = GatewayConfig(host="127.0.0.1", port=18791)

    captured_config: dict[str, Any] = {}

    with (
        patch("uvicorn.Config") as mock_uv_config,
        patch("uvicorn.Server") as mock_uv_server,
        patch("agentos.gateway.boot.create_background_task") as mock_bg_task,
        patch("agentos.gateway.boot.preload_agentos_router_runtime") as _,
    ):
        mock_server_instance = MagicMock()

        async def _dummy_serve() -> None:
            pass

        mock_server_instance.serve = _dummy_serve
        mock_uv_server.return_value = mock_server_instance
        def _dummy_bg_task(coro: Any) -> Any:
            if hasattr(coro, "close"):
                coro.close()
            return MagicMock()

        mock_bg_task.side_effect = _dummy_bg_task

        def _capture_config(*args: Any, **kwargs: Any) -> Any:
            captured_config.update(kwargs)
            return MagicMock()

        mock_uv_config.side_effect = _capture_config

        handle = await start_gateway_server(config=config, run=True)
        assert handle is not None
        assert captured_config.get("access_log") is False
