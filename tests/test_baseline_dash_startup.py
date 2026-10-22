# test_baseline_dash_startup.py — Page 04 embedded Dash startup regression.
from __future__ import annotations

import http.server
import threading

import pytest

from dash_apps import baseline_editor


class _HealthyThread:
    """Minimal test substitute for the existing Dash daemon thread."""

    def is_alive(self) -> bool:
        return True


class _StoppedThread:
    """Minimal test substitute for a daemon that failed before listening."""

    def is_alive(self) -> bool:
        return False


def test_wait_retries_until_dash_layout_is_available(monkeypatch):
    """The iframe must not mount after the first failed connection attempt."""
    outcomes = iter([False, False, True])
    probes = []
    monkeypatch.setattr(
        baseline_editor,
        "_dash_responding",
        lambda port: probes.append(port) or next(outcomes),
    )
    monkeypatch.setattr(baseline_editor.time, "sleep", lambda seconds: None)

    baseline_editor._wait_for_server(8050, _HealthyThread(), timeout_seconds=2.0)
    assert probes == [8050, 8050, 8050]


def test_wait_reports_thread_crash(monkeypatch):
    """A dead Dash thread needs an actionable error instead of a blank iframe."""
    monkeypatch.setattr(baseline_editor, "_dash_responding", lambda port: False)
    with pytest.raises(RuntimeError, match="stopped while starting"):
        baseline_editor._wait_for_server(8050, _StoppedThread(), timeout_seconds=1.0)


def test_probe_accepts_only_expected_dash_layout():
    """Port-open alone is insufficient: another service may occupy port 8050."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            payload = b'{"props":{"id":"spectrum-graph"}}'
            self.send_response(200)
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert baseline_editor._dash_responding(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def test_probe_rejects_unoccupied_port():
    """A failed TCP/HTTP connection must not crash the Streamlit page."""
    # A non-HTTP protocol on the ephemeral port is an equally valid failure.
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(404)
            self.end_headers()

        def log_message(self, format, *args):
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert not baseline_editor._dash_responding(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def test_start_server_checks_readiness_when_thread_already_exists(monkeypatch):
    """Later Page 4 reruns must not skip readiness while Dash is still booting."""
    thread = _HealthyThread()
    calls = []
    monkeypatch.setattr(baseline_editor, "_SERVER_THREAD", thread)
    monkeypatch.setattr(baseline_editor, "_SERVER_PORT", 8050)
    monkeypatch.setattr(baseline_editor, "_wait_for_server", lambda port, current: calls.append((port, current)))

    assert baseline_editor.start_server(8050) == 8050
    assert calls == [(8050, thread)]
