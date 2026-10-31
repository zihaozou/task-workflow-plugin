/** Bind observed native activations to the existing shared-core worker ledger. */
export function workflowLedger({ readCurrent, call }) {
  const binding = parent => {
    const text = readCurrent(parent);
    if (!text) return null;
    const prefix = 'Registered Task Workflow context: ';
    if (!text.startsWith(prefix)) throw new Error('Current Task Workflow context is unavailable before delegation.');
    const current = JSON.parse(text.slice(prefix.length));
    return { root: current.root, task_id: current.task.task_id };
  };
  const stateFor = target => {
    const response = call('status', { root: target.root, task_id: target.task_id });
    if (!response?.ok || !response.state) throw new Error('Current Task Workflow worker state is unavailable.');
    return response.state;
  };
  const mutate = (operation, target, fields) => {
    const state = stateFor(target);
    const response = call(operation, { ...target, actor: state.coordinator, expected_version: state.version, ...fields });
    if (!response?.ok) throw new Error(`Task Workflow ${operation} was not recorded. Refresh context and reconcile the actual activation.`);
    return response;
  };
  return {
    prepare(parent, assignmentId) {
      const target = binding(parent);
      if (!target) {
        if (assignmentId) throw new Error('A worker assignment requires the current bound Task Workflow task.');
        return null;
      }
      const state = stateFor(target);
      if ((state.workflow_control_version ?? 1) !== 2 && !assignmentId) return null;
      if (!assignmentId) throw new Error('Control-version-2 delegation requires an existing assignment_id.');
      const assignment = state.workers?.[assignmentId];
      if (!assignment || assignment.status !== 'assigned') throw new Error('Delegate only an existing assigned worker from the current task.');
      return { ...target, assignment_id: assignmentId };
    },
    activate(target, activation) {
      return mutate('worker-activate', target, { assignment_id: target.assignment_id, activation,
        evidence: [`Observed native activation ${activation.handle_id}; child ${activation.child_session_id}; message ${activation.message_id}.`] });
    },
    settle(target, outcome) {
      const cancelled = outcome.result?.stopReason === 'aborted';
      // A public completed native result proves terminal transport completion,
      // not requirements acceptance. Unknown/native failure reasons remain failed.
      const succeeded = !outcome.error && outcome.result?.stopReason === 'completed';
      return mutate('worker-settle', target, { assignment_id: target.assignment_id,
        outcome: cancelled ? 'cancelled' : succeeded ? 'succeeded' : 'failed',
        result: { ...(outcome.result === undefined ? {} : { native_result: outcome.result }),
          ...(outcome.error ? { native_error: outcome.error } : {}), handle_id: outcome.handleId, child_session_id: outcome.subagentId },
        cleanup: outcome.cleanup.status === 'complete',
        evidence: [`Observed terminal native activation ${outcome.handleId}; cleanup ${outcome.cleanup.status}.`] });
    },
  };
}
