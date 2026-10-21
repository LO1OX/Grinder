"""Findet eine erreichbare Jarvis-Adresse.

Alle Adressen (Heimnetz-IP, jarvis.local, Fritzbox/MyFRITZ, Cloudflare,
IPv4 wie IPv6) werden gleichzeitig angefragt. Gewählt wird die erste in
der Vorrang-Reihenfolge, die nachweislich Jarvis ist – ein fremder Router
mit derselben 192.168.178.x-Adresse zählt nicht.
"""
from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest

MERKMALE = (b"kino.js", b"kino.css", b"jarvis", b"Jarvis", b"/kino/")


def ist_jarvis(status, ort, inhalt):
    """Entscheidet anhand der Antwort, ob wirklich Jarvis geantwortet hat."""
    if status is None or status >= 500:
        return False  # z. B. Cloudflare 530, wenn der Tunnel aus ist
    if status in (301, 302, 303, 307, 308):
        return "anmeld" in (ort or "") or "/kino" in (ort or "") or "/tor" in (ort or "")
    if status in (200, 401, 403):
        return any(m in inhalt for m in MERKMALE)
    return False


class AdressSucher(QObject):
    gefunden = pyqtSignal(str)
    nichts_gefunden = pyqtSignal()
    NACHFRIST_MS = 1500

    def __init__(self, parent=None):
        super().__init__(parent)
        self.nam = QNetworkAccessManager(self)
        self._laeuft = False
        self._antworten = []
        self._ergebnis = {}
        self._adressen = []
        self._uhr = QTimer(self, singleShot=True, timeout=self._zeit_um)

    @property
    def laeuft(self):
        return self._laeuft

    def suchen(self, adressen, zeitlimit_ms=6000):
        if self._laeuft:
            return
        self._laeuft = True
        self._adressen = list(adressen)
        self._ergebnis = {a: None for a in self._adressen}  # None=offen, True/False
        self._antworten = []
        for adresse in self._adressen:
            anfrage = QNetworkRequest(QUrl(adresse))
            anfrage.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                                 QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
            anfrage.setTransferTimeout(zeitlimit_ms)
            anfrage.setRawHeader(b"User-Agent", b"JarvisKino-Desktop")
            antwort = self.nam.get(anfrage)
            antwort.finished.connect(lambda a=adresse, r=antwort: self._fertig(a, r))
            self._antworten.append(antwort)
        self._uhr.start(zeitlimit_ms + 500)

    def _fertig(self, adresse, antwort):
        if not self._laeuft:
            antwort.deleteLater()
            return
        status = antwort.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        ort = bytes(antwort.rawHeader(b"Location")).decode("latin-1")
        inhalt = bytes(antwort.readAll())[:256 * 1024]
        self._ergebnis[adresse] = ist_jarvis(status, ort, inhalt)
        antwort.deleteLater()
        if self._ergebnis[adresse] and self._uhr.remainingTime() > self.NACHFRIST_MS:
            # Eine Adresse antwortet: auf bevorzugte (z. B. Heimnetz) nur noch kurz warten,
            # damit eine hängende Adresse unterwegs den Start nicht ausbremst.
            self._uhr.start(self.NACHFRIST_MS)
        self._auswerten(endgueltig=False)

    def _auswerten(self, endgueltig):
        for adresse in self._adressen:
            stand = self._ergebnis.get(adresse)
            if stand is True:
                return self._ende(adresse)
            if stand is None and not endgueltig:
                return  # auf Adresse mit höherem Vorrang warten
        if endgueltig or all(v is False for v in self._ergebnis.values()):
            self._ende(None)

    def _zeit_um(self):
        if self._laeuft:
            self._auswerten(endgueltig=True)

    def abbrechen(self):
        """Laufende Suche ohne Ergebnis-Signal beenden."""
        if self._laeuft:
            self._aufraeumen()

    def _aufraeumen(self):
        self._laeuft = False
        self._uhr.stop()
        for antwort in self._antworten:
            try:
                if antwort.isRunning():
                    antwort.abort()
            except RuntimeError:
                pass
        self._antworten = []

    def _ende(self, adresse):
        self._aufraeumen()
        if adresse:
            self.gefunden.emit(adresse)
        else:
            self.nichts_gefunden.emit()


def basis_tauschen(url, alte_basis, neue_basis):
    """Ersetzt die Server-Basis einer Kino-URL (z. B. Heimnetz -> Cloudflare)."""
    if alte_basis and url.startswith(alte_basis):
        return neue_basis + url[len(alte_basis):]
    marker = "/kino/"
    if marker in url and neue_basis.endswith(marker):
        return neue_basis + url.split(marker, 1)[1]
    return url
