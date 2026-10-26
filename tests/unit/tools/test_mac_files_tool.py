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

from types import SimpleNamespace

import pytest

from artemis.runtime import mac_access
from artemis.tools.system.mac_files import copy_to_phone, list_mac_files


@pytest.fixture
def share(tmp_path, monkeypatch):
    root = tmp_path / "share"
    root.mkdir()
    (root / "a.txt").write_text("hi")
    (root / ".secret").write_text("x")
    monkeypatch.setattr(mac_access, "load_roots", lambda store=None: [str(root)])
    return root


@pytest.fixture
def pushes(monkeypatch):
    calls = []

    def fake_push(device_id, mac_path, phone_folder, roots=None):
        calls.append((device_id, mac_path, phone_folder))
        return f"{phone_folder}/{mac_path.rsplit('/', 1)[-1]}"

    monkeypatch.setattr(mac_access, "push_to_phone", fake_push)
    return calls


CTX = SimpleNamespace(device=SimpleNamespace(device_id="SER"))


@pytest.mark.asyncio
async def test_list_shows_roots_then_files_without_hidden(share):
    assert str(share) in await list_mac_files.execute(ctx=CTX)
    out = await list_mac_files.execute(ctx=CTX, Path=str(share))
    assert "a.txt" in out and ".secret" not in out


@pytest.mark.asyncio
async def test_list_errors_come_back_as_text(share, monkeypatch):
    assert "outside" in await list_mac_files.execute(ctx=CTX, Path="/etc")
    monkeypatch.setattr(mac_access, "load_roots", lambda store=None: [])
    assert "Mac Folders" in await list_mac_files.execute(ctx=CTX)


@pytest.mark.asyncio
async def test_copy_returns_phone_path_using_ctx_device(share, pushes):
    out = await copy_to_phone.execute(ctx=CTX, MacPath=str(share / "a.txt"))
    assert out == "Copied to the phone: /sdcard/Download/a.txt"
    assert pushes == [("SER", str(share / "a.txt"), "/sdcard/Download")]


@pytest.mark.asyncio
async def test_copy_falls_back_to_driver_device_and_reports_no_device(share, pushes):
    driver = SimpleNamespace(device_id="DRV")
    await copy_to_phone.execute(
        driver=driver, MacPath=str(share / "a.txt"), PhoneFolder="/sdcard/Pictures"
    )
    assert pushes == [("DRV", str(share / "a.txt"), "/sdcard/Pictures")]
    assert "No phone" in await copy_to_phone.execute(MacPath="x")


@pytest.mark.asyncio
async def test_copy_refusal_is_text(share):
    out = await copy_to_phone.execute(ctx=CTX, MacPath=str(share / ".secret"))
    assert "Hidden" in out
