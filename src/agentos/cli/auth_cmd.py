"""`agentos auth` — provider logins that are not plain API keys.

Only xAI is here today. The command exists because a SuperGrok / X Premium+
subscription cannot be expressed as an API key: the only way to spend it is an
OAuth grant, and the only way to get that grant is an interactive login the
operator performs themselves.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

console = Console()
error_console = Console(stderr=True)

auth_app = typer.Typer(help="Manage provider logins (xAI OAuth).", no_args_is_help=True)

_XAI_ALIASES = {"xai", "xai-oauth", "grok", "supergrok"}


def _require_xai(provider: str) -> None:
    if provider.strip().lower() not in _XAI_ALIASES:
        error_console.print(
            f"[red]Error:[/red] unknown auth provider {provider!r} (expected: xai)"
        )
        raise typer.Exit(code=2)


@auth_app.command("login")
def auth_login(
    provider: str = typer.Argument("xai", help="Provider to log in to. Currently: xai."),
    timeout_seconds: float = typer.Option(
        20.0, "--timeout", help="Per-request timeout for the OAuth endpoints."
    ),
) -> None:
    """Log in to xAI with a SuperGrok / X Premium+ account (device-code flow)."""
    from agentos.xai_oauth import XaiOAuthError, device_code_login

    _require_xai(provider)

    def prompt(url: str, user_code: str, interval: int) -> None:
        console.print()
        console.print("To authorize AgentOS with your xAI account:")
        console.print(f"  1. Open: [bold]{url}[/bold]")
        console.print(f"  2. If prompted, enter the code: [bold]{user_code}[/bold]")
        console.print(f"Waiting for approval (checking every {max(1, interval)}s)...")

    try:
        device_code_login(on_prompt=prompt, timeout_seconds=timeout_seconds)
    except XaiOAuthError as exc:
        error_console.print(f"[red]Login failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        error_console.print("\n[yellow]Login cancelled.[/yellow]")
        raise typer.Exit(code=130) from None

    console.print("[green]Logged in to xAI.[/green]")
    console.print("x_search will use this subscription in preference to XAI_API_KEY.")


@auth_app.command("status")
def auth_status(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Show which provider logins are stored. Never prints a token."""
    from agentos.cli.output import print_json
    from agentos.xai_oauth import oauth_status

    status = oauth_status()
    if json_output:
        print_json({"xai": status})
        return

    table = Table(title="AgentOS provider logins")
    table.add_column("Provider")
    table.add_column("State")
    table.add_column("Detail", overflow="fold")

    if not status["logged_in"]:
        detail = "Run `agentos auth login xai` to use a SuperGrok / X Premium+ subscription."
        table.add_row("xai", "not logged in", detail)
    else:
        expires = status["expires_at"] or "unknown"
        detail = f"expires {expires}"
        if status["expiring_soon"]:
            detail += " (refreshes on next use)"
        if not status["has_refresh_token"]:
            detail += " — no refresh token; log in again"
        table.add_row("xai", "logged in", detail)

    console.print(table)
    last_error = status.get("last_auth_error")
    if isinstance(last_error, dict) and last_error.get("message"):
        console.print(f"[yellow]Last error:[/yellow] {last_error['message']}")
    console.print(f"Store: {status['store_path']}")


@auth_app.command("logout")
def auth_logout(
    provider: str = typer.Argument("xai", help="Provider to log out of. Currently: xai."),
) -> None:
    """Forget a stored login."""
    from agentos.xai_oauth import clear_oauth_state

    _require_xai(provider)
    if clear_oauth_state():
        console.print("[green]Logged out of xAI.[/green]")
    else:
        console.print("No stored xAI login.")
