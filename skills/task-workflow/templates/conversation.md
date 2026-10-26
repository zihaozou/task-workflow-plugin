# Required conversation responses

The main skill defines the mandatory order. These structures specify required
content for each applicable stage. Use natural language and the user's language;
do not recite these headings. Persist English summaries with original source
references in the one program-generated record.

Read the fresh `dialogue_contract` before each related reply. Follow its
`applicability`, ordered `reply_fields`, `required_recording_steps`, `wait_for`,
`turn_exit`, `approval_target`, and `allowed_next_operations`. Direct status and
ordinary replies answer the current request and retain the existing wait target.
Preserve digests in program approval bindings; show readable revision titles to
the user without requiring long digests in conversation.

## First discussion reply

1. Restate the intended result and why, with inferences identified.
2. State relevant findings from actual context, their sources, and likely impact.
3. Invite corrections and ask the most important unresolved question, with its
   consequence.

Before sending: record intent, exploration, and the exact pending question.
Wait for that answer. Do not substitute an implementation proposal for finding
out what the user wants.

## Answer acknowledgement and next discussion turn

1. State what the answer settles and its consequence.
2. State new findings or corrected understanding that affect the next choice.
3. Ask the next recorded important question and explain its consequence, or
   present the next playback when understanding is coherent.

Before dependent work or a dependent question: record the actual answer source,
update requirements and decisions and their source links, then record the next
question. Explore and record missing facts first. Keep alternatives grounded in
actual consequences; no count of alternatives or discussion rounds is required.

## Playback

1. User requirements and confirmed choices, with sources.
2. Agent proposals and reasons, clearly still proposed.
3. Explicitly delegated choices, exact scope, and sources.
4. Remaining important unknowns and a request to correct or confirm this playback.

Before sending: record the playback confirmation question with
`purpose: playback_confirmation`. Ordinary clarification questions use
`purpose: clarification` or omit it for the compatibility default. The program
uses this field to select the required playback response order and wait target;
question identifiers do not encode purpose. After the answer:
record its source and corrected requirements/decisions before `process-playback`.
Wait for actual confirmation. Resume discussion when an important gap remains.

## Reviewed design and approval

1. Present the actual coherent design and its exact readable revision and title.
2. State the independent gap-review outcome and meaningful effects.
3. Ask for approval of that exact design for planning.

Before sending: record the design and independent review for the same digest.
Wait for user approval. Record its actual source with `process-design-approve`
before preparing the implementation plan. New important reviewer questions return
to discussion before dependent work.

## Plan approval

1. Show the exact plan revision and title and approved design it implements.
2. Show work items, ownership, dependencies, verification, independent reviews,
   integration scope, and recovery.
3. Ask for approval of that exact plan for implementation.

Before sending: record the plan. Wait for approval. Record its actual source with
`process-plan-approve` before implementation. Preserve separate integration
permission and any limits in the approval.

## Execution, review, and delivery

1. State the new observed result and current item or task state.
2. Give material verification and actual requirements/quality/overall verdicts.
3. State the next allowed action or actual missing decision and its consequence.

Record evidence and transitions before claiming them. Distinguish a worker claim
from inspected evidence and review acceptance. Continue authorized routine work.
A status-only request gets the requested status without forced phase progression.

## Reentry

State the new evidence, affected choice, and consequence. Record `process-reenter`
and the exact question before asking it. Wait for the answer, synchronize sources,
and revise only affected requirements, decisions, design, plan, and approvals.
Preserve unaffected facts and evidence. A changed revision needs its own approval.
