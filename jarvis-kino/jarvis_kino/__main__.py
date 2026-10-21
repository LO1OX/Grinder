"""Start: python3 -m jarvis_kino  [--hardware-test | --einstellungen | --version]"""
import argparse
import faulthandler
import logging
import logging.handlers
import os
import shutil
import signal
import subprocess
import sys

from . import __version__
from .einstellungen import DATEN


def _logging():
    DATEN.mkdir(parents=True, exist_ok=True)
    datei = logging.handlers.RotatingFileHandler(DATEN / "jarvis-kino.log", maxBytes=2_000_000, backupCount=2,
                                                 encoding="utf-8")
    datei.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[datei, logging.StreamHandler()])
    faulthandler.enable(open(DATEN / "absturz.log", "a", encoding="utf-8"))

    def unerwartet(typ, wert, tb):
        # PyQt würde sonst die ganze App beenden – lieber protokollieren und weiterlaufen.
        logging.getLogger("jarvis-kino").error("Unerwarteter Fehler", exc_info=(typ, wert, tb))

    sys.excepthook = unerwartet


def _bruchteil_skalierung():
    """True, wenn GNOME Bruchteil-Skalierung (z. B. 125 %) erlaubt – XWayland-Fenster würden dann unscharf."""
    if not shutil.which("gsettings"):
        return False
    try:
        aus = subprocess.run(["gsettings", "get", "org.gnome.mutter", "experimental-features"], capture_output=True,
                             text=True, timeout=2, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "scale-monitor-framebuffer" in aus


def _plattform_waehlen():
    """Fensterrahmen wie im System. Unter GNOME mit Wayland zeichnet GNOME über XWayland den
    gewohnten Rahmen selbst (Vollbild ohne Rand). Bei Bruchteil-Skalierung bleibt die App bei
    Wayland (scharf) und nutzt Qts GNOME-Rahmen („adwaita“).
    JARVIS_KINO_WAYLAND=1 erzwingt Wayland, =0 erzwingt XWayland."""
    wahl = os.environ.get("JARVIS_KINO_WAYLAND")
    if os.environ.get("QT_QPA_PLATFORM") or not os.environ.get("WAYLAND_DISPLAY"):
        return
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP", "") + ":" + os.environ.get("XDG_SESSION_DESKTOP", "")).lower()
    gnome_artig = any(d in desktop for d in ("gnome", "ubuntu", "unity", "pantheon", "budgie", "cinnamon"))
    if wahl == "1" or (wahl != "0" and gnome_artig and _bruchteil_skalierung()) or not os.environ.get("DISPLAY"):
        if gnome_artig:
            os.environ.setdefault("QT_WAYLAND_DECORATION", "adwaita")
        return
    if wahl == "0" or gnome_artig:
        os.environ["QT_QPA_PLATFORM"] = "xcb"


def _ohne_knopfsymbole(app):
    """Dialogknöpfe ohne Symbole (keine Diskette, kein rotes X) – wie in GNOME-Dialogen."""
    from PyQt6.QtWidgets import QProxyStyle, QStyle

    class OhneSymbole(QProxyStyle):
        def styleHint(self, hinweis, option=None, widget=None, rueckgabe=None):
            if hinweis == QStyle.StyleHint.SH_DialogButtonBox_ButtonsHaveIcons:
                return 0
            return super().styleHint(hinweis, option, widget, rueckgabe)

    app.setStyle(OhneSymbole(app.style().name()))


def _deutsch(app):
    """Qt-eigene Texte (Kontextmenüs, Dialogknöpfe) auf Deutsch."""
    from PyQt6.QtCore import QLibraryInfo, QLocale, QTranslator

    pfad = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    for name in ("qtbase", "qtwebengine"):
        uebersetzer = QTranslator(app)
        if uebersetzer.load(QLocale("de_DE"), name, "_", pfad):
            app.installTranslator(uebersetzer)


def main():
    parser = argparse.ArgumentParser(prog="jarvis-kino", description="Jarvis Kino für Ubuntu")
    parser.add_argument("--hardware-test", action="store_true", help="Hardware-Dekodierung prüfen")
    parser.add_argument("--einstellungen", action="store_true", help="Einstellungen öffnen")
    parser.add_argument("--version", action="version", version=__version__)
    args, qt_args = parser.parse_known_args()

    if args.hardware_test:
        from .hardware import bericht
        print(bericht())
        return 0

    _logging()
    _plattform_waehlen()
    # Chromium soll Videos nie selbst dekodieren müssen – das macht mpv.
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--autoplay-policy=no-user-gesture-required")

    from PyQt6.QtCore import QTimer
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket
    from PyQt6.QtWidgets import QApplication

    from . import einstellungen
    from .dialog import EinstellungenDialog
    from .hauptfenster import Hauptfenster

    app = QApplication(["jarvis-kino"] + qt_args)  # Programmname = Fensterklasse für GNOME
    app.setApplicationName("Jarvis Kino")
    app.setOrganizationName("Jarvis")
    app.setDesktopFileName("jarvis-kino")
    _deutsch(app)
    _ohne_knopfsymbole(app)

    # Nur ein Fenster: ein zweiter Start holt das vorhandene nach vorn.
    name = f"jarvis-kino-{os.getuid()}"
    probe = QLocalSocket()
    probe.connectToServer(name)
    if probe.waitForConnected(300):
        probe.write(b"einstellungen" if args.einstellungen else b"zeigen")
        probe.flush()
        probe.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(name)
    server = QLocalServer()
    server.listen(name)

    einst = einstellungen.laden()
    if args.einstellungen:
        dialog = EinstellungenDialog(einst)
        if dialog.exec():
            einst = dialog.werte()
            einstellungen.speichern(einst)

    fenster = Hauptfenster(einst)

    def nach_vorn():
        verbindung = server.nextPendingConnection()
        wunsch = b""
        if verbindung:
            if verbindung.waitForReadyRead(300):
                wunsch = bytes(verbindung.readAll())
            verbindung.close()
        if fenster.isMinimized():
            fenster.showNormal()
        fenster.activateWindow()
        fenster.raise_()
        if wunsch == b"einstellungen":
            QTimer.singleShot(0, fenster.einstellungen_zeigen)

    server.newConnection.connect(nach_vorn)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    puls = QTimer(interval=500, timeout=lambda: None)  # lässt Python Signale verarbeiten
    puls.start()
    fenster.start()
    code = app.exec()
    server.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
