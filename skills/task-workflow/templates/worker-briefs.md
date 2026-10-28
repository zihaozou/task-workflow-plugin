# Worker brief structures

The coordinator fills a brief from the canonical record. Give each worker a
bounded responsibility, current source references, expected output, and a
stop condition. Workers do not delegate recursively. Store the brief as a
record section or program evidence reference. Do not create a second task
record or an unbounded set of user-facing documents.

For workflow-scoped workers on DeepSeek Harness, use the exposed Task Workflow
delegate/wait/cancel tools. Capture the returned activation handle and give each worker
a terminal return contract. The worker returns its final report through its
activation result. Use native messaging for important early questions or
findings; these messages do not mean the activation ended. Send a separate final
parent message only when the coordinator explicitly requests one.
The coordinator waits for the actual terminal result and cleanup for every owned
handle before final delivery. Explicit cancellation also requires settlement.
The caller-delivery tools do not promise an automatic parent completion notice.

## Common header

```text
Request applicability and authorized scope:
Task ID and parent task/session association, if applicable:
State root (actual absolute root argument):
Project checkout (actual absolute base path):
Task worktree (actual absolute path or recorded base placeholder):
Canonical record (actual absolute record.md path):
Protocol and current state version:
Role, actor, and exact plan item or review target:
Complete user objective and completion contract:
Exact Spec revision, digest, status, and source, if applicable:
Exact Plan revision, digest, status, and source, if applicable:
User request and approval source references:
Complete confirmed requirement ledger and decision sources (including difficult requirements):
Delegated choices and exact scope:
Permitted operations and owned paths or evidence scope:
Current context read (actual tool/runtime and root/task_id arguments):
Current main skill and available native loader or verified read fallback:
Context, source files, and revisions to inspect before action:
Expected return format:
Terminal activation return and cleanup contract:
Stop and report when:
```

A fresh DeepSeek native child does not inherit the parent's conversation
history. Other host mechanisms, such as a Codex fork with history inheritance,
can supply prior context; verify the actual capability. Keep the self-contained
brief in either case. Fill these pointers with actual current values for
workflow-scoped work; do not send
only a task name, a remembered version, or an instruction to continue. The child
first reads the supplied record, exact Spec/Plan or review target, source
references, relevant files, and current read-only task context. Check that root,
project, worktree, task, role, item, and revision agree before action. Load the
current main skill through an actual exposed native skill loader or a verified
current file-reading path. A registered skill or a usable tool does not prove it
was loaded or grant authority.

Preserve the child's actual binding status. An unbound child stays unbound unless
actual authority permits a binding operation. Use the supplied root and task ID
for the authorized read-only context call; do not
bind the child to the parent's session or enroll a replacement task to obtain
context. The brief is scoped coordinator delegation, not a new human request or
approval. It must carry the complete objective, all confirmed acceptance
requirements, and relevant decisions. Cost or difficulty does not authorize a
smaller substitute. Trace behavior and write authority to the actual user sources
and approved item. Flag any source or plan omission to the coordinator before
dependent work. If context, sources, or pointers are unavailable or inconsistent,
return that gap to the coordinator before dependent action.

For an ordinary request outside an enrolled workflow, preserve ordinary scope
and state that task/Spec/Plan pointers are not applicable. Do not invent a task,
approval, or workflow history to fill the header. Before approval, record the
actual proposed or missing revision status rather than claiming approval. Every
role stops before a consequential choice outside confirmed design or explicit
delegation and reports the question to the coordinator for user discussion.

## Coordinator

```text
Task and current state version:
User request source and completion contract:
Confirmed requirements and decision sources:
Current design/plan digests and approval sources:
Next phase and prerequisite:
Delegated items and owned paths:
Evidence to inspect before acceptance:
Authority check and reentry trigger:
```

Own task identity, authorization checks, conversation, record, work division,
review evidence, integration, and delivery. At each transition, check source
and version prerequisites. Present agent proposals as proposals. Ask one
meaningful question when the design is unsettled. Preserve exact approvals.
Inspect the actual diff and evidence before accepting worker claims.

## Explorer

```text
Question to investigate:
Source and environment scope:
Current evidence references:
Checks to perform:
Return facts, unknowns, and source locations:
Stop when evidence is unavailable or a product choice is required:
```

Investigate named unknowns in a bounded source and environment scope. Return
observed facts with locations, checks, uncertainty, and consequences for
requirements or design. Do not select product behavior on the user's behalf.

## Design reviewer

```text
Design digest and content reference:
Complete confirmed requirement ledger and decision references:
Recorded scope changes and user authority, if any:
Exploration evidence:
Review scope: builder readiness, coverage, interfaces, failure conditions, acceptance, recovery
Return unanswered important questions, affected Spec sections, consequences, and evidence:
Stop at user choice or missing fact:
```

Independently compare the exact Spec (Design) revision with the complete
source-backed confirmed requirement ledger, recorded scope changes, decision
sources, delegation scope, and exploration evidence. Flag omission, demotion,
renaming, or replacement of a confirmed requirement unless actual user authority
is recorded. Confirm every confirmed acceptance requirement appears in the Spec
and maps to acceptance before recommending approval.
Determine whether a competent builder can create a concrete plan without guessing
important behavior. Return unresolved questions in order of consequence, affected
sections, evidence, and how a wrong choice changes the plan. Respect explicit
builder freedom and omit wording preferences without a behavior consequence.
Do not implement or approve the design for the user.

## Implementer

```text
Plan item and approved design/plan digests:
Owned paths, per-file actions and responsibilities:
Spec component and requirement mappings:
Consumed/produced exact interfaces:
Ordered action steps and linked verification IDs:
Named checks/assertions, commands or inspection targets, expected outcomes:
Required behavior and acceptance criteria:
Dependencies and current revisions:
Snapshot entrypoints and required code/configuration/assets, when applicable:
Fixed external references and immutable identities:
Startup validation command and required origin checks:
Shared snapshot identity, run provenance, and mutable output location:
Snapshot ownership, live references, and cleanup boundary:
Verification to run and evidence to return:
Stop at a choice beyond approved design or delegation:
```

For executable snapshots, inspect the declared dependency closure before freezing.
Use the program-selected scope and return startup exit/report evidence plus actual
code origins. Stop when a required dependency or identity is missing or mutable.
Preserve existing snapshots and running inputs; remove only owned, unreferenced
content under the approved cleanup boundary.
Recognized `__pycache__` bytecode and `.pytest_cache` entries are disposable with
the owned worktree. Return compact counts and Git source proof, not cache backups
or duplicate source archives. Retry partial deletion through the durable cleanup
intent; preserve unknown files, changed source, external references, and Run inputs.

For an assigned long local launch, use `run-execute` with `detached: true`.
`run-dispatch` only reserves intent. After actual external queue acceptance or a
process-start acknowledgment, return the available evidence and log location,
then settle the worker activation. Do not wait for the first step, metrics, or a
checkpoint. Keep the Run and task open and resources retained. Later checks need
a user request, explicit monitoring authority, or an authorized dependent operation.
A dependent operation needs evidence later; it does not keep this turn watching.


Implement named work items from the approved plan in owned paths. Report the
change revision, verification, and any deviation. Stop when a new important
choice exceeds the approved design or delegation. Do not edit another worker's
paths without coordinator reassignment.

## Task reviewer

```text
Plan item and current change revision:
Complete confirmed requirement ledger and acceptance sources:
Recorded scope changes and user authority, if any:
Approved design/plan digests:
Changed paths and verification evidence:
Return separate requirements and quality verdicts:
Stop at missing evidence or out-of-scope choice:
```

One task reviewer can return both independent verdicts. The two rubrics below
keep their findings distinct; they do not require two reviewer agents.

### Requirements rubric

Independently inspect the actual change and verification against the complete
confirmed requirement ledger and accepted scope. Return a separate pass/fail
verdict for every requirement, with evidence and remediation. Do not treat
engineering cost, phased delivery, or an omitted/renamed ID as authority to
reduce confirmed scope. Do not substitute style opinions for requirements
findings.

### Quality rubric

Independently inspect correctness, maintainability, failure behavior, security,
and verification depth relevant to this change. Return findings with file
locations, severity, evidence, and remediation. Do not infer requirements
approval from quality approval.

## Overall reviewer

```text
Complete change revision and integrated item list:
Approved design/plan digests:
Item requirements and quality verdict references:
Cross-item behavior and verification to inspect:
Integration or delivery contract:
Return overall verdict, evidence, and remaining work:
```

After item reviews pass, inspect the integrated deliverable across items.
Check interactions, complete verification, approved design and plan alignment,
remaining risks, and readiness for authorized integration or delivery. Return
one overall verdict with evidence. This review is separate from item reviews.

## Discussion synchronization

Report each new important unknown with evidence, its consequence, and the affected
requirement, decision, design, or plan revision. The coordinator records reentry
and the question before asking the user. An answer and its affected sources must
be synchronized before dependent work resumes. Preserve unaffected evidence.
