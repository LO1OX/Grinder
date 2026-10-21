"""Einstellungen: Adressen, Hardware-Beschleunigung, Sprache."""
import threading

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                             QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit,
                             QPushButton, QVBoxLayout)

from . import hardware
from .einstellungen import normalisiere_adresse

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
        self.setMinimumWidth(560)
        self.einst = dict(einst)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        # Adressen: die App sucht selbst die passende – hier nur ergänzen oder löschen
        self.liste = QListWidget()
        self.liste.setMaximumHeight(110)
        for a in self.einst["adressen"]:
            self._eintrag(a)
        zeile = QHBoxLayout()
        self.neu = QLineEdit(placeholderText="Neue Adresse, z. B. Cloudflare")
        self.neu.returnPressed.connect(self._hinzu)
        zeile.addWidget(self.neu, 1)
        for text, fn in (("Hinzufügen", self._hinzu), ("Entfernen", self._entfernen)):
            knopf = QPushButton(text)
            knopf.clicked.connect(fn)
            zeile.addWidget(knopf)
        adressen = QVBoxLayout()
        adressen.addWidget(self.liste)
        adressen.addLayout(zeile)
        form.addRow("Jarvis-Adressen:", adressen)

        self.hwdec = self._auswahl(HWDEC, self.einst.get("hwdec"))
        hw_zeile = QHBoxLayout()
        hw_zeile.addWidget(self.hwdec, 1)
        self.hw_knopf = QPushButton("Testen")
        self.hw_knopf.clicked.connect(self._hw_testen)
        hw_zeile.addWidget(self.hw_knopf)
        form.addRow("Hardware-Beschleunigung:", hw_zeile)
        self.ton = self._auswahl(TON, self.einst.get("tonsprache"))
        form.addRow("Tonspur:", self.ton)
        self.untertitel = self._auswahl(UNTERTITEL, self.einst.get("untertitel"))
        form.addRow("Untertitel:", self.untertitel)
        self.vollbild = QCheckBox("App im Vollbild starten")
        self.vollbild.setChecked(bool(self.einst.get("app_vollbild")))
        form.addRow("", self.vollbild)
        layout.addLayout(form)

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
