"""Tests for course validation and the Browse Courses page.

Run from the project folder:  python3 -m unittest discover tests
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

import course_gui  # noqa: E402

CATALOG_COURSES = json.loads((PROJECT_DIR / "course_graph.json").read_text(encoding="utf-8"))["courses"]


class ParseCourseEntriesTests(unittest.TestCase):
    def parse(self, text):
        return course_gui.parse_course_entries(text, CATALOG_COURSES)

    def test_accepts_any_capitalization_and_spacing(self):
        for text in ("CSC 110", "csc110", "CSC110", "  csc   110 ", "Csc 110"):
            with self.subTest(text=text):
                self.assertEqual(self.parse(text), (["CSC 110"], []))

    def test_rejects_unknown_courses(self):
        for text in ("Fuck300", "XYZ999", "CSC 999", "hello"):
            with self.subTest(text=text):
                valid, rejected = self.parse(text)
                self.assertEqual(valid, [])
                self.assertEqual(rejected, [text])

    def test_multiple_entries_split_valid_and_rejected(self):
        valid, rejected = self.parse("csc110, Fuck300\nMATH 100; XYZ999, SENG265, csc 110")
        self.assertEqual(valid, ["CSC 110", "MATH 100", "SENG 265"])
        self.assertEqual(rejected, ["Fuck300", "XYZ999"])

    def test_existing_example_format_still_works(self):
        valid, rejected = self.parse("ATWP 135 or CSC 225, SENG 310")
        self.assertEqual(valid, ["ATWP 135", "CSC 225", "SENG 310"])
        self.assertEqual(rejected, [])

    def test_letter_suffix_courses(self):
        self.assertEqual(self.parse("psyc100a"), (["PSYC 100A"], []))

    def test_empty_input(self):
        self.assertEqual(self.parse("  ,\n ; "), ([], []))


class BrowseCatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = course_gui.build_course_catalog({"courses": CATALOG_COURSES})

    def test_lists_entire_database_sorted(self):
        self.assertEqual(len(self.catalog), len(CATALOG_COURSES))
        self.assertEqual(len(self.catalog), 3713)
        codes = [code for code, _title in self.catalog]
        self.assertEqual(codes, sorted(codes))

    def test_includes_courses_without_prerequisites(self):
        no_prereqs = [
            code for code, details in CATALOG_COURSES.items()
            if not details.get("prerequisite_groups")
        ]
        self.assertTrue(no_prereqs)
        codes = {code for code, _title in self.catalog}
        self.assertTrue(set(no_prereqs) <= codes)

    def test_search_by_code_any_format(self):
        for query in ("CSC 110", "csc110", "Csc 11"):
            with self.subTest(query=query):
                codes = [code for code, _ in course_gui.filter_course_catalog(self.catalog, query)]
                self.assertIn("CSC 110", codes)
                self.assertTrue(all(code.startswith("CSC 11") for code in codes))

    def test_search_by_title(self):
        results = course_gui.filter_course_catalog(self.catalog, "algorithms and data structures")
        self.assertIn("CSC 225", [code for code, _ in results])
        self.assertTrue(all("algorithms and data structures" in title.lower() for _, title in results))

    def test_subject_filter(self):
        results = course_gui.filter_course_catalog(self.catalog, "", "MATH")
        self.assertTrue(results)
        self.assertTrue(all(code.startswith("MATH ") for code, _ in results))
        everything = course_gui.filter_course_catalog(self.catalog, "", course_gui.ALL_SUBJECTS_LABEL)
        self.assertEqual(len(everything), 3713)


class GuiTests(unittest.TestCase):
    """Drive the real window with saved data redirected to a temporary folder."""

    def setUp(self):
        try:
            import tkinter
            tkinter.Tk().destroy()
        except Exception as error:  # no display or no Tk
            self.skipTest(f"Tk not available: {error}")

        self.temp = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp.name)
        self.completed_file = data_dir / "completed_courses.json"
        self.wanted_file = data_dir / "wanted_courses.json"
        # A previously saved course that isn't in the catalog must be kept as-is.
        self.completed_file.write_text(json.dumps({"completed_courses": ["ABC 123", "CSC 110"]}))

        patches = [
            mock.patch.object(course_gui, "COMPLETED_COURSES_FILE", self.completed_file),
            mock.patch.object(course_gui, "WANTED_COURSES_FILE", self.wanted_file),
            mock.patch.object(course_gui, "NOTES_FILE", data_dir / "course_notes.json"),
            mock.patch.object(course_gui, "FLOWCHART_DOT_FILE", data_dir / "flowchart.dot"),
            mock.patch.object(course_gui.messagebox, "showinfo"),
            mock.patch.object(course_gui.messagebox, "showwarning"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

        self.app = course_gui.CoursePostRequisitesApp()
        self.app.withdraw()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.app.destroy)

    def saved_completed(self):
        return json.loads(self.completed_file.read_text())["completed_courses"]

    def test_my_plan_adds_valid_rejects_invalid_and_keeps_saved(self):
        self.app.show_taken_courses_page()
        self.app.completed_courses_text.insert("1.0", "math100, Fuck300, XYZ999, csc 110")
        self.app.add_completed_courses_from_input()

        self.assertEqual(self.saved_completed(), ["ABC 123", "CSC 110", "MATH 100"])
        self.assertEqual(self.app.completed_courses_text.get("1.0", "end").strip(), "Fuck300, XYZ999")
        course_gui.messagebox.showwarning.assert_called_once()
        message = course_gui.messagebox.showwarning.call_args[0][1]
        self.assertIn("Fuck300", message)
        self.assertIn(course_gui.COURSE_NOT_FOUND_MESSAGE, message)

    def test_my_plan_only_invalid_changes_nothing(self):
        self.app.show_taken_courses_page()
        self.app.completed_courses_text.insert("1.0", "Fuck300")
        self.app.add_completed_courses_from_input()
        self.assertEqual(self.saved_completed(), ["ABC 123", "CSC 110"])
        course_gui.messagebox.showwarning.assert_called_once()

    def test_targets_use_same_validation(self):
        self.app.show_wanted_courses_page()
        self.app.wanted_course_entry.insert(0, "csc225, XYZ999")
        self.app.add_wanted_course()

        saved = json.loads(self.wanted_file.read_text())["wanted_courses"]
        self.assertEqual(saved, ["CSC 225"])
        self.assertEqual(self.app.wanted_course_entry.get(), "XYZ999")
        course_gui.messagebox.showwarning.assert_called_once()

    def test_browse_page_lists_everything_and_shows_details(self):
        self.app.show_browse_courses_page()
        self.assertEqual(self.app.browse_course_list.size(), 3713)
        self.assertIn("3713", self.app.browse_count_label.cget("text"))

        self.app.browse_search_var.set("csc225")
        self.assertEqual(self.app.browse_course_list.size(), 1)
        self.assertIn("matching", self.app.browse_count_label.cget("text"))

        self.app.browse_course_list.selection_set(0)
        self.app.show_selected_browse_course()
        details = self.app.browse_details.get("1.0", "end")
        self.assertIn("CSC 225: Algorithms and Data Structures I", details)
        self.assertIn("Credits:", details)
        self.assertIn("Prerequisites", details)


if __name__ == "__main__":
    unittest.main()
