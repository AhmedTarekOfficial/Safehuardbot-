import unittest

from sentinel.i18n import tr
from sentinel.shortcuts import normalized_word, parse_command, integer_arg


class LocalizationAndShortcutsTests(unittest.TestCase):
    def test_language_strings(self):
        self.assertIn("مركز التحكم", tr("ar", "home"))
        self.assertIn("CONTROL CENTER", tr("en", "home"))
        self.assertIn("اص", tr("ar", "shortcuts_text"))
        self.assertIn("mute", tr("en", "shortcuts_text"))
        self.assertIn("`mute`", tr("ar", "shortcuts_text"))

    def test_arabic_and_latin_shortcut_words(self):
        self.assertEqual(normalized_word(" اص "), "اص")
        self.assertEqual(normalized_word("MUTE"), "mute")
        for invalid in ("a", "/mute", "!mute", "multiple words", "@everyone", "_admin"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    normalized_word(invalid)

    def test_exact_no_prefix_dispatch(self):
        aliases = {"اص": "mute", "clear": "purge"}
        self.assertEqual(parse_command("اص <@123> 10", aliases), ("اص", "mute", "<@123> 10"))
        self.assertEqual(parse_command("CLEAR 5", aliases), ("clear", "purge", "5"))
        self.assertIsNone(parse_command("اصلي", aliases))
        self.assertIsNone(parse_command("/اص <@123>", aliases))
        self.assertIsNone(parse_command("!", aliases))

    def test_integer_arguments_and_mentions(self):
        self.assertEqual(integer_arg("<@!123> 10", 1, 40320), 10)
        self.assertEqual(integer_arg("<@123>", 1, 40320, default=10), 10)
        self.assertIsNone(integer_arg("abc", 1, 40320))
        self.assertIsNone(integer_arg("0", 1, 40320))
        self.assertIsNone(integer_arg("101", 1, 100))


if __name__ == "__main__":
    unittest.main()
