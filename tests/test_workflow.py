"""Isolated Git and evidence contract checks."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/task-workflow/scripts/workflow.py'
SPEC = importlib.util.spec_from_file_location('workflow_core_test', SCRIPT)
w = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(w)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.repo = self.base / 'project'; self.repo.mkdir()
        self.root = self.repo
        self.environment = self.base / 'environment'
        subprocess.check_call([sys.executable, '-m', 'venv', '--without-pip', str(self.environment)], stdout=subprocess.DEVNULL)
        self.git(self.repo, 'init', '-b', 'main')
        self.git(self.repo, 'config', 'user.name', 'Test Author')
        self.git(self.repo, 'config', 'user.email', 'test@example.invalid')
        (self.repo / 'code.py').write_text('VALUE = 1\n')
        (self.repo / 'uv.lock').write_text('version = 1\n')
        self.git(self.repo, 'add', '.')
        self.git(self.repo, 'commit', '-m', 'Initial fixture')
        self.state = w.dispatch('init', {'root': str(self.root), 'project': str(self.repo), 'task_id': 'task',
            'title': 'Fixture task', 'actor': 'owner', 'session_id': 'session-fixture',
            'authorization_source': 'Fixture enrollment', 'environment_registry': {'runtime': str(self.environment)}})['state']

    def git(self, path, *args):
        return subprocess.check_output(['git', '-C', str(path), *args], stderr=subprocess.DEVNULL).decode().strip()

    def refresh(self):
        self.state = w.dispatch('status', {'root': str(self.root), 'task_id': 'task'})['state']
        return self.state

    def op(self, operation, **fields):
        try:
            result = w.dispatch(operation, {'root': str(self.root), 'task_id': 'task', 'actor': 'owner',
                'expected_version': self.state['version'], **fields})
        finally:
            self.refresh()
        return result

    def approved(self):
        self.op('design', content='Change the fixture and verify the result.')
        self.op('approve', design_digest=self.state['design']['digest'], authorization_source='Fixture design approval')

    def tree(self):
        self.op('worktree-prepare', expected_base=self.git(self.repo, 'rev-parse', 'HEAD'), authorization_source='Fixture worktree')
        self.feature = Path(self.state['worktree']['path'])
        return self.feature

    def complete(self, item='overall'):
        self.op('item-start', item_id=item, actor='implementer')
        self.op('item-submit', item_id=item, actor='implementer')
        self.op('verify', item_id=item, argv=[sys.executable, '-c', 'print("verified")'])
        self.op('item-review', item_id=item, actor='reviewer', verdict='accept', notes='Actual source reviewed.')
        self.op('item-accept', item_id=item, notes='Accepted evidence.')

    def integrated(self):
        self.tree(); self.approved()
        (self.feature / 'code.py').write_text('VALUE = 2\n')
        self.git(self.feature, 'add', '.'); self.git(self.feature, 'commit', '-m', 'Change fixture')
        self.complete()
        result = self.op('integrate', base_branch='main', expected_base=self.git(self.repo, 'rev-parse', 'HEAD'),
            expected_head=self.git(self.feature, 'rev-parse', 'HEAD'), authorization_source='Fixture integration',
            dry_run=False, commit_message='Implement fixture')
        self.op('integration-verify', argv=[sys.executable, '-c', 'assert open("code.py").read() == "VALUE = 2\\n"'])
        return result

    def prepare(self, run_id='run', **fields):
        return self.op('run-prepare', run_id=run_id, environment_id='runtime', lockfiles=['uv.lock'],
            argv=['python', '-c', 'import os; from pathlib import Path; Path(os.environ["TASK_WORKFLOW_OUTPUT_DIR"], "result.txt").write_text("ok")'],
            artifacts=['result.txt'], dependency_declaration='no-external-local-dependencies', **fields)

    def error(self, code, function):
        with self.assertRaises(w.WorkflowError) as caught:
            function()
        self.assertEqual(caught.exception.code, code)


class WorkflowTests(Fixture):
    def test_project_scope_worktree_and_discovery(self):
        self.assertEqual(w.find_registered_root(self.repo), self.root)
        self.assertEqual(w.summary(self.state)['session_id'], 'session-fixture')
        self.assertFalse(self.git(self.repo, 'status', '--porcelain'))
        self.tree()
        self.assertEqual(self.feature, self.repo / '.worktrees/task')
        self.assertEqual(w.find_registered_root(self.feature), self.root)
        unrelated = self.base / 'unrelated'; unrelated.mkdir()
        self.assertIsNone(w.find_registered_root(unrelated))

    def test_event_recovery_and_corruption(self):
        self.approved()
        path = w.task_dir(self.root / '.task-workflow', 'task')
        (path / 'state.json').write_text('{}')
        self.assertEqual(self.refresh()['approval']['digest'], self.state['design']['digest'])
        self.op('recover')
        self.assertEqual(w.read_json(path / 'state.json')['task_id'], 'task')
        event = sorted((path / 'events').glob('*.json'))[-1]
        event.chmod(0o644); event.write_text('{}')
        self.error('corrupt_history', self.refresh)

    def test_review_and_version_guards(self):
        self.tree(); self.approved()
        self.op('item-start', item_id='overall', actor='implementer')
        self.op('item-submit', item_id='overall', actor='implementer')
        self.error('independent_review_required', lambda: self.op('item-review', item_id='overall', actor='implementer', verdict='accept', notes='Self review'))
        self.op('item-review', item_id='overall', actor='reviewer', verdict='accept', notes='Review')
        self.error('verification_required', lambda: self.op('item-accept', item_id='overall', notes='Missing check'))
        self.error('revision_conflict', lambda: self.op('decision', content='Stale', expected_version=1))

    def test_squash_verify_and_safe_cleanup(self):
        self.integrated()
        integration = self.state['integration']
        self.assertEqual(self.git(self.repo, 'rev-list', '--parents', '-n', '1', integration['commit']).split(), [integration['commit'], integration['base']])
        (self.feature / 'retained.txt').write_text('unique')
        self.error('unique_files', lambda: self.op('cleanup', dry_run=False))
        (self.feature / 'retained.txt').unlink()
        self.assertTrue(self.op('cleanup')['dry_run'])
        self.op('cleanup', dry_run=False)
        self.assertFalse(self.feature.exists())

    def test_managed_path_tracked_collision_and_exclude_preservation(self):
        exclude = Path(self.state['project']['common_dir']) / 'info/exclude'
        before = exclude.read_bytes()
        self.assertTrue(w.bootstrap_project(self.state['project'])['reused'])
        self.assertEqual(exclude.read_bytes(), before)
        tracked = self.repo / '.experiments/tracked'; tracked.parent.mkdir(); tracked.write_text('source')
        self.git(self.repo, 'add', '-f', '.experiments/tracked'); self.git(self.repo, 'commit', '-m', 'Tracked collision')
        self.error('managed_path_collision', lambda: w.bootstrap_project(self.state['project']))

    def test_bootstrap_preserves_unowned_untracked_runtime_contents(self):
        fresh = self.base / 'fresh'; fresh.mkdir()
        self.git(fresh, 'init', '-b', 'main')
        self.git(fresh, 'config', 'user.name', 'Test'); self.git(fresh, 'config', 'user.email', 'test@example.invalid')
        self.git(fresh, 'commit', '--allow-empty', '-m', 'Initial')
        unrelated = fresh / '.experiments/unrelated.txt'; unrelated.parent.mkdir(); unrelated.write_text('unrelated')
        before = self.git(fresh, 'status', '--porcelain', '--untracked-files=all')
        exclude = fresh / '.git/info/exclude'; original = exclude.read_bytes()
        self.error('managed_path_unowned', lambda: w.bootstrap_project(w.git_identity(fresh)))
        self.assertEqual(self.git(fresh, 'status', '--porcelain', '--untracked-files=all'), before)
        self.assertEqual(exclude.read_bytes(), original)
        self.assertEqual(unrelated.read_text(), 'unrelated')

    def test_runtime_concurrent_publication_validates_identical_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        barrier = threading.Barrier(2)
        original = os.rename
        def race(source, target):
            if str(target).startswith(str(self.root / '.task-workflow/runtimes')):
                barrier.wait(timeout=5)
            return original(source, target)
        with mock.patch.object(w.os, 'rename', side_effect=race), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(w.pin_runtime, self.state) for _ in range(2)]
            results = [future.result(timeout=10) for future in futures]
        self.assertEqual(results[0], results[1])
        for name, expected in results[0]['files'].items():
            self.assertEqual(w.sha_file(Path(results[0]['directory']) / name), expected)

    def interrupted_integration(self, phase):
        self.tree(); self.approved()
        (self.feature / 'code.py').write_text('VALUE = 3\n')
        self.git(self.feature, 'add', '.'); self.git(self.feature, 'commit', '-m', 'Fixture change')
        self.complete()
        args = {'base_branch':'main', 'expected_base':self.git(self.repo, 'rev-parse', 'HEAD'),
                'expected_head':self.git(self.feature, 'rev-parse', 'HEAD'), 'authorization_source':'Fixture integration', 'dry_run':False}
        actual = w.run
        def interrupt(argv, **kwargs):
            result = actual(argv, **kwargs)
            if (phase == 'commit' and 'commit' in argv and '-m' in argv) or (phase == 'publish' and '--ff-only' in argv):
                raise RuntimeError('Fixture interrupted integration')
            return result
        with mock.patch.object(w, 'run', side_effect=interrupt):
            with self.assertRaises(RuntimeError):
                self.op('integrate', **args)
        candidate = self.git(Path(self.state['integration']['scratch']), 'rev-parse', 'HEAD')
        self.op('integrate', **args)
        self.assertEqual(self.state['integration']['status'], 'complete')
        self.assertEqual(self.git(self.repo, 'rev-parse', 'HEAD'), candidate)
        self.assertEqual(self.git(self.repo, 'rev-list', '--count', args['expected_base'] + '..HEAD'), '1')

    def test_commit_interruption_keeps_one_squash(self):
        self.interrupted_integration('commit')

    def test_publication_interruption_keeps_one_squash(self):
        self.interrupted_integration('publish')

    def test_explicit_external_state_binding(self):
        # A second project can bind one explicit external storage root.
        other = self.base / 'other'; other.mkdir()
        self.git(other, 'init', '-b', 'main')
        self.git(other, 'config', 'user.name', 'Test'); self.git(other, 'config', 'user.email', 'test@example.invalid')
        self.git(other, 'commit', '--allow-empty', '-m', 'Initial')
        external = self.base / 'storage'; external.mkdir()
        w.dispatch('init', {'root': str(external), 'project': str(other), 'task_id': 'external', 'title': 'External task', 'actor': 'owner', 'authorization_source': 'Explicit external storage'})
        self.assertEqual(w.find_registered_root(other), external)


if __name__ == '__main__':
    unittest.main()
