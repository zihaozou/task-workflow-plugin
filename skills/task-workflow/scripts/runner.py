#!/usr/bin/env python3
"""Execute one previously reserved frozen argv and preserve a durable receipt."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import subprocess
import workflow as w


def execute(root, task_id, run_id, token, timeout):
    _, store = w.store_dir(root)
    state, _ = w.load_events(w.task_dir(store, task_id))
    current = w.get_run(state, run_id)
    if current['status'] != 'running' or current.get('token') != token or not current.get('start_validated'):
        w.fail('execution_denied', 'A matching uncompleted execution intent is required.')
    w.check_run(state, current)
    runtime = Path(current['runtime']['directory'])
    if Path(__file__).resolve().parent != runtime:
        w.fail('runtime_changed', 'Execute the pinned runner recorded by this run.')
    directory = Path(current['directory'])
    # An execution claim is permanent. A crash is recovered from evidence, never by rerunning argv.
    claim = directory / 'execution.claim'
    try:
        claim.mkdir()
    except FileExistsError:
        w.fail('execution_claimed', 'This execution was already claimed; reconcile its receipt.')
    w.atomic_json(claim / 'owner.json', {'pid': os.getpid(), 'token': token, 'time': w.now()})
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
    process = None
    with open(log_path, 'xb') as log:
        try:
            process = subprocess.Popen(argv, cwd=current['code'], env=environment, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=log, shell=False, start_new_session=True)
            code = process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, OSError) as error:
            code = 124 if isinstance(error, subprocess.TimeoutExpired) else 127
        finally:
            if process is not None:
                # Only this runner's new process group is signalled, including surviving children.
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
        log.flush()
        os.fsync(log.fileno())
    receipt = {'token': token, 'returncode': code, 'argv_digest': w.digest(current['argv']),
               'manifest_digest': current['manifest_digest'], 'environment_digest': w.digest(w.environment_identity(current['environment'])),
               'log': str(log_path), 'log_sha256': w.sha_file(log_path), 'time': w.now()}
    w.atomic_json(directory / 'execution-receipt.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('root', 'task-id', 'run-id', 'token'):
        parser.add_argument('--' + key, required=True)
    parser.add_argument('--timeout', type=int, default=3600)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 3600:
        parser.error('timeout must be between 1 and 3600 seconds')
    execute(args.root, args.task_id, args.run_id, args.token, args.timeout)


if __name__ == '__main__':
    main()
