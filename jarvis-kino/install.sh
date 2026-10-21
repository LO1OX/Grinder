#!/usr/bin/env bash
# Jarvis Kino – Installation für Ubuntu 22.04 / 24.04 (und neuer)
#
#   curl -fsSL https://raw.githubusercontent.com/LO1OX/Grinder/claude/admiring-brown-junepr/jarvis-kino/install.sh | bash
#
# Installiert nur für deinen Benutzer (~/.local), fragt einmal nach dem
# sudo-Passwort für die Pakete (mpv, Grafiktreiber für Videobeschleunigung).
set -euo pipefail

# Alles steckt in main(): bash liest so das ganze Skript ein, bevor es läuft –
# wichtig bei „curl … | bash“, damit kein Programm den Rest des Skripts verschluckt.
main() {
    REPO="LO1OX/Grinder"
    ZWEIG="${JARVIS_KINO_ZWEIG:-claude/admiring-brown-junepr}"
    # uosc 4.7: läuft mit Ubuntus mpv (0.34–0.37, Lua 5.2); 5.x zeigt dort keine Menüs.
    UOSC_VERSION="4.7.0"
    UOSC_SHA256="086772527e0b3afdd45e93877016e5ec0119ce93e860888aad9aa67660991aa1"
    PYQT="PyQt6==6.7.1 PyQt6-Qt6==6.7.3 PyQt6-WebEngine==6.7.0 PyQt6-WebEngine-Qt6==6.7.3"

    DATEN="${XDG_DATA_HOME:-$HOME/.local/share}/jarvis-kino"
    APP="$DATEN/app"
    VENV="$DATEN/venv"
    BIN="$HOME/.local/bin"
    DESKTOP="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"

    gruen() { printf '\033[1;32m%s\033[0m\n' "$*"; }
    gelb()  { printf '\033[1;33m%s\033[0m\n' "$*"; }
    rot()   { printf '\033[1;31m%s\033[0m\n' "$*" >&2; }
    schritt() { printf '\n\033[1;31m▶\033[0m \033[1m%s\033[0m\n' "$*"; }
    frage() {  # frage "Text" -> 0 bei ja (funktioniert auch bei curl | bash)
        local antwort=""
        if [ -r /dev/tty ]; then
            printf '%s [j/N] ' "$1" > /dev/tty
            read -r antwort < /dev/tty || true
        fi
        [[ "$antwort" =~ ^[jJyY] ]]
    }

    if [ "$(id -u)" -eq 0 ]; then
        rot "Bitte NICHT mit sudo starten – einfach als normaler Benutzer (sudo wird bei Bedarf gefragt)."
        exit 1
    fi
    if ! command -v apt-get >/dev/null; then
        rot "Dieses Skript ist für Ubuntu (apt). Andere Systeme werden nicht unterstützt."
        exit 1
    fi

    . /etc/os-release
    gruen "Jarvis Kino wird installiert auf: ${PRETTY_NAME:-Linux}"
    if [ "${ID:-}" = "ubuntu" ] && [ "${VERSION_ID%%.*}" -lt 22 ] 2>/dev/null; then
        gelb "Ubuntu ${VERSION_ID} ist älter als 22.04 – es kann funktionieren, getestet ist 22.04/24.04."
    fi

    # ------------------------------------------------------------ Pakete
    schritt "Pakete installieren (Player, Schriften, Netzwerk) – ggf. sudo-Passwort eingeben"
    PAKETE=(mpv ffmpeg python3 python3-venv python3-pip curl unzip ca-certificates pciutils vainfo
            libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-image0 libxcb-render-util0 libxcb-shape0
            libxcb-xinerama0 libxcb-xkb1 libxcb-randr0 libxkbcommon-x11-0 libxkbcommon0 libnss3 libegl1 libgl1
            libopengl0 libxcomposite1 libxdamage1 libxrandr2 libxtst6 libxkbfile1 libxshmfence1 libdbus-1-3
            libfontconfig1 libasound2t64 fonts-noto-core libnss-mdns avahi-daemon)
    sudo apt-get update -qq || gelb "apt-get update meldete Fehler – versuche trotzdem weiter."
    # Paketnamen, die es nicht überall gibt (z. B. libasound2t64 erst ab 24.04)
    VERFUEGBAR=()
    for p in "${PAKETE[@]}"; do
        if apt-cache show "$p" >/dev/null 2>&1; then VERFUEGBAR+=("$p")
        elif [ "$p" = "libasound2t64" ]; then VERFUEGBAR+=("libasound2")
        else gelb "Paket $p nicht gefunden – wird übersprungen."; fi
    done
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${VERFUEGBAR[@]}"

    # ------------------------------------------------------------ Grafik
    schritt "Grafikkarte erkennen und Video-Beschleunigung einrichten"
    GPU="$(lspci 2>/dev/null | grep -Ei 'vga|3d controller|display controller' || true)"
    echo "${GPU:-keine Grafikkarte erkannt}"
    if grep -qi intel <<<"$GPU"; then
        # Neue Intel-Chips (ab ~2015): iHD-Treiber; ältere: i965
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq intel-media-va-driver-non-free 2>/dev/null \
            || sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq intel-media-va-driver || true
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq i965-va-driver 2>/dev/null || true
        gruen "Intel-Videobeschleunigung (VAAPI) eingerichtet."
    fi
    if grep -Eqi 'amd|ati |radeon' <<<"$GPU"; then
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq mesa-va-drivers mesa-vdpau-drivers 2>/dev/null \
            || sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq mesa-va-drivers || true
        gruen "AMD-Videobeschleunigung (VAAPI) eingerichtet."
    fi
    if grep -qi nvidia <<<"$GPU"; then
        if command -v nvidia-smi >/dev/null && nvidia-smi >/dev/null 2>&1; then
            gruen "NVIDIA-Treiber ist aktiv – mpv nutzt NVDEC."
        else
            gelb "NVIDIA-Grafikkarte gefunden, aber der NVIDIA-Treiber läuft nicht."
            gelb "Ohne ihn spielt die Grafikkarte keine Videos ab (dann übernimmt der Prozessor)."
            if frage "Empfohlenen NVIDIA-Treiber jetzt installieren? (Neustart nötig)"; then
                sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ubuntu-drivers-common
                sudo ubuntu-drivers install && gelb "Bitte den Laptop nach der Installation neu starten."
            else
                gelb "Später nachholen mit:  sudo ubuntu-drivers install"
            fi
        fi
    fi

    # ------------------------------------------------------------ Programm
    schritt "Jarvis Kino herunterladen"
    TMP="$(mktemp -d)"
    trap 'rm -rf "$TMP"' EXIT
    QUELLE=""
    HIER=""
    # Lokale Dateien nur, wenn das Skript als Datei gestartet wurde (nicht über curl | bash)
    if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
        HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    fi
    if [ -n "$HIER" ] && [ -f "$HIER/jarvis_kino/__main__.py" ]; then
        QUELLE="$HIER"
        echo "Nutze lokale Dateien aus $QUELLE"
    else
        curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$ZWEIG" -o "$TMP/quelle.tar.gz"
        tar -xzf "$TMP/quelle.tar.gz" -C "$TMP"
        QUELLE="$(find "$TMP" -maxdepth 2 -type d -name jarvis-kino | head -1)"
        [ -f "$QUELLE/jarvis_kino/__main__.py" ] || { rot "Download unvollständig."; exit 1; }
    fi

    mkdir -p "$DATEN"
    rm -rf "$APP.neu"
    mkdir -p "$APP.neu"
    cp -r "$QUELLE/jarvis_kino" "$QUELLE/mpv" "$QUELLE/jarvis-kino.svg" "$APP.neu/"
    [ -f "$QUELLE/uninstall.sh" ] && cp "$QUELLE/uninstall.sh" "$APP.neu/"

    schritt "Player-Oberfläche (uosc $UOSC_VERSION) einrichten"
    curl -fsSL "https://github.com/tomasklaen/uosc/releases/download/$UOSC_VERSION/uosc.zip" -o "$TMP/uosc.zip"
    echo "$UOSC_SHA256  $TMP/uosc.zip" | sha256sum -c --quiet - || { rot "uosc-Download beschädigt."; exit 1; }
    unzip -q -o "$TMP/uosc.zip" -d "$TMP/uosc"
    mkdir -p "$APP.neu/mpv/scripts" "$APP.neu/mpv/fonts"
    cp -r "$TMP/uosc/scripts/"* "$APP.neu/mpv/scripts/"
    cp "$TMP/uosc/fonts/"* "$APP.neu/mpv/fonts/"
    # Ubuntus mpv nutzt Lua 5.2: dort bricht uosc ab, sobald eine Überblendung die
    # Deckkraft knapp über 100 % rechnet (negativer Alpha-Wert). Auf 0–100 % begrenzen.
    UOSC_UTILS="$APP.neu/mpv/scripts/uosc_shared/lib/utils.lua"
    sed -i 's/^\treturn 255 - math.ceil(255 \* opacity)$/\treturn 255 - math.ceil(255 * math.max(0, math.min(1, opacity)))/' "$UOSC_UTILS"
    grep -q 'math.max(0, math.min(1, opacity))' "$UOSC_UTILS" || { rot "uosc-Anpassung fehlgeschlagen."; exit 1; }

    rm -rf "$APP.alt"
    [ -d "$APP" ] && mv "$APP" "$APP.alt"
    mv "$APP.neu" "$APP"
    rm -rf "$APP.alt"

    schritt "Python-Umgebung mit Qt einrichten (einmalig ca. 200 MB)"
    if [ ! -x "$VENV/bin/python" ] || ! "$VENV/bin/python" -c 'import sys' 2>/dev/null; then
        rm -rf "$VENV"
        python3 -m venv "$VENV"
    fi
    "$VENV/bin/python" -m pip install -q --upgrade pip
    # shellcheck disable=SC2086
    "$VENV/bin/python" -m pip install -q $PYQT
    "$VENV/bin/python" -c "from PyQt6 import QtWebEngineWidgets" || { rot "Qt WebEngine lässt sich nicht laden."; exit 1; }

    schritt "Startmenü-Eintrag anlegen"
    mkdir -p "$BIN" "$DESKTOP" "$ICONS"
    cat > "$BIN/jarvis-kino" <<EOF
#!/usr/bin/env bash
# Im App-Ordner starten, damit Python nie fremden Code aus dem aktuellen Ordner lädt.
cd "$APP" || exit 1
export PYTHONPATH="$APP"
exec "$VENV/bin/python" -m jarvis_kino "\$@"
EOF
    chmod +x "$BIN/jarvis-kino"
    cp "$APP/jarvis-kino.svg" "$ICONS/jarvis-kino.svg"
    cat > "$DESKTOP/jarvis-kino.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Jarvis Kino
GenericName=Filme & Serien
Comment=Filme und Serien von Jarvis schauen
Exec=$BIN/jarvis-kino %U
Icon=jarvis-kino
Terminal=false
Categories=AudioVideo;Video;Player;
Keywords=Kino;Filme;Serien;Jarvis;Streaming;
StartupWMClass=jarvis-kino
StartupNotify=true
Actions=einstellungen;hardware;

[Desktop Action einstellungen]
Name=Einstellungen
Exec=$BIN/jarvis-kino --einstellungen

[Desktop Action hardware]
Name=Hardware-Test (Terminal)
Exec=sh -c '$BIN/jarvis-kino --hardware-test; read -r x'
Terminal=true
EOF
    update-desktop-database "$DESKTOP" >/dev/null 2>&1 || true
    gtk-update-icon-cache -q "${ICONS%/scalable/apps}" >/dev/null 2>&1 || true

    schritt "Hardware-Beschleunigung testen"
    "$BIN/jarvis-kino" --hardware-test < /dev/null || gelb "Test nicht möglich – Videos laufen trotzdem."

    echo
    gruen "✔ Jarvis Kino ist installiert!"
    echo "  Starten: im App-Menü „Jarvis Kino“ anklicken (oder im Terminal: jarvis-kino)"
    echo "  Beim ersten Start kannst du die Jarvis-Adressen prüfen, danach einmal anmelden."
    case ":$PATH:" in *":$BIN:"*) ;; *) gelb "  Hinweis: $BIN ist nicht im PATH – das App-Menü funktioniert trotzdem.";; esac
}

main "$@"
