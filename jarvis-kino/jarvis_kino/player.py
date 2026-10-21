"""Steuert mpv: Start, Fortschritt über die JSON-IPC, Folgenwechsel, Abbrüche."""
import json
import os
import shlex
import shutil
import tempfile
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal
from PyQt6.QtNetwork import QLocalSocket

from .einstellungen import DATEN, MPV_ORDNER
from .folgen import video_id_aus_url

TONSPRACHEN = {
    "de": "de,deu,ger,en,eng",
    "en": "en,eng,de,deu,ger",
    "original": "",
}
UNTERTITEL = {
    "aus": "",
    "de": "de,deu,ger",
    "en": "en,eng",
}


def mpv_argumente(einst, sock, logdatei, daten_pfad, playlist_pfad, start_index, cookie, referer, user_agent):
    """Baut die Kommandozeile für mpv (eigene Konfiguration, ändert nichts am System-mpv)."""
    args = [
        f"--config-dir={MPV_ORDNER}",
        f"--input-ipc-server={sock}",
        f"--log-file={logdatei}",
        "--fs",
        "--force-window=immediate",
        "--keep-open=always",  # Ende/Abbruch entscheidet jarvis.lua
        "--idle=no",
        f"--hwdec={einst.get('hwdec') or 'auto-safe'}",
        f"--script-opts-append=jarvis-daten={daten_pfad}",
        f"--playlist={playlist_pfad}",
        f"--playlist-start={start_index}",
    ]
    alang = TONSPRACHEN.get(einst.get("tonsprache"), TONSPRACHEN["de"])
    if alang:
        args.append(f"--alang={alang}")
    slang = UNTERTITEL.get(einst.get("untertitel"), "")
    if slang:
        args.append(f"--slang={slang}")
    else:
        args.append("--sid=auto")
    if cookie:
        # Alle Adressen in der Playlist zeigen auf Jarvis (Mediathek-Weiterleitungen
        # löst die App vorher auf), daher geht die Anmeldung nur an Jarvis.
        args.append(f"--http-header-fields-append=Cookie: {cookie}")
    if referer:
        args.append(f"--referrer={referer}")
    if user_agent:
        args.append(f"--user-agent={user_agent}")
    # Für Fehlersuche, z. B. JARVIS_KINO_MPV_ARGS="--hwdec=no --msg-level=all=debug"
    args += shlex.split(os.environ.get("JARVIS_KINO_MPV_ARGS", ""))
    return args


class PlayerSitzung(QObject):
    stand = pyqtSignal(str, float, float, bool)          # id, pos, dauer, pausiert
    folge_gewechselt = pyqtSignal(str, float, float, str)  # alte id, pos, dauer, neue id
    beendet = pyqtSignal(dict)
    meldung = pyqtSignal(str)

    MAX_NEUSTARTS = 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.prozess = None
        self.sock = None
        self.puffer = b""
        self.ordner = Path(tempfile.mkdtemp(prefix="jarvis-kino-"))
        self.sock_pfad = str(self.ordner / "mpv.sock")
        self.log_pfad = DATEN / "mpv.log"
        self.verbinden_uhr = QTimer(self, interval=100, timeout=self._verbinden)
        self.url_ids = {}
        self._zuruecksetzen()

    def _zuruecksetzen(self):
        self.aktuelle_id = None
        self.pos = 0.0
        self.dauer = 0.0
        self.pausiert = False
        self.letzte_positionen = {}   # id -> (pos, dauer)
        self.spielende_id = None
        self.bereit = False
        self.gestartet_um = 0.0
        self.hatte_position = False

    @property
    def laeuft(self):
        return self.prozess is not None and self.prozess.state() != QProcess.ProcessState.NotRunning

    @staticmethod
    def verfuegbar():
        return shutil.which("mpv") is not None

    def starten(self, einst, urls, start_index, daten, cookie, referer, user_agent):
        """urls: Liste der Video-Adressen (Folgen), daten: Infos für jarvis.lua."""
        if self.laeuft:
            self.befehl("quit")
            self.prozess.waitForFinished(3000)
        self._zuruecksetzen()
        self.url_ids = {f.get("url"): f.get("id") for f in daten.get("folgen", []) if f.get("url")}
        daten_pfad = self.ordner / "daten.json"
        daten_pfad.write_text(json.dumps(daten, ensure_ascii=False), encoding="utf-8")
        playlist = self.ordner / "folgen.m3u"
        playlist.write_text("#EXTM3U\n" + "".join(f"{u}\n" for u in urls), encoding="utf-8")
        try:
            os.unlink(self.sock_pfad)
        except FileNotFoundError:
            pass
        DATEN.mkdir(parents=True, exist_ok=True)
        args = mpv_argumente(einst, self.sock_pfad, self.log_pfad, daten_pfad, playlist,
                             start_index, cookie, referer, user_agent)
        self.prozess = QProcess(self)
        self.prozess.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.prozess.readyReadStandardOutput.connect(lambda: self.prozess.readAllStandardOutput())
        self.prozess.finished.connect(self._prozess_ende)
        self.prozess.errorOccurred.connect(self._prozess_fehler)
        self.gestartet_um = time.monotonic()
        self.prozess.start("mpv", args)
        self.verbinden_uhr.start()

    # ------------------------------------------------------------ IPC
    def _verbinden(self):
        if not self.laeuft:
            self.verbinden_uhr.stop()
            return
        if not os.path.exists(self.sock_pfad):
            return
        self.verbinden_uhr.stop()
        self.sock = QLocalSocket(self)
        self.sock.readyRead.connect(self._lesen)
        self.sock.connected.connect(self._beobachten)
        self.sock.errorOccurred.connect(lambda *_: self.laeuft and QTimer.singleShot(200, self._neu_verbinden))
        self.sock.connectToServer(self.sock_pfad)

    def _neu_verbinden(self):
        if self.laeuft and (self.sock is None or self.sock.state() != QLocalSocket.LocalSocketState.ConnectedState):
            self.verbinden_uhr.start()

    def _beobachten(self):
        for nr, name in enumerate(("time-pos", "duration", "pause", "path"), start=1):
            self._senden({"command": ["observe_property", nr, name]})

    def _senden(self, nachricht):
        if self.sock and self.sock.state() == QLocalSocket.LocalSocketState.ConnectedState:
            self.sock.write(json.dumps(nachricht).encode() + b"\n")
            self.sock.flush()

    def befehl(self, *teile):
        self._senden({"command": list(teile)})

    def springen(self, pos):
        self.befehl("seek", float(pos), "absolute")

    def _lesen(self):
        self.puffer += bytes(self.sock.readAll())
        *zeilen, self.puffer = self.puffer.split(b"\n")
        for zeile in zeilen:
            try:
                self._verarbeiten(json.loads(zeile))
            except ValueError:
                continue

    def _verarbeiten(self, n):
        ereignis = n.get("event")
        if ereignis == "property-change":
            name, wert = n.get("name"), n.get("data")
            if name == "path":
                neue_id = self.url_ids.get(wert) or video_id_aus_url(wert or "")
                if neue_id and neue_id != self.aktuelle_id:
                    alte = self.aktuelle_id
                    if alte:
                        self.letzte_positionen[alte] = (self.pos, self.dauer)
                        self.folge_gewechselt.emit(alte, self.pos, self.dauer, neue_id)
                    self.aktuelle_id = neue_id
                    self.pos, self.dauer = 0.0, 0.0
                    self.bereit = False
                return
            if name == "time-pos" and isinstance(wert, (int, float)):
                if not self.bereit:
                    return  # vor dem Sprung zur gespeicherten Stelle steht kurz 0 da
                self.pos = float(wert)
                self.hatte_position = True
                self.spielende_id = self.aktuelle_id
            elif name == "duration" and isinstance(wert, (int, float)):
                self.dauer = float(wert)
            elif name == "pause" and isinstance(wert, bool):
                self.pausiert = wert
            else:
                return
            if self.aktuelle_id and self.bereit:
                self.letzte_positionen[self.aktuelle_id] = (self.pos, self.dauer)
                self.stand.emit(self.aktuelle_id, self.pos, self.dauer, self.pausiert)
        elif ereignis == "start-file":
            self.bereit = False
        elif ereignis == "playback-restart":
            self.bereit = True
            self.hatte_position = True
        elif ereignis == "end-file" and n.get("reason") == "error":
            self.meldung.emit(f"Wiedergabe-Fehler: {n.get('file_error') or 'unbekannt'}")

    # --------------------------------------------------------- Ende
    def _prozess_fehler(self, fehler):
        if fehler == QProcess.ProcessError.FailedToStart:
            self.verbinden_uhr.stop()
            self.beendet.emit({"fehler": "mpv konnte nicht gestartet werden. Ist mpv installiert?",
                               "neustart": False, "positionen": {}, "id": None, "pos": 0, "code": -1})

    # Exit-Codes von jarvis.lua: 4 = Verbindung weg (andere Adresse suchen),
    # 5 = Video ließ sich gar nicht laden.
    NETZ_WEG = 4
    LADEFEHLER = 5

    def _prozess_ende(self, code, status):
        self.verbinden_uhr.stop()
        if self.sock:
            self.sock.abort()
            self.sock = None
        laufzeit = time.monotonic() - self.gestartet_um
        absturz = status == QProcess.ExitStatus.CrashExit or code not in (0, self.NETZ_WEG, self.LADEFEHLER)
        neustart = (code == self.NETZ_WEG or absturz) and self.hatte_position
        info = {
            "id": self.spielende_id or self.aktuelle_id,
            "pos": self.letzte_positionen.get(self.spielende_id, (self.pos, self.dauer))[0],
            "positionen": dict(self.letzte_positionen),
            "code": code,
            "neustart": neustart,
            "fehler": None,
        }
        if not neustart and (code in (self.NETZ_WEG, self.LADEFEHLER) or absturz):
            info["fehler"] = self._fehlertext(laufzeit)
        self.beendet.emit(info)

    def _fehlertext(self, laufzeit):
        try:
            zeilen = self.log_pfad.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            zeilen = []
        wichtig = [z for z in zeilen if any(w in z for w in ("[e]", "error", "Error", "HTTP", "Failed", "failed"))]
        text = "\n".join(wichtig[-8:]) or "\n".join(zeilen[-8:])
        if "401" in text or "403" in text:
            return "Der Server hat das Video abgelehnt (nicht angemeldet?).\n\n" + text
        return f"Das Video ließ sich nicht starten (nach {laufzeit:.0f} s).\n\n{text}"

    def beenden(self):
        if self.laeuft:
            self.befehl("quit")
            if not self.prozess.waitForFinished(2000):
                self.prozess.kill()
        shutil.rmtree(self.ordner, ignore_errors=True)
