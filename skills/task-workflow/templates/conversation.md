# Conversation structures

Use these as content guides, not labels to recite to the user. Ask one useful question
at a time during design discussion. The answer can reveal another question,
return the task to exploration, or make the design ready for review. There is
no question quota. An alternate path belongs in discussion only when it has a
real consequence for this task.

## Exploration update

> I found **[fact]** in **[source or revision]**. It affects **[requirement or
> decision]** because **[consequence]**. I will **[next exploration action]**.

Keep facts separate from interpretations. Record unknowns and evidence gaps.

## One-question discussion

> **Decision needed:** [one open question, or one multiple-choice question with
> concrete choices].
>
> **Why it matters:** [effect on behavior, scope, verification, or recovery].
>
> **Known so far:** [confirmed facts and requirements with source references].
>
> **My proposal, if useful:** [proposal and rationale, explicitly labeled].

Do not list speculative choices to fill a quota. A question about an important
choice must explain its consequence. The answer is evidence for that choice;
it does not approve unseen design details.

## Playback before a design draft

> **Confirmed from your messages:** [requirements and choices, each with its
> source reference].
>
> **Choices you delegated:** [scope of each delegation and source reference].
>
> **My proposals:** [unconfirmed choices and rationale].
>
> **Still open:** [one next question, or "None for this design version."]

When the user corrects the playback, update the record and continue discussion.
When new facts change a settled consequence, return to the relevant question.

## Design review and approval

The design draft has a revision and source references. Ask an independent
reviewer to identify gaps against confirmed requirements and delegated choice
scope. Revise and review again when material gaps remain. Present the reviewed
design version and its meaningful effects to the user. Ask for approval of that
specific version. Record the user-visible approval source and approved revision.

Example: "The reviewed design is revision D3 at [reference]. It selects
[behavior] and requires [scope]. Do you approve D3 for implementation planning?"

## Plan approval

Create the implementation plan only after design approval. Link the plan to
the approved design revision. Show owned work, verification, review, integration,
and recovery. Ask the user to approve that plan revision for implementation.
Record the approval source, plan revision, and any limits in the approval.

Example: "Plan P2 implements approved design D3 through [work items]. It will
verify [outcomes]. Do you approve P2?"

## Reentry when an important choice changes

> The new fact at [reference] changes [confirmed design or delegated scope].
> The affected choice is [choice]. I will return to discussion before taking
> the dependent action. [One useful question with consequence.]

Use this generic authority check at every phase: if the next action depends on
an important choice that the confirmed design and explicit delegation do not
settle, ask the user and return to discussion. Do not infer approval of new
details from a broad "go ahead." Routine implementation within approved scope
continues without a new approval.
