"""Encode an audio sample into a `.safetensors` voice state file.

The output can be passed back to `speak(voice=...)` for instant voice
loading at runtime (skips the ~2-5 s Mimi encoding + latent projection).

Requires the cloning-enabled checkpoint:
- Accept the terms at https://huggingface.co/kyutai/pocket-tts
- Run `hf auth login` once
- Delete `~/.cache/huggingface/hub/models--kyutai--pocket-tts` if a
  previous run cached the non-cloning checkpoint
"""
import sys
from pathlib import Path


def run_extract_voice(
    *,
    audio: str,
    out: Path,
    language: str,
    truncate: bool = False,
    quantize: bool = False,
    device: str = "cpu",
) -> None:
    """Load `audio`, encode it into a pocket-tts voice state, save to `out`.

    Args:
        audio: Source audio — local path, `hf://` URL, or `https://` URL.
               Any format pocket-tts can decode (wav, mp3, flac, ...).
               Auto-resampled to 24 kHz.
        out: Destination `.safetensors` path. Parent dirs are created.
        language: Pocket-tts language model to use for encoding.
        truncate: If True, truncate the audio to 30 s before encoding.
                  Recommended for long inputs to avoid memory pressure.
        quantize: Pass-through to `TTSModel.load_model(quantize=...)`.
        device: PyTorch device for the model (`"cpu"`, `"mps"` not supported
                by pocket-tts as of writing).

    Raises:
        SystemExit: if the cloning-enabled checkpoint isn't available
                    (auth missing / terms not accepted).
    """
    from pocket_tts import TTSModel, export_model_state

    print(f"Loading model ({language})…", file=sys.stderr, flush=True)
    model = TTSModel.load_model(language=language, quantize=quantize)
    model.to(device)
    if not model.has_voice_cloning:
        raise SystemExit(
            "Voice cloning unavailable. Accept the terms at "
            "https://huggingface.co/kyutai/pocket-tts, run `hf auth login`, "
            "then delete ~/.cache/huggingface/hub/models--kyutai--pocket-tts "
            "and retry."
        )

    print(f"Encoding {audio}…", file=sys.stderr, flush=True)
    state = model.get_state_for_audio_prompt(audio, truncate=truncate)

    out.parent.mkdir(parents=True, exist_ok=True)
    export_model_state(state, out)
    print(f"Voice state saved to {out}", file=sys.stderr)
