# Workflow reference

## 1. Enroll and discover

The main agent uses the current request and conversation context to choose the
route. The user's explicit routing choice wins. Handle ordinary chat, advice,
read-only status, and simple requests directly. Use this skill
automatically for substantive development or experiment action requests,
starting with exploration and design. A clear action request authorizes
enrollment for that purpose; record the request as the authorization source.
Clarify unclear intent or task identity before enrollment or mutation.

Reuse the correct existing task and still-applicable authorization for followups.
Perform only the current requested action. A progress question does not authorize
restarting experiments or releasing resources. Confirm design before
implementation and obtain applicable authorization before implementation or
experiment execution. The current Git project owns state under `.task-workflow`.
Plugin installation, hook delivery, status reads, and old state grant no action
authorization.

Discover the program's `schema` operation before mutations. Use its actual
arguments, operation names, versions, and guards. Record task identity,
coordinator, authorization source, and the completion contract. Pass the
host-provided session identifier when available.

Resolve private conventions from instructions already loaded by the host. Pass
concrete environment, storage, execution, and resource values as explicit
arguments. The plugin does not open or update private instruction files, require
an `AGENTS.md` entry, or maintain a user configuration file or global registry.

Keep one program-generated task `record.md` with the sections in
[../templates/record.md](../templates/record.md). Structured state and event
files support recovery; they do not prove external actions. Write English
summaries with references to actual original source messages and revisions.
Preserve external raw data and behavior-critical literal values.

## 2. Discuss, design, plan, delegate, and review

New tasks use process protocol 2. The supported process mutations are
`process-intent`, `process-exploration`, `process-question`, `process-answer`,
`process-playback`, `process-requirements`, `process-decision`, `process-design`,
`process-design-review`, `process-design-approve`, `process-plan`,
`process-plan-approve`, and `process-reenter`. `process-upgrade` is a guarded
legacy migration. Discover the live schema before calling any mutation. Pass
the current state version and actor. Design and plan versions have digests;
their review and approval operations refer to the exact digest shown.

For `process-question` and `process-reenter`, `question.scope` contains existing
requirement identifiers, not descriptions or file paths. Use an empty list when
no applicable requirements are recorded yet. Do not invent requirements merely
to ask a question. Optional `unknowns` entries must match recorded exploration
unknowns; use the live schema and current records for these references.
Set `question.purpose` to `playback_confirmation` when asking the user to confirm
a playback. Use `clarification` for clarification questions; omission retains
that default for compatibility. The program selects playback reply fields and
waits from this persisted field, not from question identifiers or text heuristics.

The mandatory sequence lives in the main skill. Inspect actual context before
the first substantive discussion reply. Record intent and exploration, then
record the first question before sending it. The reply restates intent and why,
then findings and impact, then one important unresolved question and consequence.
Invite corrections. Wait for that question's answer.

Acknowledge what each answer settles. Record its actual source and update affected
requirements and decisions before a dependent question or step. Explore newly
exposed factual gaps and record observations before relying on them. Record each
new question before sending. Repeat exploration, questions, and playback as the
understanding develops. There is no required count of questions or alternatives.
Play back user requirements and confirmed choices, agent proposals, delegated
choices with exact scope, and remaining unknowns in that order. Record the playback
question before sending; wait for confirmation, record its answer and corrected
sources, then record confirmed playback. A source must identify an actual message,
event, or reviewed revision. A user confirmation covers only the content shown.

Write a coherent design with behavior, components, interfaces, mapped requirements
and decisions, assumptions, verification, and recovery. Obtain independent gap
review for its exact digest. New important reviewer or worker unknowns return to
discussion before dependent work. Show the actual reviewed design, readable revision
and title, review outcome, and meaningful effects. Wait for explicit approval of
that design. Record it before preparing the plan. Then show the linked plan's
exact readable revision and title, work, ownership, dependencies, verification, independent
reviews, integration scope, and recovery. Wait for plan approval and record its
actual source before implementation. Broad approval does not cover unseen details.

At every stage, check whether confirmed design and explicit delegation settle the
next important choice. If not, use `process-reenter`, record its question before
asking, and synchronize the answer and affected sources before dependent work.
Preserve unaffected facts and evidence. Revise affected design and plan versions;
old approvals cannot approve changed versions. Routine work within approved scope
continues. Follow [../templates/phases.md](../templates/phases.md) for required
writes, waits, exit checks, and handoffs, and
[../templates/conversation.md](../templates/conversation.md) for ordered responses.

The coordinator delegates focused implementation with owned paths, expected
behavior, verification, and evidence requirements. Workers implement, fix, and
test without recursive delegation. Use
[../templates/worker-briefs.md](../templates/worker-briefs.md) and
[../templates/worker-reports.md](../templates/worker-reports.md). Put brief and
report references in the one task record. Choose a model for every focused delegation:
Luna for simple lookup, documentation, and mechanical checks; Sol by default for
implementation and review. Astra requires explicit user approval. If a lighter
model is unavailable, choose an available Sol model. Never escalate automatically
to Astra. Reuse workers only while their model remains suitable; downgrade
routine fixes and later phases when the higher model is no longer needed.
Review actual evidence and avoid agent turns or review cycles that add none.
Do not claim a capability or parallel execution that did not occur.

Each item follows `pending -> implementing -> reviewing -> complete`. Failed
review returns it to `implementing`. A task reviewer returns separate
requirements and quality verdicts from actual diffs and evidence. Keep blocked reasons and next actions
separate. The coordinator inspects actual diffs and evidence. After the items
pass, independently review the full deliverable as an overall item. Reuse valid
evidence only when the approved design and relevant code remain unchanged.

## 3. Project paths and Git

```text
<project>/
  .task-workflow/                    # Task state and records
  .worktrees/<task-id>/              # Fixed development worktree
  .experiments/<experiment-id>/
    runs/<run-id>/
      code/                         # Frozen code
      snapshot.json
      ...                           # Run outputs
```

The development worktree path is fixed. Prepare it through the program and
reuse it for fixes. Do not implement in a base placeholder or select a different
path. Preserve existing registered paths during recovery. An experiment can use
an explicit root resolved from user conventions; its default root is
`<project>/.experiments`.

The program audits and maintains its project-local `.git/info/exclude` block
for generated directories. It does not alter global Git settings. Inspect
source and ignored inputs before freezing or cleanup. Git covers tracked code;
required non-Git inputs need explicit preservation and evidence.

Implementation approval and integration authorization are separate. Within
recorded authorization, the program validates expected base and task revisions
and creates exactly one ordinary squash commit on the base. Keep normal Git
hooks and signing. Verify the actual integrated revision before freezing a
dependent run. Preserve uncertain or conflicted integration for review before
retrying. Cleanup checks integration proof, snapshots, references, and unique
material before removing the owned worktree.

## 4. Resources and frozen execution

A resource represents execution capacity supplied under the user's private
conventions. The public program records identity, ownership, state, active run
references, and release permission. It does not encode a provider's policy.
Record who provided it separately from its observed availability. Its derived
state is `available`, `in_use`, `releasable`, `released`, or `unknown`.

Register resources with actual identity and ownership evidence. Reuse them only
after checking actual availability, compatibility, and all run references. A
planned reservation establishes a resource reference. Planning and preparation
can reference pending capacity after identity, ownership, release seal, and
capability checks. Actual start requires a fresh available observation and no
conflicting execution reported by the provider. The plugin imposes no blanket
active-run limit; actual provider availability and scheduling govern admission.
Finishing a run records its
execution outcome; it does not grant release permission. Release requires
explicit permission, verified ownership, and resolved active references.
Reconcile uncertain release results before retrying. A status read has no
provisioning or release effect.

An experiment has one research goal and may contain many frozen runs. A
code-only task can use verification runs without becoming a research experiment.
Changed code or arguments for the same goal creates a new run. Changed goals
create new experiments.

Freeze code, environment references, entrypoint, arguments, inputs, outputs,
and resource references before execution. Keep stable environments outside
removable worktrees. Verify actual imports when dependencies can resolve back
to development source. Preserve existing symbolic links and referenced targets.
Shared caches are outside task cleanup.

Record purpose, parent run, checkpoint reference when relevant, frozen snapshot,
resource identity, execution receipt, and artifact acceptance. The program pins
the workflow and runner runtime. Preserve referenced runtime files and stable
environments for existing execution. Later changes create a new run.

New frozen runtimes record execution protocol 2 in their metadata and both
hashed runtime files. Unstarted runs with an earlier runtime are rejected before
dispatch or launch. Preserve their frozen files and records, then create a new
Run identity with the same approved inputs. Existing actual execution receipts
remain available for reconciliation through their original runtime.

Runs and commands have no default execution time limit. A timeout is optional
and applies only when the user supplies it; the plugin does not set a maximum.
`run-execute` waits for a receipt by default; `detached: true` returns after
launching the pinned runner.

For an external executor, call `run-dispatch` with `root`, `task_id`, `actor`,
`expected_version`, and `run_id`. Its optional `timeout` becomes immutable.
The operation saves `execution_intent` and returns `runner_argv`; it launches
nothing. Execute that exact argument array on the resource through the private
controller. The root, frozen runtime, environment, and output paths must be
accessible there. The run stays `queued` until its pinned runner checks current
ownership, availability, capabilities, and conflicting execution under locks.
The runner makes a permanent claim, starts the actual workload, and records its
process identity before releasing those locks. A queue receipt alone cannot
mark a run `running`. Repeated dispatch returns the original argument array and
intent without another launch. An unclaimed queued run can be cancelled; a
later runner then fails admission. A claimed execution requires reconciliation. If a local runner fails admission
before claiming or starting, its run remains queued and can be cancelled.

Reread task status after the runner starts to obtain the current version. Use
`run-observe` with `run_id`, `receipt_path`, and `evidence`, or use
`run-reconcile` for the canonical receipt. Both ingest actual execution evidence
without launching or repeating the workload. Preserve the frozen inputs,
execution token, log identity, and claim after interruption.

Submission does not prove execution. A zero exit does not prove artifact
quality. Accept actual artifacts with verification evidence. Experiment closure
requires resolved planned work and accepted analysis. Task closure requires the
complete deliverable, reviews, integration contract, experiments, runs, and
required cleanup. Keep earlier closure history when reopening work.

## 5. Tools, hooks, and recovery

Normal program results and the read-only context operation return a fresh
`dialogue_contract`. Its `contract_version`, `task_id`, `state_version`, and
`stage` identify the current state. `pending_questions` includes question text,
rationale, choices, and digest; `missing_records` names synchronization gaps.
Follow ordered `reply_fields`, `required_recording_steps`, `wait_for`, `turn_exit`,
`approval_target`, and `allowed_next_operations` within its `operation_scope`.
The list guides dialogue and context steps; other task, review, run, resource,
integration, and lifecycle operations follow the current schema, actual guards,
and existing user authorization. Closed tasks still require authorized reopening
before their work can change. Check `applicability` against
the current request: direct status and ordinary replies preserve a pending wait
without forced discussion or phase progression. `templates` links the required
response and record structures. Refresh context after a version conflict or
interruption. Source-linked answers and decisions must precede dependent work.

Guards check declared state, provenance links, and revisions. They cannot verify
natural-language semantic truth or guarantee model obedience. Compare the record
with actual messages, project facts, and evidence before reporting progress.

MCP tools use the same program and persistence. Reconnect the process after an
update and rediscover schemas. Replacing source does not reload an existing
process. Use one current interface for mutations in a task.

The project-local registry stores explicit session-to-task selections.
Enrollment and `bind-session` can select another task for the same session.
Historical task associations remain intact; an already associated task cannot
change its session. A closed task remains closed when selected. SessionStart
uses the explicit selection and exact recorded session match. A stale or
invalid selection does not fall back to another task. Legacy records without a
selection restore only a unique exact session match. Ordinary recovery preserves
the existing selection; an interrupted selection write can be repaired by an
explicit `bind-session` call with the current task version.

Use `status` with explicit project and task context to inspect persisted
records. Preserve the recorded session association during recovery.

The plugin imposes no transport or hook input-size, file-count, JSON, label, or
context caps, and no fixed hook deadline. Preserve complete snapshots and their
provenance. Host, framework, and machine limits remain environmental behavior.

SessionStart restores safe facts only for existing tasks in the current
project. Validate `cwd` and `session_id`, then use exact recorded session
bindings. Unenrolled sessions remain quiet. Do not put prompts, arbitrary logs,
private instruction files, or task prose into recovery context. The
UserPromptSubmit hook restores the fresh contract for the exact selected task in
the current project/session, plus routing and naming guidance for the main agent. It does not classify requests, call a separate model or API, read
transcripts or private instructions, echo prompts, or enroll work. The main
agent chooses the route using the conversation it already has.

The selected Codex manifest at `.codex-plugin/plugin.json` explicitly declares
`./hooks/hooks.json`. The package omits root `plugin.json` because the tested
native client does not discover bundled hooks with that portable root present.
Review and trust hooks through the host's supported flow. A hook does not
authorize an action, complete a task, or prove execution success. After an
interruption, compare the canonical record with actual files, Git refs,
resource ownership, execution receipts, and artifacts. Check whether an action
happened before replaying it. Record discrepancies and recover from evidence.

## 6. Report and complete

Lead updates with a new result or next action. Include material verification,
output locations, and unresolved decisions. Explain unfamiliar terms on first
use, keep names stable, and explain rename mappings. Keep routine updates short
and avoid duplicate reports.

Before large execution, state scope and stopping conditions. Review actual
results and required cleanup before declaring completion. Report integration,
execution, artifact acceptance, experiment closure, task closure, and resource
release as separate facts when they affect the conclusion.
