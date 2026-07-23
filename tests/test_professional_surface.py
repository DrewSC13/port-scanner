from pathlib import Path
import re
import unittest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EMOJI_PATTERN = re.compile("[\U0001f300-\U0001faff\u2600-\u27bf]")


class TestProfessionalSurface(unittest.TestCase):
    def test_user_facing_sources_do_not_contain_emojis(self):
        paths = [
            PROJECT_ROOT / "main.py",
            PROJECT_ROOT / "README.md",
            *sorted((PROJECT_ROOT / "src").glob("*.py")),
            *sorted((PROJECT_ROOT / "scripts").glob("*.sh")),
        ]
        offenders = []
        for path in paths:
            if EMOJI_PATTERN.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(PROJECT_ROOT)))

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
