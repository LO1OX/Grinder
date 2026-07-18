# MonoHome PWA

## Schnell testen

Die Kamera funktioniert auf iPhone nur über HTTPS oder localhost.

1. Lade den Ordner auf einen HTTPS-Webhost, z. B. GitHub Pages, Netlify oder Vercel.
2. Öffne die URL in Safari.
3. Tippe auf Teilen → Zum Home-Bildschirm.
4. Öffne MonoHome über das neue App-Symbol.

## Lokal am PC testen

Im Projektordner:

python -m http.server 8080

Dann im Browser öffnen:

http://localhost:8080

## Enthalten

- Schwarz-Weiß-Grau-Design
- Übersicht, Lampen, Wohnzimmer, Szenen
- Direktregler für Ein/Aus, Helligkeit und Farbe
- Kamera-Farbkalibrierung
- Speicherung von Profilen im Browser
- Offline-PWA-Grundgerüst
- Responsive Layout für iPhone und Tablet

## Wichtig

Diese Version arbeitet mit simulierten Geräten. Für echte Geräte muss ein Backend ergänzt werden, am sinnvollsten Home Assistant. Zugangsdaten gehören nicht direkt in die PWA.
