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

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

try:
    from admin_console.services.scheduler_service import scheduler_service
except ImportError:
    from apps.admin_console.services.scheduler_service import scheduler_service

router = APIRouter(tags=["schedules"])


class ScheduleRequest(BaseModel):
    cron: str
    goal: str
    profile: str = "flash"
    device_serial: str | None = None


@router.get("/api/schedules")
async def list_schedules():
    return {"schedules": [s.model_dump() for s in scheduler_service.list()]}


@router.post("/api/schedules")
async def create_schedule(request: ScheduleRequest):
    try:
        return scheduler_service.add(
            request.cron, request.goal, request.profile, request.device_serial
        ).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class ScheduleUpdate(BaseModel):
    enabled: bool


@router.patch("/api/schedules/{schedule_id}")
async def update_schedule(schedule_id: str, update: ScheduleUpdate):
    item = scheduler_service.set_enabled(schedule_id, update.enabled)
    if item is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return item.model_dump()


@router.delete("/api/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str):
    if not scheduler_service.remove(schedule_id):
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"status": "removed"}
