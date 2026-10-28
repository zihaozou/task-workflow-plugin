"""Owned temporary worktree cleanup, generator caches and interrupted Git removal."""
import copy
import json
import os
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
from unittest import mock

from test_workflow import Fixture, w


class CleanupRecoveryTests(Fixture):
    def ready(self):
        self.integrated()
        return self.feature

    def caches(self):
        compiled = self.feature / '__pycache__' / ('code.'+sys.implementation.cache_tag+'.pyc')
        compiled.parent.mkdir()
        py_compile.compile(str(self.feature / 'code.py'),cfile=str(compiled),doraise=True)
        cache = self.feature / '.pytest_cache'; (cache / 'v/cache').mkdir(parents=True)
        (cache / 'README.md').write_text('# pytest cache directory #\n\nThis directory contains data from pytest.\n')
        (cache / '.gitignore').write_text('# Created by pytest automatically.\n*\n')
        (cache / 'CACHEDIR.TAG').write_text('Signature: 8a477f597d28d172789f06886806bc55\n')
        (cache / 'v/cache/nodeids').write_text('["test_native.py::test_result"]')
        (cache / 'v/cache/lastfailed').write_text('{}')
        return compiled,cache

    def interrupt_removal(self, partial=True, unregister=True):
        original = w.run
        def interrupted(argv, **kwargs):
            if 'worktree' in argv and 'remove' in argv:
                if unregister:
                    admin = Path((self.feature / '.git').read_text().strip().partition('gitdir: ')[2])
                    shutil.rmtree(admin)
                if partial:
                    (self.feature / 'code.py').unlink()
                return {'returncode':1,'stdout':'','stderr':'Actual simulated partial Git removal'}
            return original(argv,**kwargs)
        with mock.patch.object(w,'run',side_effect=interrupted):
            result=self.op('cleanup',dry_run=False)
        self.assertTrue(result['cleanup_pending'])
        self.assertNotIn('cleaned',self.state)
        self.assertIn('root_identity',self.state['cleanup_intent'])
        return result

    def test_real_caches_are_disposable_dry_run_preserves_all_bytes(self):
        self.ready();compiled,cache=self.caches()
        before={str(path):path.read_bytes() for path in [compiled,*(value for value in cache.rglob('*') if value.is_file())]}
        version=self.state['version']
        preview=self.op('cleanup',dry_run=True)
        self.assertEqual(self.state['version'],version)
        self.assertEqual(set(preview['disposable_cache_roots']),{'__pycache__','.pytest_cache'})
        self.assertEqual(preview['cleanup_proof']['counts']['cache'],6)
        self.assertEqual(before,{name:Path(name).read_bytes() for name in before})
        compiled.write_bytes(b'Interrupted Python cache write')
        (cache / 'v/cache/nodeids').write_bytes(b'{Interrupted pytest cache write')
        result=self.op('cleanup',dry_run=False)
        self.assertFalse(self.feature.exists())
        self.assertEqual(result['generation_receipt']['cleanup_intent']['proof']['counts']['cache'],6)
        self.assertNotIn('archive',json.dumps(result['generation_receipt']['cleanup_intent']))

    def test_unknown_file_inside_native_named_cache_is_preserved(self):
        self.ready();_,cache=self.caches()
        private=cache / 'user-data.txt';private.write_text('Unique user data')
        self.error('unique_files',lambda:self.op('cleanup',dry_run=False))
        self.assertEqual(private.read_text(),'Unique user data')
        self.assertNotIn('cleanup_intent',self.state)

    def test_unregistered_partial_directory_resumes_from_git_source(self):
        self.ready();self.caches();self.interrupt_removal()
        self.assertFalse(w.cleanup_registration(self.state))
        self.assertTrue(self.feature.exists())
        receipt=self.op('cleanup',dry_run=False)
        self.assertFalse(self.feature.exists())
        self.assertEqual(receipt['generation_receipt']['source_commit'],self.state['integration']['head'])
        self.assertTrue(self.op('cleanup',dry_run=False)['already_cleaned'])

    def test_registered_partial_directory_resumes_and_removes_only_owned_metadata(self):
        self.ready();self.interrupt_removal(unregister=False)
        self.assertTrue(w.cleanup_registration(self.state))
        self.op('cleanup',dry_run=False)
        self.assertFalse(self.feature.exists())
        self.assertFalse(w.cleanup_registration(self.state))

    def test_missing_directory_retries_only_matching_owned_git_metadata(self):
        self.ready();self.interrupt_removal(unregister=False)
        original=w.run
        def metadata_failure(argv,**kwargs):
            if 'worktree' in argv and 'remove' in argv:
                self.assertFalse(self.feature.exists())
                return {'returncode':1,'stdout':'','stderr':'Simulated metadata removal interruption'}
            return original(argv,**kwargs)
        with mock.patch.object(w,'run',side_effect=metadata_failure):
            self.assertTrue(self.op('cleanup',dry_run=False)['cleanup_pending'])
        self.assertFalse(self.feature.exists())
        self.assertTrue(w.cleanup_registration(self.state))
        self.op('cleanup',dry_run=False)
        self.assertFalse(w.cleanup_registration(self.state))

    def test_changed_registered_head_preserves_same_directory(self):
        self.ready();self.interrupt_removal(partial=False,unregister=False)
        self.git(self.feature,'commit','--allow-empty','-m','New unintegrated revision')
        self.error('revision_conflict',lambda:self.op('cleanup',dry_run=False))
        self.assertTrue((self.feature / 'code.py').exists())

    def test_replacement_directory_and_modified_remaining_source_are_preserved(self):
        self.ready();self.interrupt_removal(partial=False)
        (self.feature / 'code.py').write_text('Modified after interruption\n')
        self.error('unique_files',lambda:self.op('cleanup',dry_run=False))
        (self.feature / 'code.py').write_text('VALUE = 2\n')
        previous=self.base / 'original-owned';self.feature.rename(previous);self.feature.mkdir()
        (self.feature / 'user.txt').write_text('Replacement directory data')
        self.error('cleanup_unknown',lambda:self.op('cleanup',dry_run=False))
        self.assertEqual((self.feature / 'user.txt').read_text(),'Replacement directory data')

    def test_environment_symlink_target_is_preserved_and_unknown_link_blocks(self):
        self.ready()
        link=self.feature / '.venv';link.symlink_to(self.environment,target_is_directory=True)
        self.op('environment-register',environment_id='worktree-env-alias',path=str(link),authorization_source='Actual shared development environment alias')
        unknown=self.feature / 'unknown';unknown.symlink_to(self.base,target_is_directory=True)
        self.error('unique_files',lambda:self.op('cleanup',dry_run=False))
        unknown.unlink()
        self.op('cleanup',dry_run=False)
        self.assertTrue((self.environment / 'bin/python').exists())
        self.assertFalse(self.feature.exists())

    def test_legacy_intent_recovers_only_after_complete_absence(self):
        self.ready();self.interrupt_removal()
        legacy=copy.deepcopy(self.state)
        for key in ('root_identity','proof','git_file_sha256','cache_roots'):
            legacy['cleanup_intent'].pop(key,None)
        store=self.root / '.task-workflow'
        self.error('cleanup_unknown',lambda:w.cleanup({'actor':'owner','dry_run':False},legacy,store))
        self.assertTrue(self.feature.exists())
        shutil.rmtree(self.feature)
        result=w.cleanup({'actor':'owner','dry_run':False},legacy,store)
        self.assertEqual(result['removed'],str(self.feature))

    def test_dangling_replacement_link_never_becomes_complete_cleanup(self):
        self.ready()
        original=w.run
        def replace_after_removal(argv,**kwargs):
            result=original(argv,**kwargs)
            if 'worktree' in argv and 'remove' in argv and result['returncode']==0:
                self.feature.symlink_to(self.base / 'unavailable-external-directory',target_is_directory=True)
            return result
        with mock.patch.object(w,'run',side_effect=replace_after_removal):
            self.error('cleanup_unknown',lambda:self.op('cleanup',dry_run=False))
        self.assertTrue(self.feature.is_symlink())
        self.assertNotIn('cleaned',self.state)

    def test_batch_source_proof_uses_no_git_per_file_or_source_archive(self):
        self.tree();self.approved()
        files=self.feature / 'many';files.mkdir()
        for index in range(1200):
            (files / str(index)).write_text('Tracked source '+str(index)+'\n')
        (self.feature / 'code.py').write_text('VALUE = 2\n')
        self.git(self.feature,'add','.');self.git(self.feature,'commit','-m','Batch cleanup source')
        self.complete()
        self.op('integrate',base_branch='main',expected_base=self.git(self.repo,'rev-parse','HEAD'),expected_head=self.git(self.feature,'rev-parse','HEAD'),authorization_source='Fixture batch integration',dry_run=False,commit_message='Batch source')
        self.op('integration-verify',argv=['python','-c','pass'])
        calls=[];original=subprocess.run
        def observe(argv,**kwargs):
            if argv and argv[0]=='git':calls.append(argv)
            return original(argv,**kwargs)
        with mock.patch.object(w.subprocess,'run',side_effect=observe):
            result=self.op('cleanup',dry_run=False)
        self.assertEqual(sum('ls-tree' in argv for argv in calls),1)
        self.assertFalse(any('archive' in argv or 'cat-file' in argv or 'hash-object' in argv for argv in calls))
        self.assertLess(len(calls),60)
        self.assertEqual(result['generation_receipt']['cleanup_intent']['proof']['counts']['tracked'],1202)
