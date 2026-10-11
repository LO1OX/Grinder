#!/usr/bin/env bash
# Installiert dvd2ordner als Dienst. Aufruf als root:
#   ./install.sh                 Ziel: /srv/dvd
#   ./install.sh /pfad/zum/ziel  eigener Zielordner
set -e
cd "$(dirname "$0")"
ZIEL="${1:-/srv/dvd}"

install -m 755 dvd2ordner.sh /usr/local/bin/dvd2ordner.sh
sed "s#^Environment=ZIEL=.*#Environment=ZIEL=$ZIEL#" dvd2ordner.service > /etc/systemd/system/dvd2ordner.service
mkdir -p "$ZIEL"
systemctl daemon-reload
systemctl enable --now dvd2ordner.service

echo "Läuft. DVDs landen in: $ZIEL"
echo "Status:    systemctl status dvd2ordner"
echo "Protokoll: $ZIEL/_protokoll.log"
