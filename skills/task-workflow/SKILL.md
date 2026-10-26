---
name: task-workflow
description: Automatically route substantive development and experiment action requests into exploration and design, then coordinate approved implementation, evidence review, Git integration, and frozen runs. Use for explicit invocation, clear substantive action requests, or authorized task continuation. Handle ordinary chat, advice, read-only status, and simple requests directly.
---

# Task Workflow

## Enrollment and context

The main agent chooses the route from the current request and conversation
context. The user's explicit routing choice wins. Handle ordinary chat, advice,
read-only status, and simple requests directly. Automatically use this
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

Maintain one program-generated `record.md` per task for intent, exploration,
requirements, sourced decisions, design, plan, progress, and evidence. Use the
fixed sections in [templates/record.md](templates/record.md). Keep all authored
deliverables in English.
Summarize decisions from other conversation languages in English and reference
the original source. Preserve externally supplied raw data and behavior-critical
literal values.

## Structured dialogue and authority

Use process protocol 2 for new tasks. An existing task without that protocol
remains a legacy task until a guarded `process-upgrade` with real authorization.
Do not fabricate prior questions, confirmations, or approvals. Use the current
program schema and state version for every mutation.

Explore the actual project, then discuss important unknowns through one useful
open or multiple-choice question at a time. Explain the consequence of each
question. Build on the answer; return to exploration when it reveals a missing
fact. Make no fixed number of questions or alternative designs mandatory. Real
alternatives may emerge when they affect the task. Play back confirmed user
requirements and choices separately from agent proposals and delegated choices.
Each important choice needs an actual source reference, status, rationale, and
scope. A broad “go ahead” does not approve unseen details.

Draft a design from confirmed requirements and decisions. Obtain an independent
design-gap review. Present the reviewed design revision to the user and record
approval for that exact revision. Build a plan from the approved design, then
record the user's approval of that plan revision. If the next consequential
action exceeds what the confirmed design and explicit delegation settle, ask
the user and return to discussion. Routine work within approved scope proceeds.
Use [templates/phases.md](templates/phases.md) for phase contracts and
[templates/conversation.md](templates/conversation.md) for speaking structures.
The program owns the record and phase guards.

## Roles and review

The primary agent coordinates and reviews the task. Choose the model for each
focused delegation: Luna for simple lookup, documentation, and mechanical
checks; Sol by default for implementation and review. Use Astra only after
explicit user approval. If a lighter model is unavailable, choose an available
Sol model. Do not escalate automatically to Astra. Reuse a worker only while
its model remains suitable; downgrade routine fixes and later phases when a
higher model is no longer needed. Workers do not delegate recursively. The
coordinator inspects actual diffs and evidence, and avoids repeated review
cycles or agent turns that add no evidence.

Each item follows `pending -> implementing -> reviewing -> complete`. Failed
review returns it to `implementing`. Give implementers bounded ownership. Have
a task reviewer return separate requirements and quality verdicts against the
actual diff and evidence.
Keep blocked reasons and next actions separate. Complete an independent overall
review after implementation items pass. Approved design, item state, and worker
claims do not prove success. Use
[templates/worker-briefs.md](templates/worker-briefs.md) and
[templates/worker-reports.md](templates/worker-reports.md) for delegation and
return formats. Store their references and verdicts in the one task record.

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
when available. Preserve that binding during recovery; do not choose an
unrelated task because it was most recently used. After CLI enrollment or
recovery, invoke MCP `status` or `workflow.status_view`
with explicit root and task context to establish the view. A CLI call does not
open a native UI panel.
Use the program's worktree preparation operation before implementation. Do not
implement in a base placeholder or create a substitute worktree path.

Native `init`, `status`, `bind-session`, and `recover` results supply the UI
resource and a safe view projection. The user selects the current chat's
right-hand **Workflow** tab manually. Only `workflow.status_view` has a thread
entrypoint. Its empty invocation can reuse a verified context when the host
supplies the same optional `openai/session` correlation metadata. Missing or
unknown metadata leaves it unbound. Supply explicit root, task, and matching
session context when available; host correlation does not authorize work.

The project keeps an explicit selected task for each session. `bind-session`
can select an existing task for the same session or associate an unbound task.
It preserves historical associations and rejects changing a task's session.
Selecting a closed task preserves its closure. Recovery preserves the selected
task. After a process restart, supply explicit context again to recreate the
view reference and optional host correlation. An unbound tab explains its state.
Do not claim automatic native tab opening, host metadata availability, or tested
client rendering without evidence. The view refreshes persisted evidence and
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

Do not impose plugin-level size, file-count, JSON, label, or output-length caps.
Preserve snapshot contents and provenance. Do not set default command deadlines
or maximum user-supplied timeouts. Let actual provider availability and scheduling
govern resource admission. Host, framework, and machine capacity remain
environmental constraints.

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
