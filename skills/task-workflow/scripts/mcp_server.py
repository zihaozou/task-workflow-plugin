#!/usr/bin/env python3
"""Dependency-free JSON-RPC transport for the core's current operation manifest.

The adapter owns no task, experiment, run, or allocation lifecycle state.
"""
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True

import workflow

VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")


def validate(value, schema, location="arguments"):
    """Validate the small JSON Schema vocabulary emitted by workflow."""
    kind = schema.get("type")
    types = {"object": dict, "array": list, "string": str,
             "integer": int, "number": (int, float), "boolean": bool,
             "null": type(None)}
    if kind and (kind not in types or not isinstance(value, types[kind])
                 or (kind in ("integer", "number") and isinstance(value, bool))):
        raise ValueError(location + " has the wrong type")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(location + " is not finite")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(location + " is not an allowed value")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        if any(key not in value for key in schema.get("required", [])):
            raise ValueError(location + " is missing required fields")
        if schema.get("additionalProperties") is False and any(key not in properties for key in value):
            raise ValueError(location + " contains unsupported fields")
        for key, item in value.items():
            if key in properties:
                validate(item, properties[key], location + "." + key)
    if isinstance(value, list) and "items" in schema:
        for item in value:
            validate(item, schema["items"], location + "[]")
    for bound, test in (("minimum", lambda x, y: x < y), ("maximum", lambda x, y: x > y)):
        if bound in schema and isinstance(value, (int, float)) and test(value, schema[bound]):
            raise ValueError(location + " is outside its allowed range")


def parse_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid JSON number")))


def package_version():
    """Read the release identity from this installed package."""
    manifest = Path(__file__).resolve().parents[3] / "package.json"
    version = json.loads(manifest.read_text(encoding="utf-8"))["version"]
    if not isinstance(version, str) or not version.strip():
        raise ValueError("The installed package must declare a nonempty version.")
    return version


class Server:
    def __init__(self):
        self.initialized = False
        self.version = package_version()
        self.tools = []
        for tool in workflow.command_schemas():
            if tool["name"] in ("init", "status", "context", "bind-session", "recover"):
                tool = {**tool, "annotations": {"readOnlyHint": tool["name"] in ("status", "context"),
                        "destructiveHint": False, "openWorldHint": False, **tool.get("annotations", {})}}
            self.tools.append(tool)
        self.by_name = {tool["name"]: tool for tool in self.tools}

    @staticmethod
    def error(request_id, code, message, data=None):
        error = {"code": code, "message": message}
        if data is not None:
            error['data'] = data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}

    def handle(self, request):
        if not isinstance(request, dict):
            return self.error(None, -32600, "Invalid Request")
        request_id = request.get("id")
        if (request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str)
                or ("id" in request and (isinstance(request_id, bool) or not isinstance(request_id, (str, int, type(None)))))):
            return self.error(None, -32600, "Invalid Request")
        notification = "id" not in request
        method = request["method"]
        params = request.get("params", {})
        if not isinstance(params, dict):
            return None if notification else self.error(request_id, -32602, "Parameters must be an object")
        # Notifications cannot execute workflow mutations.
        if notification:
            return None
        if method == "initialize":
            requested = params.get("protocolVersion")
            selected = requested if requested in VERSIONS else VERSIONS[-1]
            self.initialized = True
            result = {"protocolVersion": selected, "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": "task-workflow", "version": self.version}}
        elif method == "ping":
            result = {}
        elif not self.initialized:
            return self.error(request_id, -32002, "Server is not initialized")
        elif method == "tools/list":
            result = {"tools": self.tools}
        elif method == "tools/call":
            name = params.get("name")
            if not isinstance(name, str) or name not in self.by_name:
                return self.error(request_id, -32602, "Unknown tool")
            arguments = params.get("arguments", {})
            try:
                validate(arguments, self.by_name[name]["inputSchema"])
            except ValueError as exc:
                return self.error(request_id, -32602, str(exc), workflow.schema_diagnostic(arguments, self.by_name[name]["inputSchema"]))
            try:
                output = workflow.dispatch(name, arguments)
                failed = output.get("ok") is False
            except workflow.WorkflowError as exc:
                output = {"ok": False, "error": workflow.error_payload(exc)}
                failed = True
            except Exception:
                return self.error(request_id, -32603, "Internal workflow error")
            result = {"content": [{"type": "text", "text": json.dumps(output, ensure_ascii=False)}], "isError": failed}
        else:
            return self.error(request_id, -32601, "Method not found")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main():
    server = Server()
    stream = sys.stdin.buffer
    while True:
        line = stream.readline()
        if not line:
            break
        try:
            response = server.handle(parse_json(line.decode("utf-8")))
        except (ValueError, UnicodeError):
            response = server.error(None, -32700, "Parse error")
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
