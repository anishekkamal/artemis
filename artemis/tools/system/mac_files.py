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

"""Tools that let the agent read the user's shared Mac folders and copy files to the phone."""

import asyncio
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from artemis.context import ArtemisContext
from artemis.core.tool_failure import ToolFailure
from artemis.data_engine.trace import trace_langchain_tool
from artemis.runtime import mac_access
from artemis.runtime.mac_access import MacAccessError
from artemis.tools.base import ArtemisTool
from artemis.tools.tool_wrapper import ToolWrapper

_READ_ONLY = (
    "Read-only: Artemis never changes, moves or deletes anything on the Mac, and hidden"
    " files and folders are skipped. Only folders the user shared in the portal are reachable."
)


def _device_id(driver: Any, ctx: ArtemisContext | None) -> str | None:
    if ctx is not None and getattr(getattr(ctx, "device", None), "device_id", None):
        return ctx.device.device_id
    return getattr(driver, "device_id", None)


class ListMacFilesArgs(BaseModel):
    """Arguments schema for list_mac_files."""

    Path: str = Field(
        default="",
        description=(
            "Absolute path of a shared Mac folder or a folder inside one. Leave empty to list"
            " the shared folders themselves."
        ),
    )


class ListMacFilesTool(ArtemisTool):
    def __init__(self):
        super().__init__(
            name="list_mac_files",
            description=(
                "[MAC] Lists files in a folder the user shared from their Mac, newest first."
                " Call it with no Path to see which folders are shared. " + _READ_ONLY
            ),
            args_schema=ListMacFilesArgs,
            category="system",
        )

    async def execute(
        self, driver: Any = None, ctx: ArtemisContext | None = None, Path: str = "", **kwargs: Any
    ) -> str:
        try:
            entries = mac_access.list_files(Path, mac_access.load_roots())
        except MacAccessError as exc:
            return ToolFailure(str(exc))
        if not entries:
            return "The folder is empty (hidden files are not listed)."
        lines = [
            f"{'[dir] ' if e['is_dir'] else ''}{e['path']}"
            + ("" if e["is_dir"] else f"  ({e['size']} bytes, modified {e['modified']})")
            for e in entries
        ]
        return "\n".join(lines)


class CopyToPhoneArgs(BaseModel):
    """Arguments schema for copy_to_phone."""

    MacPath: str = Field(
        ...,
        description=(
            "Absolute path of a file or folder inside a shared Mac folder. A folder is copied"
            " whole, sub-folders included, as a folder of the same name on the phone."
        ),
    )
    PhoneFolder: str = Field(
        default=mac_access.DEFAULT_PHONE_FOLDER,
        description=(
            "Folder on the phone to copy into, under /sdcard/. Pictures and videos belong in"
            " /sdcard/Pictures or /sdcard/DCIM, everything else in /sdcard/Download (default)."
        ),
    )


class CopyToPhoneTool(ArtemisTool):
    def __init__(self):
        super().__init__(
            name="copy_to_phone",
            description=(
                "[MAC] Copies a file, or a whole folder, from a shared Mac folder onto the"
                " phone in one call and returns its path on the phone, which Gallery and the"
                " Files app then show. Lands in /sdcard/Download unless PhoneFolder says"
                " otherwise; existing files of the same name are overwritten. The Mac copy is"
                " left untouched. " + _READ_ONLY
            ),
            args_schema=CopyToPhoneArgs,
            category="system",
        )

    async def execute(
        self,
        driver: Any = None,
        ctx: ArtemisContext | None = None,
        MacPath: str = "",
        PhoneFolder: str = mac_access.DEFAULT_PHONE_FOLDER,
        **kwargs: Any,
    ) -> str:
        device_id = _device_id(driver, ctx)
        if not device_id:
            return ToolFailure("No phone is connected, so the file cannot be copied.")
        try:
            phone_path, count = await asyncio.to_thread(
                mac_access.push_to_phone, device_id, MacPath, PhoneFolder
            )
        except MacAccessError as exc:
            return ToolFailure(str(exc))
        files = "1 file" if count == 1 else f"{count} files"
        return f"Copied {files} to the phone: {phone_path}"


list_mac_files = ListMacFilesTool()
copy_to_phone = CopyToPhoneTool()
MAC_FILE_TOOLS = {t.name: t for t in (list_mac_files, copy_to_phone)}


def get_list_mac_files_tool(ctx: ArtemisContext) -> BaseTool:
    return trace_langchain_tool(list_mac_files.to_langchain_tool(ctx), ctx)


def get_copy_to_phone_tool(ctx: ArtemisContext) -> BaseTool:
    return trace_langchain_tool(copy_to_phone.to_langchain_tool(ctx), ctx)


list_mac_files_wrapper = ToolWrapper(
    tool_fn_getter=get_list_mac_files_tool,
    on_success_fn=lambda output: output,
    on_failure_fn=lambda err: f"Listing Mac files failed: {err}",
)

copy_to_phone_wrapper = ToolWrapper(
    tool_fn_getter=get_copy_to_phone_tool,
    on_success_fn=lambda output: output,
    on_failure_fn=lambda err: f"Copy to phone failed: {err}",
)
