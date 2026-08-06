"""
utils/transcribe.py
~~~~~~~~~~~~~~~~~~~
Multi-provider Speech-to-Text abstraction.

Every provider exposes the SAME public interface:

    session = get_session(on_transcript, on_error)
    session.start()
    session.send_audio(bytes)   # raw PCM s16le @ 16000 Hz
    session.stop()

Active provider is read from stt_provider.json at session creation time,
so switching takes effect on the next mic press — no restart needed.

Providers
---------
1. assemblyai     — AssemblyAI Streaming v3 (WebSocket, cloud)
2. deepgram        — Deepgram Nova-3 (WebSocket, cloud)
3. faster_whisper  — faster-whisper (local, CPU/GPU)
4. vosk            — Vosk (local, CPU, offline)
5. windows_sapi    — Windows Speech Recognition via win32com (Windows only)

Audio contract (matches what the browser sends):
    Raw PCM s16le, 16 000 Hz, mono, 16-bit signed little-endian
"""

from __future__ import annotations

import io
import os
import queue
import struct
import threading
import time
import wave
from abc import ABC, abstractmethod

from config import Config
from utils.logger import get_logger

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Provider state file helpers  (shared with app.py / admin_app.py)
# ─────────────────────────────────────────────────────────────────────────────

import json

STT_STATE_FILE = os.path.join(Config.QDRANT_PATH, "stt_provider.json")

VALID_PROVIDERS = {
    "assemblyai":    "AssemblyAI",
    "deepgram":      "Deepgram Nova-3",
    "faster_whisper": "Faster-Whisper",
    "vosk":          "Vosk",
    "windows_sapi":  "Windows Speech",
}


def read_active_provider() -> str:
    """Return the currently active STT provider key."""
    if os.path.exists(STT_STATE_FILE):
        try:
            with open(STT_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                p = data.get("provider", "").strip().lower()
                if p in VALID_PROVIDERS:
                    return p
        except Exception:
            pass
    # Fall back to .env default
    default = Config.STT_PROVIDER_DEFAULT
    if default not in VALID_PROVIDERS:
        default = "assemblyai"
    _write_provider(default)
    return default


def _write_provider(provider: str) -> None:
    os.makedirs(Config.QDRANT_PATH, exist_ok=True)
    tmp = STT_STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({
            "provider":   provider,
            "label":      VALID_PROVIDERS.get(provider, provider),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }, f)
    os.replace(tmp, STT_STATE_FILE)


def set_active_provider(provider: str) -> None:
    """Write the pending provider. Takes effect on next session.start()."""
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"Unknown STT provider: {provider!r}. Valid: {list(VALID_PROVIDERS)}")
    _write_provider(provider)
    logger.info(f"[STT] Active provider set → {provider} ({VALID_PROVIDERS[provider]})")


# ─────────────────────────────────────────────────────────────────────────────
# Abstract base
# ─────────────────────────────────────────────────────────────────────────────

class _BaseSession(ABC):
    """Common interface for all STT providers."""

    def __init__(self, on_transcript=None, on_error=None):
        self._on_transcript = on_transcript   # fn(text: str)
        self._on_error      = on_error        # fn(msg: str)
        self._stopped       = False

    def _emit(self, text: str) -> None:
        if text and self._on_transcript:
            self._on_transcript(text)

    def _err(self, msg: str) -> None:
        logger.error(f"[STT] {msg}")
        if self._on_error:
            self._on_error(msg)

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def send_audio(self, data: bytes) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...


# ─────────────────────────────────────────────────────────────────────────────
# 1. AssemblyAI  (WebSocket streaming)
# ─────────────────────────────────────────────────────────────────────────────

class _AssemblyAISession(_BaseSession):
    """
    Non-blocking AssemblyAI Streaming v3 session.
    connect() is blocking → runs in a daemon thread.
    Audio is queued and drained by a second daemon thread.
    """

    def __init__(self, on_transcript=None, on_error=None):
        super().__init__(on_transcript, on_error)
        self._client      = None
        self._audio_queue = queue.Queue()
        self._ready       = threading.Event()
        self._worker      = None

    def _handle_begin(self, client, event):
        self._ready.set()

    def _handle_turn(self, client, event):
        if getattr(event, "transcript", None):
            self._emit(event.transcript)

    def _handle_terminated(self, client, event):
        pass

    def _handle_error(self, client, error):
        self._err(str(error))

    def _run(self):
        api_key = Config.ASSEMBLYAI_API_KEY or os.environ.get("ASSEMBLYAI_API_KEY", "")
        if not api_key:
            self._err("ASSEMBLYAI_API_KEY is not configured.")
            return
        try:
            from assemblyai.streaming.v3 import (
                Encoding, StreamingClient, StreamingClientOptions,
                StreamingError, StreamingEvents, StreamingParameters,
            )
            self._client = StreamingClient(
                StreamingClientOptions(api_key=api_key, terminate_timeout=10.0)
            )
            self._client.on(StreamingEvents.Begin,       self._handle_begin)
            self._client.on(StreamingEvents.Turn,        self._handle_turn)
            self._client.on(StreamingEvents.Termination, self._handle_terminated)
            self._client.on(StreamingEvents.Error,       self._handle_error)
            self._client.connect(
                StreamingParameters(
                    speech_model="universal",
                    encoding=Encoding.pcm_s16le,
                    sample_rate=16000,
                )
            )
        except Exception as exc:
            self._err(f"AssemblyAI connect error: {exc}")

    def _drain(self):
        self._ready.wait(timeout=15)
        while True:
            chunk = self._audio_queue.get()
            if chunk is None:
                break
            if self._client and not self._stopped:
                try:
                    self._client.stream(chunk)
                except Exception as exc:
                    self._err(str(exc))

    def start(self):
        self._stopped = False
        threading.Thread(target=self._run,   daemon=True, name="aai-worker").start()
        threading.Thread(target=self._drain, daemon=True, name="aai-drain").start()

    def send_audio(self, data: bytes):
        if not self._stopped:
            self._audio_queue.put(data)

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        self._audio_queue.put(None)
        if self._client:
            try:
                self._client.disconnect(terminate=True)
            except Exception:
                pass
            self._client = None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Deepgram Nova-3  (WebSocket streaming)
# ─────────────────────────────────────────────────────────────────────────────

class _DeepgramSession(_BaseSession):
    """
    Deepgram Nova-3 real-time streaming via WebSocket.
    Uses the deepgram-sdk LiveClient which is also blocking,
    so we run it in a daemon thread exactly like AssemblyAI.
    """

    def __init__(self, on_transcript=None, on_error=None):
        super().__init__(on_transcript, on_error)
        self._audio_queue = queue.Queue()
        self._connection  = None
        self._ready       = threading.Event()

    def _run(self):
        api_key = Config.DEEPGRAM_API_KEY or os.environ.get("DEEPGRAM_API_KEY", "")
        if not api_key:
            self._err("DEEPGRAM_API_KEY is not configured.")
            return
        try:
            from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
            client = DeepgramClient(api_key)
            self._connection = client.listen.websocket.v("1")

            def on_open(self_inner, open_event, **kwargs):
                self._ready.set()

            def on_message(self_inner, result, **kwargs):
                try:
                    sentence = result.channel.alternatives[0].transcript
                    if sentence and result.is_final:
                        self._emit(sentence)
                except Exception:
                    pass

            def on_error(self_inner, error, **kwargs):
                self._err(str(error))

            self._connection.on(LiveTranscriptionEvents.Open,      on_open)
            self._connection.on(LiveTranscriptionEvents.Transcript, on_message)
            self._connection.on(LiveTranscriptionEvents.Error,      on_error)

            options = LiveOptions(
                model          = "nova-3",
                language       = "en-US",
                encoding       = "linear16",
                sample_rate    = 16000,
                channels       = 1,
                punctuate      = True,
                interim_results= False,
            )
            self._connection.start(options)

            # Drain audio queue while connection is alive
            while not self._stopped:
                try:
                    chunk = self._audio_queue.get(timeout=0.1)
                    if chunk is None:
                        break
                    self._connection.send(chunk)
                except queue.Empty:
                    continue
            self._connection.finish()

        except ImportError:
            self._err("deepgram-sdk is not installed. Run: pip install deepgram-sdk")
        except Exception as exc:
            self._err(f"Deepgram error: {exc}")

    def start(self):
        self._stopped = False
        threading.Thread(target=self._run, daemon=True, name="dg-worker").start()

    def send_audio(self, data: bytes):
        if not self._stopped:
            self._audio_queue.put(data)

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        self._audio_queue.put(None)


# ─────────────────────────────────────────────────────────────────────────────
# 3. faster-whisper  (local batch transcription)
# ─────────────────────────────────────────────────────────────────────────────

class _FasterWhisperSession(_BaseSession):
    """
    faster-whisper transcription.

    Real-time streaming is not natively supported — we accumulate PCM
    chunks and transcribe in 3-second windows to give a near-real-time
    experience without needing a persistent WebSocket.
    """

    WINDOW_SECONDS = 3       # transcribe every N seconds
    SAMPLE_RATE    = 16000
    SAMPLE_WIDTH   = 2       # int16 = 2 bytes

    def __init__(self, on_transcript=None, on_error=None):
        super().__init__(on_transcript, on_error)
        self._buffer      = bytearray()
        self._lock        = threading.Lock()
        self._timer       = None
        self._model       = None
        self._model_ready = threading.Event()

    def _load_model(self):
        try:
            from faster_whisper import WhisperModel
            model_size = Config.FASTER_WHISPER_MODEL or "base"
            logger.info(f"[STT] Loading faster-whisper model: {model_size}")
            self._model = WhisperModel(model_size, device="cpu", compute_type="int8")
            self._model_ready.set()
            logger.info("[STT] faster-whisper model ready")
        except ImportError:
            self._err("faster-whisper is not installed. Run: pip install faster-whisper")
        except Exception as exc:
            self._err(f"faster-whisper model load error: {exc}")

    def _transcribe_window(self):
        """Grab the current buffer, transcribe it, schedule the next window."""
        if self._stopped:
            return
        with self._lock:
            data = bytes(self._buffer)
            self._buffer.clear()

        if len(data) > self.SAMPLE_RATE * self.SAMPLE_WIDTH * 0.3:
            # Only transcribe if we have at least 0.3s of audio
            threading.Thread(
                target=self._run_transcription,
                args=(data,),
                daemon=True,
            ).start()

        if not self._stopped:
            self._timer = threading.Timer(self.WINDOW_SECONDS, self._transcribe_window)
            self._timer.daemon = True
            self._timer.start()

    def _run_transcription(self, pcm_bytes: bytes):
        if not self._model:
            return
        try:
            # Wrap raw PCM in a WAV container so whisper can read it
            wav_buf = io.BytesIO()
            with wave.open(wav_buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(self.SAMPLE_WIDTH)
                wf.setframerate(self.SAMPLE_RATE)
                wf.writeframes(pcm_bytes)
            wav_buf.seek(0)

            segments, _ = self._model.transcribe(wav_buf, beam_size=5, language="en")
            text = " ".join(seg.text.strip() for seg in segments).strip()
            if text:
                self._emit(text)
        except Exception as exc:
            self._err(f"faster-whisper transcription error: {exc}")

    def start(self):
        self._stopped = False
        threading.Thread(target=self._load_model, daemon=True, name="fw-load").start()
        # Start the windowed transcription loop once model is ready
        def _wait_and_start():
            self._model_ready.wait(timeout=120)
            if not self._stopped:
                self._timer = threading.Timer(self.WINDOW_SECONDS, self._transcribe_window)
                self._timer.daemon = True
                self._timer.start()
        threading.Thread(target=_wait_and_start, daemon=True).start()

    def send_audio(self, data: bytes):
        if not self._stopped:
            with self._lock:
                self._buffer.extend(data)

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        if self._timer:
            self._timer.cancel()
        # Final transcription of any remaining audio
        with self._lock:
            remaining = bytes(self._buffer)
            self._buffer.clear()
        if remaining and self._model:
            self._run_transcription(remaining)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Vosk  (local offline WebSocket-style streaming)
# ─────────────────────────────────────────────────────────────────────────────

class _VoskSession(_BaseSession):
    """
    Vosk offline speech recognition.
    Streams PCM chunks through a KaldiRecognizer for truly incremental results.
    """

    SAMPLE_RATE = 16000

    def __init__(self, on_transcript=None, on_error=None):
        super().__init__(on_transcript, on_error)
        self._audio_queue = queue.Queue()
        self._rec         = None

    def _run(self):
        try:
            from vosk import Model, KaldiRecognizer
            model_path = Config.VOSK_MODEL_PATH
            if not os.path.exists(model_path):
                self._err(
                    f"Vosk model not found at '{model_path}'. "
                    "Download a model from https://alphacephei.com/vosk/models and set VOSK_MODEL_PATH."
                )
                return
            logger.info(f"[STT] Loading Vosk model from: {model_path}")
            model = Model(model_path)
            self._rec = KaldiRecognizer(model, self.SAMPLE_RATE)
            self._rec.SetWords(True)
            logger.info("[STT] Vosk model ready")

            while True:
                chunk = self._audio_queue.get()
                if chunk is None:
                    break
                if self._rec.AcceptWaveform(chunk):
                    result = json.loads(self._rec.Result())
                    text   = result.get("text", "").strip()
                    if text:
                        self._emit(text)
                else:
                    partial = json.loads(self._rec.PartialResult())
                    # Partial results are noisy — only emit if substantial
                    p = partial.get("partial", "").strip()
                    if len(p.split()) >= 3:
                        pass  # Could emit interim results here if desired

            # Final result after stop
            final = json.loads(self._rec.FinalResult())
            text  = final.get("text", "").strip()
            if text:
                self._emit(text)

        except ImportError:
            self._err("vosk is not installed. Run: pip install vosk")
        except Exception as exc:
            self._err(f"Vosk error: {exc}")

    def start(self):
        self._stopped = False
        threading.Thread(target=self._run, daemon=True, name="vosk-worker").start()

    def send_audio(self, data: bytes):
        if not self._stopped:
            self._audio_queue.put(data)

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        self._audio_queue.put(None)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Windows SAPI  (win32com, Windows-only)
# ─────────────────────────────────────────────────────────────────────────────

class _WindowsSAPISession(_BaseSession):
    """
    Windows Speech Recognition via win32com.shell / pyttsx3 SAPI.

    Windows SAPI does not support raw PCM streaming from an arbitrary source.
    It reads from the default microphone device directly.

    Strategy:
    - We activate the Windows Speech Recognizer on start().
    - send_audio() is a no-op (SAPI manages its own mic input).
    - Recognized phrases are emitted via a recognition event.
    - stop() shuts down the recognizer.

    Note: The browser mic audio is NOT piped to SAPI — SAPI reads from the
    default Windows microphone. This means both the browser and SAPI may
    capture audio simultaneously. For best results, use this provider on
    Windows where the browser mic == the default Windows mic device.
    """

    def __init__(self, on_transcript=None, on_error=None):
        super().__init__(on_transcript, on_error)
        self._recognizer = None
        self._thread     = None

    def _run(self):
        try:
            import win32com.client
            import pythoncom

            pythoncom.CoInitialize()
            try:
                context = win32com.client.Dispatch("SAPI.SpInProcRecoContext")
                grammar = context.CreateGrammar()
                grammar.DictationLoad()
                grammar.DictationSetState(1)  # 1 = SPRS_ACTIVE

                # Use a simple polling loop to collect recognition results
                # SAPI events are COM-based; polling is the most portable approach
                logger.info("[STT] Windows SAPI recognizer active")

                last_result = ""
                while not self._stopped:
                    try:
                        event = context.WaitForNotifyEvent(100)  # 100ms timeout
                        if event:
                            result = context.CreateRecoResult()
                            phrase = result.PhraseInfo.GetText()
                            if phrase and phrase != last_result:
                                last_result = phrase
                                self._emit(phrase)
                    except Exception:
                        time.sleep(0.1)

                grammar.DictationSetState(0)  # deactivate
            finally:
                pythoncom.CoUninitialize()

        except ImportError:
            self._err(
                "pywin32 is not installed. Run: pip install pywin32  "
                "(Windows only)"
            )
        except Exception as exc:
            self._err(f"Windows SAPI error: {exc}")

    def start(self):
        self._stopped = False
        self._thread  = threading.Thread(target=self._run, daemon=True, name="sapi-worker")
        self._thread.start()

    def send_audio(self, data: bytes):
        # SAPI handles its own mic input — this is intentionally a no-op
        pass

    def stop(self):
        if self._stopped:
            return
        self._stopped = True


# ─────────────────────────────────────────────────────────────────────────────
# Factory — the only function app.py needs to call
# ─────────────────────────────────────────────────────────────────────────────

_PROVIDER_MAP: dict[str, type] = {
    "assemblyai":     _AssemblyAISession,
    "deepgram":       _DeepgramSession,
    "faster_whisper": _FasterWhisperSession,
    "vosk":           _VoskSession,
    "windows_sapi":   _WindowsSAPISession,
}


def get_session(on_transcript=None, on_error=None) -> _BaseSession:
    """
    Return an STT session for the currently active provider.

    The provider is read from stt_provider.json at call time, so
    switching via the admin panel takes effect on the next mic press.
    """
    provider = read_active_provider()
    cls      = _PROVIDER_MAP.get(provider)
    if cls is None:
        logger.warning(f"[STT] Unknown provider '{provider}' — falling back to assemblyai")
        cls = _AssemblyAISession
    logger.info(f"[STT] Creating session: {provider} ({VALID_PROVIDERS.get(provider, provider)})")
    return cls(on_transcript=on_transcript, on_error=on_error)


# ─────────────────────────────────────────────────────────────────────────────
# Legacy alias — keeps existing app.py import working unchanged
# ─────────────────────────────────────────────────────────────────────────────

TranscribeSession = _AssemblyAISession


# ─────────────────────────────────────────────────────────────────────────────
# AssemblyAI radio demo (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

STREAM_URL  = "https://14123.live.streamtheworld.com/WBBRAMAAC.aac"
RUN_SECONDS = 25


def run_radio_demo():
    import requests as _req
    from assemblyai.streaming.v3 import (
        Encoding, StreamingClient, StreamingClientOptions,
        StreamingEvents, StreamingParameters,
    )
    client = StreamingClient(
        StreamingClientOptions(
            api_key=Config.ASSEMBLYAI_API_KEY or os.environ.get("ASSEMBLYAI_API_KEY", ""),
            terminate_timeout=30.0,
        )
    )
    client.on(StreamingEvents.Turn, lambda c, e: print(e.transcript) if e.transcript else None)
    client.connect(StreamingParameters(speech_model="universal-3-5-pro", encoding=Encoding.aac))
    response = _req.get(STREAM_URL, stream=True)
    deadline = time.time() + RUN_SECONDS
    try:
        for chunk in response.iter_content(chunk_size=4096):
            client.stream(chunk)
            if time.time() > deadline:
                break
    finally:
        response.close()
        client.disconnect(terminate=True)


if __name__ == "__main__":
    run_radio_demo()
