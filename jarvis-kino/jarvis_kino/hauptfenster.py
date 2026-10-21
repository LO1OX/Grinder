"""Hauptfenster: Jarvis-Kino-Oberfläche + Übergabe der Videos an mpv."""
import json
import logging
import shutil
import sqlite3
import subprocess
import time
from collections import deque
from pathlib import Path
from urllib.parse import quote, urlsplit

from PyQt6 import sip
from PyQt6.QtCore import (QByteArray, QEvent, QFile, QIODevice, QObject, QStandardPaths, Qt, QTimer, QUrl,
                          QUrlQuery, pyqtSlot)
from PyQt6.QtGui import QAction, QColor, QGuiApplication, QIcon, QKeySequence, QPalette
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkInformation, QNetworkRequest
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile, QWebEngineScript,
                                   QWebEngineSettings)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QMainWindow, QMenu, QMessageBox

from . import einstellungen
from .dialog import EinstellungenDialog
from .einstellungen import DATEN, Fortschritt, fast_fertig
from .folgen import anzeige_titel, folgen_aus_antworten, video_id_aus_url
from .meldung import anfrage_bauen, gueltige_vorlage
from .netz import AdressSucher, basis_tauschen
from .player import PlayerSitzung

log = logging.getLogger("jarvis-kino")
HIER = Path(__file__).resolve().parent

# Startseite: erst nur ein Ladekreisel, während die App Jarvis sucht. Nur wenn
# gar nichts erreichbar ist, erscheint ein Knopf (und bei Bedarf ein Adressfeld).
STARTSEITE = """<!doctype html><html lang="de"><head><meta charset="utf-8"><style>
html,body{margin:0;height:100%;background:#141416;color:#e5e5ea;overflow:hidden;
font-family:system-ui,-apple-system,'Ubuntu','Noto Sans',sans-serif;-webkit-font-smoothing:antialiased}
body{display:flex;align-items:center;justify-content:center}
.z{display:none;flex-direction:column;align-items:center;text-align:center;animation:ein .4s ease}
.an{display:flex}
@keyframes ein{from{opacity:0}to{opacity:1}}
.kreis{width:28px;height:28px;border-radius:50%;border:2.5px solid rgba(235,235,245,.12);
border-top-color:rgba(235,235,245,.6);animation:dreh .9s linear infinite}
@keyframes dreh{to{transform:rotate(360deg)}}
h1{font-size:19px;font-weight:600;margin:0 0 22px;color:#e5e5ea}
button{font:inherit;font-size:15px;font-weight:500;border:0;border-radius:999px;padding:10px 24px;cursor:pointer;
background:rgba(235,235,245,.14);color:#e5e5ea;transition:background .2s,opacity .2s}
button:hover{background:rgba(235,235,245,.22)}
button:disabled{opacity:.45;cursor:default}
a{color:rgba(235,235,245,.45);font-size:13px;margin-top:18px;cursor:pointer;text-decoration:none;transition:color .2s}
a:hover{color:rgba(235,235,245,.8)}
form{display:none;margin-top:14px;gap:8px;align-items:center}form.an{display:flex}
input{font:inherit;font-size:14px;width:290px;padding:9px 14px;border-radius:999px;border:1px solid rgba(235,235,245,.14);
background:rgba(235,235,245,.06);color:#e5e5ea;outline:none;transition:border-color .2s}
input:focus{border-color:rgba(235,235,245,.4)}
form button{padding:9px 16px;font-size:14px}
#hinweis{min-height:18px;margin-top:16px;color:rgba(235,235,245,.45);font-size:13px}
</style></head><body>
<div id="suche" class="z"><div class="kreis"></div></div>
<div id="fehler" class="z"><h1>Jarvis nicht erreichbar</h1>
<button id="knopf" onclick="nochmal()">Erneut suchen</button>
<a onclick="var f=document.getElementById('f');f.classList.toggle('an');document.getElementById('u').focus()">Adresse eingeben</a>
<form id="f" onsubmit="event.preventDefault();var v=document.getElementById('u').value.trim();
if(v){sucht();hinweis('Verbinde …');location.href='jarviskino://adresse?u='+encodeURIComponent(v)}">
<input id="u" placeholder="z. B. neue Cloudflare-Adresse" autocomplete="off" spellcheck="false">
<button type="submit">Verbinden</button></form>
<div id="hinweis">Die App sucht automatisch weiter.</div></div>
<script>
function zustand(n){['suche','fehler'].forEach(function(i){document.getElementById(i).classList.toggle('an',i===n)});
var k=document.getElementById('knopf');k.disabled=false;k.textContent='Erneut suchen';}
function hinweis(t){document.getElementById('hinweis').textContent=t;}
function sucht(){var k=document.getElementById('knopf');k.disabled=true;k.textContent='Suche …';}
function nochmal(){sucht();location.href='jarviskino://suchen';}
zustand('{zustand}');
</script></body></html>"""

# Scrollleisten wie unter GNOME (Overlay): schmal, rund, ohne Pfeile, nur beim Scrollen
# oder unter der Maus sichtbar. Schon ab Dokumentbeginn, damit nie die eckige Leiste aufblitzt.
SCROLLLEISTEN_CSS = (
    "::-webkit-scrollbar{width:10px;height:10px;background:transparent}"
    "::-webkit-scrollbar-track,::-webkit-scrollbar-corner{background:transparent}"
    "::-webkit-scrollbar-button{display:none;width:0;height:0}"
    "::-webkit-scrollbar-thumb{min-height:40px;min-width:40px;border-radius:99px;border:3px solid transparent;"
    "background-clip:padding-box;background-color:transparent}"
    "::-webkit-scrollbar-thumb:vertical{border-left-width:4px}::-webkit-scrollbar-thumb:horizontal{border-top-width:4px}"
    "[data-jk-scrollt]::-webkit-scrollbar-thumb{background-color:rgba(255,255,255,.2)}"
    "html::-webkit-scrollbar-thumb:hover,html ::-webkit-scrollbar-thumb:hover{border-width:2px;background-color:rgba(255,255,255,.4)}"
    "html::-webkit-scrollbar-thumb:active,html ::-webkit-scrollbar-thumb:active{border-width:2px;background-color:rgba(255,255,255,.6)}"
)
SCROLLLEISTEN_JS = """(function(){
if(window.__jkScroll)return;window.__jkScroll=1;
function einhaengen(){if(document.getElementById('jarvis-kino-scroll'))return true;
var w=document.documentElement;if(!w)return false;
var s=document.createElement('style');s.id='jarvis-kino-scroll';s.textContent=CSS;w.appendChild(s);return true;}
if(!einhaengen()){var b=new MutationObserver(function(){if(einhaengen())b.disconnect();});
b.observe(document,{childList:true,subtree:true});}
var uhren=new WeakMap();
function zeig(el){if(!el||!el.setAttribute)return;el.setAttribute('data-jk-scrollt','');clearTimeout(uhren.get(el));
uhren.set(el,setTimeout(function(){el.removeAttribute('data-jk-scrollt');},900));}
document.addEventListener('scroll',function(e){if(e.target===document){zeig(document.documentElement);zeig(document.body);}
else zeig(e.target);},{capture:true,passive:true});
})();"""
HINTERGRUND = "#141416"  # Grundton des Jarvis-Kinos


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
            # Nur die eigene Startseite darf die App steuern – keine fremde Seite oder Unterseite.
            if hauptframe and self.url().toString() == "about:blank":
                QTimer.singleShot(0, lambda u=QUrl(url): self.fenster.interner_link(u))
            return False
        return super().acceptNavigationRequest(url, art, hauptframe)

    def createWindow(self, _art):
        return self  # Links mit target=_blank im selben Fenster öffnen

    def javaScriptConsoleMessage(self, stufe, text, zeile, quelle):
        if stufe == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            log.debug("JS-Fehler %s:%s %s", quelle, zeile, text)


class KinoAnsicht(QWebEngineView):
    """Rechtsklick: in Textfeldern und auf Markiertem das übliche Menü (Kopieren, Einfügen),
    sonst die App-Funktionen."""

    def contextMenuEvent(self, ereignis):
        anfrage = self.lastContextMenuRequest()
        if anfrage is not None and (anfrage.isContentEditable() or anfrage.selectedText()):
            menue = self.createStandardContextMenu()
            sip.transferto(menue, None)  # sonst gibt Python das Menü sofort wieder frei
        else:
            menue = QMenu(self)
            menue.addActions(self.actions())
        menue.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menue.popup(ereignis.globalPos())


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
        bildschirm = self.screen().availableGeometry() if self.screen() else None
        if bildschirm:
            self.resize(int(bildschirm.width() * 0.85), int(bildschirm.height() * 0.85))
        else:
            self.resize(1280, 800)
        # Grundton wie das Kino: kein heller Rand/Blitz beim Laden oder im Vollbild
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(HINTERGRUND))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

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
        self.profil = QWebEngineProfile("jarvis-kino", QApplication.instance())
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

        scroll = QWebEngineScript()
        scroll.setName("jarvis-scrollleisten")
        scroll.setSourceCode(SCROLLLEISTEN_JS.replace("CSS", json.dumps(SCROLLLEISTEN_CSS), 1))
        scroll.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        scroll.setWorldId(QWebEngineScript.ScriptWorldId.ApplicationWorld)
        scroll.setRunsOnSubFrames(True)
        self.profil.scripts().insert(scroll)

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
        self.seite.setBackgroundColor(QColor(HINTERGRUND))

        self.ansicht = KinoAnsicht(self)
        self.ansicht.setPage(self.seite)
        self.ansicht.setContentsMargins(0, 0, 0, 0)
        self.ansicht.setZoomFactor(float(self.einst.get("zoom") or 1.0))
        self.setCentralWidget(self.ansicht)
        self.wach_cookie = None
        self.suche_seit = 0.0

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
        aktion("Jarvis neu suchen", ["Ctrl+Shift+R"], self.adresse_suchen)
        aktion("Einstellungen …", ["Ctrl+,"], self.einstellungen_zeigen)
        aktion("Beenden", ["Ctrl+Q"], self.close)

    def _netzwechsel_beobachten(self):
        try:
            if QNetworkInformation.loadDefaultBackend() and QNetworkInformation.instance():
                info = QNetworkInformation.instance()
                info.reachabilityChanged.connect(lambda *_: QTimer.singleShot(1500, self._netz_geaendert))
        except Exception:  # noqa: BLE001 – Backend fehlt auf manchen Systemen
            log.info("Keine Netzwerk-Statusmeldungen verfügbar")

    # --------------------------------------------------------- Adressen
    def start(self):
        self._startseite("suche")
        if self.einst.get("app_vollbild"):
            self.showFullScreen()
        else:
            self.showMaximized()
        self._dunkle_titelleiste()
        self.adresse_suchen()

    def event(self, ereignis):
        if ereignis.type() == QEvent.Type.WinIdChange:
            QTimer.singleShot(0, self._dunkle_titelleiste)
        return super().event(ereignis)

    def _dunkle_titelleiste(self):
        """Unter XWayland zeichnet GNOME die Titelleiste – dunkel passend zum Kino."""
        if QGuiApplication.platformName() != "xcb" or not shutil.which("xprop"):
            return
        try:
            subprocess.run(["xprop", "-id", str(int(self.winId())), "-f", "_GTK_THEME_VARIANT", "8u",
                            "-set", "_GTK_THEME_VARIANT", "dark"], check=False, timeout=3,
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            pass

    def adresse_suchen(self):
        self.wiederholen.stop()
        if not self.sucher.laeuft:
            self.suche_seit = time.monotonic()
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
        log.info("Jarvis unter keiner Adresse erreichbar: %s", ", ".join(urlsplit(a).netloc for a in self.einst["adressen"]))
        if self.player.laeuft or self.letzter_start:
            pass  # Film läuft oder wird fortgesetzt: Kino-Seite nicht anfassen
        elif self.seite.url().toString() == "about:blank":
            # Mindestens kurz „Suche …“ zeigen, sonst wirkt der Knopf wie ohne Funktion
            rest = int(max(0.0, 0.8 - (time.monotonic() - self.suche_seit)) * 1000)
            QTimer.singleShot(rest, lambda: self.seite.runJavaScript("window.zustand&&zustand('fehler')"))
        else:
            self._startseite("fehler")
        if self.letzter_start and self.letzter_start.get("neustart_wartet"):
            self.neustarts += 1
            if self.neustarts > 6:
                self.letzter_start = None
        self.wiederholen.start(10_000)

    def _startseite(self, zustand):
        self.seite.setHtml(STARTSEITE.replace("{zustand}", zustand), QUrl("about:blank"))

    def interner_link(self, url):
        if url.host() != "adresse":
            self.adresse_suchen()
            return
        adresse = einstellungen.normalisiere_adresse(
            QUrlQuery(url).queryItemValue("u", QUrl.ComponentFormattingOption.FullyDecoded))
        if not adresse:
            self._startseite_hinweis("Das ist keine gültige Adresse.")
            return
        # Nur die eingegebene Adresse prüfen; gespeichert wird sie erst, wenn dort Jarvis antwortet.
        self.wiederholen.stop()
        self.sucher.abbrechen()
        self.pruefer = AdressSucher(self)
        self.pruefer.gefunden.connect(lambda a: (self._adresse_eintragen(a), self._basis_gefunden(a)))
        self.pruefer.nichts_gefunden.connect(lambda: (
            self._startseite_hinweis("Unter dieser Adresse antwortet kein Jarvis."), self.wiederholen.start(10_000)))
        self.pruefer.suchen([adresse])

    def _startseite_hinweis(self, text):
        if self.seite.url().toString() == "about:blank":
            self.seite.runJavaScript(f"window.zustand&&(zustand('fehler'),hinweis({json.dumps(text)}))")

    def _adresse_eintragen(self, adresse):
        if adresse in self.einst["adressen"]:
            return
        adressen = list(self.einst["adressen"])
        if "trycloudflare.com" in adresse:
            # Schnell-Tunnel bekommen bei jedem Neustart eine neue Adresse – die alte ist dann tot.
            adressen = [a for a in adressen if "trycloudflare.com" not in a]
        adressen.append(adresse)
        self.einst["adressen"] = adressen
        einstellungen.speichern(self.einst)
        log.info("Adresse gespeichert: %s", adresse)

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
        if not (self.player.laeuft or self.letzter_start):
            self._startseite("suche")
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

    def _wach_halten(self, an):
        """GNOME soll während des Films nicht abdunkeln (mpv schafft das unter Wayland nicht überall)."""
        try:
            from PyQt6.QtDBus import QDBusArgument, QDBusConnection, QDBusInterface
            from PyQt6.QtCore import QMetaType
            sm = QDBusInterface("org.gnome.SessionManager", "/org/gnome/SessionManager",
                                "org.gnome.SessionManager", QDBusConnection.sessionBus())
            if not sm.isValid():
                return
            ganzzahl = QMetaType.Type.UInt.value
            if an and self.wach_cookie is None:
                xid = int(self.winId()) if QGuiApplication.platformName() == "xcb" else 0
                antwort = sm.call("Inhibit", "jarvis-kino", QDBusArgument(xid, ganzzahl), "Film läuft",
                                  QDBusArgument(8, ganzzahl))
                werte = antwort.arguments()
                self.wach_cookie = werte[0] if werte else None
            elif not an and self.wach_cookie is not None:
                sm.call("Uninhibit", QDBusArgument(self.wach_cookie, ganzzahl))
                self.wach_cookie = None
        except Exception:  # noqa: BLE001 – ohne GNOME/DBus einfach nichts tun
            self.wach_cookie = None

    def _player_starten(self):
        self._wach_halten(True)
        s = self.letzter_start
        for folge, url in zip(s["daten"]["folgen"], s["urls"]):
            folge["url"] = url
        start_url = s["urls"][s["index"]] if s["urls"] else ""
        self.player.starten(self.einst, s["urls"], s["index"], s["daten"],
                            self._cookie_kopf(urlsplit(start_url).hostname or ""),
                            s["referer"], self.profil.httpUserAgent(),
                            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation))

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
        self._wach_halten(False)
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
        if self.basis and self.seite.url().toString() == "about:blank":
            # Während des Films kam die Startseite – jetzt das Kino zurückholen
            QTimer.singleShot(300, lambda: self._seite_umstellen(None))
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

    def _fehler_zeigen(self, fehler):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Jarvis Kino – Wiedergabe")
        box.setText(fehler.get("text") or "Das Video konnte nicht abgespielt werden.")
        if fehler.get("details"):
            box.setDetailedText(fehler["details"])
        ohne_hw = None
        if fehler.get("art") == "bild" and self.einst.get("hwdec") != "no":
            ohne_hw = box.addButton("Ohne Hardware-Beschleunigung versuchen", QMessageBox.ButtonRole.ActionRole)
        box.setDefaultButton(box.addButton("Schließen", QMessageBox.ButtonRole.RejectRole))
        box.exec()
        if ohne_hw is not None and box.clickedButton() == ohne_hw:
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
        self._wach_halten(False)
        self.fortschritt.sichern()
        super().closeEvent(ereignis)
