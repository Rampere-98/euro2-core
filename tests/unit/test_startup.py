"""`serve` waits for the database instead of dying after a reboot."""

from euro2core import startup


def test_wait_returns_immediately_when_the_database_answers(monkeypatch):
    monkeypatch.setattr(startup, "_reachable", _always(True))
    monkeypatch.setattr(startup, "_start_local_stack", _boom)
    assert startup.wait_for_database("postgresql+asyncpg://x") is True


def test_wait_starts_the_local_stack_once_and_polls_until_up(monkeypatch):
    answers = iter([False, False, True])
    started = []
    monkeypatch.setattr(startup, "_reachable", lambda url: _coro(next(answers)))
    monkeypatch.setattr(startup, "_start_local_stack", lambda: started.append(1))
    monkeypatch.setattr(startup.time, "sleep", lambda s: None)
    assert startup.wait_for_database("postgresql+asyncpg://x", timeout=60) is True
    assert started == [1]


def test_wait_gives_up_after_the_timeout(monkeypatch):
    monkeypatch.setattr(startup, "_reachable", _always(False))
    monkeypatch.setattr(startup, "_start_local_stack", lambda: None)
    monkeypatch.setattr(startup.time, "sleep", lambda s: None)
    clock = iter(range(0, 10_000, 30))
    monkeypatch.setattr(startup.time, "monotonic", lambda: next(clock))
    assert startup.wait_for_database("postgresql+asyncpg://x", timeout=60) is False


async def _coro(value):
    return value


def _always(value):
    return lambda url: _coro(value)


def _boom():
    raise AssertionError("must not start the stack when the database answers")


def test_already_running_detects_a_server_on_the_port():
    # Windows lets two processes bind the same port (SO_REUSEADDR); a second `serve` must
    # notice the first one instead of silently sharing connections with it
    import socket
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Health(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def log_message(self, *a):
            pass

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    assert startup.already_running("127.0.0.1", free_port) is False
    server = HTTPServer(("127.0.0.1", 0), Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert startup.already_running("127.0.0.1", server.server_address[1]) is True
    finally:
        server.shutdown()
