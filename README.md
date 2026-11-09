# Österreich-Karte – Datenstand

Täglicher Datenstand der OpenStreetMap-Daten für <https://karte.lupos.li>.

- **Zweig `main`:** Abrufskript (`fetch.py`), Abfrage-Leser (`extract-queries.mjs`) und GitHub-Actions-Workflow
- **Zweig `data`:** jeden Tag neu geschrieben: `manifest.json` plus `files/<schlüssel>.json.gz`, ein Paket je Overpass-Abfrage

Ablauf, täglich um 01:23 UTC (`.github/workflows/osm-datenstand.yml`):

1. Die Abfragen werden direkt aus der live Karte gelesen. Ändert sich eine Abfrage in der App, ändert sich ihr Schlüssel, und ab dem nächsten Lauf gibt es das passende Paket.
2. Alle Pakete werden bei Overpass geholt, mit vier Servern, mehreren Runden und Pausen. Scheitert eines, wird das Paket vom Vortag übernommen.
3. Die Daten landen im Zweig `data`. Das CDN jsDelivr liefert sie an die Karte aus.

Die Karte nutzt den Datenstand, wenn ihr Server unter `/snapshot.json` dieses Repository nennt. Fehlt ein Paket oder ist es älter als 8 Tage, fragt sie wie bisher direkt bei Overpass.

Eingerichtet und überwacht wird das Ganze vom Ansible-Playbook `oesterreich_karte_daten.yml` (Semaphore).

Daten: © OpenStreetMap-Mitwirkende, [ODbL](https://www.openstreetmap.org/copyright).
