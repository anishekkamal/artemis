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

"""Cron parsing and SchedulerService.tick behavior."""

from datetime import datetime
import json

from fastapi import HTTPException
import pytest

from apps.admin_console.core.state import state
from apps.admin_console.services.scheduler_service import (
    SchedulerService,
    cron_matches,
    parse_cron,
)

# 2026-10-26 is a Monday.
MON_0900 = datetime(2026, 10, 26, 9, 0)


def test_parse_fields():
    minute, hour, _, _, dow = parse_cron("*/15 9-11 * * 1,3")
    assert minute == {0, 15, 30, 45}
    assert hour == {9, 10, 11}
    assert dow == {1, 3}
    assert parse_cron("10-30/10 * * * *")[0] == {10, 20, 30}
    assert parse_cron("* * * * 7")[4] == parse_cron("* * * * 0")[4] == {0}


@pytest.mark.parametrize(
    "expr",
    ["* * * *", "60 * * * *", "* 24 * * *", "* * 0 * *", "a * * * *", "*/0 * * * *", "5-1 * * * *"],
)
def test_parse_rejects_bad_input(expr):
    with pytest.raises(ValueError):
        parse_cron(expr)


def test_dom_or_dow_when_both_restricted():
    # The 15th OR any Monday.
    expr = parse_cron("0 9 15 * 1")
    assert cron_matches(expr, MON_0900)
    assert cron_matches(expr, datetime(2026, 10, 15, 9, 0))  # Thursday the 15th
    assert not cron_matches(expr, datetime(2026, 10, 14, 9, 0))
    # Only dow restricted: AND with the wildcard dom.
    assert not cron_matches(parse_cron("0 9 * * 2"), MON_0900)
    assert cron_matches(parse_cron("0 9 * * 1"), MON_0900)


class FakeSubmit:
    def __init__(self, response=None, exc=None):
        self.requests = []
        self.response = response or {"status": "queued", "tasks": [{"session_id": "sid-1"}]}
        self.exc = exc

    async def __call__(self, request):
        self.requests.append(request)
        if self.exc:
            raise self.exc
        return self.response


@pytest.fixture
def svc(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "queue_items", [])
    return SchedulerService(tmp_path / "schedules.json")


def saved(svc):
    return json.loads(svc.path.read_text())[0]


@pytest.mark.asyncio
async def test_fires_once_per_minute_and_persists(svc):
    svc.add("0 9 * * *", "check battery", "pro", "SER1")
    submit = FakeSubmit()
    await svc.tick(MON_0900, submit)
    await svc.tick(MON_0900.replace(second=30), submit)
    assert len(submit.requests) == 1
    req = submit.requests[0]
    assert (req.goal, req.profile, req.device_serial, req.ingress) == (
        "check battery",
        "pro",
        "SER1",
        "scheduler",
    )
    row = saved(svc)
    assert row["last_session_id"] == "sid-1"
    assert row["last_fired_minute"] == "2026-10-26T09:00"
    assert row["last_error"] is None
    assert SchedulerService(svc.path).list()[0].last_session_id == "sid-1"


@pytest.mark.asyncio
async def test_does_not_fire_when_not_due(svc):
    svc.add("0 9 * * *", "g")
    submit = FakeSubmit()
    await svc.tick(MON_0900.replace(minute=1), submit)
    assert submit.requests == []


@pytest.mark.asyncio
async def test_records_rejected_response(svc):
    svc.add("* * * * *", "g")
    await svc.tick(MON_0900, FakeSubmit({"status": "rejected", "error": "no device", "tasks": []}))
    assert saved(svc)["last_error"] == "no device"


@pytest.mark.asyncio
async def test_records_http_exception_and_keeps_other_schedules_running(svc):
    svc.add("* * * * *", "locked")
    svc.add("* * * * *", "second")

    async def submit(request):
        if request.goal == "locked":
            raise HTTPException(status_code=409, detail="device is locked")
        return {"status": "queued", "tasks": [{"session_id": "sid-2"}]}

    await svc.tick(MON_0900, submit)
    first, second = svc.list()
    assert first.last_error == "device is locked"
    assert second.last_session_id == "sid-2"


@pytest.mark.asyncio
async def test_skips_while_previous_session_still_queued(svc, monkeypatch):
    svc.add("* * * * *", "g")
    submit = FakeSubmit()
    await svc.tick(MON_0900, submit)
    monkeypatch.setattr(state, "queue_items", [{"session_id": "sid-1", "status": "running"}])
    await svc.tick(MON_0900.replace(minute=1), submit)
    assert len(submit.requests) == 1
    assert saved(svc)["last_error"] == "skipped: previous run still active"
    monkeypatch.setattr(state, "queue_items", [])
    await svc.tick(MON_0900.replace(minute=2), submit)
    assert len(submit.requests) == 2


def test_add_validates_and_remove(svc):
    with pytest.raises(ValueError):
        svc.add("nope", "g")
    item = svc.add("* * * * *", "g")
    assert svc.remove(item.id) is True
    assert svc.remove(item.id) is False
    assert json.loads(svc.path.read_text()) == []
