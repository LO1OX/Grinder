"""Liest Folgen und Staffeln aus den JSON-Antworten des Jarvis-Kinos.

Das Kino liefert Serien als JSON (z. B. /api/kino/serie/<id>). Der genaue
Aufbau ist hier nicht fest verdrahtet: Gesucht wird die Liste, in der die
gerade gestartete Video-Kennung vorkommt. Liegt diese Liste in einer Staffel,
werden alle Staffeln der Reihe nach zusammengefügt.
"""
import re

ID_SCHLUESSEL = ("id", "video", "video_id", "videoId", "datei", "kennung", "vid", "datei_id")
TITEL_SCHLUESSEL = ("titel", "title", "name", "folgentitel", "episodentitel")
STAFFEL_SCHLUESSEL = ("staffel", "season", "staffel_nr", "season_number", "s")
FOLGE_SCHLUESSEL = ("folge", "episode", "folge_nr", "episode_number", "nummer", "nr", "e")
POSITION_SCHLUESSEL = ("position", "fortschritt", "pos", "sekunden", "stand", "zeit")
DAUER_SCHLUESSEL = ("dauer", "laenge", "länge", "duration", "gesamt")
GESEHEN_SCHLUESSEL = ("gesehen", "fertig", "watched", "beendet")

VIDEO_PFAD = re.compile(r"/api/video/(?:datei|stream|status|abspielbar|vorbereiten|bild)/([^/?#]+)")


def video_id_aus_url(url):
    """Kennung aus einer Kino-Video-URL, sonst None."""
    m = VIDEO_PFAD.search(url or "")
    return m.group(1) if m else None


def _erstes(d, schluessel):
    for k in schluessel:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _zahl(wert):
    if isinstance(wert, bool):
        return None
    if isinstance(wert, (int, float)):
        return wert
    if isinstance(wert, str):
        m = re.search(r"\d+(?:\.\d+)?", wert)
        if m:
            return float(m.group(0)) if "." in m.group(0) else int(m.group(0))
    return None


def _id_schluessel(d, gesucht):
    for k in ID_SCHLUESSEL:
        if str(d.get(k, "")) == gesucht:
            return k
    for k, v in d.items():
        if isinstance(v, (str, int)) and not isinstance(v, bool) and str(v) == gesucht:
            return k
    return None


def _pfad_zu(daten, gesucht):
    """Pfad (Liste von (Behälter, Schlüssel)) zum Objekt mit der Kennung."""
    stapel = [(daten, [])]
    while stapel:
        knoten, pfad = stapel.pop()
        if isinstance(knoten, dict):
            if _id_schluessel(knoten, gesucht) and pfad and isinstance(pfad[-1][0], list):
                return pfad
            for k, v in knoten.items():
                if isinstance(v, (dict, list)):
                    stapel.append((v, pfad + [(knoten, k)]))
        elif isinstance(knoten, list):
            for i, v in enumerate(knoten):
                if isinstance(v, (dict, list)):
                    stapel.append((v, pfad + [(knoten, i)]))
    return None


def _folge(d, id_key, staffel_vorgabe, index):
    titel = _erstes(d, TITEL_SCHLUESSEL)
    staffel = _zahl(_erstes(d, STAFFEL_SCHLUESSEL))
    folge = _zahl(_erstes(d, FOLGE_SCHLUESSEL))
    gesehen = _erstes(d, GESEHEN_SCHLUESSEL)
    pos = _zahl(_erstes(d, POSITION_SCHLUESSEL))
    dauer = _zahl(_erstes(d, DAUER_SCHLUESSEL))
    # Fortschritt kann auch verschachtelt kommen: {"fortschritt": {"position": 12, "dauer": 40}}
    for k in POSITION_SCHLUESSEL:
        if isinstance(d.get(k), dict):
            pos = _zahl(_erstes(d[k], POSITION_SCHLUESSEL)) or pos
            dauer = _zahl(_erstes(d[k], DAUER_SCHLUESSEL)) or dauer
            gesehen = _erstes(d[k], GESEHEN_SCHLUESSEL) if gesehen is None else gesehen
    return {
        "id": str(d[id_key]),
        "titel": str(titel) if titel is not None else "",
        "staffel": staffel if staffel is not None else staffel_vorgabe,
        "folge": folge if folge is not None else index + 1,
        "position": float(pos) if pos else 0.0,
        "dauer": float(dauer) if dauer else 0.0,
        "gesehen": bool(gesehen) if gesehen is not None else False,
    }


def _ist_folgenliste(liste, id_key):
    return isinstance(liste, list) and any(isinstance(x, dict) and id_key in x for x in liste)


def folgen_finden(daten, aktuelle_id):
    """Gibt (serientitel, [folgen...]) zurück; leere Liste, wenn nichts passt."""
    if not aktuelle_id:
        return None, []
    pfad = _pfad_zu(daten, str(aktuelle_id))
    if not pfad:
        return None, []
    liste, index = pfad[-1]
    eintrag = liste[index]
    id_key = _id_schluessel(eintrag, str(aktuelle_id))

    serientitel = None
    staffeln = None  # [(staffelnummer, liste)]
    if len(pfad) >= 2:
        behaelter, schluessel = pfad[-2]
        if isinstance(behaelter, dict) and len(pfad) >= 3 and isinstance(pfad[-3][0], list):
            # [{staffel: 1, folgen: [...]}, {staffel: 2, folgen: [...]}]
            alle = pfad[-3][0]
            staffeln = []
            for i, s in enumerate(alle):
                if isinstance(s, dict) and _ist_folgenliste(s.get(schluessel), id_key):
                    nr = _zahl(_erstes(s, STAFFEL_SCHLUESSEL + ("nummer", "nr")))
                    staffeln.append((nr if nr is not None else i + 1, s[schluessel]))
            if len(pfad) >= 4 and isinstance(pfad[-4][0], dict):
                serientitel = _erstes(pfad[-4][0], TITEL_SCHLUESSEL)
        elif isinstance(behaelter, dict):
            listen = [(k, v) for k, v in behaelter.items() if _ist_folgenliste(v, id_key)]
            if len(listen) > 1 and all(_zahl(k) is not None for k, _ in listen):
                # {"1": [...], "2": [...]} oder {"staffel 1": [...], ...}
                staffeln = sorted(((_zahl(k), v) for k, v in listen), key=lambda x: x[0])
            else:
                serientitel = _erstes(behaelter, TITEL_SCHLUESSEL)
            if staffeln and len(pfad) >= 3 and isinstance(pfad[-3][0], dict):
                serientitel = _erstes(pfad[-3][0], TITEL_SCHLUESSEL)

    if not staffeln:
        staffeln = [(None, liste)]

    folgen, gesehen_ids = [], set()
    for nr, eintraege in staffeln:
        for i, d in enumerate(eintraege):
            if isinstance(d, dict) and id_key in d and str(d[id_key]) not in gesehen_ids:
                gesehen_ids.add(str(d[id_key]))
                folgen.append(_folge(d, id_key, nr, i))
    return (str(serientitel) if serientitel else None), folgen


def folgen_aus_antworten(antworten, aktuelle_id):
    """Durchsucht gespeicherte Kino-Antworten (neueste zuerst)."""
    bester = (None, [])
    for daten in antworten:
        titel, folgen = folgen_finden(daten, aktuelle_id)
        if len(folgen) > len(bester[1]):
            bester = (titel, folgen)
            if len(folgen) > 1:
                break
    return bester


def anzeige_titel(serie, folge):
    """'Serie · S1:F3 – Titel' bzw. nur der Filmtitel."""
    teile = []
    if folge.get("staffel") is not None:
        teile.append(f"S{folge['staffel']}:F{folge['folge']}")
    if folge.get("titel"):
        teile.append(folge["titel"])
    text = " – ".join(teile)
    if serie and serie != folge.get("titel"):
        return f"{serie} · {text}" if text else serie
    return text or serie or ""
