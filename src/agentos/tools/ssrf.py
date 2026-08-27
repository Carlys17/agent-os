"""Shared SSRF protection for URL-fetching tools."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from httpcore._backends.base import SOCKET_OPTION, AsyncNetworkBackend

from agentos.tools.types import SSRFBlockedError, UnsupportedURLSchemeError

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

RFC2544_FAKE_IP_NETWORK = ipaddress.IPv4Network("198.18.0.0/15")

_HARD_BLOCKED_NETWORKS: tuple[IPNetwork, ...] = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)

#: Hostnames that resolve to a cloud metadata service. Blocked by name as well
#: as by address, because a resolver that answers them at all is answering for
#: the credential endpoint.
_METADATA_HOSTNAMES: frozenset[str] = frozenset(
    {
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
    }
)

#: Addresses that serve instance credentials to anything that can reach them.
#: These are the non-negotiable floor: unlike ordinary private ranges they have
#: no legitimate agent use, on any tool, under any configuration.
_METADATA_ADDRESSES: frozenset[IPAddress] = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),  # AWS / GCP / Azure / DO / Oracle
        ipaddress.ip_address("169.254.169.253"),  # Azure IMDS wire server
        ipaddress.ip_address("169.254.170.2"),  # AWS ECS task role credentials
        ipaddress.ip_address("100.100.100.200"),  # Alibaba Cloud
        ipaddress.ip_address("fd00:ec2::254"),  # AWS metadata over IPv6
    }
)

#: The whole link-local range. Nothing an agent should be talking to lives
#: here, and enumerating individual metadata addresses has repeatedly missed a
#: cloud vendor's variant.
_METADATA_NETWORKS: tuple[IPNetwork, ...] = (
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fe80::/10"),
)

_trusted_fake_ip_cidrs: tuple[IPNetwork, ...] = ()


def validate_trusted_fake_ip_cidrs(values: Iterable[str]) -> list[str]:
    """Return normalized fake-IP CIDRs or raise for unsafe entries."""
    networks: list[str] = []
    for raw in values:
        try:
            network = ipaddress.ip_network(str(raw).strip(), strict=False)
        except ValueError as exc:
            raise ValueError(f"trusted_fake_ip_cidrs entry {raw!r} is not a valid CIDR") from exc

        if not isinstance(network, ipaddress.IPv4Network) or not network.subnet_of(
            RFC2544_FAKE_IP_NETWORK
        ):
            raise ValueError(
                "trusted_fake_ip_cidrs may only contain subnets of "
                f"{RFC2544_FAKE_IP_NETWORK}; got {network}"
            )
        networks.append(str(network))
    return networks


def configure_trusted_fake_ip_cidrs(values: Iterable[str]) -> None:
    """Configure process-wide fake-IP CIDRs trusted by URL fetch guards."""
    global _trusted_fake_ip_cidrs
    normalized = validate_trusted_fake_ip_cidrs(values)
    _trusted_fake_ip_cidrs = tuple(ipaddress.ip_network(value) for value in normalized)


def get_trusted_fake_ip_cidrs() -> list[str]:
    """Return the process-wide trusted fake-IP CIDRs as normalized strings."""
    return [str(network) for network in _trusted_fake_ip_cidrs]


def _is_metadata_address(addr: IPAddress) -> bool:
    """Return whether *addr* is a cloud metadata endpoint."""
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        # ``::ffff:169.254.169.254`` is the same endpoint wearing a different
        # hat, and compares equal to neither the IPv4 address nor the IPv4
        # networks. Unwrap before deciding.
        addr = addr.ipv4_mapped
    if addr in _METADATA_ADDRESSES:
        return True
    return any(
        addr.version == network.version and addr in network for network in _METADATA_NETWORKS
    )


def assert_not_metadata_endpoint(url: str) -> None:
    """Raise :class:`SSRFBlockedError` if *url* targets a cloud metadata service.

    The security floor for tools that must keep reaching private addresses.
    ``http_request`` is routinely pointed at ``localhost`` and LAN services on
    purpose, so it cannot take the full :func:`validate_http_url_for_fetch`
    treatment — but no configuration makes the instance-credential endpoint a
    legitimate destination.

    A hostname that cannot be resolved is not blocked: the request that follows
    will fail on its own, and failing closed here would take the tool offline
    whenever DNS is unavailable.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return
    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname:
        return
    if hostname in _METADATA_HOSTNAMES:
        raise SSRFBlockedError(
            f"Blocked request to {hostname}: cloud metadata endpoints serve instance "
            "credentials and are never a valid agent target."
        )

    try:
        literal = ipaddress.ip_address(hostname.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        if _is_metadata_address(literal):
            raise SSRFBlockedError(
                f"Blocked request to {hostname}: link-local/metadata addresses serve "
                "instance credentials and are never a valid agent target."
            )
        return

    try:
        infos = socket.getaddrinfo(hostname, None)
    except (socket.gaierror, UnicodeError, ValueError):
        return
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:  # pragma: no cover - getaddrinfo returned a non-address
            continue
        if _is_metadata_address(addr):
            raise SSRFBlockedError(
                f"Blocked request to {hostname}: it resolves to {addr}, a cloud "
                "metadata endpoint that serves instance credentials."
            )


def validate_http_url_for_fetch(
    url: str,
    *,
    trusted_fake_ip_cidrs: Iterable[str] | None = None,
) -> None:
    """Validate that an HTTP(S) URL does not resolve to a blocked address."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsupportedURLSchemeError("Only HTTP/HTTPS URLs are supported")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Invalid URL: no hostname")

    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Cannot resolve hostname: {hostname}") from exc

    trusted_networks = (
        tuple(
            ipaddress.ip_network(value)
            for value in validate_trusted_fake_ip_cidrs(trusted_fake_ip_cidrs)
        )
        if trusted_fake_ip_cidrs is not None
        else _trusted_fake_ip_cidrs
    )

    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        block_reason = _hard_block_reason(addr)
        if block_reason is not None:
            raise SSRFBlockedError(_blocked_message(hostname, addr, block_reason))
        if _is_trusted_fake_ip(addr, trusted_networks):
            continue
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            reason = (
                f"reserved/private range; configure [tools].trusted_fake_ip_cidrs "
                f"with {RFC2544_FAKE_IP_NETWORK} only if this is fake-IP DNS"
                if addr in RFC2544_FAKE_IP_NETWORK
                else "private/internal range"
            )
            raise SSRFBlockedError(_blocked_message(hostname, addr, reason))


def _hard_block_reason(addr: IPAddress) -> str | None:
    for network in _HARD_BLOCKED_NETWORKS:
        if addr.version == network.version and addr in network:
            return f"hard-blocked network {network}"
    return None


def _is_trusted_fake_ip(addr: IPAddress, trusted_networks: tuple[IPNetwork, ...]) -> bool:
    return any(addr.version == network.version and addr in network for network in trusted_networks)


def _blocked_message(hostname: str, addr: IPAddress, reason: str) -> str:
    return f"Blocked: {hostname} resolves to {addr} ({reason})"


def _unwrap_mapped(addr: IPAddress) -> IPAddress:
    """Return the IPv4 an IPv4-mapped IPv6 address stands for, else *addr*."""
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def _fetch_block_reason(
    addr: IPAddress, *, trusted_networks: tuple[IPNetwork, ...]
) -> str | None:
    """Return why *addr* may not be fetched, or None when it may."""
    hard = _hard_block_reason(addr)
    if hard is not None:
        return hard
    if _is_trusted_fake_ip(addr, trusted_networks):
        return None
    if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
        return (
            f"reserved/private range; configure [tools].trusted_fake_ip_cidrs "
            f"with {RFC2544_FAKE_IP_NETWORK} only if this is fake-IP DNS"
            if addr in RFC2544_FAKE_IP_NETWORK
            else "private/internal range"
        )
    return None


def _trusted_networks(
    trusted_fake_ip_cidrs: Iterable[str] | None,
) -> tuple[IPNetwork, ...]:
    if trusted_fake_ip_cidrs is not None:
        return tuple(
            ipaddress.ip_network(value)
            for value in validate_trusted_fake_ip_cidrs(trusted_fake_ip_cidrs)
        )
    return _trusted_fake_ip_cidrs


def resolve_safe_addresses(
    hostname: str,
    *,
    metadata_only: bool = False,
    trusted_fake_ip_cidrs: Iterable[str] | None = None,
) -> list[str]:
    """Resolve *hostname* and return every safe address as an IP literal.

    Every address the name resolves to is validated before any of them is
    returned, so a caller that connects to one of the returned literals is
    guaranteed the validated address is the connected address. This is what
    closes the DNS-rebinding window: a guard that resolves once while the HTTP
    stack resolves again at connect time can be shown a public address first
    and a metadata address second.

    Raises :class:`SSRFBlockedError` when any resolved address is blocked and
    ``ValueError`` when the name does not resolve.
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Cannot resolve hostname: {hostname}") from exc

    trusted_networks = _trusted_networks(trusted_fake_ip_cidrs)
    safe: list[str] = []
    seen: set[str] = set()
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:  # pragma: no cover - getaddrinfo returned a non-address
            continue
        check = _unwrap_mapped(addr)
        reason = (
            f"metadata endpoint {check}"
            if metadata_only and _is_metadata_address(check)
            else None
        )
        if reason is None and not metadata_only:
            reason = _fetch_block_reason(check, trusted_networks=trusted_networks)
        if reason is not None:
            raise SSRFBlockedError(_blocked_message(hostname, addr, reason))
        literal = str(addr)
        if literal not in seen:
            seen.add(literal)
            safe.append(literal)
    if not safe:
        raise ValueError(f"Cannot resolve hostname: {hostname}")
    return safe


class ValidatingNetworkBackend(AsyncNetworkBackend):
    """httpcore network backend that pins TCP connections to validated IPs.

    The URL-level guards in this module resolve a hostname and check the
    result, but httpx/httpcore then resolve the same hostname *again* when
    opening the connection. With a short-TTL (rebinding) domain the two
    resolutions can differ, so the guard validates one address and the socket
    connects to another — e.g. ``169.254.169.254``.

    This backend removes the second resolution: it resolves the target itself,
    validates every address, and connects to one of the validated literals.
    TLS is unaffected — httpcore still performs the handshake against the
    origin hostname (SNI and certificate verification), only the TCP endpoint
    changes.
    """

    def __init__(self, *, metadata_only: bool = False, inner: Any = None) -> None:
        from httpcore._backends.auto import AutoBackend

        self._inner = inner if inner is not None else AutoBackend()
        self._metadata_only = metadata_only

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> Any:
        try:
            literal = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            literal = None

        if literal is not None:
            check = _unwrap_mapped(literal)
            blocked = _is_metadata_address(check) if self._metadata_only else (
                _fetch_block_reason(check, trusted_networks=_trusted_fake_ip_cidrs)
                is not None
            )
            if blocked:
                raise SSRFBlockedError(
                    f"Blocked: {host} is a private/internal or metadata address"
                )
            candidates = [str(literal)]
        else:
            if host.strip().lower().rstrip(".") in _METADATA_HOSTNAMES:
                raise SSRFBlockedError(
                    f"Blocked request to {host}: cloud metadata endpoints serve "
                    "instance credentials and are never a valid agent target."
                )
            candidates = resolve_safe_addresses(host, metadata_only=self._metadata_only)

        last_exc: Exception | None = None
        for candidate in candidates:
            try:
                return await self._inner.connect_tcp(
                    candidate,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except Exception as exc:  # try the next resolved address
                last_exc = exc
        assert last_exc is not None  # candidates is never empty
        raise last_exc

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> Any:
        return await self._inner.connect_unix_socket(
            path, timeout=timeout, socket_options=socket_options
        )

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def ssrf_guarded_client(
    *,
    metadata_only: bool = False,
    **client_kwargs: Any,
) -> Any:
    """Return an ``httpx.AsyncClient`` whose connections are pinned to validated IPs.

    The client is constructed normally (so env-proxy mounts and every other
    httpx default stay intact) and then the default connection pool's network
    backend is swapped for :class:`ValidatingNetworkBackend`. That backend
    resolves and validates the destination itself at connect time, closing the
    DNS-rebinding window between the URL-level guard and the actual socket —
    without rewriting the URL, so TLS SNI, the Host header, and relative
    redirects are unaffected.

    ``metadata_only=True`` keeps ordinary private addresses reachable (the
    ``http_request`` flavour, which is pointed at localhost on purpose) while
    still blocking cloud metadata endpoints at connect time.
    """
    import httpx

    client = httpx.AsyncClient(**client_kwargs)
    try:
        pool = client._transport._pool  # type: ignore[attr-defined]  # httpx 0.28 layout
        pool._network_backend = ValidatingNetworkBackend(  # type: ignore[attr-defined]  # noqa: SLF001
            metadata_only=metadata_only
        )
    except AttributeError:
        # A test fake (or a future httpx layout) without the expected pool
        # structure falls back to the URL-level guard only.
        pass
    return client
