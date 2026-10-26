# Reusable workflow templates

Use these structures to conduct the conversation and to prepare focused worker
briefs. The workflow program owns the canonical task state and generates one
`record.md` per task. Update that record through the current program interface;
these templates do not create parallel task records.

| Template | Use |
| --- | --- |
| [phases.md](phases.md) | Inputs, conversation, writes, exit checks, and handoffs for each phase. |
| [conversation.md](conversation.md) | Exploration, one-question discussion, playback, approvals, and reentry. |
| [record.md](record.md) | Fixed section contract for the generated task record. |
| [worker-briefs.md](worker-briefs.md) | Coordinator, explorer, design reviewer, implementer, task reviewers, and overall reviewer briefs. |
| [worker-reports.md](worker-reports.md) | Evidence-based return formats for each worker role. |

Use actual message, file revision, program event, and artifact references. A
source reference should let a reader identify the exact user-visible message or
revision. Do not substitute a paraphrase for a source. Preserve source language
in the referenced conversation; write the task record and worker material in
English. A proposal remains a proposal until the user confirms it or explicitly
delegates the choice. An approval applies to the version the user saw.

These are original Task Workflow adaptations informed by the
[Superpowers project](https://github.com/obra/superpowers), which is licensed
under MIT. No Superpowers template text is copied here.
