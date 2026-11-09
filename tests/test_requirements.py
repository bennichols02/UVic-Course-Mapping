"""Accuracy tests for prerequisite / pre-or-corequisite data and how the app interprets it.

Run from the project folder:  python3 -m unittest discover tests
"""

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

import course_gui  # noqa: E402

GRAPH = json.loads((PROJECT_DIR / "course_graph.json").read_text(encoding="utf-8"))
COURSES = GRAPH["courses"]
STATS_OPTIONS = ["GEOG 226", "PSYC 300A", "STAT 254", "STAT 255", "STAT 260"]
ONE_OF_LINE = re.compile(
    r"^(\s*)(Complete|Completed or concurrently enrolled in|Concurrently enrolled in) 1 of: (.+)$"
)
ALL_OF_LINE = re.compile(r"^(\s*)Complete all of: (.+)$")


def summary_lines_with_context(summary):
    """Yield (line, inside_an_or_wrapper) for each line of a requirement summary."""
    stack = []  # (indent, is_or_wrapper)

    for line in summary.splitlines():
        indent = len(line) - len(line.lstrip())
        while stack and stack[-1][0] >= indent:
            stack.pop()
        inside_or = any(is_or for _indent, is_or in stack)
        yield line, inside_or
        if line.strip().endswith("of the following:"):
            stack.append((indent, not line.strip().startswith("Complete all")))


class StructuredDataTests(unittest.TestCase):
    def test_catalog_is_complete(self):
        self.assertEqual(len(COURSES), 3713)
        for code, details in COURSES.items():
            self.assertTrue(details.get("title"), code)
            for key in ("prerequisite_groups", "requirement_groups", "requirement_summary"):
                self.assertIn(key, details, code)

    def test_csc226_structure(self):
        groups = COURSES["CSC 226"]["requirement_groups"]
        self.assertEqual(len(groups), 2)

        prerequisite, statistics = groups
        self.assertEqual(prerequisite["courses"], ["CSC 225"])
        self.assertEqual(prerequisite["category"], "prerequisite")
        self.assertFalse(prerequisite["concurrent_allowed"])

        self.assertEqual(statistics["courses"], STATS_OPTIONS)
        self.assertEqual(statistics["category"], "pre_or_corequisite")
        self.assertTrue(statistics["concurrent_allowed"])

        self.assertEqual(COURSES["CSC 226"]["prerequisite_groups"], [["CSC 225"], STATS_OPTIONS])
        self.assertFalse(COURSES["CSC 226"]["needs_review"])

    def test_complete_one_of_is_never_split_into_mandatory_groups(self):
        for code, details in COURSES.items():
            group_sets = [set(group) for group in details["prerequisite_groups"]]
            for line, _inside_or in summary_lines_with_context(details["requirement_summary"]):
                match = ONE_OF_LINE.match(line)
                if not match:
                    continue
                options = {c for c in match.group(3).split(", ") if re.fullmatch(r"[A-Z]{2,5} \d{3}[A-Z]?", c)}
                options.discard(code)
                if len(options) < 2:
                    continue
                with self.subTest(course=code, line=line.strip()):
                    self.assertTrue(
                        any(options <= group for group in group_sets),
                        "alternatives must stay together in one group",
                    )
                    for option in options:
                        self.assertNotIn({option}, group_sets, "an alternative became mandatory")

    def test_complete_all_of_requires_every_course(self):
        for code, details in COURSES.items():
            group_lists = details["prerequisite_groups"]
            for line, inside_or in summary_lines_with_context(details["requirement_summary"]):
                match = ALL_OF_LINE.match(line)
                if not match or inside_or:
                    continue
                for course in match.group(2).split(", "):
                    if course == code or not re.fullmatch(r"[A-Z]{2,5} \d{3}[A-Z]?", course):
                        continue
                    with self.subTest(course=code, required=course):
                        self.assertIn([course], group_lists)

    def test_multiple_independent_groups(self):
        self.assertEqual(
            COURSES["CSC 360"]["prerequisite_groups"],
            [["CSC 225"], ["SENG 265"], ["CSC 120", "ENGR 130"], ["CSC 230", "ECE 255"]],
        )

    def test_graph_edges_match_structured_groups(self):
        edges_by_course = {}
        for edge in GRAPH["edges"]:
            edges_by_course.setdefault(edge["to"], set()).add(
                (edge["from"], edge["requirement_group"], edge["requirement_type"], edge["concurrent_allowed"])
            )

        for code, details in COURSES.items():
            expected = {
                (course, index, "any_of" if len(group["courses"]) > 1 else "required", group["concurrent_allowed"])
                for index, group in enumerate(details["requirement_groups"], start=1)
                for course in group["courses"]
            }
            with self.subTest(course=code):
                self.assertEqual(edges_by_course.get(code, set()), expected)

    def test_flagged_courses_explain_why(self):
        for code, details in COURSES.items():
            if details["needs_review"]:
                self.assertTrue(details["review_reasons"], code)


class GuiInterpretationTests(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter
            tkinter.Tk().destroy()
        except Exception as error:
            self.skipTest(f"Tk not available: {error}")

        self.temp = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp.name)
        patches = [
            mock.patch.object(course_gui, "COMPLETED_COURSES_FILE", data_dir / "completed.json"),
            mock.patch.object(course_gui, "WANTED_COURSES_FILE", data_dir / "wanted.json"),
            mock.patch.object(course_gui, "NOTES_FILE", data_dir / "notes.json"),
            mock.patch.object(course_gui, "FLOWCHART_DOT_FILE", data_dir / "flowchart.dot"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

        self.app = course_gui.CoursePostRequisitesApp()
        self.app.withdraw()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.app.destroy)

    def details(self, code):
        return self.app.get_course_details(code)

    def test_gui_groups_match_data(self):
        for code in ("CSC 226", "CSC 360", "MATH 100", "ENT 400"):
            with self.subTest(course=code):
                self.assertEqual(self.app.get_prerequisite_groups(self.details(code)), COURSES[code]["prerequisite_groups"])

    def test_old_format_text_fallback_keeps_alternatives(self):
        old_style = {
            "prerequisite_groups": [["CSC 225"]] + [[c] for c in STATS_OPTIONS],
            "prerequisite_text": COURSES["CSC 226"]["prerequisite_text"],
        }
        groups = self.app.get_requirement_groups(old_style)
        self.assertEqual([g["courses"] for g in groups], [["CSC 225"], STATS_OPTIONS])
        self.assertFalse(groups[0]["concurrent_allowed"])
        self.assertTrue(groups[1]["concurrent_allowed"])

    def test_csc226_display(self):
        text = self.app.format_prerequisites(self.details("CSC 226"))
        self.assertIn("Prerequisites:\n  Complete all of: CSC 225", text)
        self.assertIn(
            "Pre- or corequisites:\n  Completed or concurrently enrolled in 1 of: "
            "GEOG 226, PSYC 300A, STAT 254, STAT 255, STAT 260",
            text,
        )
        self.assertNotIn("Complete all of: STAT", text)

    def test_browse_shows_one_prerequisites_heading(self):
        text = self.app.format_browse_requirements(self.details("PHYS 441"))
        self.assertTrue(text.startswith("Prerequisites:\n"))
        self.assertEqual(text.count("Prerequisites"), 1)
        self.assertNotIn("model exactly", text)

        no_prereq = next(code for code, d in COURSES.items() if d["requirement_summary"] == "No prerequisites listed.")
        self.assertEqual(
            self.app.format_browse_requirements(self.details(no_prereq)),
            "Prerequisites\nNo prerequisites listed.",
        )

    def test_one_statistics_option_is_enough(self):
        stats = self.app.get_requirement_groups(self.details("CSC 226"))[1]
        for option in STATS_OPTIONS:
            self.assertTrue(self.app.course_is_available("CSC 226", {"CSC 225", option}), option)
        self.assertFalse(self.app.requirement_is_satisfied(stats, {"CSC 225"}, allow_concurrent=False))

    def test_csc225_is_still_required(self):
        self.assertFalse(self.app.course_is_available("CSC 226", {"STAT 260"}))

    def test_statistics_can_be_taken_concurrently(self):
        # STAT 255 has no completed-before prerequisites, so CSC 226 is open with just CSC 225:
        # the student can take a statistics option in the same term.
        stat_255_blocking = [
            g for g in self.app.get_requirement_groups(self.details("STAT 255")) if not g["concurrent_allowed"]
        ]
        self.assertEqual(stat_255_blocking, [])
        self.assertTrue(self.app.course_is_available("CSC 226", {"CSC 225"}))

    def test_unlocked_wording(self):
        unlocked = {course: (match, other) for course, match, other in self.app.get_unlocked_courses("STAT 260")}
        match, _other = unlocked["CSC 226"]
        text = self.app.format_unlocked_course_result("CSC 226", match, unlocked["CSC 226"][1], "STAT 260")
        self.assertIn("STAT 260 is one of several options", text)
        self.assertIn("taken at the same time (pre- or corequisite)", text)
        self.assertIn("Completed or concurrently enrolled in 1 of:\n• GEOG 226\n", text)
        self.assertIn("• STAT 260   (searched course)", text)
        self.assertIn("Additional requirements:\n• Complete all of:\n– CSC 225", text)

        unlocked = {course: (match, other) for course, match, other in self.app.get_unlocked_courses("CSC 225")}
        text = self.app.format_unlocked_course_result("CSC 226", *unlocked["CSC 226"], "CSC 225")
        self.assertIn("CSC 225 is required: it must be completed beforehand (prerequisite)", text)

    def test_targets_wording(self):
        self.app.completed_courses = ["CSC 225"]
        self.app.show_wanted_courses_page()
        self.app.display_wanted_course_details("CSC 226")
        text = self.app.wanted_results.get("1.0", "end")
        self.assertIn("Met: Complete all of: CSC 225", text)
        self.assertIn("Needed (can be taken at the same time): Completed or concurrently enrolled in 1 of:", text)
        self.assertIn("same term", text)

    def test_flowchart_edges_for_csc226(self):
        nodes = {"CSC 226", "CSC 225", *STATS_OPTIONS}
        edges = {(s, t, kind) for s, t, kind, _group in self.app.get_flowchart_edges(nodes)}
        self.assertIn(("CSC 225", "CSC 226", "required"), edges)
        for option in STATS_OPTIONS:
            self.assertIn((option, "CSC 226", "any_of"), edges)
            self.assertNotIn((option, "CSC 226", "required"), edges)


if __name__ == "__main__":
    unittest.main()
