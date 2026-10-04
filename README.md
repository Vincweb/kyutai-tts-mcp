# kyutai-tts-mcp

Local-only voice for Claude Code on macOS, via [Kyutai Pocket TTS](https://github.com/kyutai-labs/pocket-tts).
No cloud, no API keys, no rate limits.

- 🇫🇷 French (Estelle), 🇬🇧 English (Alba — multilingual neutral voice), plus Spanish, German, Italian, Portuguese, Dutch
- **TTFA ~80–200 ms** thanks to native streaming via the pocket-tts Python API
- ~4-5× real-time generation on Apple Silicon / Intel CPU — model stays warm in RAM
- Non-blocking `speak()`, gap-free playback via `sounddevice` write-mode
- Bundled `/voice-mode` skill — Claude speaks summaries of its answers automatically
- ~600 MB venv, ~1 GB model cache — lightweight relative to bigger TTS models

> 💡 Companion plugin: [**voxtral-mcp**](https://github.com/Vincweb/voxtral-mcp)
> wraps Mistral Voxtral 4B (more natural voice but 5× more RAM and Apple Silicon
> only). See the [comparison table](#kyutai-tts-mcp-vs-voxtral-mcp) below — both
> plugins share the same MCP API and `/voice-mode` skill.

## Requirements

- macOS (Apple Silicon recommended; Intel works too — model is CPU-only)
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
        "french_24l"
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

Replace `french_24l` with whatever language you mostly speak (`english`,
`spanish_24l`, `german_24l`, `italian_24l`, `portuguese_24l`, `dutch_24l`). Per-call
`language=` always wins anyway — this is just the default. For other
knobs (voice, quantize, device, max tokens), see the
[Configuration](#configuration) table below.

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
[PyPI](https://pypi.org/project/kyutai-tts-mcp/) (~30 s) and the Kyutai
model downloads from Hugging Face (~1 GB, once per language). Subsequent
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

The first call after a Claude Code restart takes ~3–5 s (model load).
Subsequent calls have **~80–200 ms TTFA** thanks to native streaming — you
hear the start of the audio almost immediately, even on long texts.

## MCP tools exposed

| Tool | Purpose |
|---|---|
| `speak(text, voice?, language?, interrupt?)` | Generate audio for `text` and **queue it for background playback**. Returns immediately; streaming generation feeds the audio stream while you keep working. By default, multiple calls queue and play sequentially — including across conversational turns. Pass `interrupt=True` to abort current playback and clear the queue first (use when the user has clearly interrupted). Pass `language=` per call to switch model on the fly (`english`, `spanish_24l`, etc.) — first use of a new language pays a one-time ~3-5 s load + ~1 GB RAM, then cached. |
| `stop_speaking()` | Stop playback, drop the queue, cancel in-flight generation. Use when the user explicitly asked to be quiet ("mute" / "silence"). For mid-turn interruption where you still want to speak something new, use `speak(text, interrupt=True)` instead — it does both atomically. |
| `status()` | Report loaded languages, sample rate, cached voices, queue depths, last error. |

## Configuration

The default language is set via the `--language` CLI flag (in the `args`
block of `.mcp.json`). Other knobs go in the `env` block:

| Setting | Where | Default | Notes |
|---|---|---|---|
| `--language` | `args` | `french_24l` | Default language used when `speak()` is called without an explicit `language=` arg. Also: `english` (= `english_2026-09`), `english_2026-01`, `english_2026-04`, `spanish_24l`, `german_24l`, `italian_24l`, `portuguese_24l`, `dutch_24l`. Each `_24l` model also has a lighter 6-layer variant without the suffix (`french`, `spanish`, …). Can also be set via `KYUTAI_TTS_LANGUAGE` env var (the CLI flag wins). |
| `KYUTAI_TTS_VOICE` | `env` | (language default) | Built-in voice name to use when `speak()` is called without an explicit `voice` arg |
| `KYUTAI_TTS_DEVICE` | `env` | `cpu` | PyTorch device. Stick with `cpu` on Apple Silicon — `mps` is unsupported by the pocket-tts model. |
| `KYUTAI_TTS_QUANTIZE` | `env` | `0` | Set to `1` for int8 quantization (smaller RAM, slightly slower). |
| `KYUTAI_TTS_MAX_TOKENS` | `env` | `50` | Max tokens per streaming chunk. |

## Voices

Pass `voice="..."` in your conversation ("parle avec la voix de Rafael"):

| Voice | Pair with `language=` | Notes |
|---|---|---|
| `estelle` | `french_24l` | default for French |
| `alba` | `english` | neutral, works in EN |
| `juergen` | `german_24l` | |
| `lola` | `spanish_24l` | |
| `giovanni` | `italian_24l` | |
| `rafael` | `portuguese_24l` | |
| `daan` | `dutch_24l` | |

You can also pass any Hugging Face voice URL (`hf://kyutai/tts-voices/...`)
to use one of Kyutai's published voices, or use a custom voice — see below.

## Voice cloning (custom voices)

Pocket-tts can clone a voice from a short audio sample. The cloning is
**100 % local** — your audio never leaves the machine — but the
cloning-enabled model checkpoint is gated on Hugging Face, so there's a
one-time setup before you can pass a custom audio path to `speak()`.

### 1. One-time Hugging Face setup

1. Create a (free) account at [huggingface.co](https://huggingface.co/join).
2. Visit [huggingface.co/kyutai/pocket-tts](https://huggingface.co/kyutai/pocket-tts)
   and click **"Agree and access repository"** to accept the terms.
3. Generate a [read token](https://huggingface.co/settings/tokens).
4. Install the CLI and authenticate:

   ```bash
   uv tool install huggingface-hub
   hf auth login          # paste the token
   ```

5. Clear any previously-cached non-cloning checkpoint so the cloning-
   enabled one downloads on next run:

   ```bash
   rm -rf ~/.cache/huggingface/hub/models--kyutai--pocket-tts
   ```

On the next `speak()` call, the cloning-capable checkpoint (~1 GB)
downloads once. Without this setup, pocket-tts silently falls back to a
non-cloning checkpoint and any custom-audio voice raises a
`ValueError(VOICE_CLONING_UNSUPPORTED)`.

### 2. Record a sample

Recommendations for a good clone:

- **10-30 seconds**, single speaker (you), clean audio (no music, no
  background conversation)
- **Neutral reading style** (a paragraph from a book) beats spontaneous
  speech — avoids cloning "uh / um" fillers
- **Match the target language** (FR sample → FR speech)
- Any format pocket-tts can decode: `.wav`, `.mp3`, `.flac`, `.m4a`, …
  Auto-resampled to 24 kHz.

### 3. Use the sample directly (lazy)

The simplest path — pass the audio file to `speak()`:

```
speak(text="…", voice="/Users/you/voices/yours.wav", language="french_24l")
```

The first call encodes the sample (~2-5 s) and caches the voice state for
the rest of the session. Restarting the server discards the cache.

### 4. Pre-extract for instant loading (`.safetensors`)

If you use the same voice across sessions, pre-extract it once with the
`extract-voice` CLI subcommand:

```bash
uvx kyutai-tts-mcp extract-voice \
  --audio ~/voices/yours.wav \
  --out ~/voices/yours.safetensors \
  --language french_24l \
  --truncate
```

Then pass the `.safetensors` file to `speak(voice=...)` — loading is
near-instant (skips Mimi encoding + latent projection):

```
speak(text="…", voice="/Users/you/voices/yours.safetensors", language="french_24l")
```

The `.safetensors` file is small (a few KB), portable, and contains only
the voice state — no audio.

## Architecture

```
Claude Code  ──MCP stdio──▶  kyutai-tts-mcp (Python, MCPServer)
                                  │
                                  │  speak(text)
                                  ▼
                              gen queue
                                  │
                                  ▼
                       generation thread
                            tts_model.generate_audio_stream(...)
                            yields torch.Tensor chunks (~80 ms each)
                                  │
                                  ▼
                          audio_q (numpy float32)
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

- **In-process model**: pocket-tts is loaded directly via `TTSModel.load_model()`.
  No external daemon, no HTTP, no temp WAVs, no `afplay` subprocess.
- **Native streaming**: chunks are produced by `generate_audio_stream` as the
  model generates — first chunk arrives in ~80–200 ms, the rest stream in
  while playback is already happening.
- **Write-mode sounddevice**: the OutputStream is opened WITHOUT a callback,
  so a Python writer thread calls `stream.write(chunk)` in blocking mode.
  PortAudio's internal buffer absorbs all timing variation, and Python never
  has to meet realtime deadlines — yielding clean, gap-free playback.
- **Voice state cache**: `_voice_states` maps `(language, voice)` → state, so
  the expensive `get_state_for_audio_prompt` call only runs once per (language, voice) pair.
- **Per-language model cache**: `_models` maps language → loaded `TTSModel`.
  The first `speak()` in a new language pays ~3-5 s and ~1 GB RAM; subsequent
  calls in that language are instant. All pocket-tts models share the mimi
  codec at 24 kHz, so one `OutputStream` serves every language.

## Repo layout

```
kyutai-tts-mcp/                          repo root
├── mcp/                                 the MCP server (published to PyPI)
│   ├── src/kyutai_tts_mcp/              Python source
│   ├── pyproject.toml                   declares mcp + pocket-tts + sounddevice deps
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
| Parameters | ~100 M | 4 B (40× larger) |
| Voice quality | Synthetic but intelligible | More natural prosody |
| **TTFA** (post-load) | **~80–200 ms** ⭐ | ~2 s |
| Generation speed | ~4–5× real-time | ~2.4× real-time |
| Resident RAM | ~1 GB | ~3 GB |
| Disk (model cache) | ~1 GB | ~2.5 GB |
| Apple Silicon required | No (works on Intel too) | Yes (MLX-only) |
| Languages | EN, FR, ES, DE, IT, PT, NL | EN, FR, ES, DE, IT, PT, NL, HI, AR |
| Model licence | Permissive (Kyutai) | CC BY-NC 4.0 (non-commercial) |
| Architecture | In-process via PyTorch | In-process via mlx-audio |

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
# Optionally delete the cached model:
rm -rf ~/.cache/huggingface/hub/models--kyutai--pocket-tts
```

## Why this and not the alternatives

| Path | Pros | Cons |
|---|---|---|
| ElevenLabs MCP | Best quality | Cloud, API key, costs |
| macOS `say` MCP | Free, instant | Robotic voice |
| Hook + regex extraction of `<speak>` tags | No MCP needed | Fragile: transcript parsing, race conditions, debugging hell |
| [voxtral-mcp](https://github.com/Vincweb/voxtral-mcp) | More natural voice, 9 languages | 3× the RAM, ~10× slower TTFA, non-commercial licence, Apple Silicon only |
| **This (kyutai-tts-mcp)** | Local, free, fastest local TTFA, permissive licence, ~1 GB total footprint | Voice is synthetic — not ElevenLabs / Voxtral level |

## License

MIT — see [LICENSE](LICENSE).

## Credits

- [Kyutai Labs](https://kyutai.org/) for Pocket TTS — the actual hard work
- [Anthropic](https://anthropic.com/) for Claude Code & the MCP spec
- This wrapper: just glue
