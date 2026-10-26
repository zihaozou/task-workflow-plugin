#!/usr/bin/env python3
"""Explicitly enrolled, event-backed project workflow. Python standard library only."""
from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import tempfile
import threading
import uuid


VERSION = 1
PORTABLE_FORMAT = 2
EXECUTION_PROTOCOL = 2
STATES = ("pending", "implementing", "reviewing", "complete")
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
MAX_JSON = 4 * 1024 * 1024
MAX_OUTPUT = 16000
TERMINAL_RUNS = ("complete", "failed", "cancelled")

class WorkflowError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message

def fail(code, message):
    raise WorkflowError(code, message)

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def sha_file(path):
    result = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()

def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        fail("invalid_identifier", "Identifiers must contain 1-64 letters, digits, underscores or hyphens.")
    return value

def text_value(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 100000:
        fail("invalid_text", "A nonempty bounded text value is required.")
    return value

def existing_dir(value):
    if not isinstance(value, str) or not value:
        fail("invalid_path", "An existing absolute directory is required.")
    path = Path(value).expanduser()
    if not path.is_absolute() or not path.is_dir() or path.is_symlink():
        fail("invalid_path", "An existing absolute directory without a symlink leaf is required.")
    return path.resolve()

def within(path, parent):
    return path == parent or parent in path.parents

def safe_relative(value):
    if not isinstance(value, str) or not value or "\\" in value:
        fail("unsafe_path", "A safe relative path is required.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(x in ("", ".", "..") for x in path.parts) or value != str(path):
        fail("unsafe_path", "Absolute paths and traversal are prohibited.")
    return path

def no_symlinks(path, anchor):
    if not within(path.absolute(), anchor.absolute()):
        fail("unsafe_path", "Path is outside its authorized directory.")
    current = anchor
    if current.is_symlink():
        fail("unsafe_path", "Symlink paths are prohibited.")
    for part in path.relative_to(anchor).parts:
        current = current / part
        if current.is_symlink():
            fail("unsafe_path", "Symlink paths are prohibited.")

def run(argv, cwd=None, timeout=60, max_output=MAX_OUTPUT, input_text=None):
    # Disk-backed capture prevents a noisy child from exhausting Python memory.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            result = subprocess.run(argv, cwd=cwd, input=input_text.encode() if input_text is not None else None,
                                    **({} if input_text is not None else {"stdin": subprocess.DEVNULL}),
                                    stdout=stdout, stderr=stderr,
                                    timeout=timeout, shell=False)
            code, error = result.returncode, None
        except subprocess.TimeoutExpired:
            code, error = None, "timeout"
        except OSError:
            code, error = None, "unavailable"
        result = {"returncode": code}
        for name, stream in (("stdout", stdout), ("stderr", stderr)):
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - max_output))
            result[name] = stream.read().decode("utf-8", "replace")
        if error:
            result["error"] = error
        return result

def git(path, *argv):
    result = run(["git", "-C", str(path), *argv])
    if result["returncode"] != 0:
        fail("git_error", "Git could not validate the requested operation.")
    return result["stdout"].strip()

def git_identity(path):
    path = existing_dir(str(path))
    top = Path(git(path, "rev-parse", "--show-toplevel")).resolve()
    if path != top:
        fail("git_identity", "Project and worktree paths must be exact Git checkout roots.")
    common = Path(git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
    branch = git(path, "symbolic-ref", "--quiet", "--short", "HEAD")
    if not git_registered_worktree(path, path, "refs/heads/" + branch):
        fail("git_identity", "The checkout must be registered by Git at its exact path and branch.")
    return {"path": str(path), "common_dir": str(common), "branch": branch}

def git_registered_worktree(repository, path, branch=None):
    for record in git(repository, "worktree", "list", "--porcelain", "-z").split("\0\0"):
        fields = dict(field.split(" ", 1) if " " in field else (field, "") for field in record.split("\0") if field)
        if fields.get("worktree") == str(path) and fields.get("branch") == branch:
            return True
    return False

def check_identity(state):
    for key in ("project", "worktree"):
        current = git_identity(state[key]["path"])
        if current != state[key]:
            fail("git_identity_changed", "A registered checkout identity or branch changed.")
    if state["project"]["common_dir"] != state["worktree"]["common_dir"]:
        fail("git_identity", "Project and worktree must belong to the same Git repository.")

def revision(state, clean=True):
    check_identity(state)
    if state["project"]["path"] == state["worktree"]["path"] or state["project"]["branch"] == state["worktree"]["branch"]:
        fail("worktree_required", "Prepare or explicitly enroll a distinct task worktree before implementation.")
    path = state["worktree"]["path"]
    status = git(path, "status", "--porcelain=v1", "--untracked-files=all")
    if clean and status:
        fail("dirty_revision", "Commit or explicitly resolve worktree changes before collecting evidence.")
    return {"commit": git(path, "rev-parse", "HEAD"),
            "tree": git(path, "rev-parse", "HEAD^{tree}"), "clean": not bool(status)}

def atomic_json(path, value):
    raw = canonical(value) + b"\n"
    fd, name = tempfile.mkstemp(prefix=".projection-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)

def sync_dir(path):
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass

@contextlib.contextmanager
def lock(path):
    try:
        path.mkdir()
    except FileExistsError:
        fail("locked", "A conservative workflow lock exists; verify its owner manually before removal.")
    try:
        atomic_json(path / "owner.json", {"pid": os.getpid(), "host": __import__("socket").gethostname(), "created": now()})
        yield
    finally:
        # Never delete an unexpected file or recursively remove another owner's lock.
        (path / "owner.json").unlink(missing_ok=True)
        path.rmdir()

def store_dir(root, create=False):
    root = existing_dir(root)
    store = root / ".task-workflow"
    no_symlinks(store, root)
    if create:
        store.mkdir(exist_ok=True)
    if not store.is_dir():
        fail("not_enrolled", "This root has no explicitly enrolled workflow.")
    return root, store

def task_dir(store, task_id):
    path = store / "tasks" / identifier(task_id)
    no_symlinks(path, store)
    return path

def read_json(path):
    try:
        if path.is_symlink() or path.stat().st_size > MAX_JSON:
            fail("corrupt_state", "State file is unsafe or too large.")
        return json.loads(path.read_text())
    except (OSError, ValueError):
        fail("corrupt_state", "A workflow state file is missing or invalid.")

def state_patch(before, after, prefix=None):
    prefix = prefix or []
    if isinstance(before, dict) and isinstance(after, dict):
        patches = []
        for key in sorted(set(before) | set(after)):
            if key not in after:
                patches.append({"op": "delete", "path": prefix + [key]})
            elif key not in before:
                patches.append({"op": "set", "path": prefix + [key], "value": after[key]})
            else:
                patches.extend(state_patch(before[key], after[key], prefix + [key]))
        return patches
    if before == after:
        return []
    if isinstance(before, list) and isinstance(after, list) and len(after) >= len(before) and after[:len(before)] == before:
        return [{"op": "append", "path": prefix, "value": after[len(before):]}]
    return [{"op": "set", "path": prefix, "value": after}]

def replay_patch(state, patches):
    state = copy.deepcopy(state)
    try:
        for patch in patches:
            parts = patch["path"]
            if not parts or any(not isinstance(x, str) for x in parts):
                fail("corrupt_history", "An event patch path is invalid.")
            parent = state
            for key in parts[:-1]:
                parent = parent[key]
            key = parts[-1]
            if patch["op"] == "set":
                parent[key] = patch["value"]
            elif patch["op"] == "delete":
                del parent[key]
            elif patch["op"] == "append":
                parent[key].extend(patch["value"])
            else:
                fail("corrupt_history", "An event patch operation is invalid.")
    except (KeyError, TypeError, AttributeError):
        fail("corrupt_history", "An event patch cannot be replayed.")
    return state

def load_events(path):
    folder = path / "events"
    if not folder.is_dir() or folder.is_symlink():
        fail("not_found", "The requested task has no event history.")
    files = sorted(folder.glob("*.json"))
    if not files:
        fail("not_found", "The requested task has no event history.")
    previous = None
    state = None
    for sequence, event_path in enumerate(files, 1):
        if event_path.name != f"{sequence:08d}.json":
            fail("corrupt_history", "Event sequence is incomplete.")
        event = read_json(event_path)
        expected_hash = event.pop("hash", None)
        if event.get("previous") != previous or digest(event) != expected_hash:
            fail("corrupt_history", "Event integrity validation failed.")
        state = event["state"] if "state" in event else replay_patch(state, event.get("patches", []))
        if not isinstance(state, dict) or state.get("version") != sequence:
            fail("corrupt_history", "Event state version is invalid.")
        previous = expected_hash
    return state, previous

def record_text(state):
    lines = [f"# {state['title']}", "", f"Task: `{state['task_id']}` · version {state['version']}",
             "", f"Project: `{state['project']['path']}`", f"Worktree: `{state['worktree']['path']}`",
             "", "Generated from immutable events; edit through the workflow commands.",
             "", "## Design and authorization", "", (state.get("design") or {}).get("content", "No design recorded.")]
    design = state.get("design") or {}
    approval = state.get("approval") or {}
    lines += ["", f"Design version: {design.get('version', 'none')}; digest: `{design.get('digest', 'none')}`.",
              f"Approval: {approval.get('actor', 'none')}; source: {approval.get('authorization_source', 'none')}.",
              "", "## Plan, progress and evidence", ""]
    for item_id, item in state["items"].items():
        lines += [f"### {item_id}: {item['title']}", "", f"State: **{item['status']}**; implementer: {item.get('implementer') or 'unassigned'}.",
                  f"Scope: {'overall' if item['overall'] else ', '.join(item.get('owned_paths', []))}."]
        if item.get("blocked"):
            lines.append(f"Blocked: {item['blocked']}")
        if item.get("reason"):
            lines.append(f"Reason: {item['reason']}")
        if item.get("next_action"):
            lines.append(f"Next action: {item['next_action']}")
        if item.get("submitted"):
            lines.append(f"Submitted commit: `{item['submitted']['revision']['commit']}`.")
        for check in item.get("verifications", []):
            lines.append(f"Verification: {'PASS' if check['passed'] else 'FAIL'}; actual exit {check['result']['returncode']}; commit `{check['revision']['commit']}`; log `{check['log']}`.")
        if item.get("review"):
            review = item["review"]
            lines.append(f"Independent review by {review['actor']}: {review['verdict']}. {review['notes']}")
        if item.get("acceptance"):
            accept = item["acceptance"]
            lines.append(f"Coordinator acceptance by {accept['actor']}: {accept['notes']}")
        lines.append("")
    lines += ["## Decisions", ""]
    lines += [f"- {d['time']} — {d['actor']}: {d['content']}" for d in state["decisions"]] or ["None."]
    integration = state.get("integration", {})
    preparation = state.get("worktree_preparation")
    if preparation:
        lines += ["", "## Development worktree", "", f"Preparation: **{preparation['status']}**; branch: `{preparation['branch']}`.",
                  f"Reserved path: `{preparation['path']}`.", f"Preparation base: `{preparation['base']}`."]
        if preparation["status"] != "complete":
            lines.append("Next action: inspect the reserved checkout and retry worktree-prepare with the current task version and recorded base commit.")
    lines += ["", "## Integration", "", f"Status: {integration.get('status', 'not integrated')}; commit: `{integration.get('commit', 'none')}`."]
    if integration.get("scratch") and integration.get("status") != "complete":
        lines.append(f"Isolated integration checkout: `{integration['scratch']}`.")
        lines.append("Next action: inspect this checkout and the base before retrying. Resolve task changes in development and renew review when required.")
    if integration.get("conflicts"):
        conflicts = sorted(set(line.split("\t", 1)[-1] for line in integration["conflicts"].splitlines()))
        lines.append("Conflicting paths: " + ", ".join("`" + name + "`" for name in conflicts) + ".")
    for attempt in state.get("integration_history", []):
        if attempt.get("scratch") and Path(attempt["scratch"]).exists():
            lines.append(f"Preserved earlier integration checkout ({attempt.get('status', 'unknown')}): `{attempt['scratch']}`. Inspect and safely remove it after resolving retained material.")
    if integration.get("verification"):
        check = integration["verification"]
        lines.append(f"Post-merge verification: {'PASS' if check['passed'] else 'FAIL'}; log `{check['log']}`.")
    lines += ["", "## Experiments", ""]
    lifecycle = state.get("task_lifecycle", {})
    lines += [f"Task aggregate status: {lifecycle.get('status', 'unrecorded')}; outcome: {lifecycle.get('closure', {}).get('outcome', 'unrecorded')}."]
    if lifecycle.get("closure"):
        lines += [f"Task outcome acceptance: {lifecycle['closure']['notes']}", "Evidence: " + ", ".join(lifecycle['closure']['evidence'])]
    for experiment_id, research in state.get("experiments", {}).items():
        lines += [f"- Experiment `{experiment_id}`: {research['status']}; goal: {research['goal']}; directory: `{research['directory']}`."]
        if research.get("closure"):
            lines.append(f"  Outcome: {research['closure']['outcome']}; analysis accepted: {research['closure']['notes']}")
            lines.append("  Evidence: " + ", ".join(research['closure']['evidence']))
    for run_id, experiment in state["runs"].items():
        if "commit" not in experiment:
            lines.append(f"- Run `{run_id}`: {experiment['status']}; experiment: {experiment.get('experiment_id') or 'task verification'}; resource: {experiment.get('resource_id') or 'none'}.")
            continue
        lines += [f"- `{run_id}`: {experiment['status']}; resource {experiment.get('resource_id') or 'none'}.",
                  f"  Frozen commit `{experiment['commit']}`, design `{experiment['design_digest']}`; snapshot `{experiment['code']}`; environment `{experiment['environment']['path']}`."]
        if experiment.get("execution_intent") and not experiment.get("start_validated"):
            lines.append("  Execution dispatched; waiting for actual runner admission.")
        if experiment.get("start_validated") and experiment["start_validated"].get("pid") is None and "pid" in experiment["start_validated"]:
            lines.append("  Runner admitted; workload launch failed.")
        elif experiment.get("start_validated"):
            lines.append(f"  Actual workload started at {experiment['started']}; process {experiment['start_validated'].get('pid', 'unrecorded')}.")
        if experiment.get("execution"):
            lines.append(f"  Actual exit {experiment['execution']['returncode']}; log `{experiment['execution']['log']}`.")
        if experiment.get("artifact_acceptance"):
            lines.append(f"  Artifacts accepted by {experiment['artifact_acceptance']['actor']}: {experiment['artifact_acceptance']['notes']}")
    return "\n".join(lines) + "\n"

def project_state(path, state):
    no_symlinks(path / "state.json", path)
    no_symlinks(path / "record.md", path)
    atomic_json(path / "state.json", state)
    if "resource_id" in state and "items" not in state:
        return
    fd, name = tempfile.mkstemp(prefix=".record-", dir=str(path))
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(record_text(state))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path / "record.md")
    finally:
        if os.path.exists(name):
            os.unlink(name)
    sync_dir(path)

def commit_event(path, state, previous, operation, actor):
    state["version"] += 1
    state["updated"] = now()
    event = {"format": VERSION, "operation": operation, "actor": actor,
             "time": state["updated"], "previous": previous}
    if previous is None:
        event["state"] = state
    else:
        before, actual_previous = load_events(path)
        if actual_previous != previous:
            fail("revision_conflict", "Event history changed during the operation.")
        event["patches"] = state_patch(before, state)
    event["hash"] = digest(event)
    raw = canonical(event) + b"\n"
    if len(raw) > MAX_JSON:
        fail("state_too_large", "Task event exceeds the bounded storage size.")
    destination = path / "events" / f"{state['version']:08d}.json"
    # Publish complete bytes with an exclusive hard link: readers cannot observe a
    # partial final event and existing event filenames can never be overwritten.
    fd, pending = tempfile.mkstemp(prefix=".event-", dir=str(path / "events"))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(pending, 0o444)
        os.link(pending, destination)
        sync_dir(path / "events")
    except FileExistsError:
        fail("revision_conflict", "An event with this version already exists.")
    finally:
        os.unlink(pending)
    project_state(path, state)
    return event["hash"]

def summary(state):
    return {"task_id": state["task_id"], "version": state["version"],
            "scope_paths": sorted(set([state["project"]["path"], state["worktree"]["path"]] + [r[key] for r in state["runs"].values() for key in ("directory", "code") if key in r])),
            "counts": {key: sum(i["status"] == key for i in state["items"].values()) for key in STATES},
            "approved": bool(state.get("approval") and state.get("design") and state["approval"]["digest"] == state["design"]["digest"]),
            "integrated": state.get("integration", {}).get("status") == "complete",
            "session_id": state.get("session_id"),
            "active_runs": sum(r["status"] not in TERMINAL_RUNS for r in state["runs"].values()),
            "task_status": state.get("task_lifecycle", {}).get("status", "unrecorded"),
            "open_experiments": sum(e["status"] != "complete" for e in state.get("experiments", {}).values()),
            "run_counts": {key: sum(r["status"] == key for r in state["runs"].values()) for key in ("planned", "preparing", "prepared", "queued", "running", "awaiting_artifacts", "complete", "failed", "cancelled", "unknown")}}

def spec(description, required=None, optional=None):
    return {"description": description, "required": {"root": "string", **(required or {})}, "optional": optional or {}}

def mutation(description, required=None, optional=None):
    return spec(description, {"task_id": "string", "actor": "string", "expected_version": "integer", **(required or {})}, optional)

def command_schemas():
    result = []
    for name, command in COMMANDS.items():
        properties = {key: {"type": value} for key, value in {**command["required"], **command["optional"]}.items()}
        for key in ("argv", "lockfiles", "artifacts", "owned_paths", "evidence", "ownership_evidence"):
            if key in properties:
                properties[key]["items"] = {"type": "string"}
        result.append({"name": name, "description": command["description"], "inputSchema": {
            "type": "object", "properties": properties, "required": list(command["required"]), "additionalProperties": False}})
    return result

def validate(operation, args):
    if operation not in COMMANDS or not isinstance(args, dict):
        fail("invalid_operation", "Unknown operation or invalid argument object.")
    command = COMMANDS[operation]
    allowed = {**command["required"], **command["optional"]}
    if set(args) - set(allowed) or set(command["required"]) - set(args):
        fail("invalid_arguments", "Arguments contain unknown fields or omit required fields; use schema.")
    types = {"string": str, "integer": int, "boolean": bool, "array": list, "object": dict}
    for key, value in args.items():
        if type(value) is not types[allowed[key]]:
            fail("invalid_arguments", "An argument has an incorrect JSON type.")
    for key in ("actor", "authorization_source", "title", "content", "notes", "artifact_notes", "dependency_declaration", "reason", "commit_message", "goal", "handle", "eligibility_key", "token"):
        if key in args:
            text_value(args[key])
    for key in ("task_id", "item_id", "run_id", "environment_id", "experiment_id", "parent_run_id", "resource_id"):
        if key in args:
            identifier(args[key])
    for key in ("argv", "lockfiles", "artifacts", "owned_paths", "evidence", "ownership_evidence"):
        if key in args and (len(args[key]) > 200 or any(not isinstance(x, str) or not x or "\x00" in x for x in args[key])):
            fail("invalid_arguments", "Argument arrays require bounded nonempty strings.")
    if "argv" in args and not args["argv"]:
        fail("invalid_arguments", "A nonempty executable argv is required.")
    if "expected_version" in args and args["expected_version"] < 1:
        fail("invalid_arguments", "Expected version must be a positive integer.")
    for duration_key in ("expected_duration_seconds", "recovery_margin_seconds"):
        if duration_key in args and not 1 <= args[duration_key] <= 365 * 86400:
            fail("invalid_duration", "Expected duration and recovery margin must be positive seconds, bounded to one year.")
    if "timeout" in args:
        if args["timeout"] < 1 or (operation not in ("run-execute", "run-dispatch") and args["timeout"] > 3600):
            fail("invalid_arguments", "Run timeout must be positive; command checks are bounded to 3600 seconds.")

def require_approved(state):
    if not summary(state)["approved"]:
        fail("approval_required", "Explicit approval of the current design is required.")

def binding(state, rev, item=None):
    value = {"design_digest": state["design"]["digest"], "revision": rev}
    if item is not None and not item["overall"]:
        paths = item.get("owned_paths")
        if not paths:
            fail("scope_required", "Implementation items must declare owned_paths; overall checks cover the complete revision.")
        objects = {}
        if state.get("cleaned"):
            repository = state["project"]["path"]
            source_tree = rev["tree"]
            if git(repository, "cat-file", "-t", source_tree) != "tree":
                fail("stale_evidence", "The recorded source tree is unavailable for scoped acceptance.")
            for path in paths:
                entry = git(repository, "--literal-pathspecs", "ls-tree", source_tree, "--", path)
                if not entry:
                    objects[path] = "absent"
                    continue
                fields = entry.split("\t", 1)[0].split()
                if len(fields) != 3 or "\n" in entry:
                    fail("stale_evidence", "A recorded scope cannot be resolved to one source-tree object.")
                git(repository, "cat-file", "-e", fields[2])
                objects[path] = fields[2]
        else:
            for path in paths:
                result = run(["git", "-C", state["worktree"]["path"], "rev-parse", "--verify", rev["commit"] + ":" + path])
                objects[path] = result["stdout"].strip() if result["returncode"] == 0 else "absent"
        value["scope"] = {"paths": paths, "digest": digest(objects)}
    return value

def evidence_matches(evidence, current):
    if not evidence or evidence.get("design_digest") != current["design_digest"]:
        return False
    return evidence.get("scope") == current["scope"] if "scope" in current else evidence.get("revision") == current["revision"]

def get_item(state, item_id):
    if item_id not in state["items"]:
        fail("not_found", "The task item does not exist.")
    return state["items"][item_id]

def make_item(title, overall=False, owned_paths=None):
    return {"title": title, "overall": overall, "owned_paths": owned_paths or [], "status": "pending", "implementer": None,
            "submitted": None, "verifications": [], "review": None, "acceptance": None,
            "blocked": "", "reason": "", "next_action": ""}

def branch_absent(project, branch):
    return run(["git", "-C", str(project), "show-ref", "--verify", "--quiet", "refs/heads/" + branch])["returncode"] == 1

def absolute_destination(value):
    path = Path(value).expanduser()
    if not path.is_absolute() or ".." in path.parts:
        fail("invalid_path", "Worktree destinations must be absolute paths without traversal.")
    no_symlinks(path, Path(path.anchor))
    return path.resolve()

def project_status(state):
    # Exclude only verified, registered nested checkouts, never their container.
    excluded = [":(top,literal,exclude)" + name for tree in registered_task_trees(state) for name in [str(Path(tree["path"]).relative_to(Path(state["project"]["path"])))]]
    return git(state["project"]["path"], "status", "--porcelain=v1", "--untracked-files=all", "--", ".", *excluded)

def prepare_worktree(args, state, path, store, previous):
    project = Path(state["project"]["path"])
    if git_identity(str(project)) != state["project"]:
        fail("git_identity_changed", "The registered base checkout changed.")
    if state.get("cleaned"):
        fail("already_cleaned", "A cleaned task cannot create a replacement worktree.")
    common = Path(state["project"]["common_dir"])
    with lock(common / "task-workflow-integration.lock"), lock(store / "registry.lock"):
        association = state.get("worktree_preparation")
        if association:
            for argument, field in (("branch", "branch"),):
                supplied = str(absolute_destination(args[argument])) if argument != "branch" and argument in args else args.get(argument)
                if supplied is not None and supplied != association.get(field):
                    fail("worktree_association", "This task already reserves a different worktree path or branch.")
            if args["expected_base"] != association["base"]:
                fail("revision_conflict", "Retry using the recorded preparation base.")
            if association["status"] == "complete":
                check_identity(state)
                register_root(Path(state["root"]), state)
                return {"worktree": state["worktree"], "reused": True}, previous, False
        else:
            base = git(project, "rev-parse", "HEAD")
            if args["expected_base"] != base:
                fail("revision_conflict", "The expected base commit changed.")
            if state["worktree"]["path"] != str(project):
                check_identity(state)
                if state["worktree"]["branch"] == state["project"]["branch"]:
                    fail("worktree_association", "The task must use a distinct development branch.")
                target = Path(state["worktree"]["path"])
                branch = state["worktree"]["branch"]
                root = absolute_destination(str(project / ".worktrees"))
                if args.get("branch", branch) != branch or target != root / state["task_id"]:
                    fail("worktree_association", "Reuse the task's explicitly enrolled worktree in place.")
                state["worktree_preparation"] = {"status": "complete", "path": str(target), "branch": branch,
                    "worktree_root": str(root), "base": base, "reused": True, "authorization_source": args["authorization_source"]}
                return {"worktree": state["worktree"], "reused": True}, previous, True
            if any(item["status"] != "pending" for item in state["items"].values()) or state["runs"] or state["integration"]:
                fail("worktree_association", "Preparation cannot migrate active evidence or runs to another checkout.")
            token = uuid.uuid4().hex
            root = absolute_destination(str(project / ".worktrees"))
            name = state["task_id"]
            target = absolute_destination(str(root / name))
            branch = args.get("branch", "task/" + name + "-" + token[:8])
            if target.parent != root or target == project or within(project, target) or within(Path(state["root"]), target) or within(target, store):
                fail("invalid_path", "Choose a direct child of the declared worktree root, separate from base and task records.")
            valid = run(["git", "check-ref-format", "--branch", branch])
            if valid["returncode"] != 0 or valid["stdout"].strip() != branch or branch == state["project"]["branch"]:
                fail("invalid_branch", "A valid distinct literal task branch is required.")
            if target.exists() or not branch_absent(project, branch):
                fail("worktree_exists", "The destination or branch already exists; explicitly enroll a suitable existing worktree instead.")
            association = {"status": "reserved", "token": token, "path": str(target), "branch": branch,
                "worktree_root": str(root), "base": base, "authorization_source": args["authorization_source"], "time": now()}
            state["worktree_preparation"] = association
            previous = commit_event(path, state, previous, "worktree-prepare-intent", args["actor"])
        target, root = Path(association["path"]), Path(association["worktree_root"])
        no_symlinks(target, Path(target.anchor))
        owner_ref = "refs/task-workflow/worktrees/" + association["token"]
        owned = run(["git", "-C", str(project), "rev-parse", "--verify", owner_ref])
        if owned["returncode"] != 0:
            if target.exists() or not branch_absent(project, association["branch"]):
                fail("worktree_exists", "An unowned path or branch appeared after reservation; preserve it for manual inspection.")
            transaction = "start\ncreate refs/heads/" + association["branch"] + " " + association["base"] + "\ncreate " + owner_ref + " " + association["base"] + "\nprepare\ncommit\n"
            result = run(["git", "-C", str(project), "update-ref", "--stdin"], input_text=transaction)
            if result["returncode"] != 0:
                fail("worktree_reservation", "Git refused the atomic branch ownership reservation.")
        elif owned["stdout"].strip() != association["base"]:
            fail("worktree_association", "The task's ownership reference changed.")
        if git(project, "rev-parse", "refs/heads/" + association["branch"]) != association["base"]:
            fail("worktree_association", "The reserved branch changed before preparation completed.")
        if not target.exists():
            root.mkdir(parents=True, exist_ok=True)
            result = run(["git", "-C", str(project), "worktree", "add", "--", str(target), association["branch"]], timeout=300)
            if result["returncode"] != 0:
                fail("worktree_creation", "Git did not complete the reserved worktree; inspect reality and retry this reservation.")
        identity = git_identity(str(target))
        if identity != {"path": str(target), "branch": association["branch"], "common_dir": str(common)} or git(target, "rev-parse", "HEAD") != association["base"]:
            fail("worktree_association", "The reserved destination is not the expected task worktree.")
        if git(target, "status", "--porcelain=v1", "--untracked-files=all"):
            fail("dirty_revision", "Preserve and inspect changes in the interrupted preparation before retrying.")
        state.update(worktree=identity, owned_worktree=True)
        association["status"] = "complete"
        previous = commit_event(path, state, previous, "worktree-prepare-complete", args["actor"])
        register_root(Path(state["root"]), state)
        return {"worktree": identity, "reused": owned["returncode"] == 0}, previous, False

def require_implementation_complete(state):
    rev = revision(state)
    for item in state["items"].values():
        if not item["overall"] and (item["status"] != "complete" or not evidence_matches(item["acceptance"], binding(state, rev, item))):
            fail("implementation_incomplete", "Complete and validate all implementation scopes before overall verification.")

def invalidate_overall(state):
    for item in state["items"].values():
        if item["overall"]:
            item.update(status="pending", implementer=None, submitted=None, review=None, acceptance=None)

def invalidate_integration(state):
    if state["integration"]:
        state.setdefault("integration_history", []).append(copy.deepcopy(state["integration"]))
    state["integration"] = {}

def apply_item(operation, args, state, task_path):
    item = get_item(state, args["item_id"])
    actor = args["actor"]
    require_approved(state)
    if item["overall"] and operation in ("item-start", "item-accept"):
        require_implementation_complete(state)
    if operation == "item-start":
        revision(state)
        if item["status"] == "complete":
            if evidence_matches(item["acceptance"], binding(state, revision(state), item)):
                fail("invalid_transition", "This completed item still has current evidence.")
        elif item["status"] != "pending":
            fail("invalid_transition", "Only a pending or stale completed item can be started.")
        item.update(status="implementing", implementer=actor, submitted=None, review=None, acceptance=None, blocked="", next_action="")
        return
    if not item["implementer"]:
        fail("invalid_transition", "Start the item before submitting or collecting evidence.")
    current = binding(state, revision(state), item)
    if operation == "item-submit":
        if actor != item["implementer"] or item["status"] not in ("implementing", "reviewing"):
            fail("invalid_transition", "Only the implementer can submit an active item.")
        item.update(status="reviewing", submitted=current, review=None, acceptance=None)
    elif operation == "verify":
        if item["status"] not in ("implementing", "reviewing"):
            fail("invalid_transition", "Verification requires an active item.")
        result = run(args["argv"], cwd=state["worktree"]["path"], timeout=args.get("timeout", 300))
        try:
            unchanged = revision(state) == current["revision"]
        except WorkflowError:
            unchanged = False
        evidence_dir = task_path / "evidence"
        no_symlinks(evidence_dir, task_path)
        evidence_dir.mkdir(exist_ok=True)
        evidence_id = uuid.uuid4().hex
        log_path = evidence_dir / (evidence_id + ".json")
        atomic_json(log_path, {"stdout_tail": result.pop("stdout", ""), "stderr_tail": result.pop("stderr", ""), "output_limit_bytes": MAX_OUTPUT})
        item["verifications"].append({**current, "argv": args["argv"], "actor": actor, "time": now(),
                                     "passed": result["returncode"] == 0 and unchanged,
                                     "unchanged": unchanged, "result": result, "log": str(log_path), "log_sha256": sha_file(log_path)})
    elif operation == "item-review":
        if item["status"] != "reviewing" or not evidence_matches(item["submitted"], current):
            fail("stale_evidence", "Review requires the currently submitted design and revision.")
        if actor == item["implementer"]:
            fail("independent_review_required", "The reviewer must differ from the implementer.")
        if args["verdict"] not in ("accept", "changes"):
            fail("invalid_verdict", "Review verdict must be accept or changes.")
        item["review"] = {**current, "actor": actor, "verdict": args["verdict"], "notes": args["notes"], "time": now()}
        if args["verdict"] == "changes":
            item.update(status="implementing", submitted=None, acceptance=None)
    elif operation == "item-accept":
        if actor != state["coordinator"]:
            fail("coordinator_required", "Only the registered coordinator may accept an item.")
        review = item["review"] or {}
        if item["status"] != "reviewing" or not evidence_matches(item["submitted"], current) or review.get("verdict") != "accept" or not evidence_matches(review, current) or review.get("actor") == item["implementer"]:
            fail("stale_evidence", "A current independent accepting review is required.")
        checks = [v for v in item["verifications"] if evidence_matches(v, current)]
        if not checks or not checks[-1]["passed"]:
            fail("verification_required", "The latest actual verification of this revision must pass.")
        item.update(status="complete", acceptance={**current, "actor": actor, "notes": args["notes"], "time": now()}, blocked="", next_action="")

def all_current(state, rev):
    require_approved(state)
    if not any(i["overall"] for i in state["items"].values()):
        fail("overall_required", "An overall verification task item is required.")
    for item in state["items"].values():
        if item["status"] != "complete" or not evidence_matches(item["acceptance"], binding(state, rev, item)):
            fail("incomplete_items", "Every item, including overall verification, must be accepted at the current revision.")

def integration_commit_matches(project, integration, commit):
    parents = git(project, "rev-list", "--parents", "-n", "1", commit).split()
    message = git(project, "show", "-s", "--format=%B", commit)
    return (parents == [commit, integration["base"]]
            and git(project, "rev-parse", commit + "^{tree}") == integration.get("tree")
            and message == integration["commit_message"])

def commit_policy(project):
    pattern = r"^(core\.hookspath|commit\.(gpgsign|cleanup|template)|user\.(name|email|signingkey)|gpg\..*)$"
    result = run(["git", "-C", str(project), "config", "--get-regexp", pattern])
    if result["returncode"] not in (0, 1):
        fail("integration_policy", "Git commit policy could not be inspected.")
    return result["stdout"]

def check_scratch(state, integration):
    scratch = existing_dir(integration["scratch"])
    if (Path(git(scratch, "rev-parse", "--show-toplevel")).resolve() != scratch
            or Path(git(scratch, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve() != Path(state["project"]["common_dir"])
            or run(["git", "-C", str(scratch), "symbolic-ref", "--quiet", "HEAD"])["returncode"] != 1
            or not git_registered_worktree(scratch, scratch)):
        fail("integration_scratch", "The recorded isolated integration worktree changed identity.")
    return scratch

def remove_integration_scratch(state, integration):
    scratch = Path(integration["scratch"])
    if not scratch.exists():
        return
    check_scratch(state, integration)
    if git(scratch, "rev-parse", "HEAD") != integration["commit"] or git(scratch, "status", "--porcelain=v1", "--untracked-files=all", "--ignored"):
        fail("integration_scratch", "Preserve changed or unique material in the integration worktree.")
    result = run(["git", "-C", state["project"]["path"], "worktree", "remove", "--", str(scratch)], timeout=120)
    if result["returncode"] != 0:
        fail("integration_scratch", "Git refused safe removal of the isolated integration worktree.")

def integrate(args, state, path, previous):
    rev = revision(state)
    all_current(state, rev)
    project, worktree = Path(state["project"]["path"]), Path(state["worktree"]["path"])
    if project == worktree or state["project"]["branch"] != args["base_branch"] or state["worktree"]["branch"] == args["base_branch"]:
        fail("integration_target", "Integration requires a separate task branch and the registered base checkout.")
    head = rev["commit"]
    if args["expected_head"] != head:
        fail("revision_conflict", "The expected task commit changed.")
    with lock(Path(state["project"]["common_dir"]) / "task-workflow-integration.lock"):
        check_identity(state)
        if revision(state) != rev:
            fail("revision_conflict", "The task changed during integration checks.")
        integration = state["integration"]
        if integration:
            if (integration.get("method") != "squash" or integration["head"] != head
                    or integration["base"] != args["expected_base"] or integration["base_branch"] != args["base_branch"]
                    or ("commit_message" in args and args["commit_message"] != integration["requested_message"])):
                fail("integration_pending", "Inspect the recorded integration before starting another attempt.")
            if integration["status"] in ("conflict", "unknown", "empty"):
                fail("integration_pending", "The recorded integration needs inspection and renewed task review before retrying.")
        elif git(project, "rev-parse", "HEAD") != args["expected_base"]:
            fail("revision_conflict", "The expected base commit changed.")
        if project_status(state):
            fail("dirty_project", "The base checkout must be clean before integration.")
        if args.get("dry_run", True):
            return {"dry_run": True, "head": head, "base": args["expected_base"], "integration": integration}, previous, False
        if not integration:
            token = uuid.uuid4().hex
            scratch = path / ("integration-" + token)
            if scratch.exists():
                fail("integration_scratch", "The isolated integration destination already exists.")
            message = args.get("commit_message", state["title"]).strip()
            integration = {"method": "squash", "status": "preparing", "token": token, "head": head,
                "source_tree": rev["tree"], "base": args["expected_base"], "base_branch": args["base_branch"],
                "scratch": str(scratch), "requested_message": message,
                "commit_message": message + "\n\nTask-Workflow-Integration: " + token,
                "authorization_source": args["authorization_source"], "actor": args["actor"], "time": now()}
            state["integration"] = integration
            previous = commit_event(path, state, previous, "integrate-intent", args["actor"])
        if integration["status"] == "complete":
            if (not integration_commit_matches(project, integration, integration["commit"])
                    or run(["git", "-C", str(project), "merge-base", "--is-ancestor", integration["commit"], "HEAD"])["returncode"] != 0):
                fail("integration_changed", "The recorded integration is no longer present in base.")
            remove_integration_scratch(state, integration)
            return {"integration": integration, "already_integrated": True}, previous, False
        scratch = Path(integration["scratch"])
        if not scratch.exists():
            if integration["status"] != "preparing":
                fail("integration_scratch", "The recorded integration worktree is missing.")
            result = run(["git", "-C", str(project), "worktree", "add", "--detach", "--", str(scratch), integration["base"]], timeout=300)
            if result["returncode"] != 0:
                fail("integration_scratch", "Git did not complete the isolated worktree; inspect it before retrying.")
        check_scratch(state, integration)
        if integration["status"] == "preparing":
            if git(scratch, "rev-parse", "HEAD") != integration["base"] or git(scratch, "status", "--porcelain=v1", "--untracked-files=all", "--ignored"):
                fail("integration_scratch", "An interrupted squash has unrecorded changes; preserve it for inspection.")
            integration["status"] = "merging"
            previous = commit_event(path, state, previous, "integrate-merge-intent", args["actor"])
            result = run(["git", "-C", str(scratch), "merge", "--squash", "--no-commit", "--", head], timeout=300)
            conflicts = git(scratch, "ls-files", "--unmerged")
            if conflicts or result["returncode"] != 0:
                integration.update(status="conflict" if conflicts else "unknown", result=result, conflicts=conflicts)
                return {"integration": integration}, previous, True
            tree = git(scratch, "write-tree")
            if tree == git(project, "rev-parse", integration["base"] + "^{tree}"):
                integration.update(status="empty", result=result)
                return {"integration": integration, "no_task_changes": True}, previous, True
            integration.update(status="committing", tree=tree)
            previous = commit_event(path, state, previous, "integrate-commit-intent", args["actor"])
        if integration["status"] == "merging":
            # A squash has no MERGE_HEAD. The index is the authoritative conflict evidence.
            conflicts = git(scratch, "ls-files", "--unmerged")
            integration.update(status="conflict" if conflicts else "unknown", conflicts=conflicts)
            return {"integration": integration}, previous, True
        if integration["status"] == "committing":
            candidate = git(scratch, "rev-parse", "HEAD")
            if candidate == integration["base"]:
                if commit_policy(project) != commit_policy(scratch):
                    fail("integration_policy", "Base and isolated checkout have different commit hook, signing or author configuration; reconcile the explicit repository policy before committing.")
                if (git(scratch, "ls-files", "--unmerged") or git(scratch, "write-tree") != integration["tree"]
                        or run(["git", "-C", str(scratch), "diff", "--quiet"])["returncode"] != 0
                        or git(scratch, "ls-files", "--others", "--exclude-standard")):
                    fail("integration_scratch", "The prepared squash changed before commit; preserve it for inspection.")
                result = run(["git", "-C", str(scratch), "commit", "-m", integration["commit_message"]], timeout=300)
                candidate = git(scratch, "rev-parse", "HEAD")
                if result["returncode"] != 0 and candidate == integration["base"]:
                    integration.update(status="unknown", result=result)
                    return {"integration": integration}, previous, True
            if not integration_commit_matches(project, integration, candidate) or git(scratch, "status", "--porcelain=v1", "--untracked-files=all", "--ignored"):
                fail("integration_scratch", "The actual commit does not match the recorded squash tree, parent and token.")
            integration.update(status="publishing", commit=candidate)
            previous = commit_event(path, state, previous, "integrate-publish-intent", args["actor"])
        if integration["status"] == "publishing":
            candidate = integration["commit"]
            if not integration_commit_matches(project, integration, candidate) or git(scratch, "rev-parse", "HEAD") != candidate:
                fail("integration_scratch", "The recorded integration candidate changed.")
            base_now = git(project, "rev-parse", "HEAD")
            if base_now != candidate:
                if base_now != integration["base"] or project_status(state) or revision(state) != rev:
                    fail("revision_conflict", "Base or task changed before publication; the candidate is preserved.")
                result = run(["git", "-C", str(project), "merge", "--ff-only", "--no-overwrite-ignore", "--no-edit", "--", candidate], timeout=300)
                if result["returncode"] != 0:
                    integration.update(result=result)
                    return {"integration": integration}, previous, True
            if git(project, "rev-parse", "HEAD") != candidate or project_status(state):
                fail("revision_conflict", "Base changed during publication; inspect the recorded candidate before retrying.")
            integration["status"] = "complete"
            previous = commit_event(path, state, previous, "integrate-complete", args["actor"])
            remove_integration_scratch(state, integration)
        return {"integration": integration}, previous, True

def env_fingerprint(path, forbidden=()):
    logical = Path(path).expanduser()
    if not logical.is_absolute() or not logical.is_dir():
        fail("invalid_environment", "The registered environment path is unavailable.")
    env = logical.resolve()
    metadata = {}
    for package_root in sorted(env.glob("lib/python*/site-packages")):
        for pth in sorted(package_root.glob("*.pth")):
            if pth.stat().st_size > 1024 * 1024:
                fail("environment_unverifiable", "Environment path metadata exceeds the size limit.")
            value = pth.read_text(errors="replace")
            metadata[str(pth.relative_to(env))] = sha_file(pth)
            for line in value.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith(("import ", "import\t")):
                    if any(str(f) in line for f in forbidden):
                        fail("development_import", "Environment import hooks reference a development checkout.")
                    # Unknown executable path hooks could silently import live code.
                    if not line.startswith(("import _virtualenv", "import os; var = 'SETUPTOOLS_USE_DISTUTILS'")):
                        fail("unverifiable_import_hook", "An executable .pth import hook needs an explicit supported audit strategy.")
                    continue
                referenced = (package_root / line).resolve()
                if any(within(referenced, Path(f).resolve()) for f in forbidden):
                    fail("development_import", "An environment .pth path points into a development checkout.")
                if not within(referenced, env):
                    fail("external_import", "An environment .pth path points outside the registered environment.")
        for direct in sorted(package_root.glob("*.dist-info/direct_url.json")):
            value = read_json(direct)
            metadata[str(direct.relative_to(env))] = sha_file(direct)
            if value.get("dir_info", {}).get("editable"):
                fail("development_import", "Editable installed packages are prohibited for frozen experiments.")

    python = env / "bin" / "python"
    if not python.is_file() or not os.access(python, os.X_OK):
        fail("invalid_environment", "The registered environment must contain an executable bin/python.")
    result = run([str(python), "-I", "-c", "import importlib.metadata,json,sys; print(json.dumps({'prefix':sys.prefix,'version':sys.version,'packages':sorted((d.metadata.get('Name',''),d.version) for d in importlib.metadata.distributions())},sort_keys=True))"], timeout=60, max_output=1024 * 1024)
    if result["returncode"] != 0:
        fail("environment_unverifiable", "The registered environment could not report its package inventory.")
    try:
        inventory = json.loads(result["stdout"])
    except ValueError:
        fail("environment_unverifiable", "The environment returned an invalid package inventory.")
    if Path(inventory["prefix"]).resolve() != env:
        fail("invalid_environment", "The interpreter does not belong to the registered environment.")
    config = env / "pyvenv.cfg"
    return {"path": str(env), "logical_path": str(logical), "python": str(python.resolve()), "inventory": inventory,
            "path_metadata": metadata, "pyvenv_sha256": sha_file(config) if config.is_file() else None}

def manifest(folder):
    result = {}
    for path in sorted(folder.rglob("*")):
        if path.is_symlink():
            fail("unsafe_snapshot", "Snapshot symlinks are prohibited.")
        if path.is_file():
            result[str(path.relative_to(folder))] = sha_file(path)
        elif not path.is_dir():
            fail("unsafe_snapshot", "Snapshot contains a special filesystem object.")
    return result

def excluded(parts):
    return any(p in (".git", ".venv", "venv", "__pycache__", ".cache", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules") or p.endswith(".pyc") for p in parts)

def check_dependencies(files, declaration):
    if ".gitmodules" in files or any(p.endswith(".gitattributes") and b"filter=lfs" in content for p, content in files.items()):
        fail("unsupported_dependency", "Submodules and Git LFS require an explicit supported export strategy.")
    for name, data in files.items():
        if data.startswith(b"version https://git-lfs.github.com/spec/"):
            fail("unsupported_dependency", "Git LFS pointers cannot be used as experiment code or data.")
        if name.endswith(("pyproject.toml", "requirements.txt", "uv.lock", "poetry.lock")):
            text = data.decode("utf-8", "replace")
            if re.search(r"(?:file://|^-e\s|^--editable\s)", text, re.M):
                fail("unsupported_dependency", "External local dependencies require a supported explicit export strategy.")
            local_assignments = re.findall(r"(?:path|editable|directory)\s*=\s*([^,}\n]+)", text)
            if any(value.strip() not in ('"."', "'.'") for value in local_assignments):
                fail("unsupported_dependency", "External local dependencies require a supported explicit export strategy.")
    if declaration != "no-external-local-dependencies":
        fail("dependency_declaration_required", "Declare no-external-local-dependencies after checking imports and external inputs.")

def archive_preflight(project, commit):
    """Read Git object sizes, never blob contents, before bounded export."""
    with tempfile.TemporaryFile() as listing, tempfile.TemporaryFile() as errors:
        try:
            result = subprocess.run(["git", "-C", project, "ls-tree", "-r", "-l", "-z", "--full-tree", commit], stdout=listing, stderr=errors, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            fail("archive_failed", "Git could not inspect the snapshot object inventory.")
        if result.returncode != 0 or listing.tell() > 16 * 1024 * 1024:
            fail("snapshot_too_large", "Snapshot metadata is unavailable or exceeds the inventory limit.")
        listing.seek(0)
        total = 0
        for record in listing.read().split(b"\0"):
            if not record:
                continue
            try:
                header, name = record.split(b"\t", 1)
                mode, kind, object_id, size = header.split()
            except ValueError:
                fail("archive_failed", "Git returned an invalid object inventory.")
            if mode == b"160000" or kind == b"commit":
                fail("unsupported_dependency", "Submodule contents cannot silently disappear from experiment snapshots.")
            if mode == b"120000":
                fail("unsafe_snapshot", "Tracked symlinks require an explicit supported export strategy.")
            if kind == b"blob":
                length = int(size)
                total += length
                if length > 64 * 1024 * 1024 or total > 240 * 1024 * 1024:
                    fail("snapshot_too_large", "Tracked blobs exceed snapshot export limits; no blob data was copied.")

def require_coordinator(args, state):
    if args["actor"] != state["coordinator"]:
        fail("coordinator_required", "Only the registered coordinator can accept or reopen an aggregate scope.")

def task_lifecycle(state):
    # Old events stay unchanged until an explicit lifecycle operation is recorded.
    return state.setdefault("task_lifecycle", {"status": "open", "generation": 1, "history": []})

def require_task_open(state):
    require_portable_state(state)
    if state.get("task_lifecycle", {}).get("status") == "complete":
        fail("task_closed", "Reopen the task before adding or changing its work.")

def get_experiment(state, experiment_id):
    if experiment_id not in state.get("experiments", {}):
        fail("not_found", "The research experiment does not exist.")
    return state["experiments"][experiment_id]

def scope_ref(state, run_state):
    experiment_id = run_state.get("experiment_id")
    scope = get_experiment(state, experiment_id) if experiment_id else state.get("task_lifecycle", {})
    return {"task_id": state["task_id"], "kind": "experiment" if experiment_id else "task",
            "id": experiment_id or state["task_id"], "generation": scope.get("generation", 1)}

def plan_run(args, state, store, status="planned"):
    if args["run_id"] in state["runs"]:
        fail("already_exists", "Run identifiers cannot be reused; changed code or configuration requires a new run.")
    association = run_association(args, state)
    validate_resource_reference(store, state, association)
    planned = {"run_id": args["run_id"], "status": status, "created": now(), **association}
    state["runs"][args["run_id"]] = planned
    if association["experiment_id"]:
        get_experiment(state, association["experiment_id"])["run_ids"].append(args["run_id"])
    return {"run": planned}

def accepted_run_proof(state, current):
    """Revalidate accepted bytes and actual execution identity without consulting Git HEAD."""
    try:
        if current['status'] != 'complete':
            return False
        acceptance = current.get('artifact_acceptance', {})
        execution = current.get('execution', {})
        directory = Path(current['directory'])
        code = Path(current['code'])
        no_symlinks(directory, Path(directory.anchor))
        no_symlinks(code, directory)
        expected_log = directory / 'execution.log'
        no_symlinks(expected_log, directory)
        if (not acceptance.get('sha256') or set(acceptance['sha256']) != set(current['artifacts'])
                or execution.get('returncode') != 0 or execution.get('token') != current['token']
                or execution.get('argv_digest') != digest(current['argv'])
                or execution.get('manifest_digest') != current['manifest_digest']
                or execution.get('environment_digest') != digest(environment_identity(current['environment']))
                or not current.get('start_validated') or execution.get('log') != str(expected_log)
                or not expected_log.is_file() or sha_file(expected_log) != execution.get('log_sha256')
                or manifest(code) != current['manifest']):
            return False
        for name, expected in acceptance['sha256'].items():
            artifact = directory / str(safe_relative(name))
            no_symlinks(artifact, directory)
            if not artifact.is_file() or within(artifact, code) or sha_file(artifact) != expected:
                return False
        runtime = current['runtime']
        if runtime['digest'] != digest(runtime['files']):
            return False
        for name, expected in runtime['files'].items():
            target = Path(runtime['directory']) / str(safe_relative(name))
            no_symlinks(target, Path(state['root']))
            if not target.is_file() or sha_file(target) != expected:
                return False
        return True
    except (WorkflowError, OSError, KeyError, TypeError):
        return False


def successful_scope_proof(state):
    task_success = state.get('task_lifecycle', {}).get('closure', {}).get('outcome') == 'completed'
    for current in state['runs'].values():
        experiment = state.get('experiments', {}).get(current.get('experiment_id'), {})
        required = task_success or experiment.get('closure', {}).get('outcome') == 'completed'
        if required and current['status'] == 'complete' and not accepted_run_proof(state, current):
            return False
    return True


def close_scope(args, state, experiment_id=None):
    require_coordinator(args, state)
    require_approved(state)
    scope = get_experiment(state, experiment_id) if experiment_id else task_lifecycle(state)
    if scope["status"] != "open":
        fail("scope_closed", "This aggregate scope already has a recorded closure.")
    if args["outcome"] not in ("completed", "stopped", "abandoned") or not args["evidence"]:
        fail("acceptance_required", "Closure needs an explicit completed, stopped or abandoned outcome and evidence references.")
    runs = [r for r in state["runs"].values() if not experiment_id or r.get("experiment_id") == experiment_id]
    if any(r["status"] not in TERMINAL_RUNS for r in runs):
        fail("runs_incomplete", "Resolve all planned, prepared, queued, running and uncertain runs before closing the aggregate scope.")
    if args['outcome'] == 'completed' and any(current['status'] == 'complete' and not accepted_run_proof(state, current) for current in runs):
        fail('accepted_evidence_changed', 'Accepted output, snapshot or execution evidence changed; preserve it and resolve the aggregate outcome honestly.')
    if experiment_id:
        if not runs and args["outcome"] == "completed":
            fail("runs_required", "A successful research outcome requires at least one accepted run.")
        if args["outcome"] == "completed" and not any(r["status"] == "complete" for r in runs):
            fail("accepted_run_required", "A successful research outcome requires accepted run artifacts.")
    else:
        if any(e["status"] != "complete" for e in state.get("experiments", {}).values()):
            fail("experiments_incomplete", "Accept the outcome and analysis of every experiment before closing the task.")
        if args["outcome"] == "completed":
            integration = state["integration"]
            if state.get("integration_required", True):
                if integration.get("status") != "complete":
                    fail("integration_required", "Task success requires the integration included at enrollment.")
                rev = {"commit": integration["head"], "tree": integration.get("source_tree") or git(state["project"]["path"], "rev-parse", integration["head"] + "^{tree}"), "clean": True}
                if not state.get("cleaned"):
                    rev = revision(state)
                all_current(state, rev)
                cleanup_integration_proof(state, rev["commit"])
            else:
                current_revision = revision(state)
                all_current(state, current_revision)
                if current_revision["tree"] != git(state["project"]["path"], "rev-parse", "HEAD^{tree}"):
                    fail("unpublished_changes", "A task that excludes integration cannot close successfully with unpublished code changes.")
    scope.update(status="complete", closure={"id": uuid.uuid4().hex, "outcome": args["outcome"], "notes": args["notes"],
                 "evidence": args["evidence"], "actor": args["actor"], "time": now(), "generation": scope["generation"]})
    return {"experiment" if experiment_id else "task_lifecycle": scope}

def reopen_scope(args, state, experiment_id=None):
    require_coordinator(args, state)
    scope = get_experiment(state, experiment_id) if experiment_id else task_lifecycle(state)
    if scope["status"] != "complete":
        fail("invalid_transition", "Only a closed aggregate scope can be reopened.")
    scope.setdefault("history", []).append({"closure": scope.pop("closure"), "reopened_by": args["actor"], "reason": args["reason"], "time": now()})
    scope.update(status="open", generation=scope["generation"] + 1)
    return {"experiment" if experiment_id else "task_lifecycle": scope}

def accept_run(args, state):
    require_coordinator(args, state)
    current = get_run(state, args["run_id"])
    if current["status"] not in ("awaiting_artifacts", "complete"):
        fail("run_execution_unknown", "Accept artifacts only after a recorded successful workload exit.")
    if not current.get("execution") or current["execution"]["returncode"] != 0 or not current.get("start_validated"):
        fail("run_execution_unknown", "Successful validated execution must be recorded before accepting artifacts.")
    if not current.get("artifacts"):
        fail("artifact_acceptance_required", "Declared output artifacts and coordinator notes are required.")
    code = Path(current["code"])
    if manifest(code) != current["manifest"]:
        fail("snapshot_changed", "The frozen code changed during execution.")
    accepted = {}
    for name in current["artifacts"]:
        artifact = Path(current["directory"]) / str(safe_relative(name))
        no_symlinks(artifact, Path(current["directory"]))
        if not artifact.is_file() or within(artifact, code):
            fail("artifact_missing", "A declared artifact is missing or is an input code file.")
        accepted[name] = sha_file(artifact)
    current.update(status="complete", artifact_acceptance={"actor": args["actor"], "notes": args["artifact_notes"], "sha256": accepted, "time": now()})
    return {"run": current}

def prepare_run_staged(args, root, store):
    path = task_dir(store, args["task_id"])
    with lifecycle_lock(store), lock(path / "write.lock"):
        state, previous = load_events(path)
        if state["version"] != args["expected_version"]:
            fail("revision_conflict", "The task changed; reread status before preparation.")
        require_task_open(state)
        require_approved(state)
        require_coordinator(args, state)
        frozen_intent = {key: args.get(key) for key in ('argv', 'artifacts', 'environment_id', 'lockfiles', 'output_dir', 'dependency_declaration')}
        frozen_intent.update(commit=state.get('integration', {}).get('commit'), design_digest=state['design']['digest'])
        current = state["runs"].get(args["run_id"])
        if current and current.get('preparation_intent') and current['preparation_intent'] != frozen_intent:
            fail('preparation_changed', 'Prepared inputs are immutable; use a new run identity.')
        if current:
            if current["status"] not in ("planned", "preparing"):
                fail("already_exists", "Run identifiers cannot be reused.")
            association = run_association({**current, **args}, state)
            if any(association[key] != current.get(key) for key in association):
                fail("planned_run_changed", "A planned run's frozen intent cannot be replaced; create a new run.")
            validate_resource_reference(store, state, association)
            current["status"] = "preparing"
        else:
            plan_run(args, state, store, "preparing")
        state['runs'][args['run_id']]['preparation_intent'] = frozen_intent
        state['runs'][args['run_id']].setdefault('preparation_token', uuid.uuid4().hex)
        commit_event(path, state, previous, "run-prepare-intent", args["actor"])
    with lock(path / "write.lock"):
        state, previous = load_events(path)
        require_task_open(state)
        if get_run(state, args["run_id"])["status"] != "preparing":
            fail("preparation_changed", "The preparation reservation changed before its snapshot was created.")
        result = prepare_run(args, state, root)
        commit_event(path, state, previous, "run-prepare", args["actor"])
        return {"ok": True, "state": state, "summary": summary(state), **result}

def prepare_run(args, state, root):
    require_approved(state)
    integration = state["integration"]
    if integration.get("status") != "complete":
        fail("integration_required", "An explicitly integrated task revision is required before experiment snapshots.")
    check_identity(state)
    verified = integration.get("verification", {})
    if not verified.get("passed") or verified.get("commit") != integration["commit"] or verified.get("design_digest") != state["design"]["digest"]:
        fail("integration_verification_required", "The integrated commit requires actual successful integration-verify evidence.")
    commit = integration["commit"]
    if run(["git", "-C", state["project"]["path"], "merge-base", "--is-ancestor", commit, "HEAD"])["returncode"] != 0:
        fail("integration_changed", "The integrated commit is no longer present in the registered base branch.")
    run_id = args["run_id"]
    planned = state["runs"].get(run_id)
    if planned and planned["status"] not in ("planned", "preparing"):
        fail("already_exists", "Run identifiers cannot be reused.")
    association = run_association({**(planned or {}), **args}, state)
    if planned and any(association[key] != planned.get(key) for key in association):
        fail("planned_run_changed", "A planned run's goal, lineage, configuration, resources and reservation cannot be replaced; create a new run.")
    default_output = (Path(get_experiment(state, association["experiment_id"])["directory"]) / "runs" if association["experiment_id"] else root / ".experiments" / "verification" / state["task_id"])
    output = Path(args.get("output_dir", str(default_output))).expanduser()
    if not output.is_absolute():
        fail("invalid_path", "Run output must be absolute.")
    no_symlinks(output, Path(output.anchor))
    output.mkdir(parents=True, exist_ok=True)
    output = existing_dir(str(output))
    if association["experiment_id"]:
        expected = Path(get_experiment(state, association["experiment_id"])["directory"]) / "runs"
        if output != expected:
            fail("unsafe_path", "Research run output must be the experiment's recorded recorded runs directory.")
        no_symlinks(output, Path(output.anchor))
    else:
        if not within(output, root) or within(output, root / ".task-workflow"):
            fail("unsafe_path", "Task verification output must be inside its registered root and outside workflow storage.")
        no_symlinks(output, root)
    destination = output / run_id
    if destination.exists() or destination.is_symlink():
        no_symlinks(destination, output)
        snapshot_path = destination / "snapshot.json"
        if planned and planned['status'] == 'preparing' and snapshot_path.is_file():
            recovered = read_json(snapshot_path)
            if (recovered.get('run_id') != run_id or recovered.get('commit') != commit
                    or recovered.get('design_digest') != state['design']['digest']
                    or recovered.get('argv') != args['argv'] or recovered.get('artifacts') != args['artifacts']
                    or recovered.get('environment_id') != args['environment_id']
                    or recovered.get('directory') != str(destination)
                    or recovered.get('code') != str(destination / 'code')
                    or set(recovered.get('lockfiles', {})) != set(args['lockfiles'])
                    or any(recovered.get(key) != value for key, value in association.items())):
                fail('preparation_changed', 'The preserved preparation does not match this frozen intent.')
            check_run(state, recovered)
            state['runs'][run_id] = recovered
            return {'run': recovered, 'recovered': True}
        marker = destination / '.preparation-intent.json'
        if not planned or not marker.is_file() or read_json(marker).get('token') != planned.get('preparation_token'):
            fail("already_exists", "The experiment destination has no matching ownership proof; preserve its files for inspection.")
    env_id = args["environment_id"]
    if env_id not in state["environment_registry"]:
        fail("environment_not_registered", "Reference an environment explicitly registered at task enrollment.")
    environment = env_fingerprint(state["environment_registry"][env_id], (state["project"]["path"], state["worktree"]["path"]))
    for argument in args["argv"]:
        if any(checkout in argument for checkout in (state["project"]["path"], state["worktree"]["path"])):
            fail("development_reference", "Experiment argv cannot reference a mutable development checkout.")
    if not args["lockfiles"]:
        fail("lockfile_required", "At least one committed dependency lockfile is required.")
    for name in args["lockfiles"] + args["artifacts"]:
        safe_relative(name)
    archive_preflight(state["project"]["path"], commit)
    # Archive only Git objects. It never copies .git, environments, caches or
    # mutable working tree files, and never hard-links experiment code.
    files = {}
    modes = {}
    total = 0
    with tempfile.TemporaryFile() as archive:
        try:
            with tempfile.TemporaryFile() as errors:
                process = subprocess.Popen(["git", "-C", state["project"]["path"], "archive", "--format=tar", commit], stdout=subprocess.PIPE, stderr=errors)
                try:
                    while True:
                        chunk = process.stdout.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > 256 * 1024 * 1024:
                            process.kill()
                            process.wait()
                            fail("snapshot_too_large", "Git archive exceeds the 256 MiB export limit.")
                        archive.write(chunk)
                    if process.wait(timeout=120) != 0:
                        fail("archive_failed", "Git could not export the integrated commit.")
                finally:
                    process.stdout.close()
                    if process.poll() is None:
                        process.kill()
                        process.wait()
        except (subprocess.SubprocessError, OSError):
            fail("archive_failed", "Git could not export the integrated commit.")
        archive.seek(0)
        total = 0
        with tarfile.open(fileobj=archive, mode="r:") as tar:
            for member in tar.getmembers():
                relative = safe_relative(member.name.rstrip("/"))
                if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                    fail("unsafe_snapshot", "Symlinks, hard links and special archive entries are prohibited.")
                if member.isdir() or excluded(relative.parts):
                    continue
                total += member.size
                if member.size > 64 * 1024 * 1024 or total > 256 * 1024 * 1024:
                    fail("snapshot_too_large", "Snapshot export exceeds bounded limits.")
                files[str(relative)] = tar.extractfile(member).read()
                modes[str(relative)] = member.mode & 0o777
    check_dependencies(files, args.get("dependency_declaration", "reason"))
    for name in args["lockfiles"]:
        if name not in files:
            fail("lockfile_missing", "A declared dependency lockfile is absent from the exported commit.")
    marker = destination / '.preparation-intent.json'
    ownership = {'token': planned['preparation_token'], 'intent': planned['preparation_intent'],
                 'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    if destination.exists():
        if read_json(marker) != ownership:
            fail('preparation_changed', 'The preserved partial snapshot differs from its owned preparation intent.')
    else:
        destination.mkdir()
        atomic_json(marker, ownership)
    code = destination / 'code'
    allowed = {'.preparation-intent.json', 'code'}
    for name in files:
        relative = PurePosixPath('code') / name
        allowed.add(str(relative))
        allowed.update(str(parent) for parent in relative.parents if str(parent) != '.')
    for entry in destination.rglob('*'):
        relative = str(entry.relative_to(destination))
        if entry.is_symlink() or relative not in allowed or not (entry.is_file() or entry.is_dir()):
            fail('preparation_changed', 'Unexpected partial snapshot material must be preserved for inspection.')
        if entry.is_file() and relative != '.preparation-intent.json':
            data = files[str(PurePosixPath(relative).relative_to('code'))]
            if not data.startswith(entry.read_bytes()):
                fail('preparation_changed', 'Owned partial code differs from the immutable source; preserve it.')
    code.mkdir(exist_ok=True)
    for name, data in files.items():
        file_path = code / name
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if file_path.exists():
            file_path.chmod(0o600)
        with open(file_path, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        file_path.chmod((modes[name] & 0o111) | 0o444)
    code_manifest = manifest(code)
    run_state = {**association, "run_id": run_id, "status": "prepared", "commit": commit,
                 "design_digest": state["design"]["digest"], "frozen_approval": copy.deepcopy(state["approval"]),
                 "independent_snapshot": True,
                 "directory": str(destination), "code": str(code),
                 "manifest": code_manifest, "manifest_digest": digest(code_manifest),
                 "lockfiles": {name: code_manifest[name] for name in args["lockfiles"]},
                 "environment_id": env_id, "environment": environment, "argv": args["argv"],
                 "artifacts": args["artifacts"], "token": "tw-" + uuid.uuid4().hex, "created": now()}
    run_state["runtime"] = pin_runtime(state)
    atomic_json(destination / "snapshot.json", run_state)
    state["runs"][run_id] = run_state
    if association["experiment_id"] and run_id not in get_experiment(state, association["experiment_id"])["run_ids"]:
        get_experiment(state, association["experiment_id"])["run_ids"].append(run_id)
    return {"run": run_state}

def get_run(state, run_id):
    if run_id not in state["runs"]:
        fail("not_found", "The experiment run does not exist.")
    return state["runs"][run_id]

def environment_identity(value):
    return {key: item for key, item in value.items() if key != "logical_path"}

def check_run(state, experiment):
    root = Path(state["root"])
    code = Path(experiment["code"])
    if experiment.get("experiment_id"):
        anchor = Path(get_experiment(state, experiment["experiment_id"])["directory"])
        no_symlinks(anchor, Path(anchor.anchor))
        no_symlinks(code, anchor)
    else:
        no_symlinks(code, root)
    if manifest(code) != experiment["manifest"]:
        fail("snapshot_changed", "The experiment code differs from its recorded manifest.")
    if environment_identity(env_fingerprint(experiment["environment"]["path"], (state["project"]["path"], state["worktree"]["path"]))) != environment_identity(experiment["environment"]):
        fail("environment_changed", "The registered environment differs from its prepared inventory.")
    if experiment.get("frozen_approval", {}).get("digest") != experiment["design_digest"]:
        fail("approval_required", "The frozen experiment has no approval for its own design.")
    if experiment.get("runtime"):
        check_runtime(state, experiment)


def check_runtime(state, current):
    runtime = current['runtime']
    location = Path(runtime['directory'])
    expected = Path(state['root']) / '.task-workflow/runtimes' / runtime['digest']
    if location != expected or runtime.get('digest') != digest(runtime.get('files')):
        fail('runtime_changed', 'The frozen execution runtime identity changed.')
    for name, expected_hash in runtime['files'].items():
        target = location / str(safe_relative(name))
        no_symlinks(target, Path(state['root']))
        if not target.is_file() or sha_file(target) != expected_hash:
            fail('runtime_changed', 'The frozen execution runtime bytes changed before execution.')
    return runtime


def require_execution_protocol(state, current):
    runtime = current.get('runtime')
    message = ('This frozen runtime uses a legacy execution protocol. Preserve it and create a new Run '
               'identity with the same approved inputs before execution or dispatch.')
    if not runtime:
        fail('legacy_runtime', message)
    runtime = check_runtime(state, current)
    if runtime.get('execution_protocol') != EXECUTION_PROTOCOL or set(runtime['files']) != {'workflow.py', 'runner.py'}:
        fail('legacy_runtime', message)
    for name in runtime['files']:
        content = (Path(runtime['directory']) / name).read_bytes()
        if not re.search(rb'(?m)^EXECUTION_PROTOCOL = ' + str(EXECUTION_PROTOCOL).encode() + rb'$', content):
            fail('legacy_runtime', message)


def pin_runtime(state):
    source = Path(__file__).resolve().parent
    files = {name: (source / name).read_bytes() for name in ("workflow.py", "runner.py")}
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
    runtime_digest = digest(hashes)
    store = Path(state["root"]) / ".task-workflow"
    container = store / "runtimes"
    no_symlinks(container, store)
    container.mkdir(exist_ok=True)
    target = container / runtime_digest
    no_symlinks(target, store)
    if not target.exists():
        with tempfile.TemporaryDirectory(prefix=".runtime-", dir=str(container)) as temporary:
            staging = Path(temporary)
            for name, content in files.items():
                with open(staging / name, "xb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                (staging / name).chmod(0o444)
            # Concurrent tasks can publish identical content. Validate the complete
            # winning directory below instead of overwriting or failing its loser.
            try:
                os.rename(staging, target)
            except OSError as error:
                if error.errno not in (errno.EEXIST, errno.ENOTEMPTY) or not target.is_dir():
                    raise
            sync_dir(container)
    if not target.is_dir() or {entry.name for entry in target.iterdir()} != set(files):
        fail("runtime_changed", "The shared frozen runtime contains unexpected material; preserve it for inspection.")
    for name in files:
        no_symlinks(target / name, store)
        if not (target / name).is_file() or sha_file(target / name) != hashes[name]:
            fail("runtime_changed", "A shared frozen runtime differs from its recorded content identity; it cannot be overwritten.")
    return {"protocol_version": 1, "execution_protocol": EXECUTION_PROTOCOL, "digest": runtime_digest, "directory": str(target), "files": hashes}

def cleanup_integration_proof(state, head):
    integration = state["integration"]
    project = state["project"]["path"]
    if head != integration.get("head"):
        fail("unmerged_commits", "The task head changed since its recorded integration.")
    verified = integration.get("verification", {})
    if not verified.get("passed") or verified.get("commit") != integration.get("commit") or verified.get("design_digest") != (state.get("design") or {}).get("digest"):
        fail("integration_verification_required", "Cleanup requires successful verification of the recorded integrated commit.")
    if run(["git", "-C", project, "merge-base", "--is-ancestor", integration["commit"], "HEAD"])["returncode"] != 0:
        fail("integration_changed", "The recorded integrated commit is no longer reachable from base.")
    if integration.get("method") == "squash":
        if git(project, "rev-parse", head + "^{tree}") != integration["source_tree"] or not integration_commit_matches(project, integration, integration["commit"]):
            fail("integration_changed", "The squash result does not match its recorded source, tree and sole parent.")
    elif run(["git", "-C", project, "merge-base", "--is-ancestor", head, integration["commit"]])["returncode"] != 0:
        fail("unmerged_commits", "The legacy integration does not contain the task head.")

def cleanup_task_references(state, store):
    paths = set((store / "tasks").iterdir())
    target = Path(state["worktree"]["path"])
    own_path = task_dir(store, state["task_id"])
    for other in paths:
        if other == own_path:
            continue
        other_state, _ = load_events(other)
        if other_state["worktree"]["path"] == state["worktree"]["path"] and not other_state.get("cleaned"):
            fail("active_reference", "Another enrolled task still references this worktree.")
        references = list(other_state["environment_registry"].values())
        for experiment in other_state["runs"].values():
            references += [experiment[key] for key in ("code", "directory") if key in experiment]
            if experiment.get("environment"):
                references.append(experiment["environment"]["path"])
        if any(within(Path(reference).absolute(), target) or within(Path(reference).resolve(), target) for reference in references):
            fail("active_reference", "Another enrolled task references an environment, snapshot or run directory in this worktree.")

def cleanup(args, state, store):
    if not state["owned_worktree"] or state["project"]["path"] == state["worktree"]["path"]:
        fail("not_owned", "Only a distinct explicitly owned task worktree can be removed.")
    if state["integration"].get("status") != "complete":
        fail("integration_required", "Worktree cleanup requires a completed integration.")
    target = Path(state["worktree"]["path"])
    if state.get("cleaned") and not target.exists():
        return {"already_cleaned": True}
    check_identity(state)
    cleanup_task_references(state, store)
    for experiment in state["runs"].values():
        if experiment["status"] not in ("complete", "failed", "cancelled"):
            if experiment.get("independent_snapshot") is not True or any(within(Path(experiment[key]).resolve(), target) for key in ("code", "directory")) or within(Path(experiment["environment"]["path"]).resolve(), target):
                fail("active_reference", "An unfinished run still depends on this worktree.")
    safe_env_links = []
    candidates = list(state["environment_registry"].values()) + [r["environment"].get("logical_path", r["environment"]["path"]) for r in state["runs"].values() if r.get("environment")]
    for logical in candidates:
        link = Path(logical)
        if within(link.resolve(), target):
            fail("active_reference", "A registered environment is stored inside the development worktree.")
        if within(link, target) and link.is_symlink() and link.resolve().is_dir() and not within(link.resolve(), target):
            relative = str(link.relative_to(target))
            if relative not in safe_env_links:
                safe_env_links.append(relative)
    dirty = git(target, "status", "--porcelain=v1", "--untracked-files=all", "--ignored")
    allowed_status = {prefix + name for name in safe_env_links for prefix in ("?? ", "!! ")}
    if any(line not in allowed_status for line in dirty.splitlines()):
        fail("unique_files", "Uncommitted, untracked or ignored unique files prevent safe cleanup.")
    head = git(target, "rev-parse", "HEAD")
    cleanup_integration_proof(state, head)
    if args.get("dry_run", True):
        return {"dry_run": True, "removable": str(target), "environment_links_only": safe_env_links}
    with lock(Path(state["project"]["common_dir"]) / "task-workflow-integration.lock"):
        check_identity(state)
        cleanup_task_references(state, store)
        cleanup_integration_proof(state, head)
        if git(target, "rev-parse", "HEAD") != head or git(target, "status", "--porcelain=v1", "--untracked-files=all", "--ignored") != dirty:
            fail("revision_conflict", "The worktree changed after cleanup checks.")
        for name in safe_env_links:
            link = target / name
            if link.is_symlink() and not within(link.resolve(), target):
                link.unlink()  # Remove only the checkout entrypoint, never its external environment.
            else:
                fail("revision_conflict", "An environment entrypoint changed during cleanup.")
        result = run(["git", "-C", state["project"]["path"], "worktree", "remove", "--", str(target)], timeout=120)
        if result["returncode"] != 0:
            fail("cleanup_failed", "Git refused safe worktree removal; files were not force removed.")
    state["cleaned"] = {"time": now(), "actor": args["actor"]}
    return {"removed": str(target)}

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=sorted(COMMANDS))
    parser.add_argument("--root", help="Project root; defaults to the current registered Git project")
    parser.add_argument("--json-args", default="{}", help="JSON argument object, or '-' to read stdin")
    options = parser.parse_args(argv)
    try:
        raw = sys.stdin.read(MAX_JSON + 1) if options.json_args == "-" else options.json_args
        if len(raw.encode()) > MAX_JSON:
            fail("invalid_arguments", "JSON arguments exceed the size limit.")
        args = json.loads(raw)
        if not isinstance(args, dict) or ("root" in args and args["root"] != options.root):
            fail("invalid_arguments", "JSON must be an object with no conflicting root.")
        args["root"] = options.root or str(find_registered_root(os.getcwd()) or Path(git(os.getcwd(), "rev-parse", "--show-toplevel")))
        print(json.dumps(dispatch(options.operation, args), ensure_ascii=False))
        return 0
    except WorkflowError as error:
        print(json.dumps({"ok": False, "error": {"code": error.code, "message": error.message}}))
        return 2
    except (ValueError, OSError, KeyError, TypeError):
        print(json.dumps({"ok": False, "error": {"code": "invalid_or_unavailable", "message": "Input or local state is invalid, or a required resource is unavailable."}}))
        return 2

@contextlib.contextmanager
def lifecycle_lock(store):
    with lock(store / 'lifecycle.lock'):
        yield

def require_portable_state(state):
    if state.get('workflow_format') != PORTABLE_FORMAT:
        fail('legacy_read_only', 'Legacy records remain readable; enroll a new project task for this workflow.')

def bootstrap_project(project):
    """Audit an atomic repository-local exclude update before runtime files exist."""
    root = Path(project['path'])
    names = ('.task-workflow', '.worktrees', '.experiments')
    for name in names:
        no_symlinks(root / name, root)
        if git(root, 'ls-files', '--', name):
            fail('managed_path_collision', 'A managed runtime path contains tracked project files.')
    common = Path(project['common_dir'])
    target = common / 'info/exclude'
    no_symlinks(target, common)
    target.parent.mkdir(exist_ok=True)
    block = b'\n# task-workflow managed runtime paths\n/.task-workflow/\n/.worktrees/\n/.experiments/\n# end task-workflow managed runtime paths\n'
    with lock(common / 'task-workflow-exclude.lock'):
        before = target.read_bytes() if target.exists() else b''
        audit_dir = common / 'task-workflow-bootstrap'
        no_symlinks(audit_dir, common)
        owned = False
        if before.count(block) == 1 and audit_dir.is_dir():
            owned = any(read_json(entry).get('status') == 'complete' and read_json(entry).get('added_block') == block.decode()
                        for entry in audit_dir.glob('*.json'))
        if not owned:
            for name in names:
                candidate = root / name
                if candidate.exists() and (not candidate.is_dir() or any(candidate.iterdir())):
                    fail('managed_path_unowned', 'Existing unowned runtime-path contents must remain visible; preserve and explicitly reconcile them before enrollment.')
        if b'# task-workflow managed runtime paths' in before:
            if before.count(block) != 1:
                fail('exclude_conflict', 'The managed exclusion block changed; preserve it for explicit reconciliation.')
            return {'path': str(target), 'sha256': hashlib.sha256(before).hexdigest(), 'reused': True}
        if target.exists() and (not target.is_file() or len(before) > MAX_JSON):
            fail('exclude_conflict', 'The repository exclude file is unsafe or too large.')
        after = before + block
        audit_dir = common / 'task-workflow-bootstrap'
        no_symlinks(audit_dir, common)
        audit_dir.mkdir(exist_ok=True)
        audit = audit_dir / (uuid.uuid4().hex + '.json')
        record = {'status': 'intent', 'path': str(target), 'before_sha256': hashlib.sha256(before).hexdigest(),
                  'after_sha256': hashlib.sha256(after).hexdigest(), 'added_block': block.decode(), 'time': now()}
        atomic_json(audit, record)
        descriptor, temporary = tempfile.mkstemp(prefix='.exclude-', dir=str(target.parent))
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(after)
                stream.flush()
                os.fsync(stream.fileno())
            if (target.read_bytes() if target.exists() else b'') != before:
                fail('exclude_conflict', 'Repository exclusions changed during the audited update.')
            os.replace(temporary, target)
            sync_dir(target.parent)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        record['status'] = 'complete'
        atomic_json(audit, record)
        return {'path': str(target), 'sha256': record['after_sha256'], 'audit': str(audit), 'reused': False}

def register_root(root, state):
    store = root / '.task-workflow'
    path = store / 'registry.json'
    data = read_json(path) if path.exists() else {'format': VERSION, 'root': str(root), 'project': state['project'], 'tasks': []}
    if data.get('root') != str(root) or data.get('project', {}).get('common_dir') != state['project']['common_dir']:
        fail('project_mismatch', 'This state root belongs to a different Git project.')
    data['tasks'] = sorted(set(data['tasks'] + [state['task_id']]))
    atomic_json(path, data)

def find_registered_root(cwd):
    """Discover only the verified current Git project and its registered checkouts."""
    path = Path(cwd).expanduser().resolve()
    if not path.is_dir():
        path = path.parent
    result = run(['git', '-C', str(path), 'rev-parse', '--path-format=absolute', '--git-common-dir'])
    if result['returncode'] != 0:
        return None
    common = Path(result['stdout'].strip()).resolve()
    candidates = []
    listing = run(['git', '-C', str(path), 'worktree', 'list', '--porcelain', '-z'])
    if listing['returncode'] != 0:
        return None
    for record in listing['stdout'].split('\0\0'):
        fields = dict(field.split(' ', 1) if ' ' in field else (field, '') for field in record.split('\0') if field)
        if fields.get('worktree'):
            candidates.append(Path(fields['worktree']))
    binding = common / 'task-workflow-root.json'
    if binding.exists():
        value = read_json(binding)
        if value.get('common_dir') == str(common):
            candidates.insert(0, Path(value['root']))
    for candidate in candidates:
        registry = candidate / '.task-workflow/registry.json'
        no_symlinks(registry, candidate)
        if not registry.is_file() or registry.is_symlink():
            continue
        data = read_json(registry)
        if data.get('root') == str(candidate) and data.get('project', {}).get('common_dir') == str(common):
            project = data['project']
            if git_identity(project['path']) == project:
                return candidate
    return None

def registered_task_trees(state):
    store = Path(state['root']) / '.task-workflow'
    result = []
    for path in (store / 'tasks').iterdir():
        if not path.is_dir() or path.is_symlink():
            continue
        candidate, _ = load_events(path)
        tree = candidate['worktree']
        if candidate['project']['common_dir'] == state['project']['common_dir'] and tree['path'] != state['project']['path']:
            result.append(tree)
    return result

def init(args, root, store):
    project = git_identity(args['project'])
    worktree = git_identity(args.get('worktree', args['project']))
    if worktree['common_dir'] != project['common_dir']:
        fail('git_identity', 'Project and worktree must share a Git repository.')
    expected = Path(project['path']) / '.worktrees' / args['task_id']
    if worktree['path'] != project['path'] and Path(worktree['path']) != expected:
        fail('worktree_association', 'A task checkout must use project/.worktrees/task-id.')
    if root != Path(project['path']) and (within(root, Path(project['path'])) or within(root, Path(worktree['path']))):
        fail('state_inside_checkout', 'Use the project root or an external state root.')
    if args.get('owned_worktree') and worktree['path'] == project['path']:
        fail('invalid_ownership', 'The base checkout cannot be declared an owned task worktree.')
    environments = {}
    for name, value in args.get('environment_registry', {}).items():
        identifier(name)
        logical = Path(value).expanduser()
        if not logical.is_absolute() or not logical.is_dir():
            fail('invalid_environment', 'Environment references must be existing absolute directories.')
        environments[name] = str(logical)
    with lock(Path(project['common_dir']) / 'task-workflow-integration.lock'), lock(store / 'registry.lock'):
        binding_path = Path(project['common_dir']) / 'task-workflow-root.json'
        if binding_path.exists() and read_json(binding_path) != {'root': str(root), 'common_dir': project['common_dir']}:
            fail('project_mismatch', 'This project already has a different authoritative state root.')
        (store / 'tasks').mkdir(exist_ok=True)
        path = task_dir(store, args['task_id'])
        if path.exists():
            fail('already_exists', 'Task identifiers cannot be reused.')
        state = {'format': VERSION, 'workflow_format': PORTABLE_FORMAT, 'task_id': args['task_id'], 'title': args['title'],
            'root': str(root), 'version': 0, 'created': now(), 'coordinator': args.get('coordinator', args['actor']),
            'session_id': args.get('session_id'), 'enrollment': {'actor': args['actor'], 'authorization_source': args['authorization_source']},
            'project': project, 'worktree': worktree, 'owned_worktree': args.get('owned_worktree', False),
            'environment_registry': environments, 'managed_paths': args['_managed_paths'], 'design': None, 'approval': None,
            'integration_required': args.get('integration_required', True), 'items': {'overall': make_item('Overall verification', True)},
            'decisions': [], 'runs': {}, 'experiments': {}, 'integration': {}, 'task_lifecycle': {'status': 'open', 'generation': 1, 'history': []}}
        text_value(state['coordinator'])
        if state['session_id'] is not None:
            text_value(state['session_id'])
        path.mkdir()
        (path / 'events').mkdir()
        atomic_json(binding_path, {'root': str(root), 'common_dir': project['common_dir']})
        register_root(root, state)
        commit_event(path, state, None, 'init', args['actor'])
        return {'ok': True, 'state': state, 'summary': summary(state)}

def create_experiment(args, state, store):
    require_coordinator(args, state)
    require_approved(state)
    identifier(args['experiment_id'])
    base = absolute_destination(args.get('experiment_root', str(Path(state['project']['path']) / '.experiments')))
    destination = base / args['experiment_id']
    existing = state['experiments'].get(args['experiment_id'])
    if existing:
        if existing['goal'] != args['goal'] or Path(existing['directory']) != destination or existing.get('storage_ready'):
            fail('already_exists', 'Experiment identifiers and research goals cannot be replaced.')
        return {'experiment': existing}
    for task_path in (store / 'tasks').iterdir():
        other, _ = load_events(task_path)
        if any(exp['directory'] == str(destination) for exp in other.get('experiments', {}).values()):
            fail('experiment_collision', 'Another task already reserves this experiment directory.')
    if destination.exists():
        fail('already_exists', 'The experiment directory already exists; preserve it.')
    state['experiments'][args['experiment_id']] = {'experiment_id': args['experiment_id'], 'goal': args['goal'],
        'directory': str(destination), 'status': 'open', 'generation': 1, 'history': [], 'run_ids': [], 'storage_ready': False,
        'created': now(), 'actor': args['actor']}
    return {'experiment': state['experiments'][args['experiment_id']]}

def run_association(args, state):
    experiment_id = args.get('experiment_id')
    purpose = args.get('purpose', 'research' if experiment_id else 'verification')
    if purpose not in ('research', 'verification') or (purpose == 'research' and not experiment_id):
        fail('experiment_required', 'Research runs require an explicit experiment.')
    if experiment_id and get_experiment(state, experiment_id)['status'] != 'open':
        fail('experiment_closed', 'Reopen the experiment before planning another run.')
    parent = args.get('parent_run_id')
    if parent and (parent == args['run_id'] or get_run(state, parent).get('experiment_id') != experiment_id):
        fail('invalid_lineage', 'A parent run must be a different run in the same experiment or verification scope.')
    if args.get('checkpoint_reference') and not parent:
        fail('invalid_lineage', 'A checkpoint reference requires its parent run.')
    requirements = args.get('requirements', {})
    validate_capabilities(requirements)
    return {'experiment_id': experiment_id, 'purpose': purpose, 'parent_run_id': parent,
        'checkpoint_reference': args.get('checkpoint_reference'), 'config': args.get('config', {}),
        'resource_id': args.get('resource_id'), 'requirements': copy.deepcopy(requirements)}

def validate_capabilities(values):
    if not isinstance(values, dict) or len(values) > 100:
        fail('invalid_capabilities', 'Capabilities must be a bounded object of named scalar values.')
    for key, value in values.items():
        identifier(key)
        if type(value) not in (str, int, bool) or (type(value) is int and value < 0) or (isinstance(value, str) and (not value or len(value) > 1000)):
            fail('invalid_capabilities', 'Capability values must be nonnegative integers, booleans or nonempty strings.')

def resource_dir(store, resource_id):
    target = store / 'resources' / identifier(resource_id)
    no_symlinks(target, store)
    return target

def read_resource(store, resource_id):
    return load_events(resource_dir(store, resource_id))

def observation_current(resource):
    try:
        return dt.datetime.now(dt.timezone.utc) <= dt.datetime.fromisoformat(resource['observation']['valid_until'])
    except (KeyError, TypeError, ValueError):
        return False

def resource_owner(resource, actor):
    if resource['owner'] != actor or resource['owner_uid'] != os.getuid():
        fail('resource_owner', 'Only the recorded resource owner can use or release this resource.')

def resource_associations(store, resource_id):
    result = []
    for task_path in sorted((store / 'tasks').iterdir()):
        if not task_path.is_dir() or task_path.is_symlink():
            fail('resource_scope_unknown', 'An enrolled task is unavailable; resource references cannot be resolved.')
        state, _ = load_events(task_path)
        for run_id, current in state['runs'].items():
            if current.get('resource_id') == resource_id:
                result.append((state, run_id, current))
    return result

def resource_projection(store, resource):
    associated = resource_associations(store, resource['resource_id'])
    owner_state, _ = load_events(task_dir(store, resource['owner_task_id']))
    states = {state['task_id']: state for state, _, _ in associated}
    states[owner_state['task_id']] = owner_state
    live = any(current['status'] not in TERMINAL_RUNS for _, _, current in associated)
    closed = all(state.get('task_lifecycle', {}).get('status') == 'complete' and state['task_lifecycle'].get('closure')
                 and all(exp.get('status') == 'complete' for exp in state.get('experiments', {}).values())
                 and all(current['status'] in TERMINAL_RUNS for current in state['runs'].values()) for state in states.values())
    refs = [{'task_id': state['task_id'], 'run_id': run_id, 'status': current['status']} for state, run_id, current in associated]
    key = digest({'resource_id': resource['resource_id'], 'resource_version': resource['version'],
                  'tasks': {name: {'version': value['version'], 'closure': value.get('task_lifecycle')} for name, value in states.items()}, 'refs': refs})
    evidence_valid = all(successful_scope_proof(state) for state in states.values())
    released = resource.get('release', {}).get('status') == 'released'
    uncertain = resource.get('release', {}).get('status') in ('releasing', 'unknown')
    current = observation_current(resource)
    eligible = bool(closed and evidence_valid and not live and current and resource['observed_state'] == 'available' and not released and not uncertain)
    reason = ('released' if released else 'release_unknown' if uncertain else 'live_references' if live else
              'aggregate_scope_open' if not closed else 'accepted_evidence_changed' if not evidence_valid else 'observation_required' if not current or resource['observed_state'] != 'available' else 'eligible')
    derived = ('released' if released else 'unknown' if uncertain else 'in_use' if live else 'releasable' if eligible else
               'available' if current and resource['observed_state'] == 'available' else 'unknown')
    return {**copy.deepcopy(resource), 'derived_state': derived, 'observed_at': resource['observation']['time'],
            'eligibility': {'eligible': eligible, 'reason': reason, 'key': key}, 'run_refs': refs}

def resource_status(root, resource_id):
    _, store = store_dir(str(root))
    resource, _ = read_resource(store, resource_id)
    return {'ok': True, 'resource': resource_projection(store, resource)}

def validate_resource_reference(store, state, association, require_available=False):
    resource_id = association.get('resource_id')
    if not resource_id:
        if association.get('requirements'):
            fail('resource_required', 'Declared resource requirements need an explicit resource reference.')
        return
    resource, _ = read_resource(store, resource_id)
    resource_owner(resource, state['coordinator'])
    if resource.get('release') or resource['observed_state'] == 'released':
        fail('resource_unavailable', 'A release intent seals admission; reconcile it instead of reusing the resource.')
    if require_available and (resource['observed_state'] != 'available' or not observation_current(resource)):
        fail('resource_unavailable', 'A current available resource observation is required before reuse.')
    for key, needed in association.get('requirements', {}).items():
        offered = resource['capabilities'].get(key)
        if (type(needed) is int and (type(offered) is not int or offered < needed)) or (type(needed) is not int and (type(offered) is not type(needed) or offered != needed)):
            fail('resource_mismatch', 'The observed resource capabilities do not meet this run requirement.')
    for other, run_id, current in resource_associations(store, resource_id):
        if other['task_id'] == state['task_id'] and run_id == association.get('run_id'):
            continue
        claimed_queue = (current['status'] == 'queued' and
                         (Path(current['directory']) / 'execution.claim').exists())
        if require_available and (current['status'] in ('running', 'unknown') or claimed_queue):
            fail('resource_in_use', 'Resolve the active or uncertain execution before reusing this resource.')

def register_resource(args, state, store):
    require_coordinator(args, state)
    path = resource_dir(store, args['resource_id'])
    if path.exists():
        fail('already_exists', 'Resource identifiers cannot be reused.')
    validate_capabilities(args['capabilities'])
    if args['provided_by'] not in ('user', 'agent') or not args['ownership_evidence'] or not args['evidence']:
        fail('resource_evidence_required', 'Record the resource source, ownership evidence and availability evidence.')
    for candidate in (store / 'resources').iterdir() if (store / 'resources').exists() else []:
        existing, _ = load_events(candidate)
        if existing['handle'] == args['handle']:
            fail('resource_collision', 'This opaque handle already has a project resource record.')
    observation = make_observation(args)
    resource = {'resource_id': args['resource_id'], 'handle': args['handle'], 'owner': args['actor'],
        'owner_uid': os.getuid(), 'owner_task_id': state['task_id'], 'provided_by': args['provided_by'],
        'ownership_evidence': args['ownership_evidence'], 'can_release': args['can_release'],
        'permission_source': args['authorization_source'], 'capabilities': args['capabilities'],
        'observed_state': args['observed_state'], 'observation': observation, 'version': 0, 'root': state['root']}
    if resource['observed_state'] == 'released':
        fail('resource_evidence_required', 'Register an available, unavailable or unknown resource before recording release.')
    path.mkdir(parents=True)
    (path / 'events').mkdir()
    commit_event(path, resource, None, 'resource-register', args['actor'])
    return {'resource': resource_projection(store, resource)}

def make_observation(args):
    if args['observed_state'] not in ('available', 'unavailable', 'released', 'unknown') or not args['evidence']:
        fail('resource_evidence_required', 'A supported observed state and evidence references are required.')
    if not 1 <= args['valid_for_seconds'] <= 86400:
        fail('invalid_duration', 'Observation validity must be between one second and one day.')
    moment = dt.datetime.now(dt.timezone.utc)
    return {'time': moment.isoformat(), 'valid_until': (moment + dt.timedelta(seconds=args['valid_for_seconds'])).isoformat(),
            'evidence': args['evidence'], 'actor': args['actor']}

def observe_resource(args, state, store):
    resource, previous = read_resource(store, args['resource_id'])
    resource_owner(resource, args['actor'])
    if resource['owner_task_id'] != state['task_id']:
        fail('resource_owner', 'Use the resource owning task for this operation.')
    if resource['version'] != args['expected_resource_version']:
        fail('revision_conflict', 'The resource changed; reread its current version.')
    validate_capabilities(args['capabilities'])
    if resource.get('release', {}).get('status') == 'released':
        fail('resource_released', 'A released resource cannot be revived; register a new resource identity.')
    resource.update(observed_state=args['observed_state'], capabilities=args['capabilities'], observation=make_observation(args))
    commit_event(resource_dir(store, args['resource_id']), resource, previous, 'resource-observe', args['actor'])
    return {'resource': resource_projection(store, resource)}

def release_resource(args, root, store):
    """Record permission and intent before one explicit external release action."""
    path = task_dir(store, args['task_id'])
    resource_path = resource_dir(store, args['resource_id'])
    with lifecycle_lock(store), lock(path / 'write.lock'):
        state, _ = load_events(path)
        require_portable_state(state)
        if state['version'] != args['expected_version']:
            fail('revision_conflict', 'The task changed before the release decision.')
        require_coordinator(args, state)
        resource, previous = read_resource(store, args['resource_id'])
        resource_owner(resource, args['actor'])
        if resource['owner_task_id'] != state['task_id']:
            fail('resource_owner', 'Use the resource owning task for release.')
        if not resource['can_release']:
            fail('release_permission_required', 'The recorded owner has not granted permission to release this resource.')
        projection = resource_projection(store, resource)
        if args['expected_resource_version'] != resource['version'] or args['eligibility_key'] != projection['eligibility']['key']:
            fail('stale_resource_decision', 'Resource observations or aggregate references changed; inspect release eligibility again.')
        if resource.get('release') or not projection['eligibility']['eligible']:
            fail('release_denied', 'Release requires closed aggregate scopes and resolved run references without a prior release intent.')
        token = 'release-' + uuid.uuid4().hex
        resource['release'] = {'status': 'releasing', 'token': token, 'argv': args['argv'], 'actor': args['actor'],
            'authorization_source': text_value(args['authorization_source']), 'eligibility_key': args['eligibility_key'], 'time': now()}
        previous = commit_event(resource_path, resource, previous, 'resource-release-intent', args['actor'])
        command = list(args['argv'])
    result = run(command, cwd=str(root), timeout=args.get('timeout', 300))
    receipt = {'token': token, 'resource_id': args['resource_id'], 'argv_digest': digest(command), 'result': result, 'time': now()}
    atomic_json(resource_path / 'release-receipt.json', receipt)
    with lifecycle_lock(store):
        resource, previous = read_resource(store, args['resource_id'])
        if resource['release']['token'] != token:
            fail('release_identity', 'The release intent changed; preserve the external receipt.')
        resource['release'].update(status='unknown', action_receipt=receipt)
        commit_event(resource_path, resource, previous, 'resource-release-result', args['actor'])
        return {'ok': True, 'resource': resource_projection(store, resource), 'observation_required': True}

def reconcile_release(args, state, store):
    resource, previous = read_resource(store, args['resource_id'])
    resource_owner(resource, args['actor'])
    if resource['owner_task_id'] != state['task_id']:
        fail('resource_owner', 'Use the resource owning task for this operation.')
    if resource['version'] != args['expected_resource_version']:
        fail('revision_conflict', 'The resource changed before reconciliation.')
    intent = resource.get('release')
    if not intent or intent['token'] != args['token'] or not args['evidence']:
        fail('release_identity', 'Reconciliation requires the original release token and actual release evidence.')
    if intent['status'] == 'released':
        return {'resource': resource_projection(store, resource), 'already_recorded': True}
    receipt = read_json(resource_dir(store, args['resource_id']) / 'release-receipt.json')
    if (receipt.get('token') != intent['token'] or receipt.get('resource_id') != resource['resource_id']
            or receipt.get('argv_digest') != digest(intent['argv']) or receipt.get('result', {}).get('returncode') != 0):
        fail('release_unknown', 'A matching successful action receipt is required; the action will not be repeated.')
    intent.update(status='released', action_receipt=receipt, evidence=args['evidence'], confirmed=now(), confirmed_by=args['actor'])
    resource['observed_state'] = 'released'
    resource['observation'] = {'time': now(), 'valid_until': now(), 'evidence': args['evidence'], 'actor': args['actor']}
    commit_event(resource_dir(store, args['resource_id']), resource, previous, 'resource-release-confirmed', args['actor'])
    return {'resource': resource_projection(store, resource)}


def dispatch(operation, arguments):
    validate(operation, arguments)
    args = copy.deepcopy(arguments)
    if operation == "schema":
        existing_dir(args["root"])
        return {"ok": True, "commands": command_schemas()}
    if operation == "init":
        args['_managed_paths'] = bootstrap_project(git_identity(args['project']))
    root, store = store_dir(args["root"], create=operation == "init")
    if operation == "init":
        return init(args, root, store)
    if operation == "resource-status":
        return resource_status(str(root), args["resource_id"])
    if operation in ("run-execute", "run-dispatch"):
        return execute_run(args, root, store, external=operation == "run-dispatch")
    if operation == "resource-release":
        return release_resource(args, root, store)
    if operation == "run-prepare":
        return prepare_run_staged(args, root, store)
    if operation in ("status", "list"):
        if args.get("task_id"):
            state, _ = load_events(task_dir(store, args["task_id"]))
            return {"ok": True, "state": state, "summary": summary(state), "resources": project_resources(store)}
        tasks = []
        for path in sorted((store / "tasks").iterdir()):
            if path.is_dir() and not path.is_symlink():
                state, _ = load_events(path)
                tasks.append(summary(state))
        return {"ok": True, "tasks": tasks}
    path = task_dir(store, args["task_id"])
    if not path.is_dir():
        fail("not_found", "The requested task does not exist.")
    with lifecycle_lock(store), lock(path / "write.lock"):
        state, previous = load_events(path)
        if state["version"] != args["expected_version"]:
            fail("revision_conflict", "The task changed; reread status and use the current version.")
        if state["root"] != str(root):
            fail("root_changed", "This task belongs to a different storage root.")
        require_portable_state(state)
        result = {}
        if operation not in ("recover", "task-reopen", "cleanup", "resource-observe", "resource-release-reconcile", "run-reconcile"):
            require_task_open(state)
        if operation == "recover":
            project_state(path, state)
            with lock(Path(state["project"]["common_dir"]) / "task-workflow-integration.lock"):
                register_root(root, state)
            return {"ok": True, "state": state, "summary": summary(state), "recovered": True}
        if operation == "experiment-create":
            result = create_experiment(args, state, store)
            previous = commit_event(path, state, previous, "experiment-create-intent", args["actor"])
            destination = Path(result["experiment"]["directory"])
            no_symlinks(destination, Path(destination.anchor))
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "runs").mkdir(exist_ok=True)
            result["experiment"]["storage_ready"] = True
        elif operation in ("experiment-complete", "task-complete"):
            result = close_scope(args, state, args.get("experiment_id"))
        elif operation in ("experiment-reopen", "task-reopen"):
            result = reopen_scope(args, state, args.get("experiment_id"))
        elif operation == "run-plan":
            require_approved(state)
            result = plan_run(args, state, store)
        elif operation == "run-cancel":
            require_coordinator(args, state)
            current = get_run(state, args["run_id"])
            if current["status"] == "queued" and (Path(current["directory"]) / "execution.claim").exists():
                fail("cancellation_denied", "A claimed execution requires reconciliation before cancellation.")
            if current["status"] not in ("planned", "preparing", "prepared", "queued") and not (current["status"] == "awaiting_artifacts" and current.get("execution")):
                fail("cancellation_denied", "Cancel only an unclaimed reservation or explicitly dispose an exited workload's unaccepted artifacts; running and uncertain executions require reconciliation.")
            current.update(status="cancelled", cancellation={"reason": args["reason"], "actor": args["actor"], "time": now()})
            result = {"run": current}
        elif operation in ("run-reconcile", "run-observe"):
            result = reconcile_execution(args, state)
        elif operation == "run-accept":
            result = accept_run(args, state)
        elif operation == "resource-register":
            result = register_resource(args, state, store)
        elif operation == "resource-observe":
            result = observe_resource(args, state, store)
        elif operation == "resource-release-reconcile":
            result = reconcile_release(args, state, store)
        elif operation == "worktree-prepare":
            result, previous, changed = prepare_worktree(args, state, path, store, previous)
            if not changed:
                return {"ok": True, "state": state, "summary": summary(state), **result}
        elif operation == "design":
            state["design"] = {"version": (state["design"]["version"] + 1) if state["design"] else 1,
                               "content": args["content"], "digest": digest(args["content"]), "actor": args["actor"], "time": now()}
            state["approval"] = None
            for item in state["items"].values():
                item.update(status="pending", implementer=None, submitted=None, verifications=[], review=None, acceptance=None)
            invalidate_integration(state)
        elif operation == "approve":
            if not state["design"] or args["design_digest"] != state["design"]["digest"]:
                fail("stale_design", "Approval must name the current exact design digest.")
            state["approval"] = {"digest": args["design_digest"], "actor": args["actor"], "authorization_source": args["authorization_source"], "time": now()}
        elif operation == "item-add":
            if args["item_id"] in state["items"]:
                fail("already_exists", "The task item already exists.")
            owned_paths = args.get("owned_paths", [])
            if not args.get("overall") and not owned_paths:
                fail("scope_required", "Declare owned_paths for an implementation item.")
            for owned_path in owned_paths:
                safe_relative(owned_path)
            state["items"][args["item_id"]] = make_item(args["title"], args.get("overall", False), owned_paths)
            if not args.get("overall"):
                invalidate_overall(state)
            invalidate_integration(state)
        elif operation == "item-reopen":
            require_approved(state)
            item = get_item(state, args["item_id"])
            item.update(status="pending", implementer=None, submitted=None, review=None, acceptance=None, next_action=args["reason"])
            if not item["overall"]:
                invalidate_overall(state)
            state["decisions"].append({"actor": args["actor"], "content": "Reopen " + args["item_id"] + ": " + args["reason"], "time": now()})
            invalidate_integration(state)
        elif operation == "integration-verify":
            check_identity(state)
            integration = state["integration"]
            project = state["project"]["path"]
            if integration.get("status") != "complete" or git(project, "rev-parse", "HEAD") != integration["commit"] or project_status(state):
                fail("integration_required", "Verify the exact clean integrated base commit.")
            result = run(args["argv"], cwd=project, timeout=args.get("timeout", 300))
            unchanged = git(project, "rev-parse", "HEAD") == integration["commit"] and not project_status(state)
            log_folder = path / "evidence"
            no_symlinks(log_folder, path)
            log_folder.mkdir(exist_ok=True)
            log_path = log_folder / (uuid.uuid4().hex + ".json")
            atomic_json(log_path, {"stdout_tail": result.pop("stdout"), "stderr_tail": result.pop("stderr")})
            integration["verification"] = {"commit": integration["commit"], "design_digest": state["design"]["digest"], "argv": args["argv"], "actor": args["actor"], "passed": result["returncode"] == 0 and unchanged, "result": result, "log": str(log_path), "log_sha256": sha_file(log_path), "time": now()}
            result = {"verification": integration["verification"]}
        elif operation in ("item-start", "item-submit", "verify", "item-review", "item-accept"):
            apply_item(operation, args, state, path)
        elif operation == "decision":
            state["decisions"].append({"actor": args["actor"], "content": args["content"], "time": now()})
            if args.get("item_id"):
                item = get_item(state, args["item_id"])
                for key in ("blocked", "reason", "next_action"):
                    if key in args:
                        item[key] = args[key]
        elif operation == "integrate":
            result, previous, changed = integrate(args, state, path, previous)
            if not changed:
                return {"ok": True, "summary": summary(state), **result}
        elif operation == "cleanup":
            result = cleanup(args, state, store)
            if result.get("dry_run") or result.get("already_cleaned"):
                return {"ok": True, "summary": summary(state), **result}
        elif operation == "run-prepare":
            result = prepare_run(args, state, root)
        else:
            fail("unsupported", "The operation is not implemented.")
        commit_event(path, state, previous, operation, args["actor"])
        return {"ok": True, "state": state, "summary": summary(state), **result}


COMMANDS = {
    "schema": spec("Discover operation schemas."),
    "init": spec("Explicitly enroll an existing task worktree or a base placeholder awaiting worktree-prepare.", {"task_id": "string", "title": "string", "actor": "string", "authorization_source": "string", "project": "string"}, {"worktree": "string", "coordinator": "string", "environment_registry": "object", "owned_worktree": "boolean", "integration_required": "boolean", "session_id": "string"}),
    "worktree-prepare": mutation("Explicitly create or reuse this task's reserved development worktree; path is project/.worktrees/task-id.", {"expected_base": "string", "authorization_source": "string"}, {"branch": "string"}),
    "status": spec("Read authoritative task state without modifying it.", optional={"task_id": "string"}),
    "list": spec("List task summaries without modifying state."),
    "recover": mutation("Validate events and rebuild state and record projections."),
    "design": mutation("Record a new design and invalidate prior approval/evidence.", {"content": "string"}),
    "approve": mutation("Record explicit user authorization for the exact design digest.", {"design_digest": "string", "authorization_source": "string"}),
    "item-add": mutation("Add a pending implementation or overall verification item.", {"item_id": "string", "title": "string"}, {"overall": "boolean", "owned_paths": "array"}),
    "item-reopen": mutation("Reopen an item with an explicit reason while preserving its audit history.", {"item_id": "string", "reason": "string"}),
    "integration-verify": mutation("Execute actual validation against the clean integrated base commit.", {"argv": "array"}, {"timeout": "integer"}),
    "item-start": mutation("Begin an approved item.", {"item_id": "string"}),
    "item-submit": mutation("Submit a clean committed Git revision for review.", {"item_id": "string"}),
    "verify": mutation("Execute an argv check and bind its actual outcome to design and Git revision.", {"item_id": "string", "argv": "array"}, {"timeout": "integer"}),
    "item-review": mutation("Record independent review of the current submitted revision.", {"item_id": "string", "verdict": "string", "notes": "string"}),
    "item-accept": mutation("Coordinator acceptance with current verification and independent review.", {"item_id": "string", "notes": "string"}),
    "decision": mutation("Record a decision and optional blocker or next action.", {"content": "string"}, {"item_id": "string", "blocked": "string", "reason": "string", "next_action": "string"}),
    "integrate": mutation("Squash the accepted task revision into exactly one ordinary base commit; defaults to dry run and safely reconciles recorded interrupted attempts.", {"base_branch": "string", "expected_base": "string", "expected_head": "string", "authorization_source": "string"}, {"dry_run": "boolean", "commit_message": "string"}),
    "cleanup": mutation("Dry-run or safely remove an owned integrated worktree.", optional={"dry_run": "boolean"}),
    "experiment-complete": mutation("Accept the whole research outcome and analysis after all runs are terminal.", {"experiment_id": "string", "outcome": "string", "notes": "string", "evidence": "array"}),
    "experiment-reopen": mutation("Reopen an experiment while preserving its prior closure.", {"experiment_id": "string", "reason": "string"}),
    "task-complete": mutation("Accept the full deliverable after its implementation, integration and experiments are resolved.", {"outcome": "string", "notes": "string", "evidence": "array"}),
    "task-reopen": mutation("Reopen a full deliverable and invalidate prior resource eligibility.", {"reason": "string"}),
    "run-cancel": mutation("Cancel an unsubmitted reservation; submitted or uncertain runs require receipt reconciliation.", {"run_id": "string", "reason": "string"}),
    "run-accept": mutation("Accept output artifacts after actual successful recorded execution.", {"run_id": "string", "artifact_notes": "string"}),
}

ASSOCIATION_FIELDS = {"experiment_id": "string", "purpose": "string", "parent_run_id": "string", "checkpoint_reference": "string", "config": "object", "resource_id": "string", "requirements": "object"}
COMMANDS.update({
    "experiment-create": mutation("Reserve an experiment goal and output directory.", {"experiment_id": "string", "goal": "string"}, {"experiment_root": "string"}),
    "run-plan": mutation("Reserve an immutable run intent and optional resource reference.", {"run_id": "string"}, ASSOCIATION_FIELDS),
    "run-prepare": mutation("Freeze integrated code, environment, argv and runtime.", {"run_id": "string", "environment_id": "string", "lockfiles": "array", "argv": "array", "artifacts": "array"}, {**ASSOCIATION_FIELDS, "dependency_declaration": "string", "output_dir": "string"}),
    "run-dispatch": mutation("Reserve external execution and return the pinned runner argv without launching it.", {"run_id": "string"}, {"timeout": "integer"}),
    "run-execute": mutation("Execute frozen argv once and preserve an actual process receipt.", {"run_id": "string"}, {"timeout": "integer", "detached": "boolean"}),
    "run-observe": mutation("Observe an externally provided matching actual execution receipt.", {"run_id": "string", "receipt_path": "string", "evidence": "array"}),
    "run-reconcile": mutation("Reconcile a matching execution receipt without repeating execution.", {"run_id": "string"}, {"receipt_path": "string", "evidence": "array"}),
    "resource-register": mutation("Register an opaque project resource with ownership and observation evidence.", {"resource_id": "string", "handle": "string", "provided_by": "string", "can_release": "boolean", "authorization_source": "string", "ownership_evidence": "array", "capabilities": "object", "observed_state": "string", "evidence": "array", "valid_for_seconds": "integer"}),
    "resource-observe": mutation("Record fresh observed resource facts.", {"resource_id": "string", "expected_resource_version": "integer", "capabilities": "object", "observed_state": "string", "evidence": "array", "valid_for_seconds": "integer"}),
    "resource-status": spec("Project resource facts and derived release eligibility.", {"resource_id": "string"}),
    "resource-release": mutation("Record explicit release intent before one supplied release action.", {"resource_id": "string", "expected_resource_version": "integer", "eligibility_key": "string", "authorization_source": "string", "argv": "array"}, {"timeout": "integer"}),
    "resource-release-reconcile": mutation("Confirm matching release receipt and evidence without repeating release.", {"resource_id": "string", "expected_resource_version": "integer", "token": "string", "evidence": "array"}),
})


def project_resources(store):
    container = store / 'resources'
    if not container.exists():
        return []
    return [resource_projection(store, load_events(path)[0]) for path in sorted(container.iterdir()) if path.is_dir() and not path.is_symlink()]



def reconcile_execution(args, state):
    require_coordinator(args, state)
    current = get_run(state, args['run_id'])
    if current['status'] not in ('running', 'unknown', 'awaiting_artifacts', 'failed', 'complete') or not current.get('start_validated'):
        fail('execution_receipt_invalid', 'A matching execution intent is required for reconciliation.')
    receipt_path = Path(current['directory']) / 'execution-receipt.json'
    supplied = args.get('receipt_path')
    if supplied:
        if not args.get('evidence'):
            fail('execution_evidence_required', 'An externally provided receipt requires evidence references.')
        receipt_path = Path(supplied)
        no_symlinks(receipt_path, Path(receipt_path.anchor))
    receipt = read_json(receipt_path)
    log = Path(current['directory']) / 'execution.log'
    no_symlinks(log, Path(current['directory']))
    if (receipt.get('token') != current['token'] or receipt.get('argv_digest') != digest(current['argv'])
            or receipt.get('manifest_digest') != current['manifest_digest']
            or receipt.get('environment_digest') != digest(environment_identity(current['environment']))
            or type(receipt.get('returncode')) is not int or receipt.get('log') != str(log)
            or not log.is_file() or receipt.get('log_sha256') != sha_file(log)):
        fail('execution_receipt_invalid', 'The receipt does not match the frozen inputs and actual execution log.')
    if current.get('execution'):
        if current['execution'].get('receipt_digest') != digest(receipt):
            fail('execution_conflict', 'The supplied execution receipt conflicts with recorded execution.')
        return {'run': current, 'already_recorded': True}
    unchanged = manifest(Path(current['code'])) == current['manifest']
    current.update(execution={**receipt, 'receipt_digest': digest(receipt), 'snapshot_unchanged': unchanged,
                             'evidence': args.get('evidence', [])}, workload_success=receipt['returncode'] == 0 and unchanged,
                   status='awaiting_artifacts' if receipt['returncode'] == 0 and unchanged else 'failed', finished=now())
    return {'run': current}


def execute_run(args, root, store, external=False):
    path = task_dir(store, args['task_id'])
    with lifecycle_lock(store), lock(path / 'write.lock'):
        state, previous = load_events(path)
        require_task_open(state)
        require_coordinator(args, state)
        if state['version'] != args['expected_version']:
            fail('revision_conflict', 'The task changed before execution.')
        current = get_run(state, args['run_id'])
        require_execution_protocol(state, current)
        intent = current.get('execution_intent')
        if external and intent:
            if intent['mode'] != 'external' or ('timeout' in args and args['timeout'] != intent['timeout']):
                fail('execution_denied', 'The durable execution intent cannot be replaced.')
            return {'ok': True, 'state': state, 'summary': summary(state), 'run': current,
                    'runner_argv': intent['runner_argv'], 'already_dispatched': True, 'reconciliation_required': True}
        if current['status'] != 'prepared':
            fail('execution_denied', 'Only an unstarted prepared run can execute.')
        validate_resource_reference(store, state, {**current, 'run_id': args['run_id']}, require_available=not external)
        check_run(state, current)
        runner = Path(current['runtime']['directory']) / 'runner.py'
        command = [sys.executable, str(runner), '--root', str(root), '--task-id', args['task_id'], '--run-id', args['run_id'], '--token', current['token']]
        if 'timeout' in args:
            command += ['--timeout', str(args['timeout'])]
        current.update(status='queued', execution_intent={'runner_argv': command, 'timeout': args.get('timeout'),
                       'mode': 'external' if external else 'local', 'actor': args['actor'], 'time': now()})
        commit_event(path, state, previous, 'run-dispatch-intent', args['actor'])
    if external:
        return {'ok': True, 'state': state, 'summary': summary(state), 'run': current,
                'runner_argv': command, 'reconciliation_required': True}
    # The pinned runner validates actual admission and writes its durable result.
    if args.get('detached'):
        log_path = Path(current['directory']) / 'runner.log'
        with open(log_path, 'xb') as log:
            process = subprocess.Popen(command, cwd=str(root), stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        threading.Thread(target=process.wait, daemon=True).start()
        return {'ok': True, 'state': state, 'summary': summary(state), 'run': current, 'runner_pid': process.pid, 'reconciliation_required': True}
    # The runner owns the optional workload timeout and process-group cleanup.
    result = run(command, cwd=str(root), timeout=None)
    with lifecycle_lock(store), lock(path / 'write.lock'):
        state, previous = load_events(path)
        try:
            response = reconcile_execution(args, state)
        except WorkflowError:
            current = get_run(state, args['run_id'])
            claimed = (Path(current['directory']) / 'execution.claim').exists()
            uncertain = claimed or bool(current.get('start_validated'))
            if uncertain:
                current['status'] = 'unknown'
            current['runner_result'] = result
            commit_event(path, state, previous, 'run-execution-unknown' if uncertain else 'run-admission-deferred', args['actor'])
            raise
        commit_event(path, state, previous, 'run-execution-result', args['actor'])
        return {'ok': True, 'state': state, 'summary': summary(state), **response}


if __name__ == '__main__':
    raise SystemExit(main())
