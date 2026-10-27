/** Native integration evidence. Stub model responses never replace tools or hooks. */
import test from 'node:test';
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn, spawnSync } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import {
  quoteShellArgument, runProcessSync, readContextSync, resolvedHookConfig,
  ownedLifetime, mountChild, releaseRoot, UNAVAILABLE_NOTICE, hookTransportShell, HOOK_TRUNCATED_NOTICE,
} from '../adapters/deepseek/index.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const temporary = () => fs.mkdtempSync(path.join(os.tmpdir(), 'task-workflow-test-'));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const cleanEnvironment = additions => Object.assign(Object.fromEntries(
  ['HOME', 'PATH', 'USER', 'TMPDIR', 'SHELL', 'LANG'].filter(key => process.env[key] !== undefined).map(key => [key, process.env[key]])), additions);
const json = filename => JSON.parse(fs.readFileSync(filename, 'utf8'));
const writeJson = (filename, value) => fs.writeFileSync(filename, JSON.stringify(value, null, 2) + '\n', { mode: 0o600 });
const lines = filename => fs.existsSync(filename) ? fs.readFileSync(filename, 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse) : [];
const treeHashes = directory => {
  const result = {};
  if (!fs.existsSync(directory)) return result;
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const filename = path.join(directory, entry.name);
    if (entry.isDirectory()) for (const [relative, hash] of Object.entries(treeHashes(filename))) result[path.join(entry.name, relative)] = hash;
    else if (entry.isFile()) result[entry.name] = createHash('sha256').update(fs.readFileSync(filename)).digest('hex');
  }
  return result;
};

// These tests require only built-ins and never import native host dependencies.
test('transport: complete numeric-descriptor output has no timeout or maxBuffer', () => {
  const payload = 'large-context-' + 'x'.repeat(1024 * 1024 + 8192);
  let options;
  const before = fs.readdirSync(os.tmpdir()).filter(name => name.startsWith('task-workflow-read-')).sort();
  const result = runProcessSync(process.execPath, ['-e', 'process.stdout.write(require("node:fs").readFileSync(0)); process.stderr.write("diagnostic")'], {
    input: payload, env: cleanEnvironment({}), spawn(command, args, supplied) {
      options = supplied;
      assert.equal(typeof supplied.stdio[1], 'number');
      assert.equal(typeof supplied.stdio[2], 'number');
      return spawnSync(command, args, supplied);
    },
  });
  assert.equal(result.status, 0);
  assert.equal(result.stdout, payload);
  assert.equal(result.stderr, 'diagnostic');
  assert.ok(!Object.hasOwn(options, 'timeout'));
  assert.ok(!Object.hasOwn(options, 'maxBuffer'));
  assert.deepEqual(fs.readdirSync(os.tmpdir()).filter(name => name.startsWith('task-workflow-read-')).sort(), before);
});

test('transport: context distinguishes unbound, current, mismatched and unavailable', () => {
  const request = { cwd: '/synthetic/project', session_id: 'session-a' };
  const context = { session_id: 'session-a', task: { task_id: 'task-a', session_id: 'session-a' }, dialogue_contract: { state_version: 9, canary: 'x'.repeat(1024 * 1024 + 1) } };
  let sent;
  const runtime = { python: 'python3', helper: 'helper.py', environment: () => ({ PRIVATE_TEST: 'safe' }), run(command, args, options) {
    sent = { command, args, options };
    return { status: 0, stdout: JSON.stringify({ ok: true, context }) };
  } };
  const output = readContextSync(request, runtime);
  assert.deepEqual(JSON.parse(output.slice('Registered Task Workflow context: '.length)), context);
  assert.deepEqual(JSON.parse(sent.options.input), request);
  assert.deepEqual(sent.options.env, { PRIVATE_TEST: 'safe' });
  for (const response of [{ status: 1, stdout: 'SECRET' }, { status: 0, stdout: 'bad-json' }, ...[null, [], 'invalid'].map(dialogue_contract => ({status: 0, stdout: JSON.stringify({ok:true,context:{...context,dialogue_contract}})})), { status: 0, signal: 'SIGTERM', stdout: '{}' }, { status: 0, error: new Error('SECRET'), stdout: '{}' }, { status: 0, stdout: JSON.stringify({ ok: true, context: { ...context, session_id: 'other' } }) }]) {
    assert.equal(readContextSync(request, { ...runtime, run: () => response }), UNAVAILABLE_NOTICE);
  }
  assert.equal(readContextSync(request, { ...runtime, run: () => ({ status: 0, stdout: '{"ok":true,"context":null}' }) }), '');
  assert.equal(readContextSync(request, { ...runtime, environment: () => { throw new Error('SECRET'); } }), UNAVAILABLE_NOTICE);
});

test('transport: lossy official hook output is sanitized without changing native limits or metadata', async () => {
  const done = Promise.resolve('native-done');
  const original = { exitCode: 0, signal: null, stdout: { text: 'RAW_PARTIAL_JSON_TAIL', truncated: true }, stderr: { text: '', truncated: false } };
  let calls = 0;
  const native = { resolve(request) { assert.equal(this, native); return { ...request, resolved: true }; }, async execute(spec) {
    assert.equal(this, native); assert.equal(spec.resolved, true);
    return { done, async result() { calls++; return original; }, kill() { return 'native-kill'; } };
  } };
  const facade = hookTransportShell(native);
  const handle = await facade.execute(facade.resolve({ command: 'synthetic' }));
  assert.equal(handle.done, done);
  const first = handle.result(); assert.equal(first, handle.result());
  const result = await first;
  assert.equal(calls, 1);
  assert.equal(result.stdout.text, HOOK_TRUNCATED_NOTICE);
  assert.equal(result.stdout.truncated, true);
  assert.equal(result.exitCode, original.exitCode);
  assert.equal(result.stderr, original.stderr);
  assert.equal(original.stdout.text, 'RAW_PARTIAL_JSON_TAIL');
  assert.equal(handle.kill(), 'native-kill');
});

test('configuration: exact two-hook configuration quotes hostile paths literally', () => {
  const parent = temporary();
  try {
    const directory = path.join(parent, "path with spaces ' $(printf unwanted); [x]");
    fs.mkdirSync(path.join(directory, 'hooks'), { recursive: true });
    fs.copyFileSync(path.join(ROOT, 'hooks/hooks.json'), path.join(directory, 'hooks/hooks.json'));
    const configuration = resolvedHookConfig(directory, process.execPath, 'darwin');
    assert.deepEqual(Object.keys(configuration.hooks).sort(), ['SessionStart', 'UserPromptSubmit']);
    for (const [event, groups] of Object.entries(configuration.hooks)) {
      const script = event === 'SessionStart' ? 'session_hook.py' : 'communication_prompt_hook.py';
      const expected = path.join(directory, 'skills/task-workflow/scripts', script);
      const quoted = quoteShellArgument(expected, 'darwin');
      const actual = spawnSync('/bin/sh', ['-c', `printf '%s' ${quoted}`], { encoding: 'utf8' });
      assert.equal(actual.status, 0);
      assert.equal(actual.stdout, expected);
      assert.ok(groups.every(group => group.hooks.every(hook => hook.command.includes(quoted))));
    }
    assert.equal(quoteShellArgument("C:\\one 'two'\\script.py", 'win32'), "'C:\\one ''two''\\script.py'");
    assert.throws(() => quoteShellArgument('bad\0path'));
    const source = json(path.join(directory, 'hooks/hooks.json'));
    source.hooks.SessionStart[0].hooks[0].async = true;
    writeJson(path.join(directory, 'hooks/hooks.json'), source);
    assert.throws(() => resolvedHookConfig(directory, process.execPath));
  } finally { fs.rmSync(parent, { recursive: true, force: true }); }
  assert.equal(releaseRoot, ROOT);
});

test('ownership: inactive and failed children remain owned for rollback', async () => {
  for (const state of [0, 1, 3, 4]) {
    const events = [];
    const lifetime = ownedLifetime(() => events.push('remove'));
    const child = { state, then(resolve) { resolve(); }, async dispose() { events.push('dispose'); this.state = 4; }, async await() {} };
    await assert.rejects(mountChild({ plugin: () => child }, lifetime, {}, {}), /not active/);
    await lifetime.cleanup();
    assert.deepEqual(events, ['dispose', 'remove']);
  }
  const events = [];
  const lifetime = ownedLifetime(() => events.push('remove'));
  const good = { state: 2, then(resolve) { resolve(); }, async dispose() { events.push('good'); this.state = 4; }, async await() {} };
  const bad = { state: 0, then(resolve, reject) { reject(new Error('activation failed')); }, async dispose() { events.push('bad'); this.state = 4; }, async await() {} };
  let count = 0;
  const ctx = { plugin: () => count++ ? bad : good };
  await mountChild(ctx, lifetime, {}, {});
  await assert.rejects(mountChild(ctx, lifetime, {}, {}), /activation failed/);
  await lifetime.cleanup();
  assert.deepEqual(events, ['good', 'bad', 'remove']);
});

test('ownership: pending child drain precedes config removal and cleanup is idempotent', async () => {
  const events = [], gate = deferred(), entered = deferred();
  const lifetime = ownedLifetime(() => events.push('remove'));
  lifetime.context(() => events.push('context-disposed'));
  lifetime.add({ state: 2, async dispose() { events.push('child-draining'); entered.resolve(); await gate.promise; events.push('child-drained'); this.state = 4; }, async await() {} });
  const first = lifetime.cleanup();
  assert.equal(first, lifetime.cleanup());
  await entered.promise;
  assert.deepEqual(events, ['context-disposed', 'child-draining']);
  assert.throws(() => lifetime.add({}), /disposing/);
  gate.resolve();
  await first;
  assert.deepEqual(events, ['context-disposed', 'child-draining', 'child-drained', 'remove']);
  const failed = ownedLifetime(() => assert.fail('configuration cannot be removed before failed drain is resolved'));
  failed.add({ state: 2, async dispose() { throw new Error('drain failed'); }, async await() { throw new Error('still active'); } });
  await assert.rejects(failed.cleanup(), /cleanup did not complete/);
});

async function execute(command, args, { cwd, env, receipt } = {}) {
  const child = spawn(command, args, { cwd, env, stdio: ['ignore', 'pipe', 'pipe'] });
  const output = [], errors = [];
  child.stdout.on('data', chunk => output.push(chunk));
  child.stderr.on('data', chunk => errors.push(chunk));
  const result = await new Promise((resolve, reject) => { child.once('error', reject); child.once('close', (code, signal) => resolve({ code, signal })); });
  const data = { command, args, ...result, stdout: Buffer.concat(output).toString(), stderr: Buffer.concat(errors).toString() };
  if (receipt) writeJson(receipt, data);
  assert.equal(result.code, 0, `${command} failed; inspect ${receipt || 'test output'}\n${data.stderr}`);
  return data;
}

class Sdk {
  constructor(cli, directory, env, receipts) {
    this.sequence = 0; this.pending = new Map(); this.events = []; this.receipts = receipts;
    this.wire = fs.createWriteStream(path.join(receipts, 'sdk-wire.jsonl'), { flags: 'wx', mode: 0o600 });
    this.errors = fs.createWriteStream(path.join(receipts, 'runtime.stderr.txt'), { flags: 'wx', mode: 0o600 });
    this.child = spawn(cli, ['--profile', 'workflow-test'], { cwd: directory, env, stdio: ['pipe', 'pipe', 'pipe'] });
    this.child.stderr.pipe(this.errors);
    let tail = '';
    this.child.stdout.on('data', chunk => {
      tail += chunk.toString();
      for (;;) {
        const boundary = tail.indexOf('\n'); if (boundary < 0) break;
        const line = tail.slice(0, boundary); tail = tail.slice(boundary + 1); if (!line.trim()) continue;
        this.wire.write(line + '\n');
        const frame = JSON.parse(line);
        if (Object.hasOwn(frame, 'id')) {
          const pending = this.pending.get(frame.id); if (!pending) continue;
          this.pending.delete(frame.id);
          frame.error ? pending.reject(new Error(JSON.stringify(frame.error))) : pending.resolve(frame.result);
        } else this.events.push(frame);
      }
    });
    this.exit = new Promise((resolve, reject) => {
      this.child.once('error', reject);
      this.child.once('close', (code, signal) => {
        this.wire.end(); this.errors.end();
        for (const waiter of this.pending.values()) waiter.reject(new Error(`Native runtime closed (${code}, ${signal}); receipts: ${receipts}`));
        this.pending.clear(); resolve({ code, signal });
      });
    });
    writeJson(path.join(receipts, 'live-handle.json'), { pid: this.child.pid, cli, directory, receipts });
  }
  call(method, params = {}) {
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
    });
  }
  async prompt(sessionId, text) {
    await this.call('session/prompt', { sessionId, contentBlocks: [{ type: 'text', text }] });
    await this.call('session/wait', { sessionId });
  }
  async close() {
    if (this.child.exitCode !== null) return this.exit;
    const descendants = [];
    const pending = [this.child.pid];
    while (pending.length) {
      const parent = pending.pop();
      const listing = spawnSync('pgrep', ['-P', String(parent)], { encoding: 'utf8' });
      if (listing.error) throw listing.error;
      assert.ok(listing.status === 0 || listing.status === 1);
      for (const value of listing.stdout.trim().split(/\s+/).filter(Boolean)) {
        const pid = Number(value); if (!descendants.includes(pid)) { descendants.push(pid); pending.push(pid); }
      }
    }
    try { await this.call('shutdown'); } finally { this.child.stdin.end(); }
    const result = await this.exit;
    assert.equal(result.code, 0, `Native runtime did not shut down cleanly: ${this.receipts}`);
    for (const pid of descendants) assert.throws(() => process.kill(pid, 0), error => error.code === 'ESRCH', `Owned native child ${pid} must exit`);
    writeJson(path.join(this.receipts, 'closed-handle.json'), { pid: this.child.pid, descendants, ...result, noObservedOrphans: true });
    return result;
  }
}

function probeSource() {
  return `// Private deterministic test provider; native tools, hooks and runtime are real.
import { appendFileSync, readFileSync } from 'node:fs';
import { LlmAdapter } from '@deepseek-ai/dsh-llm';
const receipt = value => appendFileSync(process.env.TW_TEST_RECEIPT, JSON.stringify(value) + '\\n');
export const inject = ['llm', 'skills', 'tools', 'workingDirectory', 'compaction'];
export async function apply(ctx) {
  const workspace = process.cwd();
  const task = 'native-task';
  let compactAfterTool = false;
  let observedAgent;
  const source = reference => ({kind:'user',reference});
  const req = (id,text,kind,reference,confirmation=reference) => ({id,text,kind,status:'confirmed',source:source(reference),confirmation_source:source(confirmation)});
  const action = (op,args,mutation=true) => ({op,args,mutation});
  function actions(stage) {
    if(stage==='BOOTSTRAP') return [
      action('schema',{root:workspace},false),
      action('init',{root:workspace,project:workspace,task_id:task,title:'Synthetic JSON report task',actor:'native-test',authorization_source:'synthetic-bootstrap-request',session_id:'native-session',integration_required:false},false),
      action('process-intent',{intent:{goal:'Add JSON output while preserving CSV.',why:'Synthetic script compatibility fixture.',success_criteria:['JSON is readable and CSV behavior remains.'],source:source('synthetic-bootstrap-request')}}),
      action('process-exploration',{exploration:{current_behavior:'The fixture README records an existing CSV command.',evidence:['README.md'],unknowns:[]}}),
      action('process-question',{question:{id:'output-choice',text:'Where should NONPROMPTED_FIRST_CANARY JSON output go?',rationale:'The destination defines the output interface.',scope:[],important:true,source:{kind:'agent',reference:'synthetic-question-1'}}}),
    ];
    if(stage==='ISOLATE') return [];
    if(stage==='STATUS') return [action('context',{root:workspace,task_id:task},false)];
    if(stage==='ANSWER') return [
      action('process-answer',{question_id:'output-choice',answer:'Use stdout.',source:source('synthetic-answer-1')}),
      action('process-requirements',{requirements:[req('csv','Preserve CSV.','constraint','synthetic-bootstrap-request'),req('json','Write JSON to stdout.','acceptance','synthetic-answer-1')]}),
      action('process-decision',{decision:{id:'destination',title:'JSON destination',choice:'Write JSON to stdout.',rationale:'The synthetic user selected stdout.',scope:['json'],status:'confirmed',source:source('synthetic-answer-1'),confirmation_source:source('synthetic-answer-1'),question_id:'output-choice'}}),
      action('process-question',{question:{id:'correction-choice',text:'Confirm NONPROMPTED_SECOND_CANARY output requirements?',rationale:'A correction must preserve source authority.',scope:['json'],important:true,source:{kind:'agent',reference:'synthetic-question-2'}}}),
    ];
    if(stage==='CORRECT') return [
      action('process-answer',{question_id:'correction-choice',answer:'Correction: write JSON to a file, preserving CSV.',source:source('synthetic-correction-2')}),
      action('process-requirements',{requirements:[req('csv','Preserve CSV.','constraint','synthetic-bootstrap-request'),req('json','Write JSON to a file.','acceptance','synthetic-answer-1','synthetic-correction-2')]}),
      action('process-decision',{decision:{id:'destination',title:'JSON destination',choice:'Write JSON to a file.',rationale:'The synthetic user corrected the destination.',scope:['json'],status:'confirmed',source:source('synthetic-answer-1'),confirmation_source:source('synthetic-correction-2'),question_id:'correction-choice'}}),
    ];
    if(stage==='COMPACT') return [action('process-question',{question:{id:'after-compact',text:'Which target uses NONPROMPTED_COMPACT_CANARY?',rationale:'Verify refresh after same-turn native compaction.',scope:['json'],important:true,source:{kind:'agent',reference:'synthetic-question-3'}}})];
    if(stage==='LARGE') return [
      action('process-answer',{question_id:'after-compact',answer:'Use the existing target.',source:source('synthetic-answer-3')}),
      action('process-question',{question:{id:'large-context',text:'LARGE_CONTEXT_BEGIN_'+'x'.repeat(1024*1024+4096)+'_LARGE_CONTEXT_END',rationale:'Complete native transport fixture.',scope:['json'],important:true,source:{kind:'agent',reference:'synthetic-large-question'}}}),
    ];
    throw new Error('Unknown fixture stage: '+stage);
  }
  class Stub extends LlmAdapter {
    async *stream(options) {
      if (options.purpose === 'compaction') {
        receipt({kind:'auxiliary-summary-request',messages:options.messages});
        yield {type:'block-start',index:0,blockType:'text'};
        yield {type:'text-delta',index:0,text:'The synthetic task preserves CSV and adds JSON export. Important authority remains in the workflow record.'};
        yield {type:'finish',reason:{kind:'stop'}};
        return;
      }
      receipt({kind:'model-request',eventSeq:observedAgent?.session.seq,messages:options.messages,tools:options.tools});
      const direct = [...options.messages].reverse().find(message=>message.role==='user'&&message.content.some(block=>block.type==='text'&&block.text.startsWith('TW_TEST_')));
      const prompt = direct?.content.find(block=>block.type==='text'&&block.text.startsWith('TW_TEST_'))?.text;
      const stage = prompt?.match(/^TW_TEST_([A-Z]+)/)?.[1];
      if(this.prompt!==prompt) { this.prompt=prompt; this.queue=actions(stage); }
      const resultMessage=[...options.messages].reverse().find(message=>message.role==='tool'&&message.toolCallId===this.pending);
      if(resultMessage&&this.pending) {
        if(resultMessage.isError) throw new Error('Native tool error: '+JSON.stringify(resultMessage));
        const value=JSON.parse(resultMessage.content.filter(block=>block.type==='text').map(block=>block.text).join('\\n'));
        receipt({kind:'actual-tool-result',callId:this.pending,op:this.operation,result:value});
        if(value.ok!==true) throw new Error('Workflow rejected fixture operation: '+JSON.stringify(value));
        this.version=value.state?.version??value.dialogue_contract?.state_version??this.version;
        this.pending=undefined;
      }
      const next=this.queue.shift();
      if(next) {
        const args=next.mutation?{root:workspace,task_id:task,actor:'native-test',expected_version:this.version,...next.args}:next.args;
        if(stage==='COMPACT') compactAfterTool = true;
        this.pending='native-call-'+(++this.counter|| (this.counter=1)); this.operation=next.op;
        receipt({kind:'scripted-call',stage,op:next.op,args,callId:this.pending});
        yield {type:'block-start',index:0,blockType:'tool-call'};
        yield {type:'block-end',index:0,block:{type:'tool-call',id:this.pending,name:'mcp__task-workflow__'+next.op,arguments:JSON.stringify(args)}};
        yield {type:'finish',reason:{kind:'tool-calls'}};
      } else {
        receipt({kind:'stage-complete',stage,version:this.version});
        yield {type:'block-start',index:0,blockType:'text'};
        yield {type:'text-delta',index:0,text:'Synthetic stage '+stage+' completed using native tools.'};
        yield {type:'finish',reason:{kind:'stop'}};
      }
    }
  }
  ctx.llm.registerAdapter(['workflow-test-stub'],new Stub());
  ctx.on('agent/created',async({agent})=>{
    observedAgent=agent;
    const loaded=await ctx.skills.get('task-workflow',{scope:agent,cwd:workspace});
    receipt({kind:'capabilities',session:agent.session.header.id,schemas:ctx.tools.schemas(agent),skill:{name:loaded?.name,path:loaded?.path,hasContent:!!loaded?.content}});
  });
  ctx.on('agent/pre-step',async ({agent,messages,signal},next)=>{
    if(compactAfterTool && messages.length===0) {
      compactAfterTool=false;
      const events=agent.session.ownEvents();
      const firstEnd=events.find(event=>event.type==='turn/end');
      if(!firstEnd) throw new Error('Balanced completed history is required for actual compaction');
      const nodes=agent.session.surface.nodes.filter(seq=>seq<=firstEnd.seq && events.find(event=>event.seq===seq)?.type!=='system/message');
      receipt({kind:'compact-selected',start:nodes[0],end:nodes.at(-1),beforeSeq:agent.session.seq,beforeSurface:[...agent.session.surface.nodes],turnOpen:true,offeredMessages:messages.length});
      const result=await ctx.compaction.compactRegion(nodes[0],nodes.at(-1),agent,signal);
      receipt({kind:'compact-completed',result,afterSeq:agent.session.seq,afterSurface:[...agent.session.surface.nodes],events:agent.session.ownEvents().filter(event=>event.type.startsWith('compaction/'))});
    }
    return next();
  });
  ctx.effect(()=>()=>receipt({kind:'probe-disposed'}));
}
`;
}

async function makeFixture(cli, t) {
  const run = path.join(process.env.DSH_TEST_ARTIFACT_ROOT || path.join(os.homedir(), 'Experiments/task-workflow-plugin/deepseek-integration/runs'), `${new Date().toISOString().replaceAll(':', '-')}-${randomUUID()}`);
  fs.mkdirSync(run, { recursive: true, mode: 0o700 });
  t.diagnostic(`Native evidence and live handle: ${run}`);
  const workspace = path.join(run, 'workspace');
  const other = path.join(run, 'other-project');
  for (const directory of [workspace, other, path.join(run, 'agents-home'), path.join(run, 'artifacts')]) fs.mkdirSync(directory, { recursive: true });
  const env = cleanEnvironment({ DSH_HOME: path.join(run, 'dsh-home'), DSH_AGENTS_HOME: path.join(run, 'agents-home'), DSH_PRIMARY_RUNTIME: '', TW_TEST_RECEIPT: path.join(run, 'probe.jsonl') });
  const profile = path.join(env.DSH_HOME, 'profiles/workflow-test');
  fs.mkdirSync(profile, { recursive: true });
  writeJson(path.join(profile, 'package.json'), { name: 'private-native-workflow-test', private: true, type: 'module', dsh: { profile: { bundles: ['@deepseek-ai/dsh-sdk-minimal'] } } });
  fs.writeFileSync(path.join(profile, 'cordis.patch.yml'), '[]\n');
  for (const directory of [workspace, other]) {
    fs.writeFileSync(path.join(directory, 'README.md'), '# Synthetic fixture\n\nThe existing report command writes CSV.\n');
    await execute('git', ['init', '-q', directory]);
    await execute('git', ['-C', directory, 'add', 'README.md']);
    await execute('git', ['-C', directory, '-c', 'user.name=Native Fixture', '-c', 'user.email=fixture@example.invalid', '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Synthetic test fixture']);
  }
  const packed = await execute('npm', ['pack', '--json', '--pack-destination', path.join(run, 'artifacts')], { cwd: ROOT, env, receipt: path.join(run, 'pack.json') });
  const archive = path.join(run, 'artifacts', JSON.parse(packed.stdout)[0].filename);
  await execute(cli, ['plugin', '--profile', 'workflow-test', 'add', '--save-exact', archive, '@deepseek-ai/dsh-hooks-codex@0.2.1-rc.3', '@deepseek-ai/dsh-hook-protocol@0.2.1-rc.3'], { cwd: workspace, env, receipt: path.join(run, 'install.json') });
  const installed = path.join(profile, 'node_modules/@local/task-workflow');
  assert.equal(json(path.join(installed, 'package.json')).version, '0.1.9');
  assert.ok(json(path.join(profile, 'package.json')).dsh.profile.bundles.includes('@local/task-workflow'));
  const probe = path.join(profile, 'node_modules/@local/workflow-test-probe');
  fs.mkdirSync(probe, { recursive: true });
  writeJson(path.join(probe, 'package.json'), { name: '@local/workflow-test-probe', private: true, type: 'module', main: 'index.js', peerDependencies: { '@deepseek-ai/dsh-llm': '0.2.1-rc.3' } });
  fs.writeFileSync(path.join(probe, 'index.js'), probeSource());
  fs.writeFileSync(path.join(profile, 'cordis.patch.yml'), `# Private exploration/test composition; no Desktop or auth state.\n- insert:\n    - id: native-test-shell\n      name: '@deepseek-ai/dsh-bash-local'\n    - id: native-test-skills\n      name: '@deepseek-ai/dsh-skill'\n    - id: native-test-probe\n      name: '@local/workflow-test-probe'\n`);
  writeJson(path.join(run, 'fixture.json'), { cli, run, workspace, other, profile, installed, archive, archiveSha256: createHash('sha256').update(fs.readFileSync(archive)).digest('hex'), provider: 'workflow-test-stub', model: 'stub', realProvider: false });
  return { cli, run, workspace, other, profile, installed, archive, env };
}

function currentRuntimeContext(request) {
  for (const message of [...request.messages].reverse()) {
    if (message.source?.kind !== 'runtime-context') continue;
    const section = message.source.sections?.find(section => section.name === 'task-workflow:current');
    if (!section) continue;
    if (section.text === UNAVAILABLE_NOTICE) return { unavailable: true };
    if (section.text.startsWith('Registered Task Workflow context: ')) return JSON.parse(section.text.slice('Registered Task Workflow context: '.length));
  }
  return null;
}
function requireCurrentContext(receipts, version, question) {
  const request = [...receipts].reverse().find(item => item.kind === 'model-request');
  assert.ok(request);
  const context = currentRuntimeContext(request);
  assert.equal(context?.task.task_id, 'native-task');
  assert.equal(context?.dialogue_contract.state_version, version);
  assert.equal(context?.dialogue_contract.pending_questions[0]?.id, question);
  assert.ok(context.dialogue_contract.current_runtime.workflow_entrypoint.endsWith('/skills/task-workflow/scripts/workflow.py'));
  return context;
}

function requireStage(fixture, stage) {
  const receipts = lines(path.join(fixture.run, 'probe.jsonl'));
  const completed = receipts.filter(item => item.kind === 'stage-complete' && item.stage === stage).at(-1);
  assert.ok(completed, `Native stage ${stage} did not complete; inspect ${fixture.run}`);
  return { receipts, completed };
}

const CLI = process.env.DSH_TEST_CLI;
if (!CLI) test('installed runtime: acceptance requires explicit DSH_TEST_CLI', () => {
  assert.fail('Installed-runtime acceptance is blocked without DSH_TEST_CLI. Run only the named low-level groups for dependency-free checks.');
});
if (CLI) test('installed runtime: real archive, schemas, tools, authority, status, resume and isolation', async t => {
  const fixture = await makeFixture(CLI, t);
  const receipts = path.join(fixture.run, 'first-runtime'); fs.mkdirSync(receipts);
  let sdk = new Sdk(CLI, fixture.workspace, fixture.env, receipts);
  try {
    await sdk.call('initialize', { cwd: fixture.workspace, provider: 'workflow-test-stub', model: 'stub' });
    await sdk.prompt('native-session', 'TW_TEST_BOOTSTRAP: Synthetic request: add JSON while preserving CSV.');
    const bootstrap = requireStage(fixture, 'BOOTSTRAP');
    const capability = bootstrap.receipts.find(item => item.kind === 'capabilities' && item.session === 'native-session');
    assert.equal(capability.skill.name, 'task-workflow'); assert.equal(capability.skill.hasContent, true);
    const advertised = capability.schemas.filter(item => item.name.startsWith('mcp__task-workflow__'));
    const actualSchema = bootstrap.receipts.find(item => item.kind === 'actual-tool-result' && item.op === 'schema').result.commands;
    assert.equal(actualSchema.length, 53); assert.equal(advertised.length, actualSchema.length);
    for (const command of actualSchema) {
      const native = advertised.find(item => item.name === 'mcp__task-workflow__' + command.name);
      assert.ok(native, command.name); assert.deepEqual(native.parameters, command.inputSchema); assert.equal(native.description, command.description);
    }
    const firstContext = requireCurrentContext(bootstrap.receipts, bootstrap.completed.version, 'output-choice');
    assert.ok(firstContext.dialogue_contract.pending_questions[0].text.includes('NONPROMPTED_FIRST_CANARY'));
    const taskDir = path.join(fixture.workspace, '.task-workflow/tasks/native-task');
    const before = treeHashes(taskDir);
    await sdk.prompt('native-session', 'TW_TEST_STATUS: Where are we now?');
    requireStage(fixture, 'STATUS'); assert.deepEqual(treeHashes(taskDir), before);
    await sdk.prompt('native-session', 'TW_TEST_ANSWER: Use stdout.'); requireStage(fixture, 'ANSWER');
    await sdk.prompt('native-session', 'TW_TEST_CORRECT: Correction: write JSON to a file, preserving CSV.'); requireStage(fixture, 'CORRECT');
    const state = json(path.join(taskDir, 'state.json'));
    const decision = state.process.decisions.find(item => item.id === 'destination');
    assert.equal(decision.choice, 'Write JSON to a file.');
    assert.equal(decision.source.reference, 'synthetic-answer-1');
    assert.equal(decision.confirmation_source.reference, 'synthetic-correction-2');
    assert.equal(decision.question_id, 'correction-choice');
    await sdk.prompt('native-session', 'TW_TEST_COMPACT: Continue the synthetic task without changing its scope.');
    const compact = requireStage(fixture, 'COMPACT');
    const completedCompact = compact.receipts.find(item => item.kind === 'compact-completed');
    assert.ok(completedCompact, 'An actual compactRegion transaction must complete');
    assert.ok(completedCompact.events.some(event => event.type === 'compaction/start'));
    assert.ok(completedCompact.events.some(event => event.type === 'compaction/summary'));
    assert.ok(completedCompact.events.some(event => event.type === 'compaction/end' && !event.data.error));
    const selection = compact.receipts.find(item => item.kind === 'compact-selected');
    assert.ok(!completedCompact.afterSurface.includes(selection.start), 'Native surface replacement must remove the selected start');
    assert.ok(compact.receipts.some(item => item.kind === 'model-request' && item.eventSeq >= completedCompact.afterSeq), 'A model request must follow actual compaction');
    const compactContext = requireCurrentContext(compact.receipts, compact.completed.version, 'after-compact');
    assert.ok(compactContext.dialogue_contract.pending_questions[0].text.includes('NONPROMPTED_COMPACT_CANARY'));
    assert.ok(compact.receipts.some(item => item.kind === 'compact-selected' && item.offeredMessages === 0));
    let finalState = json(path.join(taskDir, 'state.json'));
    await sdk.close();
    assert.equal(fs.readFileSync(path.join(receipts, 'runtime.stderr.txt'), 'utf8'), '');
    const resumed = path.join(fixture.run, 'resumed-runtime'); fs.mkdirSync(resumed);
    sdk = new Sdk(CLI, fixture.workspace, fixture.env, resumed);
    await sdk.call('initialize', { cwd: fixture.workspace, provider: 'workflow-test-stub', model: 'stub' });
    await sdk.call('session/resume', { sessionId: 'native-session' });
    assert.ok(sdk.events.some(frame => frame.method === 'session.event' && frame.params.event.type === 'agent/inbox/spliced'
      && frame.params.event.data.inserted?.some(message => message.source?.kind === 'hooks-codex'
        && message.content.some(block => block.type === 'text' && block.text.includes('native-task') && block.text.includes('after-compact')))),
      'The actual resumed SessionStart hook must inject context before any new prompt');
    await sdk.prompt('native-session', 'TW_TEST_STATUS: Where are we now?');
    const status = requireStage(fixture, 'STATUS');
    assert.equal(status.completed.version, finalState.version);
    requireCurrentContext(status.receipts, finalState.version, 'after-compact');
    assert.ok(sdk.events.some(frame => frame.method === 'session.event' && frame.params.event.type === 'hook/invoked' && frame.params.event.data.point === 'UserPromptSubmit'));
    assert.ok(sdk.events.some(frame => frame.method === 'session.event' && frame.params.event.type === 'hook/result' && frame.params.event.data.point === 'UserPromptSubmit'));
    await sdk.prompt('native-session', 'TW_TEST_LARGE: Continue the complete-context transport fixture.');
    const large = requireStage(fixture, 'LARGE');
    const largeContext = requireCurrentContext(large.receipts, large.completed.version, 'large-context');
    const text = largeContext.dialogue_contract.pending_questions[0].text;
    assert.ok(text.startsWith('LARGE_CONTEXT_BEGIN_') && text.endsWith('_LARGE_CONTEXT_END'));
    assert.ok(Buffer.byteLength(text) > 1024 * 1024);
    finalState = json(path.join(taskDir, 'state.json'));
    const largeBefore = treeHashes(taskDir);
    const noticeEventsStart = sdk.events.length;
    await sdk.prompt('native-session', 'TW_TEST_STATUS: Read-only large context check.');
    assert.deepEqual(treeHashes(taskDir), largeBefore);
    const largeStatus = requireStage(fixture, 'STATUS');
    requireCurrentContext(largeStatus.receipts, finalState.version, 'large-context');
    const hookMessages = sdk.events.slice(noticeEventsStart).filter(frame => frame.method === 'session.event' && frame.params.event.type === 'user/message')
      .map(frame => frame.params.event.data).filter(message => message.source?.kind === 'hooks-codex');
    assert.ok(hookMessages.some(message => message.content.some(block => block.text === HOOK_TRUNCATED_NOTICE)), 'Actual large prompt hook must report observed host truncation');
    assert.ok(hookMessages.every(message => message.content.every(block => block.type !== 'text' || block.text === HOOK_TRUNCATED_NOTICE)), 'No raw truncated JSON tail may become hook context');
    const unchanged = treeHashes(taskDir);
    // A different real native session has no implicit association to native-task.
    await sdk.call('session/working-directory/get', { sessionId: 'unbound-session' });
    await sdk.prompt('unbound-session', 'TW_TEST_ISOLATE: Read-only unassociated session check.');
    let isolated = lines(path.join(fixture.run, 'probe.jsonl')).filter(item => item.kind === 'model-request').at(-1);
    assert.equal(currentRuntimeContext(isolated), null);
    await sdk.call('session/working-directory/set', { sessionId: 'unbound-session', path: fixture.other });
    await sdk.prompt('unbound-session', 'TW_TEST_ISOLATE: Read-only other project check.');
    isolated = lines(path.join(fixture.run, 'probe.jsonl')).filter(item => item.kind === 'model-request').at(-1);
    assert.equal(currentRuntimeContext(isolated), null);
    assert.deepEqual(treeHashes(taskDir), unchanged);
    const stateFile = path.join(taskDir, 'events', fs.readdirSync(path.join(taskDir, 'events')).sort()[0]);
    const preservedEvent = path.join(fixture.run, 'preserved-immutable-event.json');
    fs.renameSync(stateFile, preservedEvent);
    try {
      fs.writeFileSync(stateFile, '{synthetic-invalid-state');
      await sdk.prompt('native-session', 'TW_TEST_ISOLATE: Synthetic context-read failure check.');
      const unavailable = lines(path.join(fixture.run, 'probe.jsonl')).filter(item => item.kind === 'model-request').at(-1);
      assert.deepEqual(currentRuntimeContext(unavailable), { unavailable: true });
    } finally { fs.rmSync(stateFile, { force: true }); fs.renameSync(preservedEvent, stateFile); }
    assert.deepEqual(treeHashes(taskDir), unchanged);
    await sdk.close();
    const largeResumeDirectory = path.join(fixture.run, 'large-resume-runtime'); fs.mkdirSync(largeResumeDirectory);
    sdk = new Sdk(CLI, fixture.workspace, fixture.env, largeResumeDirectory);
    await sdk.call('initialize', { cwd: fixture.workspace, provider: 'workflow-test-stub', model: 'stub' });
    await sdk.call('session/resume', { sessionId: 'native-session' });
    const resumedInsertions = sdk.events.filter(frame => frame.method === 'session.event' && frame.params.event.type === 'agent/inbox/spliced')
      .flatMap(frame => frame.params.event.data.inserted || []).filter(message => message.source?.kind === 'hooks-codex');
    assert.ok(resumedInsertions.some(message => message.content.some(block => block.text === HOOK_TRUNCATED_NOTICE)), 'Actual large SessionStart hook must report host truncation');
    assert.ok(resumedInsertions.every(message => message.content.every(block => block.type !== 'text' || block.text === HOOK_TRUNCATED_NOTICE)));
    await sdk.prompt('native-session', 'TW_TEST_STATUS: Verify large bound resume.');
    requireCurrentContext(requireStage(fixture, 'STATUS').receipts, finalState.version, 'large-context');
    assert.deepEqual(treeHashes(taskDir), unchanged);
    await sdk.close();
    const final = { result: 'passed', source: 'installed runtime with scripted LLM only', schemas: 53, stateVersion: finalState.version, taskUnchangedAfterStatus: true, actualToolCalls: status.receipts.filter(item => item.kind === 'actual-tool-result').length };
    writeJson(path.join(fixture.run, 'functional-result.json'), final);
    assert.ok(lines(path.join(fixture.run, 'probe.jsonl')).some(item => item.kind === 'probe-disposed'));
  } finally { if (sdk.child.exitCode === null) await sdk.close(); }
});

if (process.env.DSH_TEST_REAL_PROVIDER) test('live-provider: supervised current Desktop route acceptance is required', () => {
  assert.fail('Blocked: the installed Desktop profile has no SDK stdio endpoint. Use supervised Desktop acceptance with its existing authorized route/authentication and native child completion; do not copy credentials, guess a Flash ID, or count stub evidence as provider obedience.');
});

async function waitFile(filename, sdk) {
  if (fs.existsSync(filename)) return;
  await new Promise((resolve, reject) => {
    const watcher = fs.watch(path.dirname(filename), () => {
      if (fs.existsSync(filename)) { watcher.close(); resolve(); }
    });
    if (fs.existsSync(filename)) { watcher.close(); resolve(); }
    sdk.exit.then(() => { watcher.close(); if (!fs.existsSync(filename)) reject(new Error(`Runtime exited before ${filename}`)); }, reject);
  });
}

function faultProbeSource() {
  return `// Private fault-injection fixture. Never loaded by the product package.
import * as fs from 'node:fs';
import * as path from 'node:path';
import { LlmAdapter } from '@deepseek-ai/dsh-llm';
const root=process.env.TW_FAULT_ROOT;
const receipt=value=>fs.appendFileSync(path.join(root,'fault.jsonl'),JSON.stringify(value)+'\\n');
const marker=(name,value={})=>fs.writeFileSync(path.join(root,name),JSON.stringify(value));
const waitFile=name=>fs.existsSync(path.join(root,name))?Promise.resolve():new Promise(resolve=>{
  const watch=fs.watch(root,()=>{if(fs.existsSync(path.join(root,name))){watch.close();resolve();}});
  if(fs.existsSync(path.join(root,name))){watch.close();resolve();}
});
export const inject=['llm'];
export async function apply(ctx) {
  const Native=await import(process.env.TW_FAULT_ENTRY);
  class Stub extends LlmAdapter {async *stream(options){receipt({kind:'model',messages:options.messages});yield{type:'text-delta',index:0,text:'Fault fixture settled.'};yield{type:'finish',reason:{kind:'stop'}};}}
  ctx.llm.registerAdapter(['workflow-test-stub'],new Stub());
  const mode=process.env.TW_FAULT_MODE;
  let parent,target;
  let targetReady; const targetCreated=new Promise(resolve=>targetReady=resolve);
  let applyReady; const applyEntered=new Promise(resolve=>applyReady=resolve);
  const configFile=path.join(root,'owned-config');
  if(mode==='parent-barrier') {
    fs.writeFileSync(configFile,'owned configuration');
    const lifetime=Native.ownedLifetime(()=>{fs.unlinkSync(configFile);receipt({kind:'config-removed'});});
    parent=ctx.plugin({name:'real-parent',apply(parentCtx){
      const child=parentCtx.plugin({name:'real-slow-child',apply(childCtx){childCtx.effect(()=>async()=>{
        receipt({kind:'child-drain-start'});marker('drain-started');await waitFile('release');receipt({kind:'child-drain-end'});
      });}});
      lifetime.add(child);
      parentCtx.effect(()=>()=>lifetime.cleanup());
    }});
    await parent;
    marker('ready',{state:parent.state,configPath:configFile});
  } else {
    parent=ctx.plugin({name:'real-parent',apply(parentCtx){target=parentCtx.plugin(mode==='during-activation'?{...Native,apply(nativeCtx){const result=Native.apply(nativeCtx);applyReady();return result;}}:Native);targetReady();}});
    if(mode==='during-activation') {
      await targetCreated;
      await applyEntered;
      const before=target.state;
      await Native.disposeChild(parent);
      receipt({kind:'disposed-during-activation',before,parentState:parent.state,targetState:target?.state});
      marker('ready',{state:parent.state});marker('unloaded');return;
    }
    await parent;
    try{await target;}catch(error){receipt({kind:'activation-error',message:String(error)});}
    const configs=fs.readdirSync(process.env.TMPDIR).filter(name=>name.startsWith('task-workflow-hooks-')).map(name=>path.join(process.env.TMPDIR,name,'hooks.json')).filter(name=>fs.existsSync(name));
    receipt({kind:'actual-fiber-state',parent:parent.state,target:target.state,configs});
    marker('ready',{state:target.state,configPath:configs[0]});
  }
  let unloading=false;
  const watch=fs.watch(root,async(_event,name)=>{
    if(name!=='unload'||unloading||!fs.existsSync(path.join(root,'unload')))return;
    unloading=true;
    receipt({kind:'parent-unload-start'});
    try {
      await Native.disposeChild(parent);
      receipt({kind:'parent-unloaded',parentState:parent.state,targetState:target?.state});
      marker('unloaded');
    } catch(error){receipt({kind:'unload-error',message:String(error)});marker('unloaded',{error:String(error)});}
  });
  ctx.effect(()=>()=>watch.close());
}
`;
}

async function faultCase(fixture, mode, t) {
  const directory = path.join(fixture.run, mode); fs.mkdirSync(directory);
  const temporaryRoot = path.join(directory, 'temporary'); fs.mkdirSync(temporaryRoot);
  const copy = path.join(fixture.profile, 'node_modules/@local', 'fault-copy-' + mode);
  fs.cpSync(fs.realpathSync(fixture.installed), copy, { recursive: true });
  const baseline = treeHashes(copy);
  if (mode === 'invalid-config') fs.writeFileSync(path.join(copy, 'hooks/hooks.json'), '{}');
  if (mode === 'failed-mcp') fs.writeFileSync(path.join(copy, 'skills/task-workflow/scripts/mcp_server.py'), 'raise RuntimeError("Synthetic startup failure")\n');
  if (mode === 'startup-inflight' || mode === 'prompt-inflight') {
    const event = mode === 'startup-inflight' ? 'SessionStart' : 'UserPromptSubmit';
    const script = `# Private fault-injected installed copy, not immutable candidate/source.\nimport json,os,signal,time\nfrom pathlib import Path\npayload=json.load(__import__('sys').stdin)\nroot=Path(os.environ['TW_FAULT_ROOT'])\nif payload['hook_event_name']==${JSON.stringify(event)}:\n    (root/'hook-started').write_text(json.dumps({'pid':os.getpid(),'event':payload['hook_event_name']}))\n    def stop(*args):\n        (root/'hook-terminating').write_text('owned callback draining')\n        while not (root/'release').exists():time.sleep(0.005)\n    signal.signal(signal.SIGTERM,stop)\n    while not (root/'release').exists():time.sleep(0.005)\n    (root/'hook-finished').write_text('finished')\nprint(json.dumps({'hookSpecificOutput':{'hookEventName':payload['hook_event_name'],'additionalContext':'FAULT_CONTEXT_'+payload['hook_event_name']}}))\n`;
    for (const scriptName of ['session_hook.py', 'communication_prompt_hook.py']) fs.writeFileSync(path.join(copy, 'skills/task-workflow/scripts', scriptName), script);
  }
  writeJson(path.join(directory, 'fault-injection.json'), { mode, immutableArchive: fixture.archive, baseline, injected: treeHashes(copy) });
  const manifest = json(path.join(fixture.profile, 'package.json'));
  manifest.dsh.profile.bundles = manifest.dsh.profile.bundles.filter(name => name !== '@local/task-workflow');
  writeJson(path.join(fixture.profile, 'package.json'), manifest);
  const probe = path.join(fixture.profile, 'node_modules/@local/workflow-test-probe/index.js');
  fs.writeFileSync(probe, faultProbeSource());
  const skillRow = mode === 'missing-service' ? '' : "    - id: native-test-skills\n      name: '@deepseek-ai/dsh-skill'\n";
  fs.writeFileSync(path.join(fixture.profile, 'cordis.patch.yml'), "- insert:\n    - id: native-test-shell\n      name: '@deepseek-ai/dsh-bash-local'\n" + skillRow + "    - id: native-test-fault-probe\n      name: '@local/workflow-test-probe'\n");
  const env = { ...fixture.env, TMPDIR: temporaryRoot, TW_FAULT_ROOT: directory, TW_FAULT_MODE: mode, TW_FAULT_ENTRY: pathToFileURL(path.join(copy, 'adapters/deepseek/index.js')).href };
  const sdk = new Sdk(fixture.cli, fixture.workspace, env, directory);
  let pending;
  try {
    await sdk.call('initialize', { cwd: fixture.workspace, provider: 'workflow-test-stub', model: 'stub' });
    await waitFile(path.join(directory, 'ready'), sdk);
    const ready = json(path.join(directory, 'ready'));
    if (mode === 'during-activation') {
      assert.equal(ready.state, 4);
      const activated = lines(path.join(directory, 'fault.jsonl')).find(item => item.kind === 'disposed-during-activation');
      assert.ok(activated && activated.before !== 2 && activated.targetState === 4, 'The actual adapter must be loading, then disposed');
      assert.equal(fs.readdirSync(temporaryRoot).filter(name => name.startsWith('task-workflow-hooks-')).length, 0);
    } else if (['missing-service', 'invalid-config', 'failed-mcp'].includes(mode)) {
      assert.notEqual(ready.state, 2, `${mode} must not be active`);
      const actualFailure = lines(path.join(directory, 'fault.jsonl')).find(item => item.kind === 'activation-error');
      if (mode === 'missing-service') assert.equal(ready.state, 0);
      else {
        assert.ok(actualFailure, `${mode} must record its real activation failure`);
        assert.ok(!actualFailure.message.includes('ERR_MODULE_NOT_FOUND'), 'Fault fixture dependencies must resolve before intended failure');
        if (mode === 'invalid-config') assert.match(actualFailure.message, /Missing workflow hook registration/);
        if (mode === 'failed-mcp') assert.match(actualFailure.message, /initial connection or tool synchronization failed/);
      }
      fs.writeFileSync(path.join(directory, 'unload'), 'dispose');
      await waitFile(path.join(directory, 'unloaded'), sdk);
      assert.ok(!json(path.join(directory, 'unloaded')).error);
      assert.equal(fs.readdirSync(temporaryRoot).filter(name => name.startsWith('task-workflow-hooks-')).length, 0);
    } else {
      assert.equal(ready.state, 2);
      if (mode === 'parent-barrier') {
        fs.writeFileSync(path.join(directory, 'unload'), 'dispose');
        await waitFile(path.join(directory, 'drain-started'), sdk);
        assert.ok(fs.existsSync(ready.configPath), 'Real automatic child drain must retain configuration');
      } else {
        const session = 'fault-' + mode;
        if (mode === 'prompt-inflight') await sdk.call('session/working-directory/get', { sessionId: session });
        pending = sdk.call('session/prompt', { sessionId: session, contentBlocks: [{ type: 'text', text: 'Synthetic owned-hook barrier test.' }] }).then(value => ({ value }), error => ({ error: String(error) }));
        await waitFile(path.join(directory, 'hook-started'), sdk);
        const hook = json(path.join(directory, 'hook-started'));
        assert.ok(hook.pid > 0);
        process.kill(hook.pid, 0);
        fs.writeFileSync(path.join(directory, 'unload'), 'dispose');
        await waitFile(path.join(directory, 'hook-terminating'), sdk);
        assert.ok(fs.existsSync(ready.configPath), `${mode}: config must exist during actual official hook drain`);
        process.kill(hook.pid, 0);
      }
      writeJson(path.join(directory, 'configuration-during-drain.json'), { path: ready.configPath, exists: fs.existsSync(ready.configPath), mode });
      fs.writeFileSync(path.join(directory, 'release'), 'release owned work');
      await waitFile(path.join(directory, 'unloaded'), sdk);
      assert.ok(!json(path.join(directory, 'unloaded')).error);
      assert.equal(fs.existsSync(ready.configPath), false);
      if (pending) writeJson(path.join(directory, 'prompt-settlement.json'), await pending);
      const faultReceipts = lines(path.join(directory, 'fault.jsonl'));
      assert.ok(faultReceipts.some(item => item.kind === 'parent-unloaded' && item.parentState === 4));
      if (mode !== 'parent-barrier') {
        await waitFile(path.join(directory, 'hook-finished'), sdk);
        const pid = json(path.join(directory, 'hook-started')).pid;
        assert.throws(() => process.kill(pid, 0), error => error.code === 'ESRCH', 'Owned hook process must be gone');
      }
    }
    await sdk.close();
    if (mode === 'startup-inflight' || mode === 'prompt-inflight') {
      const point = mode === 'startup-inflight' ? 'SessionStart' : 'UserPromptSubmit';
      for (const request of lines(path.join(directory, 'fault.jsonl')).filter(item => item.kind === 'model')) {
        assert.ok(!JSON.stringify(request.messages).includes('FAULT_CONTEXT_' + point), 'Disposed bridge must not add late context');
      }
    }
    writeJson(path.join(directory, 'result.json'), { mode, result: 'passed', immutableArchiveUnchanged: true });
    t.diagnostic(`Actual ${mode} evidence: ${directory}`);
  } finally {
    // Release only test-owned work if an assertion fails; never leave a barrier hung.
    fs.writeFileSync(path.join(directory, 'release'), 'cleanup');
    if (sdk.child.exitCode === null) await sdk.close();
  }
}

if (CLI) test('installed ownership: real parent unload, failed startup, activation disposal and official hook drains', async t => {
  const fixture = await makeFixture(CLI, t);
  const before = createHash('sha256').update(fs.readFileSync(fixture.archive)).digest('hex');
  for (const mode of ['missing-service', 'invalid-config', 'failed-mcp', 'during-activation', 'parent-barrier', 'startup-inflight', 'prompt-inflight']) await faultCase(fixture, mode, t);
  assert.equal(createHash('sha256').update(fs.readFileSync(fixture.archive)).digest('hex'), before);
});
