#!/usr/bin/env bash
# dvd2ordner – DVD rein, Inhalt landet in einem Ordner, DVD kommt raus. Mehr nicht.
#
# Aufruf:
#   dvd2ordner.sh          wartet dauerhaft auf Discs (so läuft der Dienst)
#   dvd2ordner.sh einmal   liest die eingelegte Disc einmal ein und beendet sich
#
# Muss als root laufen (wegen mount und eject).

# ---- Einstellungen -----------------------------------------------------------
GERAET="${GERAET:-/dev/sr0}"     # das DVD-Laufwerk
ZIEL="${ZIEL:-/srv/dvd}"          # hier landen die Ordner
# ------------------------------------------------------------------------------

MOUNTPUNKT="/mnt/dvd2ordner"
PROTOKOLL="$ZIEL/_protokoll.log"

set -u
mkdir -p "$ZIEL" "$MOUNTPUNKT"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S')  $*" | tee -a "$PROTOKOLL"; }

# 0 = lesbare Disc liegt im Laufwerk
disc_drin() { blkid -p "$GERAET" >/dev/null 2>&1; }

einlesen() {
    local label datum ordner ok=0

    label=$(blkid -p -o value -s LABEL "$GERAET" 2>/dev/null | tr -c 'A-Za-z0-9._-' '_' | sed 's/_*$//')
    [ -z "$label" ] && label="DVD"
    datum=$(date '+%Y-%m-%d_%H%M')
    ordner="$ZIEL/${label}_$datum"
    mkdir -p "$ordner"

    log "Disc erkannt: $label  ->  $ordner"

    if ! mount -o ro "$GERAET" "$MOUNTPUNKT" 2>>"$PROTOKOLL"; then
        log "FEHLER: Disc lässt sich nicht lesen."
        mv "$ordner" "${ordner}_FEHLER"
        eject "$GERAET"
        return 1
    fi

    if [ -d "$MOUNTPUNKT/VIDEO_TS" ] && command -v dvdbackup >/dev/null; then
        # Film-DVD: dvdbackup kopiert und entschlüsselt gleichzeitig.
        log "Film-DVD, kopiere mit dvdbackup ..."
        umount "$MOUNTPUNKT"
        dvdbackup -i "$GERAET" -o "$ZIEL" -M -n "$(basename "$ordner")" >>"$PROTOKOLL" 2>&1 && ok=1
    else
        log "Kopiere Dateien ..."
        cp -r "$MOUNTPUNKT"/. "$ordner"/ 2>>"$PROTOKOLL" && ok=1
        umount "$MOUNTPUNKT"
    fi

    chmod -R u+w "$ordner"
    sync

    if [ "$ok" = 1 ]; then
        log "Fertig: $(du -sh "$ordner" | cut -f1) in $ordner"
    else
        log "FEHLER beim Kopieren, Details oben im Protokoll."
        mv "$ordner" "${ordner}_FEHLER"
    fi

    eject "$GERAET"
    [ "$ok" = 1 ]
}

# ---- einmaliger Aufruf -------------------------------------------------------
if [ "${1:-}" = "einmal" ]; then
    disc_drin || { echo "Keine Disc in $GERAET."; exit 1; }
    einlesen
    exit $?
fi

# ---- Dauerbetrieb -------------------------------------------------------------
log "dvd2ordner gestartet. Laufwerk: $GERAET  Ziel: $ZIEL"
while true; do
    if disc_drin; then
        einlesen
        # warten bis die Disc raus ist, sonst würde sie sofort nochmal eingelesen
        while disc_drin; do sleep 5; done
    fi
    sleep 5
done
