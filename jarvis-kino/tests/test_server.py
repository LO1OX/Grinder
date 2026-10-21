"""Nachgebautes Jarvis-Kino für Ende-zu-Ende-Tests: python3 tests/test_server.py <port> <videoordner>

- /kino/ verlangt Anmeldung (Cookie), sonst Weiterleitung auf /anmelden.html
- Serie "Testserie" mit 2 Staffeln / 3 Folgen, Videos mit Range-Unterstützung
- Fortschritt wird gespeichert und unter /test/fortschritt ausgegeben
- Folge ep3 bricht beim ersten Abruf mittendrin ab (Verbindungsabbruch)
"""
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VIDEOS = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(".")
SERIE = {"titel": "Testserie", "staffeln": [
    {"staffel": 1, "folgen": [{"id": "ep1", "titel": "Pilot", "folge": 1, "dauer": 90},
                              {"id": "ep2", "titel": "Zweite Folge", "folge": 2, "dauer": 90}]},
    {"staffel": 2, "folgen": [{"id": "ep3", "titel": "Neue Staffel", "folge": 1, "dauer": 90}]},
]}
SEITE = """<!doctype html><html><head><title>Jarvis Kino</title><script src="kino.js"></script></head>
<body style="background:#111;color:#fff"><h1>Testserie</h1><div id="player"></div>
<script>
fetch('api/kino/serie/s1').then(r => r.json()).then(serie => {
  document.title = 'Jarvis Kino – ' + serie.titel;
  setTimeout(() => {
    const v = document.createElement('video');
    v.title = 'Zweite Folge';
    document.getElementById('player').appendChild(v);
    let letzte = 0;
    v.addEventListener('timeupdate', () => {
      if (Date.now() - letzte < 2000) return;
      letzte = Date.now();
      fetch('api/video/fortschritt', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id: 'ep2', position: Math.floor(v.currentTime), dauer: v.duration || 0})});
    });
    v.addEventListener('ended', () => { document.body.dataset.ende = '1'; });
    v.src = 'api/video/datei/ep2';
    v.currentTime = 30;
    v.play();
  }, 1500);
});
</script></body></html>"""

fortschritt = []
abgebrochen = set()
sperre = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("server: " + (fmt % args) + "\n")

    def _angemeldet(self):
        return "sitzung=geheim123" in (self.headers.get("Cookie") or "")

    def _senden(self, code, body=b"", typ="text/html; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        pfad = self.path.split("?")[0]
        if pfad == "/anmelden.html":
            return self._senden(302, extra={"Location": "/kino/",
                                            "Set-Cookie": "sitzung=geheim123; Path=/; HttpOnly"})
        if pfad == "/test/fortschritt":
            with sperre:
                return self._senden(200, json.dumps(fortschritt).encode(), "application/json")
        if not pfad.startswith("/kino/"):
            return self._senden(404, b"nicht da")
        if not self._angemeldet():
            if "/api/" in pfad:
                return self._senden(401, b'{"fehler":"anmelden"}', "application/json")
            return self._senden(302, extra={"Location": "/anmelden.html"})
        if pfad == "/kino/":
            return self._senden(200, SEITE.encode())
        if pfad == "/kino/kino.js":
            return self._senden(200, b"/* kino */", "application/javascript")
        if pfad.startswith("/kino/api/kino/serie/"):
            return self._senden(200, json.dumps(SERIE).encode(), "application/json")
        m = re.match(r"/kino/api/video/datei/(\w+)$", pfad)
        if m:
            return self._video(m.group(1))
        return self._senden(404, b"nicht da")

    def _video(self, vid):
        datei = VIDEOS / f"{vid}.mkv"
        if not datei.exists():
            return self._senden(404, b"kein video")
        daten = datei.read_bytes()
        groesse = len(daten)
        anfang, ende = 0, groesse - 1
        bereich = self.headers.get("Range")
        if bereich:
            m = re.match(r"bytes=(\d*)-(\d*)", bereich)
            anfang = int(m.group(1) or 0)
            ende = int(m.group(2)) if m.group(2) else groesse - 1
        teil = daten[anfang:ende + 1]
        self.send_response(206 if bereich else 200)
        self.send_header("Content-Type", "video/x-matroska")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(len(teil)))
        if bereich:
            self.send_header("Content-Range", f"bytes {anfang}-{ende}/{groesse}")
        self.end_headers()
        if self.command == "HEAD":
            return
        if vid == "ep3" and vid not in abgebrochen and anfang < groesse // 2:
            abgebrochen.add(vid)
            self.wfile.write(teil[: groesse // 2 - anfang])
            self.wfile.flush()
            self.close_connection = True
            sys.stderr.write("server: ep3 absichtlich abgebrochen\n")
            return
        try:
            self.wfile.write(teil)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        laenge = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(laenge)
        if self.path.startswith("/kino/api/video/fortschritt") and self._angemeldet():
            with sperre:
                fortschritt.append({"body": json.loads(body or b"{}"),
                                    "ua": self.headers.get("User-Agent", "")})
            return self._senden(200, b'{"ok":1}', "application/json")
        return self._senden(401, b"nein")


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
