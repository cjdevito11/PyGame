"""CLI integration tests for the demo commands."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import unittest

from ui import cli


DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def run_cli(args: list[str]):
    buffer = StringIO()
    with redirect_stdout(buffer):
        code = cli.run(args)
    return code, buffer.getvalue()


class TestCli(unittest.TestCase):
    def test_list_outputs_entries(self) -> None:
        code, output = run_cli([str(DATA_DIR), "list", "classes"])

        self.assertEqual(code, 0)
        self.assertIn("Available entries:", output)
        self.assertIn("adventurer", output)

    def test_show_handles_missing_entry(self) -> None:
        code, output = run_cli([str(DATA_DIR), "show", "classes", "missing"])

        self.assertEqual(code, 1)
        self.assertIn("No classes named 'missing'", output)

    def test_validate_confirms_definitions(self) -> None:
        code, output = run_cli([str(DATA_DIR), "validate"])

        self.assertEqual(code, 0)
        self.assertIn("All registry definitions are valid.", output)

    def test_debug_inspect_reports_character(self) -> None:
        code, output = run_cli([str(DATA_DIR), "debug", "inspect", "Aria"])

        self.assertEqual(code, 0)
        self.assertIn("Aria: class=adventurer", output)

    def test_debug_simulate_attack(self) -> None:
        code, output = run_cli(
            [str(DATA_DIR), "debug", "simulate", "Aria", "Shade", "--weapon", "bronze_sword", "--bonus", "2"]
        )

        self.assertEqual(code, 0)
        self.assertIn("Preview: Aria would deal", output)
