import asyncio
import base64
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("mcp")
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402


def test_real_stdio_uses_host_vision_and_returns_action_images_without_model_keys(monkeypatch):
    requests = []
    monkeypatch.delenv("IPHONE_MCP_ENABLE_DELEGATE", raising=False)

    class Handler(BaseHTTPRequestHandler):
        def reply(self, payload):
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/api/control/observe":
                self.reply({"screen_id": "one-use", "width": 608, "height": 1080,
                            "image_base64": base64.b64encode(b"synthetic jpeg").decode()})
            else:
                self.reply({"agent": {"running": False, "task": "", "steps": []}, "models": {}})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"null")
            requests.append((self.path, body))
            self.reply({"command_acknowledged": True, "effect_verified": False,
                        "image_base64": base64.b64encode(b"after action").decode()})

        def log_message(self, *_): pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    async def scenario():
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("LLM_", "ACTOR_", "PLANNER_"))}
        clean["IPHONE_MCP_ENABLE_DELEGATE"] = "0"
        params = StdioServerParameters(command=sys.executable, args=[
            "-m", "hidagent.cli", "--url", f"http://127.0.0.1:{server.server_port}", "mcp"], env=clean)
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = {tool.name: tool for tool in (await session.list_tools()).tools}
            assert {"iphone_observe", "iphone_tap", "iphone_compose_chinese",
                    "task_status", "stop_task"} <= tools.keys()
            assert "delegate_task" not in tools
            assert "screen_id" in tools["iphone_tap"].inputSchema["required"]
            shot = await session.call_tool("iphone_screenshot", {})
            assert not shot.isError
            assert json.loads(shot.content[0].text)["screen_id"] == "one-use"
            assert shot.content[1].type == "image" and shot.content[1].mimeType == "image/jpeg"
            missing_token = await session.call_tool("iphone_tap", {"x": .5, "y": .4})
            assert missing_token.isError and not requests
            result = await session.call_tool("iphone_tap", {"x": .5, "y": .4, "screen_id": "one-use"})
            assert not result.isError and result.content[1].type == "image"
            assert json.loads(result.content[0].text)["effect_verified"] is False
            edited = await session.call_tool("iphone_key", {
                "combo": "backspace", "screen_id": "after-observation", "repeat": 3})
            assert not edited.isError and edited.content[1].type == "image"
            assert not (await session.call_tool("stop_task", {})).isError
            guidance = await session.call_tool("iphone_model_help", {})
            assert not guidance.isError and "No model calls" in tools["iphone_model_help"].description

    try:
        asyncio.run(asyncio.wait_for(scenario(), 25))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert requests == [("/api/control/action", {"action": "tap", "screen_id": "one-use", "x": .5, "y": .4,
                                               "coordinate_space": "normalized"}),
                        ("/api/control/action", {"action": "key", "screen_id": "after-observation",
                                                "text": "backspace", "repeat": 3}),
                        ("/api/agent/stop", None)]


def test_delegate_tool_requires_explicit_opt_in(monkeypatch):
    from hidagent.mcp import create_server
    monkeypatch.setenv("IPHONE_MCP_ENABLE_DELEGATE", "1")
    tools = asyncio.run(create_server().list_tools())
    assert "delegate_task" in {tool.name for tool in tools}
