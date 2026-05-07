from pathlib import Path
import tempfile
import unittest

import map_poi_fetcher as mp
from poi_utils import append_new_records


class TestIncrementalStrategy(unittest.TestCase):
    def test_append_new_records_updates_passed_empty_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "inc.csv"
            existing_keys = set()
            records = [
                {
                    "name": "示例POI",
                    "latitude": 38.1234567,
                    "longitude": 114.7654321,
                    "source": "gaode",
                }
            ]

            appended = append_new_records(records, str(target), existing_keys)

            self.assertEqual(appended, 1)
            self.assertEqual(len(existing_keys), 1)

    def test_build_incremental_path_by_provider_and_province(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = mp.build_incremental_path(
                {"results_dir": str(tmp)},
                provider="gaode",
                province="河北省",
            )

            self.assertEqual(path.parent, Path(tmp) / "incremental" / "gaode")
            self.assertEqual(path.name, "gaode-河北省_incremental.csv")


if __name__ == "__main__":
    unittest.main()
