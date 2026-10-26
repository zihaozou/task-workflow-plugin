"""JSON-RPC transport validates requests and delegates the current core manifest."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/task-workflow/scripts"
sys.path.insert(0, str(SCRIPTS))


def fake_workflow():
    module = types.ModuleType("workflow")
    class WorkflowError(Exception):
        def __init__(self, code, message):
            self.code, self.message = code, message
    module.WorkflowError = WorkflowError
    module.command_schemas = lambda: [{"name": "status", "description": "Read status", "inputSchema": {
        "type": "object", "properties": {"root": {"type": "string"}}, "required": ["root"], "additionalProperties": False}}]
    module.dispatch = mock.Mock(return_value={"ok": True, "tasks": []})
    return module


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.core = fake_workflow()
        spec = importlib.util.spec_from_file_location("transport_test_mcp_server", SCRIPTS / "mcp_server.py")
        self.module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {"workflow": self.core}):
            spec.loader.exec_module(self.module)
        self.server = self.module.Server()

    def request(self, method, params=None, request_id=1):
        return self.server.handle({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})

    def test_protocol_versions_and_manifest_schema_preservation(self):
        for version in self.module.VERSIONS:
            self.assertEqual(self.request("initialize", {"protocolVersion": version})["result"]["protocolVersion"], version)
        self.assertEqual(self.request("initialize", {"protocolVersion": "future"})["result"]["protocolVersion"], self.module.VERSIONS[-1])
        tools = self.request("tools/list")["result"]["tools"]
        self.assertEqual({key: value for key, value in tools[0].items() if key != "_meta"}, self.core.command_schemas()[0])
        self.assertEqual(tools[0]["_meta"]["ui"]["visibility"], ["model"])
        self.request("tools/call", {"name": "status", "arguments": {"root": "/example"}})
        self.core.dispatch.assert_called_once_with("status", {"root": "/example"})

    def test_mutations_keep_their_core_schema_and_dispatch(self):
        mutation = {"name": "example-mutation", "description": "Core mutation", "inputSchema": {"type": "object", "properties": {"expected_version": {"type": "integer"}, "evidence": {"type": "array", "items": {"type": "string"}}}, "required": ["expected_version", "evidence"], "additionalProperties": False}}
        self.core.command_schemas = lambda: [mutation]
        self.server = self.module.Server(); self.request("initialize")
        arguments = {"expected_version": 3, "evidence": ["record"]}
        self.request("tools/call", {"name": "example-mutation", "arguments": arguments})
        self.core.dispatch.assert_called_once_with("example-mutation", arguments)
        self.core.dispatch.reset_mock()
        for invalid in (dict(arguments, expected_version=True), dict(arguments, evidence=[False])):
            self.assertEqual(self.request("tools/call", {"name": "example-mutation", "arguments": invalid})["error"]["code"], -32602)
        self.core.dispatch.assert_not_called()

    def test_bad_calls_and_notifications_never_dispatch(self):
        self.assertEqual(self.request("tools/list")["error"]["code"], -32002)
        self.request("initialize")
        for params in ({"name": "unknown"}, {"name": "status", "arguments": {}}, {"name": "status", "arguments": {"root": True}}, {"name": "status", "arguments": {"root": "/example", "extra": 1}}, {"name": "status", "arguments": []}):
            self.assertEqual(self.request("tools/call", params)["error"]["code"], -32602)
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "status", "arguments": {"root": "/example"}}}))
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.core.dispatch.assert_not_called()

    def test_core_errors_remain_structured_and_unexpected_errors_are_private(self):
        self.request("initialize")
        self.core.dispatch.side_effect = self.core.WorkflowError("stale_version", "Version mismatch")
        result = self.request("tools/call", {"name": "status", "arguments": {"root": "/example"}})["result"]
        self.assertTrue(result["isError"])
        self.assertEqual(json.loads(result["content"][0]["text"])["error"]["code"], "stale_version")
        self.core.dispatch.side_effect = RuntimeError("PRIVATE PATH")
        self.assertNotIn("PRIVATE", json.dumps(self.request("tools/call", {"name": "status", "arguments": {"root": "/example"}})))

    def test_real_wire_parse_errors_and_ping(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            for name in ("mcp_server.py", "status_view.py"):
                (folder / name).write_bytes((SCRIPTS / name).read_bytes())
            (folder / "workflow.py").write_text("def command_schemas(): return []\nclass WorkflowError(Exception): pass\ndef dispatch(*args): raise AssertionError('must not execute')\n")
            requests = 'not-json\n{"jsonrpc":"2.0","id":1,"id":2,"method":"ping"}\n' + json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping"}) + '\n'
            process = subprocess.run([sys.executable, str(folder / "mcp_server.py")], input=requests, text=True, capture_output=True, timeout=5)
            self.assertEqual(process.returncode, 0, process.stderr)
            replies = [json.loads(line) for line in process.stdout.splitlines()]
            self.assertEqual([reply.get("error", {}).get("code") for reply in replies[:2]], [-32700, -32700])
            self.assertEqual(replies[2], {"jsonrpc": "2.0", "id": 3, "result": {}})


if __name__ == "__main__":
    unittest.main()
