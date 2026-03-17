from __future__ import annotations

import json
import unittest
from pathlib import Path


class ManifestTests(unittest.TestCase):
    def test_a6_autodiscovery_matches_all_known_advertisement_services(self) -> None:
        manifest_path = (
            Path(__file__).resolve().parents[1]
            / "custom_components"
            / "weightgurus_ble"
            / "manifest.json"
        )
        manifest = json.loads(manifest_path.read_text())

        bluetooth_matchers = manifest["bluetooth"]
        self.assertEqual(
            {
                matcher["service_uuid"]
                for matcher in bluetooth_matchers
                if matcher.get("connectable") is True
            },
            {
                "20568521-5acd-4c5a-9294-eb2691c8b8bf",
                "e492c1fb-2466-4749-ab37-69433d2d7846",
                "0000a602-0000-1000-8000-00805f9b34fb",
            },
        )


if __name__ == "__main__":
    unittest.main()
