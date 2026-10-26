# Phase contracts

For each phase, check INPUT before action, follow CONVERSATION, use the program
operation in WRITE, meet EXIT before advancing, and pass RETURN to the next
phase. The live operation schema is the authority for exact arguments and
guards. Every mutation uses the current task version and actor.

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
- CONVERSATION: State the objective and intended completion in plain language.
- WRITE: `process-intent` with goal, why, success criteria, and request source.
- EXIT: Intent and source are recorded without adding unasked-for scope.
- RETURN: Objective and criteria for exploration.

## Exploration

- INPUT: Recorded intent and project access.
- CONVERSATION: Report observed behavior, evidence, and meaningful unknowns.
- WRITE: `process-exploration` with current behavior, evidence, and unknowns.
- EXIT: Enough facts to ask the next useful design question or explain which
  evidence is still needed.
- RETURN: Fact references, uncertainties, and consequences for discussion.

## Multi-round discussion

- INPUT: Exploration facts and a real unresolved important choice.
- CONVERSATION: Ask one open or multiple-choice question with its consequence.
  Build on the answer. Explore further if it exposes a factual gap. There is
  no required number of questions or alternative paths.
- WRITE: `process-question`, `process-answer`, `process-requirements`, and
  `process-decision` as evidence becomes available. Source each answer. Mark
  agent proposals as proposed; mark user-confirmed choices as confirmed; mark
  delegated choices with their explicit scope and source. Use
  `process-playback` with the user's confirmation source after presenting
  confirmed requirements, proposals, and delegated choices separately.
- EXIT: No important unresolved choice blocks a coherent design draft; the
  playback has an actual confirmation source.
- RETURN: Confirmed requirements, sourced decisions, delegated scope, and open
  assumptions for design.

## Design draft and independent gap review

- INPUT: Confirmed playback, requirements, decisions, and exploration evidence.
- CONVERSATION: Explain behavior, components, interfaces, impact, verification,
  assumptions, and unresolved choices. Present the actual revision reviewed.
- WRITE: `process-design`, then `process-design-review` with the design digest,
  independent verdict, notes, and evidence. Revise and review material gaps.
- EXIT: An independent gap review accepts the same design digest that will be
  shown to the user.
- RETURN: Reviewed design digest, review evidence, and remaining assumptions.

## User design approval

- INPUT: Reviewed design digest and user-visible design revision.
- CONVERSATION: Ask for approval of that exact version and its meaningful
  effects. State any unconfirmed proposal that remains.
- WRITE: `process-design-approve` with design digest and actual user approval
  source.
- EXIT: Approval applies to the reviewed design digest.
- RETURN: Approved design digest and authority scope for planning.

## Implementation plan and user plan approval

- INPUT: Approved design digest and mapped requirements.
- CONVERSATION: Present work items, ownership, dependencies, verification,
  separate review, integration, and recovery. Ask for approval of the plan
  version the user saw.
- WRITE: `process-plan` with shared requirements, dependencies, review focus,
  and item details; then `process-plan-approve` with plan digest and actual
  user approval source.
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
- EXIT: Every item passes both reviews on its current change revision.
- RETURN: Complete item evidence and diff references for overall review.

## Overall review and integration

- INPUT: Passing item verdicts, complete diff, approved design and plan.
- CONVERSATION: Report cross-item findings and the integration action's scope.
- WRITE: Record the independent overall verdict. Use guarded integration only
  with its separate authorization source. Verify the integrated revision.
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
unchanged.
