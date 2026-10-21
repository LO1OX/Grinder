"""Tests ohne Bildschirm: python3 -m unittest discover -s tests"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis_kino.einstellungen import Fortschritt, normalisiere_adresse  # noqa: E402
from jarvis_kino.folgen import anzeige_titel, folgen_aus_antworten, folgen_finden, video_id_aus_url  # noqa: E402
from jarvis_kino.meldung import anfrage_bauen, gueltige_vorlage  # noqa: E402
from jarvis_kino.netz import basis_tauschen, ist_jarvis  # noqa: E402
from jarvis_kino.player import fehler_einordnen, mpv_argumente  # noqa: E402


class FolgenTest(unittest.TestCase):
    def test_staffeln_als_liste(self):
        daten = {"titel": "Dark", "staffeln": [
            {"staffel": 1, "folgen": [{"id": "a1", "titel": "Geheimnisse", "folge": 1},
                                      {"id": "a2", "titel": "Lügen", "folge": 2, "position": 600, "dauer": 3000}]},
            {"staffel": 2, "folgen": [{"id": "b1", "titel": "Anfänge", "folge": 1, "gesehen": True}]},
        ]}
        serie, folgen = folgen_finden(daten, "a2")
        self.assertEqual(serie, "Dark")
        self.assertEqual([f["id"] for f in folgen], ["a1", "a2", "b1"])
        self.assertEqual([f["staffel"] for f in folgen], [1, 1, 2])
        self.assertEqual(folgen[1]["position"], 600.0)
        self.assertTrue(folgen[2]["gesehen"])

    def test_staffeln_als_dict(self):
        daten = {"name": "Serie", "staffeln": {"2": [{"video": "x3"}], "1": [{"video": "x1"}, {"video": "x2"}]}}
        serie, folgen = folgen_finden(daten, "x2")
        self.assertEqual([f["id"] for f in folgen], ["x1", "x2", "x3"])
        self.assertEqual([f["staffel"] for f in folgen], [1, 1, 2])
        self.assertEqual(serie, "Serie")

    def test_flache_liste_und_verschachtelter_fortschritt(self):
        daten = {"titel": "Mini", "folgen": [{"id": "m1", "name": "Eins", "fortschritt": {"position": 50, "dauer": 100}},
                                             {"id": "m2", "name": "Zwei"}]}
        serie, folgen = folgen_finden(daten, "m1")
        self.assertEqual(serie, "Mini")
        self.assertEqual(folgen[0]["position"], 50.0)
        self.assertEqual(folgen[1]["folge"], 2)

    def test_unbekannte_id(self):
        self.assertEqual(folgen_finden({"folgen": [{"id": "a"}]}, "zzz"), (None, []))

    def test_neueste_antwort_mit_mehr_folgen_gewinnt(self):
        start = {"reihen": [{"titel": "Weiterschauen", "eintraege": [{"id": "s2"}]}]}
        serie = {"titel": "S", "folgen": [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}]}
        titel, folgen = folgen_aus_antworten([start, serie], "s2")
        self.assertEqual(len(folgen), 3)
        self.assertEqual(titel, "S")

    def test_video_id(self):
        self.assertEqual(video_id_aus_url("http://x/kino/api/video/datei/6167f34a4bd6"), "6167f34a4bd6")
        self.assertEqual(video_id_aus_url("https://y/kino/api/video/status/mt-123?ton=0"), "mt-123")
        self.assertIsNone(video_id_aus_url("blob:http://x/abc"))

    def test_anzeige(self):
        self.assertEqual(anzeige_titel("Dark", {"staffel": 1, "folge": 2, "titel": "Lügen"}), "Dark · S1:F2 – Lügen")
        self.assertEqual(anzeige_titel(None, {"staffel": None, "folge": None, "titel": "Film"}), "Film")


class MeldungTest(unittest.TestCase):
    VORLAGE = {"url": "http://192.168.178.69/kino/api/video/fortschritt", "methode": "POST",
               "kopf": {"Content-Type": "application/json", "Cookie": "x"}, "art": "json",
               "obj": {"id": "a1", "position": 61, "dauer": 3000.5, "gesehen": False},
               "felder": {"id": "id", "pos": "position", "dauer": "dauer", "faktor": 1}}

    def test_json(self):
        url, methode, kopf, body = anfrage_bauen(self.VORLAGE, "b7", 123.9, 2500.25,
                                                 "https://abc.trycloudflare.com/kino/")
        self.assertEqual(url, "https://abc.trycloudflare.com/kino/api/video/fortschritt")
        self.assertEqual(methode, "POST")
        self.assertNotIn("Cookie", kopf)
        self.assertEqual(json.loads(body), {"id": "b7", "position": 123, "dauer": 2500.25, "gesehen": False})

    def test_formular_und_id_in_url(self):
        vorlage = {"url": "http://h/kino/api/video/fortschritt/a1", "methode": "PUT", "kopf": {}, "art": "form",
                   "obj": {"ms": "61000"}, "felder": {"pos": "ms", "faktor": 1000}, "id_in_url": True, "alte_id": "a1"}
        self.assertTrue(gueltige_vorlage(vorlage))
        url, methode, kopf, body = anfrage_bauen(vorlage, "b2", 10.5, 0)
        self.assertEqual(url, "http://h/kino/api/video/fortschritt/b2")
        self.assertEqual(methode, "PUT")
        self.assertEqual(body, b"ms=10500")
        self.assertEqual(kopf["Content-Type"], "application/x-www-form-urlencoded")

    def test_ungueltig(self):
        self.assertFalse(gueltige_vorlage({"url": "x", "felder": {"pos": "p"}, "obj": {}}))


class NetzTest(unittest.TestCase):
    def test_jarvis_erkennen(self):
        self.assertTrue(ist_jarvis(302, "/anmelden.html?ziel=/kino/", b""))
        self.assertTrue(ist_jarvis(200, "", b'<script src="kino.js"></script>'))
        self.assertFalse(ist_jarvis(200, "", b"<title>FRITZ!Box</title> Bitte anmelden"))
        self.assertFalse(ist_jarvis(530, "", b"kino.js"))
        self.assertFalse(ist_jarvis(None, "", b""))

    def test_basis_tauschen(self):
        self.assertEqual(basis_tauschen("http://192.168.178.69/kino/api/video/datei/x", "http://192.168.178.69/kino/",
                                        "https://t.trycloudflare.com/kino/"),
                         "https://t.trycloudflare.com/kino/api/video/datei/x")
        self.assertEqual(basis_tauschen("http://jarvis.local/kino/#/serie/5", None, "http://[fd00::5]/kino/"),
                         "http://[fd00::5]/kino/#/serie/5")

    def test_adresse_normalisieren(self):
        self.assertEqual(normalisiere_adresse("jarvis.local"), "http://jarvis.local/kino/")
        self.assertEqual(normalisiere_adresse("https://x.myfritz.net/kino"), "https://x.myfritz.net/kino/")
        self.assertEqual(normalisiere_adresse("http://[2a02:8070::1]:8080/"), "http://[2a02:8070::1]:8080/kino/")
        self.assertEqual(normalisiere_adresse("abc-def.trycloudflare.com/kino/#/serie/5"),
                         "https://abc-def.trycloudflare.com/kino/")
        self.assertEqual(normalisiere_adresse("HTTPS://ABC.trycloudflare.com/kino/api/kino/start?x=1"),
                         "https://abc.trycloudflare.com/kino/")
        self.assertEqual(normalisiere_adresse("192.168.178.69"), "http://192.168.178.69/kino/")
        self.assertEqual(normalisiere_adresse("jarvis:8080"), "http://jarvis:8080/kino/")
        self.assertEqual(normalisiere_adresse("[fd00::5]"), "http://[fd00::5]/kino/")
        self.assertEqual(normalisiere_adresse("ftp://x.de"), "")
        self.assertEqual(normalisiere_adresse("https://abc.trycloudflare.com/anmelden.html"),
                         "https://abc.trycloudflare.com/kino/")
        self.assertEqual(normalisiere_adresse("jarvis.fritz.box"), "http://jarvis.fritz.box/kino/")
        self.assertEqual(normalisiere_adresse("2a02:8070::1"), "http://[2a02:8070::1]/kino/")


class PlayerTest(unittest.TestCase):
    def test_argumente(self):
        args = mpv_argumente({"hwdec": "vaapi", "tonsprache": "en", "untertitel": "de"}, "/s", "/l", "/d", "/p",
                             2, "sitzung=abc", "http://r/", "UA")
        self.assertIn("--hwdec=vaapi", args)
        self.assertIn("--playlist-start=2", args)
        self.assertIn("--alang=en,eng,de,deu,ger", args)
        self.assertIn("--slang=de,deu,ger", args)
        self.assertIn("--http-header-fields-append=Cookie: sitzung=abc", args)


class FehlerTest(unittest.TestCase):
    def test_einordnen(self):
        rauschen = "[   0.1][e][vaapi] libva: vaGetDriverNames() failed"
        self.assertEqual(fehler_einordnen([rauschen, "[ 0.2][e][stream] HTTP error 401 Unauthorized"])["art"], "anmeldung")
        self.assertEqual(fehler_einordnen(["[ 0.2][e][ffmpeg] http: HTTP error 404 Not Found"])["art"], "fehlt")
        self.assertEqual(fehler_einordnen(["[ 0.2][e][ffmpeg] tcp: Connection refused"])["art"], "netz")
        self.assertEqual(fehler_einordnen(["[ 0.2][e][vd] Could not open codec."])["art"], "bild")
        unbekannt = fehler_einordnen([rauschen])
        self.assertEqual(unbekannt["art"], "unbekannt")
        self.assertEqual(unbekannt["details"], "")


class FortschrittTest(unittest.TestCase):
    def test_fast_fertig_beginnt_von_vorn(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = Fortschritt(Path(d) / "f.json")
            f.setzen("a", 100, 3000)
            f.setzen("b", 2990, 3000)
            f.sichern()
            g = Fortschritt(Path(d) / "f.json")
            self.assertEqual(g.holen("a"), 100)
            self.assertEqual(g.holen("b"), 0)


if __name__ == "__main__":
    unittest.main()
