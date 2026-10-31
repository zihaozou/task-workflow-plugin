# DeepSeek Harness integration

Task Workflow uses the same Python operations, records, guards, and skill on
Codex and DeepSeek Harness. The current dialogue contract exposes the shared
`goal_integrity` policy. The UserPromptSubmit hook and generated stage context
carry the same policy so a selected template excerpt cannot reintroduce scope
bargaining. The native DeepSeek package is `@local/task-workflow`.
Its first supported target is DeepSeek Harness `0.2.1-rc.3`, with the official
`@deepseek-ai/dsh-hooks-codex` and `@deepseek-ai/dsh-hook-protocol` packages pinned
to that exact version. Do not substitute an npm distribution tag for these pins.
The two official packages are plain dependencies; their presence alone does not
register the Task Workflow bundle or prove live hook execution.

## Package and native interfaces

| Path or interface | Responsibility |
| --- | --- |
| Root `package.json` | Native package version, exported entry, archive contents, and `dsh.bundle.patch` declaration |
| `adapters/deepseek/cordis.patch.yml` | Additive native bundle row |
| `adapters/deepseek/index.js` | Child registration, current package paths, managed hook configuration, fresh context, and cleanup |
| `skills/task-workflow/scripts/deepseek_context.py` | Read-only JSON bridge to the existing session-context function |
| `skills/task-workflow/scripts/mcp_server.py` | Shared operation schemas and Python dispatch |
| `skills/task-workflow/SKILL.md` | Shared conversation, approval, and review process |

The adapter resolves paths from its installed package and uses the host's Python
interpreter. It registers the official bridge with a generated configuration
containing only the existing SessionStart and UserPromptSubmit commands. The
managed configuration resolves package-root command paths because the official
Codex bridge does not expand plugin-root placeholders or supply a plugin
environment. No Stop command or forced continuation is enabled.

The shared MCP tools use the native namespace `mcp__task-workflow__`, for example
`mcp__task-workflow__context`. The filesystem skill provider has the unique name
`task-workflow` and scans the installed package's skill root. It preserves the
host's other providers and existing skill directories. MCP names and schemas
come from the same Python program; there is no separate DeepSeek operation set.

The current capability snapshot reports `skill_loader.available` and the actual
`tool_name` and `parameters` only when the live tool catalog exposes that loader.
Use its supplied `arguments` only when present; the `name: task-workflow` example
exists only for a schema that actually accepts `name`. If no native loader is
available, read the verified `main_skill_path` through an actual supported file
reader. If neither route is available, report missing guidance. Registration or
an available loader is not evidence that the skill was read.

`capabilities.applicability` scopes these facilities to an authorized related
workflow request. Ordinary chat, advice, and simple requests keep their direct
route; status/progress requests inspect and preserve the wait. Tool availability
and injected context grant no new authority. This scope is guidance, not a new
delegation argument or a change to native tool visibility or control. Pass fresh
workflow children the actual record, root/project/worktree and current skill/
context pointers from [../templates/worker-briefs.md](../templates/worker-briefs.md).
They do not inherit the parent history or a task binding. Preserve ordinary
scope and unchanged native delegation for work outside the enrolled workflow.


### Current context and attribution

The official bridge supplies startup and accepted-prompt context. The adapter's
supplemental required `systemPrompt.context` provider refreshes context during
native request assembly, including a request after same-turn compaction without
a new human prompt. It reads the actual committed Session working directory
through `workingDirectory.get(session)` and the exact native Session identity.
It does not select a task by recency or infer a new session binding.
The refreshed context includes `goal_integrity` alongside the current stage
guidance. Preserve the complete objective and confirmed acceptance when
following that guidance; an unavailable or stale context requires status
inspection before dependent work.

For currently allowed `process-plan` and `process-decision` operations, current
stage guidance includes read-only argument drafts bound to the actual selected
task, coordinator and state version. Plan drafts copy approved component,
requirement, file and interface references; mechanical action/check links show
exact reference spelling. Semantic content and confirmation sources remain null
with explicit `required_fill_paths`. Fill and review them before any submission.
The draft does not perform an operation, confirm a choice, approve a revision,
advance a wait, or authorize a status request to change state. Regroup the draft
when the actual work needs different ownership or checks. Use exact item interface
strings in steps and keep `confirmation_source` inside `decision`.
Complete structural examples are in [workflow.md](workflow.md).

The context callback is synchronous. It invokes the Python helper and waits for
its read before model admission. Numeric stdout/stderr file descriptors carry
the complete result without a fixed process-output buffer. This adds synchronous
I/O cost; it does not make the read free or asynchronous. The adapter adds no
read deadline, output cap, workload limit, or resource limit.

Context uses the host's source attribution. The harness may represent it as a
user-role runtime-context message; its host source does not become a human
request, decision, or approval. Fresh context grants no authority and forces no
turn. Ordinary requests retain the scope and wait behavior in the main skill.

The host's shell can truncate a large hook's stdout. For the official bridge
only, the adapter checks the documented `stdout.truncated` flag and replaces the
lossy text body with: `Task Workflow hook output was truncated by the host. Use
the complete current Task Workflow runtime context.` It preserves the actual
exit code, signal, other result metadata, and host defaults. A partial JSON tail
must not become hook-provided task context. The complete required runtime context
still uses the separate numeric-descriptor read. Verify small official hook
effects, the large-output notice, and complete supplemental context separately;
none establishes an unbounded host shell.

The helper reads one JSON object on stdin with actual `cwd` and `session_id`:

| Outcome | Exit | JSON result |
| --- | --- | --- |
| Current context | 0 | `{"ok": true, "context": <core context>}` |
| No associated task | 0 | `{"ok": true, "context": null}` |
| Invalid input | 2 | `ok: false`, error code `invalid_input` |
| Read failure | 1 | `ok: false`, error code `context_unavailable` |

Invalid input reports `Expected actual cwd and session_id.` A read failure reports
`Current Task Workflow context is unavailable. Inspect status before dependent
work.` The adapter returns a sanitized unavailable notice instead of cached task
state. It does not expose tracebacks, raw input, credentials, or private file
contents. Inspect current status before dependent workflow work resumes.

### Readiness and lifetime

A successful `ctx.plugin` call is insufficient evidence of readiness. Child Fiber
state `2` means active; pending, inactive, or failed children do not satisfy
startup. Also verify actual MCP tools, skill registration, official hook effects,
and fresh context. A registration result alone does not prove model behavior.

Partial startup rolls back the children it created. Shutdown explicitly disposes
and drains owned child work before removing the temporary hook configuration.
Keep that configuration available while a hook process can still reference it.
Existing profile rows, sessions, credentials, and older installed releases are
outside adapter cleanup. Replacing source or an archive does not reload an
already-running JavaScript module; verify the new process after restart.

## Host models and delegation

Use the current authorized DeepSeek route, including the user's current Flash
selection. Native `agentDefaultModel.currentSelection()` returns provider, model,
and optional reasoning-effort metadata for new agents; an existing Session's
current selection remains authoritative for that Session. Record route metadata
without dumping settings or credentials. Do not guess an internal Flash model ID.

Discover the tools currently exposed before choosing a transport. The adapter
adds three native Task Workflow tools beside the shared MCP
operations. It leaves the host's original subagent tools unchanged.

| Tool | Arguments and result |
| --- | --- |
| `task_workflow_delegate` | Native `prompt` and `description` are required; `cwd` is optional. The workflow wrapper additionally accepts `assignment_id` for an existing task worker assignment; control version 2 requires it. Returns the native activation identity with an opaque `handleId`. |
| `task_workflow_wait` | Takes `{ "handle_id": "<returned handleId>" }`. Returns `handleId`, `subagentId`, `status: "settled"`, the unaltered public native `result` when available, and `cleanup.status` (`complete` or `failed`). A failed result capture returns an explicit `error.code: "result_unavailable"`. |
| `task_workflow_cancel` | Takes `{ "handle_id": "<returned handleId>" }`. Disposes that owned activation and waits for its actual result. It does not interrupt an unrelated native worker. |

For control-version-2 bound tasks, register `worker-assign` before delegation.
The wrapper verifies that assignment against current state, strips `assignment_id`
before invoking the native provider, and binds the observed parent session,
child session, initial message, and opaque handle through `worker-activate`.
A failed binding cancels and joins exactly the just-started owned activation,
returning its actual activation and terminal receipt for reconciliation. It does
not relaunch the child or pretend the ledger write succeeded.
`task_workflow_wait` and `task_workflow_cancel` record actual result and cleanup
through `worker-settle`; capture or cleanup failure cannot become successful
acceptance. A state-version conflict requires fresh inspection and reconciliation;
it does not authorize another worker launch. Historical tasks without control
version 2 retain their prior delegation contract.

The coordinator waits after dispatch. Shared program guards reject coordinator
execution mutations while assigned/active workers remain pending. This does not
claim interception of arbitrary native shell or file-writing tools. Current
capability context describes the wait and discovers exposed native goal tools.
`goal-request` records intent; only an actual available host invocation and exact
`goal-observe` receipt establishes a native goal. Absence remains request-only.
Native goal, item, task, integration, resource, and Run lifecycles are independent.

The tools reuse the official configured spawn provider with native preset,
depth, working-directory, and authorized provider/model checks. Handles belong
to the exact parent agent and session. Preserve the returned handle; do not
substitute a child ID or invent a handle. Caller delivery captures the public
activation result without an automatic parent completion notice. A child report
or a native child-start acknowledgement is not terminal settlement.
Handles live in the active plugin instance; they are not portable across a
restart or reload. Keep their ownership and terminal evidence in the task
record, but do not treat a recorded handle as a restored live control. Use the
host's unchanged native controls for pre-existing or unowned activations.

Wait for every owned activation to settle and finish cleanup before final
delivery. A cancelled wait does not cancel the worker; use explicit cancellation
when the work should end, then inspect its result. Check both the native result
and cleanup status: a captured successful result does not prove cleanup passed.
Report a cleanup failure as unresolved. Give progress updates while work is
active, then continue waiting within the authorized task. Do not depend on a
later automatic turn to complete the handoff. Workers return their terminal
report through their activation result. Native messaging remains available for
important early questions and findings; those messages do not settle a handle.
Send a separate final parent message only when explicitly requested. Workers do
not delegate recursively.

Query `list_subagent_models` only when the host exposes it and selection is
authorized. Do not enable model-selection settings or insert Codex model IDs.
See the shared policy in [workflow.md](workflow.md). A child result, automatic
wakeup, resume, or injected context is not a new human request. The prompt-hook
gate accepts the host's native `user` source class and excludes the known owned
initial handoff by its exact child and public message identity. Other source
classes do not invoke that prompt hook. Native `user` classification alone does
not prove human origin for an unowned handoff; verify the actual source before
recording human authority. Host context delivery grants no new authority.

A real-provider check uses the authorized route and the host's existing
credential service. Keep secret resolution inside the host. Verify actual
provider/model metadata, a harmless native MCP context call, and a native child
completion. A scripted stub proves transport or lifecycle behavior, not semantic
obedience by the selected provider. Preserve those evidence classes separately.

## Native questions and answers

Use the current capability snapshot to discover `ask_user_question`, its actual
parameters, and live root eligibility. The host's current registered roots decide
eligibility; a historical parent-session link does not. A live delegated child
returns unresolved questions to its coordinator. Do not change host settings or
invent a question tool when the capability is unavailable.

Record the workflow question successfully before calling the native tool. Use
its returned pending question ID and digest. In the inspected 0.2.1-rc.3 native
schema, `questions` contains entries with `id` and `question`, optional `header`,
optional `options` containing `label` and optional `description`, and optional
`multi_select`. Use the actual current schema if it differs. Set the native
question ID to the recorded ID; render its meaning in the conversation language.
Options come only from real recorded choices. Keep an unambiguous mapping from
unique displayed labels to recorded choice IDs; a consequence can supply the
option description. Omit options for an open question when supported. No fixed
alternative count or timeout is introduced.

Native answers contain `answers` entries with `id`, `selected` labels, and
optional `custom`. An immediate result is associated with its actual tool call;
a later `user-question-reply` names that call through `callId`. Match the call,
question ID, and captured digest against the current pending question before
recording the answer. If `custom` is nonempty, preserve its raw text and do not
invent a choice ID from a simultaneously retained selection. When `custom` is
absent or empty, map only a single unambiguous selected label to its exact
recorded choice ID. Empty,
skipped, pending, stale, or ambiguous replies keep the existing wait; they are
not approval or evidence of user agreement. An actual native human answer is a
user source even when delivered through a tool result or continued native reply.
This answer handling does not change the prompt-hook source gate.

For exact Spec/Plan approval, show the reviewed revision first and bind the card
to the live approval target. Record only the actual explicit approval. If a
native card is unavailable or cannot represent the request, use the same
recorded question or approval target in prose and retain the wait. Do not claim
that a card or an answer exists. Follow the shared handoff in the main skill.

## Build and inspect an archive

From the reviewed candidate checkout, keep the installable archive in a durable
release directory outside experiment outputs. For the standard DSH data home:

```sh
dsh_data_home="${DSH_HOME:-$HOME/.dsh}"
archive_directory="$dsh_data_home/releases/task-workflow/0.1.14"
mkdir -p "$archive_directory"
npm pack --dry-run --json
npm pack --pack-destination "$archive_directory" --json
```

`archive_directory` is the chosen artifact output directory. Use the actual
filename returned by `npm pack`; do not guess it. Inspect the packed file list
before installation. It must contain the native entry and patch, helper, shared
Python runtime, hooks, and complete skill/templates/references. Exclude private
task records, experiment outputs, credentials, user profiles, and development
worktrees. Preserve the artifact and its hash for later comparison.

The root native package and Codex manifest carry the same release version.
The native package adds host integration; it does not rewrite frozen workflow
or runner bytes referenced by existing runs.

## Install a candidate without replacing profile data

Use the supported `dsh` command supplied by the target installation. The macOS
Desktop app can supply a bundled command when `dsh` is not on PATH. Confirm its
version with `dsh --version`. Fully quit the app before changing its Desktop
profile; obtain any required user permission to interrupt active work and verify
actual exit. Installation authorization and application-exit authorization are
separate from Git integration authority.

Back up the existing package manifest, lockfile, patch, and package-manager
settings privately. Record hashes and existing bundle order without disclosing
secret values. Keep the original rows and dependency selections. The supported
Desktop installation command is:

```sh
dsh plugin --profile desktop add --save-exact "$archive_path"
```

`archive_path` is the actual reviewed archive. The native manager adds its bundle
to the existing ordered list after validating `dsh.bundle.patch`; it does not
require replacing the profile manifest. The exact official hook dependencies
must also be available. If they are absent, install the compatible pins through
the same supported manager:

```sh
dsh plugin --profile desktop add --save-exact @deepseek-ai/dsh-hooks-codex@0.2.1-rc.3 @deepseek-ai/dsh-hook-protocol@0.2.1-rc.3
```

A previous successful dependency installation is evidence of package presence,
not current Task Workflow registration. Check the saved package versions and
bundle selection separately from activation. Restart through the host's supported
app launch path only after registration is coherent. Then verify actual child
readiness, tools, skill load, hooks, and current context in the target process.
No Task Workflow configuration wizard, AGENTS entry, or credential export is
required. DeepSeek profiles remain the host's ordinary installation mechanism.

After the approved release is pushed, prefer an immutable Git commit as the
saved installation origin. Replace the placeholder with the actual approved
release commit, and use the same quit, backup, compatibility, and verification
steps as for the archive:

```sh
dsh plugin --profile desktop add --save-exact \
  'git+https://github.com/zihaozou/task-workflow-plugin.git#<approved-release-commit>'
```

The supported manager accepts Git specs and passes the commit fragment to pnpm.
Its GitHub connectivity check does not prove installation or activation. Verify
the saved source, actual package version, full installed payload, bundle order,
and runtime readiness. Compare the Git-installed payload with the reviewed
archive before replacing an active installation. Do not follow a moving branch
or use an experiment directory as the permanent release source. If Git retrieval
is unavailable, install the same checksum-verified archive from the durable
release directory and retain that exact origin and hash in the installation
receipt. Candidate installation does not authorize publication or replacement
of an active profile.

## Candidate verification and release order

1. Complete item checks and independent reviews for the approved candidate.
2. Inspect and install its archive within the recorded candidate-test authority.
   Confirm saved composition, restart, and verify actual native activation.
3. Use the current authorized provider and native delegation for a synthetic task.
   Check exact project/session context, harmless tool execution, progress reads,
   resume, same-turn compaction, and child cleanup. Record actual results and
   material failures; do not infer them from package presence or stub tests.
4. Complete sequential independent requirements and quality review, then main
   acceptance of the implementation and installed-host evidence. Obtain applicable Git integration authorization.
5. Integrate through the guarded workflow operation, then verify the integrated
   revision. Compare the reviewed candidate's packaged files with a package from
   that revision. Include path sets and file bytes; account for archive metadata
   separately. A changed payload needs affected verification again.
6. Complete final installed-payload and runtime verification before reporting the
   release accepted. Publish or update other installations only within their
   recorded authority. Preserve earlier releases and pinned execution runtimes.

Useful repository checks are:

```sh
PYTHONPATH=tests python3 -m unittest test_deepseek_adapter
DSH_TEST_CLI="$dsh_cli" npm run test:deepseek
python3 -m unittest discover -s tests -p test_package.py -v
```

`dsh_cli` is the supported command for the target installation. Inspect each
test's actual scope: isolated SDK/stub evidence does not by itself prove live
Desktop activation or real-provider completion. Test records are separate from
Task Workflow approval, experiment acceptance, and closure.

## Automatic invalid-tool-JSON recovery

The adapter uses the official `@deepseek-ai/dsh-llm-retry` 0.2.1-rc.3 recovery
boundary for the authorized active workflow's exact invalid tool-argument JSON
failure, with public typed stream inspection from `@deepseek-ai/dsh-llm` at the
same pinned version. The error must be `MALFORMED_RESPONSE` with message
`DeepSeek Messages stream: tool input is invalid JSON`. Eligibility also requires
the same live agent, turn, step, and confirmed current native `assistant/attempt`
sequence, whose nonempty complete closed typed call set contains only currently declared
workflow MCP operations. Mixed native/ordinary calls, unknown tools, missing or
unbound tasks, and changed context pass through to native handling. It does not
match phrases in old dialogue or rendered history. This exact parse failure is
distinct from other malformed responses, schema validation, tool errors, and
workflow guards.
Unrelated failures keep their existing native handling.

Native downstream recovery gets one delegation for the current failure. If it
returns a retry decision, preserve that decision without scheduling another
retry. If it declines, including after its configured finite budget is exhausted,
the adapter's narrow fallback can continue this eligible request. The provider's
original retry configuration and provider/model route remain unchanged. The
fallback uses the official executor with a copy of the actual host backoff
settings. It rechecks current task eligibility, typed attempt, and
request identity after backoff before requesting the next attempt. Root, session,
task, and version must still match the request binding; stale or unrelated
context cannot authorize another request.

Every retry is a new model request and can repeat input-token billing and add
output charges. The selected recovery continues until valid output or actual
cancellation while the same task/request remains eligible. Cancellation or
plugin disposal stops the owned recovery wait and joins its settlement; a retry
notice is not success. Preserve failed attempts and their retry evidence in the
native session log through official `llm/retry` and `llm/retry-started` events.
A syntactically valid response can still fail a schema or workflow guard; this policy does not turn those errors into user authorization.

Recovery repeats model generation at the failed request boundary. It does not
re-enroll the task, repeat completed workflow work, guess or edit JSON arguments,
change provider settings, add a Stop continuation, or set a new retry-count cap.
Inspect actual terminal outcomes. Isolated runtime checks establish their tested
recovery and cancellation behavior; actual-session/model testing remains
reserved for the human.

## Long operations and recovery

DeepSeek's native MCP client defaults to a 60-second tool-call timeout; the
official rc.3 Codex hook bridge defaults to 600 seconds when a command supplies
none. These inherited host defaults are separate from Task Workflow workload
semantics. The adapter does not override them or promise that host calls wait
forever. Native shell calls have their own host execution behavior too.

Run long verification through the native shell and the existing workflow CLI,
using the host's supported background mechanism when a foreground call cannot
cover it. Retain output and inspect actual completion. For long workloads, use
existing `run-execute` with `detached: true`, or `run-dispatch` with its pinned
runner arguments and actual executor. Observe or reconcile the resulting receipt
after refreshing the state version. A caller timeout does not prove that a
workload stopped or failed; reconcile before retrying. A late or unknown result
does not authorize duplicate execution.

For removal, use the supported manager with the exact package name:

```sh
dsh plugin --profile desktop remove @local/task-workflow
```

Safely quit the app first when required. Compare current files with the recorded
owned changes before restoring any backup. Reconcile intervening edits instead
of overwriting them. Remove only this bundle's registrations and managed files;
remove official hook dependencies only if no other bundle needs them and removal
is authorized. Verify the original bundle order, unrelated rows, and settings.
Restart and inspect actual state. Preserve sessions, credentials, shared caches,
and older runtime files while references remain.

## Primary interface references

The installed runtime's package-owned English documentation is authoritative for
its exact version. Relevant packages are `dsh`, `dsh-app-boot`,
`dsh-plugin-manager`, `dsh-agent`, `dsh-system-prompt`, `dsh-working-directory`,
`dsh-agent-default-model`, `dsh-tool-subagent`, `dsh-mcp-client`, and
`dsh-skill-filesystem`. The official hook packages' pinned npm artifacts contain
their README and compiled implementation:
[Codex bridge rc.3](https://registry.npmjs.org/@deepseek-ai/dsh-hooks-codex/0.2.1-rc.3)
and [shared protocol rc.3](https://registry.npmjs.org/@deepseek-ai/dsh-hook-protocol/0.2.1-rc.3).
Check shipped implementation when a README disagrees with observed behavior;
preserve the evidence and version.

## Interpreter ownership

Native activation calls the installed bootstrap with isolated host Python, then uses the verified `skills/task-workflow/.venv` interpreter for context, hooks, and MCP. Activation fails if runtime ownership or interpreter verification fails. This change preserves the existing hook, delegation, recovery, and teardown contracts. See [plugin runtime ownership](workflow.md#plugin-runtime-and-project-toolchains).
