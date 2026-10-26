# Workflow reference

## 1. Enroll and discover

Start only from explicit user enrollment or authorized continuation. The current
Git project owns state under `.task-workflow`. Plugin installation, hook events,
status views, and old state do not authorize enrollment.

Discover the program's `schema` operation before mutations. Use its actual
arguments, operation names, versions, and guards. Record task identity,
coordinator, authorization source, and the completion contract. Pass the
host-provided session identifier when available.

Resolve private conventions from instructions already loaded by the host. Pass
concrete environment, storage, execution, and resource values as explicit
arguments. The plugin does not open or update private instruction files, require
an `AGENTS.md` entry, or maintain a user configuration file or global registry.

Keep one readable task `record.md` for design, plan, decisions, progress, and
evidence. Structured state and event files support recovery; they do not prove
external actions. Write English summaries with references to original source
requirements. Preserve external raw data and behavior-critical literal values.

## 2. Design, delegate, and review

Explore relevant source, existing implementations, tests, and actual execution
facts. Explain unresolved effects, file scope, verification, and recovery before
approval. After approval, continue routine implementation. Discuss new unknowns
and material scope or behavior changes.

The coordinator delegates bounded implementation with owned paths, expected
behavior, verification, and evidence requirements. Workers implement, fix, and
test without recursive delegation. Choose a model for every bounded delegation:
Luna for simple lookup, documentation, and mechanical checks; Sol by default for
implementation and review. Astra requires explicit user approval. If a lighter
model is unavailable, choose an available Sol model. Never escalate automatically
to Astra. Reuse workers only while their model remains suitable; downgrade
routine fixes and later phases when the higher model is no longer needed.
Review actual evidence and avoid agent turns or review cycles that add none.
Do not claim a capability or parallel execution that did not occur.

Each item follows `pending -> implementing -> reviewing -> complete`. Failed
review returns it to `implementing`. Keep blocked reasons and next actions
separate. The coordinator inspects actual diffs and evidence. After the items
pass, independently review the full deliverable as an overall item. Reuse valid
evidence only when the approved design and relevant code remain unchanged.

## 3. Project paths and Git

```text
<project>/
  .task-workflow/                    # Task state and records
  .worktrees/<task-id>/              # Fixed development worktree
  .experiments/<experiment-id>/
    runs/<run-id>/
      code/                         # Frozen code
      snapshot.json
      ...                           # Run outputs
```

The development worktree path is fixed. Prepare it through the program and
reuse it for fixes. Do not implement in a base placeholder or select a different
path. Preserve existing registered paths during recovery. An experiment can use
an explicit root resolved from user conventions; its default root is
`<project>/.experiments`.

The program audits and maintains its project-local `.git/info/exclude` block
for generated directories. It does not alter global Git settings. Inspect
source and ignored inputs before freezing or cleanup. Git covers tracked code;
required non-Git inputs need explicit preservation and evidence.

Implementation approval and integration authorization are separate. Within
recorded authorization, the program validates expected base and task revisions
and creates exactly one ordinary squash commit on the base. Keep normal Git
hooks and signing. Verify the actual integrated revision before freezing a
dependent run. Preserve uncertain or conflicted integration for review before
retrying. Cleanup checks integration proof, snapshots, references, and unique
material before removing the owned worktree.

## 4. Resources and frozen execution

A resource represents execution capacity supplied under the user's private
conventions. The public program records identity, ownership, state, active run
references, and release permission. It does not encode a provider's policy.
Record who provided it separately from its observed availability. Its derived
state is `available`, `in_use`, `releasable`, `released`, or `unknown`.

Register resources with actual identity and ownership evidence. Reuse them only
after checking actual availability, compatibility, and all run references. A
started run establishes a resource reference. Finishing a run records its
execution outcome; it does not grant release permission. Release requires
explicit permission, verified ownership, and resolved active references.
Reconcile uncertain release results before retrying. A status read has no
provisioning or release effect.

An experiment has one research goal and may contain many frozen runs. A
code-only task can use verification runs without becoming a research experiment.
Changed code or arguments for the same goal creates a new run. Changed goals
create new experiments.

Freeze code, environment references, entrypoint, arguments, inputs, outputs,
and resource references before execution. Keep stable environments outside
removable worktrees. Verify actual imports when dependencies can resolve back
to development source. Preserve existing symbolic links and referenced targets.
Shared caches are outside task cleanup.

Record purpose, parent run, checkpoint reference when relevant, frozen snapshot,
resource identity, execution receipt, and artifact acceptance. The program pins
the workflow and runner runtime. Preserve referenced runtime files and stable
environments for existing execution. Later changes create a new run.

Submission does not prove execution. A zero exit does not prove artifact
quality. Accept actual artifacts with verification evidence. Experiment closure
requires resolved planned work and accepted analysis. Task closure requires the
complete deliverable, reviews, integration contract, experiments, runs, and
required cleanup. Keep earlier closure history when reopening work.

## 5. View, hooks, and recovery

MCP tools use the same program and persistence. Reconnect the process after an
update and rediscover schemas. Replacing source does not reload an existing
process. Use one current interface for mutations in a task.

After enrollment, call the model-only `workflow.status_view` tool with known
project and task context. It returns an opaque view reference. The app-only
refresh tool accepts that reference and returns persisted status. The bridge
cannot request arbitrary paths or issue mutations.

The official thread entrypoint opens the current chat's right-hand Workflow
tab. The user selects the tab manually. The entrypoint alone does not provide a
verified current-chat identifier. An unbound view explains its state; the model
binds the known task through the view tool. Do not guess another chat's task,
scan the home directory, or add global navigation. Refresh does not query an
external execution service.

SessionStart restores bounded facts only for existing tasks in the current
project. Validate `cwd` and `session_id`, then use exact recorded session
bindings. Unenrolled sessions remain quiet. Do not put prompts, arbitrary logs,
private instruction files, or task prose into recovery context. The
UserPromptSubmit hook adds fixed self-contained naming guidance. It does not
read private instructions or enroll work.

Review and trust hooks through the host's supported flow. A hook does not
authorize an action, complete a task, or prove execution success. After an
interruption, compare the canonical record with actual files, Git refs,
resource ownership, execution receipts, and artifacts. Check whether an action
happened before replaying it. Record discrepancies and recover from evidence.

## 6. Report and complete

Lead updates with a new result or next action. Include material verification,
output locations, and unresolved decisions. Explain unfamiliar terms on first
use, keep names stable, and explain rename mappings. Keep routine updates short
and avoid duplicate reports.

Before large execution, state scope and stopping conditions. Review actual
results and required cleanup before declaring completion. Report integration,
execution, artifact acceptance, experiment closure, task closure, and resource
release as separate facts when they affect the conclusion.
