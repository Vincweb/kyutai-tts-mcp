---
name: voice-mode
description: "Spoken responses via Kyutai pocket-tts (local, ~80–200 ms TTFA, ~1 GB RAM, synthetic voice). Activate by saying \"parle-moi\", \"voice mode\", \"active le mode vocal\", \"réponds-moi à l'oral\", or invoking /kyutai-tts:voice-mode."
---

# Voice Mode — Kyutai pocket-tts

Activates **voice-first replies** for the remainder of this conversation. From the moment this skill is invoked until the user explicitly disables it, you must speak a short version of each response aloud via the `mcp__kyutai-tts__speak` tool, in addition to your normal text reply.

## Activation

When this skill fires, call `mcp__kyutai-tts__speak` with a brief confirmation in the user's language ("mode vocal activé, vas-y" / "voice mode on, go ahead"), then continue conversing.

## How to behave each turn

For **every** subsequent turn, follow this pattern:

1. Compose your normal text response (markdown, code blocks, links — as usual).
2. Call `mcp__kyutai-tts__speak(text=...)` once with a **spoken summary** of the response — short, natural, conversational. `speak()` is non-blocking — it returns immediately and lets streaming generation feed audio into the background queue. Multiple turns' audio queue and play sequentially; you don't have to manage the queue yourself.

The spoken summary is NOT the same as the text. It's what you'd say if reading the answer to someone in person. The text is what you'd write.

### When to interrupt instead of queuing

By default, audio from previous turns keeps playing through into the next — this is what you want most of the time (natural conversational flow, no choppy cuts). **Only when the user has clearly interrupted**, pass `interrupt=True` to abort current playback and clear the queue before this turn's speech:

- The user said "non", "wait", "attends", "stop a sec" mid-playback
- The user's message is unusually short / impatient and arrives suspiciously fast (likely cut you off)
- The user has switched topic entirely — the previous turn's audio would be stale context

```python
mcp__kyutai-tts__speak(text="...", interrupt=True)
```

If you're unsure, **don't interrupt** — let the previous audio finish. Over-interrupting cuts off the last syllable of every turn and feels jumpy.

## Rules for the spoken summary

- **Short**: 1–3 sentences, max ~30 seconds of speech. The user can ask for more aloud.
- **Natural prosody**: contractions, no bullet lists, no markdown syntax (asterisks, backticks, headers).
- **No code, file paths, URLs, or commands** in speech. Refer to them as "the code below", "the file I'm showing you", "the command in the answer".
- **Skip silent turns** when the entire response is a code dump, a long diff, or a table: speak a one-line preview ("voilà le diff", "ça fait trois fichiers à modifier") and let the text carry the detail.
- **No emojis** in the spoken text (TTS reads them literally).
- **Match the user's language**: pass `language=` on every `speak()` call so the right pocket-tts model is used. Common values:
  - French → `language="french_24l"` (default if omitted; voice defaults to `estelle`)
  - English → `language="english"`, `voice="alba"`
  - Spanish → `language="spanish_24l"`, `voice="lola"`
  - German → `language="german_24l"`, `voice="juergen"`
  - Italian → `language="italian_24l"`, `voice="giovanni"`
  - Portuguese → `language="portuguese_24l"`, `voice="rafael"`
  - Dutch → `language="dutch_24l"`, `voice="daan"`

  The first call to a new language pays a one-time ~3-5 s load (and ~1 GB RAM). Subsequent calls in that language are instant. Don't switch language gratuitously — stick to whatever language the user is writing in.

## Voice selection

By default, `speak()` uses Estelle (French built-in voice). Other voices you can pass via the `voice` arg:
- `"alba"` — neutral default voice (works in EN)
- `"estelle"` — French female (default for French)
- `"giovanni"` — Italian male
- `"juergen"` — German male
- `"lola"` — Spanish female
- `"rafael"` — Portuguese male
- `"daan"` — Dutch (default for Dutch)

If the user asks for a specific voice ("parle avec la voix de Rafael"), use that voice for the rest of the conversation until they change it.

## Deactivation

When the user says any of "mute" / "silence" / "stop talking" / "arrête de parler" / "désactive le mode vocal" / "/voice-mode off":

1. Call `mcp__kyutai-tts__stop_speaking()` once to silence whatever is mid-playback.
2. Stop calling `speak()` for the rest of the conversation. Confirm in text only: "voice mode off, je ne parle plus jusqu'à nouvel ordre".

## Anti-patterns — do not

- ❌ Don't pre-call `speak()` before composing the text (you need the text first to summarize it).
- ❌ Don't speak the literal markdown of your response (no "asterisk asterisk bonjour asterisk asterisk").
- ❌ Don't speak inline code spans verbatim (instead: "the function below" / "as shown").
- ❌ Don't repeat the full response in audio — it's a summary, not a recitation.
- ❌ Don't speak when the user explicitly typed something silent like a single command (`/status`, `/help`).
- ❌ Don't call `stop_speaking()` or `speak(interrupt=True)` reflexively at every turn — it cuts off the last syllable of the previous turn and feels jumpy. Reserve interrupt for actual interruptions (see "When to interrupt").
- ❌ Don't call both `stop_speaking()` and `speak()` in the same turn — `speak(interrupt=True)` does both atomically.

## Quick examples

Each example shows the contrast: the **text** can have markdown, code,
paths — the **speech** is the conversational gist a friend would say.

### French

User: "ce code marche pas, regarde"

Text: a few lines explaining the bug, with the offending function name in backticks and a one-line fix in a code block.

`speak()`:

```
speak(
  text="C'est un off-by-one dans la boucle, tu commences à un au lieu de zéro. Le fix est dans la réponse.",
  language="french_24l",
)
```

### English

User: "is this PR ready to merge?"

Text: a checklist — tests passing, lint clean, one minor docstring nit, link to the failing snapshot.

`speak()`:

```
speak(
  text="Almost — one snapshot's stale and there's a tiny docstring nit. Two minutes of work. Want me to fix them?",
  language="english",
  voice="alba",
)
```
