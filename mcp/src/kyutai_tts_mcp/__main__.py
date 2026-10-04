"""MCP server wrapping Kyutai Pocket TTS, run through ONNX Runtime (no PyTorch).

Pipeline:

  speak() request
      └─► generation thread: OnnxTTS.generate(...) yields 80 ms float32
          PCM frames
              └─► audio queue
                      └─► writer thread: stream.write(chunk) in blocking
                          write-mode sounddevice OutputStream
                              └─► CoreAudio

Two languages, French and English, each an int8 ONNX bundle of Kyutai's
6-layer model (see onnx_tts.py). Each `speak()` can pass `language`;
bundles load lazily and stay cached, so the first call in a language pays
the ~120 MB download once, then well under a second to load. Both share
the Mimi codec at 24 kHz, so a single OutputStream serves both.
"""
import argparse
import atexit
import os
import queue
import threading
from importlib.metadata import version
from typing import Any

import numpy as np
import sounddevice as sd
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .onnx_tts import BUNDLES, OnnxTTS, resolve_language


# ── Config (environment variables) ────────────────────────────────────────────
# Mutable: DEFAULT_LANGUAGE is overridden by main() after CLI parsing.
# The CLI default itself falls back to KYUTAI_TTS_LANGUAGE env, then to "french".
DEFAULT_LANGUAGE = os.environ.get("KYUTAI_TTS_LANGUAGE", "french")
DEFAULT_VOICE = os.environ.get("KYUTAI_TTS_VOICE")  # None → language default
_max_tokens_env = os.environ.get("KYUTAI_TTS_MAX_TOKENS")
MAX_TOKENS = int(_max_tokens_env) if _max_tokens_env else None  # None → bundle's own (50)


# ── Server instance ───────────────────────────────────────────────────────────
mcp = MCPServer("kyutai-tts", version=version("kyutai-tts-mcp"))


# ── State: caches, queues, threads ────────────────────────────────────────────
# Per-language model cache. Built lazily on first speak() in that language.
_models: dict[str, OnnxTTS] = {}
_models_lock = threading.Lock()
_model_load_errors: dict[str, str] = {}
_sample_rate: int | None = None  # set by the first loaded model; all share 24 kHz

# Per-(language, voice) state cache. Voice state is tied to its model.
_voice_states: dict[tuple[str, str], dict[str, np.ndarray]] = {}
_voice_states_lock = threading.Lock()

# Audio queue: generation thread puts numpy chunks, writer thread calls
# stream.write() in blocking mode. PortAudio handles all realtime concerns.
_audio_q: "queue.Queue[np.ndarray | None]" = queue.Queue()
_writer_thread: threading.Thread | None = None
_stream: sd.OutputStream | None = None
_stream_lock = threading.Lock()

# Generation queue (FIFO of speak requests).
_gen_q: "queue.Queue[tuple[str, str | None, str] | None]" = queue.Queue()
_gen_thread: threading.Thread | None = None
_cancel_event = threading.Event()
_gen_in_flight = threading.Event()

_last_error: str | None = None


# ── Model & voice loading ─────────────────────────────────────────────────────
def _ensure_model(language: str) -> OnnxTTS:
    global _sample_rate
    with _models_lock:
        if language in _models:
            return _models[language]
        try:
            model = OnnxTTS(language)
            sr = model.sample_rate
            if _sample_rate is None:
                _sample_rate = sr
            elif sr != _sample_rate:
                # Defensive — every bundle uses Mimi at 24 kHz today, but if
                # this ever diverges, the single shared OutputStream would
                # resample-by-skew. Surface the mismatch loudly.
                raise RuntimeError(
                    f"sample-rate mismatch: {language} reports {sr} Hz, "
                    f"stream is at {_sample_rate} Hz"
                )
            _models[language] = model
            _model_load_errors.pop(language, None)
            return model
        except Exception as e:  # noqa: BLE001
            _model_load_errors[language] = f"{type(e).__name__}: {e}"
            raise


def _resolve_voice(voice: str | None, model: OnnxTTS) -> str:
    return voice or DEFAULT_VOICE or model.default_voice


def _voice_state_for(voice: str, model: OnnxTTS) -> dict[str, np.ndarray]:
    key = (model.language, voice)
    with _voice_states_lock:
        if key in _voice_states:
            return _voice_states[key]
    state = model.load_voice(voice)
    with _voice_states_lock:
        _voice_states[key] = state
    return state


# ── Audio output (stream + writer thread) ─────────────────────────────────────
def _ensure_stream() -> None:
    global _stream
    sr = _sample_rate or 24000
    with _stream_lock:
        if _stream is None or _stream.closed:
            _stream = sd.OutputStream(
                samplerate=sr,
                channels=1,
                dtype="float32",
            )
            _stream.start()
        elif _stream.stopped:
            _stream.start()


def _close_stream() -> None:
    global _stream
    with _stream_lock:
        if _stream is not None and not _stream.closed:
            try:
                _stream.abort()
                _stream.close()
            except Exception:  # noqa: BLE001
                pass
            _stream = None


def _writer_loop() -> None:
    global _last_error
    while True:
        chunk = _audio_q.get()
        if chunk is None:
            return
        if _cancel_event.is_set():
            continue
        try:
            stream = _stream
            if stream is None or stream.closed:
                continue
            stream.write(chunk)
        except Exception as e:  # noqa: BLE001
            _last_error = f"writer: {type(e).__name__}: {e}"


def _ensure_writer() -> None:
    global _writer_thread
    if _writer_thread is None or not _writer_thread.is_alive():
        _writer_thread = threading.Thread(target=_writer_loop, daemon=True)
        _writer_thread.start()


# ── Generation pipeline ───────────────────────────────────────────────────────
def _generation_loop() -> None:
    global _last_error
    while True:
        req = _gen_q.get()
        if req is None:
            return
        text, voice_arg, language = req
        _cancel_event.clear()
        _gen_in_flight.set()
        try:
            model = _ensure_model(language)
            voice = _resolve_voice(voice_arg, model)
            voice_state = _voice_state_for(voice, model)
            opened_stream = False
            # The generator checks `stop` before every frame and runs on this
            # thread, so breaking out leaves nothing running behind us.
            for arr in model.generate(voice_state, text, stop=_cancel_event, max_tokens=MAX_TOKENS):
                if _cancel_event.is_set():
                    break
                if arr.size == 0:
                    continue
                if not opened_stream:
                    _ensure_stream()
                    _ensure_writer()
                    opened_stream = True
                _audio_q.put(arr)
        except Exception as e:  # noqa: BLE001
            _last_error = f"generation: {type(e).__name__}: {e}"
        finally:
            _gen_in_flight.clear()


def _ensure_gen_thread() -> None:
    global _gen_thread
    if _gen_thread is None or not _gen_thread.is_alive():
        _gen_thread = threading.Thread(target=_generation_loop, daemon=True)
        _gen_thread.start()


# ── Queue draining & cleanup ──────────────────────────────────────────────────
def _drain(q: "queue.Queue[Any]") -> int:
    """Drain all items from `q`, ignoring None sentinels. Returns count dropped."""
    dropped = 0
    while True:
        try:
            x = q.get_nowait()
        except queue.Empty:
            return dropped
        if x is None:
            continue
        dropped += 1


def _abort_all() -> tuple[int, int]:
    """Cancel in-flight generation, drain both queues, abort current playback.

    Shared between `stop_speaking()` and `speak(interrupt=True)`.
    Returns (audio_chunks_dropped, pending_requests_dropped).
    """
    _cancel_event.set()
    dropped_gen = _drain(_gen_q)
    dropped_audio = _drain(_audio_q)
    with _stream_lock:
        if _stream is not None and not _stream.closed:
            try:
                _stream.abort()
            except Exception:  # noqa: BLE001
                pass
    return dropped_audio, dropped_gen


def _cleanup() -> None:
    _cancel_event.set()
    _drain(_audio_q)
    _drain(_gen_q)
    _close_stream()


atexit.register(_cleanup)


# ── MCP tools ─────────────────────────────────────────────────────────────────
@mcp.tool()
def speak(
    text: str,
    voice: str | None = None,
    language: str | None = None,
    interrupt: bool = False,
) -> str:
    """Speak text aloud through Kyutai Pocket TTS (local, streaming, ~20 ms TTFA).

    Returns immediately. The text is queued for streaming generation in a
    background thread; chunks are pushed into a continuous sounddevice
    OutputStream as they're produced. By default, multiple `speak()` calls
    queue and play sequentially — they never overlap, and audio from a
    previous conversational turn keeps playing through into the next.

    Pass `interrupt=True` to abort whatever is currently playing/queued
    before speaking. Use this when the user has clearly interrupted —
    e.g. they said "wait", "non", "stop", or switched topic mid-playback.

    For the explicit "shut up, don't speak at all" case (user said "mute"
    or "silence"), call `stop_speaking()` instead and skip `speak()`.

    Args:
        text: Text to read aloud. Match the language to the text — passing
              French text with `language="english"` will produce garbled output.
        voice: Kyutai predefined voice name. Defaults to "estelle" in
               French and "alba" in English. Others: "anna", "azelma",
               "bill_boerst", "caro_davy", "charles", "cosette", "eponine",
               "eve", "fantine", "george", "giovanni", "jane", "javert",
               "jean", "juergen", "lola", "marius", "mary", "michael",
               "paul", "peter_yearsley", "rafael", "stuart_bell", "vera".
               Any voice works in either language; the first use of a
               non-default voice downloads ~5 MB.
        language: "french" or "english" (older names such as "french_24l"
                  are accepted as aliases). Defaults to the server's default
                  language (set via the --language CLI flag, the
                  KYUTAI_TTS_LANGUAGE env var, or "french"). The model
                  downloads (~120 MB) on first use of a language, then
                  stays cached.
        interrupt: If True, abort current playback and clear the queue
                   before enqueuing this text. Use when the user has
                   interrupted. Default False (queue normally).
    """
    try:
        lang = resolve_language(language or DEFAULT_LANGUAGE)
    except ValueError as e:
        # ToolError keeps its message; any other exception reaches the
        # client as a bare "Error executing tool speak".
        raise ToolError(str(e)) from None
    if interrupt:
        _abort_all()
    _ensure_gen_thread()
    _gen_q.put((text, voice, lang))
    return (
        f"enqueued {len(text)} chars (lang={lang}, voice={voice or 'default'}, "
        f"interrupt={interrupt}, gen_pending={_gen_q.qsize()}, "
        f"audio_buffer={_audio_q.qsize()})"
    )


@mcp.tool()
def stop_speaking() -> str:
    """Stop the currently-playing audio, drop pending audio chunks, AND
    cancel any in-flight generation.

    Use only when the user has explicitly asked to be quiet
    ("mute" / "silence" / "tais-toi"). For mid-turn interruptions where
    you still want to speak something new, prefer `speak(text, interrupt=True)`.
    """
    dropped_audio, dropped_gen = _abort_all()
    return (
        f"cancelled generation, dropped {dropped_audio} audio chunks "
        f"+ {dropped_gen} pending requests, aborted current playback"
    )


@mcp.tool()
def status() -> dict:
    """Report loaded languages, queue depths, and last error."""
    with _stream_lock:
        stream_active = (
            _stream is not None
            and not _stream.closed
            and not _stream.stopped
        )
    with _models_lock:
        loaded = sorted(_models.keys())
        errors = dict(_model_load_errors)
    with _voice_states_lock:
        cached_voices = sorted(f"{lang}:{v}" for lang, v in _voice_states)
    return {
        "default_language": DEFAULT_LANGUAGE,
        "supported_languages": list(BUNDLES),
        "loaded_languages": loaded,
        "model_load_errors": errors,
        "sample_rate": _sample_rate,
        "cached_voices": cached_voices,
        "gen_pending": _gen_q.qsize(),
        "gen_in_flight": _gen_in_flight.is_set(),
        "audio_buffer": _audio_q.qsize(),
        "stream_active": stream_active,
        "last_error": _last_error,
    }


# ── CLI entry ─────────────────────────────────────────────────────────────────
def main() -> None:
    global DEFAULT_LANGUAGE
    parser = argparse.ArgumentParser(
        prog="kyutai-tts-mcp",
        description="MCP server wrapping Kyutai Pocket TTS (French + English, ONNX, streaming).",
    )
    parser.add_argument(
        "--language",
        default=DEFAULT_LANGUAGE,
        help=(
            "Default language used when speak() is called without an explicit "
            "language= arg: 'french' or 'english'. Per-call language= always wins. "
            "Falls back to KYUTAI_TTS_LANGUAGE env, then to 'french'. "
            f"(current default: {DEFAULT_LANGUAGE})"
        ),
    )
    args = parser.parse_args()
    try:
        DEFAULT_LANGUAGE = resolve_language(args.language)
    except ValueError as e:
        parser.error(str(e))
    mcp.run()


if __name__ == "__main__":
    main()
