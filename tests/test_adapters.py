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
        for key, value in self.core.command_schemas()[0].items():
            self.assertEqual(tools[0][key], value)
        self.assertEqual(tools[0]["_meta"]["ui"]["visibility"], ["model"])
        self.assertEqual(tools[0]["_meta"]["ui"]["resourceUri"], self.module.status_view.RESOURCE_URI)
        self.assertTrue(tools[0]["annotations"]["readOnlyHint"])
        self.assertIn("tasks", tools[0]["outputSchema"]["properties"])
        self.request("tools/call", {"name": "status", "arguments": {"root": "/example"}})
        self.core.dispatch.assert_called_once_with("status", {"root": "/example"})

    def test_lifecycle_calls_return_native_view_data_without_an_extra_view_tool(self):
        properties = {key: {"type": "string"} for key in ("root", "task_id", "session_id")}
        self.core.command_schemas = lambda: [{"name": name, "description": name, "inputSchema": {
            "type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}}
            for name in ("init", "status", "bind-session", "recover")]
        state = {"root": "/example", "task_id": "task-a", "session_id": "session-a", "items": {}}
        self.core.dispatch.return_value = {"ok": True, "state": state, "session_bindings": {"session-a": "task-a"}}
        self.server = self.module.Server()
        self.request("initialize")
        schemas = {tool["name"]: tool for tool in self.request("tools/list")["result"]["tools"]}
        for name in ("init", "status", "bind-session", "recover"):
            self.assertEqual(schemas[name]["_meta"]["ui"], {"resourceUri": self.module.status_view.RESOURCE_URI, "visibility": ["model"]})
            self.assertNotIn("openai/ui", schemas[name]["_meta"])
            self.assertEqual(schemas[name]["annotations"]["readOnlyHint"], name == "status")
            result = self.request("tools/call", {"name": name, "arguments": {"root": "/example", "task_id": "task-a", "session_id": "session-a"}})["result"]
            self.assertFalse(result["isError"])
            self.assertTrue(json.loads(result["content"][0]["text"])["ok"])
            self.assertEqual(result["structuredContent"]["status"], "bound")
            self.assertEqual(result["structuredContent"]["tasks"][0]["task_id"], "task-a")
            self.assertEqual(result["_meta"]["ui"]["resourceUri"], schemas[name]["_meta"]["ui"]["resourceUri"])
            self.assertNotIn("/example", json.dumps(result["structuredContent"]))
        self.assertTrue(all(call.args[0] != self.module.status_view.TOOL_NAME for call in self.core.dispatch.call_args_list))
        self.core.dispatch.reset_mock()
        with mock.patch.object(self.server.views, "open", side_effect=RuntimeError("PRIVATE PROJECTION")):
            enrolled = self.request("tools/call", {"name": "init", "arguments": {"root": "/example", "task_id": "task-a", "session_id": "session-a"}})["result"]
        self.assertFalse(enrolled["isError"])
        self.assertTrue(json.loads(enrolled["content"][0]["text"])["ok"])
        self.assertEqual(enrolled["structuredContent"]["reason"], "unavailable")
        self.core.dispatch.assert_called_once()

    def test_view_failure_preserves_core_success_and_reconnect_requires_explicit_context(self):
        self.core.command_schemas = lambda: [{"name": "status", "inputSchema": {"type": "object", "properties": {
            "root": {"type": "string"}, "task_id": {"type": "string"}}, "required": ["root", "task_id"], "additionalProperties": False}}]
        state = {"root": "/example", "task_id": "task-a", "items": {}}
        self.core.dispatch.return_value = {"ok": True, "state": state}
        self.server = self.module.Server(); self.request("initialize")
        params = {"name": "status", "arguments": {"root": "/example", "task_id": "task-a"}}
        initial = self.request("tools/call", params)["result"]["structuredContent"]
        old_ref = initial["view_ref"]
        self.server = self.module.Server(); self.request("initialize")
        orphan = self.request("tools/call", {"name": self.module.status_view.REFRESH_TOOL, "arguments": {"view_ref": old_ref}})["result"]["structuredContent"]
        self.assertEqual(orphan["status"], "unbound")
        restored = self.request("tools/call", params)["result"]["structuredContent"]
        self.assertEqual(restored["tasks"], initial["tasks"])
        self.assertNotEqual(restored["view_ref"], old_ref)
        self.core.dispatch.side_effect = [{"ok": True, "state": state}, RuntimeError("PRIVATE")]
        result = self.request("tools/call", params)["result"]
        self.assertFalse(result["isError"])
        self.assertTrue(json.loads(result["content"][0]["text"])["ok"])
        self.assertEqual(result["structuredContent"]["reason"], "unavailable")
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.core.dispatch.side_effect = None
        self.core.dispatch.return_value = {"ok": True, "state": state}
        with mock.patch.object(self.server.views, "open", side_effect=RuntimeError("PRIVATE PROJECTION")):
            result = self.request("tools/call", params)["result"]
        self.assertFalse(result["isError"])
        self.assertTrue(json.loads(result["content"][0]["text"])["ok"])
        self.assertEqual(result["structuredContent"]["reason"], "unavailable")

    def test_optional_host_correlation_restores_only_its_verified_thread_context(self):
        self.core.command_schemas = lambda: [{"name": "status", "inputSchema": {"type": "object", "properties": {
            "root": {"type": "string"}, "task_id": {"type": "string"}}, "required": ["root", "task_id"], "additionalProperties": False}}]
        def dispatch(name, arguments):
            if arguments.get('task_id') == 'failed':
                return {'ok': False, 'error': {'code': 'not_found', 'message': 'Task unavailable'}}
            return {'ok': True, 'state': {'root': arguments['root'], 'task_id': arguments['task_id'], 'items': {}}}
        self.core.dispatch.side_effect = dispatch
        self.server = self.module.Server(); self.request('initialize')
        def call(name, arguments=None, host=None, metadata=None):
            params = {'name': name, 'arguments': arguments or {}}
            if metadata is not None:
                params['_meta'] = metadata
            elif host is not None:
                params['_meta'] = {'openai/session': host}
            return self.request('tools/call', params)['result']
        status = self.module.status_view.TOOL_NAME
        refresh = self.module.status_view.REFRESH_TOOL
        context_a = {'root': '/example', 'task_id': 'task-a'}
        context_b = {'root': '/example', 'task_id': 'task-b'}
        opened = call('status', context_a, 'host-a')['structuredContent']
        self.assertEqual(opened['status'], 'bound')
        self.assertEqual(call(status, host='host-a')['structuredContent']['tasks'][0]['task_id'], 'task-a')
        self.assertEqual(call(status, host='host-b')['structuredContent']['status'], 'unbound')
        call('status', context_b, 'host-b')
        self.assertEqual(call(status, host='host-b')['structuredContent']['tasks'][0]['task_id'], 'task-b')
        self.assertEqual(call(status, host='host-a')['structuredContent']['tasks'][0]['task_id'], 'task-a')
        self.assertEqual(call(status)['structuredContent']['status'], 'unbound')
        for metadata in ({'session_id': 'host-a'}, {'thread_id': 'host-a'}, {'openai/session': 1}, {'openai/session': 'host-a\n'}):
            self.assertEqual(call(status, metadata=metadata)['structuredContent']['status'], 'unbound')
        self.assertTrue(call('status', dict(context_a, task_id='failed'), 'host-a')['isError'])
        self.assertEqual(call(status, host='host-a')['structuredContent']['tasks'][0]['task_id'], 'task-a')
        self.assertEqual(call(refresh, {'view_ref': opened['view_ref']}, 'host-b')['structuredContent']['reason'], 'context_mismatch')
        call('status', context_b, 'host-a')
        self.assertEqual(call(status, host='host-a')['structuredContent']['tasks'][0]['task_id'], 'task-b')
        self.assertEqual(call(refresh, {'view_ref': opened['view_ref']}, 'host-a')['structuredContent']['reason'], 'context_mismatch')
        self.server = self.module.Server(); self.request('initialize')
        self.assertEqual(call(status, host='host-a')['structuredContent']['status'], 'unbound')
        restored = call('status', context_b, 'host-a')['structuredContent']
        self.assertEqual(restored['tasks'][0]['task_id'], 'task-b')
        self.assertEqual(call(status, host='host-a')['structuredContent']['tasks'], restored['tasks'])
        for private in ('host-a', 'host-b', '/example'):
            self.assertNotIn(private, json.dumps(restored))

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

    def test_real_wire_accepts_message_larger_than_one_mib(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            for name in ("mcp_server.py", "status_view.py"):
                (folder / name).write_bytes((SCRIPTS / name).read_bytes())
            (folder / "workflow.py").write_text("def command_schemas(): return []\nclass WorkflowError(Exception): pass\n")
            request = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"payload": "x" * (1024 * 1024 + 1)}}
            process = subprocess.run([sys.executable, str(folder / "mcp_server.py")], input=json.dumps(request) + "\n", text=True, capture_output=True, timeout=10)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout), {"jsonrpc": "2.0", "id": 1, "result": {}})


if __name__ == "__main__":
    unittest.main()
