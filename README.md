# kyutai-tts-mcp

Local-only voice for Claude Code on macOS, via [Kyutai Pocket TTS](https://github.com/kyutai-labs/pocket-tts).
No cloud, no API keys, no rate limits.

- 🇫🇷 French (Estelle) and 🇬🇧 English (Alba), plus 24 other Kyutai voices usable in both
- **No PyTorch**: runs on [ONNX Runtime](https://onnxruntime.ai/) with int8 exports of Kyutai's
  6-layer model ([French](https://huggingface.co/Vincweb/pocket-tts-french-onnx),
  [English](https://huggingface.co/Vincweb/pocket-tts-english-onnx))
- **TTFA ~20 ms**, ~9× real-time on an Apple Silicon CPU, frame-by-frame streaming
- Non-blocking `speak()`, gap-free playback via `sounddevice` write-mode
- Bundled `/voice-mode` skill — Claude speaks summaries of its answers automatically
- ~160 MB venv, ~115 MB model per language, ~330 MB RAM

> 💡 Companion plugin: [**voxtral-mcp**](https://github.com/Vincweb/voxtral-mcp)
> wraps Mistral Voxtral 4B (more natural voice but ~10× more RAM and Apple Silicon
> only). See the [comparison table](#kyutai-tts-mcp-vs-voxtral-mcp) below — both
> plugins share the same MCP API and `/voice-mode` skill.

## Requirements

- macOS 13+ (Apple Silicon recommended). Intel Macs should work with Python
  3.11–3.13, the last versions ONNX Runtime ships Intel wheels for — untested.
- [uv](https://docs.astral.sh/uv/) — install with `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Claude Code (CLI, desktop app, or Cursor extension)

## Install

### Option A — standalone MCP (works with any MCP client)

This is the universal path: a regular MCP server you wire into any client
that speaks the Model Context Protocol (Claude Desktop, Claude Code CLI,
Cursor's Claude Code extension, etc.).

Add this entry to the `mcpServers` block of your project's `.mcp.json`
(or `~/.claude.json` for a global install):

```json
{
  "mcpServers": {
    "kyutai-tts": {
      "command": "uvx",
      "args": [
        "kyutai-tts-mcp",
        "--language",
        "french"
      ]
    }
  }
}
```

`uvx` pulls the package from [PyPI](https://pypi.org/project/kyutai-tts-mcp/)
on first launch, caches the venv, and spawns the MCP. No clone, no local
install script. If you'd rather have the binary persistent in `~/.local/bin`,
`uv tool install kyutai-tts-mcp` once and use `"command": "kyutai-tts-mcp"` in
the JSON instead.

Replace `french` with `english` if that's what you mostly speak. Per-call
`language=` always wins anyway — this is just the default. For other
knobs (voice, max tokens), see the [Configuration](#configuration) table
below.

If you want the bundled `/voice-mode` skill (only relevant in Claude
Code / Cursor), also drop it in:

```bash
mkdir -p ~/.claude/skills/voice-mode
curl -sLo ~/.claude/skills/voice-mode/SKILL.md \
  https://raw.githubusercontent.com/Vincweb/kyutai-tts-mcp/main/plugin/skills/voice-mode/SKILL.md
```

Then restart your MCP client.

### Option B — Claude Code plugin (recommended if you use Claude Code or Cursor)

If you're already on Claude Code (CLI, desktop, or the Cursor extension),
the plugin path bundles the MCP server, the `/voice-mode` skill, and the
wiring in one step:

```
/plugin marketplace add Vincweb/kyutai-tts-mcp
/plugin install kyutai-tts@vincweb-tools
```

Restart Claude Code. On first use, `uvx` pulls `kyutai-tts-mcp` from
[PyPI](https://pypi.org/project/kyutai-tts-mcp/) (a few seconds) and the
model downloads from Hugging Face (~115 MB, once per language). Subsequent
runs are instant.

> 💡 The plugin layer is a Claude Code feature; Cursor inherits it because
> it ships the Claude Code CLI. Claude Desktop (the native app) and
> non-Claude MCP clients don't expose `/plugin install` — use Option A
> there.

## Use

In any conversation, type **`/voice-mode`** or say **"parle-moi"** / **"voice mode"**.
Claude will:

- Reply with normal text (markdown, code, links — unchanged)
- Call `speak()` with a short spoken summary of the turn (1–3 sentences,
  audio plays in the background while Claude continues with other work)
- Let consecutive turns' audio queue and play sequentially — no choppy
  cuts mid-sentence. When you interrupt ("non", "wait"), Claude calls
  `speak(..., interrupt=True)` to abort and restart cleanly.
- Skip speaking pure code dumps / long diffs

Stop with **"mute"**, **"silence"**, **"stop talking"**, **"arrête de parler"**.

The first call after a Claude Code restart loads the model in well under a
second (once it's downloaded). Every call has **~20 ms TTFA**: audio is
decoded and played 80 ms frame by frame while the rest is still being
generated, so you hear the start almost immediately, even on long texts.

## MCP tools exposed

| Tool | Purpose |
|---|---|
| `speak(text, voice?, language?, interrupt?)` | Generate audio for `text` and **queue it for background playback**. Returns immediately; streaming generation feeds the audio stream while you keep working. By default, multiple calls queue and play sequentially — including across conversational turns. Pass `interrupt=True` to abort current playback and clear the queue first (use when the user has clearly interrupted). Pass `language=` per call to switch between `french` and `english` on the fly — first use of a language downloads its model once (~115 MB), then it stays cached. An unsupported language returns an error listing the supported ones. |
| `stop_speaking()` | Stop playback, drop the queue, cancel in-flight generation. Use when the user explicitly asked to be quiet ("mute" / "silence"). For mid-turn interruption where you still want to speak something new, use `speak(text, interrupt=True)` instead — it does both atomically. |
| `status()` | Report loaded languages, sample rate, cached voices, queue depths, last error. |

## Configuration

The default language is set via the `--language` CLI flag (in the `args`
block of `.mcp.json`). Other knobs go in the `env` block:

| Setting | Where | Default | Notes |
|---|---|---|---|
| `--language` | `args` | `french` | Default language used when `speak()` is called without an explicit `language=` arg: `french` or `english`. Older names (`french_24l`, `english_2026-04`, …) are accepted as aliases, so existing configs keep working. Can also be set via `KYUTAI_TTS_LANGUAGE` env var (the CLI flag wins). |
| `KYUTAI_TTS_VOICE` | `env` | (language default) | Voice name to use when `speak()` is called without an explicit `voice` arg |
| `KYUTAI_TTS_MAX_TOKENS` | `env` | `50` | Max tokens per generated chunk (long texts are split on sentence boundaries). |

## Voices

Pass `voice="..."` in your conversation ("parle avec la voix de Rafael").
The defaults are **`estelle`** for French and **`alba`** for English. Any of
Kyutai's predefined voices works in both languages:

`alba`, `anna`, `azelma`, `bill_boerst`, `caro_davy`, `charles`, `cosette`,
`eponine`, `estelle`, `eve`, `fantine`, `george`, `giovanni`, `jane`,
`javert`, `jean`, `juergen`, `lola`, `marius`, `mary`, `michael`, `paul`,
`peter_yearsley`, `rafael`, `stuart_bell`, `vera`

The two defaults ship with the model; any other voice is fetched once
(~5 MB) from [`kyutai/pocket-tts-without-voice-cloning`](https://huggingface.co/kyutai/pocket-tts-without-voice-cloning),
at the exact weights revision the model was exported from.

> **Voice cloning is gone since 0.9.0.** It needs Mimi's encoder, which the
> ONNX exports don't include. If you rely on it, or on Spanish, German,
> Italian, Portuguese or Dutch, stay on the last PyTorch release:
> `uvx "kyutai-tts-mcp<0.9" --language french_24l`.

## Architecture

```
Claude Code  ──MCP stdio──▶  kyutai-tts-mcp (Python, MCPServer)
                                  │
                                  │  speak(text)
                                  ▼
                              gen queue
                                  │
                                  ▼
                       generation thread  (onnx_tts.py)
                            flow LM step → flow head → Mimi decoder
                            yields one float32 frame per step (80 ms)
                                  │
                                  ▼
                               audio_q
                                  │
                                  ▼
                       writer thread → stream.write() blocking
                                  │
                                  ▼
                       sounddevice OutputStream (write-mode)
                                  │
                                  ▼
                              CoreAudio
```

Key design choices:

- **ONNX Runtime, no PyTorch**: each language is three int8 ONNX graphs
  (flow LM backbone, flow head, Mimi decoder), a float16 text lookup table,
  the tokenizer, and a `manifest.json` carrying the state layout and the
  generation parameters. The generation loop mirrors pocket-tts's
  `generate_audio_stream`; the text preparation and sentence chunking are
  vendored from pocket-tts.
- **Frame-by-frame streaming**: every generated latent is decoded right
  away, so the first 80 ms of audio is ready ~20 ms after `speak()`.
  Cancellation is checked before every frame.
- **Write-mode sounddevice**: the OutputStream is opened WITHOUT a callback,
  so a Python writer thread calls `stream.write(chunk)` in blocking mode.
  PortAudio's internal buffer absorbs all timing variation, and Python never
  has to meet realtime deadlines — yielding clean, gap-free playback.
- **Voice state cache**: `_voice_states` maps `(language, voice)` → the flow
  LM's key/value cache for that voice, loaded once per pair.
- **Per-language model cache**: `_models` maps language → loaded bundle.
  Both languages share the Mimi codec at 24 kHz, so one `OutputStream`
  serves both.
- **Pinned model revisions**: the Hugging Face repos are pinned to a commit
  in `onnx_tts.py`, so a change to the model repos never reaches existing
  installs without a release.

## Repo layout

```
kyutai-tts-mcp/                          repo root
├── mcp/                                 the MCP server (published to PyPI)
│   ├── src/kyutai_tts_mcp/              Python source
│   ├── pyproject.toml                   declares mcp + onnxruntime + sounddevice deps
│   └── uv.lock
├── plugin/                              the Claude Code plugin
│   ├── .claude-plugin/plugin.json       plugin manifest
│   ├── .mcp.json                        MCP wiring — launches `mcp/` via uvx
│   └── skills/voice-mode/SKILL.md       /voice-mode skill
├── .claude-plugin/
│   └── marketplace.json                 declares the marketplace
├── README.md
└── LICENSE
```

The two halves are independent: `mcp/` can be installed and used on its
own (Option A), and `plugin/` just declares how Claude Code should
discover and wire it up (Option B).

## Versioning

| Version | Highlights |
|---|---|
| **0.8.0** | **pocket-tts 3.3.** Fixes `extract-voice`, which crashed on import with pocket-tts ≥ 3.1. Cancellation (`stop_speaking()` / `interrupt=True`) now also stops pocket-tts's internal generation threads. Adds Dutch (`dutch_24l`, voice `daan`). Model weights moved to a new revision upstream: the first `speak()` after upgrading re-downloads the model. |
| **0.6.0** | **`speak(interrupt=True)`** to abort current playback before speaking (replaces the always-`stop_speaking()`-first pattern — audio now queues across turns naturally). **`kyutai-tts-mcp extract-voice` CLI** pre-extracts voice states to `.safetensors` for instant loading. Voice cloning docs (HF auth + recording recommendations). |
| **0.5.0** | **Renamed `pocket-tts-mcp` → `kyutai-tts-mcp`** (the previous name was taken on PyPI by an unrelated project). **First PyPI release.** **Multi-language at runtime** — `speak(text, voice?, language?)` switches model on the fly (lazy load, ~3-5 s on first use). Repo split into `mcp/` (Python package) + `plugin/` (Claude Code wrapper); `install.sh` retired in favor of `uvx`. CI release workflow via OIDC Trusted Publishing. |
| 0.4.0     | **In-process model + native streaming + write-mode sounddevice.** Drops the `pocket-tts serve` HTTP daemon entirely. TTFA drops from ~3 s to ~80–200 ms. Mirrors the [voxtral-mcp](https://github.com/Vincweb/voxtral-mcp) v0.4.0 architecture. |
| 0.3.0     | Non-blocking `speak()` + internal playback queue + `stop_speaking()` tool (still daemon-backed). |
| 0.2.0     | Bundles the `pocket-tts` CLI as a dependency. Pinned Python `>=3.10,<3.14`. |
| 0.1.0     | Initial plugin form (marketplace + plugin manifest + bundled MCP + skill). |

## kyutai-tts-mcp vs voxtral-mcp

Both plugins ship with the same MCP API (`speak`, `stop_speaking`, `status`),
the same `/voice-mode` skill, and the same in-process Python + sounddevice
write-mode pipeline (v0.4.0 on both sides). They differ in the model they
wrap:

|   | **kyutai-tts-mcp** | [**voxtral-mcp**](https://github.com/Vincweb/voxtral-mcp) |
|---|---|---|
| Model | Kyutai Pocket TTS | Mistral Voxtral 4B |
| Parameters | ~55 M est. (6 layers, int8) | 4 B |
| Voice quality | Synthetic but intelligible | More natural prosody |
| **TTFA** (post-load) | **~20 ms** ⭐ | ~2 s |
| Generation speed | ~9× real-time | ~2.4× real-time |
| Resident RAM | ~330 MB | ~3 GB |
| Disk (model cache) | ~115 MB per language | ~2.5 GB |
| Apple Silicon required | No (Intel: Python ≤ 3.13, untested) | Yes (MLX-only) |
| Languages | EN, FR | EN, FR, ES, DE, IT, PT, NL, HI, AR |
| Model licence | CC BY 4.0 (Kyutai) | CC BY-NC 4.0 (non-commercial) |
| Architecture | In-process via ONNX Runtime | In-process via mlx-audio |

**When to pick which:**

- **kyutai-tts-mcp** for snappy short summaries (TTFA matters more than
  prosody on 1–3 sentences), low RAM footprint, multi-project workflows
  where Cursor might hold multiple MCP instances, permissive licensing,
  Intel Macs.
- **voxtral-mcp** for long narration where the voice quality difference
  is audible and you can spare 3 GB of RAM.

You can install **both** plugins side-by-side — the MCP server names
differ (`kyutai-tts` vs `voxtral`) so the tools won't collide. The shared
`/voice-mode` skill defaults to voxtral when both are available; you can
override at runtime by asking Claude to "use kyutai-tts" or "use voxtral".

## Uninstall

If installed as a plugin:
```
/plugin uninstall kyutai-tts@vincweb-tools
/plugin marketplace remove vincweb-tools
```

If installed standalone:
```bash
rm -rf ~/.claude/skills/voice-mode
# Remove the "kyutai-tts" entry from your project's .mcp.json
uv cache clean kyutai-tts-mcp   # drop the uvx-cached venv
# Optionally delete the cached models and voices:
rm -rf ~/.cache/huggingface/hub/models--Vincweb--pocket-tts-*-onnx
rm -rf ~/.cache/huggingface/hub/models--kyutai--pocket-tts-without-voice-cloning
```

## Why this and not the alternatives

| Path | Pros | Cons |
|---|---|---|
| ElevenLabs MCP | Best quality | Cloud, API key, costs |
| macOS `say` MCP | Free, instant | Robotic voice |
| Hook + regex extraction of `<speak>` tags | No MCP needed | Fragile: transcript parsing, race conditions, debugging hell |
| [voxtral-mcp](https://github.com/Vincweb/voxtral-mcp) | More natural voice, 9 languages | ~10× the RAM, ~100× slower TTFA, non-commercial licence, Apple Silicon only |
| **This (kyutai-tts-mcp)** | Local, free, fastest local TTFA, permissive licence, no PyTorch, ~300 MB total footprint | Voice is synthetic — not ElevenLabs / Voxtral level; French and English only |

## License

MIT — see [LICENSE](LICENSE). `text_chunking.py` is vendored from
[pocket-tts](https://github.com/kyutai-labs/pocket-tts) (MIT).

The model weights are Kyutai's, released under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); the ONNX
exports are an adaptation under the same licence. The `alba` voice was
recorded by Alba McKenna and is released under CC BY 4.0 — credit her
when you use it. Kyutai's terms of use apply: see the
[Pocket TTS model card](https://huggingface.co/kyutai/pocket-tts).

## Credits

- [Kyutai Labs](https://kyutai.org/) for Pocket TTS — the actual hard work
- Alba McKenna for the `alba` voice
- [Anthropic](https://anthropic.com/) for Claude Code & the MCP spec
- This wrapper: just glue
