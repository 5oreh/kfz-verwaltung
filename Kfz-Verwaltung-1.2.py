#!/usr/bin/env python3
"""
Kfz-Verwaltung – Komplette Anwendung in einer Datei
Version: 1.2 – Dateiname: Kfz-Verwaltung-1.2.py
Für Linux Mint 22.x / GTK 3

Aufbau:
  1. Konfiguration & Hilfsfunktionen
  2. DataStore      – Persistenz (JSON pro Fahrzeug), Backup, Export/Import
  3. FieldSpec      – deklarative Modul-Felddefinitionen (Typ -> Dialog/Anzeige)
  4. EntryDialog    – generischer Eingabedialog für alle Module
  5. VehicleDialog  – Fahrzeug-Stammdaten (Grunddaten + Technik)
  6. MainWindow     – Sidebar, Kopfzeile, Module, Dashboard, Auswertungen
"""

import os
import json
import subprocess
import zipfile
from datetime import datetime
from typing import Optional, Dict, List, Any

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk

# ==================== 1. KONFIGURATION ====================
APP_NAME = "kfz_verwaltung"
APP_VERSION = "1.2"
DATA_DIR = os.path.expanduser(f"~/.{APP_NAME}")
SETTINGS_FILE = os.path.join(DATA_DIR, "einstellungen.json")
BACKUP_DIR = os.path.join(DATA_DIR, "backup")
MAX_BACKUPS = 10
MAX_VEHICLES = 3

# Standard-Backupordner = Ordner der Skriptdatei
try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    SCRIPT_DIR = os.getcwd()

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)


def load_settings() -> Dict:
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(settings: Dict):
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ==================== HILFSFUNKTIONEN ====================
def format_currency(amount) -> str:
    try:
        return f"{float(amount or 0):,.2f} €".replace(".", "X").replace(",", ".").replace("X", ",")
    except (TypeError, ValueError):
        return "0,00 €"

def format_number(value, decimals: int = 1) -> str:
    try:
        return f"{float(value or 0):,.{decimals}f}".replace(".", "X").replace(",", ".").replace("X", ",")
    except (TypeError, ValueError):
        return "0"

def format_date(value) -> str:
    """ISO (YYYY-MM-DD) -> DD.MM.YYYY; andere Werte unverändert."""
    if not value:
        return ""
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return str(value)

def format_int(value) -> str:
    try:
        return f"{int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(value or "")

def parse_date(value: str) -> Optional[str]:
    """DD.MM.YYYY -> ISO; akzeptiert auch ISO direkt."""
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Ungültiges Datum: {value} (erwartet TT.MM.JJJJ)")

def parse_float(value: str) -> float:
    value = (value or "").replace("€", "").replace(" ", "").strip()
    if not value:
        return 0.0
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    try:
        return float(value)
    except ValueError:
        raise ValueError(f"Ungültige Zahl: {value}")

def parse_int(value: str) -> int:
    value = (value or "").replace(".", "").replace("km", "").strip()
    if not value:
        return 0
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"Ungültige ganze Zahl: {value}")

def combo_set_active_text(combo: Gtk.ComboBoxText, text: str) -> bool:
    """GTK-3-kompatibles set_active_text(): wählt den Eintrag mit dem
    gegebenen Text per Index (set_active_text existiert nicht überall)."""
    if not text:
        return False
    model = combo.get_model()
    if model is None:
        return False
    combo.set_active(next((i for i, row in enumerate(model) if row[0] == text), -1))
    return combo.get_active() != -1


def today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ==================== 2. DATA STORE ====================
BASIC_FIELDS = {
    'make': '', 'model': '', 'license_plate': '', 'vin': '',
    'first_registration': '', 'color': '', 'fuel_type': '',
    'transmission': '', 'power': '', 'vehicle_type': '',
}
TECH_FIELDS = {
    'engine_capacity': '', 'empty_weight': '', 'max_weight': '', 'seats': '',
    'doors': '', 'length': '', 'width': '', 'height': '', 'notes': '',
}
LIST_KEYS = ['tuv_hu', 'repairs', 'maintenance', 'tires',
             'insurances', 'fuel_entries', 'trip_log', 'documents']


class DataStore:
    """Hält alle Fahrzeuge im Speicher; ein JSON-File pro Fahrzeug."""

    def __init__(self, backup_dir: Optional[str] = None):
        self.vehicles: Dict[str, Dict] = {}
        self.backup_dir = backup_dir or SCRIPT_DIR
        self._load_all()

    # ---------- Persistenz ----------
    def _vehicle_path(self, vid: str) -> str:
        return os.path.join(DATA_DIR, f"fahrzeug_{vid}.json")

    def _load_all(self):
        self.vehicles = {}
        try:
            names = os.listdir(DATA_DIR)
        except OSError:
            names = []
        for name in names:
            if not (name.startswith("fahrzeug_") and name.endswith(".json")):
                continue
            vid = name[len("fahrzeug_"):-len(".json")]
            try:
                with open(os.path.join(DATA_DIR, name), 'r', encoding='utf-8') as f:
                    self.vehicles[vid] = self._normalize(json.load(f))
            except Exception:
                pass  # defekte Datei überspringen, App bleibt nutzbar

    def _normalize(self, data: Dict) -> Dict:
        data.setdefault('basic', {})
        data.setdefault('technical', {})
        for k, v in BASIC_FIELDS.items():
            data['basic'].setdefault(k, v)
        for k, v in TECH_FIELDS.items():
            data['technical'].setdefault(k, v)
        for key in LIST_KEYS:
            entries = data.setdefault(key, [])
            data[key] = [e for e in entries if isinstance(e, dict)]
        return data

    def _save(self, vid: str):
        with open(self._vehicle_path(vid), 'w', encoding='utf-8') as f:
            json.dump(self.vehicles[vid], f, indent=2, ensure_ascii=False)

    # ---------- Fahrzeug-CRUD ----------
    def _next_id(self) -> str:
        max_id = 0
        for vid in self.vehicles:
            try:
                max_id = max(max_id, int(vid))
            except ValueError:
                pass
        return str(max_id + 1)

    def add_vehicle(self, data: Dict) -> str:
        if len(self.vehicles) >= MAX_VEHICLES:
            raise ValueError(f"Maximal {MAX_VEHICLES} Fahrzeuge erlaubt.")
        vid = self._next_id()
        data = self._normalize(data)
        data['id'] = vid
        self.vehicles[vid] = data
        self._save(vid)
        return vid

    def update_vehicle(self, vid: str, data: Dict):
        if vid not in self.vehicles:
            raise ValueError("Fahrzeug nicht gefunden.")
        data['id'] = vid
        self.vehicles[vid] = self._normalize(data)
        self._save(vid)

    def delete_vehicle(self, vid: str):
        if vid not in self.vehicles:
            raise ValueError("Fahrzeug nicht gefunden.")
        path = self._vehicle_path(vid)
        if os.path.exists(path):
            os.remove(path)
        del self.vehicles[vid]

    def get_vehicle(self, vid: str) -> Optional[Dict]:
        return self.vehicles.get(vid)

    def get_vehicle_list(self) -> List[Dict]:
        result = []
        for vid, v in sorted(self.vehicles.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
            result.append({
                'id': vid,
                'name': f"{v['basic']['make']} {v['basic']['model']}".strip() or "(unbenannt)",
                'license_plate': v['basic']['license_plate'],
                'total_costs': self.total_costs(v),
            })
        return result

    # ---------- Eintrag-CRUD ----------
    def add_entry(self, vid: str, key: str, entry: Dict) -> str:
        vehicle = self.get_vehicle(vid)
        if vehicle is None:
            raise ValueError("Kein Fahrzeug ausgewählt.")
        entry['id'] = self._next_entry_id(vehicle[key])
        vehicle[key].append(entry)
        self._save(vid)
        return entry['id']

    def update_entry(self, vid: str, key: str, entry_id: str, entry: Dict):
        vehicle = self.get_vehicle(vid)
        if vehicle is None:
            raise ValueError("Kein Fahrzeug ausgewählt.")
        for i, e in enumerate(vehicle[key]):
            if e.get('id') == entry_id:
                entry['id'] = entry_id
                vehicle[key][i] = entry
                self._save(vid)
                return
        raise ValueError("Eintrag nicht gefunden.")

    def delete_entry(self, vid: str, key: str, entry_id: str):
        vehicle = self.get_vehicle(vid)
        if vehicle is None:
            raise ValueError("Kein Fahrzeug ausgewählt.")
        before = len(vehicle[key])
        vehicle[key] = [e for e in vehicle[key] if e.get('id') != entry_id]
        if len(vehicle[key]) == before:
            raise ValueError("Eintrag nicht gefunden.")
        self._save(vid)

    @staticmethod
    def _next_entry_id(entries: List[Dict]) -> str:
        max_id = 0
        for e in entries:
            try:
                max_id = max(max_id, int(e.get('id', 0)))
            except (TypeError, ValueError):
                pass
        return str(max_id + 1)

    # ---------- Berechnungen ----------
    @staticmethod
    def total_costs(vehicle: Dict) -> float:
        total = 0.0
        for entry in vehicle.get('fuel_entries', []):
            total += float(entry.get('cost') or 0)
        for key in ['repairs', 'tires']:
            for entry in vehicle.get(key, []):
                total += float(entry.get('cost') or 0)
        for entry in vehicle.get('tuv_hu', []):
            total += float(entry.get('cost') or 0)
        for entry in vehicle.get('insurances', []):
            total += float(entry.get('annual_cost') or 0)
        return total

    @staticmethod
    def fuel_consumption(fuel_entries: List[Dict]) -> float:
        """Verbrauch l/100km über volle Tankstopps (1. Eintrag = Referenz)."""
        if len(fuel_entries) < 2:
            return 0.0
        entries = sorted(fuel_entries, key=lambda e: e.get('date') or '')
        total_liters, total_km = 0.0, 0.0
        for i in range(1, len(entries)):
            try:
                prev_km = float(entries[i - 1].get('odometer') or 0)
                curr_km = float(entries[i].get('odometer') or 0)
                liters = float(entries[i].get('liters') or 0)
            except (TypeError, ValueError):
                continue
            km_diff = curr_km - prev_km
            if km_diff > 0 and liters > 0:
                total_liters += liters
                total_km += km_diff
        return (total_liters / total_km) * 100 if total_km > 0 else 0.0

    # ---------- Jahres-Auswertung ----------
    YEARLY_CATEGORIES = ['Tanken', 'Hauptuntersuchung', 'Service',
                         'Reifen', 'Versicherung / Kfz-Steuer']

    def yearly_costs(self, vehicle: Dict) -> Dict[str, Dict[str, float]]:
        """Aggregiert Kosten und gefahrene km pro Jahr (Schlüssel 'YYYY').

        Liefert je Jahr: Kategoriebeträge, 'total' (Gesamtkosten) und
        'km' (Differenz aus erstem/letztem Tankbuch-Zählerstand des Jahres).
        """
        years: Dict[str, Dict[str, Any]] = {}

        def year_of(date) -> Optional[str]:
            year = str(date or '')[:4]
            return year if year.isdigit() else None

        def bucket(year: str) -> Dict[str, Any]:
            y = years.setdefault(year, {c: 0.0 for c in self.YEARLY_CATEGORIES})
            y.setdefault('total', 0.0)
            y.setdefault('km', 0.0)
            return y

        def add(date, category: str, amount):
            year = year_of(date)
            if year is None:
                return
            try:
                amount = float(amount or 0)
            except (TypeError, ValueError):
                return
            y = bucket(year)
            y[category] += amount
            y['total'] += amount

        for e in vehicle.get('fuel_entries', []):
            add(e.get('date'), 'Tanken', e.get('cost'))
        for e in vehicle.get('tuv_hu', []):
            add(e.get('date'), 'Hauptuntersuchung', e.get('cost'))
        for e in vehicle.get('repairs', []):
            add(e.get('date'), 'Service', e.get('cost'))
        for e in vehicle.get('tires', []):
            add(e.get('mount_date'), 'Reifen', e.get('cost'))
        for e in vehicle.get('insurances', []):
            add(e.get('start_date'), 'Versicherung / Kfz-Steuer', e.get('annual_cost'))

        # Gefahrene km und Ø Verbrauch pro Jahr (Näherung über die
        # Tankbuch-Zählerstände; erste Betankung des Jahres = Referenz).
        fuel_by_year: Dict[str, List[Dict[str, float]]] = {}
        for e in vehicle.get('fuel_entries', []):
            year = year_of(e.get('date'))
            if year is None:
                continue
            try:
                fuel_by_year.setdefault(year, []).append({
                    'odometer': float(e.get('odometer') or 0),
                    'liters': float(e.get('liters') or 0)})
            except (TypeError, ValueError):
                continue
        for year, entries in fuel_by_year.items():
            entries.sort(key=lambda x: x['odometer'])
            odometers = [x['odometer'] for x in entries]
            if len(odometers) >= 2:
                bucket(year)['km'] = max(odometers) - min(odometers)
            liters_sum, km_sum = 0.0, 0.0
            for i in range(1, len(entries)):
                km_diff = entries[i]['odometer'] - entries[i - 1]['odometer']
                if km_diff > 0 and entries[i]['liters'] > 0:
                    liters_sum += entries[i]['liters']
                    km_sum += km_diff
            if km_sum > 0:
                bucket(year)['consumption'] = (liters_sum / km_sum) * 100
        return years

    # ---------- Backup / Export / Import ----------
    def create_backup(self) -> str:
        """Erstellt eine ZIP-Backupdatei im konfigurierten Zielordner."""
        target_dir = self.backup_dir
        os.makedirs(target_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = os.path.join(target_dir, f"kfz_backup_{stamp}.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for vid in self.vehicles:
                src = self._vehicle_path(vid)
                if os.path.exists(src):
                    zf.write(src, os.path.basename(src))
        self._cleanup_backups(target_dir)
        return zip_path

    def set_backup_dir(self, path: str):
        if not path:
            raise ValueError("Kein Zielordner angegeben.")
        self.backup_dir = path
        save_settings({'backup_dir': path})

    def _cleanup_backups(self, target_dir: str):
        """Behält nur die neuesten MAX_BACKUPS Backup-ZIPs im Zielordner."""
        try:
            items = [(f, os.path.getmtime(os.path.join(target_dir, f)))
                     for f in os.listdir(target_dir)
                     if f.startswith("kfz_backup_") and f.endswith(".zip")]
        except OSError:
            return
        items.sort(key=lambda x: x[1])
        while len(items) > MAX_BACKUPS:
            try:
                os.remove(os.path.join(target_dir, items.pop(0)[0]))
            except OSError:
                break

    def export_zip(self, path: str):
        if not path:
            raise ValueError("Kein Dateiname angegeben.")
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for vid in self.vehicles:
                src = self._vehicle_path(vid)
                if os.path.exists(src):
                    zf.write(src, os.path.basename(src))

    def import_zip(self, path: str):
        imported = 0
        with zipfile.ZipFile(path, 'r') as zf:
            for name in zf.namelist():
                base = os.path.basename(name)
                if not (base.startswith("fahrzeug_") and base.endswith(".json")):
                    continue
                vid = base[len("fahrzeug_"):-len(".json")]
                if vid not in self.vehicles and len(self.vehicles) >= MAX_VEHICLES:
                    raise ValueError(f"Import abgebrochen: maximal {MAX_VEHICLES} Fahrzeuge erlaubt.")
                with zf.open(name) as f:
                    self.vehicles[vid] = self._normalize(json.loads(f.read().decode('utf-8')))
                self._save(vid)
                imported += 1
        return imported


# ==================== 3. FELD-SPEZIFIKATIONEN ====================
# Typen: text | date | int | float | currency | combo | multiline
FUEL_TYPES = ["Benzin", "Diesel", "Elektro", "Hybrid", "Gas (LPG)", "Gas (CNG)"]
TRANSMISSIONS = ["Manuell", "Automatik", "Stufenlos (CVT)", "Halbautomatik"]
VEHICLE_TYPES = ["Pkw", "Kombi", "Limousine", "SUV", "Van", "Motorrad", "Sonstiges"]

MODULE_SPECS: Dict[str, Dict[str, Any]] = {
    'tuv_hu': {
        'title': "Hauptuntersuchung",
        'fields': [
            ('date', 'Datum', 'date'),
            ('next_date', 'Nächster Termin', 'date'),
            ('result', 'Ergebnis', 'text'),
            ('cost', 'Kosten', 'currency'),
            ('notes', 'Notizen', 'multiline'),
        ],
    },
    'repairs': {
        'title': "Service",
        'fields': [
            ('type', 'Art / Beschreibung', 'text'),
            ('date', 'Datum', 'date'),
            ('mileage', 'km-Stand', 'int'),
            ('cost', 'Kosten', 'currency'),
            ('workshop', 'durchgeführte Arbeiten', 'multiline'),
        ],
    },
    'maintenance': {
        'title': "Wartung",
        'fields': [
            ('date', 'Datum', 'date'),
            ('odometer', 'Stand km / Milen', 'int'),
            ('coolant_level', 'Stand Kühlflüssigkeit', 'text'),
            ('engine_oil', 'Ölstand Motor', 'text'),
            ('gear_oil', 'Ölstand Getriebe', 'text'),
            ('servo_oil', 'Ölstand Servopumpe', 'text'),
            ('battery_voltage', 'Batteriespannung', 'text'),
            ('pressure_front_left', 'Luftdruck VL', 'text'),
            ('pressure_rear_left', 'Luftdruck HL', 'text'),
            ('pressure_front_right', 'Luftdruck VR', 'text'),
            ('pressure_rear_right', 'Luftdruck HR', 'text'),
            ('notes', 'Weitere Maßnahmen / Bemerkungen', 'multiline'),
        ],
    },
    'tires': {
        'title': "Reifen",
        'fields': [
            ('type', 'Art (Sommer/Winter/Ganzjahr)', 'text'),
            ('brand', 'Marke', 'text'),
            ('size', 'Größe', 'text'),
            ('mount_date', 'Montagedatum', 'date'),
            ('mileage', 'km-Stand bei Montage', 'int'),
            ('cost', 'Kosten', 'currency'),
        ],
    },
    'insurances': {
        'title': "Versicherung / Kfz-Steuer",
        'fields': [
            ('type', 'Beschreibung', 'text'),
            ('company', 'Versicherer', 'text'),
            ('contract_number', 'Vertragsnummer', 'text'),
            ('start_date', 'Beginn', 'date'),
            ('end_date', 'Ende', 'date'),
            ('annual_cost', 'Jahresbeitrag', 'currency'),
        ],
    },
    'fuel_entries': {
        'title': "Tankbuch",
        'fields': [
            ('date', 'Datum', 'date'),
            ('odometer', 'km-Stand', 'int'),
            ('liters', 'Menge (Liter)', 'float'),
            ('cost', 'Kosten', 'currency'),
            ('station', 'Tankstelle', 'text'),
        ],
    },
    'trip_log': {
        'title': "Fahrtenbuch",
        'fields': [
            ('date', 'Datum', 'date'),
            ('occasion', 'Anlass', 'text'),
            ('odometer_from', 'Stand km / Milen von', 'int'),
            ('odometer_to', 'Stand km / Milen bis', 'int'),
            ('driven_miles', 'gefahrene Milen', 'float'),
            ('driven_km', 'gefahrene km', 'float'),
            ('route', 'Fahrtstrecke', 'multiline'),
        ],
    },
    'documents': {
        'title': "Dokumente",
        'fields': [
            ('type', 'Typ', 'text'),
            ('title', 'Titel', 'text'),
            ('file_path', 'Dateipfad', 'text'),
            ('date', 'Datum', 'date'),
        ],
    },
}

MODULE_ORDER = ['dashboard', 'fahrzeuge', 'tuv_hu', 'repairs',
                'maintenance', 'tires', 'insurances', 'fuel_entries', 'trip_log',
                'documents', 'reports', 'backup', 'info']
MODULE_LABELS = {
    'dashboard': "Dashboard", 'fahrzeuge': "Fahrzeugdaten", 'tuv_hu': "Hauptuntersuchung",
    'repairs': "Service", 'maintenance': "Wartung",
    'tires': "Reifen",
    'insurances': "Versicherung / Kfz-Steuer", 'fuel_entries': "Tankbuch",
    'trip_log': "Fahrtenbuch",
    'documents': "Dokumente", 'reports': "Auswertungen", 'backup': "Backup",
    'info': "Info",
}


def format_field(value, ftype: str) -> str:
    if ftype == 'date':
        return format_date(value)
    if ftype == 'currency':
        return format_currency(value)
    if ftype == 'int':
        return format_int(value)
    if ftype == 'float':
        return format_number(value, 2)
    return str(value or '')


# ==================== 4. GENERISCHER EINTRAGS-DIALOG ====================
def get_mile_factor(vid: str) -> float:
    """Gespeicherter Meilen-Faktor eines Fahrzeugs (km je Meile, Std. 1,37)."""
    try:
        return float(load_settings().get(f'mile_factor_{vid}', 1.37) or 1.37)
    except (TypeError, ValueError):
        return 1.37


# Felder, die NICHT im Erfassungs-/Bearbeitungsdialog erscheinen,
# aber in der Tabelle sichtbar bleiben (z. B. automatisch berechnete Werte)
DIALOG_HIDDEN_FIELDS = {('trip_log', 'driven_miles'), ('trip_log', 'driven_km')}

class EntryDialog:
    """Baut aus einer Modul-Feldspezifikation automatisch ein Formular."""

    def __init__(self, parent, store: DataStore, vid: str, key: str, entry: Optional[Dict] = None):
        spec = MODULE_SPECS[key]
        self.entry = entry or {}
        self.vid = vid
        self.key = key
        self.is_new = entry is None
        title = f"{spec['title']} – {'Neuer Eintrag' if self.is_new else 'Eintrag bearbeiten'}"

        self.dialog = Gtk.Dialog(title=title, transient_for=parent, modal=True)
        self.dialog.add_buttons("Abbrechen", Gtk.ResponseType.CANCEL,
                                "Speichern", Gtk.ResponseType.OK)
        self.dialog.set_default_size(450, -1)
        box = self.dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)

        self.widgets: Dict[str, Any] = {}
        grid = Gtk.Grid(row_spacing=8, column_spacing=10)
        # Automatisch berechnete Felder nicht im Dialog abfragen
        dialog_fields = [f for f in spec['fields']
                         if (key, f[0]) not in DIALOG_HIDDEN_FIELDS]
        for row, (fname, label, ftype) in enumerate(dialog_fields):
            grid.attach(Gtk.Label(label=label, halign=Gtk.Align.END), 0, row, 1, 1)
            widget = self._make_widget(fname, ftype)
            grid.attach(widget, 1, row, 1, 1)
        box.pack_start(grid, False, False, 0)
        # Tankbuch/Fahrtenbuch: optionale Umrechnung des Stands von Milen
        self.odometer_miles_check = None
        if key in ('fuel_entries', 'trip_log'):
            self.odometer_miles_check = Gtk.CheckButton(
                label="Angabe in Milen (wird automatisch in km umgerechnet)")
            if self.entry.get('odometer_in_miles'):
                self.odometer_miles_check.set_active(True)
                # Tankbuch: gespeicherten km-Wert zurück in Milen anzeigen
                if key == 'fuel_entries':
                    factor = get_mile_factor(vid)
                    widget = self.widgets['odometer'][0]
                    try:
                        km = float(self.entry.get('odometer') or 0)
                        if km and factor > 0:
                            widget.set_text(format_number(km / factor, 0))
                    except (TypeError, ValueError, ZeroDivisionError):
                        pass
            box.pack_start(self.odometer_miles_check, False, False, 0)
        box.show_all()
        self.dialog.connect("response", self._on_response, parent, store, vid, key)

    def _make_widget(self, fname: str, ftype: str):
        if ftype == 'multiline':
            w = Gtk.TextView()
            w.set_wrap_mode(Gtk.WrapMode.WORD)
            # Mindestens 10 Zeilen Platz für längeren Text;
            # wächst mit auf die volle Dialogbreite
            w.set_size_request(500, 220)
            w.set_hexpand(True)
        else:
            w = Gtk.Entry()
            if ftype == 'date':
                w.set_placeholder_text("TT.MM.JJJJ")
                if not self.entry.get(fname):
                    w.set_text(datetime.now().strftime("%d.%m.%Y"))
        self.widgets[fname] = (w, ftype)
        value = self.entry.get(fname)
        if value is not None:
            if ftype == 'multiline':
                w.get_buffer().set_text(str(value))
            else:
                w.set_text(format_field(value, ftype) if ftype in ('date',) else str(value or ''))
        return w

    def _collect(self) -> Dict:
        result = {}
        for fname, (widget, ftype) in self.widgets.items():
            if ftype == 'multiline':
                buf = widget.get_buffer()
                result[fname] = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
            else:
                raw = widget.get_text().strip()
                if ftype == 'date':
                    result[fname] = parse_date(raw)
                elif ftype == 'int':
                    result[fname] = parse_int(raw) if raw else 0
                elif ftype in ('float', 'currency'):
                    result[fname] = round(parse_float(raw), 2) if raw else 0.0
                else:
                    result[fname] = raw
        # Tankbuch/Fahrtenbuch: Milen-Eingabe berücksichtigen
        if self.odometer_miles_check is not None:
            in_miles = self.odometer_miles_check.get_active()
            factor = get_mile_factor(self.vid)
            result['odometer_in_miles'] = in_miles
            # Tankbuch: Stand nach km umrechnen
            if 'odometer' in result and in_miles:
                try:
                    miles = parse_float(str(result.get('odometer') or 0))
                except (TypeError, ValueError):
                    miles = 0.0
                result['odometer'] = int(round(miles * factor))
            # Fahrtenbuch: gefahrene Milen/km aus der Differenz von/bis
            if self.key == 'trip_log':
                try:
                    diff = parse_float(str(result.get('odometer_to') or 0)) \
                         - parse_float(str(result.get('odometer_from') or 0))
                except (TypeError, ValueError):
                    diff = 0.0
                if diff > 0:
                    if in_miles:
                        # Milen angegeben: Milen direkt, km über den Faktor
                        result['driven_miles'] = round(diff, 1)
                        result['driven_km'] = round(diff * factor, 1)
                    else:
                        # km angegeben: nur km berechnen, keine Milen-Umrechnung
                        result['driven_km'] = round(diff, 1)
        # Preis pro Liter automatisch berechnen (Tankbuch)
        if 'liters' in result and 'cost' in result and result.get('liters'):
            result['price_per_liter'] = round(result['cost'] / result['liters'], 3)
        return result

    def _on_response(self, dialog, response, parent, store, vid, key):
        if response != Gtk.ResponseType.OK:
            dialog.destroy()
            return
        try:
            data = self._collect()
            if self.is_new:
                store.add_entry(vid, key, data)
            else:
                store.update_entry(vid, key, self.entry['id'], data)
            dialog.destroy()
        except ValueError as e:
            self._show_error(parent, str(e))

    def _show_error(self, parent, msg):
        d = Gtk.MessageDialog(transient_for=self.dialog, modal=True,
                              message_type=Gtk.MessageType.ERROR,
                              buttons=Gtk.ButtonsType.OK, text="Eingabefehler")
        d.format_secondary_text(msg)
        d.run()
        d.destroy()

    def run(self):
        return self.dialog.run()


# ==================== 5. FAHRZEUG-DIALOG ====================
class VehicleDialog:
    def __init__(self, parent, store: DataStore, vid: Optional[str] = None, on_save=None):
        self.store = store
        self.vid = vid
        self.on_save = on_save
        title = "Fahrzeug bearbeiten" if vid else "Neues Fahrzeug"
        self.dialog = Gtk.Dialog(title=title, transient_for=parent, modal=True)
        self.dialog.add_buttons("Abbrechen", Gtk.ResponseType.CANCEL,
                                "Speichern", Gtk.ResponseType.OK)
        self.dialog.set_default_size(700, 500)
        self.entries: Dict[str, Gtk.Entry] = {}
        self.tech_entries: Dict[str, Gtk.Entry] = {}
        self._build_ui()
        if vid:
            self._fill_form(store.get_vehicle(vid))
        self.dialog.connect("response", self._on_response, parent)

    def _build_ui(self):
        notebook = Gtk.Notebook()
        notebook.set_border_width(10)
        self.dialog.get_content_area().pack_start(notebook, True, True, 0)

        # --- Tab: Grunddaten ---
        grid = Gtk.Grid(row_spacing=8, column_spacing=10)
        grid.set_border_width(10)
        basic_rows = [
            ("Herstellermarke *", 'make'), ("Modell *", 'model'),
            ("Kennzeichen", 'license_plate'), ("Fahrgestellnummer (VIN)", 'vin'),
            ("Erstzulassung", 'first_registration'), ("Farbe", 'color'),
            ("Leistung (PS)", 'power'),
        ]
        for row, (label, name) in enumerate(basic_rows):
            grid.attach(Gtk.Label(label=label, halign=Gtk.Align.END), 0, row, 1, 1)
            e = Gtk.Entry()
            if name == 'first_registration':
                e.set_placeholder_text("TT.MM.JJJJ")
            self.entries[name] = e
            grid.attach(e, 1, row, 1, 1)

        self.combos: Dict[str, Gtk.ComboBoxText] = {}
        combo_specs = [('fuel_type', "Kraftstoffart", FUEL_TYPES),
                       ('transmission', "Getriebe", TRANSMISSIONS),
                       ('vehicle_type', "Fahrzeugtyp", VEHICLE_TYPES)]
        for i, (name, label, options) in enumerate(combo_specs):
            row = len(basic_rows) + i
            grid.attach(Gtk.Label(label=label, halign=Gtk.Align.END), 0, row, 1, 1)
            c = Gtk.ComboBoxText()
            for opt in options:
                c.append_text(opt)
            c.set_active(0)
            self.combos[name] = c
            grid.attach(c, 1, row, 1, 1)

        scroll1 = Gtk.ScrolledWindow()
        scroll1.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll1.add(grid)
        notebook.append_page(scroll1, Gtk.Label(label="Grunddaten"))

        # --- Tab: Technische Daten ---
        grid2 = Gtk.Grid(row_spacing=8, column_spacing=10)
        grid2.set_border_width(10)
        tech_rows = [
            ("Hubraum (cm³)", 'engine_capacity'), ("Leergewicht (kg)", 'empty_weight'),
            ("Zul. Gesamtgewicht (kg)", 'max_weight'), ("Sitzplätze", 'seats'),
            ("Türen", 'doors'), ("Länge (mm)", 'length'),
            ("Breite (mm)", 'width'), ("Höhe (mm)", 'height'),
        ]
        for row, (label, name) in enumerate(tech_rows):
            grid2.attach(Gtk.Label(label=label, halign=Gtk.Align.END), 0, row, 1, 1)
            e = Gtk.Entry()
            self.tech_entries[name] = e
            grid2.attach(e, 1, row, 1, 1)
        grid2.attach(Gtk.Label(label="Notizen", halign=Gtk.Align.END,
                               valign=Gtk.Align.START), 0, len(tech_rows), 1, 1)
        self.notes_view = Gtk.TextView()
        self.notes_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.notes_view.set_size_request(-1, 100)
        grid2.attach(self.notes_view, 1, len(tech_rows), 1, 1)

        scroll2 = Gtk.ScrolledWindow()
        scroll2.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll2.add(grid2)
        notebook.append_page(scroll2, Gtk.Label(label="Technische Daten"))

        note = Gtk.Label(label="* Pflichtfelder (Hersteller und Modell)")
        note.set_halign(Gtk.Align.START)
        note.get_style_context().add_class("dim-label")
        self.dialog.get_content_area().pack_start(note, False, False, 6)
        self.dialog.get_content_area().show_all()

    def _fill_form(self, vehicle: Optional[Dict]):
        if not vehicle:
            return
        basic, tech = vehicle.get('basic', {}), vehicle.get('technical', {})
        for name, e in self.entries.items():
            value = basic.get(name, '')
            value = '' if value is None else value
            try:
                e.set_text(format_date(value) if name == 'first_registration' else str(value))
            except Exception:
                e.set_text('')
        for name, combo in self.combos.items():
            value = basic.get(name) or ''
            # Wert nur setzen, wenn er in der Liste enthalten ist
            if value:
                combo_set_active_text(combo, str(value))
            if combo.get_active() == -1:
                combo.set_active(0)
        for name, e in self.tech_entries.items():
            value = tech.get(name, '')
            value = '' if value is None else value
            try:
                e.set_text(str(value))
            except Exception:
                e.set_text('')
        self.notes_view.get_buffer().set_text(str(tech.get('notes') or ''))

    def _collect(self, old: Optional[Dict]) -> Dict:
        basic = {name: e.get_text().strip() for name, e in self.entries.items()}
        basic['license_plate'] = basic['license_plate'].upper()
        basic['vin'] = basic['vin'].upper()
        if basic['first_registration']:
            basic['first_registration'] = parse_date(basic['first_registration'])
        for name, combo in self.combos.items():
            basic[name] = combo.get_active_text() or ''
        tech = {name: e.get_text().strip() for name, e in self.tech_entries.items()}
        buf = self.notes_view.get_buffer()
        tech['notes'] = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
        data = {'basic': basic, 'technical': tech}
        # Bestehende Einträge (Tankbuch etc.) unverändert übernehmen!
        if old:
            for key in LIST_KEYS:
                data[key] = old.get(key, [])
        return data

    def _on_response(self, dialog, response, parent):
        if response != Gtk.ResponseType.OK:
            dialog.destroy()
            return
        try:
            if not self.entries['make'].get_text().strip() or not self.entries['model'].get_text().strip():
                raise ValueError("Hersteller und Modell sind Pflichtfelder.")
            old = self.store.get_vehicle(self.vid) if self.vid else None
            data = self._collect(old)
            if self.vid:
                self.store.update_vehicle(self.vid, data)
            else:
                self.vid = self.store.add_vehicle(data)
            if self.on_save:
                self.on_save(self.vid)
            dialog.destroy()
        except Exception as e:
            # Auch unerwartete Fehler (nicht nur ValueError) anzeigen,
            # damit nichts stumm scheitert und der Dialog offen bleibt.
            import traceback
            traceback.print_exc()
            d = Gtk.MessageDialog(transient_for=self.dialog, modal=True,
                                  message_type=Gtk.MessageType.ERROR,
                                  buttons=Gtk.ButtonsType.OK, text="Speichern fehlgeschlagen")
            d.format_secondary_text(str(e))
            d.run()
            d.destroy()

    def run(self):
        return self.dialog.run()


# ==================== 6. HAUPTFENSTER ====================
class MainWindow(Gtk.Window):
    def __init__(self, store: DataStore):
        super().__init__(title=f"Kfz-Verwaltung {APP_VERSION}")
        self.store = store
        # Einstellbare Distanz für die Verbrauchs-Hochrechnung (Auswertungen)
        self.refuel_distance = load_settings().get('refuel_km', 130)
        self.current_vehicle_id: Optional[str] = None
        self.current_module = 'dashboard'
        # Fenstergröße dauerhaft merken (letzte eingestellte Größe behalten)
        self._win_geometry = {
            'width': int(load_settings().get('win_width', 1200)),
            'height': int(load_settings().get('win_height', 800)),
            'maximized': bool(load_settings().get('win_maximized', False)),
        }
        self.set_default_size(self._win_geometry['width'], self._win_geometry['height'])
        self.connect("configure-event", self._on_window_configure)
        self.connect("window-state-event", self._on_window_state)
        self._apply_css()
        self._build_ui()
        if self._win_geometry['maximized']:
            self.maximize()

    # ---------- Fenstergröße dauerhaft merken ----------
    def _on_window_state(self, win, event):
        self._win_geometry['maximized'] = bool(
            event.new_window_state & Gdk.WindowState.MAXIMIZED)
        return False

    def _on_window_configure(self, win, _event):
        """Jede Größenänderung direkt speichern (nur bei tatsächlicher Änderung)."""
        g = self._win_geometry
        g['width'], g['height'] = win.get_size()
        geom = (g['width'], g['height'])
        if geom != getattr(self, '_last_saved_geom', None):
            self._last_saved_geom = geom
            settings = load_settings()
            settings['win_width'] = g['width']
            settings['win_height'] = g['height']
            settings['win_maximized'] = g['maximized']
            save_settings(settings)
        return False

    # ---------- CSS ----------
    def _apply_css(self):
        css = b"""
        #sidebar { background-color: #2c3e50; }
        #sidebar button { background: transparent; color: #ffffff; border: none;
                          padding: 12px 20px; font-size: 14px;
                          border-left: 3px solid transparent; outline: none; }
        #sidebar button:hover { background-color: #34495e; }
        #sidebar button:checked { background-color: #3498db; border-left-color: #ffffff; }
        #sidebar label { color: #ffffff; font-weight: bold; }
        #sidebar #quit-btn { background-color: #c0392b; background-image: none;
                             border: none; border-radius: 4px; }
        #sidebar #quit-btn:hover { background-color: #e74c3c; }
        #sidebar #quit-btn label { color: #ffffff; font-weight: bold; }
        #header { background-color: #ffffff; border-bottom: 1px solid #dcdcdc; }
        .card { background-color: #ffffff; border: 1px solid #e0e0e0;
                border-radius: 8px; padding: 14px; }
        .stat-value { font-size: 22px; font-weight: bold; color: #3498db; }
        .stat-label { color: #7f8c8d; }
        .dim-label { color: #888888; font-size: 12px; }
        .header-btn { background-color: #3498db; background-image: none; border: none;
                      border-radius: 4px; }
        .header-btn:hover { background-color: #5dade2; }
        .header-btn label { color: #ffffff; font-weight: bold; }
        #yes-btn { background-color: #3498db; background-image: none; border: none;
                   border-radius: 4px; }
        #yes-btn:hover { background-color: #5dade2; }
        #yes-btn label { color: #ffffff; font-weight: bold; }
        treeview row:nth-child(even) { background-color: #f4f7f9; }
        .backup-btn { background-color: #3498db; background-image: none; border: none;
                      border-radius: 4px; }
        .backup-btn:hover { background-color: #2e86c1; }
        .backup-btn label { color: #ffffff; font-weight: bold; }
        """
        try:
            provider = Gtk.CssProvider()
            provider.load_from_data(css)
            screen = Gdk.Screen.get_default()
            if screen is not None:
                Gtk.StyleContext.add_provider_for_screen(
                    screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        except Exception:
            pass  # CSS ist kosmetisch – App läuft auch ohne

    # ---------- UI-Aufbau ----------
    def _build_ui(self):
        main = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.add(main)

        # Sidebar
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar.set_name("sidebar")
        sidebar.set_size_request(190, -1)
        logo = Gtk.Label(label="Kfz-Verwaltung")
        logo.set_margin_top(14)
        logo.set_margin_bottom(2)
        sidebar.pack_start(logo, False, False, 0)
        version = Gtk.Label(label=f"Version {APP_VERSION}")
        version.get_style_context().add_class("dim-label")
        version.set_margin_bottom(14)
        sidebar.pack_start(version, False, False, 0)
        first = None
        for mid in MODULE_ORDER:
            btn = (Gtk.RadioButton.new_with_label_from_widget(first, MODULE_LABELS[mid])
                   if first else Gtk.RadioButton.new_with_label(None, MODULE_LABELS[mid]))
            if first is None:
                first = btn
            btn.set_mode(False)
            btn.connect("toggled", self._on_module_toggled, mid)
            sidebar.pack_start(btn, False, False, 0)

        # Beenden-Schaltfläche unten links (rot)
        quit_btn = Gtk.Button.new_with_label("Beenden")
        quit_btn.set_name("quit-btn")
        quit_btn.set_margin_start(10)
        quit_btn.set_margin_end(10)
        quit_btn.set_margin_bottom(10)
        quit_btn.connect("clicked", self._on_quit)
        sidebar.pack_end(quit_btn, False, False, 0)
        main.pack_start(sidebar, False, False, 0)

        # Rechter Bereich
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main.pack_start(right, True, True, 0)

        # Kopfzeile
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.set_name("header")
        header.set_size_request(-1, 52)
        self.vehicle_combo = Gtk.ComboBoxText()
        self.vehicle_combo.set_margin_start(12)
        self.vehicle_combo.set_size_request(260, -1)
        self._combo_handler = self.vehicle_combo.connect("changed", self._on_vehicle_changed)
        header.pack_start(self.vehicle_combo, False, False, 0)

        for label, cb in [("Neues Fahrzeug", self._on_new_vehicle),
                          ("Bearbeiten", self._on_edit_vehicle),
                          ("Löschen", self._on_delete_vehicle)]:
            b = Gtk.Button.new_with_label(label)
            b.get_style_context().add_class("header-btn")
            b.set_margin_end(4)
            b.connect("clicked", cb)
            header.pack_start(b, False, False, 0)

        # Leerzeile über der Kopfzeile (Fahrzeugwahl + Schaltflächen)
        right.pack_start(Gtk.Label(label=""), False, False, 0)
        right.pack_start(header, False, False, 0)

        # Modul-Stack
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        right.pack_start(self.stack, True, True, 0)

        self._build_dashboard_page()
        self._build_vehicle_page()
        self._build_module_pages()
        self._build_reports_page()
        self._build_backup_page()
        self._build_info_page()

        self._refresh_vehicle_combo()
        self.show_all()
        self._show_module('dashboard')
        self.connect("destroy", self._on_destroy)

    # ---------- Dashboard ----------
    def _build_dashboard_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        page.set_margin_start(20); page.set_margin_end(20)
        page.set_margin_top(20); page.set_margin_bottom(20)

        self.dash_title = Gtk.Label()
        self.dash_title.set_halign(Gtk.Align.START)
        page.pack_start(self.dash_title, False, False, 0)

        cards = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        page.pack_start(cards, False, False, 0)
        self.dash_cards = {}
        for key, label in [('costs', "Gesamtkosten (aktuelles Fahrzeug)"),
                           ('consumption', "Ø Verbrauch (aktuelles Fahrzeug)"),
                           ('tuv', "Nächste HU (aktuelles Fahrzeug)")]:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            card.get_style_context().add_class("card")
            l1 = Gtk.Label(label=label)
            l1.set_halign(Gtk.Align.START)
            l1.get_style_context().add_class("stat-label")
            l2 = Gtk.Label(label="–")
            l2.set_halign(Gtk.Align.START)
            l2.get_style_context().add_class("stat-value")
            card.pack_start(l1, False, False, 0)
            card.pack_start(l2, False, False, 0)
            self.dash_cards[key] = l2
            cards.pack_start(card, True, True, 0)

        # Jährliche Auswertung (kompakt) für das aktuelle Fahrzeug
        yearly_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        yearly_card.get_style_context().add_class("card")
        yearly_title = Gtk.Label(label="<b>Kosten je Jahr (aktuelles Fahrzeug)</b>",
                                 use_markup=True)
        yearly_title.set_halign(Gtk.Align.START)
        yearly_card.pack_start(yearly_title, False, False, 0)
        self.dash_yearly_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        yearly_card.pack_start(self.dash_yearly_box, False, False, 0)
        page.pack_start(yearly_card, False, False, 0)

        # Fahrzeugbestand (in einer Box wie "Kosten je Jahr (aktuelles Fahrzeug)")
        stock_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        stock_card.get_style_context().add_class("card")
        stock_title = Gtk.Label(label="<b>Fahrzeugbestand</b>", use_markup=True)
        stock_title.set_halign(Gtk.Align.START)
        stock_card.pack_start(stock_title, False, False, 0)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.set_min_content_height(300)
        self.dash_list = Gtk.ListBox()
        sw.add(self.dash_list)
        stock_card.pack_start(sw, True, True, 0)
        page.pack_start(stock_card, True, True, 0)
        self.stack.add_named(page, 'dashboard')

    def _build_vehicle_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page.set_margin_start(20); page.set_margin_end(20)
        page.set_margin_top(20); page.set_margin_bottom(20)
        self.vehicle_detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.add(self.vehicle_detail_box)
        page.pack_start(sw, True, True, 0)
        self.stack.add_named(page, 'fahrzeuge')

    # ---------- Generische Modulseiten ----------
    def _build_module_pages(self):
        self.module_treeviews: Dict[str, Gtk.TreeView] = {}
        for key, spec in MODULE_SPECS.items():
            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            page.set_margin_start(20); page.set_margin_end(20)
            page.set_margin_top(20); page.set_margin_bottom(20)

            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            head.pack_start(Gtk.Label(label=f"<b>{spec['title']}</b>", use_markup=True),
                            False, False, 0)
            edit_btn = Gtk.Button.new_with_label("Bearbeiten")
            edit_btn.connect("clicked", self._on_edit_selected_entry, key)
            head.pack_start(edit_btn, False, False, 0)
            del_btn = Gtk.Button.new_with_label("Löschen")
            del_btn.connect("clicked", self._on_delete_selected_entry, key)
            head.pack_start(del_btn, False, False, 0)
            # Tankbuch: Ø Verbrauch (Milen und km) über der Tabelle anzeigen
            if key == 'fuel_entries':
                self.fuel_summary_label = Gtk.Label(label="")
                self.fuel_summary_label.get_style_context().add_class("dim-label")
                head.pack_start(self.fuel_summary_label, False, False, 0)
            add_btn = Gtk.Button.new_with_label("Neuer Eintrag")
            add_btn.connect("clicked", self._on_add_entry, key)
            head.pack_end(add_btn, False, False, 0)
            page.pack_start(head, False, False, 0)

            sw = Gtk.ScrolledWindow()
            sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            tree = self._build_module_treeview(key)
            self.module_treeviews[key] = tree
            sw.add(tree)
            page.pack_start(sw, True, True, 0)
            self.stack.add_named(page, key)

    def _build_module_treeview(self, key: str) -> Gtk.TreeView:
        """Baut aus der Modul-Spezifikation eine sortierbare Tabelle."""
        spec = MODULE_SPECS[key]
        fields = spec['fields']
        n_fields = len(fields)
        # Indizes der Datumsfelder: für diese Spalten werden versteckte
        # ISO-Datumsspalten (YYYY-MM-DD) angelegt, damit Klick auf die
        # Spaltenüberschrift chronologisch statt alphabetisch nach Tag sortiert.
        date_idx = [i for i, (_f, _l, ftype) in enumerate(fields) if ftype == 'date']
        # Berechnete Zusatzspalten fürs Tankbuch
        extra = 3 if key == 'fuel_entries' else 0
        # Store: sichtbare Felder + Zusatz + versteckte ISO-Daten + Eintrags-ID
        store = Gtk.ListStore(*([str] * (n_fields + extra + len(date_idx) + 1)))
        tree = Gtk.TreeView(model=store)
        tree.set_hexpand(True)
        tree.set_vexpand(True)
        tree.get_selection().set_mode(Gtk.SelectionMode.SINGLE)
        # Tankbuch: Spalte "Tankstelle" später hinten anhängen
        station_idx = None
        for i, (fname, label, ftype) in enumerate(fields):
            if key == 'fuel_entries' and fname == 'station':
                station_idx = i
                continue
            renderer = Gtk.CellRendererText()
            col = Gtk.TreeViewColumn(label, renderer, text=i)
            col.set_resizable(True)
            col.set_clickable(True)
            # Datumsspalten sortieren nach versteckter ISO-Spalte
            col.set_sort_column_id(n_fields + extra + date_idx.index(i) if ftype == 'date' else i)
            col.set_min_width(70)
            # Mehrzeilige/lange Textspalten (z. B. "durchgeführte Arbeiten")
            # erhalten den restlichen Platz und lassen sich breiter ziehen
            if ftype == 'multiline':
                col.set_expand(True)
                col.set_min_width(200)
            tree.append_column(col)
        # Zusatzspalten Tankbuch: Ø Verbrauch, gefahrene km, Ø €/Liter
        if key == 'fuel_entries':
            for j, title in enumerate(["Ø l/100km", "gefahrene km", "Ø €/Liter"]):
                renderer = Gtk.CellRendererText()
                col = Gtk.TreeViewColumn(title, renderer, text=n_fields + j)
                col.set_resizable(True)
                col.set_clickable(True)
                col.set_sort_column_id(n_fields + j)
                col.set_min_width(90)
                tree.append_column(col)
        # Tankbuch: Spalte "Tankstelle" zum Schluss (hinter "Ø €/Liter")
        if key == 'fuel_entries' and station_idx is not None:
            renderer = Gtk.CellRendererText()
            col = Gtk.TreeViewColumn("Tankstelle", renderer, text=station_idx)
            col.set_resizable(True)
            col.set_clickable(True)
            col.set_sort_column_id(station_idx)
            col.set_min_width(90)
            tree.append_column(col)
        # Doppelklick auf eine Zeile öffnet den Bearbeiten-Dialog
        # (Ausnahme Dokumente: dort öffnet der Klick auf den Pfad das Verzeichnis)
        tree.connect("row-activated", self._on_row_activated, key)
        if key == 'documents':
            # Klick auf die Spalte "Dateipfad" öffnet das Verzeichnis im Dateimanager
            tree.connect("button-press-event", self._on_documents_button_press)
        return tree

    # ---------- Auswertungen ----------
    def _build_reports_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page.set_margin_start(20); page.set_margin_end(20)
        page.set_margin_top(20); page.set_margin_bottom(20)
        self.reports_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.add(self.reports_box)
        page.pack_start(sw, True, True, 0)
        self.stack.add_named(page, 'reports')

    # ---------- Backup ----------
    def _build_backup_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page.set_margin_start(20); page.set_margin_end(20)
        page.set_margin_top(20); page.set_margin_bottom(20)
        page.pack_start(Gtk.Label(label=""), False, False, 0)
        page.pack_start(Gtk.Label(label="<b>Backup &amp; Import / Export</b>", use_markup=True),
                        False, False, 0)
        page.pack_start(Gtk.Label(label=""), False, False, 0)
        page.pack_start(Gtk.Label(label=""), False, False, 0)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        btn_row.set_halign(Gtk.Align.CENTER)
        page.pack_start(btn_row, False, False, 0)
        for label, cb in [("Backup", self._on_backup),
                          ("Export ZIP", self._on_export),
                          ("Import ZIP", self._on_import)]:
            b = Gtk.Button.new_with_label(label)
            b.get_style_context().add_class("backup-btn")
            b.connect("clicked", cb)
            btn_row.pack_start(b, False, False, 0)

        # Zwei Zeilen Abstand, dann Zielordner-Anzeige
        page.pack_start(Gtk.Label(label=""), False, False, 0)
        page.pack_start(Gtk.Label(label=""), False, False, 0)

        # Zielordner für Backups (Standard: Skriptordner)
        dir_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.backup_dir_label = Gtk.Label(label=self.store.backup_dir)
        self.backup_dir_label.set_halign(Gtk.Align.START)
        self.backup_dir_label.get_style_context().add_class("dim-label")
        dir_box.pack_start(self.backup_dir_label, False, False, 0)
        change_dir_btn = Gtk.Button.new_with_label("Zielordner ändern …")
        change_dir_btn.connect("clicked", self._on_change_backup_dir)
        dir_box.pack_start(change_dir_btn, False, False, 0)
        page.pack_start(dir_box, False, False, 0)
        self.backup_status = Gtk.Label(label="")
        self.backup_status.get_style_context().add_class("dim-label")
        page.pack_start(self.backup_status, False, False, 0)
        self.stack.add_named(page, 'backup')

    # ---------- Info-Seite ----------
    def _build_info_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page.set_margin_start(20); page.set_margin_end(20)
        page.set_margin_top(20); page.set_margin_bottom(20)

        page.pack_start(Gtk.Label(label=""), False, False, 0)
        page.pack_start(Gtk.Label(label="<b>Info – Wo liegen die Daten?</b>", use_markup=True),
                        False, False, 0)

        def make_card(title: str, lines: List[str]) -> Gtk.Widget:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            card.get_style_context().add_class("card")
            card.pack_start(Gtk.Label(label=f"<b>{title}</b>", use_markup=True,
                                      halign=Gtk.Align.START), False, False, 0)
            for line in lines:
                l = Gtk.Label(label=line)
                l.set_halign(Gtk.Align.START)
                l.set_line_wrap(True)
                card.pack_start(l, False, False, 0)
            return card

        page.pack_start(make_card("Fahrzeugdaten", [
            f"Alle Fahrzeugdaten werden als einzelne JSON-Dateien pro Fahrzeug im "
            f"Home-Verzeichnis gespeichert:",
            f"    {DATA_DIR}",
            "Dort liegen die Dateien fahrzeug_1.json, fahrzeug_2.json … – je eine "
            "pro Fahrzeug mit sämtlichen Stammdaten und Einträgen (Tankbuch, HU, "
            "Reparaturen, Kosten usw.).",
            "Gespeichert wird automatisch bei jeder Änderung; das Verzeichnis wird "
            "beim Programmstart angelegt, falls es fehlt.",
        ]), False, False, 0)

        page.pack_start(make_card("Einstellungen", [
            f"Die Programmeinstellungen (z. B. der gewählte Backup-Zielordner) "
            f"liegen in der Datei:",
            f"    {SETTINGS_FILE}",
        ]), False, False, 0)

        page.pack_start(make_card("Backups und Export", [
            f"Backup-ZIPs (kfz_backup_JJJJMMTT_HHMMSS.zip) werden im aktuell "
            f"eingestellten Zielordner abgelegt, standardmäßig im Ordner der "
            f"Skriptdatei:",
            f"    {self.store.backup_dir}",
            "Im Modul „Backup“ lässt sich dieser Zielordner über „Zielordner "
            "ändern …“ jederzeit anpassen. Es werden maximal 10 Backups "
            "behalten, die ältesten werden automatisch gelöscht.",
            "Der Datenexport („Export ZIP“) schreibt die Fahrzeugdateien "
            "zusätzlich in eine frei wählbare ZIP-Datei; über „Import ZIP“ "
            "lassen sich diese wieder einlesen.",
        ]), False, False, 0)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for child in page.get_children():
            page.remove(child)
            inner.pack_start(child, False, False, 0)
        sw.add(inner)
        page.pack_start(sw, True, True, 0)
        self.stack.add_named(page, 'info')

    # ---------- Navigation ----------
    def _on_module_toggled(self, btn, module_id):
        if btn.get_active():
            self._show_module(module_id)

    def _show_module(self, module_id: str):
        self.current_module = module_id
        self.stack.set_visible_child_name(module_id)
        self._update_module()

    def _update_module(self):
        mid = self.current_module
        if mid == 'dashboard':
            self._update_dashboard()
        elif mid == 'fahrzeuge':
            self._update_vehicle_details()
        elif mid == 'reports':
            self._update_reports()
        elif mid == 'backup':
            pass
        elif mid == 'info':
            pass
        elif mid in MODULE_SPECS:
            self._update_module_list(mid)

    # ---------- Fahrzeugauswahl ----------
    def _refresh_vehicle_combo(self):
        self.vehicle_combo.handler_block(self._combo_handler)
        try:
            self.vehicle_combo.remove_all()
            vehicles = self.store.get_vehicle_list()
            for v in vehicles:
                self.vehicle_combo.append(v['id'], f"{v['name']} ({v['license_plate']})")
            if vehicles:
                if self.current_vehicle_id not in [v['id'] for v in vehicles]:
                    self.current_vehicle_id = vehicles[0]['id']
                self.vehicle_combo.set_active_id(self.current_vehicle_id)
            else:
                self.current_vehicle_id = None
        finally:
            self.vehicle_combo.handler_unblock(self._combo_handler)

    def _on_vehicle_changed(self, combo):
        vid = combo.get_active_id()
        if vid and vid != self.current_vehicle_id:
            self.current_vehicle_id = vid
            self._update_module()

    # ---------- Fahrzeug-Aktionen ----------
    def _on_new_vehicle(self, _btn):
        self._open_vehicle_dialog(vid=None)

    def _on_edit_vehicle(self, _btn):
        if not self.current_vehicle_id:
            self._info("Bitte zuerst ein Fahrzeug auswählen.")
            return
        self._open_vehicle_dialog(vid=self.current_vehicle_id)

    def _open_vehicle_dialog(self, vid: Optional[str]):
        """Öffnet den Fahrzeug-Dialog; jeglicher Fehler wird angezeigt."""
        try:
            VehicleDialog(self, self.store, vid=vid,
                          on_save=self._after_vehicle_saved).run()
        except Exception as e:
            import traceback
            traceback.print_exc()  # Details auf der Konsole
            self._error(f"Fehler beim Öffnen des Fahrzeug-Dialogs:\n{e}")

    def _after_vehicle_saved(self, _vid):
        self._refresh_vehicle_combo()
        self._update_module()

    def _on_delete_vehicle(self, _btn):
        if not self.current_vehicle_id:
            self._info("Bitte zuerst ein Fahrzeug auswählen.")
            return
        vehicle = self.store.get_vehicle(self.current_vehicle_id)
        if not vehicle:
            return
        b = vehicle['basic']
        name = f"{b['make']} {b['model']} ({b['license_plate']})".strip()
        d = Gtk.MessageDialog(transient_for=self, modal=True,
                              message_type=Gtk.MessageType.QUESTION,
                              buttons=Gtk.ButtonsType.YES_NO,
                              text="Fahrzeug löschen?")
        d.format_secondary_text(f"'{name}' samt aller Einträge wirklich löschen?")
        if d.run() == Gtk.ResponseType.YES:
            try:
                self.store.delete_vehicle(self.current_vehicle_id)
                self.current_vehicle_id = None
                self._refresh_vehicle_combo()
                self._update_module()
            except Exception as e:
                self._error(str(e))
        d.destroy()

    # ---------- Eintrag-Aktionen (generisch) ----------
    def _on_add_entry(self, _btn, key: str):
        if not self._require_vehicle():
            return
        EntryDialog(self, self.store, self.current_vehicle_id, key).run()
        self._update_module()

    def _on_edit_entry(self, _btn, key: str, entry: Dict):
        EntryDialog(self, self.store, self.current_vehicle_id, key, entry).run()
        self._update_module()

    def _on_delete_entry(self, _btn, key: str, entry: Dict):
        if not self._require_vehicle():
            return
        d = Gtk.MessageDialog(transient_for=self, modal=True,
                              message_type=Gtk.MessageType.QUESTION,
                              buttons=Gtk.ButtonsType.YES_NO,
                              text="Eintrag löschen?")
        d.format_secondary_text("Dieser Eintrag wird endgültig gelöscht.")
        if d.run() == Gtk.ResponseType.YES:
            try:
                self.store.delete_entry(self.current_vehicle_id, key, entry['id'])
                self._update_module()
            except Exception as e:
                self._error(str(e))
        d.destroy()

    def _require_vehicle(self) -> bool:
        if not self.current_vehicle_id:
            self._info("Bitte zuerst ein Fahrzeug anlegen bzw. auswählen.")
            return False
        return True

    # ---------- Listen-Rendering ----------
    def _clear_listbox(self, lb: Gtk.ListBox):
        for child in lb.get_children():
            lb.remove(child)

    def _placeholder_row(self, lb: Gtk.ListBox, text: str):
        row = Gtk.ListBoxRow(selectable=False, activatable=False)
        row.add(Gtk.Label(label=text, margin=12))
        lb.add(row)

    def _update_module_list(self, key: str):
        # Alle Module verwenden die Tabellenansicht
        self._update_module_table(key)

    # ---------- Tabellen-Ansicht ----------
    def _update_module_table(self, key: str):
        tree = self.module_treeviews[key]
        spec = MODULE_SPECS[key]
        store = tree.get_model()
        store.clear()
        vehicle = self.store.get_vehicle(self.current_vehicle_id) if self.current_vehicle_id else None
        if not vehicle:
            return
        entries = list(vehicle.get(key, []))
        date_field = next((f[0] for f in spec['fields'] if f[2] == 'date'), None)
        if date_field:
            entries.sort(key=lambda e: e.get(date_field) or '', reverse=True)
        else:
            entries.sort(key=lambda e: e.get('id', '0'))
        # Tankbuch: Ø Verbrauch (Milen und km) zusammenfassen
        if key == 'fuel_entries':
            if entries:
                cons_km = self.store.fuel_consumption(entries)
                cons_milen = cons_km * self._mile_factor()
                self.fuel_summary_label.set_text(
                    f"Ø Verbrauch: {format_number(cons_milen, 1)} l/100 Milen · "
                    f"{format_number(cons_km, 1)} l/100 km")
            else:
                self.fuel_summary_label.set_text("")

        # Berechnete Zusatzwerte je Tankvorgang (Tankbuch)
        fuel_stats = self._per_entry_fuel_stats(entries) if key == 'fuel_entries' else {}
        for entry in entries:
            fields = spec['fields']
            row = [format_field(entry.get(fname), ftype) for fname, _l, ftype in fields]
            if key == 'fuel_entries':
                s = fuel_stats.get(entry.get('id'), {})
                row.append(format_number(s['cons'], 2) if s.get('cons') else "–")
                row.append(format_number(s['km'], 0) if s.get('km') else "–")
                row.append(format_currency(s['price']) if s.get('price') else "–")
            # Versteckte ISO-Datumswerte für chronologisches Sortieren anhängen
            row += [str(entry.get(fname) or '') for fname, _l, ftype in fields if ftype == 'date']
            row.append(entry.get('id', ''))
            store.append(row)

    def _entry_id_index(self, key: str) -> int:
        """Spaltenindex der versteckten Eintrags-ID im Tabellen-Store."""
        fields = MODULE_SPECS[key]['fields']
        extra = 3 if key == 'fuel_entries' else 0
        return len(fields) + extra + sum(1 for _f, _l, t in fields if t == 'date')

    @staticmethod
    def _per_entry_fuel_stats(entries: List[Dict]) -> Dict[str, Dict]:
        """Je Tankvorgang: gefahrene km, Ø Verbrauch (l/100km) und Ø €/Liter.

        Chronologisch geordnet liefert der vorangehende Tankstopp den
        Referenz-km-Stand; der Preis pro Liter berechnet sich aus der
        jeweiligen Betankung selbst.
        """
        stats: Dict[str, Dict] = {}
        ordered = sorted(entries, key=lambda e: e.get('date') or '')
        for i, e in enumerate(ordered):
            try:
                liters = float(e.get('liters') or 0)
                cost = float(e.get('cost') or 0)
            except (TypeError, ValueError):
                continue
            item: Dict = {'price': (cost / liters) if liters > 0 else None,
                          'km': None, 'cons': None}
            if i >= 1:
                try:
                    prev_km = float(ordered[i - 1].get('odometer') or 0)
                    curr_km = float(e.get('odometer') or 0)
                except (TypeError, ValueError):
                    prev_km = curr_km = 0.0
                km_diff = curr_km - prev_km
                if km_diff > 0:
                    item['km'] = km_diff
                    if liters > 0:
                        item['cons'] = (liters / km_diff) * 100
            stats[e.get('id')] = item
        return stats

    def _selected_entry_id(self, key: str) -> Optional[str]:
        tree = self.module_treeviews[key]
        model, treeiter = tree.get_selection().get_selected()
        if not treeiter:
            return None
        return model[treeiter][self._entry_id_index(key)]

    def _edit_entry_by_id(self, key: str, entry_id: str):
        vehicle = self.store.get_vehicle(self.current_vehicle_id) if self.current_vehicle_id else None
        if not vehicle:
            return
        entry = next((e for e in vehicle.get(key, []) if e.get('id') == entry_id), None)
        if entry:
            EntryDialog(self, self.store, self.current_vehicle_id, key, entry).run()
            self._update_module()

    def _on_row_activated(self, _tree, path, _column, key):
        """Doppelklick auf eine Tabellenzeile -> Eintrag bearbeiten."""
        # Im Dokumente-Modul übernimmt der Klick auf den Dateipfad das Öffnen
        if key == 'documents':
            return
        entry_id = self.module_treeviews[key].get_model()[path][self._entry_id_index(key)]
        self._edit_entry_by_id(key, entry_id)

    def _on_documents_button_press(self, tree, event) -> bool:
        """Klick auf die Spalte 'Dateipfad' öffnet das Verzeichnis."""
        if event.type != Gdk.EventType.BUTTON_PRESS:
            return False
        result = tree.get_path_at_pos(int(event.x), int(event.y))
        if not result:
            return False
        path, column, _cx, _cy = result
        # Spaltenindex von 'file_path' in der Modul-Spezifikation bestimmen
        spec_fields = MODULE_SPECS['documents']['fields']
        path_col_index = next(i for i, (f, _l, _t) in enumerate(spec_fields)
                              if f == 'file_path')
        column_index = tree.get_columns().index(column)
        if column_index != path_col_index:
            return False
        entry_id = tree.get_model()[path][self._entry_id_index('documents')]
        vehicle = self.store.get_vehicle(self.current_vehicle_id) if self.current_vehicle_id else None
        if not vehicle:
            return False
        entry = next((e for e in vehicle.get('documents', []) if e.get('id') == entry_id), None)
        if not entry:
            return False
        file_path = (entry.get('file_path') or '').strip()
        if not file_path:
            self._info("In diesem Eintrag ist kein Dateipfad hinterlegt.")
            return True
        file_path = os.path.expanduser(file_path)
        if not os.path.exists(file_path):
            self._error(f"Der Pfad existiert nicht:\n{file_path}")
            return True
        target = file_path if os.path.isdir(file_path) else os.path.dirname(file_path)
        try:
            subprocess.Popen(['xdg-open', target])
        except Exception as e:
            self._error(f"Verzeichnis konnte nicht geöffnet werden: {e}")
        return True

    def _on_edit_selected_entry(self, _btn, key: str):
        if not self._require_vehicle():
            return
        entry_id = self._selected_entry_id(key)
        if not entry_id:
            self._info("Bitte zuerst einen Eintrag in der Tabelle auswählen.")
            return
        self._edit_entry_by_id(key, entry_id)

    def _on_delete_selected_entry(self, _btn, key: str):
        if not self._require_vehicle():
            return
        entry_id = self._selected_entry_id(key)
        if not entry_id:
            self._info("Bitte zuerst einen Eintrag in der Tabelle auswählen.")
            return
        d = Gtk.MessageDialog(transient_for=self, modal=True,
                              message_type=Gtk.MessageType.QUESTION,
                              buttons=Gtk.ButtonsType.YES_NO,
                              text="Eintrag löschen?")
        d.format_secondary_text("Dieser Eintrag wird endgültig gelöscht.")
        if d.run() == Gtk.ResponseType.YES:
            try:
                self.store.delete_entry(self.current_vehicle_id, key, entry_id)
                self._update_module()
            except Exception as e:
                self._error(str(e))
        d.destroy()

    # ---------- Dashboard-Rendering ----------
    def _update_dashboard(self):
        vehicles = self.store.get_vehicle_list()
        self.dash_title.set_markup("<b>Dashboard</b>")

        vehicle = self.store.get_vehicle(self.current_vehicle_id) if self.current_vehicle_id else None
        # Gesamtkosten nur des aktuell ausgewählten Fahrzeugs
        self.dash_cards['costs'].set_text(
            format_currency(self.store.total_costs(vehicle)) if vehicle else "–")

        if vehicle and vehicle.get('fuel_entries'):
            self.dash_cards['consumption'].set_text(
                format_number(self.store.fuel_consumption(vehicle['fuel_entries']), 1) + " l/100km")
        else:
            self.dash_cards['consumption'].set_text("–")

        if vehicle and vehicle.get('tuv_hu'):
            dates = []
            for e in vehicle['tuv_hu']:
                raw = e.get('next_date')
                if not raw:
                    continue
                try:
                    dates.append(datetime.strptime(raw, "%Y-%m-%d"))
                except ValueError:
                    continue
            self.dash_cards['tuv'].set_text(
                format_date(min(dates).strftime("%Y-%m-%d")) if dates else "–")
        else:
            self.dash_cards['tuv'].set_text("–")

        # Jährliche Auswertung (kompakt, gleichmäßig ausgerichtet)
        for child in self.dash_yearly_box.get_children():
            self.dash_yearly_box.remove(child)
        yearly = self.store.yearly_costs(vehicle) if vehicle else {}
        if not yearly:
            l = Gtk.Label(label="Noch keine Kosten erfasst.")
            l.set_halign(Gtk.Align.START)
            l.get_style_context().add_class("dim-label")
            self.dash_yearly_box.pack_start(l, False, False, 0)
        else:
            grid = Gtk.Grid(column_spacing=20, row_spacing=4)
            # Kopfzeile
            headers = ["Jahr", "Ø Verbrauch", "Gesamtkosten", "km"]
            for col, title in enumerate(headers):
                hl = Gtk.Label(label=title)
                hl.set_halign(Gtk.Align.START)
                hl.set_hexpand(True)
                hl.get_style_context().add_class("dim-label")
                grid.attach(hl, col, 0, 1, 1)
            # Eine Zeile pro Jahr
            for row, year in enumerate(sorted(yearly, reverse=True), start=1):
                y = yearly[year]
                cells = [
                    str(year),
                    (format_number(y.get('consumption', 0.0), 1) + " l/100km")
                        if y.get('consumption') else "–",
                    format_currency(y['total']),
                    format_int(y['km']) if y.get('km') else "–",
                ]
                for col, value in enumerate(cells):
                    vl = Gtk.Label(label=value)
                    vl.set_halign(Gtk.Align.START)
                    vl.set_hexpand(True)
                    grid.attach(vl, col, row, 1, 1)
            self.dash_yearly_box.pack_start(grid, False, False, 0)
        self.dash_yearly_box.show_all()

        # Fahrzeugübersicht
        self._clear_listbox(self.dash_list)
        if not vehicles:
            self._placeholder_row(self.dash_list, "Noch keine Fahrzeuge. "
                                "Oben über „Neues Fahrzeug“ anlegen.")
        else:
            for v in vehicles:
                box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, margin=6)
                nl = Gtk.Label(label=v['name'])
                nl.set_halign(Gtk.Align.START)
                box.pack_start(nl, True, True, 0)
                pl = Gtk.Label(label=v['license_plate'])
                pl.set_halign(Gtk.Align.START)
                box.pack_start(pl, False, False, 0)
                self.dash_list.add(Gtk.ListBoxRow(selectable=False, activatable=False)
                                   if False else box)
        self.dash_list.show_all()

    # ---------- Fahrzeugsdaten-Seite ----------
    def _update_vehicle_details(self):
        for child in self.vehicle_detail_box.get_children():
            self.vehicle_detail_box.remove(child)
        vehicle = self.store.get_vehicle(self.current_vehicle_id) if self.current_vehicle_id else None
        if not vehicle:
            self.vehicle_detail_box.pack_start(
                Gtk.Label(label="Kein Fahrzeug ausgewählt – bitte oben ein Fahrzeug wählen."),
                True, True, 0)
            self.vehicle_detail_box.show_all()
            return

        basic, tech = vehicle['basic'], vehicle['technical']
        basic_rows = [("Hersteller", basic['make']), ("Modell", basic['model']),
                      ("Kennzeichen", basic['license_plate']), ("VIN", basic['vin']),
                      ("Erstzulassung", format_date(basic['first_registration'])),
                      ("Farbe", basic['color']), ("Kraftstoffart", basic['fuel_type']),
                      ("Getriebe", basic['transmission']), ("Leistung (PS)", basic['power']),
                      ("Fahrzeugtyp", basic['vehicle_type'])]
        tech_rows = [("Hubraum (cm³)", tech['engine_capacity']),
                     ("Leergewicht (kg)", tech['empty_weight']),
                     ("Zul. Gesamtgewicht (kg)", tech['max_weight']),
                     ("Sitzplätze", tech['seats']), ("Türen", tech['doors']),
                     ("Länge (mm)", tech['length']), ("Breite (mm)", tech['width']),
                     ("Höhe (mm)", tech['height'])]

        for title, rows in [("Grunddaten", basic_rows), ("Technische Daten", tech_rows)]:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            card.get_style_context().add_class("card")
            card.pack_start(Gtk.Label(label=f"<b>{title}</b>", use_markup=True,
                                      halign=Gtk.Align.START), False, False, 0)
            grid = Gtk.Grid(row_spacing=4, column_spacing=20)
            for i, (label, value) in enumerate(rows):
                l = Gtk.Label(label=label)
                l.set_halign(Gtk.Align.START)
                l.get_style_context().add_class("stat-label")
                grid.attach(l, 0, i, 1, 1)
                v = Gtk.Label(label=str(value or '–'))
                v.set_halign(Gtk.Align.START)
                grid.attach(v, 1, i, 1, 1)
            card.pack_start(grid, False, False, 0)
            self.vehicle_detail_box.pack_start(card, False, False, 0)

        if tech.get('notes'):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            card.get_style_context().add_class("card")
            card.pack_start(Gtk.Label(label="<b>Notizen</b>", use_markup=True,
                                      halign=Gtk.Align.START), False, False, 0)
            lbl = Gtk.Label(label=tech['notes'])
            lbl.set_line_wrap(True)
            lbl.set_halign(Gtk.Align.START)
            card.pack_start(lbl, False, False, 0)
            self.vehicle_detail_box.pack_start(card, False, False, 0)
        self.vehicle_detail_box.show_all()

    # ---------- Auswertungen ----------
    def _update_reports(self):
        for child in self.reports_box.get_children():
            self.reports_box.remove(child)
        vehicle = self.store.get_vehicle(self.current_vehicle_id) if self.current_vehicle_id else None
        if not vehicle:
            self.reports_box.pack_start(
                Gtk.Label(label="Kein Fahrzeug ausgewählt – bitte oben ein Fahrzeug wählen."),
                True, True, 0)
            self.reports_box.show_all()
            return
        basic = vehicle['basic']
        total = self.store.total_costs(vehicle)
        fuel = vehicle.get('fuel_entries', [])

        # Kosten aufschlüsseln
        cost_parts = []
        cost_parts.append(("Tanken", sum(float(e.get('cost') or 0) for e in fuel)))
        cost_parts.append(("Hauptuntersuchung", sum(float(e.get('cost') or 0) for e in vehicle.get('tuv_hu', []))))
        cost_parts.append(("Service", sum(float(e.get('cost') or 0) for e in vehicle.get('repairs', []))))
        cost_parts.append(("Reifen", sum(float(e.get('cost') or 0) for e in vehicle.get('tires', []))))
        cost_parts.append(("Versicherungen / Kfz-Steuer", sum(float(e.get('annual_cost') or 0) for e in vehicle.get('insurances', []))))

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.get_style_context().add_class("card")
        card.pack_start(Gtk.Label(
            label=f"<b>Auswertung: {basic['make']} {basic['model']}</b>",
            use_markup=True, halign=Gtk.Align.START), False, False, 0)
        card.pack_start(Gtk.Label(label=f"Gesamtkosten: {format_currency(total)}",
                                  halign=Gtk.Align.START), False, False, 0)
        for part, amount in cost_parts:
            if amount > 0:
                pct = (amount / total * 100) if total else 0
                card.pack_start(Gtk.Label(
                    label=f"{part}: {format_currency(amount)} ({pct:.1f} %)".replace(".", ","),
                    halign=Gtk.Align.START), False, False, 0)
        self.reports_box.pack_start(card, False, False, 0)

        if fuel:
            card2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            card2.get_style_context().add_class("card")
            card2.pack_start(Gtk.Label(label="<b>Tankbuch-Statistik</b>", use_markup=True,
                                       halign=Gtk.Align.START), False, False, 0)
            # Jahresfilter: Anzeige nach Kalenderjahr möglich
            years = sorted({(e.get('date') or '')[:4] for e in fuel if e.get('date')},
                           reverse=True)
            year_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            yl = Gtk.Label(label="Jahr:")
            yl.set_halign(Gtk.Align.START)
            year_row.pack_start(yl, False, False, 0)
            self.fuel_year_combo = Gtk.ComboBoxText()
            self.fuel_year_combo.append_text("Alle Jahre")
            for y in years:
                self.fuel_year_combo.append_text(y)
            sel = getattr(self, 'fuel_year_selection', "Alle Jahre")
            self.fuel_year_combo.set_active(
                years.index(sel) + 1 if sel in years else 0)
            self.fuel_year_combo.connect("changed", self._on_fuel_year_changed)
            year_row.pack_start(self.fuel_year_combo, False, False, 0)
            card2.pack_start(year_row, False, False, 0)
            # Meilen-Faktor (editierbar, pro Fahrzeug gespeichert):
            # 1 Mil(e) = X km, z. B. 1,37 – dient nur zur Anzeige in Milen,
            # gespeichert wird immer in km (der Dialog rechnet beim Erfassen um)
            factor_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            fl1 = Gtk.Label(label="1 Mile =")
            fl1.set_halign(Gtk.Align.START)
            factor_row.pack_start(fl1, False, False, 0)
            self.mile_factor_entry = Gtk.Entry()
            self.mile_factor_entry.set_width_chars(6)
            self.mile_factor_entry.set_text(format_number(self._mile_factor(), 2))
            self.mile_factor_entry.connect("changed", self._on_mile_factor_changed)
            factor_row.pack_start(self.mile_factor_entry, False, False, 0)
            fl2 = Gtk.Label(label="km")
            fl2.set_halign(Gtk.Align.START)
            factor_row.pack_start(fl2, False, False, 0)
            card2.pack_start(factor_row, False, False, 0)
            # Verbrauchszeilen: l/100 Meile und l/100 km, live neu berechnet
            self.tank_stats_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            card2.pack_start(self.tank_stats_box, False, False, 0)
            self._render_tank_stats(fuel)
            # Ø Verbrauch auf einstellbare Distanz (Standard 130 km)
            dist_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            l1 = Gtk.Label(label="Ø Verbrauch auf")
            l1.set_halign(Gtk.Align.START)
            dist_row.pack_start(l1, False, False, 0)
            self.dist_entry = Gtk.Entry()
            self.dist_entry.set_width_chars(6)
            self.dist_entry.set_text(str(int(self.refuel_distance)))
            self.dist_entry.connect("changed", self._on_refuel_distance_changed)
            dist_row.pack_start(self.dist_entry, False, False, 0)
            l2 = Gtk.Label(label="km:")
            l2.set_halign(Gtk.Align.START)
            dist_row.pack_start(l2, False, False, 0)
            self.refuel_result_label = Gtk.Label(label="")
            self.refuel_result_label.set_halign(Gtk.Align.START)
            dist_row.pack_start(self.refuel_result_label, False, False, 0)
            card2.pack_start(dist_row, False, False, 0)
            self._update_refuel_result()
            self.reports_box.pack_start(card2, False, False, 0)

        # Jährliche Auswertung: sortierbare Tabelle pro Jahr
        yearly = self.store.yearly_costs(vehicle)
        if yearly:
            card3 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            card3.get_style_context().add_class("card")
            card3.pack_start(Gtk.Label(label="<b>Kosten je Jahr</b>", use_markup=True,
                                       halign=Gtk.Align.START), False, False, 0)

            columns = ['Jahr', 'km'] + self.store.YEARLY_CATEGORIES + ['Gesamt']
            n = len(columns)
            store = Gtk.ListStore(*([str] * n))
            tree = Gtk.TreeView(model=store)
            tree.set_hexpand(True)
            for i, title in enumerate(columns):
                renderer = Gtk.CellRendererText()
                col = Gtk.TreeViewColumn(title, renderer, text=i)
                col.set_resizable(True)
                col.set_clickable(True)
                col.set_sort_column_id(i)
                col.set_min_width(60)
                tree.append_column(col)
            for year in sorted(yearly, reverse=True):
                y = yearly[year]
                store.append([year,
                              format_int(y.get('km', 0)) if y.get('km') else '',
                              *[format_currency(y[c]) if y.get(c) else '–'
                                for c in self.store.YEARLY_CATEGORIES],
                              format_currency(y['total'])])
            card3.pack_start(tree, False, False, 0)
            self.reports_box.pack_start(card3, False, False, 0)
        self.reports_box.show_all()

    def _on_refuel_distance_changed(self, entry):
        """Distanz für die Verbrauchs-Hochrechnung; wird dauerhaft gespeichert."""
        try:
            dist = parse_float(entry.get_text())
        except (TypeError, ValueError):
            return
        if dist <= 0:
            return
        self.refuel_distance = dist
        settings = load_settings()
        settings['refuel_km'] = dist
        save_settings(settings)
        self._update_refuel_result()

    def _update_refuel_result(self):
        """Literverbrauch auf der eingestellten Distanz hochgerechnet."""
        cons = getattr(self, '_last_consumption', 0.0)
        liters = cons * self.refuel_distance / 100.0
        self.refuel_result_label.set_text(f"{format_number(liters, 2)} Liter")

    # ---------- Meilen-Faktor (Tankbuch-Statistik) ----------
    DEFAULT_MILE_FACTOR = 1.37

    def _mile_factor(self) -> float:
        """Gespeicherter Meilen-Faktor des aktuellen Fahrzeugs (km je Meile)."""
        if self.current_vehicle_id:
            settings = load_settings()
            try:
                return float(settings.get(f'mile_factor_{self.current_vehicle_id}',
                                          self.DEFAULT_MILE_FACTOR))
            except (TypeError, ValueError):
                pass
        return self.DEFAULT_MILE_FACTOR

    def _on_mile_factor_changed(self, entry):
        """Faktor speichern und Verbrauchswerte sofort neu berechnen."""
        try:
            factor = parse_float(entry.get_text())
        except (TypeError, ValueError):
            return
        if factor <= 0 or not self.current_vehicle_id:
            return
        settings = load_settings()
        settings[f'mile_factor_{self.current_vehicle_id}'] = factor
        save_settings(settings)
        vehicle = self.store.get_vehicle(self.current_vehicle_id)
        self._render_tank_stats(vehicle.get('fuel_entries', []) if vehicle else [])
        self._update_refuel_result()

    def _on_fuel_year_changed(self, combo):
        """Jahresauswahl merken und Tankbuch-Statistik neu berechnen."""
        self.fuel_year_selection = combo.get_active_text() or "Alle Jahre"
        vehicle = self.store.get_vehicle(self.current_vehicle_id)
        self._render_tank_stats(vehicle.get('fuel_entries', []) if vehicle else [])
        self._update_refuel_result()

    def _render_tank_stats(self, fuel_all: List[Dict]):
        """Tankbuch-Statistik, gefiltert nach Kalenderjahr je Auswahl."""
        for child in self.tank_stats_box.get_children():
            self.tank_stats_box.remove(child)
        sel = getattr(self, 'fuel_year_selection', "Alle Jahre")
        fuel = list(fuel_all) if sel == "Alle Jahre" else \
            [e for e in fuel_all if (e.get('date') or '')[:4] == sel]
        liters = sum(float(e.get('liters') or 0) for e in fuel)
        fuel_cost = sum(float(e.get('cost') or 0) for e in fuel)
        cons_km = self.store.fuel_consumption(fuel)
        cons_milen = cons_km * self._mile_factor()
        self._last_consumption = cons_km
        display = "Alle Jahre" if sel == "Alle Jahre" else f"Jahr {sel}"
        lines = [("Betrachtet", display),
                 ("Anzahl Betankungen", str(len(fuel))),
                 ("Menge gesamt", format_number(liters, 1) + " l"),
                 ("Kosten gesamt", format_currency(fuel_cost)),
                 ("Ø Preis pro Liter", format_currency(fuel_cost / liters if liters else 0)),
                 ("Ø Verbrauch", format_number(cons_milen, 2) + " l/100 Milen"),
                 ("Ø Verbrauch", format_number(cons_km, 2) + " l/100 km")]
        for label, value in lines:
            self.tank_stats_box.pack_start(Gtk.Label(label=f"{label}: {value}",
                                                      halign=Gtk.Align.START), False, False, 0)
        self.tank_stats_box.show_all()

    # ---------- Backup / Export / Import ----------
    def _on_backup(self, _btn):
        try:
            path = self.store.create_backup()
            self.backup_status.set_text(f"Backup erstellt: {path}")
            self._info(f"Backup erfolgreich erstellt:\n{path}")
        except Exception as e:
            self._error(f"Backup-Fehler: {e}")

    def _on_change_backup_dir(self, _btn):
        d = Gtk.FileChooserDialog(title="Backup-Zielordner wählen", parent=self,
                                  action=Gtk.FileChooserAction.SELECT_FOLDER)
        d.add_buttons("Abbrechen", Gtk.ResponseType.CANCEL,
                      "Auswählen", Gtk.ResponseType.OK)
        d.set_current_folder(self.store.backup_dir)
        if d.run() == Gtk.ResponseType.OK:
            try:
                self.store.set_backup_dir(d.get_filename())
                self.backup_dir_label.set_text(self.store.backup_dir)
                self._info(f"Neuer Backup-Zielordner:\n{self.store.backup_dir}")
            except Exception as e:
                self._error(str(e))
        d.destroy()

    def _on_export(self, _btn):
        d = Gtk.FileChooserDialog(title="Daten exportieren", parent=self,
                                  action=Gtk.FileChooserAction.SAVE)
        d.add_buttons("Abbrechen", Gtk.ResponseType.CANCEL,
                      "Speichern", Gtk.ResponseType.OK)
        d.set_do_overwrite_confirmation(True)
        d.set_current_name("kfz_daten_export.zip")
        if d.run() == Gtk.ResponseType.OK:
            try:
                path = d.get_filename()
                if path and not path.lower().endswith(".zip"):
                    path += ".zip"
                self.store.export_zip(path)
                self.backup_status.set_text(f"Exportiert: {path}")
                self._info("Export erfolgreich.")
            except Exception as e:
                self._error(f"Export-Fehler: {e}")
        d.destroy()

    def _on_import(self, _btn):
        d = Gtk.FileChooserDialog(title="Daten importieren", parent=self,
                                  action=Gtk.FileChooserAction.OPEN)
        d.add_buttons("Abbrechen", Gtk.ResponseType.CANCEL,
                      "Öffnen", Gtk.ResponseType.OK)
        if d.run() == Gtk.ResponseType.OK:
            try:
                count = self.store.import_zip(d.get_filename())
                self.current_vehicle_id = None
                self._refresh_vehicle_combo()
                self._update_module()
                self.backup_status.set_text(f"{count} Fahrzeugdatei(en) importiert.")
                self._info(f"Import erfolgreich: {count} Fahrzeugdatei(en).")
            except Exception as e:
                self._error(f"Import-Fehler: {e}")
        d.destroy()

    # ---------- Dialoge / Beenden ----------
    def _error(self, msg: str):
        d = Gtk.MessageDialog(transient_for=self, modal=True,
                              message_type=Gtk.MessageType.ERROR,
                              buttons=Gtk.ButtonsType.OK, text="Fehler")
        d.format_secondary_text(msg)
        d.run(); d.destroy()

    def _info(self, msg: str):
        d = Gtk.MessageDialog(transient_for=self, modal=True,
                              message_type=Gtk.MessageType.INFO,
                              buttons=Gtk.ButtonsType.OK, text="Information")
        d.format_secondary_text(msg)
        d.run(); d.destroy()

    def _on_quit(self, _btn):
        """Beenden-Schaltfläche: mit Sicherheitsabfrage."""
        d = Gtk.MessageDialog(transient_for=self, modal=True,
                              message_type=Gtk.MessageType.QUESTION,
                              buttons=Gtk.ButtonsType.YES_NO,
                              text="Programm wirklich beenden?")
        d.format_secondary_text(
            "Alle Daten sind bereits gespeichert.\n"
            "Möchten Sie die Kfz-Verwaltung wirklich beenden?")
        # "Ja"-Schaltfläche blau einfärben (wie die Kopfzeilen-Buttons)
        yes_btn = d.get_widget_for_response(Gtk.ResponseType.YES)
        if yes_btn is not None:
            yes_btn.set_name("yes-btn")
        if d.run() == Gtk.ResponseType.YES:
            self.destroy()
        d.destroy()

    def _on_destroy(self, _widget):
        Gtk.main_quit()


# ==================== HAUPTPROGRAMM ====================
def main():
    settings = load_settings()
    store = DataStore(backup_dir=settings.get('backup_dir'))
    win = MainWindow(store)
    Gtk.main()

if __name__ == "__main__":
    main()
