# Changelog

Alle nennenswerten Änderungen der letzten Versionen der Kfz-Verwaltung.
Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/).

## [1.12] – 2026-11-24

### Behoben
- Programmstart nach dem Spalten-Umbau im Tankbuch wiederhergestellt (GTK mochte das Verschieben der Spalte „Tankstelle“ nicht; sie wird jetzt sauber hinten angehängt)

### Geändert
- Tankbuch: Spalte „Tankstelle“ steht am Tabellenende, hinter „Ø €/Liter“
- Dateinamen-Schema eingeführt: `Kfz-Verwaltung-<Version>.py`, hier `Kfz-Verwaltung-1.12.py`

## [1.11]

### Geändert
- Dashboard „Fahrzeugbestand“: Fahrzeuge und Kennzeichen linksbündig statt zentriert
- Tankbuch: Spaltenüberschrift „gefahren. km“ → „gefahrene km“

## [1.10]

### Hinzugefügt
- Tankbuch: zwei neue berechnete Spalten, „gefahrene km“ (Differenz zum vorigen Tankstopp) und „Ø €/Liter“ (Kosten je Liter der jeweiligen Betankung); der Ø-Verbrauch wird jetzt mit 2 Nachkommastellen angezeigt
- Fenstergröße und Maximierung werden dauerhaft gemerkt und beim nächsten Start wiederhergestellt

### Geändert
- Auswertungen „Kosten je Jahr“: Spalte „Versicherung“ → „Versicherung / Kfz-Steuer“

### Entfernt
- Dashboard „Fahrzeugbestand“: Gesamtkosten entfallen aus den Fahrzeugzeilen
- Dashboard: Kennzahlkasten „Fahrzeuge“ (Anzahl) entfernt

## [1.9.6]

### Hinzugefügt
- Dashboard: Überschrift „Fahrzeugbestand“ über der Fahrzeugliste; Liste in einer Karte im Stil der Jahres-Kostenbox
- Auswertungen „Tankbuch-Statistik“: Jahresfilter („Alle Jahre“ oder ein Kalenderjahr); alle Werte (Anzahl, Menge, Kosten, Ø Preis/Liter, Ø Verbräuche, Hochrechnung) rechnen nur mit dem gewählten Zeitraum

### Geändert
- Modul „Fahrzeuge“ → „Fahrzeugdaten“ umbenannt
- TÜV / HU: Dialogfeld „Notizen“ auf das große, 10-zeilige Textfeld umgestellt (wie im Modul Service)

## [1.9.5]

### Behoben
- Fahrtenbuch: gefahrene km werden jetzt auch ohne Häkchen „Angabe in Milen“ berechnet (Differenz von/bis); die Milen-Umrechnung erfolgt nur mit Häkchen
