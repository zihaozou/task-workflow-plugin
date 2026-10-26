"""Read-only public projections for the Workflow chat content tab.

An explicit model-provided project/task context creates an opaque view reference.
Structured data and rendered fields use selected public facts. Lifecycle tools
also retain their full core text result, which the host can forward to the app.
The app refresh bridge supplies only an opaque reference, never filesystem paths.
"""
import datetime as dt
from pathlib import Path
import re
import secrets

import workflow

TOOL_NAME = "workflow.status_view"
RESOURCE_URI = "ui://task-workflow/status"
MIME_TYPE = "text/html;profile=mcp-app"
REFRESH_TOOL = "workflow.refresh_view"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$")
ITEM_STATES = {"pending", "implementing", "reviewing", "complete"}
RUN_STATES = {"planned", "preparing", "prepared", "queued", "running", "awaiting_artifacts", "complete", "failed", "cancelled", "unknown"}
PROCESS_STAGES = {"exploration", "discussion", "design", "design_review", "design_confirmation", "plan", "plan_confirmation", "implementation", "delivery"}
LIFECYCLE_TOOLS = {"init", "status", "bind-session", "recover"}


def output_schema():
    """Describe the public view envelope, separate from the core's text result."""
    nullable_text = {"type": ["string", "null"]}
    nullable_number = {"type": ["integer", "null"]}
    lifecycle = {"type": "object", "properties": {"status": {"type": "string"}, "outcome": {"type": "string"}, "time": nullable_text},
                 "required": ["status", "outcome", "time"], "additionalProperties": False}
    def rows(properties):
        return {"type": "array", "items": {"type": "object", "properties": properties,
                                             "required": list(properties), "additionalProperties": False}}
    task = {"key": {"type": "string"}, "task_id": {"type": "string"}, "title": {"type": "string"},
            "version": nullable_number, "created": nullable_text, "updated": nullable_text, "stage": {"type": "string"},
            "process_protocol": nullable_number, "phase_detail": {"type": "string"}, "closure": lifecycle,
            "items": rows({"item_id": {"type": "string"}, "title": {"type": "string"}, "status": {"type": "string"}, "overall": {"type": "boolean"}}),
            "experiments": rows({"experiment_id": {"type": "string"}, "closure": lifecycle, "created": nullable_text}),
            "runs": rows({"run_id": {"type": "string"}, "status": {"type": "string"}, "experiment_id": nullable_text,
                          "resource_id": nullable_text, "created": nullable_text}),
            "resources": rows({"resource_id": {"type": "string"}, "state": {"type": "string"}, "provided_by": {"type": "string"},
                               "can_release": {"type": ["boolean", "null"]}, "version": nullable_number, "observed_at": nullable_text,
                               "run_refs": rows({"task_id": {"type": "string"}, "run_id": {"type": "string"}, "status": {"type": "string"}})}),
            "truncated": {"type": "boolean"}}
    properties = {"schema_version": {"type": "integer", "enum": [1]}, "generated_at": {"type": "string"},
                  "status": {"type": "string", "enum": ["bound", "unbound"]}, "reason": {"type": "string"},
                  "view_ref": nullable_text, "tasks": rows(task), "notice": {"type": "string"}}
    return {"type": "object", "properties": properties,
            "required": [key for key in properties if key != "reason"], "additionalProperties": False}


def lifecycle_schema(tool):
    """Keep core arguments and semantics while associating its result with UI."""
    annotations = {"readOnlyHint": tool["name"] == "status", "destructiveHint": False, "openWorldHint": False,
                   **tool.get("annotations", {})}
    return {**tool, "annotations": annotations, "outputSchema": output_schema(),
            "_meta": {**tool.get("_meta", {}), "ui": {"resourceUri": RESOURCE_URI, "visibility": ["model"]}}}



def tool_schema():
    return {"name": TOOL_NAME, "title": "Workflow", "description": "Open the enrolled task using explicit project/task context. An empty thread entrypoint can reuse a context previously verified for the same optional host conversation metadata; otherwise it stays unbound.",
            "inputSchema": {"type": "object", "properties": {"root": {"type": "string"}, "task_id": {"type": "string"}, "session_id": {"type": "string"}}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}, "outputSchema": output_schema(),
            "_meta": {"ui": {"resourceUri": RESOURCE_URI, "visibility": ["model"]},
                      "openai/ui": {"entrypoints": [{"type": "thread"}]}}}


def refresh_schema():
    return {"name": REFRESH_TOOL, "title": "Refresh Workflow", "description": "Read the same enrolled task using an opaque view reference. Reads recorded state only.",
            "inputSchema": {"type": "object", "properties": {"view_ref": {"type": "string"}}, "required": ["view_ref"], "additionalProperties": False},
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}, "outputSchema": output_schema(),
            "_meta": {"ui": {"visibility": ["app"]}}}


def resource():
    return {"uri": RESOURCE_URI, "name": "Workflow", "description": "Read recorded task, experiment and run status.", "mimeType": MIME_TYPE,
            "_meta": {"ui": {"csp": {"connectDomains": [], "resourceDomains": [], "frameDomains": []}, "prefersBorder": False}}}


def read_resource():
    return {**resource(), "text": (Path(__file__).resolve().parents[1] / "assets" / "workflow.html").read_text(encoding="utf-8")}


def identifier(value, fallback="unknown"):
    return value if isinstance(value, str) and IDENTIFIER.fullmatch(value) else fallback


def label(value, fallback="Untitled task"):
    """Drop path-bearing tokens before displaying human labels."""
    if not isinstance(value, str):
        return fallback
    words = value.split()
    # Titles can include source paths. Omit their complete token, including a
    # preceding drive letter or URL, instead of exposing a partial private path.
    cleaned = " ".join("[private reference]" if any(c in word for c in ("/", "\\", "~")) else word for word in words)
    cleaned = "".join(c for c in cleaned if c.isprintable())
    return cleaned or fallback


def enum(value, allowed):
    return value if isinstance(value, str) and value in allowed else "unknown"


def timestamp(value):
    return value if isinstance(value, str) and TIMESTAMP.fullmatch(value) else None


def integer(value):
    return value if type(value) is int and 0 <= value else None


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
    process = mapping(state.get("process"))
    if process.get("protocol_version") == 2 and process.get("stage") not in ("implementation", "delivery"):
        return enum(process.get("stage"), PROCESS_STAGES)
    items = mapping(state.get("items"))
    statuses = [mapping(v).get("status") for v in items.values()]
    integration = mapping(state.get("integration")).get("status")
    if integration == "complete":
        return "integrated"
    if integration:
        return "integration"
    if statuses and all(v == "complete" for v in statuses):
        return "delivery" if process.get("stage") == "delivery" else "verification complete"
    if "reviewing" in statuses:
        return "review"
    if "implementing" in statuses:
        return "implementation"
    if process.get("protocol_version") == 2 and process.get("stage") == "delivery":
        return "delivery"
    approval, design = mapping(state.get("approval")), mapping(state.get("design"))
    if approval.get("digest") and approval.get("digest") == design.get("digest"):
        return "implementation" if process.get("protocol_version") == 2 else "approved"
    return "design recorded" if design else "enrolled"


def phase_detail(state):
    """Project counts and fixed guidance, never design or conversation contents."""
    process = mapping(state.get("process"))
    if process.get("protocol_version") != 2:
        return ""
    current = process.get("stage")
    if current == "discussion":
        questions = process.get("questions", [])
        unresolved = sum(1 for question in questions if isinstance(question, dict) and question.get("status") == "pending") if isinstance(questions, list) else 0
        return str(unresolved) + (" open question" if unresolved == 1 else " open questions")
    return {"exploration": "Confirm the request and inspect available evidence.",
            "design": "Prepare the design from confirmed requirements.",
            "design_review": "Check the design before user confirmation.",
            "design_confirmation": "Awaiting user confirmation of the design.",
            "plan": "Prepare implementation steps and verification.",
            "plan_confirmation": "Awaiting user confirmation of the plan.",
            "delivery": "Review the result and verification evidence."}.get(current, "")


def project_task(state, source_resources=None):
    items, experiments, runs = (mapping(state.get(key)) for key in ("items", "experiments", "runs"))
    projected_runs = []
    for run_id, raw in runs.items():
        run = mapping(raw)
        projected_runs.append({"run_id": identifier(run_id), "status": enum(run.get("status"), RUN_STATES),
                               "experiment_id": identifier(run.get("experiment_id"), None),
                               "resource_id": identifier(run.get("resource_id"), None),
                               "created": timestamp(run.get("created"))})
    resources = source_resources if isinstance(source_resources, list) else []
    projected_resources = []
    for raw in resources:
        record = mapping(raw)
        references = []
        for reference in record.get("run_refs", []) if isinstance(record.get("run_refs"), list) else []:
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
            "process_protocol": integer(mapping(state.get("process")).get("protocol_version")), "phase_detail": phase_detail(state),
            "closure": closure(state.get("task_lifecycle")),
            "items": [{"item_id": identifier(key), "title": label(mapping(raw).get("title"), "Untitled item"),
                       "status": enum(mapping(raw).get("status"), ITEM_STATES), "overall": mapping(raw).get("overall") is True} for key, raw in items.items()],
            "experiments": [{"experiment_id": identifier(key), "closure": closure(raw),
                             "created": timestamp(mapping(raw).get("created"))} for key, raw in experiments.items()],
            "runs": projected_runs, "resources": projected_resources,
            "truncated": False}


def unbound(reason="context_required"):
    notices = {"context_required": "Call the enrollment or status MCP tool with the known project and task, or call workflow.status_view. Supply the host session identifier when available.",
               "unavailable": "Reopen Workflow through a lifecycle MCP tool or workflow.status_view with the same known project, task and session after reconnecting.",
               "context_mismatch": "The supplied session context does not match the enrolled task."}
    return {"schema_version": 1, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "status": "unbound", "reason": reason,
            "view_ref": None, "tasks": [], "notice": notices[reason]}


class ViewStore:
    """Per-server opaque references; no files, configuration, or global fallback."""
    def __init__(self, core=None):
        self.core = core or workflow
        self.views = {}
        self.sessions = {}

    def read(self, binding, reference):
        try:
            response = self.core.dispatch("status", {"root": binding["root"], "task_id": binding["task_id"]})
            state = response.get("state")
            if response.get("ok") is not True or not isinstance(state, dict) or state.get("task_id") != binding["task_id"]:
                return unbound("unavailable")
            if state.get("root") and Path(state["root"]).expanduser().resolve() != Path(binding["root"]).expanduser().resolve():
                return unbound("context_mismatch")
            if binding.get("session_id") and binding["session_id"] != state.get("session_id"):
                return unbound("context_mismatch")
            session_id = binding.get("session_id") or state.get("session_id")
            selections = response.get("session_bindings", {})
            if not isinstance(selections, dict) or (session_id in selections and selections[session_id] != binding["task_id"]):
                return unbound("context_mismatch")
            return {"schema_version": 1, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "status": "bound", "view_ref": reference,
                    "tasks": [project_task(state, response.get("resources"))], "notice": "Current enrolled task. Recorded states only; refresh reads the latest stored records."}
        except Exception:
            return unbound("unavailable")

    def open(self, arguments, host_session=None):
        # The optional documented openai/session metadata correlates calls; it
        # does not authorize enrollment or identify a filesystem project. Seed
        # this process-local association only from a verified explicit context.
        if not arguments and host_session in self.sessions:
            arguments = self.sessions[host_session]
        if not arguments.get("root") or not arguments.get("task_id"):
            return unbound()
        root, task_id = arguments["root"], identifier(arguments["task_id"], None)
        if not isinstance(root, str) or not Path(root).expanduser().is_absolute() or task_id is None:
            return unbound("unavailable")
        reference = secrets.token_urlsafe(32)
        binding = {"root": root, "task_id": task_id, "session_id": arguments.get("session_id"), "host_session": host_session}
        result = self.read(binding, reference)
        if result["status"] == "bound":
            self.views[reference] = binding
            if host_session:
                self.sessions[host_session] = {key: value for key, value in binding.items() if key != "host_session"}
        return result

    def refresh(self, reference, host_session=None):
        binding = self.views.get(reference)
        if not binding:
            return unbound("unavailable")
        previous_host = binding.get("host_session")
        if previous_host:
            selected = self.sessions.get(previous_host)
            if ((host_session and host_session != previous_host) or not selected
                    or any(selected.get(key) != binding.get(key) for key in ("root", "task_id", "session_id"))):
                return unbound("context_mismatch")
        result = self.read(binding, reference)
        return result
