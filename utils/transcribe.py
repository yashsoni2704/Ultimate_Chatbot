"""
transcribe.py — AssemblyAI real-time transcription helper.

Two modes:
  1. run_radio_demo()  : streams a public internet radio URL (original demo)
  2. TranscribeSession : used by the Flask-SocketIO route to pipe raw PCM
                         audio bytes from the browser microphone.

Audio contract with the browser (script.js):
  - Float32 samples @ browser native sample-rate are captured via
    ScriptProcessor, downsampled to 16 000 Hz and converted to Int16
    INSIDE the browser before being sent here as raw bytes.
  - We tell AssemblyAI: pcm_s16le @ 16000 Hz.
"""

import os
import queue
import threading
import time

import requests
from dotenv import load_dotenv

load_dotenv()

from assemblyai.streaming.v3 import (
    BeginEvent,
    Encoding,
    StreamingClient,
    StreamingClientOptions,
    StreamingError,
    StreamingEvents,
    StreamingParameters,
    TerminationEvent,
    TurnEvent,
)

# ─────────────────────────────────────────────────────────────────────────────
# Original radio demo
# ─────────────────────────────────────────────────────────────────────────────

STREAM_URL  = "https://14123.live.streamtheworld.com/WBBRAMAAC.aac"
RUN_SECONDS = 25


def _on_begin(client, event: BeginEvent):
    print(f"Session started: {event.id}")


def _on_turn(client, event: TurnEvent):
    if event.transcript:
        print(event.transcript)


def _on_terminated(client, event: TerminationEvent):
    print(f"Session terminated: {event.audio_duration_seconds}s")


def _on_error(client, error: StreamingError):
    print(f"Error: {error}")


def run_radio_demo():
    client = StreamingClient(
        StreamingClientOptions(api_key=os.environ["ASSEMBLYAI_API_KEY"],
                               terminate_timeout=30.0)
    )
    client.on(StreamingEvents.Begin,       _on_begin)
    client.on(StreamingEvents.Turn,        _on_turn)
    client.on(StreamingEvents.Termination, _on_terminated)
    client.on(StreamingEvents.Error,       _on_error)
    client.connect(StreamingParameters(speech_model="universal-3-5-pro",
                                       encoding=Encoding.aac))
    response = requests.get(STREAM_URL, stream=True)
    deadline = time.time() + RUN_SECONDS
    try:
        for chunk in response.iter_content(chunk_size=4096):
            client.stream(chunk)
            if time.time() > deadline:
                break
    finally:
        response.close()
        client.disconnect(terminate=True)


# ─────────────────────────────────────────────────────────────────────────────
# Live mic session
# ─────────────────────────────────────────────────────────────────────────────

class TranscribeSession:
    """
    Non-blocking AssemblyAI streaming session for one browser client.

    client.connect() is blocking (it opens a WebSocket and keeps it open),
    so we run it in a dedicated daemon thread.  Audio chunks are queued
    and drained by that same thread so ordering is guaranteed and there
    is no race between "session ready" and "first chunk".
    """

    def __init__(self, on_transcript=None, on_error=None):
        self._on_transcript = on_transcript   # fn(text: str)
        self._on_error      = on_error        # fn(msg: str)
        self._client        = None
        self._audio_queue   = queue.Queue()   # bytes items; None = stop signal
        self._ready         = threading.Event()
        self._worker        = None
        self._stopped       = False

    # ── AssemblyAI event handlers ─────────────────────────────────────────

    def _handle_begin(self, client, event: BeginEvent):
        self._ready.set()           # unblock _worker after connect() returns

    def _handle_turn(self, client, event: TurnEvent):
        if event.transcript and self._on_transcript:
            self._on_transcript(event.transcript)

    def _handle_terminated(self, client, event: TerminationEvent):
        pass

    def _handle_error(self, client, error: StreamingError):
        if self._on_error:
            self._on_error(str(error))

    # ── Worker thread — owns the blocking connect() call ─────────────────

    def _run(self):
        api_key = os.environ.get("ASSEMBLYAI_API_KEY", "")
        if not api_key:
            if self._on_error:
                self._on_error("ASSEMBLYAI_API_KEY is not set.")
            return

        self._client = StreamingClient(
            StreamingClientOptions(api_key=api_key, terminate_timeout=10.0)
        )
        self._client.on(StreamingEvents.Begin,       self._handle_begin)
        self._client.on(StreamingEvents.Turn,        self._handle_turn)
        self._client.on(StreamingEvents.Termination, self._handle_terminated)
        self._client.on(StreamingEvents.Error,       self._handle_error)

        # connect() opens the WS and blocks until disconnect() is called
        self._client.connect(
            StreamingParameters(
                speech_model = "universal",
                encoding     = Encoding.pcm_s16le,
                sample_rate  = 16000,
            )
        )

    # ── Audio drain loop — separate thread so queue never backs up ────────

    def _drain_audio(self):
        # Wait until AssemblyAI signals the session is open
        self._ready.wait(timeout=15)
        while True:
            chunk = self._audio_queue.get()
            if chunk is None:           # stop signal
                break
            if self._client and not self._stopped:
                try:
                    self._client.stream(chunk)
                except Exception as exc:
                    if self._on_error:
                        self._on_error(str(exc))

    # ── Public API ────────────────────────────────────────────────────────

    def start(self):
        """Kick off the AssemblyAI session in background threads."""
        self._stopped = False
        # Thread 1: blocking connect() + receive loop
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()
        # Thread 2: audio drain loop
        threading.Thread(target=self._drain_audio, daemon=True).start()

    def send_audio(self, data: bytes):
        """Queue a raw PCM chunk. Safe to call immediately after start()."""
        if not self._stopped:
            self._audio_queue.put(data)

    def stop(self):
        """Gracefully shut down the session."""
        if self._stopped:
            return
        self._stopped = True
        self._audio_queue.put(None)     # unblock drain loop
        if self._client:
            try:
                self._client.disconnect(terminate=True)
            except Exception:
                pass
            self._client = None


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_radio_demo()
