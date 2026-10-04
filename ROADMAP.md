# Roadmap — kyutai-tts-mcp

Current state: **v0.5.0 published on PyPI** (`uvx kyutai-tts-mcp` or
`uv tool install kyutai-tts-mcp`). Multi-language at runtime, in-process
model, native streaming, write-mode sounddevice. Repo split into `mcp/`
(Python package) and `plugin/` (Claude Code marketplace plugin). GitHub
Actions workflow publishes via OIDC Trusted Publishing on release
creation — no long-lived token to manage.

Done since the previous iteration: PyPI publication, OIDC release
workflow, repo restructure, full rename from `pocket-tts-mcp` (the name
was already taken on PyPI by an unrelated project wrapping
KoljaB/PocketTTS).

---

## 1. Make the repo more credible — minimum viable

Without overdoing it (no fake stars, no buzzword salad). Order by ROI:

- **Sample audio in the README** — host a 5-second `estelle.wav` in the
  repo and link to it as an `<audio>` element or via the GitHub raw URL.
  People judge a TTS project by what it sounds like in 5 seconds.
- **Shields.io badges**, restraint: PyPI version, license (MIT), Python
  (3.10-3.13). Skip the build-status badge unless there's something
  interesting in CI beyond the publish workflow.
- **CHANGELOG.md** generated from git log. Two lines per version max.
- **GIF or asciinema of `/voice-mode`** in action (Claude Code session).
  Highest signal/effort ratio.
- **One-line tagline in repo description on GitHub** — re-verify after
  the rename has fully propagated through GitHub's UI/search.

Skip for now:

- ❌ Logo / branding (not worth it for a wrapper).
- ❌ A documentation site (README is enough until there's enough surface to
  warrant subpages).
- ❌ Hugging Face Space demo (Voxtral might benefit; pocket-tts is small
  enough that local install is the demo).
- ❌ Discord / community channel.

---

## 2. Use mcp-submit to register on directories

**Why**: passive discoverability. Glama auto-indexes from GitHub (give it
a week post-rename), but the long tail of directories (mcp.so,
mcpservers.org, Smithery, PulseMCP, etc.) needs explicit submission. The
OSS tool [mcp-submit] pushes to 10+ in one command.

**Effort**: ~15 min (install tool, run with repo URL, confirm submissions).

**Worth it once** the README has a demo (GIF or sample audio link) so the
listings don't look empty and unloved. The PyPI install line is already
there.

---

## 3. Docker image

**Why**: easy headless / Linux use cases. The server is CPU-only ONNX Runtime, so
Docker works fine — Intel/AMD/ARM Linux all good. Useful for non-Mac users
who want pocket-tts behind an MCP-compatible client.

**Caveat**: the **MCP transport is stdio**, so a containerised MCP server
needs the client to attach to the container's stdio (`docker run -i ...`).
That's awkward in Claude Code. So Docker is mainly useful for:

- A standalone REST/WS server image people can run as a microservice. Out
  of scope for this MCP repo but could be a separate `kyutai-tts-server`
  repo if there's demand.
- Power users running their MCP client inside the same container.

**Effort**: low for the image itself (~30 min), but the UX story isn't
clean for an MCP. **Defer** unless someone asks for it.

---

## Priority order (current best guess)

1. **Sample audio + GIF in README** — credibility per-eyeball.
2. **PyPI / license / Python badges** — passive trust signal.
3. **mcp-submit run** — once #1 is done so listings have content.
4. **Docker** — only if someone asks.

---

## Open questions

- Should the repo description on GitHub mention "Claude Code plugin" or
  lead with "MCP server"? Currently leads with "Claude Code". Consider
  swapping after the PyPI listing settles into search results.
- Worth adding a `CITATION.cff` so academic users can cite the wrapper?
  Probably not — they'd cite Kyutai pocket-tts, not the glue.
- Should we provide a tiny benchmark script under `bench/` so users can
  reproduce the TTFA numbers in the README? Yes if asked, no by default.
