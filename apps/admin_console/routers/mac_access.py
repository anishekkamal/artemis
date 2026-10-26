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
_CHOOSE = 'POSIX path of (choose folder with prompt "Choose a folder Artemis can read")'
# osascript itself is a background process, so its dialog opens behind the browser.
# Asking System Events to show it brings it to the front.
_PICKER_SCRIPTS = (
    ["-e", 'tell application "System Events"', "-e", "activate", "-e", _CHOOSE, "-e", "end tell"],
    ["-e", _CHOOSE],
)
# osascript reports a dismissed dialog as error -128 ("User canceled.").
_USER_CANCELED = "-128"
# Error -1743: macOS has not allowed this process to control System Events.
_NOT_AUTHORIZED = "-1743"


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
    for script in _PICKER_SCRIPTS:
        code, out, err = await _run_picker(script)
        if code == 0 or _NOT_AUTHORIZED not in err:
            break
    if code != 0:
        if _USER_CANCELED in err:
            return {"path": None}
        raise HTTPException(
            status_code=500, detail=err.strip() or "The folder picker closed unexpectedly"
        )
    chosen = out.strip()
    return {"path": chosen.rstrip("/") or "/" if chosen else None}


async def _run_picker(script: list[str]) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        "osascript",
        *script,
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
    return process.returncode, out.decode(errors="replace"), err.decode(errors="replace")
