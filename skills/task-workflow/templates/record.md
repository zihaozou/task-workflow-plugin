# Task record section contract

The program generates exactly one `record.md` for a task. Preserve these
section names and order. Program state and events are authoritative for guards;
this Markdown is the readable account of the same task. Use explicit source and
revision references. Leave a section with a concise "Pending" entry until the
relevant phase starts. Do not invent approval for legacy tasks.

## Current state

Task identity, protocol version, current phase, state version, blocked reason,
next action, current approved design and plan revisions, and session binding
when verified. Include the current dialogue stage, exact pending question and
its source/digest and explicit purpose (`clarification` or
`playback_confirmation`), missing records, required next recording steps, and wait or
approval target when present in the program contract. A missing protocol version means legacy state, not implicit
upgrade. State a pending user action only when one is actually required.

## Intent

The user's complete objective, completion contract, and original enrollment
source. Distinguish user-confirmed scope from agent interpretation. Carry the
full completion contract through every revision and worktree generation. Record
any authorized scope change with its actual user source and affected
requirements; implementation cost or complexity alone is not a scope change.

## Exploration

Observed facts, source locations, checks performed, unresolved unknowns, and
evidence gaps. Include feasibility question, exact inputs, actual versions,
procedure, pass/refute criterion, observed result, and retained output. Record
relevant performance/cost/reuse assumptions and evidence. Each fact has a source reference and observation date or revision
when it can change.

## Confirmed requirements

One row per requirement: identifier, text, kind (`scope`, `constraint`, or
`acceptance`), source reference, status (`proposed` or `confirmed`), user
confirmation source when confirmed, and acceptance evidence. Keep the confirmed
requirement ledger source-backed and complete across reentry and requirement
updates. Do not silently remove, rename, demote, or replace a confirmed item.
Each authorized removal, replacement, revision, or demotion records the prior
requirement digest, disposition, reason, and actual user authorization in
`scope_changes` with `requirement_id`, `previous_digest`, `action`, `reason`, and
`authorization_source`; `replacement_ids` is required only for replacement.
Replacement requirements retain their actual confirmation sources. User
requirements must not be relabeled as agent proposals. An agent
suggestion must not be relabeled as a user requirement.

## Sourced decisions

One row per important choice: identifier, title, choice, source reference,
status (`proposed`, `confirmed`, `delegated`, or `rejected`), rationale, scope,
confirmation source or delegation identifier, and affected design revision.
Include the precise scope of any delegated choice. A source
points to an actual user-visible message, program event, or reviewed revision.

## Design

Render the Spec inside this Design section using [spec.md](spec.md). Spec and
Design name the same revision. Include intent/success, scope, current behavior
and impact, required behavior, decisions and authority, constraints/delegation,
acceptance, failure conditions, and actual open questions. Show meaningful
subheadings, grouped bullets, and acceptance tables. Preserve authoritative
references, component interfaces, recovery, independent builder gap-review result,
and user approval source. Keep reviewed draft
and approved revision distinct. Approval covers the revision presented.

## Implementation plan

Use [plan.md](plan.md). Render the revision, approved Spec reference, file
responsibilities, and concrete task blocks. Each block includes component and
requirement mappings, owned file actions/responsibilities, interface declarations,
dependencies, ordered action steps, named tests/assertions or inspection criteria,
verification commands/targets and expected results, acceptance, and review focus.
Include a coverage map from every confirmed acceptance requirement to concrete
tasks and checks, including difficult or expensive requirements. Phases may
order dependencies while preserving the full goal and acceptance. Include
applicable integration/recovery and user plan-approval source. Lifecycle phase
names alone do not describe implementation tasks. If the design changes materially, return to discussion and revise
the dependent plan.

## Execution and review

For each item, record the implementation state, worker brief reference, change
revision, tests and evidence, separate requirements and quality verdicts,
remediation, ordered independent requirements/quality verdicts and main acceptance
(or the retained historical overall-review verdict). Record worker assignments,
actual native activation identity, terminal outcome and cleanup, and pending
waits. Record native goal capability/request and exact observed receipt; absence
is explicit, never an invented invocation. For every worktree generation,
record its base revision, worktree identity, accepted evidence, integration and
verification binding, cleanup intent and receipt, and links to dependent Runs.
Preserve old generation and run evidence when a later approved revision creates
a new generation. A worker claim alone is not a verdict. Reviewers inspect actual
changes and evidence.

## Experiments and runs

Research goal, experiment and frozen run identities, code and environment
revisions, inputs, resource identity and ownership, actual resource-use activity,
retention holds, execution receipt, artifact checks, acceptance, and closure.
Include the inspected entrypoint dependency
closure, inclusion paths for code/configuration/assets, excluded unrelated scope,
fixed external identities, and their design/plan confirmation sources. Record the
selected shared snapshot identity, per-run source provenance, startup validation
command, required origin checks, validated report/exit evidence, mutable output
location, and ownership/reference checks for cleanup. Keep each run immutable
after freeze. Preserve old snapshots and active inputs.
Code-only verification need not create a research experiment.

## Delivery

Integrated revision, integration authorization source, final verification,
accepted artifacts, user-facing result, material limitations, and required
cleanup evidence. Show evidence for the complete confirmed completion contract.
For formal runs, record successful worktree cleanup and the matching cleanup
receipt before dispatch. Distinguish integration, run, resource, and task closure.

## Decision history

Chronological references to important questions, answers, playback, proposals,
delegations, design and plan approvals, reentries, and supersessions. Each entry
names its source and affected revision. Link answers to their questions and
decisions to the answers or explicit delegation that supports them. Record
questions before sending and synchronize answers and affected sources before
dependent work. Preserve prior decisions and superseded approvals for audit.
