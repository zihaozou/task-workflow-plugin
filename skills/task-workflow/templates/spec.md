# Spec template

A Spec is the existing Design revision, not another phase or document. Store it
inside the one record's Design section through `process-design`. Use the same
revision, independent review, digest binding, and approval. The Spec states the
complete user-confirmed objective and maps every confirmed requirement to
behavior and acceptance. Keep confirmed scope intact through revisions; an
omission, renamed ID, demotion, or replacement does not remove a requirement.
Only an explicit actual user scope change, recorded with its prior digest and
disposition, changes the confirmed goal. New submissions use the current schema.
Existing stored envelopes remain readable and approvable without rewriting their
content or digest.

Present the actual revision using concise bold labels and grouped bullets or
tables. Keep source links in the record and show them beside user-facing facts
when useful. Omit empty optional presentation groups. Material unknowns prevent
approval. The template is a content structure, not a parallel source of authority.

## Required content and source mapping

| Section | Content | Authoritative source |
| --- | --- | --- |
| Intent and success | Outcome, reason, observable success | Intent and confirmed acceptance requirements |
| Scope | Included behavior and relevant exclusions | Confirmed scope requirements; design `out_of_scope` |
| Current behavior and impact | Observed baseline, affected users/components, compatibility effect | Exploration; design `current_impact` |
| Required behavior | Flows, inputs/outputs, interfaces, relevant failure behavior | Design behavior and components with mapped requirement IDs |
| Decisions and authority | Choice, rationale, confirmed/proposed/delegated status, scope, actual investigation and probe findings | Sourced decisions and retained exploration evidence referenced by design |
| Performance, cost, and reuse (when relevant) | Expected scale, measured/estimated cost, reused inputs/results, recomputation boundary | Actual probe evidence and explicit assumptions |
| Constraints and delegation | Exact constraints, implementation freedom and boundaries | Confirmed constraints; design assumptions and delegated decision references |
| Acceptance | Requirement, check method, observable expected result | Confirmed acceptance requirements and design verification |
| Failure conditions | Conditions that make the result unacceptable | Design `failure_conditions`, tied to confirmed scope and acceptance |
| Open questions | Remaining consequential choices or missing facts | Exploration, unresolved questions, design unresolved entries |

For executable snapshots, Scope must identify the entrypoint, required local code,
configuration, runtime assets, fixed external references, and unrelated excluded
subprojects. Explain dependencies from inspected evidence. Acceptance must include
startup validation and actual code-origin checks. Resolve material inclusion or
reference choices through the existing user confirmation loop. Store this content
in the existing Spec and record, not a separate configuration policy.

Include recovery and data compatibility in required behavior or constraints when
material. Do not fill missing authority with an agent assumption. Label an agent
proposal and discuss it before treating it as settled. Preserve source data and
exact approved values. `current_impact` describes the observed baseline and effect;
`out_of_scope` and `failure_conditions` are explicit lists in new design content.

When the plan will use typed interface dependencies, declare exact
`interface_contracts` in Spec using `id`, `producer`, `consumers`, and `contract`.
Carry the same accepted semantics into the Plan; changing an interface requires
revising its affected sources and approval rather than assuming compatibility.

Before submitting Spec, resolve consequential feasibility gaps against actual
inputs and real versions. Record each probe's question, inputs, versions,
procedure, pass/refute criterion, observed result, and evidence in Exploration.
A refuted or inconclusive result informs the design; it is not acceptance.
Do not substitute a hypothetical API, planned check, or invented host capability
for an observed fact. Cite inspected source when execution is unnecessary.

Declare required feasibility prerequisites in optional
`design.feasibility_checks: [{"check_id": "actual-check-id", "requirement_ids": ["actual-requirement-id"]}]`.
Each declared check must have actual passed source-bound proof and its recorded
criterion before Spec admission. Missing, failed, or uncertain declared proof
blocks that Spec. Unlisted refuting probes for abandoned alternatives remain
findings; they do not globally block the design. The gate preserves the durable
checked revision rather than requiring implementation to retain the pre-Spec
source unchanged.

## Presentation outline

```markdown
**Spec Dn - descriptive title**

**Intent and success**
- [Outcome, reason, and observable result.]

**Scope**
- [Included behavior and relevant exclusions.]

**Current behavior and impact**
- [Observed baseline and concrete effect of the change.]

**Required behavior**
- [Behavior, interface, and relevant failure case.]

**Decisions and authority**
| Choice | Authority and scope | Reason |
| --- | --- | --- |
| [Choice] | [User-confirmed or delegated scope] | [Reason] |

**Constraints and delegation**
- [Exact constraint or explicit implementation freedom.]

**Acceptance**
| Requirement | Verification | Expected result |
| --- | --- | --- |
| [Behavior] | [Check] | [Observable result] |

**Failure conditions**
- [Unacceptable behavior.]

**Open questions**
- [A real unresolved question, only when present.]

**Review**
- [Independent review outcome for this exact revision.]

**Approve**
Do you approve Spec Dn for implementation planning?
```

## Independent builder gap review

Give the reviewer the exact Spec revision, complete source-backed confirmed
requirement ledger, recorded scope changes, decision sources, delegation
boundaries, and exploration evidence. Flag any omitted or reduced confirmed
requirement, including one missing after an update or ID change. Approval waits
until complete coverage is restored or an actual user-authorized scope change is
recorded. Ask whether a competent
builder could make a concrete implementation plan without guessing important
behavior. Return consequential unanswered questions, affected sections, evidence,
and how a wrong choice changes the plan, in order of consequence. Check coverage,
interfaces, failure conditions, acceptance, and recovery. Respect choices explicitly
left to the builder; wording preferences alone are not design gaps.

The coordinator resolves facts from existing sources, settles choices within
explicit delegation, and brings consequential user choices into discussion.
Record resulting answers and decisions before revising the Spec. Obtain an
independent review of the actual revised digest before approval. Approval covers
only the reviewed revision presented to the user.
