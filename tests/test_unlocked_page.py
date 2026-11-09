"""Layout and formatting regression tests for the Unlocked/Post-requisites page.

Run from the project folder:  python3 -m unittest discover tests
"""

import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

import course_gui  # noqa: E402

BULLET = "• "


class UnlockedPageTests(unittest.TestCase):
    def setUp(self):
        try:
            tk.Tk().destroy()
        except Exception as error:
            self.skipTest(f"Tk not available: {error}")

        self.temp = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp.name)
        for name, filename in (
            ("COMPLETED_COURSES_FILE", "completed.json"),
            ("WANTED_COURSES_FILE", "wanted.json"),
            ("NOTES_FILE", "notes.json"),
            ("FLOWCHART_DOT_FILE", "flowchart.dot"),
        ):
            patch = mock.patch.object(course_gui, name, data_dir / filename)
            patch.start()
            self.addCleanup(patch.stop)

        self.app = course_gui.CoursePostRequisitesApp()
        self.app.geometry("1200x780")
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.app.destroy)
        self.app.show_unlocked_courses_page()
        self.app.update()

    def search(self, text):
        self.app.unlocked_course_entry.delete(0, tk.END)
        self.app.unlocked_course_entry.insert(0, text)
        self.app.check_unlocked_courses()
        self.app.update()
        return self.app.unlocked_results.get("1.0", "end")

    # ------------------------------------------------------------------ layout

    def test_results_row_expands(self):
        result_frame = self.app.unlocked_results.master
        page = result_frame.master
        self.assertEqual(int(result_frame.grid_info()["row"]), 3)
        self.assertEqual(int(page.grid_rowconfigure(3)["weight"]), 1)
        self.assertEqual(int(page.grid_rowconfigure(4)["weight"]), 0)

    def test_results_fill_window_and_resize(self):
        page = self.app.unlocked_results.master.master
        self.assertGreater(self.app.unlocked_results.winfo_height(), page.winfo_height() * 0.6)

        self.app.geometry("1150x700")
        self.app.update()
        small = (self.app.unlocked_results.winfo_width(), self.app.unlocked_results.winfo_height())
        self.app.geometry("1250x790")
        self.app.update()
        large = (self.app.unlocked_results.winfo_width(), self.app.unlocked_results.winfo_height())
        self.assertGreater(large[0], small[0] + 50)
        self.assertGreater(large[1], small[1] + 50)

    def test_search_bar_stays_visible_and_results_start_at_top(self):
        self.search("MATH 100")
        self.app.unlocked_results.yview_moveto(1.0)
        self.app.update()
        self.assertGreater(self.app.unlocked_results.yview()[0], 0.0)  # it really scrolls
        self.search("CSC 225")
        self.assertEqual(self.app.unlocked_results.yview()[0], 0.0)
        self.assertTrue(self.app.unlocked_course_entry.winfo_ismapped())
        self.assertLess(self.app.unlocked_course_entry.winfo_rooty(), self.app.unlocked_results.winfo_rooty())

    # ------------------------------------------------------------------ content

    def assert_nothing_lost(self, target):
        text = self.search(target)
        unlocked = self.app.get_unlocked_courses(target)
        self.assertIn(f"{len(unlocked)} loaded courses list {target}", self.app.unlocked_summary.cget("text"))

        for course, matching, other in unlocked:
            section = self.app.format_unlocked_course_result(course, matching, other, target)
            self.assertIn(section, text)
            lines = section.split("\n")
            details = self.app.get_course_details(course)

            # one role line per group containing the searched course
            role_lines = [line for line in lines if line.startswith(f"{target} is ")]
            self.assertEqual(len(role_lines), len(matching), course)

            # one bulleted heading per other group, with its exact wording and every option listed
            additional = lines[lines.index("Additional requirements:") + 1:] if other else []
            if "Other conditions:" in additional:
                additional = additional[:additional.index("Other conditions:")]
            headings = [line for line in additional if line.startswith(BULLET)]
            self.assertEqual(
                headings,
                [BULLET + self.app.requirement_prefix(requirement) + ":" for requirement in other],
                course,
            )

            for requirement in matching + other:
                for option in requirement["courses"]:
                    self.assertIn(option, section)

            for note in details.get("requirement_notes") or []:
                self.assertIn(BULLET + note, lines)

        # course codes are the bold headings
        ranges = self.app.unlocked_results.tag_ranges("unlocked_code")
        headings = {
            self.app.unlocked_results.get(ranges[i], ranges[i + 1]).split("   ")[0].strip()
            for i in range(0, len(ranges), 2)
        } - {""}
        self.assertEqual(headings, {course for course, _m, _o in unlocked})
        return unlocked

    def test_math100(self):
        self.assertEqual(len(self.assert_nothing_lost("MATH 100")), 31)

    def test_csc225_and_csc226(self):
        self.assert_nothing_lost("CSC 225")
        self.assert_nothing_lost("CSC 226")

    def test_complex_requirements(self):
        for target in ("BIOL 311", "BIOL 225", "COM 220", "STAT 260"):
            with self.subTest(target=target):
                self.assertTrue(self.assert_nothing_lost(target))

    def test_unknown_course(self):
        text = self.search("XYZ 999")
        self.assertEqual(text.strip(), "")
        self.assertIn("No loaded courses list XYZ 999", self.app.unlocked_summary.cget("text"))


if __name__ == "__main__":
    unittest.main()
