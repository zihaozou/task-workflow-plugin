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
applicable user authorization. Installation, hook delivery, status reads, and
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

## Mandatory conversation sequence

This ordered process is required for an enrolled task. It is not optional
speaking advice. Use natural Chinese or English with the user. Write persisted
summaries and deliverables in English and reference the original messages.
Use concise bold labels with grouped bullets or tables, following the stage
layouts in [templates/conversation.md](templates/conversation.md). Keep one
finding, choice, action, or result per bullet. Put the recorded question or
approval request in a separate final section. Omit empty optional sections.
Keep source identifiers, state versions, digests, and routine recording narration
in the record; show relevant source links only where they help assess a finding.
Use readable revision titles. Do not turn these layouts into long paragraphs.

Use process protocol 2 for new tasks. Legacy tasks retain their recorded state
until a guarded `process-upgrade` with actual authorization. Never invent prior
questions, answers, confirmations, reviews, or approvals.

Before each related reply, read the current `dialogue_contract` from the program
or exact project/session hook context. Check its `applicability` against the
current request. A status question or ordinary message gets a direct answer;
it does not authorize phase progression or require another design question.
Keep any existing wait target intact. For authorized workflow progression,
follow `reply_fields` in order, perform `required_recording_steps`, respect
`allowed_next_operations` within its `operation_scope`, and meet `turn_exit`
before advancing. This list guides dialogue and context steps. It does not list
every task, review, run, resource, integration, or lifecycle operation. Use the
current schema, actual program guards, and existing user authorization for those
operations. A closed task still requires authorized reopening before its work
can change. A pending
question keeps its original text and identity. Use the current `state_version`
for mutations. Refresh context after a conflict or interruption. Preserve exact
digests in program records and approval bindings. Show readable revision titles
to the user; long digests are not required in conversation.

### 1. Inspect context, then open discussion

Read the supplied context and relevant actual project sources before the first
substantive discussion reply. Establish current behavior, affected components,
and evidence gaps. Record intent with `process-intent` and findings with
`process-exploration`. Record the first important unresolved question with
`process-question` before sending it.

The first discussion reply must contain, in this order:

1. The user's intended result and why it matters, distinguishing stated intent
   from any inference.
2. Relevant observed behavior, sources, and the change's likely impact.
3. One important unresolved question and why its answer changes the work.

Invite corrections in that reply. Wait for the answer to the recorded question.
Exit this step only when intent, exploration, and the pending question are
recorded. Do not ask the user for facts the available context already answers.

### 2. Acknowledge, record, explore, and ask

After an answer, first state what it settles and any consequence. Before asking
a dependent question or moving forward, record it with `process-answer` using
its actual source. Update affected requirements through `process-requirements`
and important choices through `process-decision`, with answer/decision links,
status, rationale, and exact delegation scope. An agent proposal stays proposed
until confirmed or explicitly delegated. A broad “go ahead” covers only the
content the user saw.

Explore again when the answer exposes a factual gap. Record new observations
before relying on them. Then ask the next important question, recorded before
sending, and explain its consequence. Repeat acknowledgement, recording,
exploration, and questioning as needed. There is no fixed question count or
mandatory number of alternative designs. Discuss alternatives when they have
real consequences. Wait for the pending answer; exit a discussion turn only
with the settled information synchronized and the next wait target recorded.

### 3. Play back understanding and confirm

As a coherent part becomes clear, play it back before building on it. Present,
in order, user requirements and confirmed choices, agent proposals with reasons,
explicitly delegated choices with scope, and remaining important unknowns.
Ask for correction or confirmation of the exact playback. Record this question
with `purpose: playback_confirmation` before sending. Clarification questions use
`purpose: clarification`, which is the compatibility default when omitted.
Use the explicit purpose field; do not infer purpose from question identifiers.
Keep proposed content distinct even when it is a sensible default. After the response, record the answer and affected requirement/decision
sources, then record `process-playback` with the actual confirmation source.
Repeat discussion and playback when corrections or new facts change the result.
Exit discussion only when the playback is confirmed and no important unresolved
choice blocks a coherent design.

### 4. Review the coherent design, then request approval

Spec (Design) is the same design revision and approval stage. Use the name Spec
in conversation; retain the program's design operations and the record's Design
section. Write the complete Spec with `process-design` using
[templates/spec.md](templates/spec.md). Cover intent, success, scope, observed
current behavior and impact, required behavior, decisions and authority,
constraints, delegated choices, acceptance, failure conditions, and open questions.
Use authoritative intent, requirements, exploration, decisions, components, and
verification records rather than duplicating their authority in prose. Obtain an
independent gap review against those sources and record `process-design-review` for that exact design digest.
The reviewer must identify important guesses a builder would still need to make
before creating a concrete plan. Resolve factual gaps from existing evidence,
settle choices within explicit delegation, and bring new important unknowns from
any worker back into the discussion before dependent work. Review a revised design as needed.

Show the actual reviewed design, its readable revision and title, review outcome, and
meaningful effects. Ask explicitly for approval of that exact design. Wait for
that approval; do not plan implementation before it. Record the actual approval
source with `process-design-approve`. Exit only when the shown, reviewed, and
approved design revision and digest match.

### 5. Present the plan, then request approval

After design approval, record `process-plan` linked to the approved design.
Use [templates/plan.md](templates/plan.md) to present the exact plan revision
and title, linked approved Spec, and concrete tasks. Specify each exact file and
its responsibility, consumed and produced interfaces, ordered action steps,
named checks and their assertions, verification commands or inspection targets,
and expected outcomes. Map tasks to Spec components and acceptance requirements.
Include ownership, dependencies, independent review, applicable integration and
recovery. Prepare/Implement/Verify/Review/Integrate is a lifecycle overview;
it does not replace concrete implementation tasks. An implementer must be able
to act without inventing consequential behavior or test expectations. In the
approval reply, use meaningful component names and readable executable command
text paired with expected outcomes. Keep serialized `argv`, schema objects, and
internal component/requirement/source identifier inventories in the record unless
an identifier helps the user assess a decision. Show each check with its action,
command or inspection target, and expected result together; do not repeat the
same checks in a separate command-metadata dump. A compact product-data JSON
example is useful when its actual shape is a material design choice. Keep every
material behavior, decision, and task visible for approval; a link alone is
insufficient. Ask for
approval of that plan for implementation. Wait for the user's response. Record
its source with `process-plan-approve`. Exit only when the current plan has
approval and still links to the approved design. Design approval alone does
not approve the plan or authorize Git integration.

### 6. Execute, review, and report actual state

Prepare the registered worktree and execute approved plan items. Report a new
result, actual verification evidence, current review state, and the next allowed
action when relevant. A worker report is evidence to inspect. It does not itself
prove acceptance. Record item transitions and separate requirements and quality
verdicts; complete independent overall review before delivery. Report integration,
execution, artifact acceptance, and closure from observed state and their separate
authority sources. Wait only for a real missing user decision or authorization;
continue routine work within approved scope.

At every stage, a new important unknown outside confirmed design or delegated
scope requires `process-reenter`, a recorded question, and user discussion before
the dependent action. Preserve unaffected facts and evidence. Update affected
design/plan revisions and obtain their approvals again; stale approvals cannot
approve a changed revision. Record worker discoveries before asking the resulting
question. Follow [templates/phases.md](templates/phases.md) and
[templates/conversation.md](templates/conversation.md) as required phase contracts.

The program checks declared state, source links, versions, and operation guards.
It cannot verify the semantic truth of natural language or guarantee that a model
follows these instructions. The coordinator must compare the record with actual
messages, project facts, diffs, and evidence.

## Roles and review

The primary agent coordinates and reviews the task.

Choose each delegation through capabilities actually exposed by the current
host. Preserve explicit user model and execution preferences. On Codex, use
Luna for simple lookup, documentation, and mechanical checks, and Sol for
implementation and review when those models are available. Astra requires
explicit user approval. If a lighter Codex model is unavailable, use an available
Sol model; do not silently escalate to Astra.

On DeepSeek Harness, inherit the host's current authorized provider/model route,
including the user's selected Flash route. Use the host's native subagent tools.
Query selectable child routes only when its native model-discovery tool is
actually exposed and selection is authorized. Do not guess an internal Flash
identifier, pass OpenAI model names, enable model-selection settings, or silently
change the cost or provider. Record the actual selected route and delegation
evidence. An unavailable capability is a gap to resolve, not a capability to
claim. Reuse a worker only while its model remains suitable, and use a lighter
available authorized route when appropriate. Workers do not delegate recursively.
The coordinator inspects actual diffs and evidence, and avoids repeated review
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
Treat those schemas as the authority rather than inventing fields. Use the
current host's registered MCP tools or native shell and workflow CLI. DeepSeek
installation, context refresh, native models, and long-operation boundaries are
specified in [references/deepseek.md](references/deepseek.md).

Register the current project and task after explicit invocation, enrollment, or a
clear substantive action request. Pass the host-provided session identifier
when available. Preserve that binding during recovery; do not choose an
unrelated task because it was most recently used.
Use the program's worktree preparation operation before implementation. Do not
implement in a base placeholder or create a substitute worktree path.

The project keeps an explicit selected task for each session. `bind-session`
can select an existing task for the same session or associate an unbound task.
It preserves historical associations and rejects changing a task's session.
Selecting a closed task preserves its closure. Recovery preserves the selected
task. Use `status` with the known project and task context to inspect the
persisted record before continuing authorized work.

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
