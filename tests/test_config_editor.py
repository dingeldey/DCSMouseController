import tempfile
from pathlib import Path
import unittest

from utils.config_editor import ConfigDocument, MappingRow, replace_device


SAMPLE = """; user heading must survive
[input]
modifier = dev:old-guid:button:8
axis_speed = 400 ; keep nearby comments
key_mappings = dev:old-guid:button:1 => Ctrl+A, \\
                dev:old-guid:button:2:M => MB1:hold
axis_mappings = dev:Other Stick:axis:0 => mouse_x

[unrelated]
value = untouched
"""


class ConfigDocumentTests(unittest.TestCase):
    def make_document(self):
        temporary = tempfile.TemporaryDirectory()
        path = Path(temporary.name) / "profile.ini"
        path.write_text(SAMPLE, encoding="utf-8")
        return temporary, path, ConfigDocument(path)

    def test_reads_all_mapping_rows(self):
        temporary, _path, document = self.make_document()
        self.addCleanup(temporary.cleanup)
        rows = document.mappings()
        self.assertEqual(3, len(rows))
        self.assertEqual("old-guid", rows[0].device)
        self.assertTrue(rows[1].modified)
        self.assertEqual("Axis 0", rows[2].input_label)

    def test_save_preserves_comments_and_other_sections(self):
        temporary, path, document = self.make_document()
        self.addCleanup(temporary.cleanup)
        document.set_option("axis_speed", "900")
        document.save()
        result = path.read_text(encoding="utf-8")
        self.assertIn("; user heading must survive", result)
        self.assertIn("[unrelated]\nvalue = untouched", result)
        self.assertEqual("900", ConfigDocument(path).get("axis_speed"))
        self.assertTrue(path.with_suffix(".ini.bak").exists())

    def test_remap_updates_mappings_and_modifier_only(self):
        temporary, path, document = self.make_document()
        self.addCleanup(temporary.cleanup)
        rows = document.mappings()
        self.assertEqual(3, document.remap_device("old-guid", "new-guid", rows))
        document.set_mappings(rows)
        document.save(False)
        reread = ConfigDocument(path)
        self.assertEqual("dev:new-guid:button:8", reread.get("modifier"))
        self.assertEqual(["new-guid", "Other Stick"], reread.referenced_devices())

    def test_replace_device_requires_exact_token(self):
        value = "dev:old-guid-extra:button:1"
        self.assertEqual(value, replace_device(value, "old-guid", "new-guid"))

    def test_set_mappings_round_trip(self):
        temporary, path, document = self.make_document()
        self.addCleanup(temporary.cleanup)
        expected = [
            MappingRow("key", "dev:a:button:1", "F1"),
            MappingRow("key", "dev:a:button:1", "MB1:hold"),
            MappingRow("axis", "dev:b:axis:2", "mouse_y"),
        ]
        document.set_mappings(expected)
        document.save(False)
        self.assertEqual(expected, ConfigDocument(path).mappings())


if __name__ == "__main__":
    unittest.main()
