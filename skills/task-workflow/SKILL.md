---
name: task-workflow
description: Automatically route substantive development and experiment action requests into exploration and design, then coordinate approved implementation, evidence review, Git integration, and frozen runs. Use for explicit invocation, clear substantive action requests, or authorized task continuation. Handle ordinary chat, advice, read-only status, and simple bounded requests directly.
---

# Task Workflow

## Enrollment and context

The main agent chooses the route from the current request and conversation
context. The user's explicit routing choice wins. Handle ordinary chat, advice,
read-only status, and simple bounded requests directly. Automatically use this
skill for substantive development or experiment action requests, starting with
exploration and design. A clear action request authorizes enrollment for that
purpose; record the request as the authorization source. If intent or task
identity is unclear, clarify before enrollment or mutation.

For an existing task, reuse its correct identity and still-applicable
authorization. Perform only the current requested action. A progress question
does not authorize restarting experiments or releasing resources. Confirm the
design before implementation. Implementation and experiment execution require
applicable user authorization. Installation, hook delivery, status views, and
old state do not grant authorization.

This skill, the bundled hooks, and the workflow program supply workflow context.
Use the user's instructions already loaded by the host to resolve optional
private conventions. Pass those resolved values as explicit program arguments.
The plugin does not read, parse, edit, or require `AGENTS.md`. Do not add an entry
to that file. The plugin has no user configuration file, execution profiles,
root-selection wizard, or global task registry.

Work in the current Git project. Store task state in `<project>/.task-workflow/`.
Use exactly `<project>/.worktrees/<task-id>/` for a development worktree. Reuse an
existing registered task worktree for fixes. New experiment data defaults to
`<project>/.experiments/<experiment-id>/runs/<run-id>/`; an explicit experiment
root can come from the user's already loaded conventions. Preserve existing
registered paths and frozen run inputs. Let the program maintain its project
local `.git/info/exclude` block for generated task directories.

Maintain one readable `record.md` per task for the approved design, plan,
decisions, progress, and evidence. Keep all authored deliverables in English.
Summarize decisions from other conversation languages in English and reference
the original source. Preserve externally supplied raw data and behavior-critical
literal values.

## Roles and review

The primary agent coordinates and reviews the task. Choose the model for each
bounded delegation: Luna for simple lookup, documentation, and mechanical
checks; Sol by default for implementation and review. Use Astra only after
explicit user approval. If a lighter model is unavailable, choose an available
Sol model. Do not escalate automatically to Astra. Reuse a worker only while
its model remains suitable; downgrade routine fixes and later phases when a
higher model is no longer needed. Workers do not delegate recursively. The
coordinator inspects actual diffs and evidence, and avoids repeated review
cycles or agent turns that add no evidence.

Each item follows `pending -> implementing -> reviewing -> complete`. Failed
review returns it to `implementing`. Keep blocked reasons and next actions
separate. Complete an independent overall review after implementation items
pass. Approved design, item state, and worker claims do not prove success.

Discuss unresolved design effects, file scope, verification, and recovery before
approval. After approval, continue routine implementation. Revisit material
scope or behavior changes. Use concise progress updates when they add a result,
a meaningful transition, or a needed decision.

## Program interface

Discover `scripts/workflow.py --help` and the `schema` operation before calling
mutations. The standard-library program exposes `dispatch(op, args)`. CLI shape
is `OP --root <project> --json-args '<JSON>'`; `--json-args -` accepts stdin JSON.
The current schema defines operation names, arguments, versions, and guards.
Treat those schemas as the authority rather than inventing fields.

Register the current project and task after explicit invocation, enrollment, or a
clear substantive action request. Pass the host-provided session identifier
when available. Preserve that binding during
recovery; do not choose an unrelated task because it was most recently used.
Use the program's worktree preparation operation before implementation. Do not
implement in a base placeholder or create a substitute worktree path.

After enrollment, invoke the model-only `workflow.status_view` tool with the
known project and task context. It supplies the view binding for this task.
The user selects the current chat's right-hand **Workflow** tab manually. Its
thread entrypoint alone may open without verified chat context; an unbound tab
must explain that state. Do not claim automatic chat identification, global
navigation, or a native task badge. The view refreshes persisted evidence and
does not inspect an external execution service.

## Integration, resources, and experiments

Implementation approval and Git integration authorization are separate facts.
Use the guarded integration operation only within recorded authorization. It
creates one ordinary squash commit on the selected base with normal Git hooks
and signing. Verify the integrated revision before freezing dependent runs.
Cleanup requires accepted integration, snapshots, and reference-safety checks.

Record who provided each resource and its observed availability. Derived states
are `available`, `in_use`, `releasable`, `released`, and `unknown`. Record ownership,
run references, and release permission explicitly. Resolve private provisioning and execution conventions
from the user's already loaded instructions, then pass concrete parameters to
the program. A state query does not provision or release a resource. A finished
run does not authorize release. Reuse only after checking recorded ownership,
fit, references, and actual availability.

An experiment has one research goal and can contain several frozen runs. A
code or configuration change for the same goal creates a new run. A changed
goal creates a new experiment. Freeze code, environment references, arguments,
inputs, outputs, and resource references before execution. Preserve the pinned
runtime and stable environments while runs reference them. Record actual
execution and artifact acceptance before accepting a result. Task, experiment,
run, and resource closure are distinct facts.

Read [references/workflow.md](references/workflow.md) for operating details.
After interruption, reconcile the record with actual Git refs, worktrees,
resource ownership, execution receipts, and artifacts before retrying an action.
Avoid duplicate integration, execution, or release. Report integration and
experiment outcomes separately. Complete the task only after required review,
acceptance, and in-scope cleanup.
