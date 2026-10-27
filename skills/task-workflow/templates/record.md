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

The user's objective, completion contract, task scope, original enrollment
source, and any later scope changes. Distinguish the user's words from the
agent's interpretation.

## Exploration

Observed facts, source locations, checks performed, unresolved unknowns, and
evidence gaps. Each fact has a source reference and observation date or revision
when it can change.

## Confirmed requirements

One row per requirement: identifier, text, kind (`scope`, `constraint`, or
`acceptance`), source reference, status (`proposed` or `confirmed`), user
confirmation source when confirmed, and acceptance evidence. User requirements
must not be relabeled as agent proposals. An agent suggestion must not be
relabeled as a user requirement.

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
Include applicable integration/recovery and user plan-approval source. Lifecycle
phase names alone do not describe implementation tasks. If the design changes materially, return to discussion and revise
the dependent plan.

## Execution and review

For each item, record the implementation state, worker brief reference, change
revision, tests and evidence, separate requirements and quality verdicts,
remediation, and final overall-review verdict. A worker claim alone is not a
verdict. Reviewers inspect actual changes and evidence.

## Experiments and runs

Research goal, experiment and frozen run identities, code and environment
revisions, inputs, resource identity and ownership, execution receipt,
artifact checks, acceptance, and closure. Include the inspected entrypoint dependency
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
cleanup evidence. Distinguish integration, run, resource, and task closure.

## Decision history

Chronological references to important questions, answers, playback, proposals,
delegations, design and plan approvals, reentries, and supersessions. Each entry
names its source and affected revision. Link answers to their questions and
decisions to the answers or explicit delegation that supports them. Record
questions before sending and synchronize answers and affected sources before
dependent work. Preserve prior decisions and superseded approvals for audit.
