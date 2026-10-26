# Phase contracts

For each applicable phase, check INPUT before action, follow CONVERSATION in
order, use the program operation in WRITE, honor WAIT, meet EXIT before advancing,
and pass RETURN to the next phase. The main skill contains the mandatory sequence.
Use the bold stage labels, grouped bullets/tables, and separate final question
in [conversation.md](conversation.md). Omit empty optional presentation groups.
A direct status or ordinary reply does not advance a phase. The live operation
schema is the authority for exact arguments and guards. Every mutation uses the current task version and actor.

## Source references and version chain

Use a source object with a kind and a reference. Distinguish a `user` message,
an `agent` proposal, and observed `evidence`; label an inference in the written
summary and cite the facts that support it. A user-request reference identifies
the actual request. A confirmation or approval reference identifies the actual
user-visible answer and the revision presented. A source reference alone is
never a claim of approval. Preserve design and plan digests through review,
approval, implementation, and final review.

## Intent

- INPUT: A clear substantive action request or explicit invocation, correct
  project and task identity, and enrollment authority.
- CONVERSATION: In the first discussion reply, state intent and why, then actual
  findings and impact, then one important question with its consequence. Invite
  corrections. Inspect project context before this substantive reply.
- WRITE: `process-intent` with goal, why, success criteria, and request source.
- WAIT: The recorded first question must receive an actual answer.
- EXIT: Intent and source are recorded without adding unasked-for scope.
- RETURN: Objective and criteria for exploration.

## Exploration

- INPUT: Recorded intent and project access.
- CONVERSATION: Report observed behavior, evidence, and meaningful unknowns.
- WRITE: `process-exploration` with current behavior, evidence, and unknowns.
- WAIT: Record the next question before sending it; wait for its answer.
- EXIT: Enough facts to ask the next useful design question or explain which
  evidence is still needed.
- RETURN: Fact references, uncertainties, and consequences for discussion.

## Multi-round discussion

- INPUT: Exploration facts and a real unresolved important choice.
- CONVERSATION: Acknowledge what the previous answer settles and its consequence.
  Record it and update source-linked requirements/decisions before any dependent
  question or action. Report new findings, then ask one recorded question with
  its consequence. Explore further if it exposes a factual gap. There is
  no required number of questions or alternative paths.
- WRITE: `process-question`, `process-answer`, `process-requirements`, and
  `process-decision` as evidence becomes available. Source each answer. Mark
  agent proposals as proposed; mark user-confirmed choices as confirmed; mark
  delegated choices with their explicit scope and source. Use
  `process-playback` with the user's confirmation source after presenting
  user requirements and confirmed choices, agent proposals, delegated choices,
  and remaining unknowns in that order. Record the confirmation question with
  `purpose: playback_confirmation` before sending; use `clarification` or the
  omitted compatibility default for clarification questions; record its answer and updated sources before confirmed playback.
- WAIT: The pending question or exact playback needs its actual user answer.
- EXIT: No important unresolved choice blocks a coherent design draft; the
  playback has an actual confirmation source.
- RETURN: Confirmed requirements, sourced decisions, delegated scope, and open
  assumptions for design.

## Design draft and independent gap review

- INPUT: Confirmed playback, requirements, decisions, and exploration evidence.
- CONVERSATION: Present the actual Spec (Design) revision using [spec.md](spec.md):
  intent/success, scope, current behavior/impact, required behavior, decisions and
  authority, constraints/delegation, acceptance, failure conditions, and actual
  open questions. Group content under meaningful bold labels.
- WRITE: `process-design`, then `process-design-review` with the design digest,
  independent verdict, notes, and evidence. The builder gap review identifies
  important guesses that would prevent a concrete plan. Revise and review
  material gaps against the exact current digest.
- WAIT: Await the independent review. Bring new important unknowns back into
  discussion before dependent work.
- EXIT: An independent gap review accepts the same design digest that will be
  shown to the user.
- RETURN: Reviewed design digest, review evidence, and remaining assumptions.

## User design approval

- INPUT: Reviewed design digest and user-visible design revision.
- CONVERSATION: Ask for approval of that exact version and its meaningful
  effects. State any unconfirmed proposal that remains.
- WRITE: `process-design-approve` with design digest and actual user approval
  source.
- WAIT: Actual user approval of the exact shown revision, bound to its recorded digest.
- EXIT: Approval applies to the reviewed design digest; record it before planning.
- RETURN: Approved design digest and authority scope for planning.

## Implementation plan and user plan approval

- INPUT: Approved design digest and mapped requirements.
- CONVERSATION: Use [plan.md](plan.md) for file responsibilities and concrete
  tasks: owned paths, exact interfaces, ordered actions, named checks/assertions,
  verification commands or inspection targets, expected results, dependencies,
  independent reviews, and applicable integration/recovery. Ask for approval in
  a separate final section. Lifecycle labels alone are insufficient tasks.
- WRITE: `process-plan` with shared requirements, dependencies, review focus,
  and item details; then `process-plan-approve` with plan digest and actual
  user approval source.
- WAIT: Actual user approval of the exact shown plan revision, bound to its recorded digest.
- EXIT: Plan approval applies to the current plan digest linked to the
  approved design.
- RETURN: Approved plan digest, item briefs, and acceptance criteria.

## Delegated implementation and item review

- INPUT: Approved plan and prepared owned worktree.
- CONVERSATION: Give each implementer a bounded brief and report a material
  deviation or blocked decision promptly.
- WRITE: Record item state, brief reference, change revision, test evidence,
  separate requirements verdict, separate quality verdict, and remediation in
  `Execution and review` through current program operations.
- WAIT: Await worker evidence and independent verdicts. A new important unknown
  outside approved scope requires recorded reentry and a user answer.
- EXIT: Every item passes both reviews on its current change revision.
- RETURN: Complete item evidence and diff references for overall review.

## Overall review and integration

- INPUT: Passing item verdicts, complete diff, approved design and plan.
- CONVERSATION: Report cross-item findings and the integration action's scope.
- WRITE: Record the independent overall verdict. Use guarded integration only
  with its separate authorization source. Verify the integrated revision.
- WAIT: Await the overall verdict and any missing integration authorization.
- EXIT: Overall review passes and required integration is accepted and proven.
- RETURN: Integrated revision and verification for any dependent runs.

## Optional experiments and delivery

- INPUT: Approved experiment purpose, frozen inputs, integrated revision when
  required, and explicit execution/resource authority.
- CONVERSATION: State run scope and stopping conditions. Report actual result,
  artifact acceptance, and material limits.
- WRITE: Record experiment and immutable run identities, resource ownership,
  execution receipt, artifact evidence, acceptance, and closure in `Experiments
  and runs`; record final outcome and cleanup in `Delivery`.
- WAIT: Await actual receipts, artifact review, and any missing user authority.
- EXIT: Required runs and artifacts are accepted, remaining references are
  resolved, and the delivery contract is met.
- RETURN: User-facing result with paths, verification, and material limits.

## Reentry and legacy tasks

When a new important choice exceeds confirmed design or delegated scope, use
`process-reenter` with one question and a reason. Return to discussion, update
the design and plan versions when affected, and obtain new approvals for the
changed versions. Existing legacy tasks keep their recorded state. Use guarded
`process-upgrade` only with actual authorization; do not synthesize historical
questions, playback, or approvals. Existing resource and run evidence stays
unchanged. Preserve unaffected facts and evidence. Mark affected approvals stale
when their revision changes; do not reconstruct source history.
