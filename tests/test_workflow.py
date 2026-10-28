"""Isolated Git and evidence contract checks."""
import importlib.util
import base64
import hashlib
import zlib
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
        self.state = self.enroll({'root': str(self.root), 'project': str(self.repo), 'task_id': 'task',
            'title': 'Fixture task', 'actor': 'owner', 'session_id': 'session-fixture',
            'authorization_source': 'Fixture enrollment', 'environment_registry': {'runtime': str(self.environment)}})['state']
        self.op('environment-bind', path=str(self.environment), authorization_source='Actual fixture main environment selection')

    def enroll(self, arguments):
        if getattr(self, 'structured', False):
            return w.dispatch('init', arguments)
        # Represent existing event streams without exposing a legacy-init bypass.
        with mock.patch.object(w, 'new_process', return_value=None):
            return w.dispatch('init', arguments)

    def git(self, path, *args):
        return subprocess.check_output(['git', '-C', str(path), *args], stderr=subprocess.DEVNULL).decode().strip()

    def refresh(self):
        self.state = w.dispatch('status', {'root': str(self.root), 'task_id': 'task'})['state']
        return self.state

    def startup_fields(self):
        validator = ('import json,os,runpy; from pathlib import Path; '
            'assert runpy.run_path("code.py")["VALUE"] == 2; '
            'Path(os.environ["TASK_WORKFLOW_STARTUP_REPORT"]).write_text(json.dumps({'
            '"token":os.environ["TASK_WORKFLOW_STARTUP_TOKEN"],'
            '"origins":[{"id":"entrypoint:code.py","path":str(Path("code.py").absolute())}],'
            '"references":[]}))')
        return {'snapshot_scope': {'entrypoints': ['code.py'], 'code': [], 'configs': ['uv.lock'], 'assets': []},
            'fixed_references': [], 'validation_argv': ['python', '-c', validator], 'origin_checks': []}

    def op(self, operation, **fields):
        if operation == 'run-prepare':
            fields = {**self.startup_fields(), **fields}
        try:
            result = w.dispatch(operation, {'root': str(self.root), 'task_id': 'task', 'actor': 'owner',
                'expected_version': self.state['version'], **fields})
        finally:
            self.refresh()
        self.assertEqual(result['dialogue_contract']['task_id'], 'task')
        if 'state' in result:
            self.assertEqual(result['dialogue_contract']['state_version'], result['state']['version'])
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
        dimensions = {'requirements_verdict': 'accept', 'quality_verdict': 'accept'} if self.state.get('process') else {}
        self.op('item-review', item_id=item, actor='reviewer', verdict='accept', notes='Actual source reviewed.', **dimensions)
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
        defaults = dict(environment_id='runtime', lockfiles=['uv.lock'],
            argv=['python', '-c', 'import os; from pathlib import Path; Path(os.environ["TASK_WORKFLOW_OUTPUT_DIR"], "result.txt").write_text("ok")'],
            artifacts=['result.txt'], dependency_declaration='no-external-local-dependencies')
        return self.op('run-prepare', run_id=run_id, **{**defaults, **fields})

    def error(self, code, function):
        with self.assertRaises(w.WorkflowError) as caught:
            function()
        self.assertEqual(caught.exception.code, code)


def retained_runtime(directory):
    """Materialize the hash-verified published 0.1.14 source fixture."""
    archive = json.loads((Path(__file__).parent / 'fixtures/runtime014.json').read_text())
    directory.mkdir(exist_ok=True)
    for name, item in archive['files'].items():
        content = zlib.decompress(base64.b64decode(item['zlib_base64']))
        assert hashlib.sha256(content).hexdigest() == item['sha256']
        (directory / name).write_bytes(content)
    spec = importlib.util.spec_from_file_location('retained014_' + directory.parent.name, directory / 'workflow.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class LegacyFixture(Fixture):
    """Explicit retained format2 premises for pre-cleanup execution regression tests."""
    def enroll(self, arguments):
        if not hasattr(self, 'retained'):
            self.retained = retained_runtime(self.base / 'published014')
        with mock.patch.object(self.retained, 'new_process', return_value=None):
            return self.retained.dispatch('init', arguments)

    def op(self, operation, **fields):
        if operation not in ('verify', 'integration-verify'):
            return super().op(operation, **fields)
        try:
            result = self.retained.dispatch(operation, {'root': str(self.root), 'task_id': 'task', 'actor': 'owner',
                'expected_version': self.state['version'], **fields})
        finally:
            self.refresh()
        return result


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


class UnrestrictedCoreTests(Fixture):
    def test_large_text_state_cli_and_identifier_round_trip(self):
        content = 'x' * (4 * 1024 * 1024 + 1)
        self.op('design', content=content)
        self.assertEqual(self.refresh()['design']['content'], content)
        long_id = 'item_' + 'a' * 100
        self.op('item-add', item_id=long_id, title='Large identifier', owned_paths=['code.py'])
        self.assertIn(long_id, self.state['items'])
        arguments = {'task_id': 'task', 'actor': 'owner', 'expected_version': self.state['version'], 'content': content}
        result = subprocess.run([sys.executable, str(SCRIPT), 'decision', '--root', str(self.root), '--json-args', '-'],
                                input=json.dumps(arguments), capture_output=True, text=True, check=True)
        response = json.loads(result.stdout)
        self.assertEqual(response['state']['decisions'][-1]['content'], content)

    def test_complete_output_large_argv_and_explicit_timeout(self):
        self.tree(); self.approved()
        self.op('item-start', item_id='overall', actor='implementer')
        self.op('item-submit', item_id='overall', actor='implementer')
        argv = [sys.executable, '-c', 'import sys; print("A" * 20000); print("B" * 20000, file=sys.stderr)'] + ['argument'] * 201
        self.op('verify', item_id='overall', argv=argv, timeout=7200)
        evidence = self.state['items']['overall']['verifications'][-1]
        log = w.read_json(Path(evidence['log']))
        self.assertEqual(log['stdout_tail'], 'A' * 20000 + '\n')
        self.assertEqual(log['stderr_tail'], 'B' * 20000 + '\n')
        self.assertNotIn('output_limit_bytes', log)
        result = w.run([sys.executable, '-c', 'print("complete")'], timeout=10 ** 100)
        self.assertEqual(result['stdout'], 'complete\n')
        self.assertEqual(result['returncode'], 0)
        result = w.run([sys.executable, '-c', 'import sys; print(len(sys.stdin.read()))'],
                       timeout=10 ** 100, input_text='x' * 100000)
        self.assertEqual(result['returncode'], 0)
        self.assertEqual(result['stdout'], '100000\n')

    def test_internal_subprocesses_have_no_deadline(self):
        actual_run = w.run
        actual_subprocess_run = subprocess.run
        def capture(argv, **kwargs):
            if 'timeout' in kwargs:
                self.assertIsNone(kwargs['timeout'], argv)
            return actual_run(argv, **kwargs)
        def capture_direct(argv, **kwargs):
            self.assertIsNone(kwargs.get('timeout'), argv)
            return actual_subprocess_run(argv, **kwargs)
        with mock.patch.object(w, 'run', side_effect=capture), mock.patch.object(w.subprocess, 'run', side_effect=capture_direct):
            self.integrated()
            self.prepare()
            self.op('run-validate', run_id='run', check_id='startup')
            self.op('cleanup', dry_run=False)

    def test_large_blob_exports_as_disk_paths_and_chunked_streams(self):
        size = 64 * 1024 * 1024 + 1
        blob = self.repo / 'large.bin'
        with blob.open('wb') as stream:
            stream.truncate(size)
        self.git(self.repo, 'add', 'large.bin'); self.git(self.repo, 'commit', '-m', 'Large sparse fixture')
        commit = self.git(self.repo, 'rev-parse', 'HEAD')
        w.archive_preflight(str(self.repo), commit)
        original_copy = w.shutil.copyfileobj
        sizes = []
        def copy(source, destination, length):
            sizes.append(length)
            return original_copy(source, destination, length)
        with mock.patch.object(w.shutil, 'copyfileobj', side_effect=copy):
            with w.exported_snapshot(str(self.repo), commit) as (files, modes):
                exported = files['large.bin']
                self.assertIsInstance(exported, Path)
                self.assertEqual(exported.stat().st_size, size)
                self.assertEqual(w.sha_file(exported), w.sha_file(blob))
                w.check_dependencies(files, 'no-external-local-dependencies')
            self.assertFalse(exported.exists())
        self.assertTrue(sizes)
        self.assertTrue(all(value == 1024 * 1024 for value in sizes))

    def test_inventory_accepts_large_total_blob_sizes(self):
        def inventory(argv, **kwargs):
            self.assertIsNone(kwargs.get('timeout'))
            record = b'100644 blob ' + b'a' * 40 + b' 1099511627776\t' + b'b' * 200 + b'\0'
            for _ in range(10):
                kwargs['stdout'].write(record * 10000)
            return subprocess.CompletedProcess(argv, 0)
        commit = self.git(self.repo, 'rev-parse', 'HEAD')
        with mock.patch.object(w.subprocess, 'run', side_effect=inventory):
            w.archive_preflight(str(self.repo), commit)

    def test_large_environment_metadata_and_inventory(self):
        package_root = next((self.environment / 'lib').glob('python*/site-packages'))
        metadata = package_root / 'large.pth'
        metadata.write_text('#' + 'x' * (1024 * 1024 + 1))
        original = w.run
        def inventory(argv, **kwargs):
            self.assertIsNone(kwargs.get('timeout'))
            result = original(argv, **kwargs)
            if 'import importlib.metadata,json,sys' in argv[-1]:
                data = json.loads(result['stdout'])
                data['packages'] = [['package_' + 'x' * 100 + str(index), '1'] for index in range(10000)]
                result['stdout'] = json.dumps(data)
            return result
        with mock.patch.object(w, 'run', side_effect=inventory):
            fingerprint = w.env_fingerprint(str(self.environment))
        self.assertEqual(len(fingerprint['inventory']['packages']), 10000)
        self.assertEqual(fingerprint['path_metadata'][str(metadata.relative_to(self.environment))], w.sha_file(metadata))
