import itertools
import logging
import os
import tempfile
import unittest

from utils.controller.bindings import InputConfig, KeyMapConfig, parse_input
from utils.file.inireader import IniReader

_logger_seq = itertools.count()


class _CollectingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class _LoggingTestCase(unittest.TestCase):
    """Base class giving each test its own throwaway INI file and logger,
    both torn down automatically so tests can't bleed state into each other."""

    def _write_ini(self, text: str) -> str:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False, encoding="utf-8")
        tmp.write(text)
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        return tmp.name

    def _make_logger(self):
        logger = logging.getLogger(f"test_bindings.{next(_logger_seq)}")
        logger.setLevel(logging.DEBUG)
        handler = _CollectingHandler()
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        return logger, handler


class ParseInputAxisModeTests(unittest.TestCase):
    def test_unknown_axis_mode_raises(self):
        with self.assertRaises(ValueError):
            parse_input("dev:0:axis:1:posx:0.5")

    def test_missing_threshold_after_mode_raises(self):
        with self.assertRaises(ValueError):
            parse_input("dev:0:axis:1:pos")

    def test_missing_threshold_after_comparator_raises(self):
        with self.assertRaises(ValueError):
            parse_input("dev:0:axis:1:>")

    def test_valid_legacy_axis_mode_still_works(self):
        ib = parse_input("dev:0:axis:1:pos:0.5")
        self.assertEqual("pos", ib.axis_mode)
        self.assertEqual(0.5, ib.threshold)


class KeyMapConfigToleranceTests(_LoggingTestCase):
    def test_one_bad_entry_does_not_drop_the_rest(self):
        path = self._write_ini(
            "[input]\n"
            "key_mappings = dev:0:button:1 => A, \\\n"
            "               dev:0:axis:1:bogus:0.5 => A, \\\n"
            "               dev:0:button:2 => MB1\n"
        )
        log, handler = self._make_logger()
        cfg = IniReader(path, log)
        maps = KeyMapConfig.from_ini(cfg, log)

        self.assertEqual(2, len(maps))
        errors = [r for r in handler.records if r.levelno == logging.ERROR]
        self.assertEqual(1, len(errors))
        self.assertIn("bogus", errors[0].getMessage())

    def test_typo_action_verb_warns_but_still_loads(self):
        path = self._write_ini(
            "[input]\n"
            "key_mappings = dev:0:button:1 => FocusWndow:WindowClass:DCS\n"
        )
        log, handler = self._make_logger()
        cfg = IniReader(path, log)
        maps = KeyMapConfig.from_ini(cfg, log)

        self.assertEqual(1, len(maps))
        warnings = [r for r in handler.records if r.levelno == logging.WARNING]
        self.assertTrue(any("typo" in r.getMessage() for r in warnings))

    def test_real_key_combo_does_not_warn(self):
        path = self._write_ini(
            "[input]\n"
            "key_mappings = dev:0:button:1 => Ctrl+Shift+F5\n"
        )
        log, handler = self._make_logger()
        cfg = IniReader(path, log)
        KeyMapConfig.from_ini(cfg, log)

        warnings = [r for r in handler.records if r.levelno == logging.WARNING]
        self.assertEqual([], warnings)


class InputConfigModifierToleranceTests(_LoggingTestCase):
    def test_bad_modifier_disables_layer_instead_of_crashing(self):
        path = self._write_ini(
            "[input]\n"
            "modifier = dev:0:buton:5\n"  # typo: "buton"
        )
        log, handler = self._make_logger()
        cfg = IniReader(path, log)
        obj = InputConfig.from_ini(cfg, log)

        self.assertIsNone(obj.modifier)
        errors = [r for r in handler.records if r.levelno == logging.ERROR]
        self.assertTrue(any("modifier" in r.getMessage() for r in errors))

    def test_valid_modifier_still_parses(self):
        path = self._write_ini(
            "[input]\n"
            "modifier = dev:0:button:8\n"
        )
        log, _ = self._make_logger()
        cfg = IniReader(path, log)
        obj = InputConfig.from_ini(cfg, log)

        self.assertIsNotNone(obj.modifier)
        self.assertEqual(7, obj.modifier.input_id)  # 1-based in INI -> 0-based


class InputConfigCenterModeTests(_LoggingTestCase):
    def test_missing_option_defaults_to_absolute(self):
        path = self._write_ini(
            "[input]\n"
            "modifier = dev:0:button:8\n"
        )
        log, _ = self._make_logger()
        cfg = IniReader(path, log)
        obj = InputConfig.from_ini(cfg, log)

        self.assertEqual("absolute", obj.center_mode)

    def test_relative_is_accepted_case_insensitively(self):
        path = self._write_ini(
            "[input]\n"
            "center_mode = Relative\n"
        )
        log, _ = self._make_logger()
        cfg = IniReader(path, log)
        obj = InputConfig.from_ini(cfg, log)

        self.assertEqual("relative", obj.center_mode)

    def test_bad_value_falls_back_to_absolute_and_warns(self):
        path = self._write_ini(
            "[input]\n"
            "center_mode = sideways\n"
        )
        log, handler = self._make_logger()
        cfg = IniReader(path, log)
        obj = InputConfig.from_ini(cfg, log)

        self.assertEqual("absolute", obj.center_mode)
        warnings = [r for r in handler.records if r.levelno == logging.WARNING]
        self.assertTrue(any("center_mode" in r.getMessage() for r in warnings))


class IniReaderBomTests(unittest.TestCase):
    def test_utf8_bom_does_not_break_loading(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".ini", delete=False)
        tmp.write("[input]\naxis_speed = 700\n".encode("utf-8-sig"))
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)

        cfg = IniReader(tmp.name)
        self.assertEqual(["input"], cfg.cfg.sections())
        self.assertEqual(700, cfg.get_int("input", "axis_speed"))


if __name__ == "__main__":
    unittest.main()
