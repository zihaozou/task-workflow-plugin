/** Native composition; the Python workflow remains the authority for state. */
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { ownedDelegations, collectionTools, delegationFacades, DELEGATE_TOOL, WAIT_TOOL, CANCEL_TOOL, OWNED_PROVIDER } from './delegation.js';
import { taskScopedRecovery } from './recovery.js';

export const name = 'task-workflow';
export const inject = ['shell', 'sessionProjections', 'workingDirectory', 'systemPrompt', 'tools', 'skills'];
export const UNAVAILABLE_NOTICE = 'Current Task Workflow context is unavailable. Inspect status before dependent work.';
export const HOOK_TRUNCATED_NOTICE = 'Task Workflow hook output was truncated by the host. Use the complete current Task Workflow runtime context.';
export const releaseRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
export const WORKFLOW_SCOPE = 'These workflow instructions apply only to authorized related Task Workflow work. Handle ordinary conversation, advice and simple requests directly. A status or progress request authorizes inspection and a direct answer, preserves the current stage/wait, and does not authorize new questions, delegation or enrollment. Tool availability and context delivery grant no authority.';

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
export function hookOwnership({ humanMessages = async (_agent, messages) => messages.filter(message => message.source?.kind === 'user') } = {}) {
  const abort = new AbortController();
  const pending = new Set(), listeners = [];
  const originals = new WeakMap();
  let closed = false, closing;
  return {
    on(ctx, event, listener, options) {
      const wrapper = function (...args) {
        const receiver = this;
        const originalNext = typeof args[1] === 'function' ? args[1] : undefined;
        if (closed) return originalNext?.call(receiver);
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
          if (closed) return originalNext?.call(receiver);
          if (event === 'agent/pre-step') {
            const messages = await humanMessages(args[0].agent, args[0].messages, args[0].signal);
            if (closed || messages.length === 0) return args[1]?.call(receiver);
            // Only this official hook sees the filtered prompt. Its downstream
            // continuation still owns the complete original message batch.
            args[0] = { ...args[0], messages };
          }
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
  const contexts = [];
  let closed = false, cleanupTask;
  return {
    get closed() { return closed; },
    add(child) { if (closed) throw new Error('Task Workflow is disposing.'); children.push(child); },
    context(dispose) { contexts.push(dispose); },
    drain(dispose) { drains.push(dispose); },
    cleanup() {
      if (cleanupTask) return cleanupTask;
      closed = true;
      cleanupTask = (async () => {
        let contextError;
        for (const removeContext of contexts.splice(0)) {
          try { removeContext(); } catch (error) { contextError = error; }
        }
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

export function capabilityContext(ctx, agent, registry) {
  try {
    const schemas = ctx.tools.schemas(agent);
    const names = schemas.map(tool => tool.name);
    const owned = [DELEGATE_TOOL, WAIT_TOOL, CANCEL_TOOL].every(name => names.includes(name));
    const questionTool = schemas.find(tool => tool.name === 'ask_user_question');
    const skillTool = schemas.find(tool => tool.name === 'skill');
    const agents = ctx.get?.('agents');
    const currentRoot = agents ? agents.roots().includes(agent) : null;
    return 'Current native Task Workflow capabilities: ' + JSON.stringify({
      tool_names: names,
      applicability: WORKFLOW_SCOPE,
      skill_loader: {
        available: Boolean(skillTool),
        ...(skillTool ? { tool_name: skillTool.name, parameters: skillTool.parameters,
          ...(skillTool.parameters?.properties?.name ? { arguments: { name: 'task-workflow' } } : {}) } : {}),
        main_skill_path: path.join(releaseRoot, 'skills/task-workflow/SKILL.md'),
        instruction: 'Before authorized workflow progress, load the current task-workflow skill through the actually available native skill tool using its current schema. If no supported loader is exposed, use an available supported file-reading tool for main_skill_path. If neither route is available, report current guidance unavailable before dependent work. A file path or a listed capability does not prove the skill was read. Do not invoke tools or enroll a task merely because this context is present.',
      },
      owned_delegation_available: owned,
      ...(owned ? { workflow_delegation: 'For authorized related workflow delegation, use task_workflow_delegate and collect its exact handleId with task_workflow_wait before reporting the final child outcome. task_workflow_cancel disposes only that owned activation. A canceled wait leaves the worker running. Native interrupt acknowledgment is not settlement. Native and unowned worker messages remain independent.' } : {}),
      owned_activations: registry?.context(agent) ?? [],
      user_question: {
        available: Boolean(questionTool), current_root: currentRoot,
        ...(questionTool ? { tool_name: questionTool.name, parameters: questionTool.parameters } : {}),
        protocol: 'When workflow work requires a user answer or approval, for discussion first record the question with process-question (or process-reenter) and wait for its successful result. For Spec/Plan approval, use the successfully recorded and reviewed exact current approval_target; do not call a discussion-only operation in an approval stage. Use the returned current pending question/digest or approval_target, then actually call ask_user_question if exposed and currently eligible; a prose question or option list does not replace that call. Present the complete current stage layout before the card. A status-only request preserves the existing wait and does not ask again. The current live root restriction is authoritative; do not infer eligibility from a historical parentSession marker. An owned child returns unresolved questions to its coordinator. If the tool is unavailable or the native service denies eligibility, report that fact and use the supported conversation/coordinator path without claiming a tool invocation.',
        identity: 'Use questions[{id,question,header?,options?:[{label,description?}],multi_select?}] with the exact recorded question id. Render headings, question meaning and choices in the current conversation language. Keep a unique exact submitted-label to recorded choice_id mapping for this call; include the choice id in each label if labels would collide. Preserve each recorded choice meaning and consequence. Omit options when no choices were recorded; do not invent choices or force a count. Follow the currently exposed parameters; do not add a wait duration unless actually requested.',
        answer_rule: 'Use only the actual native tool result linked to its callId, or an actual continued user-question-reply linked to that callId. Keep its raw selected/custom content and original source reference. Nonempty custom input takes precedence over selected labels and must not invent choice_id. Otherwise map only an exact submitted option label to its recorded choice_id. Empty, skipped, missing, aborted or pending/timed results do not confirm a choice or approval; preserve the current pending wait. Before recording a late answer, reread current context and validate the question id, question_digest and exact approval_target revision/digest against the original call; changed targets require fresh clarification. A fixture answer is test data, not human approval. Record process-answer and linked decisions before dependent progress.',
      },
      capability_rule: 'Use only the current tool names and their current schemas. Historical tool names are not current capabilities.',
    });
  } catch {
    return 'Current native tool capabilities are unavailable. Inspect the current catalog before using remembered tools.';
  }
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
  const [HooksCodex, McpClient, SkillFilesystem, subprocess, NativeDelegate, NativeRetry, llm] = await Promise.all([
    import('@deepseek-ai/dsh-hooks-codex'), import('@deepseek-ai/dsh-mcp-client'),
    import('@deepseek-ai/dsh-skill-filesystem'), import('@deepseek-ai/dsh-subprocess'),
    import('@deepseek-ai/dsh-tool-subagent'),
    import('@deepseek-ai/dsh-llm-retry'), import('@deepseek-ai/dsh-llm'),
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
    const readAgent = agent => readContextSync({ cwd: ctx.workingDirectory.get(agent.session), session_id: agent.session.header.id }, {
      python, helper: path.join(releaseRoot, 'skills/task-workflow/scripts/deepseek_context.py'), environment,
    });
    const recovery = taskScopedRecovery({ readCurrent: readAgent,
      toolSchemas: agent => ctx.tools.schemas(agent), streamChunks: llm.assistantStreamChunks });
    lifetime.drain(() => recovery.close());
    ctx.on('agent/assistant-stream', payload => recovery.observeFrame(payload));
    ctx.on('session/event', (session, event) => recovery.observeEvent(session, event));
    ctx.on('agent/disposed', ({ agent }) => recovery.disposeAgent(agent));
    const ownedRetry = { name: 'task-workflow-request-recovery', Config: NativeRetry.Config, inject: NativeRetry.inject,
      apply(child, config) { return NativeRetry.apply(child.extend({ on(event, listener, options) {
        return recovery.on(child, event, listener, options);
      } }), config); } };
    await mountChild(ctx, lifetime, ownedRetry, {});
    fs.writeFileSync(configPath, JSON.stringify(resolvedHookConfig(releaseRoot, python)), { mode: 0o600 });
    const nativeSubagents = ctx.get('subagents');
    const registry = nativeSubagents ? ownedDelegations(nativeSubagents) : undefined;
    if (registry) lifetime.drain(() => registry.close());
    const hooks = hookOwnership(registry ? { humanMessages: (...args) => registry.humanMessages(...args) } : {});
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
    if (registry) {
      const ownedNative = { name: 'task-workflow-owned-delegation', Config: NativeDelegate.Config, inject: NativeDelegate.inject,
        apply(child, config) {
          const facades = delegationFacades(child, registry);
          for (const tool of collectionTools(registry)) child.tools.register(tool);
          const systemPrompt = new Proxy(child.systemPrompt, { get(target, property) {
            if (property === 'section') return section => target.section(section.name !== `tool:${DELEGATE_TOOL}` ? section : {
              ...section, text(context) {
                const visible = typeof section.text === 'function' ? section.text(context) : section.text;
                return visible ? WORKFLOW_SCOPE + ' For authorized Task Workflow delegation, start the owned child with task_workflow_delegate. Collect its final return value and cleanup through task_workflow_wait before reporting completion. Use task_workflow_cancel only for an owned activation. Meaningful early worker questions and findings remain valid messages.' : '';
              },
            });
            const value = Reflect.get(target, property, target);
            return typeof value === 'function' ? value.bind(target) : value;
          } });
          return NativeDelegate.apply(child.extend({ ...facades, systemPrompt }), config);
        } };
      await mountChild(ctx, lifetime, ownedNative, { provider: OWNED_PROVIDER, toolName: DELEGATE_TOOL });
      ctx.on('agent/disposed', ({ agent }) => registry.disposeParent(agent));
    }
    lifetime.context(ctx.systemPrompt.context({ name: 'task-workflow:capabilities', order: 901, required: true, interpolate: false,
      text(context) { return lifetime.closed || !context.agent ? '' : capabilityContext(ctx, context.agent, registry); } }));
    lifetime.context(ctx.systemPrompt.context({ name: 'task-workflow:current', order: 900, required: true, interpolate: false,
      text(context) {
        if (lifetime.closed || !context.agent) return '';
        try {
          const value = readAgent(context.agent);
          recovery.captureContext(context.agent, value);
          return value;
        } catch { recovery.captureContext(context.agent, UNAVAILABLE_NOTICE); return UNAVAILABLE_NOTICE; }
      } }));
    lifetime.context(ctx.systemPrompt.context({ name: 'task-workflow:request-recovery', order: 902, required: true, interpolate: false,
      text(context) { return lifetime.closed || !context.agent ? '' : recovery.context(context.agent); } }));
  } catch (error) {
    await lifetime.cleanup();
    throw error;
  }
}
