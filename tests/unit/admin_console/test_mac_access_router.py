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

import asyncio

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from apps.admin_console.routers import mac_access as router_module
from artemis.runtime import mac_access


@pytest.fixture
def api(tmp_path, monkeypatch):
    store = tmp_path / "state" / "mac_access.json"
    monkeypatch.setattr(mac_access, "_store_path", lambda s=None: s or store)
    app = FastAPI()
    app.include_router(router_module.router)
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost")
    return client, tmp_path


@pytest.mark.asyncio
async def test_crud_round_trip(api):
    client, tmp = api
    a, b = tmp / "a", tmp / "b"
    a.mkdir()
    b.mkdir()
    assert (await client.get("/api/mac-access")).json() == {"roots": []}

    assert (await client.post("/api/mac-access", json={"path": str(a)})).status_code == 200
    roots = (await client.get("/api/mac-access")).json()["roots"]
    assert roots == [{"path": str(a.resolve()), "exists": True}]

    res = await client.put("/api/mac-access", json={"old_path": str(a), "new_path": str(b)})
    assert res.json() == {"path": str(b.resolve())}

    assert (await client.delete("/api/mac-access", params={"path": str(b)})).status_code == 200
    assert (await client.get("/api/mac-access")).json() == {"roots": []}


@pytest.mark.asyncio
async def test_errors_and_missing(api):
    client, tmp = api
    res = await client.post("/api/mac-access", json={"path": str(tmp / "nope")})
    assert res.status_code == 400 and "not found" in res.json()["detail"].lower()
    assert (await client.post("/api/mac-access", json={"path": "/"})).status_code == 400

    res = await client.put("/api/mac-access", json={"old_path": "/x", "new_path": str(tmp)})
    assert res.status_code == 404
    assert (await client.delete("/api/mac-access", params={"path": "/x"})).status_code == 404
    assert (await client.delete("/api/mac-access")).status_code == 422


@pytest.mark.asyncio
async def test_delete_accepts_json_body_and_reports_vanished_folder(api):
    client, tmp = api
    gone = tmp / "gone"
    gone.mkdir()
    await client.post("/api/mac-access", json={"path": str(gone)})
    gone.rmdir()
    roots = (await client.get("/api/mac-access")).json()["roots"]
    assert roots[0]["exists"] is False
    res = await client.request("DELETE", "/api/mac-access", json={"path": str(gone)})
    assert res.status_code == 200


class FakeProc:
    def __init__(self, code, out=b"", err=b"", hang=False):
        self.returncode = None
        self._final = code
        self.out, self.err, self.hang, self.killed = out, err, hang, False

    async def communicate(self):
        if self.hang:
            await asyncio.sleep(10)
        self.returncode = self._final
        return self.out, self.err

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        return self.returncode


def _spawn(monkeypatch, *procs):
    seen = []
    queue = list(procs)

    async def fake(*args, **kwargs):
        seen.append(args)
        return queue.pop(0)

    monkeypatch.setattr(router_module.asyncio, "create_subprocess_exec", fake)
    monkeypatch.setattr(router_module.sys, "platform", "darwin")
    return seen


@pytest.mark.asyncio
async def test_pick_returns_path_without_trailing_slash(api, monkeypatch):
    seen = _spawn(monkeypatch, FakeProc(0, out=b"/Users/me/Pictures/\n"))
    res = await api[0].post("/api/mac-access/pick")
    assert res.json() == {"path": "/Users/me/Pictures"}
    assert seen[0][0] == "osascript" and "System Events" in " ".join(seen[0])
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_pick_falls_back_to_plain_dialog_when_system_events_is_not_allowed(api, monkeypatch):
    denied = FakeProc(1, err=b"Not authorized to send Apple events to System Events. (-1743)")
    seen = _spawn(monkeypatch, denied, FakeProc(0, out=b"/Users/me/Pictures\n"))
    assert (await api[0].post("/api/mac-access/pick")).json() == {"path": "/Users/me/Pictures"}
    assert "System Events" not in " ".join(seen[1])


@pytest.mark.asyncio
async def test_pick_cancel_returns_null(api, monkeypatch):
    err = b"execution error: User canceled. (-128)\n"
    _spawn(monkeypatch, FakeProc(1, err=err))
    assert (await api[0].post("/api/mac-access/pick")).json() == {"path": None}


@pytest.mark.asyncio
async def test_pick_other_failure_is_500(api, monkeypatch):
    _spawn(monkeypatch, FakeProc(1, err=b"boom"))
    res = await api[0].post("/api/mac-access/pick")
    assert res.status_code == 500 and res.json()["detail"] == "boom"


@pytest.mark.asyncio
async def test_pick_timeout_kills_dialog(api, monkeypatch):
    proc = FakeProc(0, hang=True)
    _spawn(monkeypatch, proc)
    monkeypatch.setattr(router_module, "PICK_TIMEOUT_SECONDS", 0.01)
    assert (await api[0].post("/api/mac-access/pick")).status_code == 504
    assert proc.killed


@pytest.mark.asyncio
async def test_pick_is_501_off_macos(api, monkeypatch):
    monkeypatch.setattr(router_module.sys, "platform", "linux")
    assert (await api[0].post("/api/mac-access/pick")).status_code == 501
