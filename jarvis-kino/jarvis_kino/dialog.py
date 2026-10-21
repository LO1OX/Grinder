"""Einstellungen: Adressen, Hardware-Beschleunigung, Sprache."""
import threading

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit,
                             QPushButton, QVBoxLayout)

from . import hardware
from .einstellungen import normalisiere_adresse
from .netz import AdressSucher

HWDEC = [
    ("auto-safe", "Automatisch (empfohlen)"),
    ("auto-copy-safe", "Automatisch, kompatibel (bei Bildfehlern)"),
    ("vaapi", "Intel / AMD (VAAPI)"),
    ("nvdec", "NVIDIA (NVDEC)"),
    ("no", "Aus – nur Prozessor"),
]
TON = [("de", "Deutsch bevorzugen"), ("en", "Englisch bevorzugen"), ("original", "Originalton")]
UNTERTITEL = [("aus", "Aus"), ("de", "Deutsch"), ("en", "Englisch")]


class _Melder(QObject):
    fertig = pyqtSignal(str)


class EinstellungenDialog(QDialog):
    def __init__(self, einst, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Jarvis Kino – Einstellungen")
        self.setMinimumWidth(620)
        self.einst = dict(einst)
        layout = QVBoxLayout(self)

        # --- Adressen
        gruppe = QGroupBox("Jarvis-Adressen (von oben nach unten bevorzugt)")
        g = QVBoxLayout(gruppe)
        hinweis = QLabel("Die App prüft alle Adressen gleichzeitig und nimmt die erste, die antwortet – "
                         "zu Hause die Heimnetz-Adresse, unterwegs z. B. Cloudflare oder MyFRITZ. "
                         "IPv4 und IPv6 funktionieren beide.")
        hinweis.setWordWrap(True)
        g.addWidget(hinweis)
        self.liste = QListWidget()
        for a in self.einst["adressen"]:
            self._eintrag(a)
        g.addWidget(self.liste)
        zeile = QHBoxLayout()
        self.neu = QLineEdit(placeholderText="z. B. https://xyz.trycloudflare.com/kino/ oder http://jarvis.local")
        self.neu.returnPressed.connect(self._hinzu)
        zeile.addWidget(self.neu)
        for text, fn in (("Hinzufügen", self._hinzu), ("▲", lambda: self._schieben(-1)),
                         ("▼", lambda: self._schieben(1)), ("Entfernen", self._entfernen),
                         ("Alle prüfen", self._pruefen)):
            knopf = QPushButton(text)
            knopf.clicked.connect(fn)
            zeile.addWidget(knopf)
        g.addLayout(zeile)
        layout.addWidget(gruppe)

        # --- Wiedergabe
        wg = QGroupBox("Wiedergabe")
        form = QFormLayout(wg)
        self.hwdec = self._auswahl(HWDEC, self.einst.get("hwdec"))
        hw_zeile = QHBoxLayout()
        hw_zeile.addWidget(self.hwdec, 1)
        self.hw_knopf = QPushButton("Hardware testen")
        self.hw_knopf.clicked.connect(self._hw_testen)
        hw_zeile.addWidget(self.hw_knopf)
        form.addRow("Hardware-Beschleunigung:", hw_zeile)
        self.ton = self._auswahl(TON, self.einst.get("tonsprache"))
        form.addRow("Tonspur:", self.ton)
        self.untertitel = self._auswahl(UNTERTITEL, self.einst.get("untertitel"))
        form.addRow("Untertitel:", self.untertitel)
        self.vollbild = QCheckBox("App im Vollbild starten (wie ein Fernseher)")
        self.vollbild.setChecked(bool(self.einst.get("app_vollbild")))
        form.addRow("", self.vollbild)
        layout.addWidget(wg)

        self.ausgabe = QPlainTextEdit(readOnly=True)
        self.ausgabe.setMaximumHeight(150)
        self.ausgabe.hide()
        layout.addWidget(self.ausgabe)

        knoepfe = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        knoepfe.button(QDialogButtonBox.StandardButton.Save).setText("Speichern")
        knoepfe.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        knoepfe.accepted.connect(self.accept)
        knoepfe.rejected.connect(self.reject)
        layout.addWidget(knoepfe)

        self._melder = _Melder()
        self._melder.fertig.connect(self._hw_fertig)
        self._pruefer = []

    @staticmethod
    def _auswahl(optionen, wert):
        box = QComboBox()
        for schluessel, text in optionen:
            box.addItem(text, schluessel)
        i = box.findData(wert)
        box.setCurrentIndex(max(i, 0))
        return box

    def _eintrag(self, adresse):
        item = QListWidgetItem(adresse)
        item.setData(Qt.ItemDataRole.UserRole, adresse)
        self.liste.addItem(item)

    def _adressen(self):
        return [self.liste.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.liste.count())]

    def _hinzu(self):
        adresse = normalisiere_adresse(self.neu.text())
        if adresse and adresse not in self._adressen():
            self._eintrag(adresse)
        self.neu.clear()

    def _entfernen(self):
        for item in self.liste.selectedItems():
            self.liste.takeItem(self.liste.row(item))

    def _schieben(self, richtung):
        zeile = self.liste.currentRow()
        ziel = zeile + richtung
        if zeile < 0 or not 0 <= ziel < self.liste.count():
            return
        item = self.liste.takeItem(zeile)
        self.liste.insertItem(ziel, item)
        self.liste.setCurrentRow(ziel)

    def _pruefen(self):
        self._pruefer = []
        for i in range(self.liste.count()):
            item = self.liste.item(i)
            adresse = item.data(Qt.ItemDataRole.UserRole)
            item.setText(f"…  {adresse}")
            sucher = AdressSucher(self)
            sucher.gefunden.connect(lambda _a, it=item, ad=adresse: it.setText(f"✓  {ad}   (erreichbar)"))
            sucher.nichts_gefunden.connect(lambda it=item, ad=adresse: it.setText(f"✗  {ad}   (nicht erreichbar)"))
            sucher.suchen([adresse])
            self._pruefer.append(sucher)

    def _hw_testen(self):
        self.hw_knopf.setEnabled(False)
        self.hw_knopf.setText("Teste …")
        self.ausgabe.show()
        self.ausgabe.setPlainText("Teste Hardware-Dekodierung (dauert bis zu einer Minute) …")
        wahl = self.hwdec.currentData()
        hwdec = {"auto-safe": "auto-copy-safe", "vaapi": "vaapi-copy", "nvdec": "nvdec-copy"}.get(wahl, wahl)
        threading.Thread(target=lambda: self._melder.fertig.emit(hardware.bericht(hwdec)), daemon=True).start()

    def _hw_fertig(self, text):
        self.ausgabe.setPlainText(text)
        self.hw_knopf.setEnabled(True)
        self.hw_knopf.setText("Hardware testen")

    def werte(self):
        self.einst.update({
            "adressen": self._adressen() or self.einst["adressen"],
            "hwdec": self.hwdec.currentData(),
            "tonsprache": self.ton.currentData(),
            "untertitel": self.untertitel.currentData(),
            "app_vollbild": self.vollbild.isChecked(),
        })
        return self.einst
