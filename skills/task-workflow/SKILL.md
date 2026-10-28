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
The current dialogue contract's `goal_integrity` field is the shared policy
anchor. The prompt hook and generated stage context carry the same guidance;
use refreshed context so a stage-specific excerpt cannot weaken it.
The plugin does not read, parse, edit, or require `AGENTS.md`. Do not add an entry
to that file. The plugin has no user configuration file, execution profiles,
root-selection wizard, or global task registry.

Discover the tools actually exposed in the current session before choosing a
transport or calling a mutation. Refresh discovery after activation, reconnect,
or an unavailable-tool error; a remembered tool name is not current evidence.
Read the live workflow schema before constructing arguments.
For workflow-scoped work, load the current main skill through the native skill
loader actually exposed by the host. Otherwise use its verified current skill
path with a supported reader. If neither route is available, report the missing
guidance before dependent work; do not guess a tool or stale installation path.
Tool and skill availability do not authorize workflow enrollment or progression.
Ordinary requests keep their direct scope; status requests inspect and answer
without changing the wait.

Work in the current Git project. Store task state in `<project>/.task-workflow/`.
Use exactly `<project>/.worktrees/<task-id>/` for a development worktree.
For `init`, `project` is the existing absolute base checkout path; `task_id` is
the short label. Normally `root` is that same checkout. Enroll from the base with
`owned_worktree:false` and omit `worktree`; use `worktree-prepare` after plan
approval to create the dedicated owned checkout. Preserve an existing registered
state root. Reuse an existing registered task worktree for fixes. New experiment data defaults to
`<project>/.experiments/<experiment-id>/runs/<run-id>/`; an explicit experiment
root can come from the user's already loaded conventions. Preserve existing
registered paths and frozen run inputs. Let the program maintain its project
local `.git/info/exclude` block for generated task directories.

Maintain one program-generated `record.md` per task for intent, exploration,
requirements, sourced decisions, design, plan, progress, and evidence. Use the
fixed sections in [templates/record.md](templates/record.md). Keep all authored
deliverables in English.

The complete current user objective and every confirmed acceptance requirement
remain the target through discussion, design, planning, implementation, review,
integration, verification, runs, and closure. Resolve difficulty through
investigation and concrete implementation planning. Decompose work while
retaining complete acceptance. Change confirmed scope only with explicit actual
user authority recorded in `scope_changes`. Keep confirmed requirements
source-backed and visible across reentry and revised requirements; do not drop,
rename, demote, or replace them by omission or identifier changes. Preserve the
user's authorized provider, model, and resource choices. Apply actual user
permissions and private resource policies without inventing limits or promising
that physical constraints can be removed.
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
Start each applicable reply with the actual content for the current stage, not a
promise to follow the workflow or a generic restatement of the whole process.
Render headings and question-card labels in the user's current conversation
language. English labels in templates and `reply_fields` identify their meaning;
they are not literal display strings. Keep persisted summaries in English.
Use only the current stage's layout and relevant content. Show a complete Spec
or Plan when that exact revision needs review or approval, not on every request.
Routine questions and progress replies state the concrete user decision or
current work. Omit internal rule/skill citations, process apologies, and
administrative narration. If a prior question was wrong, correct it and state
the actual next decision; do not blame the skill. Keep authority and checks in
the record. Honor any higher-priority mandatory permission disclosure when it
actually applies.



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

After an answer, first state what it settles and any consequence. Before asking a
dependent question or moving forward, record it with `process-answer` using its
actual source. Update affected requirements through `process-requirements` and
important choices through `process-decision`, with answer/decision links, status,
rationale, and exact delegation scope. Preserve every existing confirmed
requirement unless an actual user-authorized scope change is recorded with its
prior digest and disposition. An agent proposal stays proposed until confirmed
or explicitly delegated. A broad “go ahead” covers only the content the user
saw. Discuss material behavior, acceptance, dependencies, and genuine unknowns;
do not reopen confirmed scope because work is large, costly, or difficult. Do not
repeatedly offer a smaller subset, prototype, or deferment as a substitute for
investigating and planning the confirmed goal.

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
It cannot verify the semantic truth of natural language or guarantee that a
model follows these instructions. The coordinator must compare the record with
actual messages, project facts, diffs, and evidence. A task is complete only
when the full confirmed completion contract and all applicable review,
integration, verification, run, artifact, reference, and cleanup requirements
are satisfied with accepted evidence.

## Native question handoff

After a discussion or reentry question is successfully recorded, obtain its
actual pending question ID and digest from the returned contract. Use the host's
currently exposed native question capability (`ask_user_question` on DeepSeek
Harness) when it is available and the current agent is eligible. Supply the current-stage context first, then invoke
the native question card; do not replace the available card with a plain-text
question or duplicate its contents in another question paragraph.

Build the card from the exact recorded question and real choices. Preserve
meaning when rendering in the conversation language. Map each unique displayed
option label to its exact recorded choice ID. Do not invent alternatives or
require an option count. Native free-text questions need no artificial choices.
Record the association with the actual native call ID, question ID, and digest
in the task's existing evidence or source references; do not create another task
record. A Spec or Plan approval card refers to the live `approval_target` after
the exact reviewed revision is displayed; do not create a discussion question
in a stage that does not permit one.

Match an immediate tool result or later native answer to that submitted call and
question, then recheck the current pending question and digest before recording
`process-answer`. A nonempty custom answer takes precedence over selected
labels: preserve the raw human text and record no fabricated `choice_id`. A single unambiguous
selection maps to its recorded choice ID. Empty, skipped, pending, stale, or
ambiguous responses do not confirm a choice or approval; retain the actual wait.
Use actual user sources and update linked decisions before dependent progress.

If the capability is absent, unavailable to this agent, or cannot represent the
question, ask the same recorded question in the final question section and
preserve its identity and wait. Do not claim a native card was shown. A live
owned child returns important questions to the coordinator. Native root
eligibility comes from current host capabilities, not historical session links.
See [references/deepseek.md](references/deepseek.md) for native answer details.

## Roles and review

The primary agent coordinates and reviews the task.

Choose each delegation through capabilities actually exposed by the current
host. Preserve explicit user model and execution preferences. On Codex, use
Luna for simple lookup, documentation, and mechanical checks, and Sol for
implementation and review when those models are available. Astra requires
explicit user approval. If a lighter Codex model is unavailable, use an available
Sol model; do not silently escalate to Astra.

On DeepSeek Harness, inherit the host's current authorized provider/model route,
including the user's selected Flash route. Use the exposed plugin-owned
`task_workflow_delegate`, `task_workflow_wait`, and `task_workflow_cancel` tools
for Task Workflow workers. They retain native provider, model, and preset checks.
Query selectable child routes only when its native model-discovery tool is
actually exposed and selection is authorized. Do not guess an internal Flash
identifier, pass OpenAI model names, enable model-selection settings, or silently
change the cost or provider. Record the actual selected route and delegation
evidence. An unavailable capability is a gap to resolve, not a capability to
claim. Reuse a worker only while its model remains suitable, and use a lighter
available authorized route when appropriate. Workers do not delegate recursively.
A worker result, automatic wakeup, resume, or injected context is not a new
human request. Continue the recorded task from its actual wait state.
Track every owned activation handle. Wait for its actual terminal result and
cleanup before final delivery; a report sent while its activation is still
running does not settle it. Cancel an owned activation explicitly when its work
should end, then await settlement. Report cleanup failures as unresolved.
A progress reply can state that work remains active; do not declare completion
or rely on another automatic parent turn to finish the handoff.
The coordinator inspects actual diffs and evidence, and avoids repeated review
cycles or agent turns that add no evidence.

Each item follows `pending -> implementing -> reviewing -> complete`. Failed
review returns it to `implementing`. Give implementers bounded ownership.
Give each fresh child the actual state-root, project, worktree, canonical record,
current context/skill pointers, exact item and role, Spec/Plan revisions, and
source authority in the worker brief. A fresh DeepSeek native child does not
inherit parent history. Other hosts may inherit history through their actual
delegation mechanism; verify what the child receives and keep the explicit brief.
It inspects that context before action and does not acquire the parent's binding
from the brief. Binding changes require actual authority; a coordinator brief
is not new human approval.
Have a task reviewer return separate requirements and quality verdicts against the
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

Use the explicitly bound main/base repository environment for development
worktrees, tests, and development checks. Bind this existing environment once
for the project state root with `environment-bind`. The binding lives in
`.task-workflow/environment.json`. Its legitimate editable installation of the
project source is valid for development.

Register a separate fixed environment for formal training Runs with
`environment-register`, `purpose: runtime`, the explicit `project_distributions`
list, the host-resolved `cache_root`, and the actual `install_receipt`. The receipt
records the successful `uv pip install` command using `--python`, `--cache-dir`,
and `--link-mode symlink`, its zero exit status, and actual stdout/stderr logs
with their SHA-256 digests. Compare third-party distribution names
and versions with the main environment at registration, then freeze that
provenance. Resolve compatibility in the main project's dependency declarations;
do not silently change runtime versions. Validate representative package import
files as actual symlinks into
the shared uv cache. Reject copied or hardlinked packages, foreign editable
installs, overlays, foreign environment paths, and manual `.pth` overlays. Only
exclude the named project distributions after verifying their origin under the
base project; frozen Run imports must resolve project code from the registered
snapshot, not the mutable main checkout. Later changes to main dependencies do
not invalidate already registered or prepared runtime provenance. The host
supplies resolved environment and cache paths; do not infer a `.venv` path or
create copy-based cache workarounds. Preserve historical frozen Runs and their
recorded environment references.

## Integration, resources, and experiments

Implementation approval and Git integration authorization are separate facts.
Use the guarded integration operation only within recorded authorization. It
creates one ordinary squash commit on the selected base with normal Git hooks
and signing. Integration requires a clean base by default. Use
`preserve_unrelated_dirty: true` only when the authorized integration must retain
unrelated dirty tracked work. First preview the exact base, task source, and
preservation digest. Publish with the same revision arguments and exact
`expected_preservation_digest`; preserve staged and unstaged tracked material
without a stash, reset, forced checkout, or unrelated commit. Collision checks
cover candidate paths and ancestors. Untracked and ignored trees outside that
collision frontier stay outside the publication footprint.

Verify the integrated revision before freezing dependent Runs. Integration
verification defaults to `source_mode: live_checkout`, which requires the
current clean integrated checkout. Preserved dirty integration requires
`source_mode: fixed_commit`; optionally pass `expected_integration_commit` to
assert the exact recorded commit. It is never an arbitrary source selector.
That check uses an owned detached checkout of the exact integrated commit and
cleans it only after claim settlement and receipt validation. The fixed runner
removes `PYTHONPATH` and `PYTHONHOME`, disables bytecode writes, and rejects
explicit command paths into mutable registered checkouts. An opaque validator
must itself inspect the bound source. Cancel an unclaimed fixed check only
through its guarded operation; it removes only a proven-owned clean checkout.
Preserve unexpected content or uncertain references and report
`cleanup_pending`; do not replay the check.
Development checks bind their evidence to the actual worktree revision and can
use an authorized managed resource, including a GPU, before merge. Integration
verification runs against the exact integrated commit after merge and can also
use an authorized managed resource, including a GPU. Each check binds evidence
to the revision it actually checks. Long checks run outside shared project and
task write locks; reserve and
reconcile their source-bound evidence in short transactions. Use external
`check-dispatch` to save a durable check intent and return its exact `runner_argv`
for the private controller. `verify` and `integration-verify` run the pinned
local check runner. Reconcile an actual receipt before retry; never relaunch an
existing intent. A proven local protocol-4 pre-admission claim can be cancelled
only after the matching runner is confirmed dead on the same boot, host, and
user identity. For a partial claim, a possibly started workload, or a foreign
owner, require actual terminal evidence for the runner, all owned workloads, and
all process groups. Get the program-derived target from fresh status and copy it
exactly into the observation; do not calculate claim or intent digests. Use
`check-reconcile` or `run-reconcile` with `settlement_path` and nonempty evidence
for a failed or cancelled execution. The observation must include an actual
controller receipt path and SHA-256. `settlement_path` and `receipt_path` are
mutually exclusive. A settlement records non-success; it cannot create a
successful receipt, startup success, or acceptance.

Each new formal Run follows accepted item and overall review, one ordinary
squash integration, successful verification of that integrated revision,
independent frozen inputs, successful startup validation, reference checks, and
safe cleanup of the owned worktree before guarded dispatch. When the user has
paused a workload or retained startup control, prepare and verify the environment
and report readiness; do not dispatch training until the user authorizes its
start. The cleanup receipt
binds the generation, integration proof, Run startup proofs, and removal. A
later approved revision recreates the fixed worktree from current main as a new
generation; preserve earlier Runs and evidence.

`run-prepare` freezes from the recorded integrated Git commit. Its immutable
preparation intent and Run snapshot retain the exact integration verification
proof, including the check receipt and source mode. Preserved dirty integration
requires matching fixed-commit verification before freeze; unrelated live
checkout contents do not become Run code. Recovery retains that original proof
even when a later check passes against the same source.

Record who provided each resource and its observed availability. Derived states
are `available`, `in_use`, `releasable`, `released`, and `unknown`. Record ownership,
actual check and Run uses, retention holds, and release permission explicitly.
A hold names future work or a persistent choice; it does not consume execution
capacity. A terminal use releases only its own capacity. A persistent retention
choice is separate from the owner's permission to release and from authorization
for an actual release action. Do not infer any of these from a successful run or
from each other. The program resolves a program-owned hold only when its exact
task or experiment scope closes. A manually created persistent hold needs an
explicit `resource-hold-resolve` operation after closure. Resolve private
provisioning and execution conventions from
the user's already loaded instructions, then pass concrete parameters to the
program. A state query does not provision or release a resource. Reuse only
after checking recorded ownership, fit, references, and actual availability.
Evaluate capacity against this resource's matching execution references, not
unrelated task closure or artifact review. Preserve active, queued, reserved,
cross-task, and uncertain holds; free capacity does not itself authorize release.
Apply the actual private lifecycle choice and per-action authorization. Correct
misrecorded permission only through the audited `resource-observe` pair described
in the operator reference. Inspect current eligibility and the actual receipt
before any retry; do not repeat a completed release.

Do not impose plugin-level size, file-count, JSON, label, or output-length caps.
Preserve snapshot contents and provenance. Do not set default command deadlines
or maximum user-supplied timeouts. Let actual provider availability and scheduling
govern resource admission. Host, framework, and machine capacity remain
environmental constraints.

Before freezing executable code, inspect the actual entrypoint and its dependency
closure: imported local code, configuration, runtime assets, and fixed external
references. Record inclusion paths and their reasons in the existing task record.
Exclude unrelated subprojects by explicit semantic scope, not a project blacklist.
Resolve material scope or dependency choices through the existing discussion,
Spec review, and actual user approval loop before dependent preparation.

The Spec must define the execution boundary. The plan must name the selected
scope, fixed references, startup validation, actual code-origin checks, immutable
reuse, and ownership-safe cleanup. Give workers these exact inputs and require
corresponding evidence. Use the program's selected batch freeze; do not copy the
whole checkout or construct an unrecorded supervisor snapshot as a substitute.
Project verification that needs a frozen pre-change baseline must use the same
scope and validation helpers to export that baseline. A baseline does not bypass
formal run integration guards.

Before the main workload, execute the frozen startup validation in its actual
environment and working directory. Check required imports, configuration, assets,
fixed reference identities, and actual code origins. Require the program-validated
startup report and successful exit; a successful import alone is insufficient.
Recheck code, environment, and resource eligibility after long startup validation.
Reuse identical immutable code and scope across runs, with each run's source
provenance and mutable outputs recorded separately. Preserve old snapshots and
running inputs. Cleanup requires ownership proof and no remaining references;
uncertain or external content stays in place.

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

## Plugin execution runtime

Launch installed CLI commands through `python3 -I <installed-skill>/scripts/bootstrap.py workflow.py <operation>`. Bootstrap creates the standard-library-only environment at `<installed-skill>/.venv` from the existing host base Python. MCP, hooks, and DeepSeek use this same owned runtime. Project development and scientific training environments remain separate. See [runtime ownership](references/workflow.md#plugin-runtime-and-project-toolchains).
