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

import os
import subprocess

import pytest

from artemis.runtime import mac_access as m


@pytest.fixture
def share(tmp_path):
    root = tmp_path / "share"
    root.mkdir()
    (root / "a.txt").write_text("hi")
    (root / "sub").mkdir()
    (root / "sub" / "b.png").write_bytes(b"png")
    (root / ".secret").write_text("x")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("x")
    (tmp_path / "outside.txt").write_text("nope")
    return root


def test_resolves_file_inside_root(share):
    assert (
        m.resolve_allowed(str(share / "sub" / "b.png"), [str(share)])
        == (share / "sub" / "b.png").resolve()
    )


def test_dotdot_escape_is_refused(share):
    with pytest.raises(m.MacAccessError, match="outside"):
        m.resolve_allowed(str(share / "sub" / ".." / ".." / "outside.txt"), [str(share)])


def test_symlink_escaping_root_is_refused(share, tmp_path):
    (share / "link.txt").symlink_to(tmp_path / "outside.txt")
    with pytest.raises(m.MacAccessError, match="outside"):
        m.resolve_allowed(str(share / "link.txt"), [str(share)])


def test_symlink_into_hidden_dir_is_refused(share):
    (share / "innocent").symlink_to(share / ".git")
    with pytest.raises(m.MacAccessError, match="Hidden"):
        m.resolve_allowed(str(share / "innocent" / "config"), [str(share)])


@pytest.mark.parametrize("rel", [".secret", ".git/config", ".git"])
def test_hidden_components_are_refused(share, rel):
    with pytest.raises(m.MacAccessError, match="Hidden"):
        m.resolve_allowed(str(share / rel), [str(share)])


def test_missing_file_and_no_roots(share):
    with pytest.raises(m.MacAccessError, match="Not found"):
        m.resolve_allowed(str(share / "nope.txt"), [str(share)])
    with pytest.raises(m.MacAccessError, match="Mac Folders"):
        m.resolve_allowed(str(share / "a.txt"), [])


def test_list_files_skips_hidden_and_sorts_newest_first(share):
    os.utime(share / "a.txt", (1_000_000_000, 1_000_000_000))
    names = [e["name"] for e in m.list_files(str(share), [str(share)])]
    assert names == ["sub", "a.txt"]
    assert [e["name"] for e in m.list_files(str(share), [str(share)], limit=1)] == ["sub"]


def test_list_files_without_path_lists_roots(share):
    entries = m.list_files(None, [str(share)])
    assert [(e["name"], e["is_dir"]) for e in entries] == [(str(share), True)]
    with pytest.raises(m.MacAccessError, match="Mac Folders"):
        m.list_files("", [])


def test_list_files_on_a_file_is_refused(share):
    with pytest.raises(m.MacAccessError, match="Not a folder"):
        m.list_files(str(share / "a.txt"), [str(share)])


@pytest.mark.parametrize(
    "folder", ["/data/local/tmp", "/sdcard/../data", "/sdcardx/Download", "Download", "/"]
)
def test_phone_folder_rejects(folder):
    with pytest.raises(m.MacAccessError):
        m._validate_phone_folder(folder)


def test_phone_folder_normalizes():
    assert m._validate_phone_folder("/sdcard//Download/") == "/sdcard/Download"
    assert m._validate_phone_folder("/storage/emulated/0/Pictures") == (
        "/storage/emulated/0/Pictures"
    )


class FakeAdb:
    def __init__(self, fail_on=None, scan_raises=False):
        self.calls = []
        self.fail_on = fail_on
        self.scan_raises = scan_raises

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if self.scan_raises and "scan_file" in " ".join(argv):
            raise subprocess.TimeoutExpired(argv, 1)
        failed = self.fail_on and self.fail_on in argv
        return subprocess.CompletedProcess(
            argv, 1 if failed else 0, "", "adb: error: closed" if failed else ""
        )


@pytest.fixture
def adb(monkeypatch):
    fake = FakeAdb()
    monkeypatch.setattr(m, "adb_command", lambda args: ["adb", *args])
    monkeypatch.setattr(m.subprocess, "run", fake)
    return fake


def test_push_builds_adb_argv_and_scans(share, adb):
    out = m.push_to_phone("SER", str(share / "a.txt"), "/sdcard/Download/", [str(share)])
    assert out == ("/sdcard/Download/a.txt", 1)
    src = str((share / "a.txt").resolve())
    assert adb.calls[0] == ["adb", "-s", "SER", "shell", "mkdir", "-p", "/sdcard/Download"]
    assert adb.calls[1] == ["adb", "-s", "SER", "push", src, "/sdcard/Download/"]
    assert "scan_file --arg /sdcard/Download/a.txt" in adb.calls[2][-1]
    assert (share / "a.txt").read_text() == "hi"


def test_push_failure_is_reported(share, adb):
    adb.fail_on = "push"
    with pytest.raises(m.MacAccessError, match="failed: adb: error: closed"):
        m.push_to_phone("SER", str(share / "a.txt"), roots=[str(share)])


def test_failed_scan_does_not_fail_copy(share, adb):
    adb.scan_raises = True
    assert m.push_to_phone("SER", str(share / "a.txt"), roots=[str(share)])[0].endswith("/a.txt")


def test_push_refuses_hidden_and_oversize(share, adb, monkeypatch):
    with pytest.raises(m.MacAccessError, match="Hidden"):
        m.push_to_phone("SER", str(share / ".secret"), roots=[str(share)])
    monkeypatch.setattr(m, "MAX_COPY_BYTES", 1)
    with pytest.raises(m.MacAccessError, match="limit"):
        m.push_to_phone("SER", str(share / "a.txt"), roots=[str(share)])
    assert adb.calls == []


def test_push_folder_keeps_structure_and_skips_hidden_and_escapes(tmp_path, adb, monkeypatch):
    share = tmp_path / "share"
    kit = share / "kit"
    (kit / "x1").mkdir(parents=True)
    (kit / ".git").mkdir()
    (kit / "top.md").write_text("t")
    (kit / ".DS_Store").write_text("junk")
    (kit / "x1" / "01.png").write_text("png")
    (kit / ".git" / "config").write_text("secret")
    outside = tmp_path / "outside.txt"
    outside.write_text("no")
    (kit / "link.txt").symlink_to(outside)

    assert m.push_to_phone("SER", str(kit), roots=[str(share)]) == ("/sdcard/Download/kit", 2)
    assert adb.calls[0] == [
        "adb",
        "-s",
        "SER",
        "shell",
        "mkdir",
        "-p",
        "/sdcard/Download/kit",
        "/sdcard/Download/kit/x1",
    ]
    pushes = adb.calls[1:3]
    assert pushes == [
        ["adb", "-s", "SER", "push", str((kit / "top.md").resolve()), "/sdcard/Download/kit/"],
        [
            "adb",
            "-s",
            "SER",
            "push",
            str((kit / "x1" / "01.png").resolve()),
            "/sdcard/Download/kit/x1/",
        ],
    ]
    assert "scan_file --arg /sdcard/Download/kit" in adb.calls[3][-1]

    monkeypatch.setattr(m, "MAX_COPY_FILES", 1)
    with pytest.raises(m.MacAccessError, match="more than 1 files"):
        m.push_to_phone("SER", str(kit), roots=[str(share)])


def test_push_folder_with_only_hidden_files_is_refused(share, adb):
    (share / "sub" / "b.png").unlink()
    (share / "sub" / ".hidden").write_text("x")
    with pytest.raises(m.MacAccessError, match="Nothing to copy"):
        m.push_to_phone("SER", str(share / "sub"), roots=[str(share)])
    assert adb.calls == []


def test_push_bad_phone_folder_runs_nothing(share, adb):
    with pytest.raises(m.MacAccessError):
        m.push_to_phone("SER", str(share / "a.txt"), "/data/local/tmp", [str(share)])
    assert adb.calls == []


def test_corrupt_file_is_moved_aside(tmp_path):
    store = tmp_path / "mac_access.json"
    store.write_text("{not json")
    assert m.load_roots(store) == []
    assert (tmp_path / "mac_access.json.bad").read_text() == "{not json"
    assert not store.exists()


def test_wrong_shape_is_moved_aside(tmp_path):
    store = tmp_path / "mac_access.json"
    store.write_text('["a"]')
    assert m.load_roots(store) == []
    assert (tmp_path / "mac_access.json.bad").exists()


def test_add_remove_replace(tmp_path, share):
    store = tmp_path / "state" / "mac_access.json"
    other = tmp_path / "other"
    other.mkdir()
    assert m.add_root(str(share), store) == str(share.resolve())
    m.add_root(str(share), store)
    assert m.load_roots(store) == [str(share.resolve())]

    assert m.replace_root(str(share), str(other), store) == str(other.resolve())
    assert m.load_roots(store) == [str(other.resolve())]
    assert m.replace_root("/never/shared", str(share), store) is None

    assert m.remove_root(str(other), store) is True
    assert m.remove_root(str(other), store) is False
    assert m.load_roots(store) == []


def test_add_rejects_missing_file_and_filesystem_root(tmp_path, share):
    store = tmp_path / "mac_access.json"
    for bad in ("/", str(tmp_path / "missing"), str(share / "a.txt")):
        with pytest.raises(m.MacAccessError):
            m.add_root(bad, store)
    assert m.load_roots(store) == []


def test_removed_root_that_no_longer_exists_can_still_be_removed(tmp_path):
    store = tmp_path / "mac_access.json"
    gone = tmp_path / "gone"
    gone.mkdir()
    m.add_root(str(gone), store)
    gone.rmdir()
    assert m.remove_root(str(gone), store) is True
