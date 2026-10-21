"""Einstellungen und lokale Daten (Fortschritt, Logs)."""
import ipaddress
import json
import os
import re
import time
from urllib.parse import urlsplit
from pathlib import Path

DATEN = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "jarvis-kino"
KONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "jarvis-kino" / "einstellungen.json"
APP_ORDNER = Path(__file__).resolve().parent.parent
MPV_ORDNER = Path(os.environ.get("JARVIS_KINO_MPV_ORDNER") or APP_ORDNER / "mpv")

# Reihenfolge = Vorrang. Alle werden gleichzeitig geprüft, die erste
# erreichbare mit dem höchsten Vorrang gewinnt.
STANDARD_ADRESSEN = [
    "http://192.168.178.69/kino/",
    "http://jarvis.local/kino/",
    "https://receives-lower-bids-oecd.trycloudflare.com/kino/",
]

STANDARD = {
    "adressen": STANDARD_ADRESSEN,
    "hwdec": "auto-safe",
    "tonsprache": "de",
    "untertitel": "aus",
    "app_vollbild": False,
    "zoom": 1.0,
    "letzte_adresse": "",
}


def fast_fertig(pos, dauer):
    """Im Abspann (letzte 5 %, höchstens 60 s) gilt ein Titel als gesehen."""
    return bool(dauer) and pos >= dauer - min(60.0, dauer * 0.05)


def _atomar_schreiben(pfad, daten):
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_suffix(".tmp")
    tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, pfad)


def _lokaler_host(host):
    host = host.strip("[]").lower()
    lokale_endungen = (".local", ".fritz.box", ".lan", ".home", ".home.arpa", ".internal", ".localdomain")
    if host == "localhost" or host.endswith(lokale_endungen) or "." not in host:
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def normalisiere_adresse(text):
    """Macht aus einer eingetippten oder eingefügten Adresse die Kino-Basis „…/kino/“.
    Ohne Angabe: http für Heimnetz (IP, .local, Rechnername), sonst https."""
    text = (text or "").strip()
    if not text:
        return ""
    if "://" not in text and text.count(":") > 1 and not text.startswith("["):
        text = f"[{text}]"  # nackte IPv6-Adresse
    if "://" not in text:
        host = re.match(r"\[[^\]]*\]|[^/:?#]*", text).group(0)
        text = ("http://" if _lokaler_host(host) else "https://") + text
    teile = urlsplit(text)
    if not teile.netloc or teile.scheme.lower() not in ("http", "https"):
        return ""
    treffer = re.search(r"/kino(?=/|$)", teile.path)
    pfad = teile.path[:treffer.end()] if treffer else "/kino"  # fremde Pfade (z. B. /anmelden) verwerfen
    return f"{teile.scheme.lower()}://{teile.netloc.lower()}{pfad}/"


def laden():
    daten = dict(STANDARD)
    try:
        daten.update(json.loads(KONFIG.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    adressen = [normalisiere_adresse(a) for a in daten.get("adressen") or []]
    daten["adressen"] = [a for i, a in enumerate(adressen) if a and a not in adressen[:i]] or list(STANDARD_ADRESSEN)
    return daten


def speichern(daten):
    _atomar_schreiben(KONFIG, daten)


class Fortschritt:
    """Lokale Sicherung der Wiedergabestelle, falls der Server nicht erreichbar war."""

    def __init__(self, pfad=None):
        self.pfad = Path(pfad) if pfad else DATEN / "fortschritt.json"
        try:
            self.daten = json.loads(self.pfad.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.daten = {}

    def holen(self, vid):
        eintrag = self.daten.get(vid) or {}
        pos, dauer = eintrag.get("pos", 0), eintrag.get("dauer", 0)
        if fast_fertig(pos, dauer):
            return 0.0
        return float(pos)

    def setzen(self, vid, pos, dauer):
        if not vid:
            return
        self.daten[vid] = {"pos": round(pos, 1), "dauer": round(dauer or 0, 1), "zeit": int(time.time())}
        if len(self.daten) > 2000:
            for alt in sorted(self.daten, key=lambda k: self.daten[k].get("zeit", 0))[:500]:
                del self.daten[alt]

    def sichern(self):
        try:
            _atomar_schreiben(self.pfad, self.daten)
        except OSError:
            pass
