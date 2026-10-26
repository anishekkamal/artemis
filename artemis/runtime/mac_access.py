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

"""Read-only access to user-chosen folders on the Mac, plus copying files to the phone.

The allowlist lives in ``mac_access.json`` next to the database and is re-read on every
call, so portal edits reach running tasks without a restart. Nothing here writes, moves
or deletes anything on the Mac.
"""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import posixpath
import shlex
import subprocess
from typing import Any

from artemis.config import DB_PATH
from artemis.runtime.adb_endpoint import adb_command
from third_party.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)

MAX_COPY_BYTES = 500 * 1024 * 1024
DEFAULT_PHONE_FOLDER = "/sdcard/Download"
_PHONE_ROOTS = ("/sdcard", "/storage/emulated/0")
_SCAN_TIMEOUT_SECONDS = 15


NO_ROOTS_MESSAGE = (
    "No Mac folders are shared. The user can add one in the portal under Mac Folders."
)


class MacAccessError(Exception):
    """A refusal or failure whose message is safe to show the user or the agent."""


def _store_path(store: Path | None) -> Path:
    return store or DB_PATH.parent / "mac_access.json"


def load_roots(store: Path | None = None) -> list[str]:
    path = _store_path(store)
    try:
        roots = json.loads(path.read_text("utf-8"))["roots"]
        if not isinstance(roots, list):
            raise ValueError("roots is not a list")
        return [r for r in roots if isinstance(r, str)]
    except FileNotFoundError:
        return []
    except (ValueError, KeyError, TypeError):
        # Keep the unreadable file for the user instead of overwriting it on the next save.
        bad = path.with_suffix(".json.bad")
        os.replace(path, bad)
        logger.error(f"Unreadable Mac access file moved to {bad}; starting with no folders")
        return []


def _save_roots(roots: list[str], store: Path | None) -> None:
    path = _store_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"roots": roots}, indent=2), "utf-8")
    os.replace(tmp, path)


def root_exists(path: str) -> bool:
    return Path(path).expanduser().is_dir()


def _as_folder(path: str) -> str:
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise MacAccessError(f"Folder not found: {path}") from exc
    if not resolved.is_dir():
        raise MacAccessError(f"Not a folder: {path}")
    if resolved == Path(resolved.anchor):
        raise MacAccessError("The whole disk cannot be shared; choose a specific folder.")
    return str(resolved)


def add_root(path: str, store: Path | None = None) -> str:
    folder = _as_folder(path)
    roots = load_roots(store)
    if folder not in roots:
        _save_roots([*roots, folder], store)
    return folder


def remove_root(path: str, store: Path | None = None) -> bool:
    roots = load_roots(store)
    target = _normalize_stored(path)
    kept = [r for r in roots if r != target and r != path]
    if len(kept) == len(roots):
        return False
    _save_roots(kept, store)
    return True


def replace_root(old: str, new: str, store: Path | None = None) -> str | None:
    """Swaps ``old`` for ``new`` in place. Returns None when ``old`` is not shared."""
    roots = load_roots(store)
    old_value = next((r for r in roots if r in (old, _normalize_stored(old))), None)
    if old_value is None:
        return None
    folder = _as_folder(new)
    swapped = [folder if r == old_value else r for r in roots]
    _save_roots(list(dict.fromkeys(swapped)), store)
    return folder


def _normalize_stored(path: str) -> str:
    # A stored root may no longer exist, so fall back to the plain string.
    try:
        return str(Path(path).expanduser().resolve())
    except (OSError, RuntimeError):
        return path


def resolve_allowed(path: str, roots: list[str]) -> Path:
    """Resolves ``path`` and proves it sits inside a shared folder and is not hidden."""
    if not roots:
        raise MacAccessError(NO_ROOTS_MESSAGE)
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise MacAccessError(f"Not found on the Mac: {path}") from exc
    for root in roots:
        try:
            root_resolved = Path(root).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if not resolved.is_relative_to(root_resolved):
            continue
        if any(part.startswith(".") for part in resolved.relative_to(root_resolved).parts):
            raise MacAccessError(f"Hidden files and folders are not accessible: {path}")
        return resolved
    raise MacAccessError(
        f"{path} is outside the shared Mac folders. Shared folders: {', '.join(roots)}"
    )


def _entry(path: Path, name: str | None = None) -> dict[str, Any]:
    st = path.stat()
    return {
        "name": name or path.name,
        "path": str(path),
        "is_dir": path.is_dir(),
        "size": st.st_size,
        "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
    }


def list_files(path: str | None, roots: list[str], limit: int = 200) -> list[dict[str, Any]]:
    """Newest-first listing of a shared folder, or of the shared roots when ``path`` is empty."""
    if not path:
        if not roots:
            raise MacAccessError(NO_ROOTS_MESSAGE)
        found = []
        for root in roots:
            try:
                found.append(_entry(Path(root).expanduser().resolve(strict=True), root))
            except OSError:
                continue
        return found[:limit]
    folder = resolve_allowed(path, roots)
    if not folder.is_dir():
        raise MacAccessError(f"Not a folder: {path}")
    entries = []
    try:
        children = [c for c in folder.iterdir() if not c.name.startswith(".")]
    except OSError as exc:
        raise MacAccessError(f"Cannot read {path}: {exc.strerror or exc}") from exc
    for child in children:
        try:
            entries.append(_entry(child))
        except OSError:
            continue
    entries.sort(key=lambda e: e["modified"], reverse=True)
    return entries[:limit]


def _validate_phone_folder(folder: str) -> str:
    if ".." in folder.split("/"):
        raise MacAccessError("PhoneFolder must not contain '..'.")
    normal = posixpath.normpath(folder)
    if not any(normal == base or normal.startswith(base + "/") for base in _PHONE_ROOTS):
        raise MacAccessError(
            "PhoneFolder must be under /sdcard/ (for example /sdcard/Download or"
            f" /sdcard/Pictures), got {folder!r}."
        )
    return normal


def _run_adb(device_id: str, args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        adb_command(["-s", device_id, *args]),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def push_to_phone(
    device_id: str,
    mac_path: str,
    phone_folder: str = DEFAULT_PHONE_FOLDER,
    roots: list[str] | None = None,
) -> str:
    """Copies one shared file to the phone and returns its phone path. The Mac copy is untouched."""
    source = resolve_allowed(mac_path, load_roots() if roots is None else roots)
    if not source.is_file():
        raise MacAccessError(f"Only files can be copied, not folders: {mac_path}")
    size = source.stat().st_size
    if size > MAX_COPY_BYTES:
        raise MacAccessError(
            f"{source.name} is {size // (1024 * 1024)} MB; the limit is"
            f" {MAX_COPY_BYTES // (1024 * 1024)} MB."
        )
    folder = _validate_phone_folder(phone_folder)
    destination = f"{folder}/{source.name}"
    # ponytail: fixed 2 MB/s floor for the timeout; USB 2 on a bad cable is the ceiling.
    timeout = 60 + size / (2 * 1024 * 1024)
    try:
        made = _run_adb(device_id, ["shell", "mkdir", "-p", shlex.quote(folder)], 15)
        pushed = (
            _run_adb(device_id, ["push", str(source), destination], timeout)
            if made.returncode == 0
            else made
        )
    except subprocess.TimeoutExpired as exc:
        raise MacAccessError(f"Copy to the phone timed out after {exc.timeout:.0f} s.") from exc
    except OSError as exc:
        raise MacAccessError(f"Could not run adb: {exc}") from exc
    if pushed.returncode != 0:
        detail = (pushed.stderr or pushed.stdout).strip()
        raise MacAccessError(f"Copy to the phone failed: {detail or 'adb returned an error'}")
    _scan_media(device_id, destination)
    return destination


def _scan_media(device_id: str, phone_path: str) -> None:
    """Asks MediaProvider to index the file so Gallery and Files show it. Never fails the copy."""
    try:
        result = _run_adb(
            device_id,
            [
                "shell",
                "content call --uri content://media/external_primary"
                f" --method scan_file --arg {shlex.quote(phone_path)}",
            ],
            _SCAN_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            logger.warning(f"Media scan of {phone_path} failed: {result.stderr.strip()}")
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning(f"Media scan of {phone_path} failed: {exc}")
