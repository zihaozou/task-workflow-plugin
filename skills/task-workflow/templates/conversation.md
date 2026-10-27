# Required conversation layouts

Use these stage layouts with the mandatory sequence in the main skill. Use the
user's language in conversation and English summaries in the one task record.
Bold labels group content; bullets state one finding, choice, action, or result.
Use a table when relationships are easier to compare. Put the exact recorded
question or approval request in its own final section or native question card. Omit empty optional groups
and routine statements about recording, provenance, or workflow mechanics.
Show useful source links beside relevant findings. Keep machine identifiers,
state versions, and digests in the record. Readable revision names remain visible.
Start directly with the current stage's content. Do not preface it by announcing
that a template or workflow will be used. Render all display headings and card
labels in the current conversation language. The English labels below identify
semantic roles; keep the source templates and persisted summaries in English.
Use the matching section, not the full set of layouts. A direct status reply
answers status and keeps the existing wait; it does not repeat a full Spec/Plan.
Routine replies name the actual work or user decision. Omit internal rule/skill
citations, process apologies, and administrative narration. Correct a wrong
question directly rather than attributing it to the skill. Keep authority and
checks in the record. Preserve a higher-priority mandatory permission disclosure
when it actually applies.


After the required recording succeeds, use the host's available, eligible native
question capability (`ask_user_question` on DeepSeek Harness) for the final
Question, Confirm, or Approve action.
The prose supplies stage context; the native card supplies the question and real
choices. Do not duplicate a displayed card as another plain-text question.
The question text in these examples illustrates card content. If the native
capability is unavailable or unsuitable, use that same recorded question in the
final prose section. Preserve its exact ID and digest; do not invent choices.
Match the native call and question identity before recording an answer. Nonempty custom
text overrides selected labels; an empty, skipped, or pending response keeps the
wait and does not approve anything. Spec/Plan cards bind to the current approval
target after the exact reviewed revision is shown.


Read the fresh `dialogue_contract` before each related reply. Follow its
`applicability`, `reply_fields`, `presentation`, `required_recording_steps`,
`wait_for`, `turn_exit`, `approval_target`, and `allowed_next_operations` within
its `operation_scope`. Other operations follow the current schema, actual guards,
and existing user authority. Direct status replies preserve the current wait.

Examples below illustrate format only. Their JSON report behavior is not a
requirement for another task. Replace every detail with actual task evidence.
Preserve the complete confirmed objective and acceptance through every stage.
Discuss real semantic choices and factual unknowns; do not repeatedly offer a
smaller subset, prototype, or deferment because confirmed work is difficult or
costly. Phase work to handle dependencies while keeping full acceptance visible.
Change scope only when the user asks or evidence establishes a material
constraint; record actual user authority before changing confirmed scope.

## First discussion reply

Required order: **Goal**, **What I found**, relevant **My proposal** when needed,
then **Question**. State intent and reason, observed behavior and impact, then
why the unresolved choice matters and its exact recorded question. Invite
correction without adding another question.

> **Goal**
> - Add JSON output for another script while preserving CSV behavior.
>
> **What I found**
> - `report.py` writes `report.csv` with `name` and `count` columns.
> - There is no format option, so JSON needs a new command interface.
>
> **Question**
> The interface determines how the other script receives results. Please correct
> any misunderstanding. How should it request and receive JSON?

Before sending: record intent, exploration, and question. Wait for its answer.

## Answer acknowledgement and discussion

Required order: **Settled**, relevant **New findings**, relevant **My proposal**,
then **Question**. Omit groups with no new content.

> **Settled**
> - `--format json` writes to stdout; the existing command keeps writing CSV.
>
> **My proposal**
> - Use one JSON array with one object per row, so scripts read one document.
>
> **Question**
> Does that array structure fit the receiving script?

Record the answer and update source-linked requirements/decisions before the
next dependent question or action. Preserve prior confirmed requirements across
updates; omission or an ID rewrite does not remove them. Record the next question
before sending it. Explore factual gaps first. No question count or alternative
count is required.

## Playback

Required order: **Your requirements and confirmed choices**, pending **My
proposals**, explicit **Choices you delegated**, unresolved **Open questions**,
then **Confirm**. Omit empty optional groups. A confirmed agent proposal belongs
with confirmed choices; preserve its agent origin and user confirmation in state.

> **Your requirements and confirmed choices**
> - Select JSON with `--format json` and write it to stdout.
> - Keep the existing CSV output and column names.
>
> **My proposals**
> - Use one array containing one object per row.
>
> **Confirm**
> Does this description match what you want?

Record the confirmation question with `purpose: playback_confirmation` before
sending. Clarification questions use `purpose: clarification`, the default when
omitted. Purpose does not depend on a question's identifier. Wait for the actual
answer, update affected requirement/decision sources, then record confirmed
`process-playback`. Continue discussion if an important choice remains open.

## Spec and approval

Use **Spec Dn - title** and the sections in [spec.md](spec.md). Show the actual
reviewed content, grouped under meaningful labels, followed by **Review** and
**Approve**. Keep its digest bound in program state. A link alone does not show
unseen behavior or decisions for approval.

> **Spec D2 - JSON report output**
>
> **Required behavior**
> - `--format json` writes one array of report rows to stdout.
> - The existing command continues writing `report.csv`.
>
> **Acceptance**
> | Condition | Expected result |
> | --- | --- |
> | JSON selected | Parsed rows use `name` and `count`. |
> | Existing command | CSV content remains unchanged. |
>
> **Review**
> - The independent reviewer found no remaining material gap in D2.
>
> **Approve**
> Do you approve Spec D2 for implementation planning?

This excerpt illustrates layout; an actual approval reply includes all material
Spec sections. Record the Spec and independent review before asking. Wait for
actual approval and record it before planning. New important gaps return to
discussion before dependent work.

## Plan and approval

Use **Plan Pn - title**, its approved Spec reference, **File responsibilities**,
**Tasks**, **Verification and review**, applicable **Integration and recovery**,
then **Approve**. Follow [plan.md](plan.md) for concrete task content and example.
Use meaningful component names in the reply. Keep internal component IDs and
serialized command argument arrays in the record. Present readable executable
commands beside each check's expected result in the task or verification table;
do not append a second dump of the same command metadata. Include a compact
product-data JSON example when its shape affects the design. Keep all material
behavior, decisions, and tasks visible; approval cannot rely on a link alone.
Lifecycle phase names alone are insufficient work items. Record the plan before
showing it. Wait for approval and record it before implementation.

## Execution, review, and delivery

Use **Result**, **Checks**, relevant **Needs attention**, then **Next**.

> **Result**
> - JSON rows now use the existing report column names.
>
> **Checks**
> | Check | Outcome |
> | --- | --- |
> | JSON output parses as an array | Passed |
> | Default CSV content unchanged | Passed |
>
> **Next**
> - Independent item review is pending.

Record evidence and actual transitions before reporting them. A worker claim
alone does not establish acceptance. Compare results with the complete confirmed
requirement ledger and completion contract. Reviewers must identify omitted
confirmed behavior even when it is difficult or expensive. Distinguish
requirements, quality, and overall verdicts where relevant. Continue routine
authorized work.

## Goal-preserving examples

**Complete goal, hard requirement**

> The user confirmed a complete importer, including support for a legacy text
> encoding. Later investigation shows that encoding support needs more work.
> Investigate the actual encoding behavior, dependencies, and acceptance checks;
> plan the complete importer. Ask about scope only if evidence shows a real
> compatibility or permission constraint that changes the confirmed result.

Incorrect: repeatedly ask to defer legacy encoding, deliver a prototype, or
charge an invented per-operation budget because implementation is difficult.

**Gap found in review**

> A Spec omits the confirmed legacy encoding requirement. The independent reviewer
> flags the missing requirement-to-behavior and acceptance mapping. Revise the
> Spec and plan before approval, unless the user explicitly changes scope and
> the actual authority is recorded.

## Status and reentry

A direct status reply uses **Status** and relevant **Next**. State actual progress
and an existing pending decision without repeating it as a new question. Preserve
the wait target and stage.

For reentry, use **New finding**, **Impact**, then **Question**. Record the evidence,
`process-reenter`, and question before asking. Wait for its answer, synchronize
sources, and revise affected design/plan approvals while preserving other evidence.
