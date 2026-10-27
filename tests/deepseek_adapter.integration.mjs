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
  hookOwnership, capabilityContext,
  WORKFLOW_SCOPE,
} from '../adapters/deepseek/index.js';
import { ownedDelegations, collectionTools, delegationFacades, DELEGATE_TOOL } from '../adapters/deepseek/delegation.js';
import { taskScopedRecovery, INVALID_TOOL_JSON, CONTEXT_PREFIX } from '../adapters/deepseek/recovery.js';

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

test('dialogue: only human hook input changes, while whole downstream batches survive', async () => {
  let wrapper;
  const prompts = [];
  const hooks = hookOwnership();
  hooks.on({ on(event, handler) { assert.equal(event, 'agent/pre-step'); wrapper = handler; return () => {}; } }, 'agent/pre-step', async (payload, next) => {
    prompts.push(payload.messages);
    return next();
  });
  const human = { id: 'human', source: { kind: 'user' }, content: [{ type: 'text', text: 'Actual human prompt' }] };
  const report = { id: 'report', source: { kind: 'agent-message', senderSessionId: 'child' }, content: [{ type: 'text', text: 'New worker finding' }] };
  const settlement = { id: 'settled', source: { kind: 'subagent-settled', senderSessionId: 'child' }, content: [{ type: 'text', text: 'New final report' }] };
  for (const messages of [[report], [settlement], [human, report, settlement], [human]]) {
    const downstream = { kind: 'enter', messages, startsRequestSeries: true };
    const actual = await wrapper({ agent: { id: 'parent' }, messages }, async () => downstream);
    assert.equal(actual, downstream);
    assert.equal(actual.messages, messages);
  }
  assert.deepEqual(prompts, [[human], [human]]);
  await hooks.close();
});

test('dialogue: each capability snapshot uses the actual current native catalog', () => {
  const agent = { id: 'parent' };
  let names = ['wait_agent', 'native-tool'];
  const ctx = { tools: { schemas(actual) { assert.equal(actual, agent); return names.map(name => ({ name })); } } };
  assert.ok(capabilityContext(ctx, agent).includes('wait_agent'));
  names = ['native-tool', 'task_workflow_delegate', 'task_workflow_wait', 'task_workflow_cancel'];
  const current = capabilityContext(ctx, agent);
  assert.ok(!current.includes('wait_agent'));
  assert.ok(current.includes('"owned_delegation_available":true'));
});

test('dialogue: native question guidance follows current schema and runtime root ownership', () => {
  const agent = { id: 'resumed-child', session: { header: { parentSessionId: 'historical-parent' } } };
  const schema = { name: 'ask_user_question', parameters: { type: 'object', properties: { questions: { type: 'array' } } } };
  let schemas = [schema], roots = [agent];
  const ctx = { tools: { schemas: () => schemas }, get(name) { assert.equal(name, 'agents'); return { roots: () => roots }; } };
  const read = () => JSON.parse(capabilityContext(ctx, agent).split(': ', 2)[1]).user_question;
  const current = read();
  assert.equal(current.available, true); assert.equal(current.current_root, true);
  assert.deepEqual(current.parameters, schema.parameters);
  for (const rule of ['actually call ask_user_question', 'status-only request', 'approval_target', 'discussion-only']) assert.ok(current.protocol.includes(rule));
  for (const rule of ['unique exact submitted-label', 'current conversation language', 'Omit options', 'do not add a wait duration']) assert.ok(current.identity.includes(rule));
  for (const rule of ['custom input takes precedence', 'Empty, skipped', 'pending/timed', 'user-question-reply', 'question_digest', 'approval_target', 'original call']) assert.ok(current.answer_rule.includes(rule));
  roots = [];
  assert.equal(read().current_root, false);
  schemas = [];
  assert.equal(read().available, false); assert.equal(read().parameters, undefined);
});

test('dialogue: workflow scope and current native skill loader remain explicit for unbound requests', () => {
  const agent = { id: 'unbound' };
  let schemas = [{ name: 'skill', parameters: { type: 'object', properties: { name: { type: 'string' } }, required: ['name'] } }];
  const ctx = { tools: { schemas: () => schemas } };
  const read = () => JSON.parse(capabilityContext(ctx, agent).split(': ', 2)[1]);
  const current = read();
  assert.equal(current.applicability, WORKFLOW_SCOPE);
  for (const rule of ['ordinary conversation', 'direct answer', 'preserves the current stage/wait', 'no authority']) assert.ok(current.applicability.includes(rule));
  assert.equal(current.skill_loader.available, true);
  assert.deepEqual(current.skill_loader.arguments, { name: 'task-workflow' });
  assert.deepEqual(current.skill_loader.parameters, schemas[0].parameters);
  assert.equal(current.skill_loader.main_skill_path, path.join(ROOT, 'skills/task-workflow/SKILL.md'));
  assert.ok(fs.existsSync(current.skill_loader.main_skill_path));
  assert.ok(current.skill_loader.instruction.includes('supported file-reading tool'));
  assert.ok(current.skill_loader.instruction.includes('does not prove the skill was read'));
  schemas = [];
  assert.equal(read().skill_loader.available, false); assert.equal(read().skill_loader.arguments, undefined);
  assert.deepEqual(read().owned_activations, []);
  schemas = [{ name: 'skill', parameters: { type: 'object', properties: { other: { type: 'string' } } } }];
  assert.equal(read().skill_loader.arguments, undefined);
});

const nativeParent = id => ({ id, session: { header: { id } } });

function recoveryFixture({ names = ['mcp__task-workflow__process-question'], message = INVALID_TOOL_JSON } = {}) {
  let current = { root: '/synthetic', session_id: 'recovery-session', task: { task_id: 'recovery-task', session_id: 'recovery-session', task_status: 'open' }, dialogue_contract: { state_version: 7 } };
  let catalog = names.map(name => ({ name, parameters: { type: 'object' } }));
  const text = () => CONTEXT_PREFIX + JSON.stringify(current);
  const agent = { session: { header: { id: 'recovery-session' }, requestHeader: () => ({ config: { provider: 'fixture' }, tools: names.map(name => ({ name, parameters: { type: 'object' } })) }) } };
  const recovery = taskScopedRecovery({ readCurrent: text, toolSchemas: () => catalog, streamChunks: (stream, type) => stream.filter(chunk => chunk.type === type) });
  const signal = new AbortController();
  const payload = { agent, turn: 1, step: 2, provider: 'fixture', failure: { code: 'MALFORMED_RESPONSE', message }, signal: signal.signal,
    retryPolicy: { mode: 'normal', maxRetries: 0, retryableCodes: ['MALFORMED_RESPONSE'], initialDelayMs: 3, maxDelayMs: 9, jitterRatio: 0 } };
  function capture(seq = 10, { closed = true } = {}) {
    recovery.captureContext(agent, text());
    recovery.observeFrame({ agent, frame: { type: 'start', attemptId: 'attempt-' + seq, turn: 1, step: 2 } });
    const stream = names.flatMap((name, index) => [{ type: 'block-start', index, blockType: 'tool-call' }, ...(closed ? [{ type: 'block-end', index, block: { type: 'tool-call', name, arguments: 'not repaired' } }] : [])]);
    stream.push({ type: 'finish', reason: { kind: 'error', failure: payload.failure } });
    recovery.observeEvent(agent.session, { type: 'assistant/attempt', seq, data: { turn: 1, step: 2, stream } });
    recovery.observeFrame({ agent, frame: { type: 'end', attemptId: 'attempt-' + seq, outcome: { kind: 'committed', eventType: 'assistant/attempt', seq } } });
  }
  const wrap = listener => { let result; recovery.on({ on(event, callback) { result = callback; return () => {}; } }, 'agent/request-error', listener); return result; };
  return { recovery, agent, payload, signal, capture, wrap, changeBinding() { current.dialogue_contract.state_version++; }, changeCatalog() { catalog = []; }, changeSchema() { catalog[0] = { ...catalog[0], parameters: { type: 'object', required: ['new_field'] } }; } };
}

test('recovery: exact durable workflow attempts extend finite policy without repairing arguments', async () => {
  const fixture = recoveryFixture();
  const original = structuredClone(fixture.payload.retryPolicy);
  let downstream = 0, scheduled = 0;
  const callback = fixture.wrap(async (payload, next) => {
    assert.deepEqual(payload.retryPolicy, { mode: 'always', initialDelayMs: 3, maxDelayMs: 9, jitterRatio: 0 });
    assert.equal(await next(), undefined); scheduled++; return { kind: 'retry' };
  });
  for (let index = 0; index < 8; index++) {
    fixture.capture(10 + index);
    assert.equal((await callback(fixture.payload, async () => { downstream++; })).kind, 'retry');
  }
  assert.equal(scheduled, 8); assert.equal(downstream, 8);
  assert.deepEqual(fixture.payload.retryPolicy, original);
  assert.ok(fixture.recovery.context(fixture.agent).includes('No tools from that failed response were dispatched'));
  assert.ok(!fixture.recovery.context(fixture.agent).includes('not repaired'));
  fixture.recovery.close();
});

test('recovery: unknown, mixed, incomplete, unbound and other failures retain native handling', async () => {
  for (const options of [{ names: ['native_other'] }, { names: ['mcp__task-workflow__process-question', 'native_other'] }, { message: 'DeepSeek Messages stream: invalid block index' }, { incomplete: true }, { unbound: true }, { policy: false }]) {
    const fixture = recoveryFixture(options);
    fixture.capture(10, { closed: !options.incomplete });
    if (options.unbound) fixture.recovery.captureContext(fixture.agent, 'unavailable');
    if (options.policy === false) fixture.payload.retryPolicy = undefined;
    // An unavailable current read must fail closed even with a prior captured binding.
    if (options.unbound) fixture.changeBinding();
    let owned = 0, native = 0;
    const result = await fixture.wrap(async () => { owned++; })(fixture.payload, async () => { native++; return { kind: 'native' }; });
    assert.deepEqual(result, { kind: 'native' }); assert.equal(owned, 0); assert.equal(native, 1);
    fixture.recovery.close();
  }
});

test('recovery: a consumed hint cannot survive a later unrelated failed attempt', async () => {
  const fixture = recoveryFixture(); fixture.capture();
  const callback = fixture.wrap(async (_payload, next) => { await next(); return { kind: 'retry' }; });
  await callback(fixture.payload, async () => undefined);
  assert.ok(fixture.recovery.context(fixture.agent));
  fixture.payload.failure = { code: 'MALFORMED_RESPONSE', message: 'Different native malformed response' };
  fixture.capture(11);
  assert.equal(fixture.recovery.context(fixture.agent), '');
  const native = { kind: 'retry' };
  assert.equal(await callback(fixture.payload, async () => native), native);
  assert.equal(fixture.recovery.context(fixture.agent), ''); fixture.recovery.close();
});

test('recovery: post-backoff task/catalog guards affect only added retries and disposal aborts own wait', async () => {
  for (const mutate of ['changeBinding', 'changeCatalog', 'changeSchema']) {
    const fixture = recoveryFixture(); fixture.capture();
    const entered = deferred(), release = deferred();
    const callback = fixture.wrap(async (_payload, next) => { await next(); entered.resolve(); await release.promise; return { kind: 'retry' }; });
    const pending = callback(fixture.payload, async () => undefined);
    await entered.promise; fixture[mutate](); release.resolve();
    assert.equal(await pending, undefined);
    fixture.recovery.close();
  }
  const inherited = recoveryFixture(); inherited.capture();
  const decision = { kind: 'retry' };
  const preserved = await inherited.wrap(async (_payload, next) => next())(inherited.payload, async () => { inherited.changeBinding(); return decision; });
  assert.equal(preserved, decision, 'Existing downstream retry retains object identity and authority');
  inherited.recovery.close();
  const unloading = recoveryFixture(); unloading.capture();
  const waiting = deferred(), release = deferred();
  const nativePending = unloading.wrap(async (payload, next) => {
    const result = await next();
    return payload.signal.aborted ? undefined : result;
  })(unloading.payload, async () => { waiting.resolve(); await release.promise; return decision; });
  await waiting.promise; unloading.recovery.close(); release.resolve();
  assert.equal(await nativePending, decision, 'Plugin disposal cannot revoke a completed native-owned retry decision');
  const cleanupFailure = recoveryFixture(); cleanupFailure.capture();
  assert.equal(await cleanupFailure.wrap(async (_payload, next) => { await next(); throw new Error('Owned listener cleanup failed'); })(cleanupFailure.payload, async () => decision), decision);
  cleanupFailure.recovery.close();
  for (const stop of ['caller', 'plugin']) {
    const fixture = recoveryFixture(); fixture.capture(); const entered = deferred();
    const pending = fixture.wrap(async (payload, next) => {
      await next(); entered.resolve();
      await new Promise(resolve => payload.signal.addEventListener('abort', resolve, { once: true }));
      return undefined;
    })(fixture.payload, async () => undefined);
    await entered.promise;
    if (stop === 'caller') fixture.signal.abort(); else fixture.recovery.close();
    assert.equal(await pending, undefined); fixture.recovery.close();
  }
});

test('delegation: initial handoff publication is excluded without excluding a later real human', async () => {
  const publication = deferred(), result = deferred();
  let spec;
  const registry = ownedDelegations({ async startActivation(actual) {
    spec = actual; await publication.promise;
    return { childId: actual.childId, messageId: 'handoff', result: result.promise, dispose: async () => { result.resolve({ output: [], stopReason: 'aborted' }); } };
  } });
  const parent = nativeParent('parent');
  const start = registry.start({ provider: 'spawn', request: { parent }, signal: new AbortController().signal });
  await Promise.resolve();
  assert.equal(spec.delivery, 'caller');
  const handoff = { id: 'handoff', source: { kind: 'user' } };
  const human = { id: 'later-human', source: { kind: 'user' } };
  const report = { id: 'worker-report', source: { kind: 'agent-message' } };
  let admitted = false;
  const input = registry.humanMessages({ id: spec.childId }, [handoff, human, report]).then(value => { admitted = true; return value; });
  await Promise.resolve(); assert.equal(admitted, false);
  publication.resolve(); await start;
  assert.deepEqual(await input, [human]);
  await registry.close();
});

test('delegation: caller abort leaves work intact and completion waits for exact cleanup', async () => {
  const result = deferred(), cleanup = deferred(), disposing = deferred();
  let calls = 0;
  const registry = ownedDelegations({ async startActivation(spec) {
    return { childId: spec.childId, messageId: 'initial', result: result.promise,
      async dispose() { calls++; disposing.resolve(); await cleanup.promise; } };
  } });
  const parent = nativeParent('parent');
  const handle = await registry.start({ request: { parent } });
  const owned = registry.descriptor(handle.childId, parent);
  const caller = new AbortController();
  const abandoned = registry.wait(owned.handleId, parent, caller.signal);
  caller.abort(); await assert.rejects(abandoned, { name: 'AbortError' }); assert.equal(calls, 0);
  const final = { output: [{ type: 'text', text: 'Exact native closing report' }], stopReason: 'completed', structured: { checked: true } };
  let collected = false;
  const wait = registry.wait(owned.handleId, parent).then(value => { collected = true; return value; });
  result.resolve(final); await disposing.promise;
  assert.equal(collected, false);
  cleanup.resolve();
  const outcome = await wait;
  assert.equal(outcome.result, final); assert.equal(outcome.cleanup.status, 'complete'); assert.equal(calls, 1);
  await registry.close();
});

test('delegation: foreign handles are rejected and concurrent cancel/wait targets only the owned activation', async () => {
  const result = deferred(); let disposed = 0;
  const registry = ownedDelegations({ async startActivation(spec) {
    return { childId: spec.childId, messageId: 'initial', result: result.promise,
      async dispose() { disposed++; result.resolve({ output: [], stopReason: 'aborted' }); } };
  } });
  const parent = nativeParent('parent'), foreign = nativeParent('parent');
  const handle = await registry.start({ request: { parent } });
  const owned = registry.descriptor(handle.childId, parent);
  await assert.rejects(registry.cancel(owned.handleId, foreign), /unavailable/);
  await assert.rejects(registry.cancel('unowned-native-child', parent), /unavailable/);
  assert.equal(disposed, 0);
  const [canceled, waited] = await Promise.all([registry.cancel(owned.handleId, parent), registry.wait(owned.handleId, parent)]);
  assert.equal(canceled, waited); assert.equal(canceled.result.stopReason, 'aborted'); assert.equal(disposed, 1);
  await registry.close();
});

test('delegation: unload drains a racing owned start and exposes cleanup failures', async () => {
  const publication = deferred(), result = deferred(); let disposed = 0;
  const registry = ownedDelegations({ async startActivation(spec) {
    await publication.promise;
    return { childId: spec.childId, messageId: 'initial', result: result.promise,
      async dispose() { disposed++; result.resolve({ output: [], stopReason: 'aborted' }); } };
  } });
  const start = registry.start({ request: { parent: nativeParent('parent') } });
  const rejected = assert.rejects(start, /disposed during startup/);
  const close = registry.close(); publication.resolve();
  await rejected; await close; assert.equal(disposed, 1);
  const failed = ownedDelegations({ async startActivation(spec) {
    return { childId: spec.childId, messageId: 'initial', result: Promise.resolve({ output: [], stopReason: 'completed' }),
      async dispose() { throw new Error('Synthetic owned cleanup failure'); } };
  } });
  const parent = nativeParent('other');
  const handle = await failed.start({ request: { parent } });
  const outcome = await failed.wait(failed.descriptor(handle.childId, parent).handleId, parent);
  assert.equal(outcome.result.stopReason, 'completed'); assert.equal(outcome.cleanup.status, 'failed');
  const token = failed.descriptor(handle.childId, parent).handleId;
  await assert.rejects(failed.disposeParent(parent), /cleanup did not complete/);
  assert.deepEqual(failed.context(parent), []);
  await assert.rejects(failed.wait(token, parent), /unavailable/);
  await assert.rejects(failed.close(), /cleanup did not complete/);
});

test('delegation: parent disposal aborts unpublished work and releases completed handle entries', async () => {
  const entered = deferred();
  const registry = ownedDelegations({ async startActivation(spec) {
    entered.resolve();
    await new Promise((resolve, reject) => { spec.signal.addEventListener('abort', () => reject(new Error('Synthetic native startup aborted')), { once: true }); });
  } });
  const parent = nativeParent('parent');
  const start = registry.start({ request: { parent } });
  const rejected = assert.rejects(start, /startup aborted/);
  await entered.promise; await registry.disposeParent(parent); await rejected;
  assert.deepEqual(registry.context(parent), []);
  await assert.rejects(registry.start({ request: { parent } }), /disposed/);
  await registry.close();
  const complete = ownedDelegations({ async startActivation(spec) {
    return { childId: spec.childId, messageId: 'initial', result: Promise.resolve({ output: [], stopReason: 'completed' }), dispose: async () => {} };
  } });
  const live = nativeParent('live');
  const handle = await complete.start({ request: { parent: live } });
  const descriptor = complete.descriptor(handle.childId, live);
  await complete.wait(descriptor.handleId, live); await complete.disposeParent(live);
  assert.deepEqual(complete.context(live), []);
  await assert.rejects(complete.wait(descriptor.handleId, live), /unavailable/);
  await complete.close();
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

function probeSource(questions = false) {
  return `// Private deterministic test provider; native tools, hooks and runtime are real.
import { appendFileSync, readFileSync } from 'node:fs';
import { LlmAdapter, createUserMessage } from '@deepseek-ai/dsh-llm';
const receipt = value => appendFileSync(process.env.TW_TEST_RECEIPT, JSON.stringify(value) + '\\n');
export const inject = ['llm', 'skills', 'tools', 'workingDirectory', 'compaction'${questions ? ", 'agents', 'userQuestions'" : ''}];
export async function apply(ctx) {
  const workspace = process.cwd();
  const task = 'native-task';
  let compactAfterTool = false;
  let observedAgent;
  let questionMode = 'skip';
  if (${questions}) ctx.on('user-questions/request', async request => {
    receipt({kind:'synthetic-question-request',questions:request.questions,session:request.agent.id,currentRoot:ctx.get('agents').roots().includes(request.agent)});
    if(questionMode==='pending') { const {UserQuestionError}=await import('@deepseek-ai/dsh-user-questions'); throw new UserQuestionError('Synthetic unanswered batch','ASK_TIMED_OUT'); }
    return {answers:request.questions.map(question=>({id:question.id,selected:questionMode==='skip'?[]:[question.options[0].label],...(questionMode==='custom'?{custom:'Use a third destination; preserve original source.'}:{})}))};
  });
  const source = reference => ({kind:'user',reference});
  const req = (id,text,kind,reference,confirmation=reference) => ({id,text,kind,status:'confirmed',source:source(reference),confirmation_source:source(confirmation)});
  const action = (op,args,mutation=true) => ({op,args,mutation});
  function actions(stage) {
    if(stage==='BOOTSTRAP') return [
      ...(${questions}?[action('@skill',{name:'task-workflow'},false)]:[]),
      action('schema',{root:workspace},false),
      action('init',{root:workspace,project:workspace,task_id:task,title:'Synthetic JSON report task',actor:'native-test',authorization_source:'synthetic-bootstrap-request',session_id:'native-session',integration_required:false},false),
      action('process-intent',{intent:{goal:'Add JSON output while preserving CSV.',why:'Synthetic script compatibility fixture.',success_criteria:['JSON is readable and CSV behavior remains.'],source:source('synthetic-bootstrap-request')}}),
      action('process-exploration',{exploration:{current_behavior:'The fixture README records an existing CSV command.',evidence:['README.md'],unknowns:[]}}),
      action('process-question',{question:{id:'output-choice',text:'Where should NONPROMPTED_FIRST_CANARY JSON output go?',rationale:'The destination defines the output interface.',scope:[],important:true,source:{kind:'agent',reference:'synthetic-question-1'},...(${questions}?{choices:[{id:'stdout',text:'Write to stdout',consequence:'The receiver reads stdout',source:{kind:'agent',reference:'Synthetic candidate'}},{id:'file',text:'Write a file',consequence:'The receiver reads the file',source:{kind:'agent',reference:'Synthetic candidate'}}]}:{})}}),
      ...(${questions}?[action('@ask',{questions:[{id:'output-choice',question:'Where should NONPROMPTED_FIRST_CANARY JSON output go?',header:'Question',options:[{label:'stdout: Write to stdout',description:'The receiver reads stdout'},{label:'file: Write a file',description:'The receiver reads the file'}]}]},false)]:[]),
    ];
    if(stage==='ASKPENDING'||stage==='ASKCUSTOM') {
      questionMode=stage==='ASKPENDING'?'pending':'custom';
      return [action('@ask',{questions:[{id:'output-choice',question:'Where should NONPROMPTED_FIRST_CANARY JSON output go?',options:[{label:'stdout: Write to stdout'},{label:'file: Write a file'}]}]},false)];
    }
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
        const raw=resultMessage.content.filter(block=>block.type==='text').map(block=>block.text).join('\\n');
        const value=this.operation==='@skill'?{loaded:raw.includes('Task Workflow')}:JSON.parse(raw);
        receipt({kind:'actual-tool-result',callId:this.pending,op:this.operation,result:value});
        if(!['@ask','@skill'].includes(this.operation)&&value.ok!==true) throw new Error('Workflow rejected fixture operation: '+JSON.stringify(value));
        if(this.operation==='@ask'&&value.answers?.[0]?.custom) this.queue.push(action('process-answer',{question_id:value.answers[0].id,answer:value.answers[0].custom,source:source('Synthetic native answerer tool call '+this.pending)}));
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
        yield {type:'block-end',index:0,block:{type:'tool-call',id:this.pending,name:next.op==='@ask'?'ask_user_question':next.op==='@skill'?'skill':'mcp__task-workflow__'+next.op,arguments:JSON.stringify(args)}};
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
    if (${questions} && agent.id==='native-session') await probeLineage();
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
  async function probeLineage() {
    const options={provider:'workflow-test-stub',model:'stub'};
    const first=await ctx.agents.create({sessionId:'lineage-root',meta:{cwd:workspace,parentSession:'historical-parent'},agentOptions:options});
    first.agent.followup(createUserMessage({source:{kind:'user'},content:[{type:'text',text:'TW_TEST_ISOLATE: Synthetic persisted lineage anchor.'}]}));
    await first.agent.whenIdle();
    await first.dispose();
    const resumed=await ctx.agents.resume({resumeSessionId:'lineage-root',agentOptions:options});
    let child;
    try {
      const args={questions:[{id:'lineage-probe',question:'Synthetic current-root eligibility probe.'}]};
      const execute=agent=>ctx.tools.get('ask_user_question',agent).execute(args,{agent,signal:new AbortController().signal,callId:'lineage-probe-call'});
      const answer=await execute(resumed.agent);
      receipt({kind:'resumed-root-question',historicalParent:resumed.agent.session.header.parentSession,currentRoot:ctx.agents.roots().includes(resumed.agent),answer});
      child=await ctx.agents.create({sessionId:'live-owned-child',parentAgent:resumed.agent,meta:{cwd:workspace,parentSession:'lineage-root'},agentOptions:options});
      try { await execute(child.agent); throw new Error('Owned child unexpectedly asked the user'); }
      catch(error) { if(error.code!=='DELEGATED_CALLER') throw error; receipt({kind:'owned-question-rejected',code:error.code}); }
    } finally { if(child)await child.dispose(); await resumed.dispose(); }
  }
}
`;
}

async function makeFixture(cli, t, { owned = false, questions = false, recovery = false } = {}) {
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
  await execute(cli, ['plugin', '--profile', 'workflow-test', 'add', '--save-exact', archive, '@deepseek-ai/dsh-hooks-codex@0.2.1-rc.3', '@deepseek-ai/dsh-hook-protocol@0.2.1-rc.3', ...(recovery ? ['@deepseek-ai/dsh-llm-deepseek@0.2.1-rc.3'] : []), ...(questions ? ['@deepseek-ai/dsh-user-questions@0.2.1-rc.3', '@deepseek-ai/dsh-tool-ask-user@0.2.1-rc.3', '@deepseek-ai/dsh-tool-skill@0.2.1-rc.3'] : [])], { cwd: workspace, env, receipt: path.join(run, 'install.json') });
  const installed = path.join(profile, 'node_modules/@local/task-workflow');
  assert.equal(json(path.join(installed, 'package.json')).version, json(path.join(ROOT, 'package.json')).version);
  assert.ok(json(path.join(profile, 'package.json')).dsh.profile.bundles.includes('@local/task-workflow'));
  const probe = path.join(profile, 'node_modules/@local/workflow-test-probe');
  fs.mkdirSync(probe, { recursive: true });
  writeJson(path.join(probe, 'package.json'), { name: '@local/workflow-test-probe', private: true, type: 'module', main: 'index.js', peerDependencies: { '@deepseek-ai/dsh-llm': '0.2.1-rc.3' } });
  fs.writeFileSync(path.join(probe, 'index.js'), recovery ? recoveryProbeSource() : owned ? ownedProbeSource() : probeSource(questions));
  if (owned || recovery) {
    const manifest = json(path.join(profile, 'package.json'));
    manifest.dsh.profile.bundles = manifest.dsh.profile.bundles.filter(name => name !== '@local/task-workflow');
    writeJson(path.join(profile, 'package.json'), manifest);
    env.TW_OWNED_ROOT = run;
    env.TW_OWNED_ENTRY = pathToFileURL(path.join(installed, 'adapters/deepseek/index.js')).href;
  }
  fs.writeFileSync(path.join(profile, 'cordis.patch.yml'), `# Private exploration/test composition; no Desktop or auth state.\n- insert:\n    - id: native-test-shell\n      name: '@deepseek-ai/dsh-bash-local'\n    - id: native-test-skills\n      name: '@deepseek-ai/dsh-skill'\n${questions ? "    - id: native-test-questions\n      name: '@deepseek-ai/dsh-user-questions'\n    - id: native-test-skill-tool\n      name: '@deepseek-ai/dsh-tool-skill'\n    - id: native-test-ask\n      name: '@deepseek-ai/dsh-tool-ask-user'\n      config:\n        mode: timed\n" : ''}${owned ? "    - id: native-test-subagents\n      name: '@deepseek-ai/dsh-subagent'\n" : ''}    - id: native-test-probe\n      name: '@local/workflow-test-probe'\n${owned ? "    - id: unchanged-native-delegate\n      name: '@deepseek-ai/dsh-tool-subagent'\n      config:\n        provider: spawn\n        toolName: subagent\n" : ''}`);
  writeJson(path.join(run, 'fixture.json'), { cli, run, workspace, other, profile, installed, archive, archiveSha256: createHash('sha256').update(fs.readFileSync(archive)).digest('hex'), provider: 'workflow-test-stub', model: 'stub', realProvider: false });
  return { cli, run, workspace, other, profile, installed, archive, env };
}

function recoveryProbeSource() {
  return `// Real Messages transport and parser against an isolated loopback SSE server.
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as http from 'node:http';
import {DeepSeekAdapter,resolveAdapterOptions} from '@deepseek-ai/dsh-llm-deepseek';
const mode=process.env.TW_RECOVERY_MODE;
const root=process.env.TW_OWNED_ROOT;
const log=path.join(root,'recovery-'+mode+'.jsonl');
const receipt=value=>fs.appendFileSync(log,JSON.stringify(value)+'\\n');
export const inject=['llm','agents'];
export async function apply(ctx) {
 const Native=await import(process.env.TW_OWNED_ENTRY);
 let native,requests=0;
 const workspace=process.cwd(),task='recovery-'+mode;
 const state=()=>JSON.parse(fs.readFileSync(path.join(workspace,'.task-workflow/tasks',task,'state.json'),'utf8'));
 const server=http.createServer(async(request,response)=>{
  let body='';for await(const part of request)body+=part;
  requests++;receipt({kind:'http-request',number:requests,method:request.method,url:request.url,recoveryHint:body.includes('The native provider rejected the previous workflow response')});
  response.writeHead(200,{'content-type':'text/event-stream'});
  const event=(type,data)=>response.write('event: '+type+'\\ndata: '+JSON.stringify({type,...data})+'\\n\\n');
  event('message_start',{message:{id:'synthetic-'+mode+'-'+requests,model:'deepseek-flash',role:'assistant',content:[],usage:{input_tokens:1,output_tokens:0}}});
  const valid=mode==='valid'||mode==='always';
  if(valid&&requests===7){
   event('content_block_start',{index:0,content_block:{type:'text',text:''}});
   event('content_block_delta',{index:0,delta:{type:'text_delta',text:'Synthetic recovery completed.'}});
   event('content_block_stop',{index:0});
   event('message_delta',{delta:{stop_reason:'end_turn'},usage:{output_tokens:1}});
  }else{
   const current=state();
   const operation=valid&&requests===1?'process-exploration':'process-question';
   const envelope={root:workspace,task_id:task,actor:'native-test',expected_version:current.version};
   if(operation==='process-exploration')envelope.exploration={current_behavior:'Prior successful SSE operation.',evidence:['Synthetic loopback provider'],unknowns:[]};
   else envelope.question={id:'raw-sse-choice',text:'Which synthetic output is required?',rationale:'Exercise native malformed response recovery.',scope:[],important:true,source:{kind:'agent',reference:'Synthetic raw SSE fixture'}};
   const malformed=!valid||(requests>=2&&requests<=5);
   const raw=malformed?JSON.stringify(envelope.question)+', "root": '+JSON.stringify(workspace)+'}':JSON.stringify(envelope);
   event('content_block_start',{index:0,content_block:{type:'tool_use',id:'sse-'+mode+'-'+requests,name:'mcp__task-workflow__'+operation,input:{}}});
   const middle=Math.floor(raw.length/2);
   for(const partial_json of [raw.slice(0,middle),raw.slice(middle)])event('content_block_delta',{index:0,delta:{type:'input_json_delta',partial_json}});
   event('content_block_stop',{index:0});
   event('message_delta',{delta:{stop_reason:'tool_use'},usage:{output_tokens:1}});
  }
  event('message_stop',{});response.end();
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 ctx.effect(()=>()=>new Promise(resolve=>{server.close(resolve);server.closeAllConnections();}));
 const policy=mode==='always'?{mode:'always',backoff:{initialDelayMs:1,maxDelayMs:1,jitterRatio:0}}:mode==='valid'?{mode:'normal',maxRetries:1,retryableCodes:['MALFORMED_RESPONSE'],backoff:{initialDelayMs:1,maxDelayMs:1,jitterRatio:0}}:
  {mode:'normal',maxRetries:0,retryableCodes:['TRANSPORT'],backoff:{initialDelayMs:5000,maxDelayMs:5000,jitterRatio:0}};
 const options=resolveAdapterOptions({baseURL:'http://127.0.0.1:'+server.address().port,retryPolicy:policy});
 ctx.llm.registerAdapter(['workflow-recovery-sse'],new DeepSeekAdapter({options:()=>options,resolveAuth:async()=>({headers:{}}),resolveUserId:()=> 'synthetic-loopback-test',prepareExtensions:async()=>({fields:{},accept:async()=>{}})}));
 native=ctx.plugin(Native);await native;
 if(native.state!==2)throw new Error('Native recovery candidate is not active');
 ctx.on('session/event',(session,event)=>{
  if(session.header.id!==task)return;
  if(['assistant/attempt','assistant/message','tool/call','tool/result','llm/retry','llm/retry-started','turn/end'].includes(event.type))receipt({kind:'event',seq:event.seq,type:event.type,data:event.data});
  if(event.type==='llm/retry'&&mode==='cancel')ctx.agents.get(session.header.id).cancel({kind:'user'});
  if(event.type==='llm/retry'&&mode==='unload')Promise.resolve().then(async()=>{
   await native.dispose();await native.await();
   receipt({kind:'native-unloaded',state:native.state});
   fs.writeFileSync(path.join(root,'recovery-unloaded'),'done');
  });
 });
 ctx.on('agent/pre-step',({agent,messages},next)=>{receipt({kind:'pre-step',session:agent.id,sources:messages.map(message=>message.source)});return next();});
 ctx.on('agent/assistant-stream',({agent,frame})=>{if(frame.type==='start')receipt({kind:'attempt-start',session:agent.id,turn:frame.turn,step:frame.step});});
}
`;
}

function ownedProbeSource() {
  return `// Synthetic provider and fault barriers; tools and managed Agents are native.
import * as fs from 'node:fs';
import * as path from 'node:path';
import { LlmAdapter } from '@deepseek-ai/dsh-llm';
const root=process.env.TW_OWNED_ROOT;
const receipt=value=>fs.appendFileSync(path.join(root,'owned.jsonl'),JSON.stringify(value)+'\\n');
const marker=(name,value={})=>fs.writeFileSync(path.join(root,name),JSON.stringify(value));
const waitFile=name=>fs.existsSync(path.join(root,name))?Promise.resolve():new Promise(resolve=>{
 const watcher=fs.watch(root,()=>{if(fs.existsSync(path.join(root,name))){watcher.close();resolve();}});
 if(fs.existsSync(path.join(root,name))){watcher.close();resolve();}
});
export const inject=['llm','subagents','tools','agents'];
export async function apply(ctx) {
 const Native=await import(process.env.TW_OWNED_ENTRY);
 const modes=new Map(), parents=new Map();
 ctx.subagents.registerProvider({name:'spawn',inheritsParentContext:false,
  capabilities:{agentOptions:true,agentPreset:true,outputSchema:true,depthLimit:true},
  async prepareContinuable(request){
   modes.set(request.sessionId,request.parent.id);
   receipt({kind:'native-prepare',child:request.sessionId,parent:request.parent.id});
   if(request.parent.id==='startup-parent'){
    marker('startup-entered');
    await new Promise((resolve,reject)=>{
     if(request.signal.aborted){reject(request.signal.reason);return;}
     request.signal.addEventListener('abort',()=>{marker('startup-aborted');reject(request.signal.reason);},{once:true});
    });
   }
   return {};
  }});
 let native;
 const lifetime=ctx.plugin({name:'private-native-owner',apply(parent){native=parent.plugin(Native);}});
 await lifetime;await native;
 if(native.state!==2)throw new Error('Tested native composition is not active');
 let stale=ctx.tools.register({name:'wait_agent',description:'Private removable catalog canary',parameters:{type:'object',properties:{},additionalProperties:false},
  output:{schema:{type:'object',additionalProperties:false},render:()=>[]},execute:()=>({})});
 ctx.on('tools/post-execute',async(exec,result,next)=>{const decision=await next();
  if(exec.name==='task_workflow_delegate'&&stale){stale();stale=undefined;}
  receipt({kind:'native-tool-settlement',parent:exec.agent?.id,name:exec.name,isError:result.isError});return decision;
 });
 ctx.on('agent/created',({agent})=>{
  receipt({kind:'agent-created',id:agent.id,parent:agent.session.header.parentSession,provider:agent.options.provider,model:agent.options.model});
  if(agent.session.header.origin!=='subagent'){parents.set(agent.id,agent);return;}
  if(modes.get(agent.id)==='owned-parent')agent.ctx.effect(()=>async()=>{
   receipt({kind:'owned-cleanup-start',child:agent.id});marker('cleanup-started');
   await waitFile('release-cleanup');receipt({kind:'owned-cleanup-end',child:agent.id});
  });
 });
 ctx.on('subagent/start',value=>receipt({kind:'activation-start',...value}));
 ctx.on('subagent/end',value=>receipt({kind:'activation-end',...value}));
 ctx.on('session/event',(session,event)=>{
  if(event.type==='hook/invoked')receipt({kind:'hook',session:session.header.id,point:event.data.point});
  if(event.type==='user/message')receipt({kind:'input',session:session.header.id,id:event.data.id,source:event.data.source});
 });
 class Stub extends LlmAdapter {
  states=new Map();
  async *stream(options){
   const id=options.sessionId;
   receipt({kind:'request',session:id,messages:options.messages,tools:options.tools});
   const mode=modes.get(id);
   if(mode){
    marker('child-started-'+mode,{child:id});
    if(mode==='owned-parent')await ctx.subagents.sendMessage(ctx.agents.get(id),'owned-parent',[{type:'text',text:'MEANINGFUL_EARLY_FINDING'}],{signal:options.signal});
    if(mode==='cancel-parent'||mode==='unowned-parent'){
     if(mode==='unowned-parent')await waitFile('release-unowned');
     else await new Promise((resolve,reject)=>{if(options.signal.aborted)reject(options.signal.reason);else options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true});});
    }
    yield{type:'block-start',index:0,blockType:'text'};
    yield{type:'text-delta',index:0,text:'EXACT_OWNED_REPORT_'+mode};yield{type:'finish',reason:{kind:'stop'}};return;
   }
   let state=this.states.get(id);if(!state){state={step:0};this.states.set(id,state);}
   const tool=[...options.messages].reverse().find(message=>message.role==='tool'&&message.toolCallId===state.pending);
   if(tool){
    receipt({kind:'parent-tool-result',session:id,name:state.operation,isError:tool.isError,content:tool.content});
    if(tool.isError){if(id!=='foreign-parent'&&id!=='startup-parent')throw new Error('Unexpected native tool failure: '+JSON.stringify(tool));}
    else if(state.operation==='subagent'){
     receipt({kind:'unchanged-native-render',session:id,text:tool.content.filter(block=>block.type==='text').map(block=>block.text).join('\\n')});
    }else{
     const value=JSON.parse(tool.content.filter(block=>block.type==='text').map(block=>block.text).join('\\n'));
     if(state.operation==='task_workflow_delegate'){state.handle=value.handleId;state.child=value.subagentId;marker('last-handle',{...value,parent:id});}
     if(state.operation==='task_workflow_wait'||state.operation==='task_workflow_cancel'){
      if(value.status!=='settled'||value.cleanup.status!=='complete')throw new Error('Owned collection did not prove cleanup');
      state.collected=value;receipt({kind:'collected',session:id,value});
     }
    }
    state.pending=undefined;
   }
   let name,args;
   if(state.step===0){
    if(id==='foreign-parent'){name='task_workflow_wait';args={handle_id:JSON.parse(fs.readFileSync(path.join(root,'first-handle'),'utf8')).handleId};}
    else{name=id==='unowned-parent'?'subagent':'task_workflow_delegate';args={description:'Synthetic owned check',prompt:'Return the synthetic final report using the inherited route.'};}
   }else if(state.step===1&&id!=='foreign-parent'&&id!=='startup-parent'&&id!=='unowned-parent'){
    name=id==='cancel-parent'?'task_workflow_cancel':'task_workflow_wait';args={handle_id:state.handle};
   }
   if(name){state.step++;state.operation=name;state.pending=id+'-call-'+state.step;
    yield{type:'block-start',index:0,blockType:'tool-call'};
    yield{type:'block-end',index:0,block:{type:'tool-call',id:state.pending,name,arguments:JSON.stringify(args)}};
    yield{type:'finish',reason:{kind:'tool-calls'}};return;
   }
   if(id==='owned-parent'&&!state.collected)throw new Error('Full parent answer preceded collection');
   receipt({kind:'final-answer',session:id,collected:!!state.collected});marker('final-'+id);
   yield{type:'block-start',index:0,blockType:'text'};yield{type:'text-delta',index:0,text:'FULL_FINAL_REPORT_'+id};yield{type:'finish',reason:{kind:'stop'}};
  }
 }
 ctx.llm.registerAdapter(['workflow-test-stub'],new Stub());
 let unloading=false;
 const watcher=fs.watch(root,async(_event,name)=>{
  if(name!=='unload-native'||unloading||!fs.existsSync(path.join(root,name)))return;
  unloading=true;try{await Native.disposeChild(lifetime);marker('native-unloaded');}catch(error){marker('native-unloaded',{error:String(error)});}
 });
 ctx.effect(()=>()=>watcher.close());
}
`;
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
if (CLI) test('installed recovery: real malformed Messages SSE regenerates without tool replay and honors cancellation', async t => {
  const fixture = await makeFixture(CLI, t, { recovery: true });
  await execute('python3', ['-c', `import sys
sys.path.insert(0,sys.argv[1])
import workflow
root=sys.argv[2]
for mode in ('valid','always','cancel','unload'):
 task='recovery-'+mode
 state=workflow.dispatch('init',dict(root=root,project=root,task_id=task,title='Synthetic SSE recovery',actor='native-test',authorization_source='Explicit isolated fixture',session_id=task,integration_required=False))['state']
 for operation,fields in [('process-intent',dict(intent=dict(goal='Verify native recovery',why='Synthetic transport fixture',success_criteria=['No rejected input executes'],source=dict(kind='user',reference='Synthetic fixture authorization')))),('process-exploration',dict(exploration=dict(current_behavior='Fixture inspected',evidence=['Synthetic fixture'],unknowns=[])))]:
  state=workflow.dispatch(operation,dict(root=root,task_id=task,actor='native-test',expected_version=state['version'],**fields))['state']
`, path.join(fixture.installed, 'skills/task-workflow/scripts'), fixture.workspace]);
  for (const mode of ['valid', 'always', 'cancel', 'unload']) {
    const receipts = path.join(fixture.run, 'recovery-runtime-' + mode); fs.mkdirSync(receipts);
    const sdk = new Sdk(CLI, fixture.workspace, { ...fixture.env, TW_RECOVERY_MODE: mode }, receipts);
    const taskDir = path.join(fixture.workspace, '.task-workflow/tasks/recovery-' + mode);
    const before = treeHashes(taskDir);
    try {
      await sdk.call('initialize', { cwd: fixture.workspace, provider: 'workflow-recovery-sse', model: 'deepseek-flash' });
      let outcome;
      try { await sdk.prompt('recovery-' + mode, 'Synthetic raw SSE recovery ' + mode); outcome = 'settled'; }
      catch (error) { outcome = error.message; if (mode === 'valid' || mode === 'always') throw error; }
      if (mode === 'unload') await waitFile(path.join(fixture.run, 'recovery-unloaded'), sdk);
      const observed = lines(path.join(fixture.run, 'recovery-' + mode + '.jsonl'));
      const requests = observed.filter(row => row.kind === 'http-request');
      const failed = observed.filter(row => row.kind === 'event' && row.type === 'assistant/attempt');
      const retries = observed.filter(row => row.kind === 'event' && row.type === 'llm/retry');
      if (mode === 'valid' || mode === 'always') {
        assert.equal(requests.length, 7); assert.equal(failed.length, 4); assert.equal(retries.length, 4);
        assert.equal(retries.filter(row => row.data.mode === 'normal').length, mode === 'valid' ? 1 : 0);
        assert.equal(retries.filter(row => row.data.mode === 'always').length, mode === 'valid' ? 3 : 4);
        if (mode === 'valid') assert.ok(requests.some(row => row.recoveryHint), 'The model receives a scoped regeneration hint');
        assert.ok(failed.every(row => row.data.stream.some(record => record.type === 'chunk' && record.chunk.type === 'finish' && record.chunk.reason.failure?.message === INVALID_TOOL_JSON)));
        const calls = observed.filter(row => row.kind === 'event' && row.type === 'tool/call');
        assert.equal(calls.length, 2, 'Only the prior successful operation and new valid question execute');
        assert.equal(calls.filter(row => row.data.name === 'mcp__task-workflow__process-exploration').length, 1);
        assert.equal(calls.filter(row => row.data.name === 'mcp__task-workflow__process-question').length, 1);
        assert.equal(json(path.join(taskDir, 'state.json')).process.questions[0].id, 'raw-sse-choice');
        assert.equal(observed.filter(row => row.kind === 'pre-step' && row.sources.some(source => source.kind === 'user')).length, 1, 'Regeneration adds no human prompt');
      } else {
        assert.equal(requests.length, 1); assert.equal(failed.length, 1); assert.equal(retries.length, 1);
        assert.deepEqual(treeHashes(taskDir), before);
        assert.ok(!observed.some(row => row.kind === 'event' && row.type === 'tool/call'));
        if (mode === 'unload') assert.ok(observed.some(row => row.kind === 'native-unloaded' && row.state === 4));
      }
      writeJson(path.join(fixture.run, 'recovery-result-' + mode + '.json'), { passed: true, mode, requests: requests.length, malformedAttempts: failed.length, retries: retries.length, outcome, realProvider: false, realParser: true });
      await sdk.close();
    } finally { if (sdk.child.exitCode === null) await sdk.close(); }
  }
});
if (CLI) test('installed owned protocol: native handles cleanup source and final-answer ordering', async t => {
  const fixture = await makeFixture(CLI, t, { owned: true });
  const receipts = path.join(fixture.run, 'owned-runtime'); fs.mkdirSync(receipts);
  const sdk = new Sdk(CLI, fixture.workspace, fixture.env, receipts);
  try {
    await sdk.call('initialize', { cwd: fixture.workspace, provider: 'workflow-test-stub', model: 'stub' });
    await sdk.call('session/prompt', { sessionId: 'owned-parent', contentBlocks: [{ type: 'text', text: 'Synthetic owned completion check.' }] });
    await waitFile(path.join(fixture.run, 'cleanup-started'), sdk);
    let observed = lines(path.join(fixture.run, 'owned.jsonl'));
    assert.ok(!observed.some(item => item.kind === 'final-answer' && item.session === 'owned-parent'));
    const handle = json(path.join(fixture.run, 'last-handle'));
    fs.copyFileSync(path.join(fixture.run, 'last-handle'), path.join(fixture.run, 'first-handle'));
    assert.equal(typeof handle.handleId, 'string'); assert.equal(handle.parent, 'owned-parent');
    const parentRequests = observed.filter(item => item.kind === 'request' && item.session === 'owned-parent');
    assert.equal(parentRequests.length, 2, 'The parent is waiting, not answering during child cleanup');
    assert.ok(parentRequests[0].messages.filter(message => message.role === 'system').some(message => message.content.some(block => block.text?.includes(WORKFLOW_SCOPE))), 'The actual owned tool section preserves ordinary/status scope');
    const capability = request => [...request.messages].reverse().flatMap(message => message.source?.kind === 'runtime-context' ? message.source.sections ?? [] : []).find(section => section.name === 'task-workflow:capabilities')?.text;
    assert.ok(capability(parentRequests[0]).includes('wait_agent'));
    assert.ok(!capability(parentRequests[1]).includes('wait_agent'));
    assert.equal(parentRequests[1].tools.filter(tool => tool.name.startsWith('mcp__task-workflow__')).length, 54);
    const ownedSchema = parentRequests[1].tools.find(tool => tool.name === 'task_workflow_delegate');
    const nativeSchema = parentRequests[1].tools.find(tool => tool.name === 'subagent');
    assert.deepEqual(ownedSchema.parameters, nativeSchema.parameters, 'Native parameter policy is retained');
    fs.writeFileSync(path.join(fixture.run, 'release-cleanup'), 'release owned cleanup');
    await sdk.call('session/wait', { sessionId: 'owned-parent' });
    observed = lines(path.join(fixture.run, 'owned.jsonl'));
    const cleanup = observed.findIndex(item => item.kind === 'owned-cleanup-end');
    const collected = observed.findIndex(item => item.kind === 'collected' && item.session === 'owned-parent');
    const final = observed.findIndex(item => item.kind === 'final-answer' && item.session === 'owned-parent');
    assert.ok(cleanup >= 0 && cleanup < collected && collected < final);
    assert.ok(observed.filter(item => item.kind === 'request' && item.session === 'owned-parent').some(request => request.messages.some(message => message.source?.kind === 'agent-message' && message.content.some(block => block.text?.includes('MEANINGFUL_EARLY_FINDING')))), 'A deliberate worker report remains in a subsequent parent request');
    assert.equal(observed.filter(item => item.kind === 'request' && item.session === 'owned-parent').length, 3);
    assert.ok(!observed.some(item => item.kind === 'input' && item.session === 'owned-parent' && item.source?.kind === 'subagent-settled'));
    const child = observed.find(item => item.kind === 'agent-created' && item.parent === 'owned-parent');
    assert.equal(child.provider, 'workflow-test-stub'); assert.equal(child.model, 'stub');
    assert.ok(!observed.some(item => item.kind === 'hook' && item.session === child.id && item.point === 'UserPromptSubmit'), 'Owned delegated initial input is not a new human prompt');
    assert.ok(observed.some(item => item.kind === 'hook' && item.session === 'owned-parent' && item.point === 'UserPromptSubmit'));
    assert.equal(observed.filter(item => item.kind === 'hook' && item.session === 'owned-parent' && item.point === 'UserPromptSubmit').length, 1, 'The worker report does not become another human prompt hook');
    await sdk.prompt('foreign-parent', 'Synthetic foreign handle rejection check.');
    observed = lines(path.join(fixture.run, 'owned.jsonl'));
    assert.ok(observed.some(item => item.kind === 'parent-tool-result' && item.session === 'foreign-parent' && item.isError));
    await sdk.call('session/prompt', { sessionId: 'unowned-parent', contentBlocks: [{ type: 'text', text: 'Synthetic independent native activation.' }] });
    await waitFile(path.join(fixture.run, 'child-started-unowned-parent'), sdk);
    await waitFile(path.join(fixture.run, 'final-unowned-parent'), sdk);
    await sdk.prompt('cancel-parent', 'Synthetic owned cancellation check.');
    observed = lines(path.join(fixture.run, 'owned.jsonl'));
    const canceled = observed.find(item => item.kind === 'collected' && item.session === 'cancel-parent');
    assert.equal(canceled.value.result.stopReason, 'aborted'); assert.equal(canceled.value.cleanup.status, 'complete');
    const unrelated = json(path.join(fixture.run, 'child-started-unowned-parent')).child;
    assert.ok(!observed.some(item => item.kind === 'activation-end' && item.id === unrelated));
    await sdk.call('session/prompt', { sessionId: 'startup-parent', contentBlocks: [{ type: 'text', text: 'Synthetic disposal during unpublished native startup.' }] });
    await waitFile(path.join(fixture.run, 'startup-entered'), sdk);
    fs.writeFileSync(path.join(fixture.run, 'unload-native'), 'dispose only the tested native plugin');
    await waitFile(path.join(fixture.run, 'native-unloaded'), sdk);
    assert.deepEqual(json(path.join(fixture.run, 'native-unloaded')), {});
    assert.ok(fs.existsSync(path.join(fixture.run, 'startup-aborted')));
    observed = lines(path.join(fixture.run, 'owned.jsonl'));
    assert.ok(!observed.some(item => item.kind === 'activation-end' && item.id === unrelated));
    fs.writeFileSync(path.join(fixture.run, 'release-unowned'), 'allow independent native work to finish');
    await sdk.call('session/wait', { sessionId: 'unowned-parent' });
    await sdk.close();
    observed = lines(path.join(fixture.run, 'owned.jsonl'));
    assert.ok(observed.some(item => item.kind === 'activation-end' && item.id === unrelated && item.stopReason === 'completed'));
    writeJson(path.join(fixture.run, 'owned-result.json'), { passed: true, coreOperations: 54, cleanupBeforeCollectionBeforeFinal: true, automaticOwnedSettlementMessages: 0, nativePoliciesPreserved: true, foreignHandleRejected: true, startupAborted: true, unownedActivationPreserved: true });
  } finally {
    for (const marker of ['release-cleanup', 'release-unowned']) fs.writeFileSync(path.join(fixture.run, marker), 'owned test cleanup');
    if (sdk.child.exitCode === null) await sdk.close();
  }
});
if (CLI) test('installed questions: canonical stage text, recorded native card and actual answer states', async t => {
  const fixture = await makeFixture(CLI, t, { questions: true });
  const receipts = path.join(fixture.run, 'question-runtime'); fs.mkdirSync(receipts);
  const sdk = new Sdk(CLI, fixture.workspace, fixture.env, receipts);
  try {
    await sdk.call('initialize', { cwd: fixture.workspace, provider: 'workflow-test-stub', model: 'stub' });
    await sdk.prompt('native-session', 'TW_TEST_BOOTSTRAP: Synthetic question transport.');
    let observed = lines(path.join(fixture.run, 'probe.jsonl'));
    const resumedRoot = observed.find(row => row.kind === 'resumed-root-question');
    assert.equal(resumedRoot.historicalParent, 'historical-parent'); assert.equal(resumedRoot.currentRoot, true);
    assert.ok(observed.some(row => row.kind === 'owned-question-rejected' && row.code === 'DELEGATED_CALLER'));
    const recorded = observed.findIndex(row => row.kind === 'actual-tool-result' && row.op === 'process-question');
    const card = observed.findIndex(row => row.kind === 'synthetic-question-request' && row.questions[0].id === 'output-choice');
    assert.ok(recorded >= 0 && card > recorded);
    assert.equal(observed[card].currentRoot, true);
    const beforeAsk = observed.slice(0, card).filter(row => row.kind === 'model-request').at(-1);
    const context = currentRuntimeContext(beforeAsk);
    const nativeCapabilities = beforeAsk.messages.filter(message => message.source?.kind === 'runtime-context')
      .flatMap(message => message.source.sections ?? []).filter(section => section.name === 'task-workflow:capabilities').at(-1);
    const capabilities = JSON.parse(nativeCapabilities.text.slice('Current native Task Workflow capabilities: '.length));
    const actualSkill = beforeAsk.tools.find(tool => tool.name === 'skill');
    assert.ok(actualSkill); assert.deepEqual(capabilities.skill_loader.parameters, actualSkill.parameters);
    assert.deepEqual(capabilities.skill_loader.arguments, { name: 'task-workflow' });
    assert.equal(capabilities.applicability, WORKFLOW_SCOPE);
    assert.ok(observed.some(row => row.kind === 'actual-tool-result' && row.op === '@skill' && row.result.loaded));
    assert.equal(context.stage_guidance.mode, 'first_reply');
    assert.ok(context.stage_guidance.conversation_template.includes('## First discussion reply'));
    assert.ok(!context.stage_guidance.conversation_template.includes('## Plan and approval'));
    assert.ok(context.stage_guidance.title_language_rule.includes('current conversation language'));
    const example = context.stage_guidance.recording_example.arguments;
    assert.equal(example.root, fixture.workspace); assert.equal(example.task_id, 'native-task');
    assert.equal(example.expected_version, context.dialogue_contract.state_version);
    assert.ok(example.question.choices.every(choice => choice.id && choice.source));
    const pending = context.dialogue_contract.pending_questions[0];
    assert.equal(observed[card].questions[0].id, pending.id);
    assert.deepEqual(observed[card].questions[0].options.map(option => option.label.split(':')[0]), pending.choices.map(choice => choice.id));
    const taskDir = path.join(fixture.workspace, '.task-workflow/tasks/native-task');
    const skippedState = json(path.join(taskDir, 'state.json'));
    assert.equal(skippedState.process.questions[0].status, 'pending');
    const before = treeHashes(taskDir);
    await sdk.prompt('native-session', 'TW_TEST_ASKPENDING: Synthetic pending native answer.');
    assert.deepEqual(treeHashes(taskDir), before);
    observed = lines(path.join(fixture.run, 'probe.jsonl'));
    assert.ok(observed.some(row => row.kind === 'actual-tool-result' && row.op === '@ask' && row.result.pending === true));
    await sdk.prompt('native-session', 'TW_TEST_ASKCUSTOM: Synthetic custom answer overrides selected.');
    observed = lines(path.join(fixture.run, 'probe.jsonl'));
    const custom = observed.find(row => row.kind === 'actual-tool-result' && row.op === '@ask' && row.result.answers?.[0]?.custom);
    assert.equal(custom.result.answers[0].selected[0], 'stdout: Write to stdout');
    const answer = json(path.join(taskDir, 'state.json')).process.questions[0].answer;
    assert.equal(answer.text, custom.result.answers[0].custom);
    assert.equal(answer.choice_id, undefined);
    assert.ok(answer.source.reference.includes(custom.callId));
    assert.equal(requireCurrentContext(observed, json(path.join(taskDir, 'state.json')).version).stage_guidance.mode, 'answer_acknowledgment');
    writeJson(path.join(fixture.run, 'question-result.json'), { passed: true, scriptedProviderOnly: true, recordedBeforeActualCard: true, skippedAndPendingPreserveWait: true, customRawSourcePreserved: true, completeCanonicalExampleDelivered: true });
    await sdk.close();
  } finally { if (sdk.child.exitCode === null) await sdk.close(); }
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
    assert.equal(actualSchema.length, 54); assert.equal(advertised.length, actualSchema.length);
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
    const final = { result: 'passed', source: 'installed runtime with scripted LLM only', schemas: 54, stateVersion: finalState.version, taskUnchangedAfterStatus: true, actualToolCalls: status.receipts.filter(item => item.kind === 'actual-tool-result').length };
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
