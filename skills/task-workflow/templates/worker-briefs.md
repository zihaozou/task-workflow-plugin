# Worker brief structures

The coordinator fills a brief from the canonical record. Give each worker a
bounded responsibility, current source references, expected output, and a
stop condition. Workers do not delegate recursively. Store the brief as a
record section or program evidence reference. Do not create a second task
record or an unbounded set of user-facing documents.

## Common header

```text
Task ID:
Protocol and state version:
Role and owner:
Objective:
Approved design revision and source, if applicable:
Approved plan revision and source, if applicable:
Confirmed requirements and source references:
Delegated choices and exact scope:
Owned paths or evidence scope:
Inputs and current revisions:
Expected return format:
Stop and report when:
```

Every role stops before a consequential choice outside confirmed design or
explicit delegation. Report the question to the coordinator for user discussion.

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
Confirmed requirement and decision references:
Exploration evidence:
Review scope: coverage, assumptions, interfaces, verification, recovery
Return gaps with locations, consequences, and evidence:
Stop at user choice or missing fact:
```

Independently compare design revision with confirmed requirements, decision
sources, delegation scope, and exploration evidence. Return specific gaps,
unsupported assumptions, conflicts, and questions. Do not implement or approve
the design for the user.

## Implementer

```text
Plan item and approved design/plan digests:
Owned paths and permitted interfaces:
Required behavior and acceptance criteria:
Dependencies and current revisions:
Verification to run and evidence to return:
Stop at a choice beyond approved design or delegation:
```

Implement named work items from the approved plan in owned paths. Report the
change revision, verification, and any deviation. Stop when a new important
choice exceeds the approved design or delegation. Do not edit another worker's
paths without coordinator reassignment.

## Task reviewer

```text
Plan item and current change revision:
Confirmed requirements and acceptance sources:
Approved design/plan digests:
Changed paths and verification evidence:
Return separate requirements and quality verdicts:
Stop at missing evidence or out-of-scope choice:
```

One task reviewer can return both independent verdicts. The two rubrics below
keep their findings distinct; they do not require two reviewer agents.

### Requirements rubric

Independently inspect the actual change and verification against confirmed
requirements and accepted scope. Return a separate pass/fail verdict for each
requirement with evidence and remediation. Do not substitute style opinions for
requirements findings.

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
