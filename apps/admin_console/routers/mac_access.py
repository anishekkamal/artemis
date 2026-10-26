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

"""Manage the Mac folders Artemis may read, including the native macOS folder picker."""

import asyncio
import sys

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from artemis.runtime import mac_access
from artemis.runtime.mac_access import MacAccessError

router = APIRouter(tags=["mac-access"])

PICK_TIMEOUT_SECONDS = 300
_PICKER_SCRIPT = 'POSIX path of (choose folder with prompt "Choose a folder Artemis can read")'
# osascript reports a dismissed dialog as error -128 ("User canceled.").
_USER_CANCELED = "-128"


class PathRequest(BaseModel):
    path: str


class ReplaceRequest(BaseModel):
    old_path: str
    new_path: str


@router.get("/api/mac-access")
async def list_roots():
    return {
        "roots": [{"path": r, "exists": mac_access.root_exists(r)} for r in mac_access.load_roots()]
    }


@router.post("/api/mac-access")
async def add_root(request: PathRequest):
    try:
        return {"path": mac_access.add_root(request.path)}
    except MacAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/api/mac-access")
async def replace_root(request: ReplaceRequest):
    try:
        new = mac_access.replace_root(request.old_path, request.new_path)
    except MacAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if new is None:
        raise HTTPException(status_code=404, detail="Folder is not shared")
    return {"path": new}


@router.delete("/api/mac-access")
async def remove_root(path: str | None = Query(default=None), body: PathRequest | None = None):
    target = path or (body.path if body else None)
    if not target:
        raise HTTPException(status_code=422, detail="path is required")
    if not mac_access.remove_root(target):
        raise HTTPException(status_code=404, detail="Folder is not shared")
    return {"status": "removed"}


@router.post("/api/mac-access/pick")
async def pick_folder():
    """Opens the macOS folder chooser on the Mac running Artemis and returns the choice."""
    if sys.platform != "darwin":
        raise HTTPException(status_code=501, detail="The folder picker only works on macOS")
    process = await asyncio.create_subprocess_exec(
        "osascript",
        "-e",
        _PICKER_SCRIPT,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(process.communicate(), PICK_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="The folder picker timed out") from exc
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    if process.returncode != 0:
        if _USER_CANCELED in err.decode(errors="replace"):
            return {"path": None}
        raise HTTPException(status_code=500, detail=err.decode(errors="replace").strip())
    chosen = out.decode().strip()
    return {"path": chosen.rstrip("/") or "/" if chosen else None}
