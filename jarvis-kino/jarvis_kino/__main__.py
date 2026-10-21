"""Start: python3 -m jarvis_kino  [--hardware-test | --einstellungen | --version]"""
import argparse
import faulthandler
import logging
import logging.handlers
import os
import signal
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


def _jarvis_design(app):
    """Dunkle Graustufen wie im Jarvis-Kino (auch für Einstellungen und Meldungen)."""
    from PyQt6.QtGui import QColor, QPalette

    app.setStyle("Fusion")
    farben = {
        QPalette.ColorRole.Window: "#1c1c1e", QPalette.ColorRole.WindowText: "#f5f5f7",
        QPalette.ColorRole.Base: "#0a0a0b", QPalette.ColorRole.AlternateBase: "#2c2c2e",
        QPalette.ColorRole.Text: "#f5f5f7", QPalette.ColorRole.Button: "#2c2c2e",
        QPalette.ColorRole.ButtonText: "#f5f5f7", QPalette.ColorRole.Highlight: "#e5e5ea",
        QPalette.ColorRole.HighlightedText: "#0a0a0b", QPalette.ColorRole.ToolTipBase: "#2c2c2e",
        QPalette.ColorRole.ToolTipText: "#f5f5f7", QPalette.ColorRole.PlaceholderText: "#8e8e93",
        QPalette.ColorRole.Link: "#e5e5ea",
    }
    palette = QPalette()
    for rolle, farbe in farben.items():
        palette.setColor(rolle, QColor(farbe))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#636366"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#636366"))
    app.setPalette(palette)
    app.setStyleSheet(
        "QPushButton{padding:6px 14px;border-radius:8px;background:#2c2c2e;border:1px solid #3a3a3c}"
        "QPushButton:hover{background:#3a3a3c}"
        "QLineEdit,QComboBox,QListWidget,QPlainTextEdit{border-radius:8px;border:1px solid #3a3a3c;padding:4px}"
        "QGroupBox{border:1px solid #2c2c2e;border-radius:12px;margin-top:14px;padding:10px}"
        "QGroupBox::title{subcontrol-origin:margin;left:12px;color:#8e8e93}")


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
    # Chromium soll Videos nie selbst dekodieren müssen – das macht mpv.
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--autoplay-policy=no-user-gesture-required")

    from PyQt6.QtCore import QTimer
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket
    from PyQt6.QtWidgets import QApplication

    from . import einstellungen
    from .dialog import EinstellungenDialog
    from .hauptfenster import Hauptfenster

    app = QApplication([sys.argv[0]] + qt_args)
    app.setApplicationName("Jarvis Kino")
    app.setOrganizationName("Jarvis")
    app.setDesktopFileName("jarvis-kino")
    _jarvis_design(app)

    # Nur ein Fenster: ein zweiter Start holt das vorhandene nach vorn.
    name = f"jarvis-kino-{os.getuid()}"
    probe = QLocalSocket()
    probe.connectToServer(name)
    if probe.waitForConnected(300):
        probe.write(b"zeigen")
        probe.flush()
        probe.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(name)
    server = QLocalServer()
    server.listen(name)

    einst = einstellungen.laden()
    if einstellungen.erster_start() or args.einstellungen:
        dialog = EinstellungenDialog(einst)
        if dialog.exec():
            einst = dialog.werte()
        einstellungen.speichern(einst)

    fenster = Hauptfenster(einst)

    def nach_vorn():
        verbindung = server.nextPendingConnection()
        if verbindung:
            verbindung.close()
        if fenster.isMinimized():
            fenster.showNormal()
        fenster.activateWindow()
        fenster.raise_()

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
