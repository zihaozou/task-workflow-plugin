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

EXECUTION_PROTOCOL = 3


def execute(root, task_id, run_id, token, timeout=None):
    _, store = w.store_dir(root)
    path = w.task_dir(store, task_id)
    with w.lifecycle_lock(store), w.lock(path / 'write.lock'):
        state, previous = w.load_events(path)
        w.require_task_open(state)
        current = w.get_run(state, run_id)
        intent = current.get('execution_intent')
        if current['status'] != 'queued' or current.get('token') != token or not intent or timeout != intent['timeout']:
            w.fail('execution_denied', 'A matching uncompleted dispatch intent is required.')
        w.require_execution_protocol(state, current)
        if current.get('snapshot_contract') != 3:
            w.fail('legacy_runtime', 'Execute a legacy Run using its original pinned runner.')
        w.check_run(state, current)
        if Path(__file__).resolve().parent != Path(current['runtime']['directory']):
            w.fail('runtime_changed', 'Execute the pinned runner recorded by this Run.')
        w.validate_resource_reference(store, state, {**current, 'run_id': run_id}, require_available=True)
        directory = Path(current['directory'])
        claim = directory / 'execution.claim'
        try:
            claim.mkdir()
        except FileExistsError:
            w.fail('execution_claimed', 'This execution was already claimed; reconcile its durable receipts.')
        w.atomic_json(claim / 'owner.json', {'pid': os.getpid(), 'token': token, 'time': w.now(), 'host': socket.gethostname()})
        w.sync_dir(claim)
        w.sync_dir(directory)
        environment = w.startup_environment(current)
        argv = list(current['argv'])
        if argv[0] in ('python', 'python3'):
            argv[0] = str(Path(current['environment']['path']) / 'bin/python')
        contract = w.execution_argv_digest(current)
        # Both files use exclusive creation. A claimed probe is never replayed.
        execution_log = directory / 'execution.log'
        log = open(execution_log, 'xb')
        try:
            current.update(status='starting', workload_started=False,
                start_validated={'time': w.now(), 'manifest_digest': current['manifest_digest'], 'runner_pid': os.getpid(), 'host': socket.gethostname()},
                startup={'status': 'starting', 'token': token, 'contract_digest': contract, 'time': w.now()})
            w.commit_event(path, state, previous, 'run-startup-intent', intent['actor'])
        except BaseException:
            log.close()
            raise
    # No project/task lock is held while the project-supplied validator executes.
    try:
        startup = w.perform_startup_validation(current)
    except BaseException:
        log.close()
        raise
    process, code, workload_error = None, 125, None
    with log:
        with w.lifecycle_lock(store), w.lock(path / 'write.lock'):
            state, previous = w.load_events(path)
            actual = w.get_run(state, run_id)
            try:
                w.require_task_open(state)
                if actual['status'] != 'starting' or actual['token'] != token or w.execution_argv_digest(actual) != contract or actual.get('execution_intent') != intent:
                    w.fail('execution_denied', 'The startup claim or execution intent changed before workload admission.')
                if startup['status'] != 'passed':
                    w.fail(startup.get('error', 'startup_failed'), 'Startup validation did not pass.')
                w.require_execution_protocol(state, actual)
                w.check_run(state, actual)
                w.validate_resource_reference(store, state, {**actual, 'run_id': run_id}, require_available=True)
                # Re-read the report under the final admission locks.
                if not w.startup_receipt_valid(actual, startup):
                    w.fail('startup_report_invalid', 'The startup report changed before workload admission.')
                try:
                    process = subprocess.Popen(argv, cwd=actual['code'], env=environment, stdin=subprocess.DEVNULL,
                        stdout=log, stderr=log, shell=False, start_new_session=True)
                    code = None
                except OSError:
                    code = 127
                    workload_error = 'workload_spawn_failed'
                actual.update(status='running' if process is not None else 'failed', started=w.now(), workload_started=process is not None)
                actual['start_validated'].update(pid=process.pid if process else None, time=w.now())
            except w.WorkflowError as failure:
                startup.update(status='failed', error=failure.code)
                actual.update(status='failed', workload_started=False)
            w.atomic_json(directory / 'startup-receipt.json', startup)
            actual['startup'] = {**startup, 'receipt_digest': w.digest(startup)}
            try:
                w.commit_event(path, state, previous, 'run-execution-started' if process else 'run-startup-failed', intent['actor'])
            except BaseException:
                stop_process(process)
                raise
            current = actual
        try:
            if process is not None:
                code = w.wait_with_timeout(lambda seconds: process.wait(timeout=seconds), timeout)
        except subprocess.TimeoutExpired:
            code = 124
        finally:
            stop_process(process)
        log.flush()
        os.fsync(log.fileno())
    receipt = {'protocol': 3, 'token': token, 'returncode': code, 'argv_digest': contract,
        'manifest_digest': current['manifest_digest'], 'environment_digest': w.digest(w.environment_identity(current['environment'])),
        'workload_started': process is not None, 'workload_error': workload_error, 'startup': startup, 'startup_digest': w.digest(startup),
        'log': str(execution_log), 'log_sha256': w.sha_file(execution_log), 'time': w.now()}
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
