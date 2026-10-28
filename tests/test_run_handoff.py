"""Dispatch intent and actual detached runner acknowledgment have different meanings."""
import copy
import json
import os
from pathlib import Path
import subprocess
import time
from unittest import mock

from test_workflow import Fixture, w


class RunHandoffTests(Fixture):
    def ready(self, managed=False, gate=False):
        self.integrated()
        fields={}
        if managed:
            self.op('resource-register',resource_id='worker',handle='user-worker',provided_by='user',can_release=False,
                authorization_source='Actual user resource',ownership_evidence=['Actual fixture ownership'],capabilities={},
                observed_state='available',evidence=['Fixture worker is available'])
            fields['resource_id']='worker'
        if gate:
            self.started=self.base / 'workload-started';self.release=self.base / 'release-workload'
            self.addCleanup(self.release.touch)
            fields['argv']=['python','-c','import os,time; from pathlib import Path; Path('+repr(str(self.started))+').touch(); p=Path('+repr(str(self.release))+');\nwhile not p.exists(): time.sleep(0.01)\nPath(os.environ["TASK_WORKFLOW_OUTPUT_DIR"],"result.txt").write_text("done")']
        current=self.prepare(**fields)['run']
        validation=self.op('run-validate',run_id='run',check_id='startup')
        if validation['status']=='reserved':
            result=subprocess.run(validation['runner_argv'],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.refresh();self.op('check-reconcile',check_id='startup')
        self.op('cleanup',dry_run=False)
        return current

    def wait_until(self,predicate):
        deadline=time.monotonic()+20
        while not predicate() and time.monotonic()<deadline:
            time.sleep(0.02)
        self.assertTrue(predicate(),'Owned fixture did not settle')

    def test_external_dispatch_is_not_actual_provider_queue_acceptance(self):
        current=self.ready(managed=True)
        holds=copy.deepcopy(self.state['resource_holds'])
        result=self.op('run-dispatch',run_id='run')
        self.assertEqual(result['handoff'],{'state':'dispatch_intent','actual_acceptance':False,'end_turn':False})
        self.assertEqual(self.state['runs']['run']['status'],'queued')
        self.assertFalse((Path(current['directory']) / 'execution.claim').exists())
        self.assertEqual(self.state['resource_holds'],holds)
        self.assertEqual(self.state['task_lifecycle']['status'],'open')
        duplicate=self.op('run-dispatch',run_id='run')
        self.assertTrue(duplicate['already_dispatched'])
        self.assertFalse(duplicate['handoff']['actual_acceptance'])
        policy=w.dialogue_contract(self.state)['run_handoff_policy']
        self.assertIn('end the current turn',policy)
        self.assertIn('later user status',policy)
        self.assertFalse(w.dispatch('resource-status',{'root':str(self.root),'resource_id':'worker'})['resource']['can_release'])

    def test_detached_runner_hands_off_without_waiting_or_post_spawn_task_lock(self):
        current=self.ready(managed=True,gate=True)
        holds=copy.deepcopy(self.state['resource_holds'])
        started={'spawned':False};original_spawn=w.subprocess.Popen;original_locks=w.mutation_locks
        def spawn(*args,**kwargs):
            process=original_spawn(*args,**kwargs)
            started['spawned']=True
            return process
        def locks(*args,**kwargs):
            if started['spawned']:
                raise AssertionError('The handoff must not reacquire task locks after process creation')
            return original_locks(*args,**kwargs)
        with mock.patch.object(w.subprocess,'Popen',side_effect=spawn),mock.patch.object(w,'mutation_locks',side_effect=locks):
            result=self.op('run-execute',run_id='run',detached=True)
        self.assertTrue(result['handoff']['actual_acceptance'])
        self.assertTrue(result['handoff']['end_turn'])
        self.assertTrue(result['reconciliation_required'])
        receipt=Path(result['handoff']['receipt_path'])
        self.assertEqual(w.sha_file(receipt),result['handoff']['receipt_sha256'])
        self.assertEqual(json.loads(receipt.read_text())['evidence']['pid'],result['runner_pid'])
        self.assertFalse((Path(current['directory']) / 'result.txt').exists())
        self.assertEqual(self.state['resource_holds'],holds)
        self.assertEqual(self.state['task_lifecycle']['status'],'open')
        self.wait_until(self.started.exists)
        self.assertEqual(self.refresh()['runs']['run']['status'],'running')
        self.release.touch()
        completed=Path(current['directory']) / 'execution-receipt.json'
        self.wait_until(completed.exists)
        result=self.op('run-reconcile',run_id='run')
        self.assertEqual(result['run']['status'],'awaiting_artifacts')
        self.assertEqual((Path(current['directory']) / 'result.txt').read_text(),'done')
        self.assertEqual(self.state['task_lifecycle']['status'],'open')
        self.assertEqual(self.state['resource_holds'],holds)
        def exited():
            try:os.kill(result_pid,0)
            except ProcessLookupError:return True
            return False
        result_pid=json.loads(receipt.read_text())['evidence']['pid']
        self.wait_until(exited)
