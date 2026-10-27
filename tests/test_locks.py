"""Owned lock publication, crash recovery and mixed-runtime exclusion."""
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

from test_workflow import w, SCRIPT


CHILD = '''import importlib.util,json,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('child_workflow',sys.argv[1])
w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
path=Path(sys.argv[2])
if len(sys.argv)>3: sys.stdin.readline()
try:
 with w.lock(path):
  print(json.dumps({'status':'held','owner':json.loads(path.read_text())}),flush=True)
  sys.stdin.readline()
except w.WorkflowError as error:print(json.dumps({'status':error.code}),flush=True)
'''


class LockTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='workflow-lock-test-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.path = self.base / 'operation.lock'

    def child(self, wait=False):
        process = subprocess.Popen([sys.executable, '-c', CHILD, str(SCRIPT), str(self.path)] + (['wait'] if wait else []),
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def cleanup():
            if process.poll() is None:
                process.terminate()
            process.communicate()
        self.addCleanup(cleanup)
        return process

    def received(self, process):
        line = process.stdout.readline()
        self.assertTrue(line, process.stderr.read() if process.poll() is not None else 'Child produced no response')
        return json.loads(line)

    def error(self, code, callback):
        with self.assertRaises(w.WorkflowError) as error:
            callback()
        self.assertEqual(error.exception.code, code)

    def acquire(self):
        with w.lock(self.path):
            pass

    def abandoned(self):
        process = self.child()
        held = self.received(process)
        self.assertEqual(held['status'], 'held')
        process.kill(); process.communicate()
        self.assertTrue(self.path.is_file())
        return held['owner']

    def test_complete_publication_and_ordinary_error_cleanup_preserve_guard_inode(self):
        original = w.WorkflowError('original', 'Actual fixture body error')
        with self.assertRaises(w.WorkflowError) as error:
            with w.lock(self.path):
                owner = json.loads(self.path.read_text())
                self.assertEqual(owner['lock_protocol'], 2)
                self.assertEqual(owner['pid'], os.getpid())
                self.assertTrue(owner['token'])
                self.assertFalse(self.path.is_dir())
                raise original
        self.assertIs(error.exception, original)
        self.assertFalse(self.path.exists())
        guard = self.path.with_name(self.path.name + '.guard')
        inode = guard.stat().st_ino
        self.acquire()
        self.assertEqual(guard.stat().st_ino, inode)

    def test_live_process_and_thread_are_never_reaped(self):
        process = self.child()
        self.assertEqual(self.received(process)['status'], 'held')
        self.error('locked', self.acquire)
        process.stdin.write('\n'); process.stdin.flush(); process.communicate()
        results = []
        with w.lock(self.path):
            def contender():
                try:
                    self.acquire()
                except w.WorkflowError as error:
                    results.append(error.code)
            thread = threading.Thread(target=contender)
            thread.start(); thread.join()
            self.assertEqual(results, ['locked'])
        self.acquire()

    def test_dead_local_owner_recovers_and_two_reapers_preserve_the_winner(self):
        owner = self.abandoned()
        if not owner['host']['identity']:
            self.skipTest('This platform cannot prove local kernel identity; recovery remains conservative')
        first, second = self.child(wait=True), self.child(wait=True)
        for process in (first, second):
            process.stdin.write('\n'); process.stdin.flush()
        outcomes = [self.received(process) for process in (first, second)]
        self.assertEqual(sorted(result['status'] for result in outcomes), ['held', 'locked'])
        winner = (first, second)[next(index for index, result in enumerate(outcomes) if result['status'] == 'held')]
        self.assertEqual(json.loads(self.path.read_text())['pid'], winner.pid)
        winner.stdin.write('\n'); winner.stdin.flush()
        for process in (first, second):
            process.communicate()
        self.assertFalse(self.path.exists())

    def test_foreign_unknown_legacy_and_permission_denied_owners_stay_untouched(self):
        owner = self.abandoned()
        original = self.path.read_bytes()
        foreign = {**owner, 'host': {'hostname': 'another-host', 'identity': {'boot': 'foreign'}}}
        self.path.write_text(json.dumps(foreign))
        before = self.path.read_bytes(); self.error('locked', self.acquire)
        self.assertEqual(self.path.read_bytes(), before)
        self.path.write_bytes(original)
        with mock.patch.object(w.os, 'kill', side_effect=PermissionError(errno.EPERM, 'Unknown process ownership')):
            self.error('locked', self.acquire)
        self.assertEqual(self.path.read_bytes(), original)
        self.path.write_text('Unknown regular marker')
        self.error('locked', self.acquire); self.assertEqual(self.path.read_text(), 'Unknown regular marker')
        self.path.unlink(); self.path.mkdir()
        self.error('locked', self.acquire); self.assertEqual(list(self.path.iterdir()), [])
        (self.path / 'owner.json').write_text(json.dumps({'pid': owner['pid'], 'host': owner['host']['hostname']}))
        self.error('locked', self.acquire)
        self.assertTrue((self.path / 'owner.json').exists())

    def test_cleanup_never_deletes_a_replacement_or_masks_the_body_error(self):
        for body_error in (False, True):
            replacement = None
            original = w.WorkflowError('original', 'Body failed')
            with self.assertRaises(w.WorkflowError) as error:
                with w.lock(self.path):
                    owner = json.loads(self.path.read_text())
                    self.path.unlink()
                    owner['token'] = 'f' * 32
                    self.path.write_text(json.dumps(owner))
                    replacement = self.path.read_bytes()
                    if body_error:
                        raise original
            self.assertEqual(error.exception.code, 'original' if body_error else 'lock_changed')
            if body_error:
                self.assertIs(error.exception, original)
            self.assertEqual(self.path.read_bytes(), replacement)
            self.path.unlink()

    def test_cleanup_failure_retains_complete_claim_and_only_own_retired_token_recovers(self):
        for body_error in (False, True):
            original_unlink = Path.unlink
            def blocked(path, *args, **kwargs):
                if path == self.path:
                    raise OSError(errno.EBUSY, 'Synthetic cleanup failure')
                return original_unlink(path, *args, **kwargs)
            with mock.patch.object(Path, 'unlink', blocked):
                with self.assertRaises(w.WorkflowError) as error:
                    with w.lock(self.path):
                        if body_error:
                            raise w.WorkflowError('original', 'Preserve this body error')
            self.assertEqual(error.exception.code, 'original' if body_error else 'lock_cleanup_failed')
            self.assertEqual(json.loads(self.path.read_text())['pid'], os.getpid())
            contender = self.child()
            self.assertEqual(self.received(contender)['status'], 'locked')
            contender.communicate()
            self.acquire()
            self.assertFalse(self.path.exists())

    def test_legacy_mkdir_clients_exclude_new_claims_in_both_directions(self):
        legacy = '''import json,os,sys
from pathlib import Path
path=Path(sys.argv[1])
try:path.mkdir()
except FileExistsError:print('locked',flush=True);sys.exit(0)
try:
 (path/'owner.json').write_text(json.dumps({'pid':os.getpid(),'host':'legacy'}))
 print('held',flush=True);sys.stdin.readline()
finally:(path/'owner.json').unlink();path.rmdir()
'''
        with w.lock(self.path):
            result = subprocess.run([sys.executable, '-c', legacy, str(self.path)], capture_output=True, text=True)
            self.assertEqual(result.stdout.strip(), 'locked')
        process = subprocess.Popen([sys.executable, '-c', legacy, str(self.path)], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), 'held')
            self.error('locked', self.acquire)
        finally:
            process.communicate('\n')
        self.acquire()

    def test_foreign_winner_during_stale_recovery_is_never_removed(self):
        owner = self.abandoned()
        if not owner['host']['identity']:
            self.skipTest('No verified local kernel identity')
        original_link = w.os.link
        winner = {**owner, 'pid': os.getpid(), 'token': 'a' * 32}
        def foreign_wins(source, target, *args, **kwargs):
            Path(target).write_text(json.dumps(winner))
            return original_link(source, target, *args, **kwargs)
        with mock.patch.object(w.os, 'link', side_effect=foreign_wins):
            self.error('locked', self.acquire)
        self.assertEqual(json.loads(self.path.read_text()), winner)

    def test_link_commit_then_client_error_cleans_only_own_claim_or_retires_it(self):
        original_link, original_unlink = w.os.link, Path.unlink
        for cleanup_fails in (False, True):
            def ambiguous(source, target, *args, **kwargs):
                original_link(source, target, *args, **kwargs)
                raise OSError(errno.EIO, 'Synthetic lost link acknowledgement')
            def unlink(path, *args, **kwargs):
                if cleanup_fails and path == self.path:
                    raise OSError(errno.EBUSY, 'Synthetic delayed cleanup')
                return original_unlink(path, *args, **kwargs)
            with mock.patch.object(w.os, 'link', side_effect=ambiguous), mock.patch.object(Path, 'unlink', unlink):
                with self.assertRaises(w.WorkflowError) as error:
                    self.acquire()
            self.assertEqual(error.exception.code, 'lock_unavailable')
            self.assertIsInstance(error.exception.__context__, OSError)
            self.assertEqual(error.exception.__context__.errno, errno.EIO)
            self.assertEqual(self.path.exists(), cleanup_fails)
            self.acquire()
            self.assertFalse(self.path.exists())

    def test_windows_guard_backend_and_close_errors_preserve_original_exception(self):
        calls = []
        windows = types.SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=lambda fd, mode, size: calls.append((mode, size, os.lseek(fd, 0, os.SEEK_CUR))))
        with tempfile.TemporaryFile() as stream, mock.patch.dict(sys.modules, {'msvcrt': windows}):
            w.lock_file_operation(stream.fileno(), True, platform='nt')
            w.lock_file_operation(stream.fileno(), False, platform='nt')
        self.assertEqual(calls, [(1, 1, 0), (2, 1, 0)])
        original_close = os.close
        def close_then_fail(fd):
            original_close(fd)
            raise OSError(errno.EIO, 'Synthetic close error')
        with mock.patch.object(w.os, 'close', side_effect=close_then_fail):
            with self.assertRaises(w.WorkflowError) as error:
                with w.lock_guard(self.path):
                    raise w.WorkflowError('original', 'Preserve guard body failure')
        self.assertEqual(error.exception.code, 'original')
        with mock.patch.object(w, 'lock_file_operation', side_effect=OSError(errno.ENOLCK, 'Unsupported guard')):
            self.error('lock_unavailable', self.acquire)

    @unittest.skipUnless(hasattr(os, 'fork'), 'Fork is not available')
    def test_fork_reuse_drops_inherited_thread_cache_and_guard_descriptors(self):
        script = '''import importlib.util,os,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('fork_workflow',sys.argv[1]);w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
path=Path(sys.argv[2]);read,write=os.pipe()
with w.lock(path):
 child=os.fork()
 if child==0:
  os.close(write);os.read(read,1)
  try:
   with w.lock(path):pass
  except BaseException:os._exit(1)
  os._exit(0)
os.write(write,b'x');os.close(write);os.close(read)
_,status=os.waitpid(child,0);sys.exit(os.waitstatus_to_exitcode(status))
'''
        result = subprocess.run([sys.executable, '-c', script, str(SCRIPT), str(self.path)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())


if __name__ == '__main__':
    unittest.main()
