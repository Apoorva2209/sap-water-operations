"""Local web dashboard + JSON API (Python standard library only).

Runs on the edge device (Raspberry Pi / laptop) so operators can use it on the
farm Wi-Fi with no internet.  Start:  python3 -m sap.server  -> http://localhost:8080
Set SAP_PIN to require a PIN for actions (default 1234 for the demo).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .controller import Controller
from .simulator import compare

ROOT = Path(__file__).resolve().parent.parent / "dashboard"
PIN = os.environ.get("SAP_PIN", "1234")
CTRL = Controller(log_path=os.environ.get("SAP_LOG", "data/events.jsonl"))


def _default(o):
    if hasattr(o, "value"):
        return o.value
    return str(o)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, default=_default).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/state":
            return self._send(200, CTRL.state())
        if self.path == "/api/simulate":
            return self._send(200, [{k: v for k, v in asdict(r).items()} for r in compare()])
        self._send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if body.get("pin") != PIN:
            return self._send(403, {"error": "wrong PIN"})
        zid, act = body.get("zone"), self.path.rsplit("/", 1)[-1]
        if act == "approve":
            ok, msg = CTRL.approve(zid)
        elif act == "reject":
            ok, msg = CTRL.reject(zid)
        elif act == "estop":
            CTRL.emergency_stop(bool(body.get("on", True))); ok, msg = True, "ok"
        elif act == "clear":
            CTRL.clear_fault(zid); ok, msg = True, "cleared"
        elif act == "inject":
            CTRL.inject(body.get("kind"), zid); ok, msg = True, "injected"
        elif act == "replan":
            CTRL.plan(); ok, msg = True, "replanned"
        elif act == "auto":
            z = CTRL.run_auto(); ok, msg = bool(z), f"auto run {z}" if z else "no auto-approved zone"
        elif act == "network":
            CTRL.online = bool(body.get("online", True)); CTRL.plan(); ok, msg = True, "ok"
        elif act == "weather":
            CTRL.weather.rain_forecast_mm = float(body.get("rain_mm", 0)); CTRL.plan(); ok, msg = True, "ok"
        else:
            return self._send(404, {"error": "unknown action"})
        self._send(200 if ok else 400, {"ok": ok, "message": msg})


def main():
    port = int(os.environ.get("SAP_PORT", "8080"))
    print(f"SAP dashboard on http://localhost:{port}  (PIN {PIN})")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
