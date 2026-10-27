/** Narrow regeneration of failed native workflow requests; no tool-input repair. */
export const INVALID_TOOL_JSON = 'DeepSeek Messages stream: tool input is invalid JSON';
export const CONTEXT_PREFIX = 'Registered Task Workflow context: ';

function binding(text) {
  if (typeof text !== 'string' || !text.startsWith(CONTEXT_PREFIX)) return null;
  try {
    const value = JSON.parse(text.slice(CONTEXT_PREFIX.length));
    const task = value.task, contract = value.dialogue_contract;
    if (!task || !contract || typeof value.root !== 'string' || typeof value.session_id !== 'string'
        || task.session_id !== value.session_id || typeof task.task_id !== 'string'
        || task.task_status !== 'open' || !Number.isSafeInteger(contract.state_version)) return null;
    return { root: value.root, session: value.session_id, task: task.task_id, version: contract.state_version };
  } catch { return null; }
}

const sameBinding = (left, right) => Boolean(left && right && left.root === right.root
  && left.session === right.session && left.task === right.task && left.version === right.version);
const invalidJson = failure => failure?.code === 'MALFORMED_RESPONSE' && failure.message === INVALID_TOOL_JSON;
const fingerprint = value => JSON.stringify(value, (_key, item) => item && typeof item === 'object' && !Array.isArray(item)
  ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item);

/** Dependencies are public native services supplied only during activation. */
export function taskScopedRecovery({ readCurrent, toolSchemas, streamChunks }) {
  let agents = new WeakMap(), sessions = new WeakMap();
  const owner = new AbortController();
  let closed = false;
  const state = agent => {
    let record = agents.get(agent);
    if (!record) {
      record = { binding: null, attempt: null, hint: null };
      agents.set(agent, record); sessions.set(agent.session, record);
    }
    return record;
  };
  function eligible(agent, payload, record, attempt) {
    if (closed || !record || owner.signal.aborted || payload.signal?.aborted || !invalidJson(payload.failure)
        || record.attempt !== attempt || !attempt?.confirmed || attempt.turn !== payload.turn
        || attempt.step !== payload.step || attempt.provider !== payload.provider
        || !invalidJson(attempt.failure) || !attempt.names?.length
        || !sameBinding(attempt.binding, record.binding)
        || attempt.binding?.session !== agent.session.header.id) return false;
    try {
      if (!sameBinding(attempt.binding, binding(readCurrent(agent)))) return false;
      const current = new Map(toolSchemas(agent).map(tool => [tool.name, fingerprint(tool)]));
      return attempt.names.every(name => name.startsWith('mcp__task-workflow__')
        && attempt.declared.has(name) && current.get(name) === attempt.declared.get(name));
    } catch { return false; }
  }
  return {
    captureContext(agent, text) {
      if (closed) return;
      state(agent).binding = binding(text);
    },
    observeFrame({ agent, frame }) {
      if (closed) return;
      const record = state(agent);
      if (frame.type === 'start') {
        record.hint = null;
        const header = agent.session.requestHeader();
        record.attempt = { id: frame.attemptId, turn: frame.turn, step: frame.step,
          binding: record.binding, provider: header?.config?.provider,
          declared: new Map((header?.tools ?? []).map(tool => [tool.name, fingerprint(tool)])), confirmed: false };
      } else if (frame.type === 'end' && record.attempt?.id === frame.attemptId) {
        if (frame.outcome.kind === 'committed' && frame.outcome.eventType === 'assistant/attempt'
            && record.attempt.seq === frame.outcome.seq) record.attempt.confirmed = true;
        else { record.attempt = null; record.hint = null; }
      }
    },
    observeEvent(session, event) {
      if (closed) return;
      const record = sessions.get(session), attempt = record?.attempt;
      if (event.type === 'turn/end') { if (record) { record.attempt = null; record.hint = null; } return; }
      if (event.type !== 'assistant/attempt' || !attempt || event.data.turn !== attempt.turn || event.data.step !== attempt.step) return;
      try {
        const starts = streamChunks(event.data.stream, 'block-start');
        const ends = streamChunks(event.data.stream, 'block-end');
        const finish = streamChunks(event.data.stream, 'finish').at(-1);
        const indices = new Set(starts.map(chunk => chunk.index));
        const ended = new Set(ends.map(chunk => chunk.index));
        const complete = starts.length === indices.size && ends.length === ended.size
          && indices.size === ended.size && [...indices].every(index => ended.has(index));
        const tools = ends.filter(chunk => chunk.block?.type === 'tool-call');
        const names = tools.map(chunk => chunk.block.name);
        const declaredCalls = starts.filter(chunk => chunk.blockType === 'tool-call');
        attempt.names = complete && tools.length === declaredCalls.length && tools.every(chunk =>
          declaredCalls.some(start => start.index === chunk.index)) && names.every(name => typeof name === 'string') ? names : null;
        attempt.failure = finish?.reason?.kind === 'error' ? finish.reason.failure : null;
        attempt.seq = event.seq;
      } catch { attempt.names = null; }
    },
    on(ctx, event, listener, options) {
      if (event !== 'agent/request-error') return ctx.on(event, listener, options);
      return ctx.on(event, async function (payload, next) {
        const record = agents.get(payload.agent), attempt = record?.attempt;
        const policy = payload.retryPolicy;
        if (!policy || !['normal', 'always'].includes(policy.mode)
            || !['initialDelayMs', 'maxDelayMs', 'jitterRatio'].every(key => Number.isFinite(policy[key]))
            || !eligible(payload.agent, payload, record, attempt)) return next();
        let downstream, downstreamReturned = false;
        const nextOnce = async () => {
          downstream = await next(); downstreamReturned = true;
          if (downstream?.kind !== 'retry') record.hint = { binding: attempt.binding, seq: attempt.seq };
          return downstream;
        };
        let result;
        try {
          result = await listener.call(this, { ...payload,
            retryPolicy: { mode: 'always', initialDelayMs: policy.initialDelayMs,
              maxDelayMs: policy.maxDelayMs, jitterRatio: policy.jitterRatio },
            signal: AbortSignal.any([payload.signal, owner.signal]),
          }, nextOnce);
        } catch (error) {
          if (downstreamReturned && downstream?.kind === 'retry') return downstream;
          throw error;
        }
        // An existing native recovery decision retains its own authority and lifetime.
        if (downstreamReturned && downstream?.kind === 'retry') return downstream;
        if (result?.kind === 'retry' && eligible(payload.agent, payload, record, attempt)) return result;
        record.hint = null;
        return undefined;
      }, options);
    },
    context(agent) {
      const record = agents.get(agent);
      if (closed || !sameBinding(record?.binding, record?.hint?.binding)) return '';
      return `The native provider rejected the previous workflow response at assistant/attempt ${record.hint.seq} because its tool input was invalid JSON. No tools from that failed response were dispatched. Generate a new response using the current complete tool schema and current stage_guidance.recording_example. Use one valid JSON object for each tool call with its required nested fields. Do not repair or execute the rejected input, replay earlier successful calls, invent answers, or treat regeneration as authorization. Each regeneration is another provider request; the user can cancel the current turn.`;
    },
    disposeAgent(agent) { agents.delete(agent); sessions.delete(agent.session); },
    close() {
      closed = true; owner.abort(new Error('Task Workflow recovery disposed'));
      agents = new WeakMap(); sessions = new WeakMap();
    },
  };
}
