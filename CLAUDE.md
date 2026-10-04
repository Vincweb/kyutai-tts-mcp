# CLAUDE.md

Maintainer notes for working *on* this repo. User-facing docs live in
[README.md](README.md) — don't duplicate them here. This file covers what
isn't obvious from reading the code.

## What this repo is

Two independent halves in one repo:

| Path | What | Ships as |
|---|---|---|
| `mcp/` | The Python MCP server (`speak` / `stop_speaking` / `status`) | PyPI package `kyutai-tts-mcp` |
| `plugin/` | Claude Code plugin — manifest, `.mcp.json` wiring, `/voice-mode` skill | GitHub marketplace `vincweb-tools` |

`plugin/.mcp.json` launches the server with plain `uvx kyutai-tts-mcp`, i.e.
**from PyPI, unpinned**. Consequence: editing `mcp/src/` changes nothing for
an installed plugin until a new version is published. See *Releasing*.

Three files under `mcp/src/kyutai_tts_mcp/`:

- [__main__.py](mcp/src/kyutai_tts_mcp/__main__.py) — MCP tools, queues,
  threads, audio output, CLI. Organised by `# ──` section markers.
- [onnx_tts.py](mcp/src/kyutai_tts_mcp/onnx_tts.py) — the inference engine:
  downloads a bundle, runs the three ONNX graphs, loads voices.
- [text_chunking.py](mcp/src/kyutai_tts_mcp/text_chunking.py) — vendored
  from pocket-tts 3.3.0 (MIT). Keep it a near-verbatim copy so upstream
  fixes can be diffed in; the only change is the tokenizer type.

There is **no PyTorch and no pocket-tts dependency** since 0.9.0. The
models are the int8 ONNX bundles in
[Vincweb/pocket-tts-french-onnx](https://huggingface.co/Vincweb/pocket-tts-french-onnx)
and [-english-onnx](https://huggingface.co/Vincweb/pocket-tts-english-onnx),
built for Volume Board (browser) and reused here.

## Testing — there is no test suite

There are no unit tests, and there's no meaningful way to smoke-test the
server by importing it: the failure modes live in the MCP handshake, the
model load, and CoreAudio. Verify by driving stdio JSON-RPC yourself.

`uv run kyutai-tts-mcp --help` catches import-level breakage. For anything
real, write a throwaway client that spawns `uv run kyutai-tts-mcp` (cwd
`mcp/`) and speaks the protocol: `initialize` → `notifications/initialized`
→ `tools/list` → `tools/call`. Two gotchas:

- **Don't pipe a static file into stdin.** EOF closes the server before it
  processes later requests. Keep stdin open and read responses line by line.
- **`speak()` returns immediately** — it only enqueues. To confirm audio
  actually rendered, poll `status()` until `gen_in_flight` is false and
  `audio_buffer` is 0, and check `last_error`. Then sleep ~2 s before
  closing stdin, or `atexit` aborts the PortAudio stream mid-tail.

The first `speak()` in a language downloads ~115 MB of model, and every
`speak()` plays sound on the machine you're running on. Say so before you do
it. To test the pipeline silently, import the module and replace
`sd.OutputStream` with a fake whose `write()` sleeps `len(chunk) / sr`.

## Hard constraints

- **`mcp>=2.0.0`** — the SDK dropped `mcp.server.fastmcp` in 2.0; the class
  is `MCPServer` from `mcp.server.mcpserver`. `@mcp.tool()` and `mcp.run()`
  are unchanged. Never reintroduce a `FastMCP` import.
- **Model repos are pinned** to a commit in `onnx_tts.BUNDLES`. They also
  serve Volume Board, so following `main` would ship browser-motivated
  changes to every uvx install. Bump the SHA deliberately, after testing.
- **`BUNDLE_FORMAT = "volume-board/pocket-tts-onnx@1"`** and
  `sampler_decode_steps == 1` are checked at load. The one-step LSD sampling
  in `_generate_chunk` is only correct for 1 step.
- **Voices** other than the bundled one come from
  `kyutai/pocket-tts-without-voice-cloning` at the revision in the
  manifest's `source.voice`. A voice state only fits the weights it was
  computed with — never point it at another revision, and don't accept
  arbitrary `.safetensors` paths (a 24-layer state loads silently and
  sounds wrong).
- **`onnxruntime>=1.20`, not higher.** 1.24+ ships macOS wheels for Apple
  Silicon on macOS 14+ only; Intel Macs and macOS 13 resolve to 1.23.x.
  The bundles are verified on 1.20.1 and 1.23.2.
- **`requires-python = ">=3.11,<3.15"`** — onnxruntime wheel coverage.
- **Unsupported languages raise `ToolError`**, not `ValueError`: mcp 2.x
  replaces any other exception's text with a bare "Error executing tool".
- **macOS / CoreAudio** via `sounddevice`. No Linux CI for the audio path.

## Threading invariants

Two long-lived daemon threads and two queues; breaking these produces
gaps, deadlocks, or audio that won't stop:

- `_gen_q` → generation thread → `_audio_q` → writer thread → OutputStream.
- The OutputStream is opened **without a callback**; the writer thread calls
  `stream.write()` in blocking mode so PortAudio absorbs all timing jitter
  and Python never has a realtime deadline. Don't switch to callback mode.
- `_cancel_event` is checked in *both* loops. `_abort_all()` is the single
  path shared by `stop_speaking()` and `speak(interrupt=True)` — set the
  event, drain both queues, `stream.abort()`. Keep it that way rather than
  adding a second abort path.
- `_cancel_event` is also passed as `stop` to `OnnxTTS.generate`, which
  checks it before every 80 ms frame. Generation runs on the generation
  thread itself (no helper threads), so `break`ing out leaves nothing
  running.
- Caches are guarded by their own locks (`_models_lock`, `_voice_states_lock`,
  `_stream_lock`). `_ensure_model` holds `_models_lock` across the heavy
  load on purpose — concurrent first-calls in the same language must not
  load twice.
- Both bundles share the Mimi codec at 24 kHz, so **one**
  OutputStream serves every language. `_ensure_model` raises loudly if a
  language ever reports a different sample rate — don't soften that into a
  resample.

## Versioning & releasing

Three files must move together or `/plugin install` and marketplace sync
break:

- `mcp/pyproject.toml` → `version`
- `plugin/.claude-plugin/plugin.json` → `version`
- `.claude-plugin/marketplace.json` → `plugins[0].version`

Use the `/bump-version` skill ([.claude/skills/bump-version/SKILL.md](.claude/skills/bump-version/SKILL.md))
— it does the three-file edit, the commit, and the local tag. It refuses to
bump on a dirty tree or on out-of-sync versions.

Publishing is **two steps and the second is outward-facing**:

```bash
git push origin main && git push origin vX.Y.Z
gh release create vX.Y.Z --generate-notes   # ← triggers PyPI
```

Creating the GitHub release is what fires
[.github/workflows/publish.yml](.github/workflows/publish.yml), which builds
`mcp/` and publishes to PyPI over OIDC Trusted Publishing (no token in the
repo). PyPI versions are immutable — never publish without the user asking.

Regenerate `mcp/uv.lock` when dependency constraints change. Note that a
relock with a newer `uv` rewrites unrelated platform markers; that noise is
expected, `uv lock --check` is the thing to confirm.

## Conventions

- Conventional Commits (`feat(scope):`, `fix:`, `refactor:`, `docs:`,
  `chore:`, `ci:`), except version bumps which use `vX.Y.Z: <summary>`.
- **No `Co-Authored-By` trailer.** [.claude/settings.json](.claude/settings.json)
  sets `attribution.commit: ""`. History before that setting has trailers,
  and the `bump-version` skill still prescribes one — the setting wins;
  the skill text is stale on this point.
- `mcp/README.md` is the **PyPI landing page**, a condensed subset of the
  root README. When you change shared content (tool table, config table,
  install snippet), update both.
- The root README has a `## Versioning` table — add a row for notable
  releases only, not for chores.
- [ROADMAP.md](ROADMAP.md) records deliberate *non*-goals (no logo, no docs
  site, no Discord, Docker deferred). Check it before proposing those.

## Sibling project

[voxtral-mcp](https://github.com/Vincweb/voxtral-mcp) is the same
architecture around Mistral Voxtral 4B, with an intentionally identical MCP
API and a shared `/voice-mode` skill. API changes here usually want a
matching change there.
