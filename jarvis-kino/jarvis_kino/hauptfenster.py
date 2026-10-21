"""Hauptfenster: Jarvis-Kino-Oberfläche + Übergabe der Videos an mpv."""
import json
import logging
import sqlite3
import time
from collections import deque
from pathlib import Path
from urllib.parse import quote, urlsplit

from PyQt6.QtCore import QByteArray, QFile, QIODevice, QObject, Qt, QTimer, QUrl, pyqtSlot
from PyQt6.QtGui import QAction, QIcon, QKeySequence
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkInformation, QNetworkRequest
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile, QWebEngineScript,
                                   QWebEngineSettings)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QMainWindow, QMessageBox

from . import einstellungen
from .dialog import EinstellungenDialog
from .einstellungen import DATEN, Fortschritt, fast_fertig
from .folgen import anzeige_titel, folgen_aus_antworten, video_id_aus_url
from .meldung import anfrage_bauen, gueltige_vorlage
from .netz import AdressSucher, basis_tauschen
from .player import PlayerSitzung

log = logging.getLogger("jarvis-kino")
HIER = Path(__file__).resolve().parent

# Jarvis-Design: dunkle Graustufen, weiche Übergänge (wie macOS/iOS)
FEHLERSEITE = """<!doctype html><html lang="de"><head><meta charset="utf-8"><style>
body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;background:#0a0a0b;
color:#f5f5f7;font-family:'Noto Sans',system-ui,sans-serif;-webkit-font-smoothing:antialiased}
.k{max-width:620px;padding:36px 40px;text-align:center;background:#1c1c1e;border-radius:22px;
border:1px solid rgba(235,235,245,.08);animation:ein .5s cubic-bezier(.2,.8,.2,1)}
@keyframes ein{from{opacity:0;transform:translateY(10px) scale(.98)}to{opacity:1;transform:none}}
h1{font-size:26px;font-weight:600;letter-spacing:-.02em;margin:0 0 10px}
p{color:rgba(235,235,245,.6);font-size:16px;line-height:1.55;margin:0}
a{display:inline-block;margin:22px 6px 0;padding:11px 22px;border-radius:12px;text-decoration:none;font-weight:600;
font-size:15px;transition:transform .2s,background .2s}a:hover{transform:scale(1.03)}
.h{background:#e5e5ea;color:#0a0a0b}.n{background:#2c2c2e;color:#f5f5f7}.z{color:rgba(235,235,245,.35);font-size:13px;margin-top:20px}
</style></head><body><div class="k"><h1>{titel}</h1><p>{text}</p>
<a class="h" href="jarviskino://neu">Erneut versuchen</a><a class="n" href="jarviskino://einstellungen">Adressen bearbeiten</a>
<p class="z">{zusatz}</p></div><script>
var s={sekunden};setInterval(function(){if(s>0){s--;var e=document.getElementById('c');if(e)e.textContent=s;}},1000);
</script></body></html>"""


class Bruecke(QObject):
    """Wird per QWebChannel in die Kino-Seite gereicht (siehe bruecke.js)."""

    def __init__(self, fenster):
        super().__init__(fenster)
        self.fenster = fenster

    @pyqtSlot(str)
    def abspielen(self, text):
        try:
            self.fenster.abspielen(json.loads(text))
        except Exception:  # noqa: BLE001 – die App darf hier nie abstürzen
            log.exception("Abspielen fehlgeschlagen")

    @pyqtSlot(str, str)
    def kinodaten(self, url, text):
        try:
            self.fenster.antworten.appendleft(json.loads(text))
        except ValueError:
            pass

    @pyqtSlot(str)
    def vorlage(self, text):
        try:
            vorlage = json.loads(text)
        except ValueError:
            return
        if gueltige_vorlage(vorlage):
            self.fenster.vorlage = vorlage
            log.info("Fortschritt-Format erkannt: %s", vorlage.get("felder"))

    @pyqtSlot(float)
    def springen(self, pos):
        if self.fenster.player.laeuft:
            self.fenster.player.springen(pos)

    @pyqtSlot(str)
    def log(self, text):
        log.info("Seite: %s", text)


class KinoSeite(QWebEnginePage):
    def __init__(self, profil, fenster):
        super().__init__(profil, fenster)
        self.fenster = fenster

    def acceptNavigationRequest(self, url, art, hauptframe):
        if url.scheme() == "jarviskino":
            QTimer.singleShot(0, lambda: self.fenster.interner_link(url.host()))
            return False
        return super().acceptNavigationRequest(url, art, hauptframe)

    def createWindow(self, _art):
        return self  # Links mit target=_blank im selben Fenster öffnen

    def javaScriptConsoleMessage(self, stufe, text, zeile, quelle):
        if stufe == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            log.debug("JS-Fehler %s:%s %s", quelle, zeile, text)


def _qwebchannel_js():
    datei = QFile(":/qtwebchannel/qwebchannel.js")
    if not datei.open(QIODevice.OpenModeFlag.ReadOnly):
        raise RuntimeError("qwebchannel.js nicht gefunden (PyQt6-WebEngine unvollständig?)")
    return bytes(datei.readAll()).decode("utf-8")


class Hauptfenster(QMainWindow):
    def __init__(self, einst):
        super().__init__()
        self.einst = einst
        self.basis = None
        self.antworten = deque(maxlen=40)
        self.vorlage = None
        self.fortschritt = Fortschritt()
        self.seiten_id = None
        self.seiten_basis = None
        self.seite_verbunden = False
        self.folgen_ids = []
        self.letzter_start = None
        self.neustarts = 0
        self.gemeldet = {}
        self.andere_gemeldet = False
        self.letztes_js = 0.0
        self.letztes_sichern = time.monotonic()
        self.kekse = {}
        self.ziel_pfad = ""

        self.setWindowTitle("Jarvis Kino")
        self.setWindowIcon(QIcon.fromTheme("jarvis-kino", QIcon(str(HIER.parent / "jarvis-kino.svg"))))
        self.resize(1440, 900)
        self.setStyleSheet("QMainWindow{background:#0a0a0b}")

        self._web_einrichten()
        self.player = PlayerSitzung(self)
        self.player.stand.connect(self._stand)
        self.player.folge_gewechselt.connect(self._folge_gewechselt)
        self.player.beendet.connect(self._player_ende)
        self.player.meldung.connect(lambda t: log.warning(t))

        self.nam = QNetworkAccessManager(self)
        self.sucher = AdressSucher(self)
        self.sucher.gefunden.connect(self._basis_gefunden)
        self.sucher.nichts_gefunden.connect(self._nichts_erreichbar)
        self.wiederholen = QTimer(self, singleShot=True, timeout=self.adresse_suchen)

        self._aktionen()
        self._netzwechsel_beobachten()

    # ------------------------------------------------------------ Aufbau
    def _web_einrichten(self):
        (DATEN / "web").mkdir(parents=True, exist_ok=True)
        self.profil = QWebEngineProfile("jarvis-kino", self)
        self.profil.setPersistentStoragePath(str(DATEN / "web"))
        self.profil.setCachePath(str(DATEN / "cache"))
        self.profil.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
        self.profil.setHttpCacheMaximumSize(300 * 1024 * 1024)
        self.profil.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        self.profil.setHttpUserAgent(self.profil.httpUserAgent() + " JarvisKinoDesktop/1.0")
        self.profil.setHttpAcceptLanguage("de-DE,de;q=0.9,en;q=0.6")

        skript = QWebEngineScript()
        skript.setName("jarvis-bruecke")
        skript.setSourceCode(_qwebchannel_js() + "\n" + (HIER / "bruecke.js").read_text(encoding="utf-8"))
        skript.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        skript.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        skript.setRunsOnSubFrames(False)
        self.profil.scripts().insert(skript)

        speicher = self.profil.cookieStore()
        speicher.cookieAdded.connect(self._keks_neu)
        speicher.cookieRemoved.connect(self._keks_weg)
        speicher.loadAllCookies()

        self.seite = KinoSeite(self.profil, self)
        self.kanal = QWebChannel(self.seite)
        self.bruecke = Bruecke(self)
        self.kanal.registerObject("jarvis", self.bruecke)
        self.seite.setWebChannel(self.kanal)

        e = self.seite.settings()
        A = QWebEngineSettings.WebAttribute
        e.setAttribute(A.PlaybackRequiresUserGesture, False)
        e.setAttribute(A.FullScreenSupportEnabled, True)
        e.setAttribute(A.ScrollAnimatorEnabled, True)
        e.setAttribute(A.LocalStorageEnabled, True)
        e.setAttribute(A.JavascriptCanOpenWindows, True)
        e.setAttribute(A.FocusOnNavigationEnabled, True)
        self.seite.fullScreenRequested.connect(self._vollbild_anfrage)
        self.seite.renderProcessTerminated.connect(self._renderer_weg)
        self.seite.loadFinished.connect(self._geladen)
        self.seite.loadStarted.connect(self._laedt)
        self.seite.setBackgroundColor(Qt.GlobalColor.black)

        self.ansicht = QWebEngineView(self)
        self.ansicht.setPage(self.seite)
        self.ansicht.setZoomFactor(float(self.einst.get("zoom") or 1.0))
        self.setCentralWidget(self.ansicht)

    def _aktionen(self):
        def aktion(text, tasten, fn):
            a = QAction(text, self)
            a.setShortcuts([QKeySequence(t) for t in tasten])
            a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            a.triggered.connect(fn)
            self.addAction(a)
            self.ansicht.addAction(a)
            return a

        aktion("Zurück", ["Alt+Left", "Back"], self.ansicht.back)
        aktion("Neu laden", ["F5", "Ctrl+R"], self.neu_laden)
        aktion("Vollbild an/aus", ["F11"], self.vollbild_umschalten)
        aktion("Größer", ["Ctrl++", "Ctrl+="], lambda: self._zoom(0.1))
        aktion("Kleiner", ["Ctrl+-"], lambda: self._zoom(-0.1))
        aktion("Normale Größe", ["Ctrl+0"], lambda: self._zoom(None))
        aktion("Andere Jarvis-Adresse suchen", ["Ctrl+Shift+R"], self.adresse_suchen)
        aktion("Einstellungen …", ["Ctrl+,"], self.einstellungen_zeigen)
        aktion("Beenden", ["Ctrl+Q"], self.close)
        self.ansicht.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)

    def _netzwechsel_beobachten(self):
        try:
            if QNetworkInformation.loadDefaultBackend() and QNetworkInformation.instance():
                info = QNetworkInformation.instance()
                info.reachabilityChanged.connect(lambda *_: QTimer.singleShot(1500, self._netz_geaendert))
        except Exception:  # noqa: BLE001 – Backend fehlt auf manchen Systemen
            log.info("Keine Netzwerk-Statusmeldungen verfügbar")

    # --------------------------------------------------------- Adressen
    def start(self):
        if self.einst.get("app_vollbild"):
            self.showFullScreen()
        else:
            self.showMaximized()
        self._fehlerseite("Verbinde mit Jarvis …", "Suche nach Heimnetz, jarvis.local und Cloudflare.", 0, warten=True)
        self.adresse_suchen()

    def adresse_suchen(self):
        self.wiederholen.stop()
        if not self.sucher.laeuft:
            log.info("Suche Jarvis unter %s", self.einst["adressen"])
            self.sucher.suchen(self.einst["adressen"])

    def _netz_geaendert(self):
        if not self.player.laeuft:
            self.adresse_suchen()

    def _basis_gefunden(self, basis):
        alt = self.basis
        self.basis = basis
        log.info("Jarvis erreichbar unter %s", basis)
        if self.einst.get("letzte_adresse") != basis:
            self.einst["letzte_adresse"] = basis
            einstellungen.speichern(self.einst)
        if self.letzter_start and self.letzter_start.get("neustart_wartet"):
            self._neustart_ausfuehren()
        if self.player.laeuft or self.letzter_start:
            return  # Seite erst nach dem Film umstellen, sonst geht ihr Zustand verloren
        self._seite_umstellen(alt)

    def _seite_umstellen(self, alt):
        basis = self.basis
        aktuell = self.seite.url().toString()
        if alt == basis and aktuell.startswith(basis):
            return
        if alt and aktuell.startswith(alt):
            ziel = basis_tauschen(aktuell, alt, basis)
        elif self.ziel_pfad:
            ziel = basis + self.ziel_pfad
        else:
            ziel = basis
        self.seite.load(QUrl(ziel))

    def _nichts_erreichbar(self):
        sekunden = 10
        self._fehlerseite(
            "Jarvis ist gerade nicht erreichbar",
            "Geprüft: " + ", ".join(urlsplit(a).netloc for a in self.einst["adressen"])
            + ".<br>Ist der Server an? Bist du online? Unterwegs brauchst du die aktuelle Cloudflare-Adresse.",
            sekunden)
        if self.letzter_start and self.letzter_start.get("neustart_wartet"):
            self.neustarts += 1
            if self.neustarts > 6:
                self.letzter_start = None
        self.wiederholen.start(sekunden * 1000)

    def _fehlerseite(self, titel, text, sekunden, warten=False):
        zusatz = "" if warten or not sekunden else 'Neuer Versuch in <span id="c">%d</span> s …' % sekunden
        html = (FEHLERSEITE.replace("{titel}", titel).replace("{text}", text)
                .replace("{zusatz}", zusatz).replace("{sekunden}", str(sekunden)))
        self.seite.setHtml(html, QUrl("about:blank"))

    def interner_link(self, was):
        if was == "einstellungen":
            self.einstellungen_zeigen()
        else:
            self.adresse_suchen()

    def _laedt(self):
        # Neue Seite = das <video>-Element der alten Seite gibt es nicht mehr.
        self.seite_verbunden = False

    def _geladen(self, ok):
        url = self.seite.url().toString()
        if url.startswith("about:") or url.startswith("data:"):
            return
        if ok:
            self.neustarts = 0 if not self.player.laeuft else self.neustarts
            if self.basis and url.startswith(self.basis):
                self.ziel_pfad = url[len(self.basis):]
            return
        log.warning("Seite konnte nicht geladen werden: %s", url)
        self._fehlerseite("Verbindung zu Jarvis verloren", "Suche eine andere Adresse …", 0, warten=True)
        QTimer.singleShot(500, self.adresse_suchen)

    def neu_laden(self):
        if self.basis and self.seite.url().toString().startswith(self.basis):
            self.seite.triggerAction(QWebEnginePage.WebAction.ReloadAndBypassCache)
        else:
            self.adresse_suchen()

    def _renderer_weg(self, status, code):
        if status != QWebEnginePage.RenderProcessTerminationStatus.NormalTerminationStatus:
            log.warning("Anzeige abgestürzt (%s, %s) – lade neu", status, code)
            QTimer.singleShot(1000, self.neu_laden)

    # ------------------------------------------------------------ Cookies
    @staticmethod
    def _keks_schluessel(keks):
        return (keks.domain(), keks.path(), bytes(keks.name()).decode("latin-1"))

    def _keks_neu(self, keks):
        # Qt gibt das Cookie-Objekt nach dem Signal frei – nur die Werte merken.
        self.kekse[self._keks_schluessel(keks)] = (bytes(keks.value()).decode("latin-1"), keks.isSecure())

    def _keks_weg(self, keks):
        self.kekse.pop(self._keks_schluessel(keks), None)

    def _gespeicherte_kekse(self):
        """Cookies aus der Datenbank des eingebauten Browsers.

        Qt meldet beim Start keine gespeicherten Cookies (nur neu gesetzte),
        daher wird die Anmeldung vom letzten Mal hier direkt gelesen."""
        datei = DATEN / "web" / "Cookies"
        if not datei.exists():
            return {}
        try:
            verbindung = sqlite3.connect(f"file:{datei}?mode=ro", uri=True, timeout=2)
            try:
                zeilen = verbindung.execute(
                    "SELECT host_key, path, name, value, is_secure FROM cookies WHERE value != ''").fetchall()
            finally:
                verbindung.close()
        except sqlite3.Error as fehler:
            log.warning("Cookie-Speicher nicht lesbar: %s", fehler)
            return {}
        return {(d, p, n): (w, bool(sicher)) for d, p, n, w, sicher in zeilen}

    def _cookie_kopf(self, host):
        alle = self._gespeicherte_kekse()
        alle.update(self.kekse)  # frisch gesetzte Cookies haben Vorrang
        werte = {}
        for (domain, _pfad, name), (wert, _sicher) in alle.items():
            d = domain.lstrip(".")
            if host == d or host.endswith("." + d):
                werte[name] = wert
        return "; ".join(f"{n}={w}" for n, w in werte.items())

    # ------------------------------------------------------------ Abspielen
    def abspielen(self, info):
        if not PlayerSitzung.verfuegbar():
            QMessageBox.critical(self, "Jarvis Kino", "mpv ist nicht installiert.\nBitte install.sh erneut ausführen.")
            return
        vid = info.get("id") or video_id_aus_url(info.get("quelle", ""))
        quelle = info.get("quelle") or ""
        self.seiten_id = vid
        self.seiten_basis = self.basis
        self.seite_verbunden = True
        self.gemeldet = {}
        self.andere_gemeldet = False
        self.neustarts = 0

        if "/api/video/" in quelle:
            praefix = quelle.split("/api/video/", 1)[0] + "/api/video/datei/"
        elif self.basis:
            praefix = self.basis + "api/video/datei/"
        else:
            praefix = None

        serie, folgen = folgen_aus_antworten(self.antworten, vid) if vid else (None, [])
        if len(folgen) < 2 or not praefix:
            folgen = [{"id": vid or "", "titel": info.get("titel") or "", "staffel": None, "folge": None,
                       "position": 0.0, "dauer": 0.0, "gesehen": False}]
            urls = [praefix + quote(vid, safe="") if (vid and praefix) else quelle]
            serie = None
        else:
            urls = [praefix + quote(f["id"], safe="") for f in folgen]
        for f in folgen:
            f["anzeige"] = anzeige_titel(serie, f) or info.get("titel") or ""
        start_index = next((i for i, f in enumerate(folgen) if f["id"] == vid), 0)

        start = {}
        for f in folgen:
            lokal = self.fortschritt.holen(f["id"])
            if lokal > f.get("position", 0) + 5:
                start[f["id"]] = lokal
        seiten_start = float(info.get("start") or 0)
        if vid:
            if seiten_start > 1:
                start[vid] = seiten_start
            elif vid not in start and folgen[start_index].get("position", 0) <= 1:
                lokal = self.fortschritt.holen(vid)
                if lokal > 1:
                    start[vid] = lokal

        daten = {"serie": serie, "folgen": folgen, "start": start, "intro_schaetzen": bool(serie)}
        self.folgen_ids = [f["id"] for f in folgen]
        self.letzter_start = {"urls": urls, "index": start_index, "daten": daten,
                              "referer": info.get("seite") or self.basis or "", "basis": self.basis}
        log.info("Starte %s (%d Folgen, Start %s)", vid, len(folgen), start.get(vid, 0))
        self._weiterleitungen_aufloesen(self._player_starten)

    def _weiterleitungen_aufloesen(self, fertig):
        """Mediathek-Titel (mt-…) leitet Jarvis zum Sender weiter. Die Weiterleitung wird
        hier aufgelöst, damit die Jarvis-Anmeldung nie an fremde Server geht."""
        s = self.letzter_start
        offen = [i for i, u in enumerate(s["urls"]) if "/api/video/datei/mt-" in u]
        if not offen:
            fertig()
            return
        rest = [len(offen)]

        def eins_fertig(i, antwort):
            ziel = antwort.attribute(QNetworkRequest.Attribute.RedirectionTargetAttribute)
            if ziel is not None and ziel.toString():
                s["urls"][i] = QUrl(s["urls"][i]).resolved(ziel).toString()
            antwort.deleteLater()
            rest[0] -= 1
            if rest[0] == 0 and self.letzter_start is s:
                fertig()

        for i in offen:
            anfrage = QNetworkRequest(QUrl(s["urls"][i]))
            anfrage.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                                 QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
            anfrage.setRawHeader(b"User-Agent", self.profil.httpUserAgent().encode())
            keks = self._cookie_kopf(urlsplit(s["urls"][i]).hostname or "")
            if keks:
                anfrage.setRawHeader(b"Cookie", keks.encode("latin-1"))
            anfrage.setTransferTimeout(8000)
            antwort = self.nam.get(anfrage)
            # Nur die Kopfzeilen interessieren – nicht den ganzen Film laden.
            antwort.metaDataChanged.connect(lambda a=antwort: a.abort())
            antwort.finished.connect(lambda i=i, a=antwort: eins_fertig(i, a))

    def _player_starten(self):
        s = self.letzter_start
        for folge, url in zip(s["daten"]["folgen"], s["urls"]):
            folge["url"] = url
        start_url = s["urls"][s["index"]] if s["urls"] else ""
        self.player.starten(self.einst, s["urls"], s["index"], s["daten"],
                            self._cookie_kopf(urlsplit(start_url).hostname or ""),
                            s["referer"], self.profil.httpUserAgent())

    def _seite_meldet(self, vid):
        """True, wenn die Kino-Seite den Fortschritt dieser Folge selbst speichert."""
        return vid == self.seiten_id and self.seite_verbunden and self.seiten_basis == self.basis

    def _stand(self, vid, pos, dauer, pausiert):
        self.fortschritt.setzen(vid, pos, dauer)
        jetzt = time.monotonic()
        if vid == self.seiten_id and self.seite_verbunden and jetzt - self.letztes_js >= 1.0:
            self.letztes_js = jetzt
            self.seite.runJavaScript(
                f"window.__jarvisKino&&window.__jarvisKino.stand({pos:.3f},{dauer:.3f},{str(pausiert).lower()})")
        if not self._seite_meldet(vid) and jetzt - self.gemeldet.get(vid, 0) >= 15:
            self._melden(vid, pos, dauer)
        if jetzt - self.letztes_sichern > 20:
            self.letztes_sichern = jetzt
            self.fortschritt.sichern()

    def _folge_gewechselt(self, alte, pos, dauer, neue):
        if alte == self.seiten_id and self.seite_verbunden:
            self.seite.runJavaScript(
                f"window.__jarvisKino&&window.__jarvisKino.stand({pos:.3f},{dauer:.3f},true)")
        self._melden(alte, pos, dauer, sofort=True)
        self.fortschritt.setzen(alte, pos, dauer)

    def _melden(self, vid, pos, dauer, sofort=False):
        if not vid or not self.vorlage or not self.basis:
            return
        if self._seite_meldet(vid) and not sofort:
            return  # das erledigt die Seite selbst
        self.gemeldet[vid] = time.monotonic()
        if vid != self.seiten_id:
            self.andere_gemeldet = True
        try:
            url, methode, kopf, body = anfrage_bauen(self.vorlage, vid, pos, dauer, self.basis)
        except (KeyError, TypeError, ValueError):
            log.exception("Fortschritt-Meldung nicht möglich")
            return
        anfrage = QNetworkRequest(QUrl(url))
        for k, v in kopf.items():
            anfrage.setRawHeader(k.encode(), v.encode())
        teile = urlsplit(self.basis)
        anfrage.setRawHeader(b"Origin", f"{teile.scheme}://{teile.netloc}".encode())
        anfrage.setRawHeader(b"Referer", self.basis.encode())
        anfrage.setRawHeader(b"User-Agent", self.profil.httpUserAgent().encode())
        keks = self._cookie_kopf(urlsplit(url).hostname or "")
        if keks:
            anfrage.setRawHeader(b"Cookie", keks.encode("latin-1"))
        anfrage.setTransferTimeout(15000)
        antwort = self.nam.sendCustomRequest(anfrage, QByteArray(methode.encode()), QByteArray(body))
        antwort.finished.connect(lambda a=antwort: (
            a.error() != a.NetworkError.NoError and log.warning("Fortschritt %s nicht gespeichert: %s", vid, a.errorString()),
            a.deleteLater()))

    def _player_ende(self, info):
        self.fortschritt.sichern()
        if info.get("neustart") and self.letzter_start and self.neustarts < 6:
            self.neustarts += 1
            vid = info.get("id")
            if vid in self.folgen_ids:
                self.letzter_start["index"] = self.folgen_ids.index(vid)
                self.letzter_start["daten"]["start"][vid] = max(0.0, info.get("pos", 0))
            self.letzter_start["neustart_wartet"] = True
            log.warning("Wiedergabe abgebrochen bei %s – suche Jarvis neu (Versuch %d)", info.get("pos"), self.neustarts)
            self.adresse_suchen()
            return

        positionen = info.get("positionen") or {}
        for vid, (pos, dauer) in positionen.items():
            self.fortschritt.setzen(vid, pos, dauer)
            if vid != self.seiten_id:
                self._melden(vid, pos, dauer, sofort=True)
        self.fortschritt.sichern()

        if self.seiten_id:
            pos, dauer = positionen.get(self.seiten_id, (0.0, 0.0))
            if self.seiten_id not in positionen:
                pos = float((self.letzter_start or {}).get("daten", {}).get("start", {}).get(self.seiten_id, 0))
            ende = fast_fertig(pos, dauer)
            mit_folgen = len(self.folgen_ids) > 1
            if not self._seite_meldet(self.seiten_id) and self.seiten_id in positionen:
                self._melden(self.seiten_id, pos, dauer, sofort=True)
            if self.seite_verbunden:
                self.seite.runJavaScript(
                    f"window.__jarvisKino&&window.__jarvisKino.ende({pos:.3f},{dauer:.3f},"
                    f"{str(ende).lower()},{str(mit_folgen).lower()})")
        self.letzter_start = None
        self.activateWindow()
        self.raise_()
        if self.basis and self.seiten_basis and self.seiten_basis != self.basis:
            QTimer.singleShot(1500, lambda alt=self.seiten_basis: self._seite_umstellen(alt))
            self.seiten_basis = self.basis
            return

        if info.get("fehler"):
            self._fehler_zeigen(info["fehler"])
        elif self.andere_gemeldet:
            # "Weiterschauen" der Seite auffrischen, nachdem andere Folgen gelaufen sind
            QTimer.singleShot(2500, lambda: not self.player.laeuft and self.neu_laden())

    def _neustart_ausfuehren(self):
        s = self.letzter_start
        s.pop("neustart_wartet", None)
        if s.get("basis") and s["basis"] != self.basis:
            s["urls"] = [basis_tauschen(u, s["basis"], self.basis) for u in s["urls"]]
            s["referer"] = basis_tauschen(s["referer"], s["basis"], self.basis)
            s["basis"] = self.basis
        log.info("Setze Wiedergabe fort über %s", self.basis)
        self._player_starten()

    def _fehler_zeigen(self, text):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Jarvis Kino – Wiedergabe")
        box.setText("Das Video konnte nicht abgespielt werden.")
        box.setDetailedText(text)
        ohne_hw = box.addButton("Ohne Hardware-Beschleunigung versuchen", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Schließen", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() == ohne_hw:
            self.einst["hwdec"] = "no"
            einstellungen.speichern(self.einst)
            QMessageBox.information(self, "Jarvis Kino",
                                    "Hardware-Beschleunigung ist jetzt aus. Starte das Video einfach noch einmal.\n"
                                    "In den Einstellungen (Strg+,) kannst du sie wieder einschalten.")

    # ------------------------------------------------------------ Fenster
    def _vollbild_anfrage(self, anfrage):
        anfrage.accept()
        if anfrage.toggleOn():
            self.showFullScreen()
        elif not self.einst.get("app_vollbild"):
            self.showMaximized()

    def vollbild_umschalten(self):
        if self.isFullScreen():
            self.showMaximized()
        else:
            self.showFullScreen()

    def _zoom(self, schritt):
        faktor = 1.0 if schritt is None else min(2.5, max(0.5, self.ansicht.zoomFactor() + schritt))
        self.ansicht.setZoomFactor(faktor)
        self.einst["zoom"] = round(faktor, 2)
        einstellungen.speichern(self.einst)

    def einstellungen_zeigen(self):
        dialog = EinstellungenDialog(self.einst, self)
        if dialog.exec():
            self.einst = dialog.werte()
            einstellungen.speichern(self.einst)
            self.adresse_suchen()

    def closeEvent(self, ereignis):
        self.player.beenden()
        self.fortschritt.sichern()
        super().closeEvent(ereignis)
