# DeepSeek Harness integration

Task Workflow uses the same Python operations, records, guards, and skill on
Codex and DeepSeek Harness. The native DeepSeek package is `@local/task-workflow`.
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

### Current context and attribution

The official bridge supplies startup and accepted-prompt context. The adapter's
supplemental required `systemPrompt.context` provider refreshes context during
native request assembly, including a request after same-turn compaction without
a new human prompt. It reads the actual committed Session working directory
through `workingDirectory.get(session)` and the exact native Session identity.
It does not select a task by recency or infer a new session binding.

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

Use only native delegation tools visible to the current agent. A configured
`subagent` tool may have another name. Its children normally inherit the native
route. Query `list_subagent_models` only when the host exposes it and the user
has authorized selectable routes. Do not enable model-selection settings or
insert Codex model identifiers to obtain that tool. Preserve user preferences
and the host's real capability checks. Task Workflow workers do not delegate
recursively. See the shared policy in [workflow.md](workflow.md).

A real-provider check uses the authorized route and the host's existing
credential service. Keep secret resolution inside the host. Verify actual
provider/model metadata, a harmless native MCP context call, and a native child
completion. A scripted stub proves transport or lifecycle behavior, not semantic
obedience by the selected provider. Preserve those evidence classes separately.

## Build and inspect an archive

From the reviewed candidate checkout:

```sh
npm pack --dry-run --json
npm pack --pack-destination "$archive_directory"
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

## Candidate verification and release order

1. Complete item checks and independent reviews for the approved candidate.
2. Inspect and install its archive within the recorded candidate-test authority.
   Confirm saved composition, restart, and verify actual native activation.
3. Use the current authorized provider and native delegation for a synthetic task.
   Check exact project/session context, harmless tool execution, progress reads,
   resume, same-turn compaction, and child cleanup. Record actual results and
   material failures; do not infer them from package presence or stub tests.
4. Complete independent overall review of the implementation and installed-host
   evidence. Obtain applicable Git integration authorization.
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
