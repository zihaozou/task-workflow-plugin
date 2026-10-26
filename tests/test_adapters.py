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
        self.assertEqual(tools, [{**self.core.command_schemas()[0], "annotations": {
            "readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}}])
        self.request("tools/call", {"name": "status", "arguments": {"root": "/example"}})
        self.core.dispatch.assert_called_once_with("status", {"root": "/example"})

    def test_lifecycle_results_preserve_complete_core_output_and_dispatch_once(self):
        properties = {key: {"type": "string"} for key in ("root", "task_id", "session_id")}
        self.core.command_schemas = lambda: [{"name": name, "description": name, "inputSchema": {
            "type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}}
            for name in ("init", "status", "context", "bind-session", "recover")]
        arguments = {"root": "/example", "task_id": "task-a", "session_id": "session-a"}
        state = {**arguments, "items": {}, "version": 4}
        self.server = self.module.Server()
        self.request("initialize")
        tools = self.request("tools/list")["result"]["tools"]
        for tool, core_schema in zip(tools, self.core.command_schemas()):
            self.assertEqual(tool, {**core_schema, "annotations": {"readOnlyHint": tool["name"] in ("status", "context"),
                                   "destructiveHint": False, "openWorldHint": False}})
        for name in ("init", "status", "context", "bind-session", "recover"):
            for output in ({"ok": True, "state": state, "session_bindings": {"session-a": "task-a"}},
                           {"ok": False, "error": {"code": "session_conflict", "message": "Session differs"}}):
                with self.subTest(name=name, ok=output["ok"]):
                    self.core.dispatch.reset_mock()
                    self.core.dispatch.return_value = output
                    result = self.request("tools/call", {"name": name, "arguments": arguments,
                                                         "_meta": {"openai/session": "host-a"}})["result"]
                    self.assertEqual(result, {"content": [{"type": "text", "text": json.dumps(output)}],
                                              "isError": not output["ok"]})
                    self.core.dispatch.assert_called_once_with(name, arguments)

    def test_removed_view_surface_is_not_advertised_or_callable(self):
        capabilities = self.request("initialize")["result"]["capabilities"]
        self.assertEqual(capabilities, {"tools": {"listChanged": False}})
        tools = self.request("tools/list")["result"]["tools"]
        self.assertEqual([tool["name"] for tool in tools], ["status"])
        self.assertTrue(all("_meta" not in tool and "outputSchema" not in tool for tool in tools))
        for name in ("workflow.status_view", "workflow.refresh_view"):
            self.assertEqual(self.request("tools/call", {"name": name})["error"]["code"], -32602)
        for method in ("resources/list", "resources/templates/list", "resources/read"):
            self.assertEqual(self.request(method, {"uri": "ui://workflow/status.html"})["error"]["code"], -32601)
        self.core.dispatch.assert_not_called()

    def test_lifecycle_annotations_preserve_explicit_core_semantics(self):
        schema = self.core.command_schemas()[0]
        schema["annotations"] = {"readOnlyHint": False, "destructiveHint": True,
                                 "openWorldHint": True, "title": "Core status"}
        self.core.command_schemas = lambda: [schema]
        self.server = self.module.Server()
        self.request("initialize")
        self.assertEqual(self.request("tools/list")["result"]["tools"], [schema])

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
            (folder / "mcp_server.py").write_bytes((SCRIPTS / "mcp_server.py").read_bytes())
            (folder / "workflow.py").write_text("def command_schemas(): return []\nclass WorkflowError(Exception): pass\ndef dispatch(*args): raise AssertionError('must not execute')\n")
            requests = 'not-json\n{"jsonrpc":"2.0","id":1,"id":2,"method":"ping"}\n' + json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping"}) + '\n'
            process = subprocess.run([sys.executable, str(folder / "mcp_server.py")], input=requests, text=True, capture_output=True, timeout=5)
            self.assertEqual(process.returncode, 0, process.stderr)
            replies = [json.loads(line) for line in process.stdout.splitlines()]
            self.assertEqual([reply.get("error", {}).get("code") for reply in replies[:2]], [-32700, -32700])
            self.assertEqual(replies[2], {"jsonrpc": "2.0", "id": 3, "result": {}})

    def test_real_wire_accepts_message_larger_than_one_mib(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "mcp_server.py").write_bytes((SCRIPTS / "mcp_server.py").read_bytes())
            (folder / "workflow.py").write_text("def command_schemas(): return []\nclass WorkflowError(Exception): pass\n")
            request = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"payload": "x" * (1024 * 1024 + 1)}}
            process = subprocess.run([sys.executable, str(folder / "mcp_server.py")], input=json.dumps(request) + "\n", text=True, capture_output=True, timeout=10)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout), {"jsonrpc": "2.0", "id": 1, "result": {}})


class WireSurfaceTests(unittest.TestCase):
    def test_shipped_server_exposes_only_core_tools_without_ui_resources(self):
        calls = [("initialize", {}), ("tools/list", {})]
        calls += [("tools/call", {"name": name})
                  for name in ("workflow.status_view", "workflow.refresh_view")]
        calls += [(method, {"uri": "ui://workflow/status.html"})
                  for method in ("resources/list", "resources/templates/list", "resources/read")]
        wire = "".join(json.dumps({"jsonrpc": "2.0", "id": index, "method": method, "params": params}) + "\n"
                       for index, (method, params) in enumerate(calls, 1))
        process = subprocess.run([sys.executable, str(SCRIPTS / "mcp_server.py")], input=wire,
                                 text=True, capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        replies = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual(len(replies), len(calls))
        self.assertEqual(replies[0]["result"]["capabilities"], {"tools": {"listChanged": False}})
        tools = replies[1]["result"]["tools"]
        self.assertTrue({"init", "status", "context", "bind-session", "recover", "run-execute"}.issubset({tool["name"] for tool in tools}))
        self.assertTrue(all("_meta" not in tool and "outputSchema" not in tool for tool in tools))
        for tool in tools:
            if tool["name"] in ("init", "status", "context", "bind-session", "recover"):
                self.assertEqual(tool["annotations"], {"readOnlyHint": tool["name"] in ("status", "context"),
                                                      "destructiveHint": False, "openWorldHint": False})
            else:
                self.assertNotIn("annotations", tool)
        self.assertEqual([reply["error"]["code"] for reply in replies[2:]], [-32602, -32602, -32601, -32601, -32601])


if __name__ == "__main__":
    unittest.main()
