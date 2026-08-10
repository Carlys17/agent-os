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


#: ``--resume`` when the operator has not approved yet. Distinct from a real
#: failure so a caller can retry without parsing prose.
EXIT_STILL_PENDING = 3


@auth_app.command("login")
def auth_login(
    provider: str = typer.Argument("xai", help="Provider to log in to. Currently: xai."),
    no_wait: bool = typer.Option(
        False,
        "--no-wait",
        help="Print the approval link and code, then exit instead of waiting.",
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Check a login started with --no-wait. Exit 0 done, 3 not yet, 1 failed.",
    ),
    login_id: str = typer.Option(
        "", "--login-id", help="Which pending login to resume. Defaults to the newest."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    timeout_seconds: float = typer.Option(
        20.0, "--timeout", help="Per-request timeout for the OAuth endpoints."
    ),
) -> None:
    """Log in to xAI with a SuperGrok / X Premium+ account (device-code flow).

    Blocks until you approve, unless split with ``--no-wait`` / ``--resume``.
    The split exists for callers that cannot hold a terminal open for minutes —
    a chat agent driving this through exec_command, most obviously.
    """
    from agentos.cli.output import print_json
    from agentos.xai_oauth import (
        XaiOAuthError,
        device_code_login,
        get_pending_login,
        latest_pending_login,
        poll_device_login,
        start_device_login,
    )

    _require_xai(provider)

    if no_wait and resume:
        error_console.print("[red]Error:[/red] --no-wait and --resume are mutually exclusive")
        raise typer.Exit(code=2)

    if resume:
        pending = get_pending_login(login_id) if login_id else latest_pending_login()
        if pending is None:
            message = "No pending xAI login. Start one with `agentos auth login xai --no-wait`."
            if json_output:
                print_json({"status": "expired", "message": message})
            else:
                error_console.print(f"[yellow]{message}[/yellow]")
            raise typer.Exit(code=1)
        try:
            complete, interval = poll_device_login(pending, timeout_seconds=timeout_seconds)
        except XaiOAuthError as exc:
            if json_output:
                print_json({"status": "failed", "message": str(exc), "code": exc.code})
            else:
                error_console.print(f"[red]Login failed:[/red] {exc}")
            raise typer.Exit(code=1) from exc
        if complete:
            if json_output:
                print_json({"status": "complete"})
            else:
                console.print("[green]Logged in to xAI.[/green]")
            return
        if json_output:
            print_json({"status": "pending", "interval": interval, "loginId": pending.login_id})
        else:
            console.print(f"Not approved yet. Check again in {interval}s.")
        raise typer.Exit(code=EXIT_STILL_PENDING)

    if no_wait:
        try:
            pending = start_device_login(timeout_seconds=timeout_seconds)
        except XaiOAuthError as exc:
            if json_output:
                print_json({"status": "failed", "message": str(exc), "code": exc.code})
            else:
                error_console.print(f"[red]Login failed:[/red] {exc}")
            raise typer.Exit(code=1) from exc
        if json_output:
            print_json(
                {
                    "status": "pending",
                    "loginId": pending.login_id,
                    "verificationUri": pending.verification_uri,
                    "userCode": pending.user_code,
                    "interval": pending.interval,
                }
            )
        else:
            console.print("To authorize AgentOS with your xAI account:")
            console.print(f"  1. Open: [bold]{pending.verification_uri}[/bold]")
            console.print(f"  2. If prompted, enter the code: [bold]{pending.user_code}[/bold]")
            console.print("Then run: agentos auth login xai --resume")
        return

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
