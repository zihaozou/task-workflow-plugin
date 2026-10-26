#!/usr/bin/env python3
"""Execute one previously reserved frozen argv and preserve a durable receipt."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import socket
import subprocess
import workflow as w

EXECUTION_PROTOCOL = 2


def execute(root, task_id, run_id, token, timeout=None):
    _, store = w.store_dir(root)
    path = w.task_dir(store, task_id)
    process = None
    log = None
    with w.lifecycle_lock(store), w.lock(path / 'write.lock'):
        state, previous = w.load_events(path)
        w.require_task_open(state)
        current = w.get_run(state, run_id)
        intent = current.get('execution_intent')
        if current['status'] != 'queued' or current.get('token') != token or not intent:
            w.fail('execution_denied', 'A matching uncompleted dispatch intent is required.')
        if timeout != intent['timeout']:
            w.fail('execution_denied', 'The runner timeout must match the durable execution intent.')
        w.require_execution_protocol(state, current)
        w.check_run(state, current)
        runtime = Path(current['runtime']['directory'])
        if Path(__file__).resolve().parent != runtime:
            w.fail('runtime_changed', 'Execute the pinned runner recorded by this run.')
        w.validate_resource_reference(store, state, {**current, 'run_id': run_id}, require_available=True)
        directory = Path(current['directory'])
        # A permanent claim prevents retries after a crash, including a failed event write.
        claim = directory / 'execution.claim'
        try:
            claim.mkdir()
        except FileExistsError:
            w.fail('execution_claimed', 'This execution was already claimed; reconcile its receipt.')
        w.atomic_json(claim / 'owner.json', {'pid': os.getpid(), 'token': token, 'time': w.now(), 'host': socket.gethostname()})
        w.sync_dir(claim)
        w.sync_dir(directory)
        argv = list(current['argv'])
        environment = dict(os.environ)
        env_path = Path(current['environment']['path'])
        if argv[0] in ('python', 'python3'):
            argv[0] = str(env_path / 'bin/python')
        environment.update(VIRTUAL_ENV=str(env_path), PATH=str(env_path / 'bin') + os.pathsep + environment.get('PATH', ''),
                           PYTHONDONTWRITEBYTECODE='1', TASK_WORKFLOW_RUN_DIR=str(directory), TASK_WORKFLOW_OUTPUT_DIR=str(directory))
        environment.pop('PYTHONPATH', None)
        environment.pop('PYTHONHOME', None)
        log_path = directory / 'execution.log'
        log = open(log_path, 'xb')
        try:
            try:
                process = subprocess.Popen(argv, cwd=current['code'], env=environment, stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=log, shell=False, start_new_session=True)
                code = None
            except OSError:
                code = 127
            current.update(status='running' if process is not None else 'failed', started=w.now(), start_validated={'time': w.now(),
                           'manifest_digest': current['manifest_digest'], 'pid': process.pid if process else None,
                           'runner_pid': os.getpid(), 'host': socket.gethostname()})
            w.commit_event(path, state, previous, 'run-execution-started', intent['actor'])
        except BaseException:
            stop_process(process)
            log.close()
            raise
    with log:
        try:
            if process is not None:
                code = w.wait_with_timeout(lambda seconds: process.wait(timeout=seconds), timeout)
        except subprocess.TimeoutExpired:
            code = 124
        finally:
            stop_process(process)
        log.flush()
        os.fsync(log.fileno())
    receipt = {'token': token, 'returncode': code, 'argv_digest': w.digest(current['argv']),
               'manifest_digest': current['manifest_digest'], 'environment_digest': w.digest(w.environment_identity(current['environment'])),
               'log': str(log_path), 'log_sha256': w.sha_file(log_path), 'time': w.now()}
    w.atomic_json(directory / 'execution-receipt.json', receipt)
    w.sync_dir(directory)
    return receipt


def stop_process(process):
    if process is None:
        return
    # Signal only the new workload process group, including surviving children.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('root', 'task-id', 'run-id', 'token'):
        parser.add_argument('--' + key, required=True)
    parser.add_argument('--timeout', type=int, default=None)
    args = parser.parse_args()
    if args.timeout is not None and args.timeout < 1:
        parser.error('timeout must be positive seconds')
    execute(args.root, args.task_id, args.run_id, args.token, args.timeout)


if __name__ == '__main__':
    main()
