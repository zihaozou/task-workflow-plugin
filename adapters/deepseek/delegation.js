/** Exact native activation ownership; no control of ordinary native children. */
import { randomUUID } from 'node:crypto';

export const DELEGATE_TOOL = 'task_workflow_delegate';
export const WAIT_TOOL = 'task_workflow_wait';
export const CANCEL_TOOL = 'task_workflow_cancel';
export const OWNED_PROVIDER = 'spawn';

/** Aborting a reader releases only its listeners, never the observed worker. */
export function abortableRead(promise, signals = []) {
  return new Promise((resolve, reject) => {
    const active = signals.filter(Boolean);
    const remove = () => { for (const signal of active) signal.removeEventListener('abort', abort); };
    const abort = () => {
      remove();
      const error = new Error('Owned child wait was canceled; this wait does not cancel execution.');
      error.name = 'AbortError';
      reject(error);
    };
    if (active.some(signal => signal.aborted)) { abort(); return; }
    for (const signal of active) signal.addEventListener('abort', abort, { once: true });
    Promise.resolve(promise).then(value => { remove(); resolve(value); }, error => { remove(); reject(error); });
  });
}

function deferred() {
  let resolve;
  const promise = new Promise(accept => { resolve = accept; });
  return { promise, resolve };
}

export function ownedDelegations(service) {
  const ownerAbort = new AbortController();
  const records = new Map(), byChild = new Map(), starting = new Map(), handoffs = new Map(), starts = new Set();
  const parents = new Map();
  const disposedParents = new WeakSet();
  const cleanupFailures = new Map();
  let closed = false, closing;
  const sessionId = parent => parent?.session?.header?.id;
  const assertOwner = (record, parent) => {
    if (!record || record.parent !== parent || record.session !== sessionId(parent)) {
      throw new Error('This owned activation handle is unavailable to the current parent.');
    }
    return record;
  };
  const dispose = record => {
    record.disposal ??= Promise.resolve().then(() => record.handle.dispose());
    return record.disposal;
  };
  const complete = record => Promise.resolve(record.handle.result).then(
    result => ({ result }),
    () => ({ error: { code: 'result_unavailable', message: 'The native owned child result could not be captured.' } }),
  ).then(async captured => {
    let cleanup = { status: 'complete' };
    // Native result settlement follows the cleanup attempt. The exact handle's
    // idempotent disposer also exposes a cleanup failure retained by the host.
    try { await dispose(record); } catch {
      cleanup = { status: 'failed', message: 'Native owned child cleanup failed. Inspect its recorded outcome.' };
    }
    record.outcome = { handleId: record.id, subagentId: record.handle.childId, status: 'settled', ...captured, cleanup };
    return record.outcome;
  });
  const registry = {
    async start(spec) {
      if (closed) throw new Error('Task Workflow delegation is disposing.');
      const parent = spec.request?.parent;
      if (!parent || typeof sessionId(parent) !== 'string') throw new Error('Owned delegation requires an exact native parent.');
      if (disposedParents.has(parent)) throw new Error('The owned parent is disposed.');
      if (!parents.has(parent)) parents.set(parent, { abort: new AbortController(), starts: new Set(), closed: false });
      const parentLifetime = parents.get(parent);
      if (parentLifetime.closed) throw new Error('The owned parent is disposing.');
      const childId = spec.childId ?? randomUUID();
      const publication = deferred();
      const pending = { parent, publication, messageId: undefined, state: 'starting' };
      starting.set(childId, pending);
      handoffs.set(childId, pending);
      const work = Promise.resolve().then(async () => {
        try {
          const signal = AbortSignal.any([ownerAbort.signal, parentLifetime.abort.signal, spec.signal].filter(Boolean));
          const handle = await service.startActivation({ ...spec, childId, signal, delivery: 'caller' });
          if (handle.childId !== childId || typeof handle.dispose !== 'function' || !handle.result
              || typeof handle.messageId !== 'string') {
            pending.state = 'failed';
            publication.resolve();
            await handle.dispose();
            throw new Error('The native provider did not return the required owned activation capabilities.');
          }
          pending.messageId = handle.messageId;
          pending.state = 'published';
          const record = { id: randomUUID(), parent, session: sessionId(parent), handle, initialMessageId: handle.messageId };
          records.set(record.id, record);
          byChild.set(handle.childId, record);
          record.settlement = complete(record);
          if (closed || parentLifetime.closed) {
            await Promise.allSettled([dispose(record), record.settlement]);
            throw new Error('Task Workflow delegation was disposed during startup.');
          }
          return handle;
        } catch (error) {
          if (pending.state !== 'published') pending.state = 'failed';
          throw error;
        } finally { publication.resolve(); starting.delete(childId); }
      });
      starts.add(work);
      parentLifetime.starts.add(work);
      try { return await work; } finally { starts.delete(work); parentLifetime.starts.delete(work); }
    },
    descriptor(childId, parent) {
      const record = assertOwner(byChild.get(childId), parent);
      return { kind: 'activation', subagentId: record.handle.childId, handleId: record.id };
    },
    async humanMessages(agent, messages, signal) {
      const pending = starting.get(agent.id);
      if (pending) await abortableRead(pending.publication.promise, [signal, ownerAbort.signal]);
      const handoff = handoffs.get(agent.id);
      if (handoff?.state === 'failed') throw new Error('Owned initial input identity was not published; no human prompt hook can be attributed.');
      const initial = byChild.get(agent.id)?.initialMessageId ?? handoff?.messageId;
      return messages.filter(message => message.source?.kind === 'user' && message.id !== initial);
    },
    async wait(handleId, parent, signal) {
      if (closed) throw new Error('Task Workflow delegation is disposing.');
      const record = assertOwner(records.get(handleId), parent);
      return abortableRead(record.settlement, [signal, parents.get(parent)?.abort.signal, ownerAbort.signal]);
    },
    async cancel(handleId, parent, signal) {
      if (closed) throw new Error('Task Workflow delegation is disposing.');
      const record = assertOwner(records.get(handleId), parent);
      record.cancelRequested = true;
      // This is explicit cancellation of the exact owned activation, unlike a
      // native interrupt request that preserves queued work and descendants.
      dispose(record).catch(() => {});
      return abortableRead(record.settlement, [signal, parents.get(parent)?.abort.signal, ownerAbort.signal]);
    },
    context(parent) {
      return [...records.values()].filter(record => record.parent === parent && record.session === sessionId(parent)).map(record => ({
        handleId: record.id, subagentId: record.handle.childId,
        status: record.outcome ? 'settled' : 'pending', cancelRequested: record.cancelRequested === true,
        ...record.outcome ? { cleanup: record.outcome.cleanup } : {},
      }));
    },
    async disposeParent(parent) {
      disposedParents.add(parent);
      if (!starting.has(parent.id)) handoffs.delete(parent.id);
      const lifetime = parents.get(parent);
      if (!lifetime) return;
      if (lifetime.disposing) return lifetime.disposing;
      lifetime.closed = true;
      lifetime.abort.abort();
      lifetime.disposing = (async () => {
        await Promise.allSettled([...lifetime.starts]);
        const owned = [...records.values()].filter(record => record.parent === parent);
        try {
          const results = await Promise.allSettled(owned.flatMap(record => [dispose(record), record.settlement]));
          if (results.some(result => result.status === 'rejected') || owned.some(record => record.outcome?.cleanup.status !== 'complete')) {
            throw new Error('Disposed parent owned child cleanup did not complete.');
          }
        } finally {
          for (const record of owned) {
            if (record.outcome?.cleanup.status !== 'complete') cleanupFailures.set(record.id, {
              handleId: record.id, subagentId: record.handle.childId, cleanup: record.outcome?.cleanup ?? { status: 'failed' },
            });
            records.delete(record.id);
            if (byChild.get(record.handle.childId) === record) byChild.delete(record.handle.childId);
          }
          for (const [childId, pending] of handoffs) if (pending.parent === parent) handoffs.delete(childId);
          parents.delete(parent);
        }
      })();
      return lifetime.disposing;
    },
    close() {
      if (closing) return closing;
      closed = true;
      ownerAbort.abort();
      closing = (async () => {
        await Promise.allSettled([...starts]);
        const owned = [...records.values()];
        try {
          const results = await Promise.allSettled(owned.flatMap(record => [dispose(record), record.settlement]));
          if (cleanupFailures.size || results.some(result => result.status === 'rejected') || owned.some(record => record.outcome?.cleanup.status !== 'complete')) {
            throw new Error('Task Workflow owned child cleanup did not complete.');
          }
        } finally {
          records.clear(); byChild.clear(); starting.clear(); handoffs.clear(); parents.clear();
        }
      })();
      return closing;
    },
  };
  return registry;
}

const handleParameters = { type: 'object', properties: { handle_id: { type: 'string', minLength: 1,
  description: 'The exact handleId returned by task_workflow_delegate in this parent.' } }, required: ['handle_id'], additionalProperties: false };

export function collectionTools(registry) {
  return [
    [WAIT_TOOL, 'Wait for this parent\'s exact owned activation result and cleanup. Canceling this wait leaves its worker running.', 'wait'],
    [CANCEL_TOOL, 'Cancel this parent\'s exact owned activation and await its real outcome and cleanup. This affects only the owned activation and its descendants.', 'cancel'],
  ].map(([name, description, method]) => ({
    name, description, parameters: handleParameters,
    output: { schema: { type: 'object', additionalProperties: true }, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }] },
    isConcurrencySafe: () => true,
    execute(args, exec) { return registry[method](args.handle_id, exec.agent, exec.signal); },
  }));
}

/** Keep native parameter, route, preset and depth policy; change only ownership. */
export function delegationFacades(ctx, registry) {
  const originalByWrapped = new WeakMap();
  const tools = new Proxy(ctx.tools, { get(target, property) {
    if (property === 'register') return definition => {
      if (definition.name !== DELEGATE_TOOL) return target.register(definition);
      const wrapped = { ...definition,
        description: 'Start a Task Workflow owned native child. Use task_workflow_wait with its handleId before reporting its final result. Use task_workflow_cancel only to cancel that owned activation. Model, preset and depth checks remain native.',
        output: { ...definition.output, schema: { ...definition.output.schema,
          properties: { ...definition.output.schema.properties, handleId: { type: 'string' } },
          required: [...definition.output.schema.required ?? [], 'handleId'],
        }, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }] },
        async execute(args, exec) {
          const value = await definition.execute.call(definition, args, exec);
          return registry.descriptor(value.subagentId, exec.agent);
        },
      };
      originalByWrapped.set(wrapped, definition);
      return target.register(wrapped);
    };
    if (property === 'get') return (...args) => { const value = target.get(...args); return originalByWrapped.get(value) ?? value; };
    const value = Reflect.get(target, property, target);
    return typeof value === 'function' ? value.bind(target) : value;
  } });
  const subagents = new Proxy(ctx.subagents, { get(target, property) {
    if (property === 'startActivation') return spec => registry.start(spec);
    const value = Reflect.get(target, property, target);
    return typeof value === 'function' ? value.bind(target) : value;
  } });
  return { tools, subagents };
}
