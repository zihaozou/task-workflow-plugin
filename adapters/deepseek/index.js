/** Native composition; the Python workflow remains the authority for state. */
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

export const name = 'task-workflow';
export const inject = ['shell', 'sessionProjections', 'workingDirectory', 'systemPrompt', 'tools', 'skills'];
export const UNAVAILABLE_NOTICE = 'Current Task Workflow context is unavailable. Inspect status before dependent work.';
export const HOOK_TRUNCATED_NOTICE = 'Task Workflow hook output was truncated by the host. Use the complete current Task Workflow runtime context.';
export const releaseRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

/** Shell arguments are literals, including installed paths with metacharacters. */
export function quoteShellArgument(value, platform = process.platform) {
  if (typeof value !== 'string' || !value || value.includes('\0')) throw new Error('Invalid command path.');
  return platform === 'win32' ? `'${value.replaceAll("'", "''")}'` : `'${value.replaceAll("'", "'\\''")}'`;
}

/** Numeric output descriptors avoid Node's default buffered-output ceiling. */
export function runProcessSync(command, args, options = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'task-workflow-read-'));
  const stdoutPath = path.join(directory, 'stdout');
  const stderrPath = path.join(directory, 'stderr');
  let stdoutFd, stderrFd;
  try {
    stdoutFd = fs.openSync(stdoutPath, 'wx', 0o600);
    stderrFd = fs.openSync(stderrPath, 'wx', 0o600);
    const result = (options.spawn || spawnSync)(command, args, {
      input: options.input ?? '', env: options.env, cwd: options.cwd,
      stdio: ['pipe', stdoutFd, stderrFd],
    });
    return { status: result.status, signal: result.signal, error: result.error,
      stdout: fs.readFileSync(stdoutPath, 'utf8'), stderr: fs.readFileSync(stderrPath, 'utf8') };
  } finally {
    if (stdoutFd !== undefined) fs.closeSync(stdoutFd);
    if (stderrFd !== undefined) fs.closeSync(stderrFd);
    fs.rmSync(directory, { recursive: true, force: true });
  }
}

export function readContextSync(request, runtime) {
  try {
    const result = (runtime.run || runProcessSync)(runtime.python, [runtime.helper], {
      input: JSON.stringify(request), env: runtime.environment(),
    });
    if (result.error || result.signal || result.status !== 0) return UNAVAILABLE_NOTICE;
    const envelope = JSON.parse(result.stdout);
    if (envelope.ok !== true || !Object.hasOwn(envelope, 'context')) return UNAVAILABLE_NOTICE;
    if (envelope.context === null) return '';
    const context = envelope.context;
    if (!context || typeof context !== 'object' || Array.isArray(context)
        || context.session_id !== request.session_id || context.task?.session_id !== request.session_id
        || typeof context.task?.task_id !== 'string' || !context.dialogue_contract
        || typeof context.dialogue_contract !== 'object' || Array.isArray(context.dialogue_contract)) return UNAVAILABLE_NOTICE;
    return 'Registered Task Workflow context: ' + JSON.stringify(context);
  } catch {
    return UNAVAILABLE_NOTICE;
  }
}

export function resolvedHookConfig(root, python, platform = process.platform) {
  const original = JSON.parse(fs.readFileSync(path.join(root, 'hooks/hooks.json'), 'utf8'));
  const hooks = {};
  for (const [event, script] of Object.entries({ SessionStart: 'session_hook.py', UserPromptSubmit: 'communication_prompt_hook.py' })) {
    const expected = `python3 "\${PLUGIN_ROOT}/skills/task-workflow/scripts/${script}"`;
    if (!Array.isArray(original.hooks?.[event]) || original.hooks[event].length === 0) throw new Error('Missing workflow hook registration.');
    hooks[event] = original.hooks[event].map(group => ({ ...group, hooks: group.hooks.map(handler => {
      if (handler.type !== 'command' || handler.async === true || handler.command !== expected) throw new Error('Unsupported workflow hook registration.');
      const command = [python, path.join(root, 'skills/task-workflow/scripts', script)].map(value => quoteShellArgument(value, platform)).join(' ');
      return { ...handler, command: (platform === 'win32' ? '& ' : '') + command };
    }) }));
  }
  return { description: original.description, hooks };
}

/** Keep host-truncated hook output out of the official plain-text fallback. */
export function hookTransportShell(shell) {
  const methods = new Map();
  const execute = async (...args) => {
    const handle = await shell.execute(...args);
    const bound = new Map();
    let resultPromise;
    const result = () => {
      resultPromise ??= handle.result().then(value => value.stdout?.truncated === true
        ? { ...value, stdout: { ...value.stdout, text: HOOK_TRUNCATED_NOTICE } } : value);
      return resultPromise;
    };
    return new Proxy(handle, { get(target, property) {
      if (property === 'result') return result;
      const value = Reflect.get(target, property, target);
      if (typeof value !== 'function') return value;
      if (!bound.has(property)) bound.set(property, value.bind(target));
      return bound.get(property);
    } });
  };
  return new Proxy(shell, { get(target, property) {
    if (property === 'execute') return execute;
    const value = Reflect.get(target, property, target);
    if (typeof value !== 'function') return value;
    if (!methods.has(property)) methods.set(property, value.bind(target));
    return methods.get(property);
  } });
}

/** Track only the callbacks belonging to this official bridge instance. */
export function hookOwnership() {
  const abort = new AbortController();
  const pending = new Set(), listeners = [];
  const originals = new WeakMap();
  let closed = false, closing;
  return {
    on(ctx, event, listener, options) {
      const wrapper = function (...args) {
        const receiver = this;
        const originalNext = typeof args[1] === 'function' ? args[1] : undefined;
        if (closed) return originalNext?.();
        let downstream, calledNext = false;
        if (originalNext) args[1] = async function (...values) {
          calledNext = true;
          downstream = await originalNext.apply(this, values);
          return downstream;
        };
        if (event === 'agent/created' || event === 'agent/pre-step') {
          const original = args[0];
          const signals = [abort.signal, original.signal].filter(Boolean);
          args[0] = { ...original, signal: AbortSignal.any(signals) };
          if (event === 'agent/created') {
            // The facade forwards public access/methods to the exact native
            // agent; only this bridge's non-waking context injection is gated.
            args[0].agent = new Proxy(original.agent, { get(target, property) {
              if (property === 'inject') return (...values) => closed ? undefined : target.inject(...values);
              const value = Reflect.get(target, property, target);
              return typeof value === 'function' ? value.bind(target) : value;
            } });
            originals.set(args[0].agent, original.agent);
          }
        }
        const task = Promise.resolve().then(async () => {
          if (closed) return originalNext?.();
          const result = await listener.apply(receiver, args);
          // Unloading cannot append this bridge's late prompt context, while
          // the already admitted user's unchanged downstream decision survives.
          if (closed && event === 'agent/pre-step' && calledNext) return downstream;
          return result;
        });
        pending.add(task);
        task.then(() => pending.delete(task), () => pending.delete(task));
        return task;
      };
      const dispose = ctx.on(event, wrapper, options);
      listeners.push(dispose);
      return dispose;
    },
    actualAgent(agent) { return originals.get(agent) || agent; },
    close() {
      if (closing) return closing;
      closed = true;
      abort.abort(new Error('Task Workflow hooks disposed.'));
      const failures = [];
      for (const dispose of listeners.splice(0)) {
        try { dispose(); } catch (error) { failures.push(error); }
      }
      closing = (async () => {
        while (pending.size) await Promise.allSettled([...pending]);
        if (failures.length) throw new Error('Task Workflow hook listener removal failed.');
      })();
      return closing;
    },
  };
}

/** Cordis's repeated dispose call need not return the first cleanup Promise. */
export async function disposeChild(child) {
  let failure;
  try { await child.dispose(); } catch (error) { failure = error; }
  try { await child.await(); } catch (error) { failure = failure || error; }
  if (child.state !== 4) throw failure || new Error('Task Workflow child did not finish disposal.');
}

/** Explicit child ownership also works when Cordis parent disposers overlap. */
export function ownedLifetime(removeFiles) {
  const children = [];
  const drains = [];
  let closed = false, cleanupTask, removeContext = () => {};
  return {
    get closed() { return closed; },
    add(child) { if (closed) throw new Error('Task Workflow is disposing.'); children.push(child); },
    context(dispose) { removeContext = dispose; },
    drain(dispose) { drains.push(dispose); },
    cleanup() {
      if (cleanupTask) return cleanupTask;
      closed = true;
      cleanupTask = (async () => {
        let contextError;
        try { removeContext(); } catch (error) { contextError = error; }
        const drained = await Promise.allSettled(drains.map(dispose => Promise.resolve().then(dispose)));
        const settled = await Promise.allSettled(children.map(disposeChild));
        if (contextError || drained.some(result => result.status === 'rejected')) throw new Error('Task Workflow callback cleanup did not complete.');
        if (settled.some(result => result.status === 'rejected')) throw new Error('Task Workflow child cleanup did not complete.');
        removeFiles();
      })();
      return cleanupTask;
    },
  };
}

export async function mountChild(ctx, lifetime, plugin, config) {
  if (lifetime.closed) throw new Error('Task Workflow is disposing.');
  const child = ctx.plugin(plugin, config);
  lifetime.add(child);
  await child;
  if (lifetime.closed || child.state !== 2) throw new Error('Task Workflow child is not active.');
  return child;
}

export async function apply(ctx) {
  // Production dependencies resolve only during native activation. Built-in-only
  // imports keep transport/ownership tests runnable without source node_modules.
  const [HooksCodex, McpClient, SkillFilesystem, subprocess] = await Promise.all([
    import('@deepseek-ai/dsh-hooks-codex'), import('@deepseek-ai/dsh-mcp-client'),
    import('@deepseek-ai/dsh-skill-filesystem'), import('@deepseek-ai/dsh-subprocess'),
  ]);
  const environment = subprocess.scrubbedParentEnv;
  if (typeof environment !== 'function') throw new Error('The native credential scrubber is unavailable.');
  const discovered = runProcessSync('python3', ['-c', 'import sys; print(sys.executable)'], { env: environment() });
  const python = discovered.stdout.trim();
  if (discovered.error || discovered.status !== 0 || !path.isAbsolute(python)) throw new Error('Task Workflow requires an available Python interpreter.');
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'task-workflow-hooks-'));
  const configPath = path.join(directory, 'hooks.json');
  const lifetime = ownedLifetime(() => fs.rmSync(directory, { recursive: true, force: true }));
  try {
    ctx.effect(() => () => lifetime.cleanup());
    fs.writeFileSync(configPath, JSON.stringify(resolvedHookConfig(releaseRoot, python)), { mode: 0o600 });
    const hooks = hookOwnership();
    lifetime.drain(() => hooks.close());
    const ownedBridge = { name: 'task-workflow-official-hooks', Config: HooksCodex.Config, inject: HooksCodex.inject,
      apply(child, config) {
        const directoryService = child.workingDirectory;
        const workingDirectory = new Proxy(directoryService, { get(target, property) {
          if (property === 'ensure') return (agent, ...values) => target.ensure(hooks.actualAgent(agent), ...values);
          const value = Reflect.get(target, property, target);
          return typeof value === 'function' ? value.bind(target) : value;
        } });
        return HooksCodex.apply(child.extend({ on(event, listener, options) {
          return hooks.on(child, event, listener, options);
        }, workingDirectory, shell: hookTransportShell(child.shell) }), config);
      } };
    await mountChild(ctx, lifetime, ownedBridge, { configPath });
    await mountChild(ctx, lifetime, McpClient, { serverName: 'task-workflow', transport: 'stdio', command: python,
      args: [path.join(releaseRoot, 'skills/task-workflow/scripts/mcp_server.py')], cwd: releaseRoot, failOnStartupError: true });
    await mountChild(ctx, lifetime, SkillFilesystem, { providerName: 'task-workflow', includeDefaultRoots: false,
      customSkillDirs: [path.join(releaseRoot, 'skills')] });
    lifetime.context(ctx.systemPrompt.context({ name: 'task-workflow:current', order: 900, required: true, interpolate: false,
      text(context) {
        if (lifetime.closed || !context.agent) return '';
        try {
          const session = context.agent.session;
          return readContextSync({ cwd: ctx.workingDirectory.get(session), session_id: session.header.id }, {
            python, helper: path.join(releaseRoot, 'skills/task-workflow/scripts/deepseek_context.py'), environment,
          });
        } catch { return UNAVAILABLE_NOTICE; }
      } }));
  } catch (error) {
    await lifetime.cleanup();
    throw error;
  }
}
