"""Regression tests for MCP server URL validation.

The MCP HTTP/SSE/streamable-HTTP transports connect to operator-configured
``config.url`` values. Both transports must reject cloud-metadata endpoints
and any URL whose scheme is not http(s).
"""

from __future__ import annotations

import pytest

from agentos.mcp.sse import MCPSSEClient
from agentos.mcp.streamable_http import MCPStreamableHTTPClient
from agentos.mcp.types import MCPServerConfig


def _sse(url: str) -> MCPSSEClient:
    return MCPSSEClient(MCPServerConfig(name="mcp", transport="sse", url=url))


def _http(url: str) -> MCPStreamableHTTPClient:
    return MCPStreamableHTTPClient(
        MCPServerConfig(name="mcp", transport="streamable_http", url=url)
    )


CLOUD_METADATA_URLS = [
    "http://169.254.169.254/metadata/instance",
    "http://169.254.169.254/computeMetadata/v1/",
    "http://[fd00:ec2::254]/latest/meta-data/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://metadata.azure.com/metadata/instance",
    "http://100.100.100.200/latest/meta-data/",
    "http://192.0.0.192/latest/meta-data/",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("url", CLOUD_METADATA_URLS)
@pytest.mark.parametrize("factory", [_sse, _http])
async def test_mcp_transports_reject_metadata_endpoints(
    url: str, factory
) -> None:
    client = factory(url)
    with pytest.raises(ValueError):
        await client.connect()


BAD_SCHEMES = [
    "file:///etc/passwd",
    "gopher://169.254.169.254/metadata",
    "ftp://example.com/secret",
    "javascript:alert(1)",
    "data:text/plain,hello",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("url", BAD_SCHEMES)
@pytest.mark.parametrize("factory", [_sse, _http])
async def test_mcp_transports_reject_non_http_schemes(
    url: str, factory
) -> None:
    client = factory(url)
    with pytest.raises(ValueError):
        await client.connect()


@pytest.mark.asyncio
async def test_mcp_sse_https_metadata_attempt_blocked() -> None:
    """Even https-wrapped cloud-metadata IP is rejected."""
    client = MCPSSEClient(
        MCPServerConfig(
            name="mcp",
            transport="sse",
            url="https://169.254.169.254/metadata",
        )
    )
    with pytest.raises(ValueError):
        await client.connect()
