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
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid
import weakref


VERSION = 1
PORTABLE_FORMAT = 2
EXECUTION_PROTOCOL = 2
STATES = ("pending", "implementing", "reviewing", "complete")
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
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
        fail("invalid_identifier", "Identifiers must start with a letter or digit and contain only letters, digits, underscores or hyphens.")
    return value

def text_value(value):
    if not isinstance(value, str) or not value.strip():
        fail("invalid_text", "A nonempty text value is required.")
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

def wait_with_timeout(waiter, timeout):
    """Honor an optional total duration with platform-compatible individual waits."""
    if timeout is None:
        return waiter(None)
    deadline = time.monotonic_ns() + timeout * 1_000_000_000
    while True:
        remaining = max(0, deadline - time.monotonic_ns())
        # TIMEOUT_MAX comes from Python's platform wait implementation. Splitting
        # a larger duration here preserves its full deadline without overflow.
        seconds = min(remaining, int(threading.TIMEOUT_MAX) * 1_000_000_000) / 1_000_000_000
        try:
            return waiter(seconds)
        except subprocess.TimeoutExpired:
            if time.monotonic_ns() >= deadline:
                raise


def run(argv, cwd=None, timeout=None, input_text=None):
    # Child output streams to disk and is returned in full after completion.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr, tempfile.TemporaryFile() as stdin:
        process = None
        try:
            if input_text is not None:
                stdin.write(input_text.encode())
                stdin.seek(0)
            process = subprocess.Popen(argv, cwd=cwd,
                                       stdin=stdin if input_text is not None else subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, shell=False)
            wait_with_timeout(lambda seconds: process.wait(timeout=seconds), timeout)
            code, error = process.returncode, None
        except subprocess.TimeoutExpired:
            code, error = None, "timeout"
        except OSError:
            code, error = None, "unavailable"
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
        result = {"returncode": code}
        for name, stream in (("stdout", stdout), ("stderr", stderr)):
            stream.seek(0)
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

def init_checkout_identity(value, field):
    """Explain enrollment path roles while retaining existing identity guards."""
    try:
        return git_identity(value)
    except WorkflowError as error:
        if error.code in ('invalid_path', 'git_identity', 'git_error'):
            fail(error.code, 'init.' + field + ' must name an existing absolute Git checkout root, '
                 'not a project label or a subdirectory. Use the actual checkout path; '
                 'put the short task label in task_id. ' + error.message)
        raise

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

_LOCK_THREADS = weakref.WeakValueDictionary()
_LOCK_THREADS_MUTEX = threading.Lock()
_LOCK_HOST = None
_LOCK_RETIRED = {}
_LOCK_FDS = set()


def reset_lock_process():
    global _LOCK_THREADS, _LOCK_THREADS_MUTEX, _LOCK_HOST, _LOCK_RETIRED, _LOCK_FDS
    for fd in _LOCK_FDS:
        try:
            os.close(fd)  # Close the child's copy without unlocking the parent.
        except OSError:
            pass
    _LOCK_THREADS = weakref.WeakValueDictionary()
    _LOCK_THREADS_MUTEX = threading.Lock()
    _LOCK_HOST = None
    _LOCK_RETIRED = {}
    _LOCK_FDS = set()


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(before=lambda: _LOCK_THREADS_MUTEX.acquire(),
                        after_in_parent=lambda: _LOCK_THREADS_MUTEX.release(),
                        after_in_child=reset_lock_process)


def lock_host_identity():
    """Identify the current kernel/PID namespace; unknown hosts cannot reap."""
    global _LOCK_HOST
    if _LOCK_HOST is None:
        identity = None
        try:
            boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
            namespace = os.stat('/proc/self/ns/pid').st_ino
            if boot:
                identity = {'boot': boot, 'pid_namespace': namespace}
        except OSError:
            if sys.platform == 'darwin':
                result = subprocess.run(['sysctl', '-n', 'kern.bootsessionuuid'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                if result.returncode == 0 and result.stdout.strip():
                    identity = {'boot': result.stdout.decode('ascii').strip()}
        _LOCK_HOST = {'hostname': socket.gethostname(), 'identity': identity}
    return _LOCK_HOST


def lock_uid():
    return os.getuid() if hasattr(os, 'getuid') else None


def lock_file_operation(fd, acquire, platform=None):
    """Use nonblocking OS locks; unsupported filesystems fail closed."""
    if (platform or os.name) == 'nt':
        import msvcrt
        if os.fstat(fd).st_size == 0:
            os.write(fd, b'\0')
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK if acquire else msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, (fcntl.LOCK_EX | fcntl.LOCK_NB) if acquire else fcntl.LOCK_UN)


def lock_identity(info):
    return info.st_dev, info.st_ino


@contextlib.contextmanager
def lock_guard(path):
    # This inode is persistent. Unlinking it would split the advisory lock.
    guard = path.with_name(path.name + '.guard')
    fd = None
    acquired = False
    try:
        with _LOCK_THREADS_MUTEX:
            fd = os.open(str(guard), os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            _LOCK_FDS.add(fd)
        opened, named = os.fstat(fd), guard.lstat()
        if (not stat.S_ISREG(opened.st_mode) or stat.S_ISLNK(named.st_mode)
                or lock_identity(opened) != lock_identity(named)
                or (lock_uid() is not None and opened.st_uid != lock_uid())):
            fail('unsafe_lock', 'The workflow lock guard is not an owned regular file.')
        try:
            lock_file_operation(fd, True)
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                fail('locked', 'A workflow operation holds this lock.')
            fail('lock_unavailable', 'The filesystem could not provide the required workflow lock guard.')
        acquired = True
        if lock_identity(guard.lstat()) != lock_identity(opened):
            fail('unsafe_lock', 'The workflow lock guard changed during acquisition.')
        yield
    finally:
        primary = sys.exc_info()[1]
        failure = None
        if fd is not None:
            try:
                if acquired:
                    lock_file_operation(fd, False)
            except OSError as error:
                failure = error
            finally:
                try:
                    with _LOCK_THREADS_MUTEX:
                        _LOCK_FDS.discard(fd)
                        os.close(fd)
                except OSError as error:
                    failure = failure or error
        if failure is not None and primary is None:
            fail('lock_cleanup_failed', 'The workflow lock guard could not be released cleanly.')


def read_lock_claim(path):
    """Read a complete regular claim without following a replaced marker."""
    try:
        named = path.lstat()
        if not stat.S_ISREG(named.st_mode) or (lock_uid() is not None and named.st_uid != lock_uid()):
            return None
        fd = os.open(str(path), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'r') as stream:
            opened = os.fstat(stream.fileno())
            if lock_identity(opened) != lock_identity(named):
                return None
            owner = json.load(stream)
        if (not isinstance(owner, dict) or owner.get('lock_protocol') != 2
                or not isinstance(owner.get('token'), str)
                or re.fullmatch('[0-9a-f]{32}', owner['token']) is None
                or type(owner.get('pid')) is not int or owner['pid'] < 1
                or owner.get('uid') != lock_uid()):
            return None
        return lock_identity(opened), owner
    except (OSError, ValueError):
        return None


def dead_lock_owner(owner):
    # Same-host serialization is sufficient: foreign clients never reap a
    # claim. Atomic publication still excludes them without assuming that
    # every NFS client shares the advisory guard implementation.
    host = lock_host_identity()
    if not host['identity'] or owner.get('host') != host:
        return False
    try:
        os.kill(owner['pid'], 0)
    except ProcessLookupError:
        return True
    except (PermissionError, OSError):
        return False
    return False  # A reused live PID remains protected.


def remove_lock_claim(path, identity, token):
    current = read_lock_claim(path)
    if current is None or current[0] != identity or current[1]['token'] != token:
        fail('lock_changed', 'The workflow lock identity changed; its replacement was preserved.')
    path.unlink()
    sync_dir(path.parent)


@contextlib.contextmanager
def lock(path):
    path = path.parent.resolve() / path.name
    with _LOCK_THREADS_MUTEX:
        local = _LOCK_THREADS.setdefault(str(path), threading.Lock())
    if not local.acquire(blocking=False):
        fail('locked', 'A workflow operation in this process holds the lock.')
    try:
        with lock_guard(path):
            if path.exists() or path.is_symlink():
                previous = read_lock_claim(path)
                retired = _LOCK_RETIRED.get(str(path))
                own_retired = bool(previous and retired == (previous[0], previous[1]['token'])
                                   and previous[1]['pid'] == os.getpid())
                if previous is None or not (own_retired or dead_lock_owner(previous[1])):
                    fail('locked', 'A live, foreign or unidentified workflow lock exists; verify quiescence before manual recovery.')
                remove_lock_claim(path, previous[0], previous[1]['token'])
            _LOCK_RETIRED.pop(str(path), None)
            owner = {'lock_protocol': 2, 'pid': os.getpid(), 'uid': lock_uid(),
                     'host': lock_host_identity(), 'token': uuid.uuid4().hex, 'created': now()}
            fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.owner-', dir=str(path.parent))
            candidate = Path(temporary)
            identity = lock_identity(os.fstat(fd))
            published = False
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(canonical(owner) + b'\n'); stream.flush(); os.fsync(stream.fileno())
                # Cleanup checks exact identity even if interruption occurs
                # immediately after link returns or a foreign client wins.
                published = True
                try:
                    os.link(str(candidate), str(path))
                except FileExistsError:
                    fail('locked', 'Another workflow operation acquired this lock.')
                except OSError:
                    fail('lock_unavailable', 'Atomic workflow lock publication is unavailable.')
                sync_dir(path.parent)
                candidate.unlink()
                yield
            finally:
                primary = sys.exc_info()[1]
                failure = None
                try:
                    if published:
                        remove_lock_claim(path, identity, owner['token'])
                except (OSError, WorkflowError) as error:
                    failure = error
                    current = read_lock_claim(path)
                    if current and current[0] == identity and current[1]['token'] == owner['token']:
                        _LOCK_RETIRED[str(path)] = (identity, owner['token'])
                try:
                    candidate.unlink(missing_ok=True)
                except OSError as error:
                    failure = failure or error
                if failure is not None and primary is None:
                    if isinstance(failure, WorkflowError):
                        raise failure
                    fail('lock_cleanup_failed', 'The workflow lock could not be removed; its complete owner claim was preserved.')
    finally:
        local.release()

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
        if path.is_symlink() or not path.is_file():
            fail("corrupt_state", "State file is unsafe.")
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
    if state.get("process"):
        return process_record_text(state)
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
            "approved": design_is_approved(state),
            "process_protocol": state.get("process", {}).get("protocol_version", 1),
            "stage": state.get("process", {}).get("stage", "legacy"),
            "plan_approved": plan_is_approved(state),
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
        for key in ("argv", "lockfiles", "artifacts", "owned_paths", "evidence", "ownership_evidence", "findings", "unverified"):
            if key in properties:
                properties[key]["items"] = {"type": "string"}
        properties.update(copy.deepcopy(PROCESS_SCHEMAS.get(name, {})))
        properties['root'].update(description='Existing absolute directory that owns .task-workflow state. Normally use the base project checkout root; preserve an already registered state root.',
                                  examples=['/absolute/path/to/project'])
        if name == 'init':
            guidance = {
                'project': ('Existing absolute path to the base Git checkout root, not a project name. It must be registered by Git at this exact path and branch.', ['/absolute/path/to/project']),
                'worktree': ('Existing absolute Git checkout root in the same repository. Omit for base enrollment; a dedicated task checkout must be project/.worktrees/task-id.', ['/absolute/path/to/project/.worktrees/report-export']),
                'owned_worktree': ('Whether this task owns the dedicated worktree and may later clean it up. Omit or use false for the base checkout. worktree-prepare records ownership when it creates the task checkout.', [False]),
                'task_id': ('Short task identifier, not a directory path or project name.', ['report-export']),
                'session_id': ('Actual current host session identifier, when available. Do not invent a session identifier.', None),
            }
            for key, (description, examples) in guidance.items():
                properties[key]['description'] = description
                if examples is not None:
                    properties[key]['examples'] = examples
        if name == "item-review":
            for key in ("verdict", "requirements_verdict", "quality_verdict"):
                properties[key]["enum"] = ["accept", "changes"]
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
        if key in args and any(not isinstance(x, str) or not x or "\x00" in x for x in args[key]):
            fail("invalid_arguments", "Argument arrays require nonempty strings without null characters.")
    if "argv" in args and not args["argv"]:
        fail("invalid_arguments", "A nonempty executable argv is required.")
    if "expected_version" in args and args["expected_version"] < 1:
        fail("invalid_arguments", "Expected version must be a positive integer.")
    for duration_key in ("expected_duration_seconds", "recovery_margin_seconds"):
        if duration_key in args and args[duration_key] < 1:
            fail("invalid_duration", "Expected duration and recovery margin must be positive seconds.")
    if "timeout" in args:
        if args["timeout"] < 1:
            fail("invalid_arguments", "Timeout must be positive seconds.")

def require_approved(state):
    if state.get("process", {}).get("design") and state["process"]["stage"] not in ("implementation", "delivery"):
        fail("discussion_required", "Complete the current discussion and exact design and plan approvals before execution.")
    if not summary(state)["approved"]:
        fail("approval_required", "Explicit approval of the current design is required.")
    if state.get("process"):
        require_process_ready(state)

def binding(state, rev, item=None):
    value = {"design_digest": state["design"]["digest"], "revision": rev}
    if state.get("process") and item is not None and not item["overall"]:
        value["design_digest"] = process_scope_digest(state, item, rev)
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
            result = run(["git", "-C", str(project), "worktree", "add", "--", str(target), association["branch"]])
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
        if state.get("process") and not item["overall"]:
            for dependency_id in item["plan_item"]["dependencies"]:
                dependency = get_item(state, dependency_id)
                if dependency["status"] != "complete" or not evidence_matches(dependency["acceptance"], binding(state, revision(state), dependency)):
                    fail("dependency_incomplete", "Accept the current evidence for each planned dependency before starting this item.")
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
        result = run(args["argv"], cwd=state["worktree"]["path"], timeout=args.get("timeout"))
        try:
            unchanged = revision(state) == current["revision"]
        except WorkflowError:
            unchanged = False
        evidence_dir = task_path / "evidence"
        no_symlinks(evidence_dir, task_path)
        evidence_dir.mkdir(exist_ok=True)
        evidence_id = uuid.uuid4().hex
        log_path = evidence_dir / (evidence_id + ".json")
        atomic_json(log_path, {"stdout_tail": result.pop("stdout", ""), "stderr_tail": result.pop("stderr", "")})
        item["verifications"].append({**current, "argv": args["argv"], "actor": actor, "time": now(),
                                     "passed": result["returncode"] == 0 and unchanged,
                                     "unchanged": unchanged, "result": result, "log": str(log_path), "log_sha256": sha_file(log_path)})
    elif operation == "item-review":
        if item["status"] != "reviewing" or not evidence_matches(item["submitted"], current):
            fail("stale_evidence", "Review requires the currently submitted design and revision.")
        if actor == item["implementer"]:
            fail("independent_review_required", "The reviewer must differ from the implementer.")
        if state.get("process") and item["overall"] and any(actor == i.get("implementer") for i in state["items"].values()):
            fail("independent_review_required", "The overall reviewer must differ from every task implementer.")
        if args["verdict"] not in ("accept", "changes"):
            fail("invalid_verdict", "Review verdict must be accept or changes.")
        dimensions = {}
        if state.get("process"):
            if not all(key in args for key in ("requirements_verdict", "quality_verdict")):
                fail("review_dimensions_required", "Record separate requirements and quality verdicts for this item.")
            dimensions = {key: args[key] for key in ("requirements_verdict", "quality_verdict")}
            if any(value not in ("accept", "changes") for value in dimensions.values()):
                fail("invalid_verdict", "Requirements and quality verdicts must be accept or changes.")
            expected = "accept" if all(value == "accept" for value in dimensions.values()) else "changes"
            if args["verdict"] != expected:
                fail("invalid_verdict", "The combined verdict must reflect both requirements and quality review.")
            dimensions["findings"] = args.get("findings", [])
            dimensions["unverified"] = args.get("unverified", [])
            process_strings(dimensions["findings"]); process_strings(dimensions["unverified"])
            if args["verdict"] == "accept" and (dimensions["findings"] or dimensions["unverified"]):
                fail("review_gaps", "Resolve review findings and unverified requirements before acceptance.")
        item["review"] = {**current, **dimensions, "actor": actor, "verdict": args["verdict"], "notes": args["notes"], "time": now()}
        if args["verdict"] == "changes":
            item.update(status="implementing", submitted=None, acceptance=None)
    elif operation == "item-accept":
        if actor != state["coordinator"]:
            fail("coordinator_required", "Only the registered coordinator may accept an item.")
        review = item["review"] or {}
        if state.get("process") and any(review.get(key) != "accept" for key in ("requirements_verdict", "quality_verdict")):
            fail("review_dimensions_required", "Both current requirements and quality review must accept this item.")
        if item["status"] != "reviewing" or not evidence_matches(item["submitted"], current) or review.get("verdict") != "accept" or not evidence_matches(review, current) or review.get("actor") == item["implementer"]:
            fail("stale_evidence", "A current independent accepting review is required.")
        checks = [v for v in item["verifications"] if evidence_matches(v, current)]
        if not checks or not checks[-1]["passed"]:
            fail("verification_required", "The latest actual verification of this revision must pass.")
        item.update(status="complete", acceptance={**current, "actor": actor, "notes": args["notes"], "time": now()}, blocked="", next_action="")
        if state.get("process") and item["overall"]:
            state["process"]["stage"] = "delivery"

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
    result = run(["git", "-C", state["project"]["path"], "worktree", "remove", "--", str(scratch)])
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
            result = run(["git", "-C", str(project), "worktree", "add", "--detach", "--", str(scratch), integration["base"]])
            if result["returncode"] != 0:
                fail("integration_scratch", "Git did not complete the isolated worktree; inspect it before retrying.")
        check_scratch(state, integration)
        if integration["status"] == "preparing":
            if git(scratch, "rev-parse", "HEAD") != integration["base"] or git(scratch, "status", "--porcelain=v1", "--untracked-files=all", "--ignored"):
                fail("integration_scratch", "An interrupted squash has unrecorded changes; preserve it for inspection.")
            integration["status"] = "merging"
            previous = commit_event(path, state, previous, "integrate-merge-intent", args["actor"])
            result = run(["git", "-C", str(scratch), "merge", "--squash", "--no-commit", "--", head])
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
                result = run(["git", "-C", str(scratch), "commit", "-m", integration["commit_message"]])
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
                result = run(["git", "-C", str(project), "merge", "--ff-only", "--no-overwrite-ignore", "--no-edit", "--", candidate])
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
    result = run([str(python), "-I", "-c", "import importlib.metadata,json,sys; print(json.dumps({'prefix':sys.prefix,'version':sys.version,'packages':sorted((d.metadata.get('Name',''),d.version) for d in importlib.metadata.distributions())},sort_keys=True))"])
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
    if ".gitmodules" in files:
        fail("unsupported_dependency", "Submodules and Git LFS require an explicit supported export strategy.")
    for name, source in files.items():
        # Snapshot mappings contain disk paths; bytes remain accepted for callers
        # that inspect an individual dependency document.
        with contextlib.ExitStack() as stack:
            stream = stack.enter_context(source.open('rb')) if isinstance(source, Path) else None
            prefix = stream.read(len(b"version https://git-lfs.github.com/spec/")) if stream else source
            if prefix.startswith(b"version https://git-lfs.github.com/spec/"):
                fail("unsupported_dependency", "Git LFS pointers cannot be used as experiment code or data.")
            if name.endswith(".gitattributes"):
                if stream:
                    stream.seek(0)
                    lfs = any(b"filter=lfs" in line for line in stream)
                else:
                    lfs = b"filter=lfs" in source
                if lfs:
                    fail("unsupported_dependency", "Submodules and Git LFS require an explicit supported export strategy.")
            if name.endswith(("pyproject.toml", "requirements.txt", "uv.lock", "poetry.lock")):
                if stream:
                    stream.seek(0)
                data = stream.read() if stream else source
                text = data.decode("utf-8", "replace")
                if re.search(r"(?:file://|^-e\s|^--editable\s)", text, re.M):
                    fail("unsupported_dependency", "External local dependencies require a supported explicit export strategy.")
                local_assignments = re.findall(r"(?:path|editable|directory)\s*=\s*([^,}\n]+)", text)
                if any(value.strip() not in ('"."', "'.'") for value in local_assignments):
                    fail("unsupported_dependency", "External local dependencies require a supported explicit export strategy.")
    if declaration != "no-external-local-dependencies":
        fail("dependency_declaration_required", "Declare no-external-local-dependencies after checking imports and external inputs.")


def inventory_records(stream):
    """Read null-delimited Git records without buffering the whole inventory."""
    pending = b''
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        records = (pending + chunk).split(b'\0')
        pending = records.pop()
        yield from records
    if pending:
        fail('archive_failed', 'Git returned an unterminated object inventory.')


def archive_preflight(project, commit):
    """Inspect object types before export; blob sizes do not restrict admission."""
    with tempfile.TemporaryFile() as listing, tempfile.TemporaryFile() as errors:
        try:
            result = subprocess.run(["git", "-C", project, "ls-tree", "-r", "-l", "-z", "--full-tree", commit], stdout=listing, stderr=errors)
        except OSError:
            fail("archive_failed", "Git could not inspect the snapshot object inventory.")
        if result.returncode != 0:
            fail("archive_failed", "Git could not inspect the snapshot object inventory.")
        listing.seek(0)
        for record in inventory_records(listing):
            try:
                header, name = record.split(b"\t", 1)
                mode, kind, object_id, size = header.split()
                if kind == b'blob' and int(size) < 0:
                    raise ValueError
            except ValueError:
                fail("archive_failed", "Git returned an invalid object inventory.")
            if mode == b"160000" or kind == b"commit":
                fail("unsupported_dependency", "Submodule contents cannot silently disappear from experiment snapshots.")
            if mode == b"120000":
                fail("unsafe_snapshot", "Tracked symlinks require an explicit supported export strategy.")


@contextlib.contextmanager
def exported_snapshot(project, commit):
    """Stream Git's archive and each exported file through temporary disk storage."""
    with tempfile.TemporaryDirectory(prefix='task-workflow-export-') as temporary:
        staging = Path(temporary)
        files, modes = {}, {}
        with tempfile.TemporaryFile() as archive, tempfile.TemporaryFile() as errors:
            try:
                result = subprocess.run(['git', '-C', project, 'archive', '--format=tar', commit],
                                        stdout=archive, stderr=errors)
            except OSError:
                fail('archive_failed', 'Git could not export the integrated commit.')
            if result.returncode != 0:
                fail('archive_failed', 'Git could not export the integrated commit.')
            archive.seek(0)
            try:
                with tarfile.open(fileobj=archive, mode='r|') as tar:
                    for member in tar:
                        relative = safe_relative(member.name.rstrip('/'))
                        if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                            fail('unsafe_snapshot', 'Symlinks, hard links and special archive entries are prohibited.')
                        if member.isdir() or excluded(relative.parts):
                            continue
                        target = staging / str(relative)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with tar.extractfile(member) as source, target.open('wb') as destination:
                            shutil.copyfileobj(source, destination, length=1024 * 1024)
                        files[str(relative)] = target
                        modes[str(relative)] = member.mode & 0o777
            except (tarfile.TarError, OSError):
                fail('archive_failed', 'Git returned an invalid snapshot archive.')
        yield files, modes


def source_has_prefix(source, prefix):
    with source.open('rb') as original, prefix.open('rb') as partial:
        for chunk in iter(lambda: partial.read(1024 * 1024), b''):
            if original.read(len(chunk)) != chunk:
                return False
    return True

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
    # Only immutable Git objects enter the independent snapshot.
    with exported_snapshot(state['project']['path'], commit) as (files, modes):
        check_dependencies(files, args.get("dependency_declaration", "reason"))
        for name in args["lockfiles"]:
            if name not in files:
                fail("lockfile_missing", "A declared dependency lockfile is absent from the exported commit.")
        marker = destination / '.preparation-intent.json'
        ownership = {'token': planned['preparation_token'], 'intent': planned['preparation_intent'],
                     'files': {name: sha_file(source) for name, source in files.items()}}
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
                source = files[str(PurePosixPath(relative).relative_to('code'))]
                if not source_has_prefix(source, entry):
                    fail('preparation_changed', 'Owned partial code differs from the immutable source; preserve it.')
        code.mkdir(exist_ok=True)
        for name, source in files.items():
            file_path = code / name
            file_path.parent.mkdir(parents=True, exist_ok=True)
            if file_path.exists():
                file_path.chmod(0o600)
            with source.open('rb') as original, open(file_path, 'wb') as stream:
                shutil.copyfileobj(original, stream, length=1024 * 1024)
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
        result = run(["git", "-C", state["project"]["path"], "worktree", "remove", "--", str(target)])
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
        raw = sys.stdin.read() if options.json_args == "-" else options.json_args
        args = json.loads(raw)
        if not isinstance(args, dict) or ("root" in args and args["root"] != options.root):
            fail("invalid_arguments", "JSON must be an object with no conflicting root.")
        args["root"] = options.root or str(find_registered_root(os.getcwd()) or Path(git(os.getcwd(), "rev-parse", "--show-toplevel")))
        result = dispatch(options.operation, args)
        print(json.dumps(result, ensure_ascii=False))
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
        if target.exists() and not target.is_file():
            fail('exclude_conflict', 'The repository exclude file is unsafe.')
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

def register_root(root, state, select_session=False):
    store = root / '.task-workflow'
    path = store / 'registry.json'
    data = read_json(path) if path.exists() else {'format': VERSION, 'root': str(root), 'project': state['project'], 'tasks': []}
    if data.get('root') != str(root) or data.get('project', {}).get('common_dir') != state['project']['common_dir']:
        fail('project_mismatch', 'This state root belongs to a different Git project.')
    data['tasks'] = sorted(set(data['tasks'] + [state['task_id']]))
    if select_session and state.get('session_id'):
        bindings = data.setdefault('session_bindings', {})
        if not isinstance(bindings, dict):
            fail('corrupt_state', 'Project session bindings are invalid.')
        bindings[state['session_id']] = state['task_id']
    atomic_json(path, data)

def session_bindings(store):
    path = store / 'registry.json'
    # A committed initial event can precede its first registry projection.
    # Explicit status/recovery must remain possible after that interruption.
    if not path.exists() and not path.is_symlink():
        return {}
    registry = read_json(path)
    bindings = registry.get('session_bindings', {})
    if not isinstance(bindings, dict):
        fail('corrupt_state', 'Project session bindings are invalid.')
    return bindings

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

def session_dialogue_context(cwd, session_id):
    """Read only the explicitly selected task in the current verified project."""
    if not isinstance(session_id, str) or re.fullmatch(r"[A-Za-z0-9_-]+", session_id) is None:
        return None
    if not isinstance(cwd, str) or any(ord(character) < 32 for character in cwd):
        return None
    path = Path(cwd)
    if not path.is_absolute() or not path.is_dir():
        return None
    root = find_registered_root(path)
    if root is None:
        return None
    root, store = store_dir(str(root))
    selected = session_bindings(store).get(session_id)
    if not isinstance(selected, str):
        return None
    identifier(selected)
    task_path = task_dir(store, selected)
    if not task_path.is_dir():
        return None
    state, _ = load_events(task_path)
    if state.get("session_id") != session_id or state["root"] != str(root):
        return None
    if session_bindings(store).get(session_id) != selected:
        return None
    contract = dialogue_contract(state)
    return {"root": str(root), "session_id": session_id, "status_tool": "context",
            "task": summary(state), "dialogue_contract": contract, "templates": contract["templates"],
            "recovery_guidance": "Use this current state version and stage for the related request. Read-only progress questions authorize inspection only. Record actual incoming answers before dependent work; hook delivery grants no authorization."}


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
    project = init_checkout_identity(args['project'], 'project')
    worktree = init_checkout_identity(args.get('worktree', args['project']), 'worktree')
    if worktree['common_dir'] != project['common_dir']:
        fail('git_identity', 'Project and worktree must share a Git repository.')
    expected = Path(project['path']) / '.worktrees' / args['task_id']
    if worktree['path'] != project['path'] and Path(worktree['path']) != expected:
        fail('worktree_association', 'A task checkout must use project/.worktrees/task-id.')
    if root != Path(project['path']) and (within(root, Path(project['path'])) or within(root, Path(worktree['path']))):
        fail('state_inside_checkout', 'Use the project root or an external state root.')
    if args.get('owned_worktree') and worktree['path'] == project['path']:
        fail('invalid_ownership', 'The base checkout cannot be declared an owned task worktree. '
             'For base enrollment, omit worktree or set it to project, and omit owned_worktree '
             'or set it to false. Use worktree-prepare for the dedicated task checkout after plan approval.')
    environments = {}
    for name, value in args.get('environment_registry', {}).items():
        identifier(name)
        logical = Path(value).expanduser()
        if not logical.is_absolute() or not logical.is_dir():
            fail('invalid_environment', 'Environment references must be existing absolute directories.')
        environments[name] = str(logical)
    with lifecycle_lock(store), lock(Path(project['common_dir']) / 'task-workflow-integration.lock'), lock(store / 'registry.lock'):
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
        process = new_process()
        if process is not None:
            state['process'] = process
        text_value(state['coordinator'])
        if state['session_id'] is not None:
            text_value(state['session_id'])
        path.mkdir()
        (path / 'events').mkdir()
        atomic_json(binding_path, {'root': str(root), 'common_dir': project['common_dir']})
        try:
            commit_event(path, state, None, 'init', args['actor'])
        except Exception:
            # Remove only the empty directories just created by this attempt.
            # Preserve every committed event or unexpected file for recovery.
            events = path / 'events'
            if events.is_dir() and not any(events.iterdir()) and set(path.iterdir()) == {events}:
                events.rmdir()
                path.rmdir()
            raise
        register_root(root, state, select_session=True)
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
    if not isinstance(values, dict):
        fail('invalid_capabilities', 'Capabilities must be an object of named scalar values.')
    for key, value in values.items():
        identifier(key)
        if type(value) not in (str, int, bool) or (type(value) is int and value < 0) or (isinstance(value, str) and not value):
            fail('invalid_capabilities', 'Capability values must be nonnegative integers, booleans or nonempty strings.')

def resource_dir(store, resource_id):
    target = store / 'resources' / identifier(resource_id)
    no_symlinks(target, store)
    return target

def read_resource(store, resource_id):
    return load_events(resource_dir(store, resource_id))

def observation_current(resource):
    try:
        observation = resource['observation']
        moment = dt.datetime.now(dt.timezone.utc)
        if observation.get('valid_until') is not None:
            return moment <= dt.datetime.fromisoformat(observation['valid_until'])
        started = dt.datetime.fromisoformat(observation['time'])
        validity = observation.get('valid_for_seconds')
        if validity is None:
            return True
        if type(validity) is not int or validity < 1:
            return False
        elapsed = moment - started
        # Compare integer seconds without constructing an overflowing datetime.
        seconds = elapsed.days * 86400 + elapsed.seconds
        return seconds < validity or (seconds == validity and elapsed.microseconds == 0)
    except (KeyError, TypeError, ValueError, OverflowError):
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

def exited_resource_reference(current):
    """Use committed execution identity, independently of artifact acceptance."""
    execution = current.get('execution')
    try:
        return bool(current.get('start_validated') and current.get('finished') and isinstance(execution, dict)
            and type(execution.get('returncode')) is int
            and execution.get('token') == current['token']
            and execution.get('argv_digest') == digest(current['argv'])
            and execution.get('manifest_digest') == current['manifest_digest']
            and execution.get('environment_digest') == digest(environment_identity(current['environment']))
            and execution.get('log') == str(Path(current['directory']) / 'execution.log')
            and isinstance(execution.get('log_sha256'), str) and re.fullmatch('[0-9a-f]{64}', execution['log_sha256'])
            and isinstance(execution.get('receipt_digest'), str) and re.fullmatch('[0-9a-f]{64}', execution['receipt_digest']))
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def resource_projection(store, resource):
    associated = resource_associations(store, resource['resource_id'])
    refs = []
    for state, run_id, current in associated:
        exited = current['status'] == 'awaiting_artifacts' and exited_resource_reference(current)
        blocking = current['status'] not in TERMINAL_RUNS and not exited
        refs.append({'task_id': state['task_id'], 'run_id': run_id, 'status': current['status'],
                     'release_blocking': blocking,
                     'exit_receipt_digest': current.get('execution', {}).get('receipt_digest') if exited else None})
    live = any(reference['release_blocking'] for reference in refs)
    key = digest({'resource_id': resource['resource_id'], 'resource_version': resource['version'],
                  'refs': refs})
    released = resource.get('release', {}).get('status') == 'released'
    uncertain = resource.get('release', {}).get('status') in ('releasing', 'unknown')
    current = observation_current(resource)
    permitted = resource.get('can_release') is True
    eligible = bool(permitted and not live and current and resource['observed_state'] == 'available' and not released and not uncertain)
    reason = ('released' if released else 'release_unknown' if uncertain else 'release_permission_required' if not permitted else
              'live_references' if live else 'observation_required' if not current or resource['observed_state'] != 'available' else 'eligible')
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
    validity = args.get('valid_for_seconds')
    if validity is not None and validity < 1:
        fail('invalid_duration', 'Observation validity must be positive seconds.')
    moment = dt.datetime.now(dt.timezone.utc)
    observation = {'time': moment.isoformat(), 'valid_until': None,
                   'evidence': args['evidence'], 'actor': args['actor']}
    if validity is not None:
        observation['valid_for_seconds'] = validity
        try:
            observation['valid_until'] = (moment + dt.timedelta(seconds=validity)).isoformat()
        except OverflowError:
            # Preserve the supplied duration when its end is beyond datetime's range.
            pass
    return observation

def observe_resource(args, state, store):
    resource, previous = read_resource(store, args['resource_id'])
    resource_owner(resource, args['actor'])
    require_coordinator(args, state)
    if resource['owner_task_id'] != state['task_id']:
        fail('resource_owner', 'Use the resource owning task for this operation.')
    if resource['version'] != args['expected_resource_version']:
        fail('revision_conflict', 'The resource changed; reread its current version.')
    validate_capabilities(args['capabilities'])
    if resource.get('release', {}).get('status') == 'released':
        fail('resource_released', 'A released resource cannot be revived; register a new resource identity.')
    if ('can_release' in args) != ('authorization_source' in args):
        fail('resource_permission_source_required', 'A permission correction requires can_release and its actual authorization_source together.')
    if 'can_release' in args:
        if resource.get('release'):
            fail('resource_sealed', 'A release intent seals permission changes; reconcile the existing action.')
        resource.update(can_release=args['can_release'], permission_source=text_value(args['authorization_source']))
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
            fail('release_denied', 'Release requires permission, current available resource evidence and resolved capacity references without a prior release intent.')
        token = 'release-' + uuid.uuid4().hex
        resource['release'] = {'status': 'releasing', 'token': token, 'argv': args['argv'], 'actor': args['actor'],
            'authorization_source': text_value(args['authorization_source']), 'eligibility_key': args['eligibility_key'], 'time': now()}
        previous = commit_event(resource_path, resource, previous, 'resource-release-intent', args['actor'])
        command = list(args['argv'])
    result = run(command, cwd=str(root), timeout=args.get('timeout'))
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


def _dispatch(operation, arguments):
    validate(operation, arguments)
    args = copy.deepcopy(arguments)
    if operation == "schema":
        existing_dir(args["root"])
        return {"ok": True, "commands": command_schemas()}
    if operation == "init":
        args['_managed_paths'] = bootstrap_project(init_checkout_identity(args['project'], 'project'))
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
    if operation in ("status", "list", "context"):
        if args.get("task_id"):
            state, _ = load_events(task_dir(store, args["task_id"]))
            result = {"ok": True, "state": state, "summary": summary(state), "session_bindings": session_bindings(store)}
            if operation != "context":
                result["resources"] = project_resources(store)
            return result
        tasks = []
        for path in sorted((store / "tasks").iterdir()):
            if path.is_dir() and not path.is_symlink():
                state, _ = load_events(path)
                tasks.append({**summary(state), "dialogue_contract": dialogue_contract(state)})
        return {"ok": True, "tasks": tasks, "session_bindings": session_bindings(store)}
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
        if operation not in ("recover", "bind-session", "task-reopen", "cleanup", "resource-observe", "resource-release-reconcile", "run-reconcile"):
            require_task_open(state)
        if operation == "recover":
            project_state(path, state)
            with lock(Path(state["project"]["common_dir"]) / "task-workflow-integration.lock"):
                register_root(root, state)
            return {"ok": True, "state": state, "summary": summary(state), "recovered": True}
        if operation == "bind-session":
            require_coordinator(args, state)
            text_value(args['session_id'])
            if state.get('session_id') not in (None, args['session_id']):
                fail('session_conflict', 'The task is already bound to another session.')
            if state.get('session_id') == args['session_id'] and session_bindings(store).get(args['session_id']) == state['task_id']:
                return {'ok': True, 'state': state, 'summary': summary(state), 'already_bound': True}
            state['session_id'] = args['session_id']
            state['session_binding'] = {'session_id': args['session_id'], 'selected_at': now()}
        elif operation == "experiment-create":
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
        elif operation.startswith("process-"):
            result = apply_process(operation, args, state)
        elif operation == "design":
            require_legacy_process(state)
            state["design"] = {"version": (state["design"]["version"] + 1) if state["design"] else 1,
                               "content": args["content"], "digest": digest(args["content"]), "actor": args["actor"], "time": now()}
            state["approval"] = None
            for item in state["items"].values():
                item.update(status="pending", implementer=None, submitted=None, verifications=[], review=None, acceptance=None)
            invalidate_integration(state)
        elif operation == "approve":
            require_legacy_process(state)
            if not state["design"] or args["design_digest"] != state["design"]["digest"]:
                fail("stale_design", "Approval must name the current exact design digest.")
            state["approval"] = {"digest": args["design_digest"], "actor": args["actor"], "authorization_source": args["authorization_source"], "time": now()}
        elif operation == "item-add":
            require_legacy_process(state)
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
            result = run(args["argv"], cwd=project, timeout=args.get("timeout"))
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
            require_legacy_process(state)
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
        if operation == 'bind-session':
            register_root(root, state, select_session=True)
        return {"ok": True, "state": state, "summary": summary(state), **result}


def dispatch(operation, arguments):
    """Attach the dialogue contract to every successful task-bearing result."""
    result = _dispatch(operation, arguments)
    if result.get("ok") is not True:
        return result
    state = result.get("state")
    task_id = arguments.get("task_id") or result.get("resource", {}).get("owner_task_id")
    if not isinstance(state, dict) and task_id:
        _, store = store_dir(arguments["root"])
        state, _ = load_events(task_dir(store, task_id))
    if isinstance(state, dict):
        result["dialogue_contract"] = dialogue_contract(state)
    if operation == "context":
        return {key: value for key, value in result.items() if key != "state" and key != "resources"}
    return result


COMMANDS = {
    "schema": spec("Discover operation schemas."),
    "init": spec("Explicitly enroll an existing task worktree or a base placeholder awaiting worktree-prepare.", {"task_id": "string", "title": "string", "actor": "string", "authorization_source": "string", "project": "string"}, {"worktree": "string", "coordinator": "string", "environment_registry": "object", "owned_worktree": "boolean", "integration_required": "boolean", "session_id": "string"}),
    "worktree-prepare": mutation("Explicitly create or reuse this task's reserved development worktree; path is project/.worktrees/task-id.", {"expected_base": "string", "authorization_source": "string"}, {"branch": "string"}),
    "status": spec("Read authoritative task state without modifying it.", optional={"task_id": "string"}),
    "context": spec("Read the current task dialogue contract and required recording steps without modifying state.", {"task_id": "string"}),
    "list": spec("List task summaries without modifying state."),
    "recover": mutation("Validate events and rebuild state and record projections."),
    "bind-session": mutation("Explicitly select this enrolled task for its known host session. Preserve historical task associations and reject changing the task's session.", {"session_id": "string"}),
    "design": mutation("Record a new design and invalidate prior approval/evidence.", {"content": "string"}),
    "approve": mutation("Record explicit user authorization for the exact design digest.", {"design_digest": "string", "authorization_source": "string"}),
    "item-add": mutation("Add a pending implementation or overall verification item.", {"item_id": "string", "title": "string"}, {"overall": "boolean", "owned_paths": "array"}),
    "item-reopen": mutation("Reopen an item with an explicit reason while preserving its audit history.", {"item_id": "string", "reason": "string"}),
    "integration-verify": mutation("Execute actual validation against the clean integrated base commit.", {"argv": "array"}, {"timeout": "integer"}),
    "item-start": mutation("Begin an approved item.", {"item_id": "string"}),
    "item-submit": mutation("Submit a clean committed Git revision for review.", {"item_id": "string"}),
    "verify": mutation("Execute an argv check and bind its actual outcome to design and Git revision.", {"item_id": "string", "argv": "array"}, {"timeout": "integer"}),
    "item-review": mutation("Record independent review of the current submitted revision; structured tasks require separate requirements and quality verdicts.", {"item_id": "string", "verdict": "string", "notes": "string"}, {"requirements_verdict": "string", "quality_verdict": "string", "findings": "array", "unverified": "array"}),
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
    "resource-register": mutation("Register an opaque project resource with ownership and observation evidence.", {"resource_id": "string", "handle": "string", "provided_by": "string", "can_release": "boolean", "authorization_source": "string", "ownership_evidence": "array", "capabilities": "object", "observed_state": "string", "evidence": "array"}, {"valid_for_seconds": "integer"}),
    "resource-observe": mutation("Record observed resource facts and an optional explicitly sourced permission correction.", {"resource_id": "string", "expected_resource_version": "integer", "capabilities": "object", "observed_state": "string", "evidence": "array"}, {"valid_for_seconds": "integer", "can_release": "boolean", "authorization_source": "string"}),
    "resource-status": spec("Project resource facts and derived release eligibility.", {"resource_id": "string"}),
    "resource-release": mutation("Record explicit release intent before one supplied release action.", {"resource_id": "string", "expected_resource_version": "integer", "eligibility_key": "string", "authorization_source": "string", "argv": "array"}, {"timeout": "integer"}),
    "resource-release-reconcile": mutation("Confirm matching release receipt and evidence without repeating release.", {"resource_id": "string", "expected_resource_version": "integer", "token": "string", "evidence": "array"}),
})


def new_process():
    """New enrollments use the structured contract; existing event streams stay legacy."""
    return {"protocol_version": 2, "stage": "exploration", "intent": None, "exploration": None,
            "requirements": [], "questions": [], "playback": None, "decisions": [],
            "design": None, "design_review": None, "design_approval": None,
            "plan": None, "plan_approval": None, "history": [],
            "provenance": {"requirement_origins": {}, "confirmed_requirements": {}, "confirmed_decisions": {}}}


def discussion_bindings(process):
    """Bind discussion summaries and approvals to the facts actually recorded."""
    return {key + "_digest": digest(process[key]) for key in
            ("intent", "exploration", "questions", "requirements", "decisions")}


def playback_is_current(process):
    playback = process.get("playback")
    if not playback:
        return False
    # Existing protocol 2 records did not bind these three fields. Keep them
    # readable; the next discussion mutation requires a fresh complete playback.
    bindings = discussion_bindings(process)
    return all(playback.get(key) == value for key, value in bindings.items()
               if key in playback or key in ("requirements_digest", "decisions_digest"))


def question_digest(question):
    return digest({key: value for key, value in question.items()
                   if key not in ("status", "answer", "actor", "time", "answer_history")})


def unresolved_unknowns(process):
    resolved = {unknown for question in process["questions"] if question["status"] == "resolved"
                for unknown in question.get("unknowns", [])}
    return [unknown for unknown in (process.get("exploration") or {}).get("unknowns", [])
            if unknown not in resolved]


def unrecorded_choices(process):
    """A reply to structured choices needs a sourced decision before design."""
    return [question["id"] for question in process["questions"]
            if question["status"] == "resolved" and question.get("choices")
            and not any(entry.get("question_id") == question["id"] and entry["status"] == "confirmed"
                        for entry in process["decisions"])]


def dialogue_contract(state):
    """Return the current reply and recording obligations without model inference."""
    process = state.get("process")
    stage = (process or {}).get("stage", "legacy")
    contract = {"contract_version": 1, "task_id": state["task_id"], "state_version": state["version"],
        "stage": stage, "pending_questions": [], "latest_answer": None, "missing_records": [],
        "required_recording_steps": [], "reply_fields": [], "wait_for": None,
        "turn_exit": "Continue only the current authorized action.", "approval_target": None,
        "allowed_next_operations": ["context", "status"],
        "operation_scope": "allowed_next_operations guides dialogue and context steps for the current phase. It is not an exhaustive list of task, review, run, resource, integration or lifecycle operations. Those operations follow the current schema, actual program guards and existing user authorization. A closed task still requires authorized reopening before its work can change.",
        "templates": ["templates/conversation.md", "templates/record.md"],
        "applicability": "Apply this stage contract to related workflow work. The current user request determines scope. For a progress or status question, inspect and answer only; do not advance the stage or force a design question.",
        "recording_rule": "Record actual findings, questions, answers and decisions with their original source references before dependent work. A successful write and its returned state version are required. Never invent an answer, confirmation or approval. Preserve raw source data.",
        "authority_rule": "Allowed operations describe recorded prerequisites, not user authorization. Hook delivery grants no authorization."}
    entrypoint = Path(__file__).resolve()
    skill_root = entrypoint.parent.parent
    runtime = {"workflow_entrypoint": str(entrypoint)}
    if (skill_root / "SKILL.md").is_file():
        runtime["main_skill"] = str(skill_root / "SKILL.md")
        runtime["template_paths"] = [str(skill_root / name) for name in contract["templates"]
                                     if (skill_root / name).is_file()]
    contract["current_runtime"] = runtime
    contract["recovery_rule"] = "Use the current runtime entrypoint or current native workflow tools. When recovering or upgrading an existing chat, read the current main skill and stage templates before workflow progress; retained older code and guidance can be stale."
    if not process:
        contract["reply_fields"] = ["Current recorded result", "Next authorized action"]
        return contract

    def missing(name, operation, instruction):
        contract["missing_records"].append(name)
        contract["required_recording_steps"].append({"operation": operation, "instruction": instruction})

    pending = process_pending(process)
    contract["pending_questions"] = [{**copy.deepcopy(question), "question_digest": question_digest(question)}
                                     for question in pending]
    resolved = [question for question in process["questions"] if question["status"] == "resolved" and question.get("answer")]
    if resolved:
        question = resolved[-1]
        latest = {"question_id": question["id"], "question_text": question["text"],
                  "answer": copy.deepcopy(question["answer"]),
                  "linked_decisions": [copy.deepcopy(entry) for entry in process["decisions"]
                                       if entry.get("question_id") == question["id"]]}
        selected = next((choice for choice in question.get("choices", [])
                         if choice["id"] == question["answer"].get("choice_id")), None)
        if selected is not None:
            latest["selected_choice"] = copy.deepcopy(selected)
        contract["latest_answer"] = latest
    if not process["intent"]:
        missing("intent", "process-intent", "Record the user's goal, reason and success criteria with the actual user source.")
    elif not process["exploration"]:
        missing("exploration", "process-exploration", "Record inspected behavior, evidence references and current unknowns.")
    if stage in ("exploration", "discussion"):
        if process["intent"]:
            contract["allowed_next_operations"].append("process-exploration")
        contract["allowed_next_operations"].append("process-intent")
        if process["intent"] and process["exploration"]:
            contract["allowed_next_operations"].append("process-decision")
            if pending:
                contract["allowed_next_operations"].append("process-answer")
            else:
                if not unrecorded_choices(process):
                    contract["allowed_next_operations"] += ["process-question", "process-requirements"]
                if not unresolved_unknowns(process) and not unrecorded_choices(process):
                    contract["allowed_next_operations"].append("process-playback")
        for question in pending:
            missing("answer:" + question["id"], "process-answer", "Record the actual reply to " + question["id"] + " with its source before proceeding.")
        for unknown in unresolved_unknowns(process):
            missing("unknown:" + unknown, "process-exploration", "Investigate this factual unknown or link it to one sourced question: " + unknown)
        for question_id in unrecorded_choices(process):
            missing("decision:" + question_id, "process-decision", "Record the actual outcome as a confirmed decision linked to " + question_id + " and its answer source; preserve agent proposals separately.")
        if process["exploration"] and not pending:
            if not process["requirements"]:
                missing("requirements", "process-requirements", "Record the confirmed scope, constraints and acceptance requirements.")
            for entry in process["requirements"]:
                if entry["status"] != "confirmed":
                    missing("requirement_confirmation:" + entry["id"], "process-requirements", "Obtain and record actual confirmation for " + entry["id"] + ".")
            if process["requirements"] and not any(entry["kind"] == "acceptance" for entry in process["requirements"]):
                missing("acceptance_requirement", "process-requirements", "Record an observable acceptance requirement with its actual source.")
            for entry in process["decisions"]:
                if entry["status"] == "proposed":
                    missing("decision_confirmation:" + entry["id"], "process-decision", "Resolve the recorded proposal through a sourced confirmation or rejection.")
            if not playback_is_current(process):
                missing("playback", "process-playback", "Present current confirmed requirements and choices separately from proposals; record the actual user confirmation.")
            if not contract["missing_records"]:
                contract["allowed_next_operations"].append("process-design")

    history = process.get("history", [])
    answer_index = max((index for index, entry in enumerate(history) if entry["operation"] == "process-answer"), default=-1)
    reset_index = max((index for index, entry in enumerate(history)
                       if entry["operation"] in ("process-intent", "process-exploration", "process-reenter")), default=-1)
    answered = answer_index > reset_index
    reentry = bool(pending and any(entry["operation"] == "process-reenter"
                                  and entry.get("entry_id") == pending[0]["id"] for entry in history))
    if stage == "exploration":
        contract["dialogue_mode"] = "first_reply"
        contract["reply_fields"] = ["User goal and why it matters", "Inspected findings, sources and impact", "Correction invitation and one useful question when a user decision is needed"]
    elif stage == "discussion":
        if pending:
            fields = (["What the recorded answer settled", "Meaningful new findings and impact"] if answered else
                      ["User goal and why it matters", "Inspected findings, sources and impact"])
            question_field = "One next recorded question and its consequence" if answered else "Correction invitation and one recorded question with its consequence"
            contract.update(dialogue_mode="answer_acknowledgment" if answered else "first_reply",
                reply_fields=fields + ["Recorded choices and consequences, when present", "Agent proposal clearly attributed, when useful", question_field],
                wait_for="The user's answer to " + pending[0]["id"], turn_exit="Ask the one recorded question and end the turn. Record the actual answer on the next related prompt before dependent work.")
            if reentry and not answered:
                contract.update(dialogue_mode="reentry", reply_fields=["New fact and its source", "Affected confirmed design or delegated scope", "One recorded question and its consequence"])
            if pending[0].get("purpose", "clarification") == "playback_confirmation":
                contract.update(dialogue_mode="playback",
                    reply_fields=["Confirmed user requirements and choices with sources", "Agent proposals", "Delegated choices and authority", "Remaining unknowns and a request to confirm this playback"],
                    wait_for="The user's confirmation or correction of the recorded playback",
                    turn_exit="Present the recorded playback in this order, ask its one confirmation question and end the turn. Record the actual answer before recording confirmed playback.")
        else:
            contract.update(dialogue_mode="playback",
                reply_fields=["Confirmed user requirements and choices with sources", "Agent proposals", "Delegated choices and authority", "Remaining unknowns and a request to confirm this playback"],
                wait_for="An answer or confirmation when the presented discussion requires one", turn_exit="If a question or playback confirmation is needed, ask it and end the turn. Otherwise prepare the design from current confirmed records.")
            if not process["requirements"] or unrecorded_choices(process):
                contract["dialogue_mode"] = "answer_acknowledgment" if answered else "first_reply"
                contract["reply_fields"] = (["What the recorded answer settled", "Meaningful new findings and impact", "One next question or the current playback"] if answered else
                    ["User goal and why it matters", "Inspected findings, sources and impact", "Correction invitation and one useful question when a user decision is needed"])
            if playback_is_current(process) and not contract["missing_records"]:
                contract.update(dialogue_mode="design_preparation", wait_for=None,
                    turn_exit="Prepare the design from the current confirmed discussion; obtain independent review before asking for approval.")
    elif stage in ("design", "design_review"):
        contract["reply_fields"] = ["Current design revision and behavior", "Requirement and decision coverage", "Independent review findings", "Required revisions or next review action"]
        contract["allowed_next_operations"] += ["process-design", "process-design-review"] if stage == "design_review" else ["process-design"]
        missing("accepted_design_review", "process-design-review", "Record an independent review of the exact current design revision before requesting design approval.")
    elif stage == "design_confirmation":
        design = process["design"]
        contract["approval_target"] = {"kind": "design", "version": design["version"], "digest": design["digest"]}
        contract.update(reply_fields=["Reviewed design revision and source", "Selected behavior and meaningful effects", "Review outcome", "Approval request for this exact design revision"],
            wait_for="Explicit user approval of the displayed design revision", turn_exit="Present the reviewed design, ask for its approval and end the turn.")
        contract["allowed_next_operations"] += ["process-design", "process-design-review", "process-design-approve"]
        missing("design_approval", "process-design-approve", "Record the actual user approval of the exact displayed design digest.")
    elif stage == "plan":
        contract["reply_fields"] = ["Approved design revision", "Implementation items and dependencies", "Verification and review", "Integration and recovery", "Plan revision to confirm"]
        contract["allowed_next_operations"].append("process-plan")
        missing("plan", "process-plan", "Record the implementation plan linked to the approved design before requesting plan approval.")
    elif stage == "plan_confirmation":
        plan = process["plan"]
        contract["approval_target"] = {"kind": "plan", "version": plan["version"], "digest": plan["digest"], "design_digest": plan["design_digest"]}
        contract.update(reply_fields=["Plan revision and approved design", "Owned work and dependencies", "Verification, review, integration and recovery", "Approval request for this exact plan revision"],
            wait_for="Explicit user approval of the displayed implementation plan", turn_exit="Present the plan, ask for its approval and end the turn.")
        contract["allowed_next_operations"] += ["process-plan", "process-plan-approve"]
        missing("plan_approval", "process-plan-approve", "Record the actual user approval of the exact displayed plan digest before implementation.")
    elif stage in ("implementation", "delivery"):
        contract["templates"] += ["templates/worker-briefs.md", "templates/worker-reports.md"]
        if "template_paths" in runtime:
            runtime["template_paths"] = [str(skill_root / name) for name in contract["templates"]
                                         if (skill_root / name).is_file()]
        contract["reply_fields"] = ["Observed result and evidence", "Current verification and review outcome", "Material blocker or next authorized action"]
        if design_is_approved(state) and plan_is_approved(state) and not pending:
            contract["authorized_work"] = "Continue the current authorized action within the approved plan, using its item, execution and review guards."
        else:
            missing("current_approval_dependencies", "process-reenter", "Restore discussion and current design and plan approvals before dependent execution.")
    if process["intent"] and process["exploration"] and not pending and not unrecorded_choices(process):
        contract["allowed_next_operations"].append("process-reenter")
    if state.get("task_lifecycle", {}).get("status") == "complete":
        contract.update(wait_for=None, turn_exit="Report the recorded closed-task result. Reopen only for an authorized new action.",
                        allowed_next_operations=["context", "status", "bind-session", "recover", "task-reopen"])
    mode = contract.get("dialogue_mode")
    sections = ["Result", "Evidence", "Next action"]
    optional = ["Next action"]
    if mode == "first_reply":
        sections, optional = ["Goal", "What I found", "My proposal", "Question"], ["My proposal"]
    elif mode == "answer_acknowledgment":
        sections, optional = ["Settled", "New findings", "My proposal", "Question"], ["New findings", "My proposal"]
    elif mode == "playback":
        sections = ["Your requirements and confirmed choices", "My proposals", "Choices you delegated", "Open questions", "Confirm"]
        optional = ["My proposals", "Choices you delegated", "Open questions"]
    elif mode == "reentry":
        sections, optional = ["New finding", "Impact", "Question"], []
    if stage in ("design", "design_review", "design_confirmation"):
        contract["templates"].append("templates/spec.md")
        sections = ["Spec (Design)", "Intent and success", "Scope", "Current behavior and impact", "Required behavior",
                    "Decisions and authority", "Constraints", "Delegated choices", "Acceptance and failure conditions", "Open questions", "Review"]
        optional = ["Delegated choices", "Open questions"]
        if stage == "design_confirmation":
            sections.append("Approve")
    elif stage in ("plan", "plan_confirmation"):
        contract["templates"] += ["templates/spec.md", "templates/plan.md"]
        sections = ["Plan and approved Spec", "File responsibilities", "Tasks", "Verification and review", "Integration and recovery"]
        optional = ["Integration and recovery"]
        if stage == "plan_confirmation":
            sections.append("Approve")
    elif stage in ("implementation", "delivery"):
        contract["templates"] += ["templates/spec.md", "templates/plan.md"]
        sections, optional = ["Result", "Checks", "Needs attention", "Next"], ["Needs attention"]
    contract["presentation"] = {"layout": "Readable sections with grouped bullets or tables; omit empty optional groups and routine internal chatter.",
        "sections": sections, "optional_sections": optional,
        "question": "Place the concrete question or exact revision approval request in a separate final section when waiting for the user."}
    if "template_paths" in runtime:
        runtime["template_paths"] = [str(skill_root / name) for name in contract["templates"] if (skill_root / name).is_file()]
    return contract


def require_legacy_process(state):
    if state.get("process"):
        fail("structured_operation_required", "Use the structured process operations for this task.")


def process_object(value, fields, optional=()):
    if not isinstance(value, dict) or set(fields) - set(value) or set(value) - set(fields) - set(optional):
        fail("invalid_process", "Structured fields are missing or unknown; use schema and the process templates.")
    return value


def process_strings(value, nonempty=False):
    if not isinstance(value, list) or (nonempty and not value):
        fail("invalid_process", "A structured list is required.")
    for item in value:
        text_value(item)
    if len(set(value)) != len(value):
        fail("invalid_process", "Structured reference lists must not contain duplicates.")
    return value


def process_source(source, user=False):
    process_object(source, ("kind", "reference"))
    if source["kind"] not in ("user", "agent", "evidence") or (user and source["kind"] != "user"):
        fail("source_required", "This transition requires an attributed user source reference." if user else "An attributed source reference is required.")
    text_value(source["reference"])
    return source


def process_confirmation(entry):
    process_source(entry["source"])
    if entry.get("confirmation_source"):
        process_source(entry["confirmation_source"], user=True)
    if entry["status"] == "confirmed" and entry["source"]["kind"] != "user" and not entry.get("confirmation_source"):
        fail("confirmation_required", "An agent proposal needs a separate user confirmation reference; preserve its original source.")


def preserve_origin(old, new, confirmed=None):
    if old and old["source"] != new["source"]:
        fail("origin_changed", "Preserve the original source when revising or confirming an existing entry.")
    baseline = confirmed or (old if old and old.get("status") == "confirmed" else None)
    if baseline and new["status"] == "confirmed":
        content = lambda entry: {key: value for key, value in entry.items() if key not in ("status", "confirmation_source")}
        if content(baseline) != content(new):
            confirmation = new.get("confirmation_source")
            if not confirmation or confirmation == baseline.get("confirmation_source", baseline["source"]):
                fail("confirmation_required", "A changed confirmed entry needs a fresh user confirmation reference; preserve its origin.")
            process_source(confirmation, user=True)


def design_is_approved(state):
    design, approval = state.get("design"), state.get("approval")
    valid = bool(design and approval and approval.get("digest") == design["digest"])
    process = state.get("process")
    if process:
        valid = valid and bool(process["design"] and process["design_approval"]
            and process["design_approval"]["version"] == process["design"]["version"]
            and process["design_approval"]["digest"] == process["design"]["digest"]
            and process["design"]["intent_digest"] == digest(process["intent"])
            and process["design"]["requirements_digest"] == digest(process["requirements"])
            and process["design"]["decisions_digest"] == digest(process["decisions"]))
        if valid:
            valid = all(process["design"].get(key, value) == value
                        for key, value in discussion_bindings(process).items())
    return valid


def plan_is_approved(state):
    process = state.get("process")
    if not process:
        return False
    plan, approval = process["plan"], process["plan_approval"]
    return bool(design_is_approved(state) and plan and approval
                and approval["digest"] == plan["digest"] and approval["version"] == plan["version"]
                and plan["design_digest"] == process["design"]["digest"])


def process_pending(process):
    return [question for question in process["questions"] if question["status"] == "pending"]


def require_process_ready(state):
    process = state["process"]
    if process_pending(process) or process["stage"] not in ("implementation", "delivery"):
        fail("discussion_required", "Resolve the recorded question and confirm the current design and plan before execution.")
    if not plan_is_approved(state):
        fail("plan_approval_required", "Explicit approval of the exact current implementation plan is required.")


def require_discussed(process):
    if not process["intent"] or not process["exploration"]:
        fail("exploration_required", "Record intent and exploration evidence first.")
    if process_pending(process):
        fail("question_pending", "Resolve the current key question before advancing.")
    require_discussion_records(process)
    if not playback_is_current(process):
        fail("playback_required", "Confirm playback of the current requirements and choices before design.")


def require_discussion_records(process):
    if unresolved_unknowns(process):
        fail("unknowns_unresolved", "Investigate the remaining exploration unknowns or resolve their linked questions first.")
    if unrecorded_choices(process):
        fail("decision_record_required", "Record each reply to structured choices as a confirmed decision linked to its actual answer source.")
    for entry in process["decisions"]:
        validate_answer_decision(process, entry)


def process_requirements(process):
    entries = {entry["id"]: entry for entry in process["requirements"]}
    if not entries or any(entry["status"] != "confirmed" for entry in entries.values()):
        fail("requirements_required", "Confirm every in-scope requirement before design.")
    if not any(entry["kind"] == "acceptance" for entry in entries.values()):
        fail("acceptance_required", "Record at least one confirmed acceptance requirement.")
    return entries


def process_refs(values, known, nonempty=False):
    process_strings(values, nonempty)
    if set(values) - set(known):
        fail("unknown_reference", "A structured reference does not name a recorded entry.")


def process_envelope(content, previous, actor, **bindings):
    version = previous["version"] + 1 if previous else 1
    return {"content": content, "version": version,
            "digest": digest({"version": version, "content": content, **bindings}), "actor": actor, "time": now(), **bindings}


def process_scope_digest(state, item, rev):
    """Unchanged requirement/component/plan scopes keep their accepted evidence."""
    process = state["process"]
    plan_item = item.get("plan_item")
    if not plan_item or not process["design"]:
        return "unplanned"
    refs = set(plan_item["requirement_ids"])
    if process["plan"]:
        refs.update(process["plan"]["content"]["shared_requirements"])
    design = process["design"]["content"]
    relevant_decisions = {d["id"] for d in process["decisions"] if refs.intersection(d["scope"]) or not d["scope"]}
    dependencies = {}
    for dependency_id in plan_item["dependencies"]:
        dependency = binding(state, rev, get_item(state, dependency_id))
        dependencies[dependency_id] = {key: dependency[key] for key in ("design_digest", "scope")}
    return digest({"requirements": [r for r in process["requirements"] if r["id"] in refs],
        "dependencies": dependencies,
        "intent": process["intent"],
        "global_design": {key: design[key] for key in ("behavior", "rationale", "impact", "assumptions", "current_impact", "out_of_scope", "failure_conditions") if key in design},
        "components": [c for c in design["components"] if refs.intersection(c["requirement_ids"])],
        "decisions": [d for d in process["decisions"] if refs.intersection(d["scope"]) or not d["scope"]],
        "selected_decisions": [entry_id for entry_id in design["decisions"] if entry_id in relevant_decisions],
        "delegated_scope": [entry_id for entry_id in design["delegated_scope"] if entry_id in relevant_decisions],
        "verification": [v for v in design["verification"] if v["requirement_id"] in refs],
        "plan_item": plan_item,
        "shared_plan": {key: process["plan"]["content"][key] for key in ("shared_requirements", "dependencies", "review_focus")}
            if process["plan"] else None})


def process_question(process, question, actor):
    if not process["intent"] or not process["exploration"]:
        fail("exploration_required", "Record intent and exploration evidence before asking a workflow question.")
    process_object(question, ("id", "text", "rationale", "scope", "important"), ("choices", "unknowns", "source", "purpose"))
    identifier(question["id"])
    text_value(question["text"]); text_value(question["rationale"])
    process_refs(question["scope"], {r["id"] for r in process["requirements"]})
    if type(question["important"]) is not bool:
        fail("invalid_process", "Question importance must be a boolean.")
    if question.get("purpose", "clarification") not in ("clarification", "playback_confirmation"):
        fail("invalid_process", "Question purpose must be clarification or playback_confirmation.")
    if process_pending(process):
        fail("question_pending", "Discuss one key question at a time.")
    if unrecorded_choices(process):
        fail("decision_record_required", "Record the previous reply's actual outcome and source before the next question.")
    if any(q["id"] == question["id"] for q in process["questions"]):
        fail("already_exists", "Question identifiers cannot be reused.")
    if "source" in question:
        process_source(question["source"])
    process_refs(question.get("unknowns", []), set(process["exploration"]["unknowns"]))
    choices = question.get("choices", [])
    if not isinstance(choices, list):
        fail("invalid_process", "Question choices must be a structured list.")
    choice_ids = set()
    for choice in choices:
        process_object(choice, ("id", "text", "consequence", "source"))
        identifier(choice["id"]); text_value(choice["text"]); text_value(choice["consequence"])
        process_source(choice["source"])
        if choice["id"] in choice_ids:
            fail("invalid_process", "Question choice identifiers must be unique.")
        choice_ids.add(choice["id"])
    question.update(status="pending", actor=actor, time=now(), answer=None)
    process["questions"].append(question)
    process.update(stage="discussion", playback=None, design_approval=None, plan_approval=None)


def validate_answer_decision(process, entry):
    """Validate explicit normalized choice links without interpreting raw replies."""
    if "choice_id" in entry and "question_id" not in entry:
        fail("question_required", "A selected decision choice must name its recorded question.")
    if "question_id" not in entry:
        return
    question = next((question for question in process["questions"] if question["id"] == entry["question_id"]), None)
    if not question or question["status"] != "resolved" or not question.get("answer"):
        fail("answer_required", "A linked decision requires the recorded answer to its question.")
    answer = question["answer"]
    if entry["status"] == "confirmed":
        authority = entry.get("confirmation_source", entry["source"])
        if authority != answer["source"] or authority["kind"] != "user":
            fail("answer_source_mismatch", "The linked decision must use the actual user answer source as its confirmation.")
    if answer.get("choice_id") is not None:
        choice = next((choice for choice in question["choices"] if choice["id"] == answer.get("choice_id")), None)
        if not choice or entry.get("choice_id") != choice["id"] or entry["choice"] != choice["text"]:
            fail("answer_choice_mismatch", "The normalized decision must match the persisted selected option identifier and text.")
    elif "choice_id" in entry:
        fail("answer_choice_mismatch", "A freeform answer did not select a recorded option; preserve its actual source without inventing an option selection.")


def validate_delegated_choice(entry, decisions):
    authority = decisions.get(entry.get("delegation_id"))
    if not authority or authority["id"] == entry["id"] or authority["status"] != "confirmed" or not authority.get("delegates") or not set(entry["scope"]).issubset(authority["scope"]):
        fail("delegation_required", "A delegated choice needs explicit confirmed authority covering its requirement scope.")


def validate_process_design(process, design):
    process_object(design, ("behavior", "components", "decisions", "rationale", "impact", "current_impact", "out_of_scope", "failure_conditions", "assumptions", "verification", "unresolved", "delegated_scope"))
    requirements = process_requirements(process)
    decisions = {entry["id"]: entry for entry in process["decisions"]}
    for entry in decisions.values():
        if entry["status"] != "rejected":
            process_refs(entry["scope"], requirements)
        if entry["status"] == "delegated":
            validate_delegated_choice(entry, decisions)
    for key in ("behavior", "rationale", "impact", "current_impact"):
        text_value(design[key])
    for key in ("assumptions", "out_of_scope", "failure_conditions"):
        process_strings(design[key])
    for key in ("decisions", "unresolved", "delegated_scope"):
        process_refs(design[key], decisions)
    if design["unresolved"] or any(d["status"] == "proposed" for d in decisions.values()) or any(decisions[x]["status"] not in ("confirmed", "delegated") for x in design["decisions"]):
        fail("unresolved_decisions", "Resolve important design choices through discussion or recorded delegation before review.")
    if any(decisions[x]["status"] != "confirmed" or not decisions[x].get("delegates") for x in design["delegated_scope"]):
        fail("delegation_required", "Delegated scope must reference confirmed authority decisions.")
    if not isinstance(design["components"], list) or not design["components"]:
        fail("invalid_process", "A design needs structured components.")
    covered, ids = set(), set()
    for component in design["components"]:
        process_object(component, ("id", "requirement_ids", "behavior", "interfaces", "files"))
        identifier(component["id"]); text_value(component["behavior"])
        if component["id"] in ids:
            fail("invalid_process", "Component identifiers must be unique.")
        ids.add(component["id"])
        process_refs(component["requirement_ids"], requirements, True)
        covered.update(component["requirement_ids"])
        process_strings(component["interfaces"]); process_strings(component["files"], True)
        for filename in component["files"]:
            safe_relative(filename)
    checked = set()
    if not isinstance(design["verification"], list):
        fail("invalid_process", "Design verification must be a structured list.")
    for check in design["verification"]:
        process_object(check, ("requirement_id", "method", "expected_result"))
        process_refs([check["requirement_id"]], requirements)
        text_value(check["method"]); text_value(check["expected_result"])
        checked.add(check["requirement_id"])
    if set(requirements) - covered or set(requirements) - checked:
        fail("requirement_coverage", "Every requirement needs a design component and an expected verification result.")


def validate_process_plan(process, plan):
    process_object(plan, ("shared_requirements", "dependencies", "review_focus", "items"))
    requirements = process_requirements(process)
    process_refs(plan["shared_requirements"], requirements)
    process_strings(plan["dependencies"]); text_value(plan["review_focus"])
    if not isinstance(plan["items"], list) or not plan["items"]:
        fail("invalid_process", "A plan needs at least one implementation item.")
    components = {component["id"]: component for component in process["design"]["content"]["components"]}
    covered, ids, covered_components = set(), set(), set()
    for item in plan["items"]:
        process_object(item, ("id", "title", "requirement_ids", "component_ids", "deliverables", "files", "file_changes", "interfaces", "dependencies", "steps", "verification", "acceptance"))
        identifier(item["id"]); text_value(item["title"])
        if item["id"] == "overall" or item["id"] in ids:
            fail("invalid_process", "Plan item identifiers must be unique and cannot use overall.")
        ids.add(item["id"])
        process_refs(item["requirement_ids"], requirements, True)
        covered.update(item["requirement_ids"])
        process_refs(item["component_ids"], components, True)
        covered_components.update(item["component_ids"])
        component_requirements = {ref for component_id in item["component_ids"] for ref in components[component_id]["requirement_ids"]}
        if set(item["requirement_ids"]) - component_requirements:
            fail("requirement_coverage", "Each work item must map its requirements to the selected Spec components.")
        for key in ("deliverables", "files", "interfaces", "dependencies", "acceptance"):
            process_strings(item[key], key in ("deliverables", "files", "acceptance"))
        for filename in item["files"]:
            safe_relative(filename)
        if not isinstance(item["file_changes"], list):
            fail("invalid_process", "Each work item needs a structured file responsibility map.")
        mapped = set()
        for change in item["file_changes"]:
            process_object(change, ("path", "action", "responsibility"))
            safe_relative(change["path"]); text_value(change["responsibility"])
            if change["path"] in mapped or change["action"] not in ("create", "modify", "test", "delete"):
                fail("invalid_process", "File responsibilities need unique paths and a valid action.")
            mapped.add(change["path"])
        if mapped != set(item["files"]):
            fail("file_coverage", "File responsibilities must cover the work item's owned files exactly once.")
        if not isinstance(item["verification"], list) or not item["verification"]:
            fail("invalid_process", "Each plan item needs expected verification results.")
        checks, checked_requirements = set(), set()
        for check in item["verification"]:
            process_object(check, ("id", "kind", "requirement_ids", "targets", "method", "expected_result"), ("argv",))
            identifier(check["id"])
            if check["id"] in checks or check["kind"] not in ("command", "inspection"):
                fail("invalid_process", "Checks need unique identifiers and command or inspection kind.")
            checks.add(check["id"])
            process_refs(check["requirement_ids"], set(item["requirement_ids"]) | set(plan["shared_requirements"]), True)
            checked_requirements.update(check["requirement_ids"])
            process_strings(check["targets"], check["kind"] == "inspection")
            for target in check["targets"]:
                safe_relative(target)
            if check["kind"] == "command":
                if not isinstance(check.get("argv"), list) or not check["argv"]:
                    fail("invalid_process", "Command checks require a nonempty executable argv.")
                for argument in check["argv"]:
                    text_value(argument)
            elif "argv" in check:
                fail("invalid_process", "Inspection checks declare source targets instead of executable argv.")
            text_value(check["method"]); text_value(check["expected_result"])
        if set(item["requirement_ids"]) - checked_requirements:
            fail("requirement_coverage", "Every work item requirement needs a named check and expected outcome.")
        if not isinstance(item["steps"], list) or not item["steps"]:
            fail("invalid_process", "Each work item needs structured actions linked to files and checks.")
        steps, acted_files, acted_interfaces, linked_checks = set(), set(), set(), set()
        for step in item["steps"]:
            process_object(step, ("id", "action", "files", "interfaces", "verification_ids"))
            identifier(step["id"]); text_value(step["action"])
            if step["id"] in steps:
                fail("invalid_process", "Action identifiers must be unique within their work item.")
            steps.add(step["id"])
            process_refs(step["files"], set(item["files"]), True)
            process_refs(step["interfaces"], set(item["interfaces"]))
            process_refs(step["verification_ids"], checks, True)
            acted_files.update(step["files"]); acted_interfaces.update(step["interfaces"])
            linked_checks.update(step["verification_ids"])
        if acted_files != set(item["files"]):
            fail("file_coverage", "Every owned file must appear in a concrete work item action.")
        if linked_checks != checks:
            fail("check_coverage", "Every planned check must be linked from an action.")
        if acted_interfaces != set(item["interfaces"]):
            fail("interface_coverage", "Every declared work item interface must appear in an action.")
    if set(requirements) - covered:
        fail("requirement_coverage", "The implementation plan must cover every confirmed requirement.")
    if set(components) - covered_components:
        fail("component_coverage", "The implementation plan must cover every approved Spec component.")
    graph = {item["id"]: item["dependencies"] for item in plan["items"]}
    def visit(item_id, ancestors):
        if item_id in ancestors:
            fail("dependency_cycle", "Implementation dependencies must not form a cycle.")
        for dependency in graph[item_id]:
            if dependency not in graph:
                fail("unknown_reference", "An item dependency does not name a planned item.")
            visit(dependency, ancestors | {item_id})
    for item_id in graph:
        visit(item_id, set())


def apply_process(operation, args, state):
    require_coordinator(args, state) if operation != "process-design-review" else None
    process = state.get("process")
    if operation == "process-upgrade":
        if process:
            fail("already_upgraded", "This task already uses the structured process contract.")
        process = new_process()
        process["history"].append({"operation": operation, "actor": args["actor"], "time": now(),
            "authorization_source": args["authorization_source"], "previous_state_version": state["version"],
            "legacy_design_digest": (state.get("design") or {}).get("digest")})
        state["process"] = process
        return {"process": process}
    if not process or process.get("protocol_version") != 2:
        fail("process_upgrade_required", "Existing tasks retain the legacy contract until an explicitly authorized process-upgrade.")
    before_stage = process["stage"]
    stage = process["stage"]
    if operation == "process-intent":
        if stage not in ("exploration", "discussion"):
            fail("discussion_required", "Return to discussion before revising intent.")
        entry = args["intent"]
        process_object(entry, ("goal", "why", "success_criteria", "source"))
        text_value(entry["goal"]); text_value(entry["why"])
        process_strings(entry["success_criteria"], True); process_source(entry["source"], user=True)
        if process["intent"] and process["intent"] != entry and process["intent"]["source"] == entry["source"]:
            fail("confirmation_required", "A revised intent needs a new user source reference.")
        process.update(intent=entry, playback=None, design_approval=None, plan_approval=None)
        state["approval"] = None
    elif operation == "process-exploration":
        if stage not in ("exploration", "discussion") or not process["intent"]:
            fail("exploration_required", "Record intent and enter exploration or discussion before adding findings.")
        entry = args["exploration"]
        process_object(entry, ("current_behavior", "evidence", "unknowns"))
        text_value(entry["current_behavior"]); process_strings(entry["evidence"], True); process_strings(entry["unknowns"])
        process.update(exploration=entry, stage="discussion", playback=None, design_approval=None, plan_approval=None)
        state["approval"] = None
    elif operation in ("process-question", "process-reenter"):
        if operation == "process-question" and stage not in ("exploration", "discussion"):
            fail("discussion_required", "Use process-reenter when the approved design and delegation cannot settle the next action.")
        process_question(process, args["question"], args["actor"])
    elif operation == "process-answer":
        questions = [q for q in process_pending(process) if q["id"] == args["question_id"]]
        if not questions:
            fail("question_required", "Answer the current pending question.")
        question = questions[0]
        if args.get("question_digest", question_digest(question)) != question_digest(question):
            fail("stale_question", "Record an answer against the currently displayed question and choices.")
        process_source(args["source"], user=questions[0]["important"])
        text_value(args["answer"])
        choice_id = args.get("choice_id")
        if question.get("choices") and choice_id is not None:
            if choice_id not in {choice["id"] for choice in question["choices"]}:
                fail("choice_required", "An explicit selected option must name one of the recorded question choices.")
        elif choice_id is not None:
            fail("unknown_reference", "The question has no recorded option with this identifier.")
        answer = {"text": args["answer"], "source": args["source"], "actor": args["actor"], "time": now(),
                  "question_digest": question_digest(question)}
        if choice_id is not None:
            answer["choice_id"] = choice_id
        question.update(status="resolved", answer=answer)
        process["playback"] = None
    elif operation == "process-playback":
        if stage != "discussion" or not process["exploration"] or process_pending(process):
            fail("question_pending", "Complete exploration and resolve the current question before playback.")
        require_discussion_records(process)
        text_value(args["summary"]); process_source(args["confirmation_source"], user=True)
        process["playback"] = {"summary": args["summary"], "confirmation_source": args["confirmation_source"], "time": now(),
            **discussion_bindings(process)}
    elif operation == "process-requirements":
        if not process["intent"] or not process["exploration"] or process_pending(process):
            fail("exploration_required", "Complete exploration and the pending question before recording requirements.")
        if stage != "discussion":
            fail("discussion_required", "Return to discussion before revising requirements.")
        if unrecorded_choices(process):
            fail("decision_record_required", "Record the selected choice before deriving requirements from it.")
        entries = args["requirements"]
        if not entries:
            fail("requirements_required", "Record structured requirements.")
        old = {entry["id"]: entry for entry in process["requirements"]}
        provenance = process["provenance"]
        ids = set()
        for entry in entries:
            process_object(entry, ("id", "text", "kind", "status", "source"), ("confirmation_source",))
            identifier(entry["id"]); text_value(entry["text"])
            if entry["id"] in ids or entry["kind"] not in ("scope", "constraint", "acceptance") or entry["status"] not in ("proposed", "confirmed"):
                fail("invalid_process", "Requirement identifiers, kind or status are invalid.")
            ids.add(entry["id"])
            prior = old.get(entry["id"], provenance["requirement_origins"].get(entry["id"]))
            preserve_origin(prior, entry, provenance["confirmed_requirements"].get(entry["id"]))
            process_confirmation(entry)
            provenance["requirement_origins"].setdefault(entry["id"], {"source": copy.deepcopy(entry["source"])})
            if entry["status"] == "confirmed":
                provenance["confirmed_requirements"][entry["id"]] = copy.deepcopy(entry)
        process["requirements"] = entries
        process["playback"] = None
    elif operation == "process-decision":
        if stage != "discussion":
            fail("discussion_required", "Record and confirm important choices during discussion.")
        entry = args["decision"]
        process_object(entry, ("id", "title", "choice", "rationale", "scope", "status", "source"), ("confirmation_source", "delegation_id", "delegates", "question_id", "choice_id"))
        identifier(entry["id"])
        for key in ("title", "choice", "rationale"):
            text_value(entry[key])
        process_refs(entry["scope"], {r["id"] for r in process["requirements"]})
        if entry["status"] not in ("proposed", "confirmed", "delegated", "rejected"):
            fail("invalid_process", "Decision status is invalid.")
        old = next((d for d in process["decisions"] if d["id"] == entry["id"]), None)
        preserve_origin(old, entry, process["provenance"]["confirmed_decisions"].get(entry["id"]))
        process_confirmation(entry)
        validate_answer_decision(process, entry)
        if "delegates" in entry and type(entry["delegates"]) is not bool:
            fail("invalid_process", "Delegation authority must be an explicit boolean.")
        if entry["status"] == "delegated":
            validate_delegated_choice(entry, {d["id"]: d for d in process["decisions"]})
        process["decisions"] = [d for d in process["decisions"] if d["id"] != entry["id"]] + [entry]
        if entry["status"] == "confirmed":
            process["provenance"]["confirmed_decisions"][entry["id"]] = copy.deepcopy(entry)
        process["playback"] = None
    elif operation == "process-design":
        require_discussed(process)
        if stage not in ("discussion", "design", "design_review", "design_confirmation"):
            fail("discussion_required", "Return to discussion before changing an approved design.")
        validate_process_design(process, args["design"])
        process["design"] = process_envelope(args["design"], process["design"], args["actor"],
            **discussion_bindings(process))
        process.update(stage="design_review", design_review=None, design_approval=None, plan_approval=None)
        state["design"] = {**process["design"], "content": json.dumps(args["design"], indent=2)}
        state["approval"] = None
        invalidate_overall(state); invalidate_integration(state)
    elif operation == "process-design-review":
        design = process["design"]
        if stage not in ("design_review", "design_confirmation") or not design or args["design_digest"] != design["digest"]:
            fail("stale_design", "Review the exact current design after discussion.")
        if args["actor"] in (design["actor"], state["coordinator"]):
            fail("independent_review_required", "The design gap reviewer must differ from the design author and coordinator.")
        if args["verdict"] not in ("accept", "changes"):
            fail("invalid_verdict", "Review verdict must be accept or changes.")
        process_strings(args["evidence"], True)
        process["design_review"] = {"digest": design["digest"], "version": design["version"],
            "actor": args["actor"], "verdict": args["verdict"], "notes": args["notes"], "evidence": args["evidence"], "time": now()}
        process["stage"] = "design_confirmation" if args["verdict"] == "accept" else "design"
    elif operation == "process-design-approve":
        require_discussed(process)
        design, review = process["design"], process["design_review"]
        if not design or args["design_digest"] != design["digest"]:
            fail("stale_design", "Approval must name the current exact design digest.")
        if stage != "design_confirmation" or not review or review["digest"] != design["digest"] or review["version"] != design["version"] or review["verdict"] != "accept":
            fail("design_review_required", "Complete an independent gap review before user design confirmation.")
        if any(design.get(key, value) != value for key, value in discussion_bindings(process).items()):
            fail("stale_design", "Requirements or decisions changed after the design; revise and review it again.")
        approval = {"digest": design["digest"], "version": design["version"], "actor": args["actor"], "authorization_source": args["authorization_source"], "time": now()}
        process.update(design_approval=approval, stage="plan")
        state["approval"] = copy.deepcopy(approval)
    elif operation == "process-plan":
        if not design_is_approved(state) or stage not in ("plan", "plan_confirmation"):
            fail("approval_required", "Confirm the current design before preparing its implementation plan.")
        validate_process_plan(process, args["plan"])
        process["plan"] = process_envelope(args["plan"], process["plan"], args["actor"], design_digest=process["design"]["digest"])
        process.update(stage="plan_confirmation", plan_approval=None)
    elif operation == "process-plan-approve":
        plan = process["plan"]
        if not plan or args["plan_digest"] != plan["digest"] or not design_is_approved(state) or plan["design_digest"] != process["design"]["digest"]:
            fail("stale_plan", "Approval must name the exact current plan for the approved design.")
        if stage != "plan_confirmation" or process_pending(process):
            fail("plan_approval_required", "Complete the current discussion and prepare the implementation plan first.")
        process["plan_approval"] = {"digest": plan["digest"], "version": plan["version"], "actor": args["actor"], "authorization_source": args["authorization_source"], "time": now()}
        planned = {item["id"]: item for item in plan["content"]["items"]}
        for item_id in list(state["items"]):
            if not state["items"][item_id]["overall"] and item_id not in planned:
                state.setdefault("item_history", []).append({"id": item_id, "item": state["items"].pop(item_id), "time": now()})
        for item_id, entry in planned.items():
            item = state["items"].get(item_id)
            if not item or item.get("plan_item") != entry:
                if item:
                    state.setdefault("item_history", []).append({"id": item_id, "item": copy.deepcopy(item), "time": now()})
                item = make_item(entry["title"], owned_paths=entry["files"])
                state["items"][item_id] = item
            item["plan_item"] = copy.deepcopy(entry)
        process["stage"] = "implementation"
        invalidate_overall(state); invalidate_integration(state)
    else:
        fail("unsupported", "Unknown structured process operation.")
    # Immutable events preserve prior structures; the readable index references them.
    process["history"].append({"operation": operation, "actor": args["actor"], "time": now(),
        "from_stage": before_stage, "to_stage": process["stage"],
        "reason": args.get("reason"), "previous_state_version": state["version"],
        "state_version": state["version"] + 1,
        "entry_id": args.get("decision", args.get("question", {})).get("id", args.get("question_id")),
        "source": args.get("source", args.get("confirmation_source", args.get("decision", {}).get("source"))),
        "authorization_source": args.get("authorization_source"),
        "design_digest": (process["design"] or {}).get("digest"), "plan_digest": (process["plan"] or {}).get("digest")})
    return {"process": process}


PROCESS_COMMANDS = {
    "process-upgrade": ({"authorization_source": "string"}, "Explicitly upgrade a legacy task; new structured approvals are required."),
    "process-intent": ({"intent": "object"}, "Record sourced goal, reason and success criteria."),
    "process-exploration": ({"exploration": "object"}, "Record current behavior, evidence and unknowns."),
    "process-question": ({"question": "object"}, "Discuss one key question at a time."),
    "process-answer": ({"question_id": "string", "answer": "string", "source": "object"}, "Record a sourced answer to the pending key question."),
    "process-playback": ({"summary": "string", "confirmation_source": "object"}, "Record the user's confirmation of the discussion playback."),
    "process-requirements": ({"requirements": "array"}, "Record requirements with preserved origin and separate confirmation."),
    "process-decision": ({"decision": "object"}, "Record proposed, confirmed or delegated choices with rationale and scope."),
    "process-design": ({"design": "object"}, "Record a complete structured design for independent gap review."),
    "process-design-review": ({"design_digest": "string", "verdict": "string", "notes": "string", "evidence": "array"}, "Record an independent gap review of the exact design version."),
    "process-design-approve": ({"design_digest": "string", "authorization_source": "string"}, "Record explicit user confirmation of the reviewed design."),
    "process-plan": ({"plan": "object"}, "Record linked implementation items and expected verification results."),
    "process-plan-approve": ({"plan_digest": "string", "authorization_source": "string"}, "Record explicit user confirmation of the exact implementation plan."),
    "process-reenter": ({"question": "object", "reason": "string"}, "Return to discussion when current design and delegation cannot settle the next action."),
}
COMMANDS.update({name: mutation(description, fields) for name, (fields, description) in PROCESS_COMMANDS.items()})
COMMANDS["process-answer"]["optional"].update({"choice_id": "string", "question_digest": "string"})


def process_schema(fields, optional=()):
    return {"type": "object", "properties": fields, "required": [key for key in fields if key not in optional], "additionalProperties": False}


_TEXT = {"type": "string", "minLength": 1}
_STRINGS = {"type": "array", "items": _TEXT, "uniqueItems": True}
_SOURCE = process_schema({"kind": {"type": "string", "enum": ["user", "agent", "evidence"]}, "reference": _TEXT})
_USER_SOURCE = process_schema({"kind": {"type": "string", "enum": ["user"]}, "reference": _TEXT})
_CHOICE = process_schema({"id": _TEXT, "text": _TEXT, "consequence": _TEXT, "source": _SOURCE})
_QUESTION = process_schema({"id": _TEXT, "text": _TEXT, "rationale": _TEXT, "scope": _STRINGS, "important": {"type": "boolean"},
    "choices": {"type": "array", "items": _CHOICE}, "unknowns": _STRINGS, "source": _SOURCE,
    "purpose": {"type": "string", "enum": ["clarification", "playback_confirmation"]}}, ("choices", "unknowns", "source", "purpose"))
_CHECK = process_schema({"id": _TEXT, "kind": {"type": "string", "enum": ["command", "inspection"]},
    "requirement_ids": _STRINGS, "targets": _STRINGS, "method": _TEXT, "expected_result": _TEXT,
    "argv": {"type": "array", "items": _TEXT}}, ("argv",))
_STEP = process_schema({"id": _TEXT, "action": _TEXT, "files": _STRINGS, "interfaces": _STRINGS, "verification_ids": _STRINGS})
_FILE_CHANGE = process_schema({"path": _TEXT, "action": {"type": "string", "enum": ["create", "modify", "test", "delete"]}, "responsibility": _TEXT})
_REQUIREMENT = process_schema({"id": _TEXT, "text": _TEXT, "kind": {"type": "string", "enum": ["scope", "constraint", "acceptance"]},
    "status": {"type": "string", "enum": ["proposed", "confirmed"]}, "source": _SOURCE, "confirmation_source": _USER_SOURCE}, ("confirmation_source",))
_DECISION = process_schema({"id": _TEXT, "title": _TEXT, "choice": _TEXT, "rationale": _TEXT, "scope": _STRINGS,
    "status": {"type": "string", "enum": ["proposed", "confirmed", "delegated", "rejected"]}, "source": _SOURCE,
    "confirmation_source": _USER_SOURCE, "delegation_id": _TEXT, "delegates": {"type": "boolean"}, "question_id": _TEXT, "choice_id": _TEXT},
    ("confirmation_source", "delegation_id", "delegates", "question_id", "choice_id"))
_COMPONENT = process_schema({"id": _TEXT, "requirement_ids": _STRINGS, "behavior": _TEXT, "interfaces": _STRINGS, "files": _STRINGS})
_PLAN_ITEM = process_schema({"id": _TEXT, "title": _TEXT, "requirement_ids": _STRINGS, "component_ids": _STRINGS,
    "deliverables": _STRINGS, "files": _STRINGS, "file_changes": {"type": "array", "items": _FILE_CHANGE},
    "interfaces": _STRINGS, "dependencies": _STRINGS, "steps": {"type": "array", "items": _STEP},
    "verification": {"type": "array", "items": _CHECK}, "acceptance": _STRINGS})
PROCESS_SCHEMAS = {
    "process-intent": {"intent": process_schema({"goal": _TEXT, "why": _TEXT, "success_criteria": _STRINGS, "source": _USER_SOURCE})},
    "process-exploration": {"exploration": process_schema({"current_behavior": _TEXT, "evidence": _STRINGS, "unknowns": _STRINGS})},
    "process-question": {"question": _QUESTION}, "process-reenter": {"question": _QUESTION},
    "process-answer": {"source": _SOURCE}, "process-playback": {"confirmation_source": _USER_SOURCE},
    "process-requirements": {"requirements": {"type": "array", "items": _REQUIREMENT}},
    "process-decision": {"decision": _DECISION},
    "process-design": {"design": process_schema({"behavior": _TEXT, "components": {"type": "array", "items": _COMPONENT},
        "decisions": _STRINGS, "rationale": _TEXT, "impact": _TEXT, "current_impact": _TEXT,
        "out_of_scope": _STRINGS, "failure_conditions": _STRINGS, "assumptions": _STRINGS,
        "verification": {"type": "array", "items": process_schema({"requirement_id": _TEXT, "method": _TEXT, "expected_result": _TEXT})},
        "unresolved": _STRINGS, "delegated_scope": _STRINGS})},
    "process-plan": {"plan": process_schema({"shared_requirements": _STRINGS, "dependencies": _STRINGS, "review_focus": _TEXT,
        "items": {"type": "array", "items": _PLAN_ITEM}})},
}


def process_record_text(state):
    process = state["process"]
    lines = [f"# {state['title']}", "", f"Task: `{state['task_id']}` · version {state['version']}", "",
        "Generated from immutable events; edit through the workflow commands."]
    def section(title, value):
        lines.extend(["", "## " + title, ""])
        if not value:
            lines.append("Not recorded.")
        else:
            render(value)
    def label(key):
        return key.replace("_", " ").capitalize()
    def scalar(value):
        if value is None:
            return "Not recorded"
        if isinstance(value, bool):
            return "Yes" if value else "No"
        return str(value)
    def render(value, indent=0):
        prefix = "  " * indent + "- "
        def bullet(content):
            parts = content.splitlines() or [""]
            lines.append(prefix + parts[0])
            lines.extend("  " * (indent + 1) + part for part in parts[1:])
        if isinstance(value, dict):
            for key, entry in sorted(value.items()):
                if isinstance(entry, (dict, list)) and entry:
                    bullet("**" + label(key) + ":**")
                    render(entry, indent + 1)
                else:
                    bullet("**" + label(key) + ":** " + ("None" if entry == [] or entry == {} else scalar(entry)))
        elif isinstance(value, list):
            for entry in value:
                if isinstance(entry, dict):
                    heading = entry.get("title") or entry.get("id") or entry.get("operation") or "Entry"
                    bullet("**" + str(heading) + "**")
                    render(entry, indent + 1)
                else:
                    bullet(scalar(entry))
        else:
            bullet(scalar(value))
    def entry(title, value):
        parts = str(value).splitlines() or [""]
        lines.append("- **" + title + ":** " + parts[0])
        lines.extend("  " + part for part in parts[1:])
    def group(title):
        lines.extend(["", "### " + title, ""])
    def cell(value):
        return str(value).replace("|", "\\|").replace("\r", "").replace("\n", "<br>")
    def table(headers, rows):
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join("---" for _ in headers) + " |")
        lines.extend("| " + " | ".join(cell(value) for value in row) + " |" for row in rows)
    def listed(title, values, absent="None recorded."):
        if values is None:
            entry(title, "Not recorded in this revision.")
        elif values:
            for value in values:
                entry(title, value)
        else:
            entry(title, absent)
    def source(value):
        return value["kind"] + ": " + value["reference"] if value else "Not recorded"
    def requirement_rows(kind):
        return [(item["id"], item["text"], item["status"], source(item["source"]), source(item.get("confirmation_source")))
                for item in process["requirements"] if item["kind"] == kind]
    def artifact_authority(envelope, approval, review=None):
        entry("Revision", str(envelope["version"]) + "; digest " + envelope["digest"])
        entry("Recorded by", envelope["actor"])
        if review:
            entry("Independent review", review["verdict"] + " by " + review["actor"] + ": " + review["notes"])
            listed("Review evidence", review["evidence"])
        if approval:
            entry("Approval source", approval["authorization_source"])
        else:
            entry("Approval", "Pending for this revision.")
    def render_spec():
        lines.extend(["", "## Design", ""])
        envelope = process["design"]
        if not envelope:
            lines.append("Not recorded.")
            return
        design = envelope["content"]
        current = all(envelope.get(key, value) == value for key, value in discussion_bindings(process).items())
        group("Spec (Design) D" + str(envelope["version"]) + ("" if current else " (historical; discussion changed)"))
        artifact_authority(envelope, process["design_approval"], process["design_review"])
        origin = next((item for item in reversed(process["history"]) if item["operation"] == "process-design"
                       and item.get("design_digest") == envelope["digest"]), {})
        version = origin.get("state_version")
        revision_source = ("[Task event " + str(version) + "](events/" + f"{version:08d}.json" + ")"
                           if type(version) is int else "Immutable process-design events for digest " + envelope["digest"])
        entry("Revision source", revision_source)
        if not current:
            entry("Binding status", "Historical Spec content. Current discussion differs and is not approved by this revision. Current intent, exploration, requirements and decisions remain in their own record sections; retrieve the bound context from the revision source.")
        group("Intent and success")
        if current:
            intent = process["intent"] or {}
            entry("Goal", intent.get("goal", "Not recorded")); entry("Why", intent.get("why", "Not recorded"))
            listed("Success criterion", intent.get("success_criteria"))
            entry("Intent source", source(intent.get("source")))
        else:
            entry("Bound intent and success", revision_source)
        group("Scope")
        rows = requirement_rows("scope") if current else []
        if rows:
            table(["Requirement", "In scope", "Status", "Origin", "Confirmation"], rows)
        elif not current:
            entry("Bound scope", revision_source)
        listed("Out of scope", design.get("out_of_scope"))
        group("Current behavior and impact")
        if current:
            exploration = process["exploration"] or {}
            entry("Current behavior", exploration.get("current_behavior", "Not recorded"))
            listed("Evidence", exploration.get("evidence"))
        else:
            entry("Bound exploration", revision_source)
        entry("Current impact", design.get("current_impact", "Not recorded in this revision."))
        entry("Change impact", design["impact"])
        group("Required behavior")
        entry("Behavior", design["behavior"]); entry("Rationale", design["rationale"])
        for component in design["components"]:
            entry("Component " + component["id"], component["behavior"])
            entry("Requirements", ", ".join(component["requirement_ids"]))
            entry("Files", ", ".join(component["files"]))
            if component["interfaces"]:
                entry("Interfaces", "; ".join(component["interfaces"]))
        group("Decisions and authority")
        selected = set(design["decisions"]) | set(design["delegated_scope"])
        decisions = [item for item in process["decisions"] if item["id"] in selected] if current else []
        if not decisions:
            if current or not selected:
                lines.append("No separate decisions selected for this revision.")
            else:
                listed("Selected decision reference", sorted(selected))
                entry("Bound decision authority", revision_source)
        for decision in decisions:
            entry(decision["id"] + " (" + decision["status"] + ")", decision["choice"])
            entry("Rationale", decision["rationale"])
            entry("Origin", source(decision["source"]))
            if decision.get("confirmation_source"):
                entry("Confirmation", source(decision["confirmation_source"]))
            if decision.get("delegation_id"):
                entry("Delegation authority", decision["delegation_id"])
        group("Constraints")
        rows = requirement_rows("constraint") if current else []
        if rows:
            table(["Requirement", "Constraint", "Status", "Origin", "Confirmation"], rows)
        elif not current:
            entry("Bound constraints", revision_source)
        else:
            lines.append("No separate constraints recorded.")
        listed("Assumption", design["assumptions"])
        if design["delegated_scope"]:
            group("Delegated choices")
            if not current:
                listed("Delegation reference", design["delegated_scope"])
                entry("Bound delegation authority", revision_source)
            for decision in decisions:
                if decision["id"] in design["delegated_scope"]:
                    entry(decision["id"], decision["choice"] + "; requirements " + (", ".join(decision["scope"]) or "shared scope"))
        group("Acceptance and failure conditions")
        rows = requirement_rows("acceptance") if current else []
        if rows:
            table(["Requirement", "Acceptance condition", "Status", "Origin", "Confirmation"], rows)
        elif not current:
            entry("Bound acceptance requirements", revision_source)
        table(["Requirement", "Verification", "Expected outcome"],
              [(check["requirement_id"], check["method"], check["expected_result"]) for check in design["verification"]])
        listed("Failure condition", design.get("failure_conditions"))
        group("Open questions")
        listed("Unresolved decision", design["unresolved"])
    def render_plan():
        lines.extend(["", "## Implementation plan", ""])
        envelope = process["plan"]
        if not envelope:
            lines.append("Not recorded.")
            return
        plan = envelope["content"]
        group("Plan P" + str(envelope["version"]))
        artifact_authority(envelope, process["plan_approval"])
        entry("Approved Spec digest", envelope["design_digest"])
        listed("Shared requirement", plan["shared_requirements"])
        listed("External dependency", plan["dependencies"])
        entry("Review focus", plan["review_focus"])
        group("File responsibilities")
        rows = []
        for item in plan["items"]:
            changes = item.get("file_changes", [{"path": path, "action": "Not recorded", "responsibility": "Not recorded in this revision."} for path in item["files"]])
            for change in changes:
                rows.append((change["path"], change["action"], change["responsibility"], item["id"], ", ".join(item.get("component_ids", [])) or "Not recorded"))
        table(["File", "Action", "Responsibility", "Work item", "Spec components"], rows)
        for item in plan["items"]:
            group("Work item " + item["id"])
            entry("Title", item["title"]); entry("Requirements", ", ".join(item["requirement_ids"]))
            listed("Deliverable", item["deliverables"])
            listed("Interface", item["interfaces"])
            listed("Depends on", item["dependencies"])
            lines.extend(["", "**Ordered actions**", ""])
            for number, step in enumerate(item["steps"], 1):
                if isinstance(step, str):
                    entry(str(number), step)
                    continue
                entry(str(number) + ". " + step["id"], step["action"])
                entry("Files", ", ".join(step["files"]))
                if step["interfaces"]:
                    entry("Interfaces", "; ".join(step["interfaces"]))
                entry("Checks", ", ".join(step["verification_ids"]))
            lines.extend(["", "**Checks and expected outcomes**", ""])
            table(["Check", "Method or command", "Read targets", "Requirements", "Expected outcome"],
                  [(check.get("id", "Not recorded"), (json.dumps(check["argv"], ensure_ascii=True) + "; " if "argv" in check else "") + check["method"],
                    ", ".join(check.get("targets", [])) or "Not recorded", ", ".join(check.get("requirement_ids", [])) or "Not recorded", check["expected_result"])
                   for check in item["verification"]])
            listed("Acceptance", item["acceptance"])
    contract = dialogue_contract(state)
    dialogue_state = {key: contract[key] for key in ("pending_questions", "missing_records", "required_recording_steps",
                      "wait_for", "approval_target") if contract[key] is not None}
    section("Current state", {"stage": process["stage"], "process_protocol": process["protocol_version"],
        "state_version": state["version"], "session_id": state.get("session_id"),
        "project": state["project"]["path"], "worktree": state["worktree"]["path"],
        "design_approved": design_is_approved(state), "plan_approved": plan_is_approved(state),
        **dialogue_state})
    section("Intent", process["intent"])
    section("Exploration", process["exploration"])
    section("Confirmed requirements", process["requirements"])
    section("Sourced decisions", process["decisions"])
    render_spec()
    render_plan()
    execution_items = {}
    for item_id, item in state["items"].items():
        projected = {key: value for key, value in item.items() if key != "plan_item"}
        if item.get("plan_item"):
            plan = process["plan"]
            same_revision = plan and any(entry == item["plan_item"] for entry in plan["content"]["items"])
            projected["plan_reference"] = ("Work item " + item_id + " in Plan P" + str(plan["version"]) if same_revision else
                "Work item " + item_id + "; its approved plan revision is preserved in immutable task events.")
        execution_items[item_id] = projected
    section("Execution and review", {"items": execution_items, "worktree_preparation": state.get("worktree_preparation")})
    section("Experiments and runs", {"experiments": state["experiments"], "runs": state["runs"]})
    section("Delivery", {"integration": state["integration"], "task_lifecycle": state.get("task_lifecycle"), "cleaned": state.get("cleaned", False)})
    record_questions = copy.deepcopy(process["questions"])
    for question in record_questions:
        if question.get("answer"):
            question["answer"].pop("text", None)
            question["answer"]["content_reference"] = "Original reply preserved in immutable task events and the cited source."
    section("Decision history", {"questions": record_questions, "playback": process["playback"], "changes": process["history"]})
    return "\n".join(lines) + "\n"


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
