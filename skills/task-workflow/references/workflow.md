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

Discover current host tools before selecting a transport. Refresh discovery
after activation, reconnect, or an unavailable-tool error. Discover the program's `schema` operation before mutations. Use its actual
arguments, operation names, versions, and guards. Record task identity,
coordinator, authorization source, and the completion contract. Pass the
host-provided session identifier when available.

`init.root` is an existing absolute state directory, normally the project
checkout root. `init.project` is the existing absolute base Git checkout root,
not its display name. Use `task_id` for a short task label. For base enrollment,
omit `worktree` and use `owned_worktree:false`; `worktree-prepare` creates the
dedicated checkout after plan approval. An existing dedicated checkout must be
`project/.worktrees/task-id` in the same Git repository. Ownership permits later
cleanup of that dedicated checkout; it never applies to the base checkout.
Correct an initialization error using the current schema and its repair message;
keep the selected project, state root, and actual session identity consistent.

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

`process-requirements.scope_changes` records an explicit user-authorized change
to a confirmed requirement. Each entry names `requirement_id`, its
`previous_digest`, `action` (`remove`, `replace`, `revise`, or `demote`), the
reason, and `authorization_source` pointing to the actual user message.
`replacement_ids` is required only for `replace`. Keep revised and replacement
requirements source-backed and confirmed. Omission, a new ID, or list
replacement is not scope-change authority.

For `process-question` and `process-reenter`, `question.scope` contains existing
requirement identifiers, not descriptions or file paths. Use an empty list when
no applicable requirements are recorded yet. Do not invent requirements merely
to ask a question. Optional `unknowns` entries must match recorded exploration
unknowns; use the live schema and current records for these references.
Set `question.purpose` to `playback_confirmation` when asking the user to confirm
a playback. Use `clarification` for clarification questions; omission retains
that default for compatibility. The program selects playback reply fields and
waits from this persisted field, not from question identifiers or text heuristics.

### Complete process-question request

This is a complete illustrative `process-question` argument object, not a task
requirement or user authorization. Replace the root, task ID, actor, current
version, proposal references, and content with actual task values. Record sourced
intent and exploration first. The question fields belong inside `question`;
common operation arguments remain outside it. Use no choices for an open
question when appropriate; this example's meaningful alternatives do not set a
required count. An empty scope is valid before requirements are recorded.

<!-- process-question-complete-example -->
```json
{
  "root": "/absolute/path/to/project",
  "task_id": "report-export",
  "actor": "coordinator",
  "expected_version": 3,
  "question": {
    "id": "q-json-destination",
    "text": "Where should JSON output be written?",
    "rationale": "The destination determines how the receiving script reads results.",
    "scope": [],
    "important": true,
    "purpose": "clarification",
    "source": {
      "kind": "agent",
      "reference": "Illustrative coordinator proposal; replace with the actual discussion reference."
    },
    "choices": [
      {
        "id": "stdout",
        "text": "Write JSON to stdout",
        "consequence": "The receiving script reads stdout while the existing CSV behavior stays unchanged.",
        "source": {
          "kind": "agent",
          "reference": "Illustrative coordinator proposal; replace with the actual discussion reference."
        }
      },
      {
        "id": "file",
        "text": "Write JSON to a separate file",
        "consequence": "The receiving script reads that file while the existing CSV behavior stays unchanged.",
        "source": {
          "kind": "agent",
          "reference": "Illustrative coordinator proposal; replace with the actual discussion reference."
        }
      }
    ]
  }
}
```

After an `ok:true` result, obtain the pending question and digest from its
`dialogue_contract`. Use the available native question tool with that exact
question identity. Render the question and unique choice labels in the user's
conversation language while preserving their meaning and the label-to-choice-ID
mapping. Retain the native call association in existing evidence or source
references. If the capability is unavailable or unsuitable, ask the same question
in prose and keep the same wait. A recording failure does not authorize asking a
new, unrecorded question.

Match an immediate native result or a later reply's actual call ID and question
ID to that recorded question; recheck its digest before `process-answer`.
Preserve nonempty custom human text with its actual source and no invented
`choice_id`. An empty custom value does not mask a valid selected choice.
Otherwise map only an unambiguous selection to the original choice ID. Empty,
skipped, pending, stale, or ambiguous answers do not establish agreement. Update
source-linked decisions before dependent work. Native Spec/Plan approval cards
refer to the live approval target after the reviewed revision is shown; no new
discussion question is required in an approval stage.

Use the fixed readable layouts in [../templates/conversation.md](../templates/conversation.md):
concise bold labels, one point per bullet, tables for comparisons, and the exact
question or approval request in a separate final section. Omit empty optional
groups and routine recording narration. Keep complete provenance and digest
bindings in the one record; show relevant source links beside useful findings.
Carry the complete confirmed objective and acceptance through every stage.
Engineering effort is resolved through evidence gathering and concrete planning;
it does not reopen confirmed scope. Preserve requirements across list updates,
reentry, and worktree generations. A confirmed requirement changes only with
explicit actual user authority recorded in `scope_changes`, including its prior
digest, disposition, reason, and source.

Spec and Design are the same revision and approval stage. Use Spec in conversation
and retain the Design record heading and `process-design` operations. Follow
[../templates/spec.md](../templates/spec.md) for complete content and independent
builder gap review. New design content adds `current_impact`, `out_of_scope`, and
`failure_conditions`; its other sections derive from authoritative intent,
requirements, exploration, decisions, components, and verification.

Follow [../templates/plan.md](../templates/plan.md) for concrete tasks. New plan
items map `component_ids` to approved Spec components. `file_changes` covers each
owned path exactly once with action and responsibility. Structured `steps` name
an action, owned files, declared interfaces, and item-local verification IDs.
Checks contain item-local IDs, kind (`command` or `inspection`), requirement IDs,
targets, method, and expected result. Command checks include nonempty `argv`;
inspection targets are safe repository-relative paths. Check targets outside
ownership permit observation, not mutation. Named tests/assertions and concrete
expected results must resolve the behavior an implementer cannot choose alone.
Prepare/Implement/Verify/Review/Integrate remains an overview, not a task plan.
Existing stored design and plan envelopes remain readable and approvable without
rewriting their approved content or digest. New submissions use the current schema.

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
The complete requirement ledger remains the coverage anchor: a missing ID,
renamed ID, or omitted row does not itself change confirmed scope.

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
Do not reopen a confirmed inclusion because it is difficult, expensive, or can be
phased. Use phases to order dependencies while retaining the complete goal and
acceptance. Only the user's explicit recorded scope-change authority changes
confirmed scope; do not invent a default subset, prototype, cap, or budget.
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
report references in the one task record.

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
Review actual evidence and avoid agent turns or review cycles that add none.
Do not claim a capability or parallel execution that did not occur.
See [deepseek.md](deepseek.md) for native installation, context, and execution
boundaries.

Each item follows `pending -> implementing -> reviewing -> complete`. Failed
review returns it to `implementing`. A task reviewer returns separate
requirements and quality verdicts from actual diffs and evidence. Keep blocked reasons and next actions
separate. The coordinator inspects actual diffs and evidence. After the items
pass, independently review the full deliverable as an overall item. Reuse valid
evidence only when the approved design and relevant code remain unchanged.

### Complete plan and decision argument examples

These examples demonstrate argument nesting only. They assume an explicitly
synthetic fixture already contains confirmed `req-report`, an approved `report`
component owning `src/report.py`, and an answered `q-encoding` with choice `utf8`.
Replace every illustrative value with current state and actual authority. Never
copy a synthetic source reference into a real task. Do not submit a plan during
an outstanding question or decision outside its allowed stage.

`plan` has no top-level `id` or `acceptance`. Item `component_ids` and
`requirement_ids` name existing approved components and requirements. Step
`interfaces` use the item's exact declared strings, not shorthand function names.
Each check maps the requirements it verifies; every item requirement needs a
check and every declared interface needs an action.

<!-- process-plan-complete-example -->
```json
{
  "root": "/absolute/project",
  "task_id": "report-task",
  "actor": "coordinator",
  "expected_version": 12,
  "plan": {
    "shared_requirements": [],
    "dependencies": [],
    "review_focus": "Check exact report loading and error behavior.",
    "items": [
      {
        "id": "report-loader",
        "title": "Load the approved report format",
        "component_ids": [
          "report"
        ],
        "requirement_ids": [
          "req-report"
        ],
        "deliverables": [
          "A report loader with the approved input and failure behavior."
        ],
        "files": [
          "src/report.py"
        ],
        "file_changes": [
          {
            "path": "src/report.py",
            "action": "modify",
            "responsibility": "Load the approved UTF-8 JSON report."
          }
        ],
        "interfaces": [
          "load_report(path: Path) -> dict"
        ],
        "dependencies": [],
        "steps": [
          {
            "id": "load",
            "action": "Read the UTF-8 file and parse JSON while preserving JSONDecodeError.",
            "files": [
              "src/report.py"
            ],
            "interfaces": [
              "load_report(path: Path) -> dict"
            ],
            "verification_ids": [
              "loading"
            ]
          }
        ],
        "verification": [
          {
            "id": "loading",
            "kind": "inspection",
            "requirement_ids": [
              "req-report"
            ],
            "targets": [
              "src/report.py"
            ],
            "method": "Inspect UTF-8 reading, JSON decoding, and exception propagation.",
            "expected_result": "The function returns the parsed object and propagates JSONDecodeError."
          }
        ],
        "acceptance": [
          "Independent review accepts the mapped report behavior."
        ]
      }
    ]
  }
}
```

`confirmation_source` is nested inside `decision`, never beside it. A confirmed
choice must use the actual persisted question/answer and exact selected choice
when applicable. Custom answers do not acquire an invented choice ID. For a
proposed choice, use `status: proposed` and omit confirmation fields; actual
confirmation remains a separate human event.

<!-- process-decision-complete-example -->
```json
{
  "root": "/absolute/project",
  "task_id": "report-task",
  "actor": "coordinator",
  "expected_version": 8,
  "decision": {
    "id": "report-encoding",
    "title": "Report text encoding",
    "choice": "Use UTF-8.",
    "rationale": "The actual recorded answer selected UTF-8.",
    "scope": [
      "req-report"
    ],
    "status": "confirmed",
    "source": {
      "kind": "agent",
      "reference": "Illustrative agent proposal; replace with actual origin source."
    },
    "confirmation_source": {
      "kind": "user",
      "reference": "Synthetic documentation fixture answer; never use as real authority."
    },
    "question_id": "q-encoding",
    "choice_id": "utf8"
  }
}
```


## 3. Project paths and Git

```text
<project>/
  .task-workflow/                    # Task state and records
  .worktrees/<task-id>/              # Fixed development worktree
  .experiments/<experiment-id>/
    .snapshots/<scope-content-modes-key>/
      code/                         # Shared immutable selected code
    runs/<run-id>/
      snapshot.json                 # Points to shared code; per-run provenance
      ...                           # Mutable run outputs
      code/                         # Retained only for legacy per-run snapshots
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
hooks and signing. Integration requires a clean base by default. Set
`preserve_unrelated_dirty: true` only for an authorized integration that must
retain unrelated dirty tracked work. First call `integrate` as a dry run and
review its preservation manifest and `preservation_digest`. The real operation
requires the exact digest in `expected_preservation_digest` plus the same base
and task revisions. It preserves staged and unstaged tracked files without
stashing, resetting, forced checkout, or committing unrelated work. It checks
candidate paths and ancestors for collisions; unrelated untracked and ignored
trees outside that collision frontier remain outside the publication footprint.
After the candidate commit passes the preservation recheck, publication uses a
non-forcing fast-forward with Git autostash and overwrite-ignore disabled. A
changed base or preservation identity stops publication for reconciliation.

Verify the actual integrated revision before freezing a dependent formal Run.
Development checks bind evidence to the worktree revision
and may use an authorized managed resource, including a GPU, before merge.
Integration verification runs against the exact integrated commit after merge
and may also use an authorized managed resource, including a GPU. It defaults to
`source_mode: live_checkout`, which retains clean-current-main checks. For a
preservation-mode integration, use `source_mode: fixed_commit`. The optional
`expected_integration_commit` asserts the recorded commit; it is never an
arbitrary source selector. Both `integration-verify` and
`check-dispatch(kind=integration)` accept these selectors. The program binds the
check to the recorded commit, tree, design and approval, generation, and
integration token. It creates a program-owned detached checkout inside the
check evidence directory, verifies its exact Git identity and cleanliness, then
executes there outside shared/task write locks. After claim settlement and
receipt validation, it removes only the proven-owned unchanged checkout. If
unique content or uncertain references remain, it records `cleanup_pending`
and preserves the checkout; a claimed check is reconciled rather than replayed.
The fixed runner removes `PYTHONPATH` and `PYTHONHOME`, disables bytecode writes,
and rejects explicit command paths into mutable registered checkouts. An opaque
validator must itself inspect the bound source. Cancelling an unclaimed fixed
check removes only a proven-owned clean checkout; unexpected content remains
with `cleanup_pending`.

External `check-dispatch`
reserves and records the check, then returns exact `runner_argv`
for the private controller; it does not execute that external workload on the
harness host. Direct `verify` and `integration-verify` wrappers run their
program-pinned local runner. Formal Run startup validation uses the arguments,
resource, and controller path recorded in that Run. For each new formal Run,
freeze and validate its inputs, check references, then safely clean the owned
worktree before guarded dispatch. Check live cross-task, runtime, and environment
references and unique content before cleanup. A later approved revision
recreates the fixed worktree path from current main as a new generation; retain
earlier runs and evidence.

`run-prepare` freezes executable files directly from the recorded integrated
Git commit's tree. Its immutable preparation intent and Run snapshot retain the
exact matching integration verification proof, including check identity,
receipt digest, source mode, generation, and integration token. A preservation-
mode integration requires a passed `fixed_commit` check bound to its recorded
commit before freeze. Unrelated dirty checkout contents do not enter the frozen
Run code. Recovery retains the original proof from the immutable preparation
intent, even when a later check passes against the same source.

Each check has an immutable intent with its source revision, selected item or
Run, frozen arguments, pinned runtime, and optional managed resource. Its
recorded state distinguishes reserved, starting, running, uncertain, passed,
failed, stale, and cancelled checks. The pinned runner makes a durable claim
before execution and writes its receipt. Long validation runs outside shared
project and task write locks; reservation, admission, and receipt reconciliation
use short transactions. `check-reconcile` verifies the actual receipt and source
binding. A changed source remains recorded as stale. `check-cancel` applies only
when the program proves a local protocol-4 pre-admission claim belongs to the
same boot, host, and user and its matching runner is dead. Preserve the claim;
do not replay it. A partial or foreign claim needs actual terminal evidence.
Reconcile uncertain work before retry; never relaunch an existing check intent.
On direct verification wrappers, `detached` changes waiting behavior only; use
`check-dispatch` for the private resource controller.

For a current check or a current formal Run, a claim without an execution receipt
can be settled only from actual failure or cancellation evidence. Fresh status
returns the program-derived `settlement_targets`; copy the complete matching
check or Run target into an `execution-settlement` observation. Do not calculate
or invent its token, contract, runner-argument, or claim digests. The observation
records actual observer identity, method, host and time, a separate absolute raw
controller receipt path and SHA-256, evidence references, and terminal coverage
for the runner, every owned workload, and every process group. The raw receipt
and observation must remain available and unchanged. Pass the observation path
as `settlement_path` with nonempty evidence to `check-reconcile` or
`run-reconcile`; it is mutually exclusive with `receipt_path` and requires
coordinator authority. A dead runner alone does not prove its workloads or
process groups ended. Weak, partial, foreign, or possibly started claims require
controller-bound evidence covering the full owned execution. Settlement
records only `failed` or `cancelled`; it never creates a workload receipt,
return code, passed check, startup success, or artifact acceptance. Apply this
path only to current checks and lifecycle-contract-1 Runs using runtime protocol
4. Preserve retained legacy execution and reconciliation unchanged.

## 4. Resources and frozen execution

A resource represents execution capacity supplied under the user's private
conventions. The public program records identity, ownership, state, actual use
activity, retention holds, references, and release permission. Activity for
checks and Runs tracks pending, active, uncertain, and terminal outcomes against
actual capacity. A `resource-hold` records named future work or a persistent
retention choice; it does not consume execution capacity. A terminal use releases
only its own capacity. Retention and physical release remain separate, and
release still requires actual per-action authority. The public program does not
encode a provider's policy. Record who provided the resource separately from its
observed availability. Its derived
state is `available`, `in_use`, `releasable`, `released`, or `unknown`.

When a managed check or Run uses a resource, the program can retain it for the
matching task or experiment scope. `task-complete` and `experiment-complete`
resolve only the program-owned `until_work_resolved` hold whose sole reference
matches that exact scope. A manually created persistent hold stays retained
after scope closure until `resource-hold-resolve` records its actual outcome and
authority. A resource hold does not consume execution capacity.

Register resources with actual identity and ownership evidence. Reuse them only
after checking actual availability, compatibility, and all run references. A
planned reservation establishes a resource reference. Planning and preparation
can record a prospective reference or retention hold after identity, ownership,
release seal, and capability checks; they do not consume active execution
capacity. Actual start requires a fresh available observation and no
conflicting execution reported by the provider. The plugin imposes no blanket
active-run limit; actual provider availability and scheduling govern admission.
Resource eligibility is specific to that capacity. `resource-status` exposes
recorded release permission, a fresh available observation, and matching use
references. Queued/admitting, starting, running, and uncertain uses of the exact
resource still hold capacity. An `awaiting_artifacts` Run can stop holding
execution capacity only when committed exit evidence matches its actual execution
identity. Task or experiment
closure and artifact acceptance are separate outcomes, not substitutes for a
capacity observation; an unrelated open task does not hold this resource.

Finishing execution does not grant release permission or per-action authority.
A persistent retention choice is distinct from the owner's actual permission:
retain the resource under the applicable explicit release instruction. That
hold does not consume active execution capacity. Do not silently rewrite
`can_release` to represent a retention choice.
Apply the user's loaded private lifecycle policy as well as current eligibility.
A release-on-success policy can require whole-scope acceptance even when compute
capacity is already free. The public program does not encode that private policy.

If owner permission was recorded incorrectly, use the existing
`resource-observe` operation with both `can_release` and `authorization_source`.
The pair requires the actual source, current task and resource versions, the
current coordinator, recorded resource owner and matching user identity, plus
the normal fresh observation, capabilities, and evidence. A permission correction
is recorded in event history; it does not release capacity or authorize the
release action. The pair cannot change permission after a release intent is
sealed. Do not silently migrate an old flag or infer permission from availability.

Actual release still uses the exact release command, a fresh authorization
source, and the existing intent seal and receipt. Preserve active and uncertain
references. Reconcile an uncertain result against its actual receipt before any
retry; never repeat an already committed release. A status read has no
provisioning or release effect.
For compatibility, preserve task format 2 state, legacy Run and snapshot bytes,
and pinned runtime files until supported old execution and reconciliation are
quiescent. The retained 0.1.14 runner requires task format 2 when it admits old
work. After legacy admissions and uncertain outcomes settle, use the explicit
`lifecycle-upgrade` operation to transition task metadata from format 2 to 3.
As a current task next uses a resource, admission transitions that resource
only after retained legacy uses settle. Do not auto-upgrade active legacy tasks.
Current entrypoints enforce the supported contract. Documentation cannot fence
arbitrary obsolete clients; do not claim that a marker or short lock can do so.

An experiment has one research goal and may contain many frozen runs. Preserve
the complete task goal and confirmed acceptance across phases and later worktree
generations. A
code-only task can use verification runs without becoming a research experiment.
Changed code or arguments for the same goal creates a new run. Changed goals
create new experiments.

Freeze code, environment references, entrypoint, arguments, inputs, outputs,
and resource references before execution. Keep stable environments outside
removable worktrees. Verify actual imports when dependencies can resolve back
to development source. Preserve existing symbolic links and referenced targets.

### Selected snapshot and startup contract

New `run-prepare` submissions must provide `snapshot_scope`, `fixed_references`,
`validation_argv`, and `origin_checks`. Inspect actual entrypoint dependencies
before writing these values in the existing record. Carry material choices into
the existing Spec/Plan approval loop. Literal Git file/directory selectors define
`entrypoints`, `code`, `configs`, and `assets`; entrypoints must be exact selected
files. Include necessary local imports and runtime inputs. Exclude unrelated
subprojects explicitly. Selected unsupported Git objects fail; unrelated objects
outside the selected scope do not expand it. Export uses the selected raw Git
objects, not archive-attribute transformations.

Fixed references contain `id`, `role`, `path`, `identity`, `evidence`, and optional
`sha256`. The program freezes their normalized logical and resolved identities. File
references always capture their actual SHA-256; an optional supplied hash is
checked against it. Directory/provider identity is an actual project-validator
observation plus declared origin-file hashes, not automatic proof that every
directory byte is immutable.
The registered environment remains identified by `environment_id` and its
fingerprint. Project-local code belongs in the selected scope; a fixed-reference
label cannot make a mutable development checkout immutable.

Each `origin_checks` entry has `id`, `reference`, and a relative `path`.
`reference` is `code`, `environment`, or a fixed-reference ID. Each entrypoint
adds a required origin ID `entrypoint:<repository-relative-path>`; explicit IDs
must not collide with these. The combined required origin set must be nonempty.

This complete illustrative `run-prepare` argument envelope selects a report
command and its inspected inputs. Replace identities, paths, current version,
registered environment, and behavior with the actual authorized task values.
It is not authority to create or execute this run:

```json
{
  "root": "/absolute/project",
  "task_id": "report-task",
  "actor": "coordinator",
  "expected_version": 12,
  "run_id": "report-check",
  "environment_id": "runtime",
  "lockfiles": ["uv.lock"],
  "argv": ["python3", "tools/report.py"],
  "artifacts": ["report.json"],
  "dependency_declaration": "The inspected reporting imports use the registered environment and selected local modules.",
  "snapshot_scope": {
    "entrypoints": ["tools/report.py"],
    "code": ["src/reporting", "tools/validate_startup.py"],
    "configs": ["config/report.json", "uv.lock"],
    "assets": ["templates/report.txt"]
  },
  "fixed_references": [],
  "validation_argv": ["python3", "tools/validate_startup.py"],
  "origin_checks": [
    {"id": "reporting-module", "reference": "code", "path": "src/reporting/__init__.py"}
  ]
}
```

The validation argument array follows the main command rules: leading `python`
or `python3` resolves to the registered environment interpreter. Its working
directory is the immutable code root; brace placeholders are not supported.

The startup command must inspect the actual loaded imports and required runtime
configuration/assets, then write JSON to `TASK_WORKFLOW_STARTUP_REPORT`. Read the
nonce from `TASK_WORKFLOW_STARTUP_TOKEN`. The report shape is
`{"token":"<provided nonce>","origins":[{"id":"<required ID>","path":"<actual origin>"}],"references":[{"id":"<fixed reference ID>","identity":"<actual identity>"}]}`.
Report exactly the required origin and reference IDs. Include generated entrypoint
origin IDs. For the illustrative command above, a structurally complete report
looks like this; its nonce and observed paths must come from the actual startup:

```json
{
  "token": "<TASK_WORKFLOW_STARTUP_TOKEN value>",
  "origins": [
    {"id": "entrypoint:tools/report.py", "path": "/actual/frozen/code/tools/report.py"},
    {"id": "reporting-module", "path": "/actual/frozen/code/src/reporting/__init__.py"}
  ],
  "references": []
}
```

Do not substitute expected paths for observations. The pinned runner
validates the actual successful exit and report, nonce, coverage, paths, reference
identities, and digest before the main command. Validation uses the same environment
and working directory as the main workload. The runner rechecks code, environment,
and resource eligibility after startup validation before launching the workload.

Within an experiment, identical scope, file contents, and modes reuse immutable
code in `.snapshots`; the source commit remains separate per-run provenance.
Mutable outputs stay in each run directory. Scope or code changes produce a new
snapshot identity. Preserve existing snapshots and running inputs. Cleanup must
prove ownership and absence of remaining references; do not delete external or
uncertain content. Project verification that needs a pre-change baseline must
use the stable helper below with a recorded baseline revision. Ordinary `verify`
and `integration-verify` remain revision-bound commands on the live worktree or
base. Independent copied-baseline verification is the case that requires these
snapshot helpers. This does not authorize a formal Run integration bypass or
alter an already running supervisor.

```python
result = workflow.prepare_verification_snapshot(
    state, commit=recorded_baseline_commit,
    directory=Path(state["root"]) / ".experiments" / "verification"
        / state["task_id"] / "baselines" / baseline_id,
    environment_id=registered_environment_id, snapshot_scope=inspected_scope,
    fixed_references=recorded_fixed_references, validation_argv=startup_argv,
    origin_checks=required_origins, authorization_source=actual_source_reference,
)
if result["startup"]["status"] != "passed":
    raise RuntimeError("Baseline startup validation failed; inspect its receipt.")
baseline_code = Path(result["baseline"]["code"])
# Run the authorized numerical comparison from baseline_code only after this check.
```

The helper signature is `prepare_verification_snapshot(state, *, commit,
directory, environment_id, snapshot_scope, fixed_references, validation_argv,
origin_checks, authorization_source)`. The allowed output namespace is
`<state_root>/.experiments/verification/<task>/baselines/<baseline-id>`. It returns
`baseline` (including the immutable `code` path) and the actual `startup` receipt.
The caller must require `startup.status == "passed"` before numerical verification.
The baseline records purpose `development-verification`; it makes no integration
or formal Run approval claim. Preserve existing baseline inputs and receipts.

## Bind the main repository environment

All development worktrees and new formal Runs reuse one existing environment
bound to the project's main/base repository. The authoritative binding is
`.task-workflow/environment.json` under the existing project state root. Use
`environment-bind` once to record the existing environment path and its actual
authorization source. Pass the operation's standard mutation fields `path` and
`authorization_source`; discover the current schema for all other required
fields. The binding is project-wide, including across tasks and their worktrees.
Resolve aliases and symlinks to the same underlying environment before reuse.

Do not create or register an alternate environment for a task, worktree,
integration check, or Run. Resolve dependency conflicts through project
compatibility discussion. Preserve existing frozen Runs, snapshots, paths, and
environment references exactly as recorded; binding the main environment does
not rewrite historical execution evidence. Do not infer a host-specific
environment directory name.

Shared package caches remain outside task cleanup.

Record purpose, parent run, checkpoint reference when relevant, frozen snapshot,
resource identity, execution receipt, and artifact acceptance. The program pins
the workflow and runner runtime. Preserve referenced runtime files and stable
environments for existing execution. Later changes create a new run.

New lifecycle-scoped runs use execution protocol 4. Their immutable contract
binds the approved worktree generation and integrated commit to the frozen
inputs. The generation cleanup receipt also records successful startup
validation for each new Run. Preserve protocol 2 and 3 runs and their pinned
runtime and inputs; use their original supported execution contracts. Older backends must
not execute protocol 4 runs. Preserve legacy preparation intents and partial
files rather than rewriting them into the new shape. An unfinished legacy
preparation without a complete pinned runtime needs its retained original
preparation backend. Completed snapshot/event recovery preserves its original
contract. Existing execution receipts remain available through
their original runtime.

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
without launching or repeating the workload. If an unsettled current Run has no
workload receipt, use the separate terminal-observation settlement path above.
Preserve the frozen inputs, execution token, log identity, and claim after
interruption.

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
without forced discussion or phase progression. `presentation` specifies readable section layout and a separate final question.
`templates` links the required response, record, Spec, and plan structures as
applicable. Refresh context after a version conflict or
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

### Lock ownership and conservative recovery

Current locks use a complete regular-file claim at the existing lock pathname
and a persistent advisory `.guard` sibling. The owner record contains a unique claim token,
user ID, process ID, and host-instance identity; acquisition and cleanup also
check file identity. An existing guard file alone is not an active claim. Keep
it in place.

Under the advisory guard, automatic recovery is limited to a recognized complete
claim with a proven dead process on the same host instance, or this process's
exact retired claim after its critical section ended and cleanup failed. The
latter requires the in-memory retired token and file identity; a live active
claim cannot be treated as retired. Age alone does not establish abandonment.
Empty or unknown files, foreign-host claims, and legacy lock directories remain
blocked for manual inspection at a verified quiescent boundary. A missing or
unverifiable owner is not permission to remove a lock. Inspect actual process/workload ownership and the lock identity
before authorized recovery. Do not delete a live claim or a persistent guard.
There is no new lock-recovery API or timeout-based unlock rule.

## 6. Report and complete

Lead updates with a new result or next action. Include material verification,
output locations, and unresolved decisions. Explain unfamiliar terms on first
use, keep names stable, and explain rename mappings. Keep routine updates short
and avoid duplicate reports.
Routine progress and questions name the actual work or user decision. Omit
internal rule/skill citations, process apologies, and administrative narration.
Correct a wrong question directly; keep authority and verification details in
the task record. Honor higher-priority mandatory permission disclosures when
they actually apply.


Before large execution, state scope and stopping conditions. Review actual
results and required cleanup before declaring completion. Report integration,
execution, artifact acceptance, experiment closure, task closure, and resource
release as separate facts when they affect the conclusion.
