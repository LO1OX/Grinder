# Jarvis Kino für Ubuntu

Eigene Desktop-App für dein Jarvis-Kino. Die Oberfläche ist dein gewohntes Kino
(gleiches Design, gleiche Anmeldung, „Weiterschauen“ wie am Handy und Fernseher).
Filme und Serien laufen im **mpv-Player** mit eigener Bedienung:

- **Folgen & Staffeln** als scrollbare Liste direkt im Player (Taste **E** oder Knopf unten rechts)
- **Nächste Folge** mit Countdown, vorherige/nächste Folge (**P** / **N**)
- **Intro überspringen** (Taste **S**), **Fortsetzen** an der letzten Stelle
- Ton- und Untertitelspur, Tempo, Vorschaubilder auf der Zeitleiste
- spielt AV1, HEVC/H.265, H.264 direkt ab – Jarvis muss nichts umwandeln
- **Hardware-Beschleunigung** (Intel/AMD über VAAPI, NVIDIA über NVDEC) wird bei der Installation eingerichtet und getestet
- funktioniert **überall**: Heimnetz, `jarvis.local`, Fritzbox/MyFRITZ, Cloudflare, IPv4 und IPv6.
  Die App prüft alle Adressen gleichzeitig, nimmt die beste und wechselt bei Abbrüchen selbst –
  der Film läuft an derselben Stelle weiter.

## Installieren (ein Befehl)

Terminal öffnen (**Strg + Alt + T**), diese Zeile einfügen, **Enter** drücken:

```bash
curl -fsSL https://raw.githubusercontent.com/LO1OX/Grinder/claude/admiring-brown-junepr/jarvis-kino/install.sh | bash
```

Einmal das Passwort deines Laptops eingeben, wenn danach gefragt wird. Fertig, wenn
„✔ Jarvis Kino ist installiert!“ erscheint (dauert beim ersten Mal ein paar Minuten).

## Erster Start

1. Im App-Menü **Jarvis Kino** öffnen – kurz dreht sich ein Ladekreisel, die App sucht Jarvis selbst.
2. Einmal bei Jarvis anmelden – fertig.

Findet die App Jarvis nicht (z. B. unterwegs mit neuer Cloudflare-Adresse), erscheint **„Erneut suchen“**
und darunter **„Adresse eingeben“**. Dort die neue Adresse einfügen → **Verbinden**. Die Cloudflare-Adresse
ändert sich bei jedem Tunnel-Neustart; die alte wird dann automatisch ersetzt. Pro Adresse einmal anmelden.

## Bedienung im Player

| Taste | Funktion |
|---|---|
| Leertaste / Klick aufs Bild | Pause |
| ← / → | 10 s zurück / vor (mit Shift: 60 s) |
| ↑ / ↓, Mausrad | Lautstärke |
| E | Folgen & Staffeln |
| N / P | nächste / vorherige Folge |
| S | Intro überspringen |
| Enter | Knopf auf dem Bild auslösen (z. B. „Nächste Folge“) |
| A / U | Tonspur / Untertitel (Menü) |
| [ / ] | langsamer / schneller |
| Pos1 | von vorn |
| F, Doppelklick | Vollbild |
| Esc | zurück ins Kino (Fortschritt wird gespeichert) |

In der App: **F11** Vollbild, **F5** neu laden, **Strg + ,** Einstellungen, Rechtsklick für alle Funktionen.
Im Player öffnet ein Rechtsklick ein kleines Menü (Folgen, Tonspur, Untertitel, Vollbild, Zurück).

## Wenn etwas nicht klappt

- **Fensterrahmen/Schärfe:** Unter Ubuntu mit Wayland nutzt die App den GNOME-Rahmen über XWayland; ist
  Bruchteil-Skalierung (z. B. 125 %) aktiv, bleibt sie bei Wayland, damit nichts unscharf wird. Erzwingen:
  `JARVIS_KINO_WAYLAND=1 jarvis-kino` (Wayland) bzw. `=0` (XWayland).
- **Ruckeln/Bildfehler:** Einstellungen → Hardware-Beschleunigung → „Testen“; ggf.
  „Automatisch, kompatibel“ wählen.
- **NVIDIA-Grafikkarte:** Ohne NVIDIA-Treiber übernimmt der Prozessor. Treiber: `sudo ubuntu-drivers install`, danach neu starten.
- **Protokolle:** `~/.local/share/jarvis-kino/jarvis-kino.log` und `mpv.log`
- **Aktualisieren:** den Installationsbefehl einfach noch einmal ausführen.
- **Entfernen:** `bash ~/.local/share/jarvis-kino/app/uninstall.sh` (mit `--alles` auch Einstellungen und Anmeldung).

## Technik (für Entwickler)

- `jarvis_kino/` – Qt-App (PyQt6 + QtWebEngine). `bruecke.js` übergibt Videos der Kino-Seite an mpv
  und spiegelt Zeit/Ende zurück, damit die Seite ihren Fortschritt wie gewohnt speichert.
- `mpv/` – eigene mpv-Konfiguration (ändert nichts am System-mpv), `scripts/jarvis.lua`
  (Folgen-Menü, Nächste Folge, Intro, Wiederaufnahme bei Abbrüchen), Oberfläche: uosc 4.7.
- Tests: `python3 -m unittest discover -s tests`; `tests/test_server.py` ist ein nachgebautes
  Jarvis-Kino (Anmeldung, Serie, Abbruch) für Ende-zu-Ende-Tests.
