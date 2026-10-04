# kyutai-tts-mcp

Local-only voice for any MCP client (Claude Code, Claude Desktop, Cursor,
etc.) via [Kyutai Pocket TTS](https://github.com/kyutai-labs/pocket-tts).
No cloud, no API keys, no rate limits.

- 🇫🇷 French (Estelle), 🇬🇧 English (Alba), plus Spanish, German, Italian, Portuguese, Dutch
- **TTFA ~80–200 ms** thanks to native streaming via the pocket-tts Python API
- **Multi-language at runtime** — pass `language=` per `speak()` call, models load lazily and cache
- ~4-5× real-time generation on Apple Silicon / Intel CPU
- Non-blocking `speak()`, gap-free playback via `sounddevice` write-mode
- ~600 MB venv, ~1 GB model cache per language

## Install

```bash
uvx kyutai-tts-mcp --help
```

Or persistent:

```bash
uv tool install kyutai-tts-mcp
```

Then add to your MCP client's `.mcp.json`:

```json
{
  "mcpServers": {
    "kyutai-tts": {
      "command": "uvx",
      "args": ["kyutai-tts-mcp", "--language", "french_24l"]
    }
  }
}
```

Replace `french_24l` with `english`, `spanish_24l`, `german_24l`,
`italian_24l`, `portuguese_24l`, or `dutch_24l` for your default language. Per-call
`language=` overrides this default.

## MCP tools

| Tool | Purpose |
|---|---|
| `speak(text, voice?, language?, interrupt?)` | Generate audio for `text` and queue it for background playback. Returns immediately, streaming generation. By default, calls queue and play sequentially (including across turns). Pass `interrupt=True` to abort current playback and clear the queue first. Pass `language=` to switch model on the fly. |
| `stop_speaking()` | Stop current playback, drop queue, cancel in-flight generation. Use for explicit "mute" requests. For mid-turn interruption + new speech, use `speak(..., interrupt=True)` instead. |
| `status()` | Report loaded languages, queue depths, sample rate, last error. |

## Configuration

The default language is set via `--language` (CLI) or `KYUTAI_TTS_LANGUAGE`
(env var). Other knobs (all env):

- `KYUTAI_TTS_VOICE` — default voice name
- `KYUTAI_TTS_DEVICE` — PyTorch device (default `cpu`; `mps` not supported)
- `KYUTAI_TTS_QUANTIZE` — set to `1` for int8 quantization
- `KYUTAI_TTS_MAX_TOKENS` — max tokens per streaming chunk (default `50`)

## Voice cloning

Pocket-tts can clone a voice from a short audio sample. The cloning runs
100 % locally — your audio never leaves the machine — but the
cloning-enabled model checkpoint is gated on Hugging Face. One-time
setup:

1. Accept the terms at [huggingface.co/kyutai/pocket-tts](https://huggingface.co/kyutai/pocket-tts)
2. `uv tool install huggingface-hub && hf auth login`
3. `rm -rf ~/.cache/huggingface/hub/models--kyutai--pocket-tts` to force
   re-downloading the cloning-enabled checkpoint

Then either pass the audio file directly to `speak(voice="/path/to.wav")`,
or pre-extract it as a `.safetensors` for instant loading:

```bash
uvx kyutai-tts-mcp extract-voice \
  --audio ~/voices/yours.wav \
  --out ~/voices/yours.safetensors \
  --language french_24l \
  --truncate
```

Then `speak(voice="/path/to/yours.safetensors")`. Full guide and recording
recommendations: [main repo](https://github.com/Vincweb/kyutai-tts-mcp#voice-cloning-custom-voices).

## Claude Code users

If you're on Claude Code (CLI, desktop, or via Cursor), you can install
the bundled plugin (MCP wiring + `/voice-mode` skill) in one shot:

```
/plugin marketplace add Vincweb/kyutai-tts-mcp
/plugin install kyutai-tts@vincweb-tools
```

See the [main repo](https://github.com/Vincweb/kyutai-tts-mcp) for
architecture details, voice catalog, and a side-by-side comparison with
[voxtral-mcp](https://github.com/Vincweb/voxtral-mcp).

## Requirements

- macOS (Apple Silicon recommended; Intel works — the model is CPU-only)
- Python 3.10 – 3.13
- ~1 GB free RAM per loaded language

## License

MIT. Kyutai pocket-tts itself is under its own permissive licence (see
[upstream](https://github.com/kyutai-labs/pocket-tts)).
