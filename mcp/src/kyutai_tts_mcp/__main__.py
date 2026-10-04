"""MCP server wrapping Kyutai Pocket TTS via its native Python streaming API.

Pipeline:

  speak() request
      └─► generation thread: tts_model.generate_audio_stream(...) yields
          ~80 ms PCM chunks of torch.Tensor
              └─► audio queue (numpy float32)
                      └─► writer thread: stream.write(chunk) in blocking
                          write-mode sounddevice OutputStream
                              └─► CoreAudio

Multi-language: each `speak()` can specify a `language` argument. Models
are loaded lazily and cached per-language, so the first call to a new
language pays ~3-5 s load time and ~1 GB resident RAM; subsequent calls
in that language are instant. All pocket-tts models share the mimi codec
at 24 kHz, so a single OutputStream serves every language.
"""
import argparse
import atexit
import os
import queue
import threading
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd
from mcp.server.mcpserver import MCPServer

from .extract import run_extract_voice


# ── Config (environment variables) ────────────────────────────────────────────
# Mutable: DEFAULT_LANGUAGE is overridden by main() after CLI parsing.
# The CLI default itself falls back to KYUTAI_TTS_LANGUAGE env, then to "french_24l".
DEFAULT_LANGUAGE = os.environ.get("KYUTAI_TTS_LANGUAGE", "french_24l")
DEFAULT_VOICE = os.environ.get("KYUTAI_TTS_VOICE")  # None → language default
QUANTIZE = os.environ.get("KYUTAI_TTS_QUANTIZE", "0") == "1"
DEVICE = os.environ.get("KYUTAI_TTS_DEVICE", "cpu")
MAX_TOKENS = int(os.environ.get("KYUTAI_TTS_MAX_TOKENS", "50"))


# ── Server instance ───────────────────────────────────────────────────────────
mcp = MCPServer("kyutai-tts")


# ── State: caches, queues, threads ────────────────────────────────────────────
# Per-language model cache. Built lazily on first speak() in that language.
_models: dict[str, Any] = {}
_models_lock = threading.Lock()
_model_load_errors: dict[str, str] = {}
_sample_rate: int | None = None  # set by the first loaded model; all share 24 kHz

# Per-(language, voice) state cache. Voice state is tied to its model.
_voice_states: dict[tuple[str, str], Any] = {}
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
def _ensure_model(language: str) -> Any:
    global _sample_rate
    with _models_lock:
        if language in _models:
            return _models[language]
        try:
            from pocket_tts.models.tts_model import TTSModel  # heavy import
            model = TTSModel.load_model(language=language, quantize=QUANTIZE)
            model.to(DEVICE)
            sr = int(model.config.mimi.sample_rate)
            if _sample_rate is None:
                _sample_rate = sr
            elif sr != _sample_rate:
                # Defensive — pocket-tts uses mimi 24 kHz everywhere today,
                # but if this ever diverges, the single shared OutputStream
                # would resample-by-skew. Surface the mismatch loudly.
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


def _resolve_voice(voice: str | None, language: str) -> str:
    if voice:
        return voice
    if DEFAULT_VOICE:
        return DEFAULT_VOICE
    from pocket_tts.default_parameters import get_default_voice_for_language
    return get_default_voice_for_language(language)


def _voice_state_for(voice: str, language: str) -> Any:
    key = (language, voice)
    with _voice_states_lock:
        if key in _voice_states:
            return _voice_states[key]
    model = _ensure_model(language)
    state = model.get_state_for_audio_prompt(voice)
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
def _chunk_to_float32(chunk: Any) -> np.ndarray:
    # pocket-tts yields torch.Tensor on CPU. Defensive: support numpy too.
    try:
        import torch  # noqa: F401
        if hasattr(chunk, "detach"):
            chunk = chunk.detach().cpu().numpy()
    except ImportError:
        pass
    arr = np.asarray(chunk).astype(np.float32, copy=False)
    if arr.ndim > 1:
        arr = arr.squeeze()
    return arr


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
            voice = _resolve_voice(voice_arg, language)
            voice_state = _voice_state_for(voice, language)
            opened_stream = False
            for chunk in model.generate_audio_stream(
                model_state=voice_state,
                text_to_generate=text,
                max_tokens=MAX_TOKENS,
                stop=_cancel_event,
            ):
                if _cancel_event.is_set():
                    # Drain instead of break: pocket-tts's own gen/decode
                    # threads exit on `stop`, and the generator only ends
                    # once they have. Breaking early would let the next
                    # request clear the event before they saw it.
                    continue
                arr = _chunk_to_float32(chunk)
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
    """Speak text aloud through Kyutai Pocket TTS (local, streaming, ~200ms TTFA).

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
        voice: Built-in voice name (e.g. "estelle", "alba", "giovanni",
               "juergen", "lola", "rafael", "daan"), or a path to a wav file for
               voice cloning, or a `hf://` URL. Defaults to the language's
               built-in voice.
        language: Pocket-tts model to use for this call. Options include
                  "french_24l", "english", "english_2026-04",
                  "spanish_24l", "german_24l", "italian_24l",
                  "portuguese_24l", "dutch_24l". Defaults to the server's default
                  language (set via the --language CLI flag, the
                  KYUTAI_TTS_LANGUAGE env var, or "french_24l"). The
                  model loads on first use of a given language (~3-5 s
                  + ~1 GB RAM), then stays cached.
        interrupt: If True, abort current playback and clear the queue
                   before enqueuing this text. Use when the user has
                   interrupted. Default False (queue normally).
    """
    if interrupt:
        _abort_all()
    lang = language or DEFAULT_LANGUAGE
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
        description="MCP server wrapping Kyutai Pocket TTS (multi-language, streaming).",
    )
    parser.add_argument(
        "--language",
        default=DEFAULT_LANGUAGE,
        help=(
            "Default language used when speak() is called without an explicit "
            "language= arg. Per-call language= always wins. "
            "Falls back to KYUTAI_TTS_LANGUAGE env, then to 'french_24l'. "
            f"(current default: {DEFAULT_LANGUAGE})"
        ),
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    extract = subparsers.add_parser(
        "extract-voice",
        help="Encode an audio sample into a .safetensors voice state",
        description=(
            "Pre-extract a voice state from an audio sample, save to a "
            ".safetensors file. The output can be passed back to "
            "speak(voice=...) for instant voice loading. Requires the "
            "cloning-enabled checkpoint (accept terms at "
            "https://huggingface.co/kyutai/pocket-tts + hf auth login)."
        ),
    )
    extract.add_argument(
        "--audio", "-i", required=True,
        help="Source audio: local path, hf:// URL, or https:// URL. "
             "Any format pocket-tts can decode (wav, mp3, flac, ...).",
    )
    extract.add_argument(
        "--out", "-o", required=True,
        help="Destination .safetensors path",
    )
    extract.add_argument(
        "--language", default=DEFAULT_LANGUAGE,
        help="Pocket-tts language model to use for encoding "
             f"(default: {DEFAULT_LANGUAGE})",
    )
    extract.add_argument(
        "--truncate", action="store_true",
        help="Truncate the audio to 30 s before encoding "
             "(recommended for long inputs to avoid memory pressure)",
    )

    args = parser.parse_args()

    if args.command == "extract-voice":
        run_extract_voice(
            audio=args.audio,
            out=Path(args.out),
            language=args.language,
            truncate=args.truncate,
            quantize=QUANTIZE,
            device=DEVICE,
        )
        return

    DEFAULT_LANGUAGE = args.language
    mcp.run()


if __name__ == "__main__":
    main()
