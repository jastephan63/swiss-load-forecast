# Lastprognose und Anomalieerkennung für den Schweizer Stromverbrauch

Kurzfassung. Die ausführliche Dokumentation mit allen Abbildungen steht im englischen [README.md](README.md).

## Aufgabe

Am Vortag um 10:00 Uhr werden die 24 Stundenwerte des Schweizer Endverbrauchs für den Folgetag prognostiziert (Horizont 14 bis 38 Stunden). Zusätzlich werden ungewöhnliche Verbrauchsperioden erkannt und von Datenfehlern unterschieden.

## Daten

* **Swissgrid, Energieübersicht Schweiz:** Summe der endverbrauchten Energie in der Regelzone Schweiz, 15-Minuten-Werte 2021 bis 2025, in MW umgerechnet. Die Rohdaten sind vollständig (175'296 Viertelstunden, keine Lücken oder Duplikate). Wichtiger Befund: Ab der Datei 2025 bezeichnen die Zeitstempel den **Beginn** statt das **Ende** der Viertelstunde. Die Pipeline erkennt das automatisch; ohne diese Korrektur wäre das ganze Jahr 2025 um 15 Minuten verschoben.
* **Open-Meteo:** Temperatur und Globalstrahlung für acht Standorte, gewichtet nach der Wohnbevölkerung der zugeordneten Kantone.
* **Feiertage:** Für jeden Tag der Bevölkerungsanteil mit einem kantonalen Feiertag (z. B. 1. August 1,0; Stephanstag 0,69; 1. Mai 0,43), dazu Brückentage und ein einfacher Schulferien-Proxy.

## Vorgehen

* Alle Merkmale respektieren den Prognosezeitpunkt (Lags von mindestens 48 Stunden, Vortag nur bis 10:00 Uhr). Unit-Tests stellen sicher, dass keine späteren Daten einfliessen, auch an den Tagen der Zeitumstellung.
* Baselines: saisonal naive Prognose (gleiche Stunde der Vorwoche) und lineare Modelle. Hauptmodell: LightGBM.
* Wetter wird getrennt ausgewiesen: nur bis zum Prognosezeitpunkt bekanntes Wetter (einsetzbar) und beobachtetes Wetter des Zieltags ("Oracle", nur als Obergrenze).
* Validierung mit Rolling-Origin-Kreuzvalidierung (8 Quartale, Juli 2023 bis Juni 2025). Testperiode Juli bis Dezember 2025, einmalig ausgewertet.
* Prognoseintervalle mit Quantilsregression und konformer Kalibrierung.

## Ergebnisse (Testperiode Juli bis Dezember 2025)

| Modell | MAE (MW) | MAPE |
|---|---:|---:|
| Saisonal naiv | 320 | 5,2% |
| Linear, nur Kalender | 315 | 5,3% |
| Linear, Lags und Wetter | 225 | 3,7% |
| LightGBM, ohne Wetter | 192 | 3,1% |
| **LightGBM, Wetter bis Prognosezeitpunkt** | **184** | **3,0%** |
| LightGBM, Oracle-Wetter (Obergrenze) | 134 | 2,2% |

* Das Hauptmodell senkt den Fehler gegenüber der naiven Baseline um 43%. Ein lineares Modell mit denselben Merkmalen liegt mit 3,7% MAPE bereits nahe; der grösste Teil des Gewinns stammt aus den Merkmalen, nicht aus dem Algorithmus.
* Bis 10:00 Uhr bekanntes Wetter bringt wenig (rund 5%). Die Oracle-Variante zeigt, dass echte Wetterprognosen den Fehler um bis zu 27% senken könnten.
* Das 90%-Intervall deckt nach der Kalibrierung 92,3% der Teststunden ab (vorher 83%).

## Anomalieerkennung

Drei sich ergänzende Verfahren: Abweichung ausserhalb des Prognoseintervalls, Isolation Forest auf 15-Minuten-Merkmalen und eine Regel für eingefrorene Messwerte. In einem Test mit künstlich eingefügten Spitzen, Einbrüchen, Niveausprüngen und eingefrorenen Werten findet die Kombination alle Ereignisse; einzeln erkennt der Isolation Forest 75% und die Residuenmethode 55%. Die grössten realen Abweichungen fallen mit plötzlichen Kälteeinbrüchen im Frühling und Spätherbst, der Hitzewelle im August 2023 und Brückentagen zusammen. Dies sind plausible Erklärungen, keine überprüften Ursachen.

## Grenzen und nächste Schritte

Nationales Aggregat statt Netzgebiet, keine echten Wetterprognosen, eine sechsmonatige Testperiode. Mit Smart-Meter- oder Netzdaten würde ich Wetterprognosen einbinden, auf Ebene Unterwerk oder Kundensegment prognostizieren, Photovoltaik, Wärmepumpen und Elektromobilität explizit modellieren und die Anomalieprüfung als Plausibilisierungsschritt für Messdaten betreiben.
