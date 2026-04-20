import os, json
from pathlib import Path
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from poi_utils import build_record_key, append_new_records, load_keys_from_file

def load_csv_keys(path):
    return load_keys_from_file(path)

def simulate(records, existing_keys, path):
    ek = set(existing_keys)
    appended = append_new_records(records, path, ek)
    print('Appended:', appended)
    print('Existing keys sample (first 5):', list(sorted(ek))[:5])
    return ek

def main():
    base = Path('POI_Data') / '2026-04-20'
    inc = base / '河北_incremental.csv'
    print('incremental file exists:', inc.exists())
    existing_keys = load_csv_keys(str(inc)) if inc.exists() else set()
    print('Loaded existing keys count:', len(existing_keys))

    # Scenario 1: provider returned records without lat/lng (old bug)
    old_provider_records = [
        {"source":"tianditu","name":"荣泰酒店","address":"绿水路08号","latitude":None,"longitude":None,"type":"120101","contact":"","task":"河北","run_time":""},
        {"source":"tianditu","name":"锦江宾馆","address":"...","latitude":None,"longitude":None,"type":"120101","contact":"","task":"河北","run_time":""},
    ]

    # Scenario 2: provider returned records with lat/lng (fixed)
    fixed_provider_records = [
        {"source":"tianditu","name":"荣泰酒店","address":"绿水路08号","latitude":37.88896,"longitude":115.24551,"type":"120101","contact":"","task":"河北","run_time":""},
        {"source":"tianditu","name":"锦江宾馆","address":"...","latitude":37.97465,"longitude":115.21498,"type":"120101","contact":"","task":"河北","run_time":""},
    ]

    tmp_old = Path('POI_Data_test') / 'tmp_old.csv'
    tmp_fixed = Path('POI_Data_test') / 'tmp_fixed.csv'
    tmp_old.parent.mkdir(parents=True, exist_ok=True)

    print('\n-- Scenario: old provider (no lat/lng) --')
    ek1 = simulate(old_provider_records, existing_keys, str(tmp_old))

    print('\n-- Scenario: fixed provider (with lat/lng) --')
    ek2 = simulate(fixed_provider_records, existing_keys, str(tmp_fixed))

    # Show keys generated for records
    print('\nKeys for old records:')
    for r in old_provider_records:
        print(' ', build_record_key(r))
    print('Keys for fixed records:')
    for r in fixed_provider_records:
        print(' ', build_record_key(r))

if __name__ == '__main__':
    main()
