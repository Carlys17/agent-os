"""Interactive token provisioning for a non-loopback gateway bind."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from enum import Enum

from agentos.gateway.access import is_loopback_bind
from agentos.gateway.config import GatewayConfig, _mode_protects_public_bind, is_public_bind
from agentos.gateway.config_persist import persist_config


class AuthProvisionOutcome(Enum):
    PROCEED = "proceed"
    CANCEL = "cancel"
    UNCHANGED = "unchanged"


def _bind_warning(host: str) -> str:
    if is_public_bind(host):
        return (
            f"[yellow]WARNING: gateway is bound to the wildcard address {host} - "
            "reachable from every interface.[/yellow]"
        )
    return (
        f"[yellow]WARNING: gateway is bound to a non-loopback address {host} - "
        "reachable beyond this machine.[/yellow]"
    )


def provision_public_bind_auth(
    config: GatewayConfig,
    *,
    interactive: bool,
    prompt: Callable[[str], str] = input,
    emit: Callable[[str], None] = print,
) -> tuple[AuthProvisionOutcome, GatewayConfig]:
    """Provision the all-or-nothing Control token required for a public bind."""

    if is_loopback_bind(config.host):
        return (AuthProvisionOutcome.UNCHANGED, config)

    emit(_bind_warning(config.host))
    if _mode_protects_public_bind(config.auth):
        return (AuthProvisionOutcome.UNCHANGED, config)
    if not interactive:
        return (AuthProvisionOutcome.UNCHANGED, config)

    emit(
        "[yellow]This public bind has no authentication configured. "
        "Choose how to proceed:[/yellow]"
    )
    emit("  [1] Generate a Control token and enable authentication (recommended)")
    emit("  [2] Cancel")
    try:
        choice = prompt("Select [1/2] (default 1): ").strip()
    except (EOFError, KeyboardInterrupt):
        return (AuthProvisionOutcome.CANCEL, config)
    if choice == "2":
        return (AuthProvisionOutcome.CANCEL, config)

    token = secrets.token_urlsafe(32)
    new_config = config.model_copy(
        update={"auth": config.auth.model_copy(update={"mode": "token", "token": token})}
    )
    try:
        saved_path = persist_config(new_config)
    except OSError as exc:
        emit(
            f"[yellow]WARNING: could not persist the token to the config file ({exc}). "
            "It stays active for this session only.[/yellow]"
        )
    else:
        emit(f"[green]auth.mode=token enabled; token saved to {saved_path}[/green]")
    emit(f"[bold]Gateway token:[/bold] {token}")
    emit("[dim]Clients authenticate with: Authorization: Bearer <token>[/dim]")
    return (AuthProvisionOutcome.PROCEED, new_config)


__all__ = ["AuthProvisionOutcome", "provision_public_bind_auth"]
