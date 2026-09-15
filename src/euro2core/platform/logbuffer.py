"""Last log lines kept in memory so the admin panel can show them without SSH."""

import logging
from collections import deque
from threading import Lock

_LINES: deque[str] = deque(maxlen=500)
_LOCK = Lock()


class RingBufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:  # never let logging break the app
            return
        with _LOCK:
            _LINES.append(line)


def install(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if any(isinstance(h, RingBufferHandler) for h in root.handlers):
        return
    handler = RingBufferHandler(level)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)


def tail(n: int = 200) -> list[str]:
    with _LOCK:
        return list(_LINES)[-n:]
