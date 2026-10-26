# Worker return formats

Use actual artifact, command, file revision, and source references. Keep the
report concise enough to copy into the task record as structured evidence.
"Pass" means the assigned checks were observed, not that a later phase is
authorized. A blocked report includes the exact missing fact and next action.

## Exploration report

```text
Scope and source revisions:
Observed facts: [fact | source | observation]
Unknowns: [question | why it matters | next check]
Consequences for requirements or design:
Suggested next action:
```

## Design-gap report

```text
Design revision reviewed:
Requirement and decision sources checked:
Verdict: gaps found | no material gaps found
Builder readiness: concrete plan possible | important guesses remain
Gaps: [question | Spec section | evidence | effect on plan | needed resolution]
Unsupported choices or approval claims:
Questions for coordinator:
```

## Implementation report

```text
Plan item and approved revisions:
Owned paths changed:
Change revision or diff reference:
Behavior implemented:
Verification: [named check | assertion or criterion | command/target | expected outcome | actual result | evidence]
Deviations or open choices:
Handoff state: ready for review | blocked
```

## Task review report

```text
Plan item and change revision reviewed:
Requirements verdict: pass | fail | blocked
Requirements evidence: [ID | verdict | change evidence | verification evidence]
Quality verdict: pass | fail | blocked
Quality findings: [severity | file location | observed consequence | evidence | fix]
Missing behavior or verification:
Required remediation:
```

## Overall review report

```text
Complete change revision and plan reviewed:
Item requirements verdict references:
Item quality verdict references:
Cross-item checks and evidence:
Design and plan alignment:
Verdict: pass | fail | blocked
Remaining work or material limitation:
```

## Discussion synchronization

Report each new important unknown with evidence, its consequence, and the affected
requirement, decision, design, or plan revision. The coordinator records reentry
and the question before asking the user. An answer and its affected sources must
be synchronized before dependent work resumes. Preserve unaffected evidence.
