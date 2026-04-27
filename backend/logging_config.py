"""Centralised logging setup for Gibberly.

Call configure_logging() once at startup (main.py).

Sub-loggers
-----------
gibberly.ws      — WebSocket / operator connection lifecycle
gibberly.session — SessionHandler orchestration and chunk timing
gibberly.stt     — Azure Speech-to-Text recogniser
gibberly.llm     — LLM translate calls (timing, token usage)
gibberly.tts     — TTS synthesis (timing, audio size)
gibberly.pubsub  — Web PubSub publish, token generation, listener counts

Azure severity mapping
----------------------
Azure App Service maps stdout → "Information" and stderr → "Error" regardless
of the Python log level.  We route WARNING/ERROR/CRITICAL to stderr so they
appear at the correct severity in Azure's log stream and Log Analytics.

Set LOG_LEVEL=DEBUG in the environment to see interim STT events, cap timers, etc.
Azure / OpenAI SDK loggers are kept at WARNING so their internal HTTP chatter
doesn't pollute the stream.
"""

import logging
import os
import sys


class _LevelSplitHandler(logging.Handler):
    """Sends INFO/DEBUG to stdout and WARNING/ERROR/CRITICAL to stderr.

    In Azure App Service this causes WARNING+ records to appear as "Error"
    severity in Log Stream and Log Analytics, while INFO records stay as
    "Information" — matching the Python log level semantics.
    """

    def __init__(self, fmt: logging.Formatter) -> None:
        super().__init__()
        self._out = logging.StreamHandler(sys.stdout)
        self._err = logging.StreamHandler(sys.stderr)
        self._out.setFormatter(fmt)
        self._err.setFormatter(fmt)

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.WARNING:
            self._err.emit(record)
        else:
            self._out.emit(record)


def configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)-18s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    root = logging.getLogger("gibberly")
    root.setLevel(level)
    root.propagate = False  # don't double-print via root logger → stderr
    if not root.handlers:
        root.addHandler(_LevelSplitHandler(fmt))

    # Azure / OpenAI SDK internal loggers — keep at WARNING unless DEBUG requested
    sdk_level = logging.DEBUG if level == logging.DEBUG else logging.WARNING
    for name in (
        "azure.core.pipeline.policies.http_logging_policy",
        "azure.messaging.webpubsubservice",
        "azure.cognitiveservices.speech",
        "openai",
        "openai._base_client",
        "httpx",
        "httpcore",
    ):
        logging.getLogger(name).setLevel(sdk_level)
