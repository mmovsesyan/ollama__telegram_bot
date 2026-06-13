#!/usr/bin/env python3
"""Pre-download the configured Whisper model so first voice message is fast."""
import os
import sys

# Add project root to path so we can import bot.settings
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from faster_whisper import WhisperModel
except Exception as e:
    print(f"[warmup] faster-whisper not available: {e}")
    sys.exit(1)

from bot.settings import WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE


def main():
    print(f"[warmup] Loading Whisper model: {WHISPER_MODEL} (device={WHISPER_DEVICE})...")
    try:
        WhisperModel(
            WHISPER_MODEL,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )
        print("[warmup] Whisper model loaded and cached successfully.")
    except Exception as e:
        print(f"[warmup] Failed to load Whisper model: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
