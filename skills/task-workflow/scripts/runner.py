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

EXECUTION_PROTOCOL = 4


def execute(root, task_id, run_id, token, timeout=None):
    _, store = w.store_dir(root)
    path = w.task_dir(store, task_id)
    arguments = {'task_id': task_id, 'run_id': run_id}
    with w.mutation_locks(store, arguments, 'run-dispatch'):
        state, previous = w.load_events(path)
        w.require_task_open(state)
        current = w.get_run(state, run_id)
        w.require_generation_dispatch(state, current)
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
        owner = {'pid': os.getpid(), 'token': token, 'time': w.now(), 'host': w.lock_host_identity(),
                 'uid': w.lock_uid(), 'contract_digest': w.execution_argv_digest(current)}
        w.atomic_json(claim / 'owner.json', owner)
        w.sync_dir(claim)
        w.sync_dir(directory)
        environment = w.startup_environment(current)
        argv = list(current['argv'])
        if current['environment'].get('kind') == 'toolchain':
            argv = w.toolchain_argv(argv, current['environment'])
        elif argv[0] in ('python', 'python3'):
            argv[0] = str(Path(current['environment']['path']) / 'bin/python')
        contract = w.execution_argv_digest(current)
        # Both files use exclusive creation. A claimed probe is never replayed.
        execution_log = directory / 'execution.log'
        log = open(execution_log, 'xb')
        try:
            current.update(status='starting', workload_started=False, execution_owner=owner,
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
        with w.mutation_locks(store, arguments, 'run-dispatch'):
            state, previous = w.load_events(path)
            actual = w.get_run(state, run_id)
            try:
                w.require_task_open(state)
                if actual['status'] != 'starting' or actual['token'] != token or w.execution_argv_digest(actual) != contract or actual.get('execution_intent') != intent:
                    w.fail('execution_denied', 'The startup claim or execution intent changed before workload admission.')
                if startup['status'] != 'passed':
                    w.fail(startup.get('error', 'startup_failed'), 'Startup validation did not pass.')
                w.require_execution_protocol(state, actual)
                w.require_generation_dispatch(state, actual)
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


def execute_check(root, task_id, check_id, token):
    """Execute a previously reserved check once, outside workflow state locks."""
    _, store = w.store_dir(root)
    path = w.task_dir(store, task_id)
    arguments = {'task_id': task_id, 'check_id': check_id}
    with w.mutation_locks(store, arguments, 'check-dispatch'):
        state, previous = w.load_events(path)
        w.require_task_open(state)
        current = state.get('checks', {}).get(check_id)
        if not current or current['status'] != 'reserved' or current['token'] != token or w.check_contract(current) != current['contract_digest']:
            w.fail('execution_denied', 'A matching unclaimed check intent is required.')
        w.check_runtime(state, current)
        if Path(__file__).resolve().parent != Path(current['runtime']['directory']):
            w.fail('runtime_changed', 'Use the exact pinned check runner.')
        if not w.check_current(state, current):
            w.fail('stale_check', 'The check source changed before admission.')
        w.validate_resource_reference(store, state, current, require_available=True)
        current['retention_hold_id'] = w.bind_resource_retention(state, current, current['actor'])
        w.ensure_check_checkout(state, current)
        check_environment = w.check_execution_environment(state, current)
        directory = Path(current['directory'])
        claim = directory / 'execution.claim'
        try:
            claim.mkdir()
        except FileExistsError:
            w.fail('execution_claimed', 'This check was already claimed; reconcile its receipt.')
        owner = {'pid': os.getpid(), 'host': w.lock_host_identity(), 'uid': w.lock_uid(), 'token': token,
                 'contract_digest': current['contract_digest'], 'time': w.now()}
        w.atomic_json(claim / 'owner.json', owner)
        log_path = directory / 'check.log'
        log = open(log_path, 'xb')
        stderr_path = directory / 'stderr.log'
        stderr_log = open(stderr_path, 'xb')
        current.update(status='starting', claim=owner)
        w.commit_event(path, state, previous, 'check-claimed', current['actor'])
    process, code, error, startup = None, 125, None, None
    with log, stderr_log:
        try:
            if current.get('frozen_inputs'):
                frozen = current['frozen_inputs']
                # A check owns its separate report and receipt namespace.
                validation = {**frozen, 'directory': str(directory), 'token': token}
                startup = w.perform_startup_validation(validation, timeout=current['timeout'])
                code = 0 if startup['status'] == 'passed' else 125
                log.write(w.canonical(startup) + b'\n')
            else:
                process = subprocess.Popen(current['argv'], cwd=current['cwd'], env=check_environment, stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=stderr_log, shell=False, start_new_session=True)
                code = None
                with w.mutation_locks(store, arguments, 'check-started'):
                    state, previous = w.load_events(path)
                    actual = state['checks'][check_id]
                    if actual['token'] != token or actual['status'] != 'starting':
                        w.fail('execution_denied', 'The check claim changed before process publication.')
                    actual.update(status='running', workload_pid=process.pid)
                    w.commit_event(path, state, previous, 'check-started', current['actor'])
                code = w.wait_with_timeout(lambda seconds: process.wait(timeout=seconds), current['timeout'])
        except subprocess.TimeoutExpired:
            code, error = 124, 'timeout'
        except OSError:
            code, error = 127, 'spawn_failed'
        finally:
            stop_process(process)
        log.flush()
        os.fsync(log.fileno())
        stderr_log.flush()
        os.fsync(stderr_log.fileno())
    if current.get('source_checkout'):
        try:
            w.check_checkout_identity(state, current)
        except w.WorkflowError:
            code, error = 125, 'check_checkout_changed'
    output_path = directory / 'output.json'
    w.atomic_json(output_path, {'stdout_tail': log_path.read_text(errors='replace'), 'stderr_tail': stderr_path.read_text(errors='replace')})
    receipt = {'protocol': 4, 'token': token, 'contract_digest': current['contract_digest'],
               'source_binding': current['source_binding'], 'returncode': code, 'error': error,
               'log': str(log_path), 'log_sha256': w.sha_file(log_path), 'started_at': owner['time'],
               'finished_at': w.now(), 'actual_host': owner['host'], 'owned_process_identity': owner}
    receipt.update(stderr_log=str(stderr_path), stderr_sha256=w.sha_file(stderr_path), output=str(output_path), output_sha256=w.sha_file(output_path))
    if startup:
        receipt['startup'] = startup
    w.atomic_json(directory / 'check-receipt.json', receipt)
    w.sync_dir(directory)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('root', 'task-id', 'token'):
        parser.add_argument('--' + key, required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--run-id')
    target.add_argument('--check-id')
    parser.add_argument('--timeout', type=int, default=None)
    args = parser.parse_args()
    if args.timeout is not None and args.timeout < 1:
        parser.error('timeout must be positive seconds')
    if args.check_id:
        execute_check(args.root, args.task_id, args.check_id, args.token)
    else:
        execute(args.root, args.task_id, args.run_id, args.token, args.timeout)


if __name__ == '__main__':
    main()
