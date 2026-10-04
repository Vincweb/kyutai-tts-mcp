# kyutai-tts-mcp

Local-only voice for any MCP client (Claude Code, Claude Desktop, Cursor,
etc.) via [Kyutai Pocket TTS](https://github.com/kyutai-labs/pocket-tts).
No cloud, no API keys, no rate limits.

- 🇫🇷 French (Estelle) and 🇬🇧 English (Alba), plus 24 other Kyutai voices usable in both
- **No PyTorch**: runs on ONNX Runtime with int8 exports of Kyutai's 6-layer model
- **TTFA ~20 ms**, ~9× real-time on an Apple Silicon CPU, frame-by-frame streaming
- Pass `language=` per `speak()` call; models load lazily and cache
- Non-blocking `speak()`, gap-free playback via `sounddevice` write-mode
- ~160 MB venv, ~115 MB model per language, ~330 MB RAM

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
      "args": ["kyutai-tts-mcp", "--language", "french"]
    }
  }
}
```

Replace `french` with `english` for your default language. Per-call
`language=` overrides this default. Older names such as `french_24l` are
accepted as aliases.

## MCP tools

| Tool | Purpose |
|---|---|
| `speak(text, voice?, language?, interrupt?)` | Generate audio for `text` and queue it for background playback. Returns immediately, streaming generation. By default, calls queue and play sequentially (including across turns). Pass `interrupt=True` to abort current playback and clear the queue first. Pass `language=` (`french` / `english`) to switch model on the fly. |
| `stop_speaking()` | Stop current playback, drop queue, cancel in-flight generation. Use for explicit "mute" requests. For mid-turn interruption + new speech, use `speak(..., interrupt=True)` instead. |
| `status()` | Report loaded languages, queue depths, sample rate, last error. |

## Configuration

The default language is set via `--language` (CLI) or `KYUTAI_TTS_LANGUAGE`
(env var). Other knobs (all env):

- `KYUTAI_TTS_VOICE` — default voice name (`estelle` in French, `alba` in
  English; any Kyutai predefined voice works in both)
- `KYUTAI_TTS_MAX_TOKENS` — max tokens per generated chunk (default `50`)

Voice cloning and the other pocket-tts languages (Spanish, German,
Italian, Portuguese, Dutch) need PyTorch and were dropped in 0.9.0: use
`uvx "kyutai-tts-mcp<0.9"` if you rely on them.

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

- macOS 13+ (Apple Silicon recommended; Intel should work with Python 3.11–3.13, untested)
- Python 3.11 – 3.14
- ~330 MB free RAM (~570 MB with both languages loaded)

## License

MIT. The model weights are Kyutai's, under CC BY 4.0; the `alba` voice is
by Alba McKenna, CC BY 4.0. See the
[Pocket TTS model card](https://huggingface.co/kyutai/pocket-tts) for
Kyutai's terms of use.
