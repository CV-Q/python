#!/usr/bin/env python3
"""Run unify_region_cache and print a short verification summary."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from map_poi_fetcher import unify_region_cache


def main():
    cfg = 'config/poi_config.json'
    merged = unify_region_cache(cfg)
    print('Merged top-level keys count:', len(merged))
    sample = list(merged.keys())[:40]
    print('Sample keys:', sample)
    print('河南 present:', '河南' in merged)
    print('河南省 present:', '河南省' in merged)
    if '河南' in merged:
        print('郑州 in 河南:', '郑州' in merged['河南'])


if __name__ == '__main__':
    main()
