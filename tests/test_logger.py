import logging
import os
import tempfile
import unittest

from utils.logger.logger import setup_logger


class SetupLoggerReentryTests(unittest.TestCase):
    def test_second_call_does_not_change_level_or_add_handlers(self):
        name = "test_logger_reentry"
        self.addCleanup(logging.getLogger(name).handlers.clear)

        with tempfile.TemporaryDirectory() as tmp:
            log_a = os.path.join(tmp, "a.log")
            log_b = os.path.join(tmp, "b.log")

            first = setup_logger(name, logfile=log_a, console=False,
                                  console_level=logging.INFO, file_level=logging.DEBUG,
                                  color_console=False)
            level_after_first = first.level
            handler_count_after_first = len(first.handlers)

            second = setup_logger(name, logfile=log_b, console=False,
                                   console_level=logging.ERROR, file_level=logging.ERROR,
                                   color_console=False)

            self.assertIs(first, second)
            self.assertEqual(level_after_first, second.level)
            self.assertEqual(handler_count_after_first, len(second.handlers))
            self.assertFalse(os.path.exists(log_b))


if __name__ == "__main__":
    unittest.main()
