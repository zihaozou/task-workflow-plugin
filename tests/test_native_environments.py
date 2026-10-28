"""Actual native toolchains remain independent of project and plugin Python."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest import mock

from test_workflow import Fixture, w


NODE = shutil.which('node')
RUSTUP_TOOLCHAINS = Path(os.environ.get('RUSTUP_HOME', str(Path.home() / '.rustup'))) / 'toolchains'
RUST_ROOT = next((root for root in sorted(RUSTUP_TOOLCHAINS.glob('*'))
                  if all((root / 'bin' / name).is_file() for name in ('rustc','cargo'))), None)
if RUST_ROOT is None and shutil.which('rustc') and shutil.which('cargo'):
    RUST_ROOT = Path(shutil.which('rustc')).absolute().parent.parent


class NativeEnvironmentTests(Fixture):
    def setUp(self):
        if not NODE:
            self.skipTest('Node is required for actual native startup validation')
        super().setUp()
        self.sdk = self.base / 'sdk'; self.sdk.mkdir()
        self.tools = [{'name':'node', 'argv':[str(Path(NODE).absolute()), '--version']}]
        (self.root / '.task-workflow/environment.json').unlink()
        self.op('environment-bind', path=str(self.sdk), kind='toolchain', tools=self.tools,
                authorization_source='Actual fixture native development toolchain')
        self.op('environment-register', environment_id='native', path=str(self.sdk), kind='toolchain',
                authorization_source='Actual fixture native registration')
        for name in ('code.py', 'uv.lock'):
            (self.repo / name).unlink()
        (self.repo / 'main.js').write_text('require("fs").writeFileSync(require("path").join(process.env.TASK_WORKFLOW_OUTPUT_DIR,"result.txt"), "native result");\n')
        (self.repo / 'package-lock.json').write_text('{"lockfileVersion":3}\n')
        (self.repo / 'validate.js').write_text('const fs=require("fs"),path=require("path");\n'
            'if(process.env.VIRTUAL_ENV||process.env.UV_PROJECT_ENVIRONMENT||process.env.PYTHONPATH) throw Error("Python project environment leaked");\n'
            'fs.writeFileSync(process.env.TASK_WORKFLOW_STARTUP_REPORT,JSON.stringify({token:process.env.TASK_WORKFLOW_STARTUP_TOKEN,references:[],origins:[{id:"entrypoint:main.js",path:path.resolve("main.js")},{id:"entrypoint:validate.js",path:path.resolve("validate.js")}]}));\n')
        self.git(self.repo, 'add', '.'); self.git(self.repo, 'commit', '-m', 'Native source fixture')

    def startup_fields(self):
        return {'snapshot_scope':{'entrypoints':['main.js','validate.js'], 'code':[],
                'configs':['package-lock.json'], 'assets':[]}, 'fixed_references':[],
                'validation_argv':['node','validate.js'], 'origin_checks':[]}

    def complete(self, item='overall'):
        self.op('item-start', item_id=item, actor='implementer')
        self.op('item-submit', item_id=item, actor='implementer')
        self.op('verify', item_id=item, argv=['node','--version'])
        self.op('item-review', item_id=item, actor='reviewer', verdict='accept', notes='Actual native source reviewed.')
        self.op('item-accept', item_id=item, notes='Accepted native evidence.')

    def integrated_native(self):
        self.tree(); self.approved()
        (self.feature / 'main.js').write_text((self.feature / 'main.js').read_text() + '// Integrated native source.\n')
        self.git(self.feature,'add','.'); self.git(self.feature,'commit','-m','Native change')
        self.complete()
        self.op('integrate',base_branch='main',expected_base=self.git(self.repo,'rev-parse','HEAD'),
            expected_head=self.git(self.feature,'rev-parse','HEAD'),authorization_source='Actual native integration',
            dry_run=False,commit_message='Integrate native fixture')
        self.op('integration-verify',argv=['node','--version'])

    def test_native_baseline_and_run_have_no_project_python(self):
        self.assertFalse((self.sdk / 'bin/python').exists())
        with mock.patch.dict(os.environ, {'VIRTUAL_ENV':'/plugin/.venv','UV_PROJECT_ENVIRONMENT':'/plugin/.venv','PYTHONPATH':'/project/python'}):
            baseline = w.prepare_verification_snapshot(self.state, commit=self.git(self.repo,'rev-parse','HEAD'),
                directory=self.root / '.experiments/verification/task/baselines/native', environment_id='native',
                authorization_source='Actual native baseline request', **self.startup_fields())
        self.assertEqual(baseline['startup']['status'],'passed')
        self.assertEqual(baseline['baseline']['environment']['kind'],'toolchain')
        self.refresh()
        self.integrated_native()
        self.op('environment-register',environment_id='native-run',path=str(self.sdk),kind='toolchain',purpose='runtime',
                authorization_source='Actual native fixed runtime registration')
        current = self.prepare(environment_id='native-run', lockfiles=['package-lock.json'],argv=['node','main.js'])['run']
        self.assertEqual(current['argv'][0], str(Path(NODE).absolute()))
        self.op('run-validate',run_id='run',check_id='native-startup')
        self.op('cleanup',dry_run=False)
        result = self.op('run-execute',run_id='run')['run']
        self.assertEqual(result['execution']['returncode'],0)
        self.assertEqual((Path(current['directory']) / 'result.txt').read_text(),'native result')
        self.assertNotIn('cache_root',current['runtime_environment_provenance'])
        self.assertNotIn('/skills/task-workflow/.venv/', result['execution_intent']['runner_argv'][0] if result.get('execution_intent') else w.stable_runtime_python())

    def test_actual_rust_and_node_versions_without_python(self):
        if RUST_ROOT is None:
            self.skipTest('The actual installed Rust toolchain is unavailable')
        tools = [{'name':name,'argv':[str(RUST_ROOT / 'bin' / name),'--version','--verbose']} for name in ('cargo','rustc')]
        tools += self.tools
        fingerprint = w.env_fingerprint(str(RUST_ROOT),kind='toolchain',tools=tools,cwd=str(self.repo))
        versions = {tool['name']:tool['version_stdout'] for tool in fingerprint['tools']}
        self.assertTrue(versions['rustc'].startswith('rustc '))
        self.assertTrue(versions['cargo'].startswith('cargo '))
        self.assertTrue(versions['node'].startswith('v'))
        self.assertFalse((RUST_ROOT / 'bin/python').exists())

    def test_legacy_sdk_annotation_is_sourced_and_idempotent(self):
        file = self.root / '.task-workflow/environment.json'
        binding = json.loads(file.read_text())
        for key in ('kind','tools','toolchain'):
            binding.pop(key,None)
        w.atomic_json(file,binding)
        result=self.op('environment-bind',path=str(self.sdk),kind='toolchain',tools=self.tools,
                       authorization_source='Actual legacy SDK annotation')
        self.assertEqual(result['environment_binding']['binding_id'],binding['binding_id'])
        self.assertIn('toolchain_annotation',result['environment_binding'])
        before=copy.deepcopy(self.state)
        self.op('environment-bind',path=str(self.sdk),kind='toolchain',tools=self.tools,authorization_source='Exact retry')
        self.assertEqual(self.state,before)
        python_binding=copy.deepcopy(binding); python_binding['logical_path']=str(self.environment);python_binding['resolved_path']=str(self.environment)
        w.atomic_json(file,python_binding)
        self.error('environment_conflict',lambda:self.op('environment-bind',path=str(self.environment),kind='toolchain',tools=self.tools,authorization_source='Invalid Python reinterpretation'))

    def test_native_guards_reject_mutable_source_and_plugin_python(self):
        fingerprint=w.registered_env_fingerprint(self.state,'native')
        self.error('unregistered_tool',lambda:w.frozen_argv(['python','-c','pass'],self.state,fingerprint))
        self.error('development_reference',lambda:w.frozen_argv(['node','-e','require('+repr(str(self.repo / 'main.js'))+')'],self.state,fingerprint))
        self.error('development_reference',lambda:w.reject_development_origin(self.state,self.repo / 'main.js',fingerprint))
        alias=self.repo / 'node';alias.symlink_to(NODE)
        self.error('development_reference',lambda:w.env_fingerprint(str(self.sdk),kind='toolchain',tools=[{'name':'node','argv':[str(alias),'--version']}],forbidden=(str(self.repo),)))

    def test_retained_runner_survives_original_plugin_environment_removal(self):
        self.tree(); self.approved()
        self.op('item-start',item_id='overall',actor='implementer')
        self.op('item-submit',item_id='overall',actor='implementer')
        installed=self.base / 'installed-plugin'
        scripts=installed / 'skills/task-workflow/scripts';scripts.mkdir(parents=True)
        source=Path(w.__file__).parent
        for name in ('workflow.py','runner.py','bootstrap.py'):
            shutil.copyfile(source / name,scripts / name)
        plugin_python=installed / 'skills/task-workflow/.venv'
        created=subprocess.run([w.stable_runtime_python(),'-I',str(scripts / 'bootstrap.py'),'--print-python'],
                               check=True,capture_output=True,text=True,cwd=self.base)
        self.assertEqual(Path(created.stdout.strip()),plugin_python / 'bin/python')
        self.assertTrue((plugin_python / '.task-workflow-runtime.json').is_file())
        arguments={'root':str(self.root),'task_id':'task','actor':'owner','expected_version':self.state['version'],
                   'check_id':'retained-native','kind':'verification','item_id':'overall','argv':['node','--version']}
        launched=subprocess.run([str(plugin_python / 'bin/python'),str(scripts / 'workflow.py'),
            'check-dispatch','--root',str(self.root),'--json-args',json.dumps(arguments)],capture_output=True,text=True,check=True)
        result=json.loads(launched.stdout)
        runner=result['runner_argv']
        self.assertFalse(Path(runner[0]).is_relative_to(installed))
        shutil.rmtree(installed)
        self.assertFalse(plugin_python.exists())
        executed=subprocess.run(runner,cwd=self.base,capture_output=True,text=True)
        self.assertEqual(executed.returncode,0,executed.stderr)
        self.refresh()
        self.assertEqual(self.op('check-reconcile',check_id='retained-native')['status'],'passed')

    def test_changed_binary_and_multicall_alias_identity(self):
        executable=self.base / 'multicall';executable.write_text('#!/bin/sh\ncase "$0" in */cargo-alias) echo cargo-fixture;; *) echo wrong;; esac\n');executable.chmod(0o755)
        alias=self.base / 'cargo-alias';alias.symlink_to(executable)
        fingerprint=w.env_fingerprint(str(self.sdk),kind='toolchain',tools=[{'name':'cargo','argv':[str(alias),'--version']}])
        command=w.toolchain_argv(['cargo','--version'],fingerprint)
        self.assertEqual(command[0],str(alias))
        self.assertEqual(subprocess.check_output(command,text=True).strip(),'cargo-fixture')
        executable.write_text(executable.read_text()+'# changed bytes\n')
        self.assertNotEqual(w.refingerprint(fingerprint,self.state),fingerprint)
        binding=copy.deepcopy(self.state['main_environment_binding'])
        binding.update(tools=w.tool_specs(fingerprint['tools']),toolchain=fingerprint)
        w.atomic_json(self.root / '.task-workflow/environment.json',binding)
        self.error('environment_changed',lambda:w.check_execution_environment(self.state,{'main_environment_binding':binding,'cwd':str(self.repo),'argv':[str(alias),'--version']}))
