"""Smoke tests for the interactive play loop."""

from io import StringIO
import contextlib
import unittest

from ui import cli


class PlayCommandTest(unittest.TestCase):
    def test_player_wins_duel_with_scripted_actions(self) -> None:
        """Scripted actions let tests cover the play loop without user input."""

        output = StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = cli.run(["play", "--actions", "attack,attack"])

        self.assertEqual(exit_code, 0)
        transcript = output.getvalue()
        self.assertIn("Aria wins!", transcript)
        self.assertIn("Shade", transcript)

    def test_missing_characters_fail_fast(self) -> None:
        output = StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = cli.run(["play", "--player", "Missing", "--enemy", "Shade", "--actions", "attack"])

        self.assertEqual(exit_code, 1)
        self.assertIn("must exist", output.getvalue())


if __name__ == "__main__":
    unittest.main()
