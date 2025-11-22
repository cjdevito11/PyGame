import logging
import os
import unittest
from io import StringIO

from core.logging_config import configure_logging, get_logger, log_with_fields
from core.validation import DefinitionValidator
from world.schemas import AppearanceDefinition


class LoggingTests(unittest.TestCase):
    def test_log_level_toggle_and_fields(self) -> None:
        stream = StringIO()
        handler = logging.StreamHandler(stream)

        configure_logging(level="DEBUG", force=True)
        logger = get_logger("systems.test")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)

        log_with_fields(logger, logging.DEBUG, "structured", step="demo")
        handler.flush()

        output = stream.getvalue()
        self.assertIn("structured", output)
        self.assertIn("step='demo'", output)

        logger.removeHandler(handler)

    def test_env_toggle_sets_root_level(self) -> None:
        os.environ["LOG_LEVEL"] = "ERROR"
        configure_logging(force=True)
        try:
            self.assertEqual(logging.getLogger().getEffectiveLevel(), logging.ERROR)
        finally:
            os.environ.pop("LOG_LEVEL", None)


class ValidationPointerTests(unittest.TestCase):
    def test_error_points_to_field_location(self) -> None:
        validator = DefinitionValidator()
        validator.register_schema("appearances", AppearanceDefinition)

        with self.assertRaises(ValueError) as ctx:
            validator.validate("appearances", {"name": "ghost", "symbol": "G", "color": "white"})

        message = str(ctx.exception)
        self.assertIn("appearances.ghost.description", message)
        self.assertIn("<missing>", message)


if __name__ == "__main__":
    unittest.main()
