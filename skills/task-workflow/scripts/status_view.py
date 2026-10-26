"""Read-only, bounded public projections for the Workflow chat content tab.

An explicit model-provided project/task context creates an opaque view reference.
The app receives bounded projections and never supplies filesystem paths.
"""
import datetime as dt
from pathlib import Path
import re
import secrets
import time

import workflow

TOOL_NAME = "workflow.status_view"
RESOURCE_URI = "ui://task-workflow/status"
MIME_TYPE = "text/html;profile=mcp-app"
REFRESH_TOOL = "workflow.refresh_view"
MAX_VIEWS = 128
VIEW_LIFETIME = 3600
MAX_ROWS = 100
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)$")
ITEM_STATES = {"pending", "implementing", "reviewing", "complete"}
RUN_STATES = {"planned", "preparing", "prepared", "queued", "running", "awaiting_artifacts", "complete", "failed", "cancelled", "unknown"}



def tool_schema():
    return {"name": TOOL_NAME, "title": "Workflow", "description": "Open the current enrolled project's task in this chat's Workflow tab. The agent supplies known root/task context. A direct empty entrypoint stays unbound.",
            "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}, "task_id": {"type": "string"}, "session_id": {"type": "string"}}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
            "_meta": {"ui": {"resourceUri": RESOURCE_URI, "visibility": ["model"]},
                      "openai/ui": {"entrypoints": [{"type": "thread"}]}}}


def refresh_schema():
    return {"name": REFRESH_TOOL, "title": "Refresh Workflow", "description": "Read the same enrolled task using an opaque view reference. Reads recorded state only.",
            "inputSchema": {"type": "object", "properties": {"view_ref": {"type": "string"}}, "required": ["view_ref"], "additionalProperties": False},
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
            "_meta": {"ui": {"visibility": ["app"]}}}


def resource():
    return {"uri": RESOURCE_URI, "name": "Workflow", "description": "Read recorded task, experiment and run status.", "mimeType": MIME_TYPE,
            "_meta": {"ui": {"csp": {"connectDomains": [], "resourceDomains": [], "frameDomains": []}, "prefersBorder": False}}}


def read_resource():
    return {**resource(), "text": (Path(__file__).resolve().parents[1] / "assets" / "workflow.html").read_text(encoding="utf-8")}


def identifier(value, fallback="unknown"):
    return value if isinstance(value, str) and IDENTIFIER.fullmatch(value) else fallback


def label(value, fallback="Untitled task"):
    """Drop path-bearing tokens before displaying bounded human labels."""
    if not isinstance(value, str):
        return fallback
    words = value.split()
    # Titles can include source paths. Omit their complete token, including a
    # preceding drive letter or URL, instead of exposing a partial private path.
    cleaned = " ".join("[private reference]" if any(c in word for c in ("/", "\\", "~")) else word for word in words)
    cleaned = "".join(c for c in cleaned if c.isprintable())[:160]
    return cleaned or fallback


def enum(value, allowed):
    return value if isinstance(value, str) and value in allowed else "unknown"


def timestamp(value):
    return value if isinstance(value, str) and TIMESTAMP.fullmatch(value) else None


def integer(value):
    return value if type(value) is int and 0 <= value <= 10**9 else None


def mapping(value):
    return value if isinstance(value, dict) else {}


def closure(value):
    scope = mapping(value)
    record = mapping(scope.get("closure"))
    return {"status": enum(scope.get("status"), {"open", "complete"}),
            "outcome": enum(record.get("outcome"), {"completed", "stopped", "abandoned"}),
            "time": timestamp(record.get("time"))}


def stage(state):
    """Describe development progress separately from aggregate closure."""
    items = mapping(state.get("items"))
    statuses = [mapping(v).get("status") for v in items.values()]
    integration = mapping(state.get("integration")).get("status")
    if integration == "complete":
        return "integrated"
    if integration:
        return "integration"
    if statuses and all(v == "complete" for v in statuses):
        return "verification complete"
    if "reviewing" in statuses:
        return "review"
    if "implementing" in statuses:
        return "implementation"
    approval, design = mapping(state.get("approval")), mapping(state.get("design"))
    if approval.get("digest") and approval.get("digest") == design.get("digest"):
        return "approved"
    return "design recorded" if design else "enrolled"


def project_task(state, source_resources=None):
    items, experiments, runs = (mapping(state.get(key)) for key in ("items", "experiments", "runs"))
    rows = lambda values: list(values.items())[:MAX_ROWS]
    projected_runs = []
    for run_id, raw in rows(runs):
        run = mapping(raw)
        projected_runs.append({"run_id": identifier(run_id), "status": enum(run.get("status"), RUN_STATES),
                               "experiment_id": identifier(run.get("experiment_id"), None),
                               "resource_id": identifier(run.get("resource_id"), None),
                               "created": timestamp(run.get("created"))})
    resources = source_resources if isinstance(source_resources, list) else []
    projected_resources = []
    for raw in resources[:MAX_ROWS]:
        record = mapping(raw)
        references = []
        for reference in record.get("run_refs", [])[:MAX_ROWS] if isinstance(record.get("run_refs"), list) else []:
            reference = mapping(reference)
            references.append({"task_id": identifier(reference.get("task_id")), "run_id": identifier(reference.get("run_id")), "status": enum(reference.get("status"), RUN_STATES)})
        resource_state = enum(record.get("derived_state"), {"available", "in_use", "releasable", "released"})
        projected_resources.append({"resource_id": identifier(record.get("resource_id")),
                                    "state": resource_state,
                                    "provided_by": enum(record.get("provided_by"), {"user", "agent"}),
                                    "can_release": record.get("can_release") if type(record.get("can_release")) is bool else None,
                                    "run_refs": references, "version": integer(record.get("version")),
                                    "observed_at": timestamp(record.get("observed_at"))})
    return {"key": identifier(state.get("task_id")),
            "task_id": identifier(state.get("task_id")), "title": label(state.get("title")),
            "version": integer(state.get("version")), "created": timestamp(state.get("created")),
            "updated": timestamp(state.get("updated")), "stage": stage(state),
            "closure": closure(state.get("task_lifecycle")),
            "items": [{"item_id": identifier(key), "title": label(mapping(raw).get("title"), "Untitled item"),
                       "status": enum(mapping(raw).get("status"), ITEM_STATES), "overall": mapping(raw).get("overall") is True} for key, raw in rows(items)],
            "experiments": [{"experiment_id": identifier(key), "closure": closure(raw),
                             "created": timestamp(mapping(raw).get("created"))} for key, raw in rows(experiments)],
            "runs": projected_runs, "resources": projected_resources,
            "truncated": any(len(values) > MAX_ROWS for values in (items, experiments, runs, resources))}


def unbound(reason="context_required"):
    notices = {"context_required": "This tab has no verified project/task context. The agent opens Workflow with the current enrolled task from its skill or hook context.",
               "unavailable": "The bound task is unavailable. The agent can reopen Workflow with its current enrolled task context.",
               "expired": "This view reference expired. The agent can reopen Workflow for the current enrolled task.",
               "context_mismatch": "The supplied session context does not match the enrolled task."}
    return {"schema_version": 1, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "status": "unbound", "reason": reason,
            "view_ref": None, "tasks": [], "notice": notices[reason]}


class ViewStore:
    """Per-server opaque references; no files, configuration, or global fallback."""
    def __init__(self, core=None, clock=None):
        self.core = core or workflow
        self.clock = clock or time.monotonic
        self.views = {}

    def prune(self):
        now = self.clock()
        self.views = {key: value for key, value in self.views.items() if value["expires"] > now}

    def read(self, binding, reference):
        try:
            response = self.core.dispatch("status", {"root": binding["root"], "task_id": binding["task_id"]})
            state = response.get("state")
            if response.get("ok") is not True or not isinstance(state, dict) or state.get("task_id") != binding["task_id"]:
                return unbound("unavailable")
            if binding.get("session_id") and state.get("session_id") and binding["session_id"] != state["session_id"]:
                return unbound("context_mismatch")
            return {"schema_version": 1, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "status": "bound", "view_ref": reference,
                    "tasks": [project_task(state, response.get("resources"))], "notice": "Current enrolled task. Recorded states only; refresh reads the latest stored records."}
        except Exception:
            return unbound("unavailable")

    def open(self, arguments):
        # No public host contract identifies the current chat for an empty tool
        # call. Require the known enrolled context supplied by the agent.
        if not arguments.get("root") or not arguments.get("task_id"):
            return unbound()
        root, task_id = arguments["root"], identifier(arguments["task_id"], None)
        if not isinstance(root, str) or not Path(root).expanduser().is_absolute() or task_id is None:
            return unbound("unavailable")
        self.prune()
        if len(self.views) >= MAX_VIEWS:
            self.views.pop(next(iter(self.views)))
        reference = secrets.token_urlsafe(32)
        binding = {"root": root, "task_id": task_id, "session_id": arguments.get("session_id"), "expires": self.clock() + VIEW_LIFETIME}
        result = self.read(binding, reference)
        if result["status"] == "bound":
            self.views[reference] = binding
        return result

    def refresh(self, reference):
        self.prune()
        binding = self.views.get(reference)
        if not binding:
            return unbound("expired")
        result = self.read(binding, reference)
        if result["status"] == "bound":
            binding["expires"] = self.clock() + VIEW_LIFETIME
        return result
