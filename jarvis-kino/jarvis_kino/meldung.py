"""Fortschritt an Jarvis melden – im selben Format, das die Kino-Seite benutzt.

Die Seite schickt ihren Fortschritt an /api/video/fortschritt. Die Brücke
merkt sich ein Beispiel davon (Vorlage) samt der Felder für Kennung, Position
und Dauer. Damit meldet die App auch Folgen, die direkt im Player gewechselt
wurden, und funktioniert nach einem Adresswechsel (WLAN -> Cloudflare) weiter.
"""
import json
from urllib.parse import quote, urlencode

from .netz import basis_tauschen

VERBOTENE_KOPFZEILEN = {"content-length", "cookie", "host", "connection", "origin", "referer"}


def _typ_gleich(vorbild, wert):
    if isinstance(vorbild, bool):
        return wert
    if isinstance(vorbild, int):
        return int(wert)
    if isinstance(vorbild, float):
        return round(wert, 2)
    if isinstance(vorbild, str):
        return str(int(wert)) if vorbild.strip().isdigit() else str(round(wert, 2))
    return wert


def anfrage_bauen(vorlage, vid, pos, dauer, basis=None):
    """Gibt (url, methode, kopfzeilen, body-bytes) zurück."""
    felder = vorlage["felder"]
    muster = vorlage["obj"]
    obj = dict(muster)
    faktor = felder.get("faktor", 1) or 1
    if felder.get("id"):
        alt = muster.get(felder["id"])
        obj[felder["id"]] = int(vid) if isinstance(alt, int) and not isinstance(alt, bool) and str(vid).isdigit() else str(vid)
    obj[felder["pos"]] = _typ_gleich(muster.get(felder["pos"]), max(0.0, pos) * faktor)
    if felder.get("dauer") and dauer and dauer > 0:
        obj[felder["dauer"]] = _typ_gleich(muster.get(felder["dauer"]), dauer * faktor)

    url = vorlage["url"]
    if vorlage.get("id_in_url") and vorlage.get("alte_id"):
        url = url.replace(quote(str(vorlage["alte_id"]), safe=""), quote(str(vid), safe=""))
    if basis:
        url = basis_tauschen(url, None, basis)

    if vorlage.get("art") == "json":
        body = json.dumps(obj, ensure_ascii=False)
        standard_typ = "application/json"
    else:
        body = urlencode({k: ("" if v is None else v) for k, v in obj.items()})
        standard_typ = "application/x-www-form-urlencoded"
    kopf = {k: str(v) for k, v in (vorlage.get("kopf") or {}).items() if k.lower() not in VERBOTENE_KOPFZEILEN}
    if not any(k.lower() == "content-type" for k in kopf):
        kopf["Content-Type"] = standard_typ
    return url, (vorlage.get("methode") or "POST").upper(), kopf, body.encode("utf-8")


def gueltige_vorlage(vorlage):
    try:
        return bool(vorlage["url"] and vorlage["felder"]["pos"] and isinstance(vorlage["obj"], dict)
                    and (vorlage["felder"].get("id") or vorlage.get("id_in_url")))
    except (KeyError, TypeError):
        return False
