"""Exercise the installed skill runtime without project environments or packages."""
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'skills/task-workflow/scripts/bootstrap.py'


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='plugin runtime with spaces ')
        self.root = Path(self.temporary.name).resolve()
        self.skill = self.root / 'installed/skills/task-workflow'
        self.scripts = self.skill / 'scripts'
        self.scripts.mkdir(parents=True)
        shutil.copyfile(SOURCE, self.scripts / 'bootstrap.py')
        self.bootstrap = self.scripts / 'bootstrap.py'
        self.environment = dict(os.environ)
        self.environment.update(PYTHONPATH=str(self.root), VIRTUAL_ENV=str(self.root / 'project/.venv'),
                                UV_PROJECT_ENVIRONMENT=str(self.root / 'project/.venv'))
        (self.root / 'json.py').write_text('raise RuntimeError("Ambient module was imported")\n')

    def tearDown(self):
        self.temporary.cleanup()

    def run_bootstrap(self, *args, python=None):
        return subprocess.run([python or sys.executable, '-I', str(self.bootstrap), *args],
                              cwd=self.root, env=self.environment, capture_output=True, text=True)

    def test_unrelated_cwd_owned_interpreter_and_clean_transport(self):
        result = self.run_bootstrap('--print-python')
        self.assertEqual(result.returncode, 0, result.stderr)
        python = result.stdout.strip()
        self.assertEqual(Path(python).parent.parent, self.skill / '.venv')
        self.assertEqual(result.stderr, '')
        probe = self.scripts / 'proof.py'
        probe.write_text('import json,sys,os,importlib.util\nprint(json.dumps({"prefix":sys.prefix,"base":sys.base_prefix,"executable":sys.executable,"pip":importlib.util.find_spec("pip") is not None,"input":sys.stdin.read(),"virtual_env":os.environ.get("VIRTUAL_ENV"),"uv_project":os.environ.get("UV_PROJECT_ENVIRONMENT")}))\n')
        result = subprocess.run([sys.executable, '-I', str(self.bootstrap), '--', str(probe)],
            cwd=self.root, env=self.environment, input='transport payload', capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        facts = json.loads(result.stdout)
        self.assertEqual(Path(facts['prefix']), self.skill / '.venv')
        self.assertNotEqual(facts['prefix'], facts['base'])
        self.assertEqual(facts['executable'], python)
        self.assertFalse(facts['pip'])
        self.assertEqual(facts['input'], 'transport payload')
        self.assertIsNone(facts['virtual_env'])
        self.assertIsNone(facts['uv_project'])
        self.assertEqual(result.stderr, '')
        activate = (self.skill / '.venv/bin/activate')
        if activate.exists():
            self.assertIn(str(self.skill / '.venv'), activate.read_text())
            self.assertNotIn('.runtime-build-', activate.read_text())

    def test_concurrent_creation_returns_one_owned_runtime(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.run_bootstrap('--print-python'), range(4)))
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len({r.stdout for r in results}), 1)
        self.assertFalse(list(self.skill.glob('.runtime-build-*')))

    def test_foreign_directory_or_wrong_owner_is_preserved(self):
        runtime = self.skill / '.venv'; runtime.mkdir()
        sentinel = runtime / 'keep'; sentinel.write_text('user owned')
        for owner in [None, {'schema': 1, 'skill_root': '/another/install', 'base_python': '/other/python'}]:
            if owner is not None:
                (runtime / '.task-workflow-runtime.json').write_text(json.dumps(owner))
            result = self.run_bootstrap('--print-python')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertEqual(sentinel.read_text(), 'user owned')

    def test_symlink_runtime_is_rejected_without_touching_target(self):
        foreign = self.root / 'foreign'; foreign.mkdir(); (foreign / 'keep').write_text('keep')
        (self.skill / '.venv').symlink_to(foreign, target_is_directory=True)
        self.assertNotEqual(self.run_bootstrap('--print-python').returncode, 0)
        self.assertEqual((foreign / 'keep').read_text(), 'keep')

    def test_interrupted_owned_creation_recovers(self):
        result = self.run_bootstrap('--print-python'); self.assertEqual(result.returncode, 0, result.stderr)
        marker = self.skill / '.venv/.task-workflow-runtime.json'
        owner = json.loads(marker.read_text()); owner['status'] = 'creating'; marker.write_text(json.dumps(owner))
        result = self.run_bootstrap('--print-python'); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('status', json.loads(marker.read_text()))

    def test_owned_runtime_rejects_added_package_or_path_injection(self):
        result = self.run_bootstrap('--print-python'); self.assertEqual(result.returncode, 0, result.stderr)
        python = result.stdout.strip()
        site = subprocess.check_output([python, '-I', '-c',
            'import sysconfig; print(sysconfig.get_path("purelib"))'], text=True).strip()
        metadata = Path(site) / 'foreign-1.0.dist-info'
        metadata.mkdir(); (metadata / 'METADATA').write_text('Name: foreign\nVersion: 1.0\n')
        self.assertNotEqual(self.run_bootstrap('--print-python').returncode, 0)
        shutil.rmtree(metadata)
        injection = Path(site) / 'foreign.pth'; injection.write_text('/unrelated/project/.venv\n')
        self.assertNotEqual(self.run_bootstrap('--print-python').returncode, 0)
        self.assertTrue(injection.is_file())

    def test_launch_from_project_venv_uses_existing_base(self):
        project = self.root / 'project/.venv'
        subprocess.run([sys.executable, '-I', '-m', 'venv', '--without-pip', str(project)], check=True)
        executable = project / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        result = self.run_bootstrap('--print-python', python=str(executable))
        self.assertEqual(result.returncode, 0, result.stderr)
        marker = json.loads((self.skill / '.venv/.task-workflow-runtime.json').read_text())
        self.assertFalse(Path(marker['base_python']).is_relative_to(project))
        self.assertFalse(project.is_relative_to(self.skill))

    def test_actual_mcp_hooks_and_context_execute_inside_plugin_runtime(self):
        source_root = SOURCE.parents[3]
        shutil.copyfile(source_root / 'package.json', self.skill.parents[1] / 'package.json')
        for source in SOURCE.parent.glob('*.py'):
            shutil.copyfile(source, self.scripts / source.name)
        # Record the actual interpreter at the common workflow import boundary.
        instrumentation = ('import workflow\nimport os\n'
            '__import__("pathlib").Path(os.environ["TW_RUNTIME_PROOF"]).write_text(json.dumps('
            '{"prefix":sys.prefix,"executable":sys.executable}))')
        for name in ['mcp_server.py', 'session_hook.py', 'communication_prompt_hook.py', 'deepseek_context.py']:
            script = self.scripts / name
            script.write_text(script.read_text().replace('import workflow', instrumentation, 1))
            proof = self.root / (name + '.proof.json')
            environment = dict(self.environment, TW_RUNTIME_PROOF=str(proof))
            payload = {'cwd': str(self.root), 'session_id': 'unbound'}
            if name == 'mcp_server.py':
                payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}}
            elif name.endswith('hook.py'):
                payload.update(hook_event_name='UserPromptSubmit' if name.startswith('communication') else 'SessionStart',
                               source='startup', prompt='A simple question')
            result = subprocess.run([sys.executable, '-I', str(self.bootstrap), name],
                input=json.dumps(payload) + '\n', env=environment, cwd=self.root,
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, (name, result.stderr))
            facts = json.loads(proof.read_text())
            self.assertEqual(Path(facts['prefix']), self.skill / '.venv')
            self.assertEqual(Path(facts['executable']).parent.parent, self.skill / '.venv')
            self.assertEqual(result.stderr, '')
            for line in result.stdout.splitlines():
                json.loads(line)


if __name__ == '__main__':
    unittest.main()
