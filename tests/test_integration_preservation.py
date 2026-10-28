"""Exact ordinary integration preserves unrelated user work and fixed-source evidence."""
import copy
from pathlib import Path
import subprocess
import sys
from unittest import mock
from test_workflow import Fixture, w


class IntegrationPreservationTests(Fixture):
    def ready(self):
        self.tree(); self.approved()
        (self.feature / 'code.py').write_text('VALUE = 2\n')
        self.git(self.feature, 'add', '.'); self.git(self.feature, 'commit', '-m', 'Reviewed fixture change')
        self.complete()
        return {'base_branch':'main', 'expected_base':self.git(self.repo, 'rev-parse', 'HEAD'),
                'expected_head':self.git(self.feature, 'rev-parse', 'HEAD'), 'authorization_source':'Authorized preservation integration',
                'preserve_unrelated_dirty':True, 'commit_message':'Integrate fixture'}

    def unrelated(self):
        (self.repo / 'notes.txt').write_text('Initial notes\n')
        self.git(self.repo, 'add', '.'); self.git(self.repo, 'commit', '-m', 'Independent notes')
        (self.repo / 'notes.txt').write_text('Staged notes\n'); self.git(self.repo, 'add', 'notes.txt')
        (self.repo / 'notes.txt').write_text('Unstaged notes\n')
        (self.repo / 'untracked.txt').write_text('Unique user data\n')
        (self.repo / '.experiments/payload').mkdir(parents=True)
        (self.repo / '.experiments/payload/data').write_text('Unrelated ignored payload\n')

    def integrate_preserved(self, fields):
        preview = self.op('integrate', **fields)
        return self.op('integrate', **fields, dry_run=False, expected_preservation_digest=preview['preservation_digest'])

    def test_dirty_main_full_lifecycle_uses_fixed_integrated_objects(self):
        self.unrelated(); fields = self.ready()
        # ready starts from the exact current main, preserving its unrelated dirt.
        before_index = self.git(self.repo, 'show', ':notes.txt')
        before_worktree = (self.repo / 'notes.txt').read_bytes()
        initial = fields['expected_base']
        result = self.integrate_preserved(fields)
        commit = result['integration']['commit']
        self.assertEqual(self.git(self.repo, 'rev-list', '--parents', '-n', '1', commit).split(), [commit, initial])
        self.assertEqual(self.git(self.repo, 'show', ':notes.txt'), before_index)
        self.assertEqual((self.repo / 'notes.txt').read_bytes(), before_worktree)
        self.error('fixed_verification_required', lambda:self.op('integration-verify', argv=[sys.executable, '-c', 'pass']))
        verified = self.op('integration-verify', source_mode='fixed_commit', expected_integration_commit=commit,
            argv=[sys.executable, '-c', 'assert open("code.py").read() == "VALUE = 2\\n"'])
        self.assertEqual(verified['status'], 'passed')
        self.assertEqual(verified['check']['checkout_cleanup']['status'], 'removed')
        self.assertFalse(Path(verified['check']['cwd']).exists())
        run = self.prepare()['run']
        self.assertEqual(run['commit'], commit)
        self.assertEqual(run['integration_verification']['source_mode'], 'fixed_commit')
        self.op('run-validate', run_id='run', check_id='startup')
        self.op('cleanup', dry_run=False)
        self.assertEqual(self.op('run-execute', run_id='run')['run']['execution']['returncode'], 0)
        self.assertEqual((self.repo / 'notes.txt').read_bytes(), before_worktree)
        self.assertEqual(self.git(self.repo, 'show', ':notes.txt'), before_index)
        self.assertEqual((self.repo / 'untracked.txt').read_text(), 'Unique user data\n')
        self.assertEqual((self.repo / '.experiments/payload/data').read_text(), 'Unrelated ignored payload\n')

    def test_stale_preview_and_same_path_collision_preserve_work(self):
        fields = self.ready()
        (self.repo / 'notes').write_text('Untracked outside footprint')
        preview = self.op('integrate', **fields)
        (self.repo / 'code.py').write_text('User owns dirty endpoint\n')
        self.error('preservation_collision', lambda:self.op('integrate', **fields, dry_run=False, expected_preservation_digest=preview['preservation_digest']))
        self.assertEqual((self.repo / 'code.py').read_text(), 'User owns dirty endpoint\n')
        self.assertEqual(self.git(self.repo, 'rev-parse', 'HEAD'), fields['expected_base'])

    def test_changed_preserved_material_rejects_stale_preview(self):
        self.unrelated(); fields = self.ready(); preview = self.op('integrate', **fields)
        (self.repo / 'notes.txt').write_text('New user notes\n')
        self.error('preservation_changed', lambda:self.op('integrate', **fields, dry_run=False, expected_preservation_digest=preview['preservation_digest']))
        self.assertEqual((self.repo / 'notes.txt').read_text(), 'New user notes\n')

    def test_publication_interruption_reconciles_same_candidate(self):
        self.unrelated(); fields = self.ready(); preview = self.op('integrate', **fields)
        actual = w.run
        def interrupt(argv, **kwargs):
            result = actual(argv, **kwargs)
            if '--ff-only' in argv:
                raise RuntimeError('Lost client after actual publication')
            return result
        with mock.patch.object(w, 'run', side_effect=interrupt):
            with self.assertRaises(RuntimeError):
                self.op('integrate', **fields, dry_run=False, expected_preservation_digest=preview['preservation_digest'])
        commit = self.git(self.repo, 'rev-parse', 'HEAD')
        result = self.op('integrate', **fields, dry_run=False, expected_preservation_digest=preview['preservation_digest'])
        self.assertEqual(result['integration']['commit'], commit)
        self.assertEqual(self.git(self.repo, 'rev-list', '--count', fields['expected_base'] + '..HEAD'), '1')

    def test_fixed_check_survives_main_advance_and_preserves_unexpected_source_files(self):
        fields = self.ready(); self.integrate_preserved(fields)
        ready, release = self.base / 'fixed-ready', self.base / 'fixed-release'
        script = 'from pathlib import Path; import time; assert Path("code.py").read_text()=="VALUE = 2\\n"; Path(' + repr(str(ready)) + ').touch(); p=Path(' + repr(str(release)) + ');\nwhile not p.exists(): time.sleep(0.01)\n'
        reserved = self.op('check-dispatch', check_id='fixed', kind='integration', source_mode='fixed_commit', argv=[sys.executable, '-c', script])
        process = subprocess.Popen(reserved['runner_argv'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            import time
            deadline = time.monotonic() + 20
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(ready.exists())
            self.refresh(); self.op('decision', content='Independent same-task update during fixed verification')
            (self.repo / 'later').write_text('Independent main change')
            self.git(self.repo, 'add', 'later'); self.git(self.repo, 'commit', '-m', 'Advance main during fixed check')
            release.touch(); _, errors = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, errors)
        finally:
            release.touch()
            if process.poll() is None:
                process.kill(); process.communicate()
        self.refresh(); done = self.op('check-reconcile', check_id='fixed')
        self.assertEqual(done['status'], 'passed')
        self.assertEqual(self.state['integration']['verification']['source_mode'], 'fixed_commit')
        # A different immutable attempt creates unexpected unique material.
        unique = self.op('check-dispatch', check_id='unique', kind='integration', source_mode='fixed_commit',
            argv=[sys.executable, '-c', 'from pathlib import Path; Path("unique.txt").write_text("preserve")'])
        self.assertEqual(subprocess.run(unique['runner_argv'], capture_output=True).returncode, 0)
        self.refresh(); result = self.op('check-reconcile', check_id='unique')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['check']['checkout_cleanup']['status'], 'cleanup_pending')
        self.assertEqual((Path(result['check']['cwd']) / 'unique.txt').read_text(), 'preserve')
        self.assertNotEqual(subprocess.run(unique['runner_argv'], capture_output=True).returncode, 0)

    def test_owned_checkout_registration_and_removal_interruptions_do_not_replay(self):
        fields = self.ready(); self.integrate_preserved(fields)
        count = self.base / 'fixed-count'
        command = 'from pathlib import Path; p=Path(' + repr(str(count)) + '); p.write_text(p.read_text()+"x" if p.exists() else "x")'
        reserved = self.op('check-dispatch', check_id='recover', kind='integration', source_mode='fixed_commit', argv=[sys.executable, '-c', command])
        actual = w.run
        def interrupt_add(argv, **kwargs):
            result = actual(argv, **kwargs)
            if 'worktree' in argv and 'add' in argv:
                raise RuntimeError('Lost client after checkout registration')
            return result
        with mock.patch.object(w, 'run', side_effect=interrupt_add):
            with self.assertRaises(RuntimeError):
                with w.mutation_locks(self.root / '.task-workflow', {'task_id':'task', 'check_id':'recover'}, 'check-dispatch'):
                    w.ensure_check_checkout(self.state, reserved['check'])
        self.assertEqual(subprocess.run(reserved['runner_argv'], capture_output=True).returncode, 0)
        self.refresh()
        def interrupt_remove(argv, **kwargs):
            result = actual(argv, **kwargs)
            if 'worktree' in argv and 'remove' in argv:
                raise RuntimeError('Lost client after checkout removal')
            return result
        with mock.patch.object(w, 'run', side_effect=interrupt_remove):
            with self.assertRaises(RuntimeError):
                self.op('check-reconcile', check_id='recover')
        result = self.op('check-reconcile', check_id='recover')
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['check']['checkout_cleanup']['status'], 'removed')
        self.assertEqual(count.read_text(), 'x')

    def test_prefix_ignored_symlink_and_alias_collisions_are_guarded(self):
        fields = self.ready()
        # Use the actual footprint inspector to cover directory/file and alias hazards.
        (self.repo / 'future').mkdir()
        (self.repo / 'future/unique').write_text('Unique ignored material')
        self.error('preservation_collision', lambda:w.publication_preservation(self.state, fields['expected_base'], fields['expected_head'], [b'future']))
        (self.repo / 'link').symlink_to(self.base)
        self.error('preservation_collision', lambda:w.publication_preservation(self.state, fields['expected_base'], fields['expected_head'], [b'link/child']))
        ignored = self.repo / '.experiments/collision'; ignored.parent.mkdir(exist_ok=True); ignored.write_text('Ignored data')
        self.error('preservation_collision', lambda:w.publication_preservation(self.state, fields['expected_base'], fields['expected_head'], [b'.experiments/collision']))
        import os
        (self.repo / 'dirty').write_text('Tracked data'); self.git(self.repo, 'add', 'dirty'); self.git(self.repo, 'commit', '-m', 'Tracked alias source')
        (self.repo / 'dirty').write_text('Uncommitted data')
        os.link(self.repo / 'dirty', self.repo / 'hard-alias')
        self.error('preservation_collision', lambda:w.publication_preservation(self.state, fields['expected_base'], fields['expected_head'], [b'hard-alias']))

    def test_candidate_and_staged_renames_include_both_raw_endpoints(self):
        self.tree(); self.approved()
        self.git(self.feature, 'mv', 'code.py', 'renamed.py')
        self.git(self.feature, 'commit', '-m', 'Reviewed candidate rename')
        self.complete()
        self.git(self.repo, 'mv', 'code.py', 'user-code.py')
        before = w.git_bytes(self.repo, 'ls-files', '--stage', '-z')
        fields = {'base_branch':'main', 'expected_base':self.git(self.repo, 'rev-parse', 'HEAD'),
                  'expected_head':self.git(self.feature, 'rev-parse', 'HEAD'), 'authorization_source':'Preserve actual rename work',
                  'preserve_unrelated_dirty':True}
        self.error('preservation_collision', lambda:self.op('integrate', **fields))
        self.assertEqual(w.git_bytes(self.repo, 'ls-files', '--stage', '-z'), before)
        self.assertEqual((self.repo / 'user-code.py').read_text(), 'VALUE = 1\n')
        self.assertFalse((self.repo / 'code.py').exists())

    def test_staged_and_unstaged_cancellation_preserves_both_identities(self):
        (self.repo / 'notes').write_text('A\n'); self.git(self.repo, 'add', 'notes'); self.git(self.repo, 'commit', '-m', 'Notes baseline')
        fields = self.ready()
        (self.repo / 'notes').write_text('B\n'); self.git(self.repo, 'add', 'notes')
        (self.repo / 'notes').write_text('A\n')
        preview = self.op('integrate', **fields)
        self.assertTrue(preview['preservation']['preserved'])
        self.op('integrate', **fields, dry_run=False, expected_preservation_digest=preview['preservation_digest'])
        self.assertEqual(self.git(self.repo, 'show', ':notes'), 'B')
        self.assertEqual((self.repo / 'notes').read_text(), 'A\n')

    def test_bound_owned_checkout_metadata_and_dangling_endpoint_are_guarded(self):
        fields = self.ready(); self.integrate_preserved(fields)
        reserved = self.op('check-dispatch', check_id='metadata', kind='integration', source_mode='fixed_commit', argv=[sys.executable, '-c', 'pass'])
        altered = copy.deepcopy(reserved['check'])
        altered['source_checkout']['commit'] = fields['expected_base']
        self.assertNotEqual(w.check_contract(altered), reserved['check']['contract_digest'])
        self.error('check_checkout_changed', lambda:w.check_checkout_identity(self.state, altered))
        (self.repo / 'dangling').symlink_to(self.base / 'missing-target')
        self.error('preservation_collision', lambda:w.publication_preservation(self.state, fields['expected_base'], fields['expected_head'], [b'dangling']))

    def test_original_snapshot_proof_recovers_after_equivalent_new_verification(self):
        fields = self.ready(); self.integrate_preserved(fields)
        command = [sys.executable, '-c', 'assert open("code.py").read() == "VALUE = 2\\n"']
        first = self.op('integration-verify', check_id='first-proof', source_mode='fixed_commit', argv=command)
        original = w.commit_event
        def interrupt(path, state, previous, operation, actor):
            if operation == 'run-prepare':
                raise RuntimeError('Client lost after immutable snapshot publication')
            return original(path, state, previous, operation, actor)
        with mock.patch.object(w, 'commit_event', side_effect=interrupt):
            with self.assertRaises(RuntimeError):
                self.prepare()
        run = self.state['runs']['run']
        snapshot = self.repo / '.experiments/verification/task/run/snapshot.json'
        before = snapshot.read_bytes()
        self.op('integration-verify', check_id='second-proof', source_mode='fixed_commit', argv=command)
        recovered = self.prepare()
        self.assertTrue(recovered['recovered'])
        self.assertEqual(snapshot.read_bytes(), before)
        self.assertEqual(recovered['run']['integration_verification']['check_id'], first['check_id'])

    def test_fixed_check_uses_committed_imports_and_rejects_mutable_script_arguments(self):
        fields = self.ready(); self.integrate_preserved(fields)
        (self.repo / 'code.py').write_text('raise RuntimeError("Dirty main must not execute")\n')
        import os
        with mock.patch.dict(os.environ, {'PYTHONPATH':str(self.repo)}):
            result = self.op('integration-verify', source_mode='fixed_commit', argv=[sys.executable, '-c', 'import code; assert code.VALUE == 2'])
        self.assertEqual(result['status'], 'passed')
        self.error('mutable_check_source', lambda: self.op('check-dispatch', check_id='mutable', kind='integration', source_mode='fixed_commit', argv=[sys.executable, str(self.repo / 'code.py')]))
        self.assertNotIn('mutable', self.refresh().get('checks', {}))
