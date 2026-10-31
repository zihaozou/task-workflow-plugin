# Reusable workflow templates

Follow the mandatory conversation sequence in the main skill. These required
phase structures support its response order, recording boundaries, waits, and
exit conditions. Use the worker structures to prepare focused briefs. The workflow program owns the canonical task state and generates one
`record.md` per task. Update that record through the current program interface;
these templates do not create parallel task records.

| Template | Use |
| --- | --- |
| [phases.md](phases.md) | Inputs, conversation, writes, exit checks, and handoffs for each phase. |
| [conversation.md](conversation.md) | Required response order, recording boundaries, waits, approvals, and reentry. |
| [spec.md](spec.md) | Complete Spec (Design) sections and independent builder gap review. |
| [plan.md](plan.md) | Concrete file responsibilities, interfaces, actions, checks, and expected outcomes. |
| [record.md](record.md) | Fixed section contract for the generated task record. |
| [worker-briefs.md](worker-briefs.md) | Coordinator, explorer, design reviewer, implementer, independent requirements/quality reviewers, and main acceptance briefs. |
| [worker-reports.md](worker-reports.md) | Evidence-based return formats for each worker role. |

Use actual message, file revision, program event, and artifact references. A
source reference should let a reader identify the exact user-visible message or
revision. Do not substitute a paraphrase for a source. Preserve source language
in the referenced conversation; write the task record and worker material in
English. A proposal remains a proposal until the user confirms it or explicitly
delegates the choice. An approval applies to the version the user saw.

These are original Task Workflow adaptations informed by the
[Superpowers brainstorming skill](https://github.com/obra/superpowers/blob/main/skills/brainstorming/SKILL.md),
[builder check](https://github.com/obra/superpowers/blob/main/skills/brainstorming/builder-check-prompt.md),
and [writing plans](https://github.com/obra/superpowers/blob/main/skills/writing-plans/SKILL.md).
Superpowers is licensed under MIT. The templates use original Task Workflow
wording and preserve this plugin's existing approval and one-record model.
