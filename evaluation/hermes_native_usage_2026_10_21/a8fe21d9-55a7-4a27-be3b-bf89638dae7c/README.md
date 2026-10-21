# Real Hermes oneshot / native usage — 2026-10-21

One authorized CLI inference invocation using the habitual default profile and
its normal authentication. No credentials were read/displayed/copied by the
collector; no OAuth import/manual refresh, new profile, alternate client, Ollama,
model/provider override or persistent config change was used. No simulator,
project controls or operational MCP was invoked.

- Hermes 0.22.2, installed checkout d923a5eb487a17c0a68801bba9ef0f56c81040a8.
- Exact configured/reported model: **poolside/laguna-s-2.1:free**, provider **nous**.
- Prompt: `Responde únicamente con la palabra OK.`
- Actual result: **OK**, rc=0, no stderr, no timeout; approximately 8.81 s wall time.
- Start/end: 2026-10-21T19:39:24.628540Z → 19:39:33.480256Z (21:39 CEST).
- One invocation with 120 s external limit; no retry by this collector.

## Why this installed CLI can run without tools/MCP

There is no dedicated --no-tools switch, and empty --toolsets restores defaults.
The installed public `catalog` toolset is desktop-only. `--toolsets catalog` is
accepted, then CLI platform gating subtracts all its tool names. An isolated
static check of that literal/spec and the source selection path confirmed zero
selected tools without importing Hermes or constructing an agent. Main startup
uses the same selection as the MCP startup name allowlist; no configured MCP key
is `catalog`. Hooks and fallback configuration were checked absent using only
those fields. No special bootstrap/client, monkeypatch or persistent override was
introduced. This is source/configuration evidence; no wire-level tool-schema or
process tracing was performed. Native usage reports a normal text stop.

The command is in command.json. Only HERMES_DISABLE_LAZY_INSTALLS=1 was added to
the subprocess environment to prohibit lazy installation. Native bootstrap/auth
ran normally; no repair or installation command was issued. The initial sandbox
failure during --version was an install-lock permission failure, not an inference
attempt. --version subsequently succeeded outside the sandbox. No failed model
invocation was repeated.

## Native counters and limits

`native_usage_reviewed.json` contains allowlisted values actually returned by
Hermes --usage-file; session_id and any failure text were not retained. The raw
report hash is preserved, but the temporary original was not archived. No full
conversation, system prompt, SOUL, memory, history, title text or credentials were
read or copied into this evidence. stdout was reviewed: only OK was retained.

Main turn: input 570, output 2, cache-read 224, cache-write 0, reasoning 0,
native total 796, native api_calls 1. Hermes also reports title_generation:
input 38, output 9, cache-read 224, cache-write/reasoning 0, native total 47,
api_calls 1. Aggregate native totals: 843 tokens and api_calls 2.

These are Hermes-normalized counters, not retained raw provider usage. Present
zeros are not proof that the provider explicitly reported zero. Main total 796
is a canonical sum; auxiliary 47 and aggregate 843 are derived by the native
oneshot code. Auxiliary total excludes its separately reported cache buckets;
do not silently reinterpret or recompute this as verified billable usage.
`service_tier` is null; raw usage fields and retry count are unavailable.
`api_calls` is not a network request count and does not rule out internal retries.
The 0.0 USD value is an estimate from provider_models_api, not billed-cost proof.
Detailed semantics/formulas/source hashes are in counter_provenance.json.

## Plugin status

**This is native Hermes usage evidence, not plugin observability capture.** No
plugin events were collected or plugin dispatch verified. A future separate test
must verify the plugin opt-in, loading/registration and emitted real hook events
under this provider/model, with explicit authorization and without copying private
context. It must correlate normalized counters and preserve absent/zero/derived
states; this native report cannot be relabeled as a plugin capture retroactively.

No files of the rover, observability implementation, concurrent work or previous
evidence were edited. No staging, commit or push. Manifest hashes cover only the
reviewed material here, not the discarded raw report or any private Hermes state.
