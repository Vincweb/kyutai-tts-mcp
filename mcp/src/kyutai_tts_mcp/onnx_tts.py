"""Torch-free Pocket TTS inference over the Vincweb/pocket-tts-*-onnx bundles.

Each bundle is Kyutai's 6-layer Pocket TTS model exported to three int8 ONNX
graphs (flow LM backbone, flow head, Mimi decoder) plus a float16 text
lookup table, the tokenizer, and a `manifest.json` that carries the state
layout and every generation parameter. The loop below mirrors pocket-tts's
`generate_audio_stream`: prefill the voice state, prefill the text, then feed
each latent back (NaN for the first step) until the end-of-speech logit
crosses the threshold, decoding every 80 ms frame as soon as it exists.
"""
import json
import math
import os
import threading
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download, snapshot_download
from huggingface_hub.errors import EntryNotFoundError
from safetensors import safe_open
from tokenizers import Tokenizer

from .text_chunking import prepare_text_prompt, split_into_best_sentences

# Pinned on purpose: these repos also serve Volume Board in the browser, and
# an unpinned `main` would ship any change made for it to every uvx install.
BUNDLES = {
    "french": ("Vincweb/pocket-tts-french-onnx", "84541283b060685dbc7f9f9d8066f4b00235820c"),
    "english": ("Vincweb/pocket-tts-english-onnx", "c7cd567b25ddd2b7c1646256e9eb3ab50a342a27"),
}
BUNDLE_FORMAT = "volume-board/pocket-tts-onnx@1"
THREADS = min(4, os.cpu_count() or 1)


def resolve_language(language: str) -> str:
    """Map a user-facing language name onto a bundle key.

    Accepts the pocket-tts model names that earlier releases used
    (`french_24l`, `english_2026-04`, ...) so existing configs keep working.
    """
    key = language.strip().lower()
    for name in BUNDLES:
        if key.startswith(name) or key == name[:2]:
            return name
    raise ValueError(
        f"unsupported language {language!r}: supported languages are "
        f"{', '.join(BUNDLES)}"
    )


def _parse_hf_uri(uri: str) -> tuple[str, str, str]:
    """`hf://owner/repo/path/to/file@rev` → (repo_id, path, revision)."""
    path, revision = uri.removeprefix("hf://").split("@")
    owner, repo, *rest = path.split("/")
    return f"{owner}/{repo}", "/".join(rest), revision


class OnnxTTS:
    """One language bundle: sessions, lookup table, tokenizer, voices."""

    def __init__(self, language: str) -> None:
        self.language = language
        repo_id, revision = BUNDLES[language]
        self._dir = Path(snapshot_download(
            repo_id,
            revision=revision,
            allow_patterns=["*.onnx", "*.f16", "tokenizer.json", "manifest.json"],
        ))
        m = json.loads((self._dir / "manifest.json").read_text())
        if m.get("format") != BUNDLE_FORMAT or m.get("sampler_decode_steps") != 1:
            raise RuntimeError(
                f"{repo_id}@{revision}: unsupported bundle format "
                f"{m.get('format')!r} (sampler_decode_steps={m.get('sampler_decode_steps')})"
            )
        self.manifest = m
        self.sample_rate = int(m["sample_rate"])
        self.default_voice: str = m["default_voice"]
        self.max_tokens_per_chunk = int(m["max_tokens_per_chunk"])

        options = ort.SessionOptions()
        options.intra_op_num_threads = THREADS
        options.inter_op_num_threads = 1

        def session(key: str) -> ort.InferenceSession:
            return ort.InferenceSession(
                str(self._dir / m["models"][key]),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )

        self._main = session("flow_lm_main")
        self._flow = session("flow_lm_flow")
        self._decoder = session("mimi_decoder")
        # Output `out_<name>` is the next step's input `<name>`.
        self._main_state_inputs = [o.name[4:] for o in self._main.get_outputs()[2:]]
        self._decoder_state_inputs = [o.name[4:] for o in self._decoder.get_outputs()[1:]]

        table = m["text_embeddings"]
        self._text_table = np.fromfile(self._dir / "text_embeddings.f16", dtype=np.float16).reshape(
            table["rows"], table["dim"]
        )
        self.tokenizer = Tokenizer.from_file(str(self._dir / m["tokenizer"]))
        self._rng = np.random.default_rng()

    # ── Voices ────────────────────────────────────────────────────────────────
    def load_voice(self, voice: str) -> dict[str, np.ndarray]:
        """Voice state as the flow LM's per-layer KV cache feeds.

        `voice` is the voice bundled with the model, or the name of any Kyutai
        predefined voice, fetched from the same weights revision the bundle
        was exported from (a voice state only fits the weights it came from).
        """
        bundled = self.manifest["voices"].get(voice)
        if bundled is not None:
            return self._voice_from_f16(self._dir / bundled["file"], bundled["offsets"])
        repo_id, default_path, revision = _parse_hf_uri(self.manifest["source"]["voice"])
        try:
            path = hf_hub_download(
                repo_id,
                f"{default_path.rsplit('/', 1)[0]}/{voice}.safetensors",
                revision=revision,
            )
        except EntryNotFoundError:
            raise ValueError(f"unknown voice {voice!r} for {self.language}") from None
        return self._voice_from_safetensors(path)

    def _voice_from_f16(self, path: Path, offsets: list[int]) -> dict[str, np.ndarray]:
        raw = np.fromfile(path, dtype=np.float16)
        feeds, start = {}, 0
        for index, (layer, offset) in enumerate(zip(self.manifest["flow_layers"], offsets)):
            shape = (2, 1, offset, layer["heads"], layer["head_dim"])
            end = start + math.prod(shape)
            feeds[f"cache_{index}"] = raw[start:end].reshape(shape).astype(np.float32)
            feeds[f"offset_{index}"] = np.array([offset], dtype=np.int64)
            start = end
        if start != raw.size:
            raise ValueError(f"{path}: size does not match the manifest offsets")
        return feeds

    def _voice_from_safetensors(self, path: str) -> dict[str, np.ndarray]:
        feeds = {}
        with safe_open(path, framework="np") as handle:
            for index, layer in enumerate(self.manifest["flow_layers"]):
                cache = handle.get_tensor(f"{layer['name']}/cache")
                offset = int(handle.get_tensor(f"{layer['name']}/offset").reshape(-1)[0])
                feeds[f"cache_{index}"] = cache[:, :, :offset].astype(np.float32)
                feeds[f"offset_{index}"] = np.array([offset], dtype=np.int64)
        return feeds

    # ── Generation ────────────────────────────────────────────────────────────
    def generate(
        self,
        voice_state: dict[str, np.ndarray],
        text: str,
        stop: threading.Event,
        max_tokens: int | None = None,
    ) -> Iterator[np.ndarray]:
        """Yield float32 PCM frames (80 ms each) for `text` until done or `stop`."""
        m = self.manifest
        chunks = split_into_best_sentences(
            self.tokenizer,
            text,
            max_tokens or self.max_tokens_per_chunk,
            m["pad_with_spaces_for_short_inputs"],
            m["remove_semicolons"],
            m["append_terminal_punctuation"],
            m["capitalize_first_letter"],
            m["replace_characters"],
        )
        for chunk in chunks:
            if stop.is_set():
                return
            yield from self._generate_chunk(voice_state, chunk, stop)

    def _generate_chunk(
        self, voice_state: dict[str, np.ndarray], chunk: str, stop: threading.Event
    ) -> Iterator[np.ndarray]:
        m = self.manifest
        prepared, frames_after_eos_guess = prepare_text_prompt(
            chunk,
            m["pad_with_spaces_for_short_inputs"],
            m["remove_semicolons"],
            m["append_terminal_punctuation"],
            m["capitalize_first_letter"],
            m["replace_characters"],
        )
        frames_after_eos = m["frames_after_eos"]
        if frames_after_eos is None:
            frames_after_eos = frames_after_eos_guess + 2
        ids = self.tokenizer.encode(prepared).ids
        max_frames = math.ceil(
            (len(ids) / m["tokens_per_second"] + m["gen_seconds_padding"]) * m["frame_rate"]
        )
        latent_dim = m["latent_dim"]

        # Every chunk restarts from the voice prompt and a fresh decoder, as
        # pocket-tts does. ONNX outputs are new arrays, so `voice_state` is
        # never mutated and stays reusable across calls.
        flow_state = dict(voice_state)
        out = self._main.run(None, {
            "sequence": np.zeros((1, 0, latent_dim), np.float32),
            "text_embeddings": self._text_table[ids][None].astype(np.float32),
            **flow_state,
        })
        flow_state.update(zip(self._main_state_inputs, out[2:]))
        mimi_state = {
            f"mimi_{index}": (np.ones if entry["key"] == "first" else np.zeros)(
                entry["shape"], np.dtype(entry["dtype"])
            )
            for index, entry in enumerate(m["mimi_states"])
        }

        no_text = np.zeros((1, 0, m["conditioning_dim"]), np.float32)
        s = np.zeros((1, 1), np.float32)
        t = np.ones((1, 1), np.float32)
        noise_std = math.sqrt(m["temperature"])
        latent = np.full((1, 1, latent_dim), np.nan, np.float32)  # NaN = BOS
        eos_step = None
        for step in range(max_frames):
            if stop.is_set():
                return
            out = self._main.run(None, {"sequence": latent, "text_embeddings": no_text, **flow_state})
            flow_state.update(zip(self._main_state_inputs, out[2:]))
            if (
                eos_step is None
                and step >= m["min_frames_before_eos"]
                and out[1].reshape(-1)[0] > m["eos_threshold"]
            ):
                eos_step = step
            if eos_step is not None and step >= eos_step + frames_after_eos:
                return
            # One-step LSD sampling: x0 ~ N(0, temp), latent = x0 + flow(c, 0, 1, x0).
            x = self._rng.normal(0.0, noise_std, (1, latent_dim)).astype(np.float32)
            x = x + self._flow.run(None, {"c": out[0], "s": s, "t": t, "x": x})[0]
            latent = x.reshape(1, 1, latent_dim)
            decoded = self._decoder.run(None, {"latent": latent, **mimi_state})
            mimi_state.update(zip(self._decoder_state_inputs, decoded[1:]))
            audio = decoded[0].astype(np.float32, copy=False)
            if step == 0:
                # 5 ms fade-in so a fresh decoder state never starts on a click.
                fade = min(audio.size, self.sample_rate // 200)
                audio = audio.copy()
                audio[:fade] *= np.linspace(0.0, 1.0, fade, dtype=np.float32)
            yield audio
