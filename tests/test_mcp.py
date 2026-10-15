import asyncio
import base64
import json
from pathlib import Path
import sys

import pytest

mcp = pytest.importorskip("mcp")
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from videoverify.core import Inspector
from videoverify.server import create_server


def test_real_stdio_tool_and_resource(media, tmp_path):
    async def scenario():
        parameters = StdioServerParameters(command=sys.executable, args=["-m", "videoverify.server",
            "--allow-root", str(media["root"]), "--output-root", str(tmp_path / "stdio")])
        async with Client(parameters) as client:
            tools = await client.list_tools()
            assert {x.name for x in tools.tools} == {"inspect_video", "inspect_sequence"}
            result = await client.call_tool("inspect_video", {"video_path": str(media["tone"]), "timestamp": 1.3})
            assert not result.is_error
            report = result.structured_content
            assert report["ok"] and report["audio"]["status"] == "extracted"
            picture = await client.read_resource(report["frame"]["uri"])
            assert base64.b64decode(picture.contents[0].blob) == Path(report["frame"]["path"]).read_bytes()
            audio = await client.read_resource(report["audio"]["uri"])
            assert base64.b64decode(audio.contents[0].blob).startswith(b"RIFF")
            failed = await client.call_tool("inspect_video", {"video_path": "https://example.com/a.mp4", "timestamp": 0})
            assert failed.is_error and "local_path_required" in failed.content[0].text
            sequence = await client.call_tool("inspect_sequence", {"video_path": str(media["silent"]), "timestamps": [0, 1.3]})
            assert not sequence.is_error
            artifact = sequence.structured_content["frames"][1]
            actual = await client.read_resource(artifact["uri"])
            assert base64.b64decode(actual.contents[0].blob) == Path(artifact["path"]).read_bytes()
    asyncio.run(scenario())


def test_in_process_missing_and_silent(media, tmp_path):
    async def scenario():
        server = create_server(Inspector([media["root"]], tmp_path / "in-process"))
        async with Client(server) as client:
            silent = await client.call_tool("inspect_video", {"video_path": str(media["silent"]), "timestamp": 0})
            assert silent.structured_content["audio"]["status"] == "absent"
            error = await client.call_tool("inspect_video", {"video_path": str(media["root"] / "missing.mp4"), "timestamp": 0})
            assert error.is_error and "file_not_found" in error.content[0].text
    asyncio.run(scenario())


def test_optional_import_tool_has_same_error_contract(media, tmp_path):
    from videoverify.acquisition import Acquirer
    async def scenario():
        server = create_server(Inspector([media["root"]], tmp_path / "evidence"), Acquirer(tmp_path / "imports"))
        async with Client(server) as client:
            tools = await client.list_tools()
            assert "import_video" in {tool.name for tool in tools.tools}
            failed = await client.call_tool("import_video", {"url": "https://127.0.0.1/a.mp4"})
            assert failed.is_error and "unsupported_url" in failed.content[0].text
    asyncio.run(scenario())
