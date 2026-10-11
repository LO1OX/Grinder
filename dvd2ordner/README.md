# dvd2ordner

DVD ins USB-Laufwerk legen. Der Inhalt wird in einen Ordner kopiert. Die DVD wird ausgeworfen. Fertig.

Pro Disc entsteht ein Ordner `ZIEL/<Discname>_<Datum>_<Uhrzeit>`.
Schlägt etwas fehl, heißt der Ordner `..._FEHLER`, und im Protokoll steht warum.

## Installation (Linux, als root)

```
sudo ./install.sh              # Ziel: /srv/dvd
sudo ./install.sh /pfad/ziel   # eigener Zielordner
```

Danach läuft es dauerhaft als Dienst und wartet auf Discs.

## Film-DVDs (optional)

Gekaufte Film-DVDs sind verschlüsselt. Damit sie entschlüsselt kopiert werden, einmalig:

```
sudo apt install dvdbackup libdvd-pkg
sudo dpkg-reconfigure libdvd-pkg
```

Ist `dvdbackup` nicht installiert, werden die Dateien trotzdem kopiert, nur eben verschlüsselt. VLC kann die meisten davon trotzdem abspielen.

## Nützliches

```
systemctl status dvd2ordner           # läuft es?
tail -f /srv/dvd/_protokoll.log       # was macht es gerade?
sudo dvd2ordner.sh einmal             # eine Disc von Hand einlesen, ohne Dienst
```

Anderes Laufwerk als `/dev/sr0`? In `/etc/systemd/system/dvd2ordner.service` die Zeile `Environment=GERAET=` anpassen, dann `systemctl daemon-reload && systemctl restart dvd2ordner`.
