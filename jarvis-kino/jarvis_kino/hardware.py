"""Grafikkarte erkennen und Hardware-Dekodierung von mpv testen."""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

# Name, ffmpeg-Encoder-Optionen (Kandidaten der Reihe nach)
CODECS = [
    ("H.264", [["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]]),
    ("HEVC (H.265)", [["-c:v", "libx265", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-x265-params", "log-level=error"]]),
    ("HEVC 10-Bit (HDR)", [["-c:v", "libx265", "-preset", "ultrafast", "-pix_fmt", "yuv420p10le", "-x265-params", "log-level=error"]]),
    ("AV1", [["-c:v", "libsvtav1", "-preset", "12", "-pix_fmt", "yuv420p"],
             ["-c:v", "libaom-av1", "-cpu-used", "8", "-row-mt", "1", "-pix_fmt", "yuv420p"]]),
]

HW_ZEILE = re.compile(r"Using hardware decoding \(([^)]+)\)")


def grafikkarten():
    """Liste der Grafikkarten laut lspci (leer, wenn nicht ermittelbar)."""
    if not shutil.which("lspci"):
        return []
    try:
        aus = subprocess.run(["lspci"], capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    karten = []
    for zeile in aus.splitlines():
        if re.search(r"VGA compatible|3D controller|Display controller", zeile):
            karten.append(zeile.split(": ", 1)[-1].strip())
    return karten


def hersteller(karten):
    text = " ".join(karten).lower()
    return {
        "nvidia": "nvidia" in text,
        "intel": "intel" in text,
        "amd": "amd" in text or "ati " in text or "radeon" in text,
    }


def _testvideo(ordner, name, kandidaten):
    ziel = Path(ordner) / (re.sub(r"\W+", "_", name) + ".mkv")
    for opts in kandidaten:
        befehl = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                  "-i", "testsrc2=size=1280x720:rate=24", "-t", "1"] + opts + [str(ziel)]
        try:
            if subprocess.run(befehl, capture_output=True, timeout=120, stdin=subprocess.DEVNULL).returncode == 0 and ziel.exists():
                return ziel
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def dekoder_testen(datei, hwdec="auto-copy-safe"):
    """Gibt die Hardware-Methode (z. B. 'vaapi', 'nvdec') oder None (Prozessor) zurück."""
    befehl = ["mpv", "--no-config", "--vo=null", "--ao=null", f"--hwdec={hwdec}", "--hwdec-codecs=all",
              "--frames=12", "--msg-level=all=no,vd=v", "--msg-color=no", str(datei)]
    try:
        lauf = subprocess.run(befehl, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    m = HW_ZEILE.search(lauf.stdout + lauf.stderr)
    return m.group(1) if m else None


def testen(hwdec="auto-copy-safe"):
    """[(Codec, Ergebnis-Text, ok)] – ok: True = Grafikkarte, False = Prozessor, None = nicht testbar."""
    if not shutil.which("mpv"):
        return [("mpv", "nicht installiert", None)]
    if not shutil.which("ffmpeg"):
        return [("ffmpeg", "nicht installiert – Test nicht möglich", None)]
    ergebnisse = []
    with tempfile.TemporaryDirectory(prefix="jarvis-hwtest-") as ordner:
        for name, kandidaten in CODECS:
            datei = _testvideo(ordner, name, kandidaten)
            if not datei:
                ergebnisse.append((name, "nicht testbar (kein Encoder)", None))
                continue
            methode = dekoder_testen(datei, hwdec)
            if methode:
                ergebnisse.append((name, f"Grafikkarte ({methode.replace('-copy', '')})", True))
            else:
                ergebnisse.append((name, "Prozessor", False))
    return ergebnisse


def bericht(hwdec="auto-copy-safe"):
    karten = grafikkarten()
    zeilen = ["Grafikkarte(n): " + ("; ".join(karten) if karten else "unbekannt")]
    for name, text, ok in testen(hwdec):
        zeichen = {True: "✓", False: "•", None: "?"}[ok]
        zeilen.append(f"  {zeichen} {name:<20} {text}")
    zeilen.append("✓ = Grafikkarte entlastet den Prozessor   • = läuft über den Prozessor (funktioniert trotzdem)")
    return "\n".join(zeilen)
