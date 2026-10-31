# Implementation plan template

A plan implements an approved Spec (the program's Design revision). Store it in
the one record's Implementation plan section through `process-plan`. Link the
exact approved design digest. Present readable revisions to the user and keep
digest bindings in program state. Existing stored plans remain readable and
approvable without rewriting their envelopes.

## Plan content

Start with the plan revision/title, approved Spec reference, complete user
objective, shared constraints, dependencies, and review focus. Preserve the
confirmed requirement ledger and map every acceptance requirement, including
difficult or expensive behavior, to concrete tasks and checks. Use phases to
order dependencies without reducing the completion contract. Map exact files
and responsibilities before defining tasks. Give each task a checkable deliverable that an independent
reviewer can assess. Setup and documentation belong with the deliverable that
needs them. Lifecycle phases may summarize the process; Prepare, Implement,
Verify, Review, and Integrate alone are not implementation tasks.

Use a file table: path | create/modify/test/delete | responsibility | task.
For each task, specify:

- Owned files and their concrete responsibilities, mapped Spec components and
  requirement IDs, dependencies, and the responsible worker or coordinator.
- Consumed and produced interfaces: exact function signatures, command arguments,
  state fields, schemas, document sections, or outputs relevant to the task.
- Ordered action steps naming what changes, where it changes, the interface
  involved, and the checks that verify the action.
- Named tests/checks with precise assertions or inspection criteria. Copy exact
  values from the approved Spec when pinned. Use a direct inspection instead of
  an unnecessary test when it provides sufficient evidence.
- Verification commands and expected outcomes, acceptance, review focus, and
  evidence the implementer must return.

For executable snapshots, add concrete actions to inspect the entrypoint dependency
closure, submit the selected code/configuration/asset scope and fixed references,
freeze through the program, and validate startup before the main workload. Name
the validation command, expected import and asset checks, required code origins,
and evidence returned by the startup report. Plan immutable code/scope reuse with
separate run outputs and provenance. Name ownership and reference checks before
cleanup. For the full formal lifecycle, require accepted implementation and
main acceptance (or the retained legacy overall-review contract), one ordinary squash integration, integrated revision verification,
independent scoped freeze, successful Run startup validation, and reference-safe
owned worktree cleanup before formal dispatch. Development checks may use
authorized managed resources, including GPUs, before merge. Integration
verification runs against the exact integrated commit after merge and may also
use authorized managed resources. Both bind evidence to the revision actually
checked. Direct verification wrappers execute their local runners; external
`check-dispatch` returns exact pinned `runner_argv` for the private controller.
`run-validate` uses the Run's frozen validation arguments
and selected resource/controller path. For pre-change project verification, use the same
frozen baseline helpers; do not create a formal Run integration bypass. A later
approved same-experiment revision starts a new worktree generation from current
main and creates a new immutable Run while preserving earlier evidence.

Integration requires a clean base by default. If an authorized integration must
preserve unrelated dirty tracked work, plan a dry-run preservation manifest and
digest, then pass that exact digest with the same base and task revisions to the
real integration. Preserve existing staged and unstaged work; never stash, reset,
force checkout, or commit unrelated changes. After publication, verify the exact
integrated commit with `source_mode: fixed_commit`; optionally pass
`expected_integration_commit` to assert the recorded commit. The owned detached
verification checkout must settle and clean safely before a formal Run. Freeze
that Run from the verified
integrated Git objects with the matching check receipt and source mode bound in
its immutable preparation intent. For an opaque integration validator, make the
check assert that it reads the bound checkout. Recovery must preserve the
original preparation proof instead of replacing it with a later check.

Include applicable integration authority, independent reviews, and recovery.
Review coverage against every approved requirement and check interface names,
types, dependencies, and verification references across tasks. Distinguish
resource capacity for actual check/Run uses from retention holds for named future
work or persistent choices; a hold is not active capacity, and a completed use
releases only its own capacity. Preserve actual ownership, release permission,
and per-action authority. Include recovery for uncertain checks, cleanup,
dispatch, legacy runtime quiescence, and worktree recreation without replaying
completed work or deleting retained inputs. Replace vague
steps such as "handle errors" or "add tests" with actual behavior and checks.

## Dependency and ownership contract

For new semantic plan contract version 2, use `contract_version: 2`, an explicit
`owner` per item, and top-level `interface_contracts` entries with `id`,
`producer`, `consumers`, and exact `contract`. Item `interfaces` name the consumed
or produced interface IDs. Declare typed item dependencies:

| `kind` | Required evidence before dependent work | Scheduling consequence |
| --- | --- | --- |
| `contract` | Accepted interface contract bound to the approved Spec; `interface_id` is required | Disjoint workers can proceed concurrently from that contract. |
| `implementation` | Accepted current producer implementation evidence | Dependent implementation waits for producer acceptance. |
| `integration` | Accepted current producer evidence and current source-bound durable composition/integration-test proof | Disjoint implementation may proceed; submission/acceptance waits for composition evidence. |

Each dependency names `item_id`; `interface_id` identifies the relevant contract.
Concurrent file writers must have disjoint exact ownership. Contract edges alone
do not serialize overlapping writers. Use implementation ordering
or reassign ownership instead. Integration dependencies concern composing task
outputs and testing them together; they do not require Git publication. Git
integration retains its independent lifecycle and authority. Keep historical plans and their digests unchanged;
plan contract version and workflow control version are separate compatibility
fields. New tasks default to control version 2, which requires every new or
changed Plan submission to explicitly declare `contract_version: 2`. A guarded
control upgrade preserves an authoritative historical Plan version 1, its exact
digest, accepted evidence, and item protocol. That continuation remains compatible
until a new Plan version 2 receives actual approval; upgrade does not manufacture
revised user approval.

For an integration-test edge, a source-bound `verify` or `check-dispatch` uses
`composition_for: [producer_item_id]`. It must name declared composition
producers and retain their accepted current evidence; a generic passed check
cannot satisfy that dependency. This field applies to verification checks,
not formal Run dispatch.

The execution chain is implementer plus self-tests, distinct independent
requirements reviewer, distinct independent quality reviewer, and main-agent
acceptance. The coordinator waits after dispatch rather than coding in parallel.
No mandatory separate postimplementation verifier stage is introduced. Include
specific checks where the actual behavior or integration requires them.

## Human-facing approval presentation

Show meaningful component names and all material tasks, behavior, and decisions
in the approval reply. Keep internal component/requirement/source identifier
inventories, serialized `argv` arrays, and schema objects in the program record
unless a particular identifier helps the user assess a decision. Show executable
command text with correct argument quoting and its expected result beside the
check or action it verifies. Preserve the exact argument array in structured
state; the readable command is its human-facing representation.

Use a single readable check table or task block pairing check/action, command or
inspection target, and expected outcome. Do not follow it with a redundant full
command-metadata dump. A compact product-data JSON example remains appropriate
when the actual output shape is a material decision. Show the material plan for
approval; a link to unseen details is insufficient. There is no fixed length,
row, or task quota.

## New submission fields

The current schema is authoritative. Item-level fields include:

| Field | Content |
| --- | --- |
| `component_ids` | Existing approved Spec component identifiers |
| `files` | Owned repository-relative paths |
| `file_changes` | Exactly one entry for each owned path: `path`, `action` (`create`, `modify`, `test`, `delete`), `responsibility` |
| `interfaces` | Declared interfaces used or produced by this task |
| `steps` | Ordered objects with `id`, `action`, owned `files`, declared `interfaces`, and `verification_ids` |
| `verification` | Checks with `id`, `kind`, mapped `requirement_ids`, `targets`, `method`, `expected_result`, and command `argv` when applicable |

Step/check IDs are local to the item. `verification_ids` reference its checks;
step files and interfaces reference its owned declarations. `kind: command`
requires a nonempty argument array, preserving arguments without shell splitting.
`kind: inspection` requires safe repository-relative targets. Check targets may
include files beyond task ownership for observation; they grant no write access.
Keep existing deliverables, dependencies, acceptance, and review fields concrete.

## Illustrative plan excerpt

This standard-library JSON example demonstrates specificity only. Its paths,
names, behavior, and tests are not requirements for another task. An actual plan
also includes all affected tasks and their approved Spec references.

```markdown
**Plan P1 - Read a JSON report**
Approved Spec: D1 - JSON report reader.

**File responsibilities**
| Path | Action | Responsibility | Task |
| --- | --- | --- | --- |
| src/report_reader.py | Create | Load UTF-8 JSON report rows. | reader |
| tests/test_report_reader.py | Test | Assert loading and malformed JSON behavior. | reader |

**Task reader - Load report rows**
- Owner: assigned implementer. Dependencies: none.
- Produces: `load_report(path: Path) -> list[dict]`.
- Consumes: UTF-8 files containing the approved array-of-objects format.

**Actions**
1. Add `test_load_report_rows` using a temporary file containing
   `[{"name":"alpha","count":3}]`; assert the exact returned list.
2. Add `test_malformed_json_raises` with invalid JSON; assert `JSONDecodeError`.
3. Implement `load_report` in `src/report_reader.py` using UTF-8 input and
   `json.load`; preserve the specified parse exception.
4. Run the named checks and return their output for independent item review.

**Verification and review**
| Check | Command | Expected result |
| --- | --- | --- |
| Load rows | `python3 -m unittest tests.test_report_reader.ReaderTests.test_load_report_rows -v` | Pass; exact rows match. |
| Invalid JSON | `python3 -m unittest tests.test_report_reader.ReaderTests.test_malformed_json_raises -v` | Pass; JSONDecodeError is observed. |

**Approve**
Do you approve Plan P1 for implementation?
```

In structured content, each action becomes a step with its owned files and
interface references. For example, step `load-rows` references check `valid-json`;
that command check records its requirement IDs, target test path, exact `argv`,
and expected rows. Write these actual values in the submission, not placeholders.
