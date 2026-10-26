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

"""Cron scheduler: enqueues a goal on a 5-field cron while the server runs.

Local time, minute resolution. Minutes missed while the server was down are not caught up.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any, NamedTuple
import uuid

from fastapi import HTTPException
from pydantic import BaseModel

from artemis.config import DB_PATH
from third_party.mobile_use.utils.logger import get_logger

try:
    from admin_console.core.state import state
    from admin_console.schemas.task_schema import RunRequest
except ImportError:
    from apps.admin_console.core.state import state
    from apps.admin_console.schemas.task_schema import RunRequest

logger = get_logger(__name__)

# (min, max) per field: minute, hour, day-of-month, month, day-of-week (7 folds to 0).
_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
_NAMES = ("minute", "hour", "day-of-month", "month", "day-of-week")

Submit = Callable[[RunRequest], Awaitable[dict[str, Any]]]


def _parse_field(text: str, lo: int, hi: int, name: str) -> frozenset[int]:
    values: set[int] = set()
    for part in text.split(","):
        base, _, step_text = part.partition("/")
        try:
            step = int(step_text) if step_text else 1
            if base == "*":
                start, end = lo, hi
            elif "-" in base:
                a, b = base.split("-")
                start, end = int(a), int(b)
            else:
                start = int(base)
                end = hi if step_text else start
        except ValueError:
            raise ValueError(f"Invalid cron {name} field: {text!r}") from None
        if step < 1 or start > end or start < lo or end > hi:
            raise ValueError(f"Cron {name} field out of range {lo}-{hi}: {text!r}")
        values.update(range(start, end + 1, step))
    return frozenset(values)


class Cron(NamedTuple):
    minute: frozenset[int]
    hour: frozenset[int]
    dom: frozenset[int]
    month: frozenset[int]
    dow: frozenset[int]
    dom_star: bool
    dow_star: bool


def parse_cron(expr: str) -> Cron:
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"Cron needs 5 fields (minute hour dom month dow), got {len(fields)}")
    parsed = [_parse_field(f, lo, hi, name) for f, (lo, hi), name in zip(fields, _RANGES, _NAMES)]
    parsed[4] = frozenset(v % 7 for v in parsed[4])
    return Cron(*parsed, fields[2].startswith("*"), fields[4].startswith("*"))


def cron_matches(cron: Cron, dt: datetime) -> bool:
    if dt.minute not in cron.minute or dt.hour not in cron.hour or dt.month not in cron.month:
        return False
    dom_ok = dt.day in cron.dom
    dow_ok = (dt.weekday() + 1) % 7 in cron.dow
    # Vixie semantics: a field starting with "*" is unrestricted; when both are
    # restricted, either may match.
    if not cron.dom_star and not cron.dow_star:
        return dom_ok or dow_ok
    return dom_ok and dow_ok


class Schedule(BaseModel):
    id: str
    cron: str
    goal: str
    profile: str = "flash"
    device_serial: str | None = None
    enabled: bool = True
    created_at: str
    last_fired_minute: str | None = None
    last_session_id: str | None = None
    last_error: str | None = None


class SchedulerService:
    def __init__(self, path: Path | None = None):
        self.path = path or DB_PATH.parent / "schedules.json"
        self._items: list[Schedule] = []
        try:
            self._items = [Schedule(**d) for d in json.loads(self.path.read_text("utf-8"))]
        except FileNotFoundError:
            pass
        except ValueError:
            # Keep the unreadable file for the user instead of overwriting it on the next save.
            bad = self.path.with_suffix(".json.bad")
            os.replace(self.path, bad)
            logger.error(f"Unreadable schedules file moved to {bad}; starting with no schedules")

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps([s.model_dump() for s in self._items], indent=2), "utf-8")
        os.replace(tmp, self.path)

    def list(self) -> list[Schedule]:
        return list(self._items)

    def add(
        self, cron: str, goal: str, profile: str = "flash", device_serial: str | None = None
    ) -> Schedule:
        parse_cron(cron)
        if not goal.strip():
            raise ValueError("Goal must not be empty")
        item = Schedule(
            id=uuid.uuid4().hex[:8],
            cron=cron,
            goal=goal,
            profile=profile,
            device_serial=device_serial,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        self._items.append(item)
        self._save()
        return item

    def remove(self, schedule_id: str) -> bool:
        kept = [s for s in self._items if s.id != schedule_id]
        if len(kept) == len(self._items):
            return False
        self._items = kept
        self._save()
        return True

    async def tick(self, now: datetime, submit: Submit) -> None:
        minute = now.replace(second=0, microsecond=0)
        key = minute.isoformat(timespec="minutes")
        for item in list(self._items):
            if not item.enabled or item.last_fired_minute == key:
                continue
            try:
                due = cron_matches(parse_cron(item.cron), minute)
            except ValueError as exc:
                item.last_error = str(exc)
                continue
            if not due:
                continue
            item.last_fired_minute = key
            if item.last_session_id and any(
                isinstance(t, dict) and t.get("session_id") == item.last_session_id
                for t in state.queue_items
            ):
                item.last_error = "skipped: previous run still active"
                continue
            item.last_error = None
            try:
                response = await submit(
                    RunRequest(
                        goal=item.goal,
                        profile=item.profile,
                        device_serial=item.device_serial,
                        ingress="scheduler",
                    )
                )
                tasks = response.get("tasks") or []
                if tasks:
                    item.last_session_id = tasks[0].get("session_id")
                if response.get("status") == "rejected":
                    item.last_error = str(response.get("error") or "rejected")
            except HTTPException as exc:
                item.last_error = str(exc.detail)
            except Exception as exc:
                item.last_error = str(exc) or type(exc).__name__
        self._save()

    async def loop(self, submit: Submit) -> None:
        while not state.is_shutting_down:
            now = datetime.now()
            # Small pad so we wake after the boundary, not just before it.
            delay = 60.05 - now.second - now.microsecond / 1e6
            try:
                await asyncio.wait_for(state.shutdown_event.wait(), timeout=delay)
                return
            except TimeoutError:
                pass
            try:
                await self.tick(datetime.now(), submit)
            except Exception:
                logger.exception("Scheduler tick failed")


scheduler_service = SchedulerService()
