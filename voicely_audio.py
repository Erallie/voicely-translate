"""PCM conversion and voice-activity detection helpers."""

from __future__ import annotations

import os
from array import array

import webrtcvad


class SpeechDetector:
    """Reusable WebRTC VAD for 16-bit stereo PCM."""

    def __init__(
        self,
        sample_rate: int,
        sample_width: int,
        frame_ms: int,
        aggressiveness: int,
        minimum_ratio: float,
        minimum_consecutive: int,
    ) -> None:
        self.sample_rate = sample_rate
        self.sample_width = sample_width
        self.frame_ms = frame_ms
        self.minimum_ratio = minimum_ratio
        self.minimum_consecutive = minimum_consecutive
        self._vad = webrtcvad.Vad(aggressiveness)

    @staticmethod
    def stereo_to_mono(pcm: bytes) -> bytes:
        samples = array("h")
        samples.frombytes(pcm)
        if len(samples) < 2:
            return b""
        if os.sys.byteorder != "little":
            samples.byteswap()
        mono = array("h")
        mono.extend(
            (int(samples[index]) + int(samples[index + 1])) // 2
            for index in range(0, len(samples) - 1, 2)
        )
        if os.sys.byteorder != "little":
            mono.byteswap()
        return mono.tobytes()

    def contains_speech(self, pcm: bytes) -> tuple[bool, float, int]:
        mono = self.stereo_to_mono(pcm)
        frame_bytes = self.sample_rate * self.sample_width * self.frame_ms // 1000
        if frame_bytes <= 0 or len(mono) < frame_bytes:
            return False, 0.0, 0
        speech_frames = total_frames = consecutive = max_consecutive = 0
        for start in range(0, len(mono) - frame_bytes + 1, frame_bytes):
            total_frames += 1
            if self._vad.is_speech(mono[start:start + frame_bytes], self.sample_rate):
                speech_frames += 1
                consecutive += 1
                max_consecutive = max(max_consecutive, consecutive)
            else:
                consecutive = 0
        ratio = speech_frames / total_frames if total_frames else 0.0
        return (
            ratio >= self.minimum_ratio
            and max_consecutive >= self.minimum_consecutive,
            ratio,
            max_consecutive,
        )
