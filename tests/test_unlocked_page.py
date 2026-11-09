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

    def section(self, target, course):
        for code, matching, other in self.app.get_unlocked_courses(target):
            if code == course:
                return self.app.format_unlocked_course_result(code, matching, other, target)
        self.fail(f"{course} does not list {target}")

    def assert_summary_rules(self, target):
        text = self.search(target)
        unlocked = self.app.get_unlocked_courses(target)
        self.assertIn(f"{len(unlocked)} loaded courses list {target}", self.app.unlocked_summary.cget("text"))

        for course, matching, other in unlocked:
            section = self.app.format_unlocked_course_result(course, matching, other, target)
            summary = self.app.summarize_unlocked_course(course, matching, other, target)
            details = self.app.get_course_details(course)
            self.assertIn(section, text)
            self.assertIn(summary["role"], section)
            self.assertTrue(summary["role"].startswith(f"{target} is "), course)

            # every independent requirement group is represented by exactly one line
            covered = sorted(index for indexes in summary["covered"] for index in indexes)
            self.assertEqual(covered, list(range(len(other))), course)

            # short lists only; internal parser wording never shown
            self.assertLessEqual(len(summary["lines"]), self.app.UNLOCKED_MAX_LINES, course)
            for phrase in ("Alternatively:", "Plus 1 of", "Other conditions:", "Complete 1 of", "Complete all of"):
                self.assertNotIn(phrase, section, course)

            # whenever detail is left out (or the stored rule is approximate), point to Prereqs
            summarized_line = any("multiple accepted combinations" in line or "other courses" in line
                                  or line.endswith("more requirements") for line in summary["lines"])
            if summarized_line or details.get("needs_review"):
                self.assertTrue(summary["summarized"], course)
                self.assertIn("See Prereqs for full requirements.", section)

            # mandatory courses and short alternative groups appear exactly as stored
            for requirement in other:
                options = requirement["courses"]
                timing = self.app.requirement_timing_note(requirement)
                if len(options) <= self.app.UNLOCKED_MAX_LISTED_OPTIONS and not summarized_line:
                    expected = options[0] if len(options) == 1 else self.app.join_courses(options, "or")
                    self.assertTrue(any(expected in line for line in summary["lines"]), (course, options))

        ranges = self.app.unlocked_results.tag_ranges("unlocked_code")
        headings = {
            self.app.unlocked_results.get(ranges[i], ranges[i + 1]).split(" \u2014 ")[0].strip()
            for i in range(0, len(ranges), 2)
        } - {""}
        self.assertEqual(headings, {course for course, _m, _o in unlocked})
        return unlocked

    def test_math100(self):
        self.assertEqual(len(self.assert_summary_rules("MATH 100")), 31)

    def test_csc225_and_csc226(self):
        self.assert_summary_rules("CSC 225")
        self.assert_summary_rules("CSC 226")

    def test_complex_requirements(self):
        for target in ("BIOL 311", "BIOL 225", "COM 220", "STAT 260", "PHYS 110"):
            with self.subTest(target=target):
                self.assertTrue(self.assert_summary_rules(target))

    def test_biol311_from_math100(self):
        self.assertEqual(self.section("MATH 100", "BIOL 311"), "\n".join([
            "BIOL 311 \u2014 Biological Oceanography",
            "MATH 100 is one of the accepted prerequisite options.",
            "Other requirements:",
            "\u2022 CHEM 102",
            "\u2022 One of CHEM 101 or CHEM 150",
            "\u2022 PHYS requirement \u2014 multiple accepted combinations",
            "\u2022 Minimum third-year standing",
            "See Prereqs for full requirements.",
        ]))

    def test_chem102_and_astr150(self):
        chem = self.section("MATH 100", "CHEM 102")
        self.assertIn("MATH 100 is one of the accepted options (can be taken at the same time).", chem)
        self.assertIn("\u2022 One of CHEM 101 or CHEM 150", chem)
        self.assertIn("\u2022 Alternative way to qualify: Chemistry 12", chem)

        astr = self.section("MATH 100", "ASTR 150")
        self.assertIn("\u2022 One of PHYS 110 or PHYS 120 (can be taken at the same time)", astr)
        self.assertIn("\u2022 Alternative way to qualify: permission of the department", astr)

    def test_csc226(self):
        self.assertEqual(self.section("STAT 260", "CSC 226"), "\n".join([
            "CSC 226 \u2014 Algorithms and Data Structures II",
            "STAT 260 is one of the accepted options (can be taken at the same time).",
            "Other requirements:",
            "\u2022 CSC 225",
        ]))
        self.assertIn(
            "\u2022 One of GEOG 226, PSYC 300A, STAT 254 or 2 other courses (can be taken at the same time)",
            self.section("CSC 225", "CSC 226"),
        )

    def test_simple_mandatory_prerequisites(self):
        text = self.section("CSC 225", "CSC 360")
        self.assertIn("CSC 225 is required.", text)
        self.assertIn("\u2022 SENG 265\n\u2022 One of CSC 120 or ENGR 130\n\u2022 One of CSC 230 or ECE 255", text)
        self.assertNotIn("See Prereqs", text)

    def test_many_overlapping_alternatives(self):
        text = self.section("COM 220", "ENT 400")
        self.assertIn("COM 220 is part of one of the accepted combinations.", text)
        self.assertIn("\u2022 ENT 410, ENT 411, ENT 412 and ENT 413 (must be taken in the same term)", text)
        self.assertIn("\u2022 COM requirement \u2014 multiple accepted combinations", text)
        self.assertIn("See Prereqs for full requirements.", text)
        self.assertLessEqual(text.count("\u2022"), 6)

    def test_note_wording(self):
        clean = self.app.clean_requirement_note
        self.assertEqual(clean("Alternatively: Chemistry 12"), "Alternative way to qualify: Chemistry 12")
        self.assertEqual(clean("Alternatively: or permission of the department."),
                         "Alternative way to qualify: permission of the department")
        self.assertEqual(clean("or permission of the school."), "Alternative way to qualify: permission of the school")
        self.assertEqual(clean("minimum third-year standing."), "Minimum third-year standing")

    def test_unknown_course(self):
        text = self.search("XYZ 999")
        self.assertEqual(text.strip(), "")
        self.assertIn("No loaded courses list XYZ 999", self.app.unlocked_summary.cget("text"))


if __name__ == "__main__":
    unittest.main()
