# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Cron schedule commands (artemis schedule)."""

from typing import Annotated

from artemis.runtime.daemon_client import (
    DEFAULT_DAEMON_HOST,
    DEFAULT_DAEMON_PORT,
    daemon_api_request,
    ensure_daemon_running,
)
from rich.console import Console
from rich.table import Table
import typer

schedule_app = typer.Typer(help="Run goals on a cron schedule while the Artemis server is up.")
console = Console()


def _call(method: str, path: str, payload: dict | None = None, *, base_url: str | None = None):
    base_url = base_url or f"http://{DEFAULT_DAEMON_HOST}:{DEFAULT_DAEMON_PORT}"
    try:
        status, body = daemon_api_request(method, path, payload, base_url=base_url)
    except OSError:
        console.print(f"[red]Artemis server is not reachable at {base_url}.[/red]")
        raise typer.Exit(1)
    if status >= 400:
        console.print(f"[red]{(body or {}).get('detail', f'Server returned HTTP {status}')}[/red]")
        raise typer.Exit(1)
    return body


@schedule_app.command("add")
def add_schedule(
    cron: Annotated[str, typer.Argument(help='5-field cron, e.g. "0 9 * * *".')],
    goal: Annotated[str, typer.Argument(help="Goal to run each time the cron matches.")],
    profile: Annotated[str, typer.Option("--profile", "-p", help="Agent profile.")] = "flash",
    device: Annotated[str | None, typer.Option("--device", "-d", help="Device serial.")] = None,
) -> None:
    """Register a goal to run on a cron schedule."""
    running, base_url = ensure_daemon_running(wait_ready=True, timeout=15.0)
    if not running:
        console.print(
            "[red]Could not start the Artemis server; schedules only fire while it runs.[/red]"
        )
        raise typer.Exit(1)
    item = _call(
        "POST",
        "/api/schedules",
        {"cron": cron, "goal": goal, "profile": profile, "device_serial": device},
        base_url=base_url,
    )
    console.print(f"[green]Scheduled {item['id']}[/green]: {item['cron']}  {item['goal']}")


@schedule_app.command("list")
def list_schedules() -> None:
    """List registered schedules."""
    schedules = _call("GET", "/api/schedules")["schedules"]
    table = Table(title=f"Schedules ({len(schedules)})")
    for column in ("ID", "Cron", "Goal", "Profile", "Last fired", "Last error"):
        table.add_column(column)
    for s in schedules:
        table.add_row(
            s["id"],
            s["cron"],
            s["goal"],
            s["profile"],
            (s["last_fired_minute"] or "-").replace("T", " "),
            s["last_error"] or "",
        )
    console.print(table)


@schedule_app.command("remove")
def remove_schedule(schedule_id: Annotated[str, typer.Argument(help="Schedule id.")]) -> None:
    """Remove a schedule."""
    _call("DELETE", f"/api/schedules/{schedule_id}")
    console.print(f"[green]Removed {schedule_id}[/green]")
