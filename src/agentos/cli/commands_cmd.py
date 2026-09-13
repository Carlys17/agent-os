"""CLI: inspect user-defined slash commands (``~/.agentos/commands/*.md``).

The command files are loaded, validated, and listed for the operator.
``agentos commands show <name>`` prints the rendered body (with a
placeholder substitution visible to the user). This is the read-only
side of the feature — the dispatch side lives in
``agentos.channels.command_registry.CommandRegistry`` and will be wired
into the channel pipeline separately.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from agentos.cli.ui import console
from agentos.engine.user_commands import (
    UserCommand,
    load_user_commands,
)
from agentos.paths import default_agentos_home

app = typer.Typer(
    help="List and inspect user-defined slash commands from ~/.agentos/commands/.",
    no_args_is_help=True,
)


def _home_dir(home: Path | None) -> Path:
    return home if home is not None else default_agentos_home()


@app.command("list")
def list_commands(
    home: Path | None = typer.Option(
        None,
        "--home",
        help="AgentOS home directory (default: ~/.agentos).",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit JSON instead of a table.",
    ),
) -> None:
    """List user-defined slash commands loaded from disk."""
    cmds = load_user_commands(_home_dir(home) / "commands")
    if json_output:

        console.print_json(
            data=[
                {
                    "name": c.name,
                    "description": c.description,
                    "surfaces": sorted(c.surfaces),
                    "argument_hint": c.argument_hint,
                    "source": str(c.source_path),
                }
                for c in cmds
            ]
        )
        return
    if not cmds:
        console.print(
            "[dim]No user-defined commands found.[/dim] "
            "Create one with: mkdir -p ~/.agentos/commands/ && "
            "write a Markdown file with frontmatter."
        )
        return
    table = Table(title=f"User-defined commands ({len(cmds)})")
    table.add_column("Name", style="bold cyan")
    table.add_column("Surfaces")
    table.add_column("Hint", overflow="fold")
    table.add_column("Description", overflow="fold")
    for c in cmds:
        table.add_row(
            c.name,
            ", ".join(sorted(c.surfaces)),
            c.argument_hint or "",
            c.description,
        )
    console.print(table)


@app.command("show")
def show_command(
    name: str = typer.Argument(..., help="Slash command name, e.g. /review."),
    home: Path | None = typer.Option(
        None,
        "--home",
        help="AgentOS home directory (default: ~/.agentos).",
    ),
    sample_args: str = typer.Option(
        "",
        "--with-args",
        help="Show a rendered preview with these args.",
    ),
) -> None:
    """Show one user-defined command, including its rendered body."""
    cmds = load_user_commands(_home_dir(home) / "commands")
    target: UserCommand | None = None
    bare = name.lstrip("/").lower()
    for c in cmds:
        if c.name.lstrip("/").lower() == bare:
            target = c
            break
    if target is None:
        console.print(f"[red]Command not found:[/red] {name}")
        raise typer.Exit(code=1)
    console.print(f"[bold]{target.name}[/bold]  {target.description}")
    console.print(f"[dim]surfaces:[/dim] {', '.join(sorted(target.surfaces)) or '—'}")
    if target.argument_hint:
        console.print(f"[dim]args:[/dim] {target.argument_hint}")
    console.print(f"[dim]source:[/dim] {target.source_path}")
    console.print("\n[bold]Body[/bold]")
    console.print(target.body)
    if sample_args:
        console.print(f"\n[bold]Rendered with args={sample_args!r}[/bold]")
        console.print(target.render(sample_args))


__all__ = ["app"]
