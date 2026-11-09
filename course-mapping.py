"""Query the bundled UVic course prerequisite data.

Course data is stored in course_graph.json, which ships with this repository.
This tool works entirely offline and never contacts the UVic website.
"""

import argparse
import json
import re
from pathlib import Path


GRAPH_FILE = Path(__file__).with_name("course_graph.json")
COURSE_CODE_PATTERN = re.compile(r"\b([A-Z]{2,5})\s*(\d{3}[A-Z]?)\b")


def normalize_user_course(text):
    match = COURSE_CODE_PATTERN.search(text.upper())

    if match:
        return f"{match.group(1)} {match.group(2)}"

    return text.strip().upper()


def load_courses():
    if not GRAPH_FILE.exists():
        print(f"{GRAPH_FILE.name} was not found.")
        raise SystemExit(1)

    graph = json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
    return graph.get("courses", {})


def get_prereq_groups(course_details):
    return [group["courses"] for group in get_requirement_groups(course_details)]


def get_requirement_groups(course_details):
    if not isinstance(course_details, dict):
        return [{"courses": group, "concurrent_allowed": False, "category": "prerequisite"} for group in course_details]

    if isinstance(course_details.get("requirement_groups"), list):
        return [group for group in course_details["requirement_groups"] if group.get("courses")]

    return [
        {"courses": group, "concurrent_allowed": False, "category": "prerequisite"}
        for group in course_details.get("prerequisite_groups", [])
    ]


def format_complete_group(group):
    if len(group) > 1:
        return f"Complete 1 of: {', '.join(group)}"

    return f"Complete all of: {group[0]}"


def format_requirements(prereq_groups):
    if not prereq_groups:
        return "no prerequisites found"

    return "; ".join(format_complete_group(group) for group in prereq_groups)


def print_unlocked_courses(target_course, courses):
    unlocked_courses = []

    for course, details in sorted(courses.items()):
        requirements = get_requirement_groups(details)
        matching_groups = [
            requirement for requirement in requirements if target_course in requirement["courses"]
        ]

        if not matching_groups:
            continue

        other_required_groups = [
            requirement["courses"] for requirement in requirements if target_course not in requirement["courses"]
        ]

        unlocked_courses.append((course, matching_groups, other_required_groups))

    print()

    if not unlocked_courses:
        print(f"No loaded courses list {target_course} as a prerequisite.")
        return

    print(f"Courses that list {target_course} as a prerequisite:")

    for course, matching_groups, other_required_groups in unlocked_courses:
        print(f"\n{course}")

        for requirement in matching_groups:
            group = requirement["courses"]

            if requirement.get("category") == "corequisite":
                timing = "must be taken at the same time (corequisite)"
            elif requirement.get("concurrent_allowed"):
                timing = "can be completed beforehand or taken at the same time"
            else:
                timing = "must be completed beforehand"

            if len(group) == 1:
                print(f"  - {target_course} is required: it {timing}.")
            else:
                print(f"  - {target_course} is one option: it {timing}.")
                print(f"    1 of: {', '.join(group)}")

        if other_required_groups:
            print(f"  - Additional requirements: {format_requirements(other_required_groups)}")


def main():
    parser = argparse.ArgumentParser(
        description="Show which UVic courses list a given course as a prerequisite."
    )
    parser.add_argument(
        "course",
        nargs="?",
        help="Course to check, such as CSC 225.",
    )
    args = parser.parse_args()

    if args.course:
        user_input = args.course
    else:
        print()
        user_input = input("Enter the course you want to check (e.g. CSC 225): ")

    target_course = normalize_user_course(user_input)
    print_unlocked_courses(target_course, load_courses())


if __name__ == "__main__":
    main()
