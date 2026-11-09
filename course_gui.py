import json
import os
import re
import shutil
import shlex
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from pathlib import Path
from tkinter import messagebox


APP_NAME = "UVic Course Mapping"
IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform.startswith("win")


def resource_dir():
    # Bundled read-only files (course data, icon). PyInstaller unpacks them to _MEIPASS.
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))

    return Path(__file__).resolve().parent


def user_data_dir():
    # Each person's own saved courses, targets and notes live outside the app folder,
    # so downloads start clean and updating the app never wipes anyone's plan.
    if IS_WINDOWS:
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif IS_MAC:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")

    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


RESOURCE_DIR = resource_dir()
DATA_DIR = user_data_dir()
COURSE_GRAPH_FILE = RESOURCE_DIR / "course_graph.json"
APP_ICON_FILE = RESOURCE_DIR / "assets" / "icon-256.png"
COMPLETED_COURSES_FILE = DATA_DIR / "completed_courses.json"
NOTES_FILE = DATA_DIR / "course_notes.json"
WANTED_COURSES_FILE = DATA_DIR / "wanted_courses.json"
FLOWCHART_DOT_FILE = DATA_DIR / "flowchart.dot"
FLOWCHART_SVG_FILE = DATA_DIR / "flowchart.svg"

# Tk point sizes render noticeably smaller on macOS than on Windows, so scale per platform.
UI_FONT_FAMILY = "Segoe UI" if IS_WINDOWS else ("Helvetica Neue" if IS_MAC else "DejaVu Sans")
FONT_SCALE = 1.45 if IS_MAC else 1.15


def ui_font(size, *styles):
    return (UI_FONT_FAMILY, round(size * FONT_SCALE), *styles)


# Matches course-like codes in any case, with or without a space: "csc110", "CSC 110", "Psyc100a".
COURSE_ENTRY_PATTERN = re.compile(r"(?<![A-Za-z])([A-Za-z]{2,5})\s*(\d{3}[A-Za-z]?)(?![A-Za-z0-9])")
COURSE_NOT_FOUND_MESSAGE = "Course not found in the current catalog. Please check the course code."
REQUIREMENT_PREREQUISITE = "prerequisite"
REQUIREMENT_PRE_OR_COREQUISITE = "pre_or_corequisite"
REQUIREMENT_COREQUISITE = "corequisite"
ALL_SUBJECTS_LABEL = "All subjects"


def parse_course_entries(text, known_courses):
    """Split user input into catalog courses and rejected entries.

    Entries are separated by commas, semicolons or new lines. Returns
    (valid, rejected): valid holds normalized codes found in known_courses,
    rejected holds the text the user typed for anything that isn't.
    """
    valid = []
    rejected = []

    for chunk in re.split(r"[,;\n]+", text):
        chunk = " ".join(chunk.split())

        if not chunk:
            continue

        matches = list(COURSE_ENTRY_PATTERN.finditer(chunk))

        if not matches:
            if chunk not in rejected:
                rejected.append(chunk)
            continue

        for match in matches:
            code = f"{match.group(1).upper()} {match.group(2).upper()}"

            if code in known_courses:
                if code not in valid:
                    valid.append(code)
            elif match.group(0) not in rejected:
                rejected.append(match.group(0))

    return valid, rejected


def build_course_catalog(course_graph):
    """Sorted (code, title) pairs for every course in the bundled database."""
    return sorted(
        (code, (details or {}).get("title", "") if isinstance(details, dict) else "")
        for code, details in course_graph.get("courses", {}).items()
    )


def filter_course_catalog(catalog, query="", subject=""):
    """Filter (code, title) pairs by a search query and an optional subject code."""
    query = " ".join(query.lower().split())
    compact_query = query.replace(" ", "")
    subject = "" if subject == ALL_SUBJECTS_LABEL else subject
    matches = []

    for code, title in catalog:
        if subject and code.split(" ")[0] != subject:
            continue

        if query and query not in title.lower() and compact_query not in code.lower().replace(" ", ""):
            continue

        matches.append((code, title))

    return matches
COURSE_CODE_PATTERN = re.compile(r"\b([A-Z]{2,5})\s*(\d{3}[A-Z]?)\b")
UVIC_DARK_BLUE = "#002754"
UVIC_BLUE = "#005493"
UVIC_GREEN = "#26A739"
UVIC_YELLOW = "#F5AA1C"
UVIC_LIGHT_BLUE = "#BEE7F9"
APP_BACKGROUND = "#edf6fa"
CARD_BACKGROUND = "#ffffff"
PANEL_BACKGROUND = "#f4fbff"
MUTED_PANEL = "#e8f3f8"
ACCENT_BACKGROUND = UVIC_DARK_BLUE


class CoursePostRequisitesApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title(APP_NAME)
        self.geometry("1400x850")
        self.minsize(1120, 700)
        self.configure(background=APP_BACKGROUND)
        self.set_window_icon()
        self.configure_app_style()

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.container = ttk.Frame(self, padding=24, style="App.TFrame")
        self.container.grid(row=0, column=0, sticky="nsew")
        self.container.columnconfigure(0, weight=1)
        self.container.rowconfigure(0, weight=1)
        self.completed_courses = self.load_completed_courses()
        self.course_graph = self.load_course_graph()
        self.notes = self.load_notes()
        self.wanted_courses = self.load_wanted_courses()
        self.flowchart_nodes = set()
        self.flowchart_completed_courses = set()
        self.flowchart_preview_course = None
        self.flowchart_direct_preview = False
        self.flowchart_scale = 1.0
        self.flowchart_selected_course = None
        self.flowchart_no_prereq_courses = []
        self.graphviz_dot_path = None
        self.flowchart_layout_cache = {}

        self.show_home_page()

    def set_window_icon(self):
        if not APP_ICON_FILE.exists():
            return

        try:
            self.window_icon = tk.PhotoImage(file=str(APP_ICON_FILE))
            self.iconphoto(True, self.window_icon)
        except tk.TclError:
            pass

    def configure_default_fonts(self):
        base_size = ui_font(11)[1]

        for name in (
            "TkDefaultFont",
            "TkTextFont",
            "TkMenuFont",
            "TkHeadingFont",
            "TkCaptionFont",
            "TkTooltipFont",
        ):
            try:
                tkfont.nametofont(name).configure(family=UI_FONT_FAMILY, size=base_size)
            except tk.TclError:
                pass

    def configure_app_style(self):
        self.configure_default_fonts()
        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self.style.configure("App.TFrame", background=APP_BACKGROUND)
        self.style.configure("Card.TFrame", background=CARD_BACKGROUND, relief="flat")
        self.style.configure("Panel.TFrame", background=PANEL_BACKGROUND, relief="flat")
        self.style.configure("Menu.TFrame", background=PANEL_BACKGROUND)
        self.style.configure("ButtonRow.TFrame", background=PANEL_BACKGROUND)
        self.style.configure("Hero.TFrame", background=ACCENT_BACKGROUND)
        self.style.configure("TLabel", background=PANEL_BACKGROUND, foreground=UVIC_DARK_BLUE)
        self.style.configure("Card.TLabel", background=CARD_BACKGROUND, foreground=UVIC_DARK_BLUE)
        self.style.configure("Panel.TLabel", background=PANEL_BACKGROUND, foreground=UVIC_DARK_BLUE)
        self.style.configure("App.TLabel", background=APP_BACKGROUND, foreground=UVIC_DARK_BLUE)
        self.style.configure("Hero.TLabel", background=ACCENT_BACKGROUND, foreground="#ffffff")
        self.style.configure(
            "PageTitle.TLabel",
            background=PANEL_BACKGROUND,
            foreground=UVIC_DARK_BLUE,
            font=ui_font(24, "bold"),
        )
        self.style.configure(
            "AppTitle.TLabel",
            background=APP_BACKGROUND,
            foreground=UVIC_DARK_BLUE,
            font=ui_font(26, "bold"),
        )
        self.style.configure(
            "Section.TLabel",
            background=PANEL_BACKGROUND,
            foreground=UVIC_BLUE,
            font=ui_font(11, "bold"),
        )
        self.style.configure(
            "Title.TLabel",
            background=APP_BACKGROUND,
            foreground=UVIC_DARK_BLUE,
            font=ui_font(28, "bold"),
        )
        self.style.configure(
            "Subtitle.TLabel",
            background=APP_BACKGROUND,
            foreground=UVIC_BLUE,
            font=ui_font(11),
        )
        self.style.configure(
            "Primary.TButton",
            background=UVIC_BLUE,
            foreground="#ffffff",
            borderwidth=0,
            focusthickness=3,
            focuscolor=UVIC_LIGHT_BLUE,
            padding=(14, 8),
        )
        self.style.map(
            "Primary.TButton",
            background=[("active", UVIC_DARK_BLUE), ("disabled", "#94a3b8")],
            foreground=[("disabled", "#e2e8f0")],
        )
        self.style.configure(
            "Accent.TButton",
            background=UVIC_YELLOW,
            foreground=UVIC_DARK_BLUE,
            borderwidth=0,
            padding=(14, 8),
        )
        self.style.map("Accent.TButton", background=[("active", "#ffd15a")])
        self.style.configure(
            "Plan.TButton",
            background="#e3f1f7",
            foreground=UVIC_DARK_BLUE,
            borderwidth=0,
            padding=(18, 12),
            anchor="center",
        )
        self.style.configure(
            "Explore.TButton",
            background="#e8f7ea",
            foreground=UVIC_DARK_BLUE,
            borderwidth=0,
            padding=(18, 12),
            anchor="center",
        )
        self.style.configure(
            "Info.TButton",
            background="#dff3fb",
            foreground=UVIC_DARK_BLUE,
            borderwidth=0,
            padding=(18, 12),
            anchor="center",
        )
        self.style.configure(
            "Personal.TButton",
            background="#fff2d4",
            foreground=UVIC_DARK_BLUE,
            borderwidth=0,
            padding=(18, 12),
            anchor="center",
        )
        self.style.map("Plan.TButton", background=[("active", UVIC_LIGHT_BLUE)])
        self.style.map("Explore.TButton", background=[("active", "#d2f0d6")])
        self.style.map("Info.TButton", background=[("active", UVIC_LIGHT_BLUE)])
        self.style.map("Personal.TButton", background=[("active", "#ffe4a3")])
        self.style.configure(
            "Back.TButton",
            background="#d6e8f0",
            foreground=UVIC_DARK_BLUE,
            borderwidth=0,
            padding=(18, 10),
            width=16,
        )
        self.style.map("Back.TButton", background=[("active", UVIC_LIGHT_BLUE)])
        self.style.configure("TButton", padding=(12, 7))
        self.style.configure("Primary.TButton", font=ui_font(12, "bold"), padding=(20, 11))
        self.style.configure("Accent.TButton", font=ui_font(12, "bold"))
        for tile_style in ("Plan.TButton", "Explore.TButton", "Info.TButton", "Personal.TButton"):
            self.style.configure(tile_style, font=ui_font(13, "bold"))
        self.style.configure("Back.TButton", font=ui_font(11, "bold"))
        self.style.configure(
            "TEntry",
            fieldbackground="#ffffff",
            padding=7,
            bordercolor="#c9dbe6",
            lightcolor="#c9dbe6",
            darkcolor="#c9dbe6",
        )
        self.style.map(
            "TEntry",
            bordercolor=[("focus", UVIC_BLUE)],
            lightcolor=[("focus", UVIC_BLUE)],
        )
        self.style.configure("Vertical.TScrollbar", background="#d6e8f0", troughcolor=PANEL_BACKGROUND, borderwidth=0, arrowcolor=UVIC_DARK_BLUE)

        for widget in ("Listbox", "Text"):
            self.option_add(f"*{widget}.background", "#ffffff")
            self.option_add(f"*{widget}.foreground", UVIC_DARK_BLUE)
            self.option_add(f"*{widget}.font", ui_font(11))
            self.option_add(f"*{widget}.borderWidth", 0)
            self.option_add(f"*{widget}.relief", "flat")
            self.option_add(f"*{widget}.highlightThickness", 1)
            self.option_add(f"*{widget}.highlightBackground", "#c9dbe6")
            self.option_add(f"*{widget}.highlightColor", UVIC_BLUE)
            self.option_add(f"*{widget}.selectBackground", UVIC_BLUE)
            self.option_add(f"*{widget}.selectForeground", "#ffffff")
        self.option_add("*Listbox.activeStyle", "none")
        self.option_add("*Text.padX", 10)
        self.option_add("*Text.padY", 8)
        self.option_add("*Text.spacing1", 2)
        self.option_add("*Text.spacing3", 2)
        self.option_add("*Text.insertBackground", UVIC_DARK_BLUE)

    def load_completed_courses(self):
        if not COMPLETED_COURSES_FILE.exists():
            return []

        try:
            data = json.loads(COMPLETED_COURSES_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

        courses = data.get("completed_courses", [])

        if not isinstance(courses, list):
            return []

        return sorted(set(courses))

    def save_completed_courses(self):
        data = {
            "completed_courses": sorted(set(self.completed_courses)),
        }
        COMPLETED_COURSES_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_course_graph(self):
        if not COURSE_GRAPH_FILE.exists():
            return {"courses": {}, "nodes": [], "edges": []}

        try:
            graph = json.loads(COURSE_GRAPH_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"courses": {}, "nodes": [], "edges": []}

        if not isinstance(graph, dict):
            return {"courses": {}, "nodes": [], "edges": []}

        if not isinstance(graph.get("courses"), dict):
            graph["courses"] = {}

        if not isinstance(graph.get("nodes"), list):
            graph["nodes"] = []

        if not isinstance(graph.get("edges"), list):
            graph["edges"] = []

        return graph

    def load_notes(self):
        if not NOTES_FILE.exists():
            return [{"title": "New Note", "body": ""}]

        try:
            data = json.loads(NOTES_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return [{"title": "New Note", "body": ""}]

        notes = data.get("notes", [])

        if not isinstance(notes, list) or not notes:
            return [{"title": "New Note", "body": ""}]

        return notes

    def save_notes(self):
        NOTES_FILE.write_text(
            json.dumps({"notes": self.notes}, indent=2),
            encoding="utf-8",
        )

    def load_wanted_courses(self):
        if not WANTED_COURSES_FILE.exists():
            return []

        try:
            data = json.loads(WANTED_COURSES_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

        courses = data.get("wanted_courses", [])

        if not isinstance(courses, list):
            return []

        return sorted(set(courses))

    def save_wanted_courses(self):
        WANTED_COURSES_FILE.write_text(
            json.dumps({"wanted_courses": sorted(set(self.wanted_courses))}, indent=2),
            encoding="utf-8",
        )

        try:
            return json.loads(COURSE_GRAPH_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"courses": {}, "nodes": [], "edges": []}

    def clear_page(self):
        for child in self.container.winfo_children():
            child.destroy()

    def create_page_header(self, page, title_text, back_command=None, back_text="Back"):
        header = ttk.Frame(page, style="Panel.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        header.columnconfigure(0, weight=1)

        title = ttk.Label(
            header,
            text=title_text,
            style="PageTitle.TLabel",
        )
        title.grid(row=0, column=0, sticky="w")

        back_button = ttk.Button(
            header,
            text=back_text,
            command=back_command or self.show_lookup_page,
            style="Back.TButton",
        )
        back_button.grid(row=0, column=1, sticky="e")

        return header

    def show_home_page(self):
        self.clear_page()

        page = ttk.Frame(self.container, style="App.TFrame")
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)

        content = ttk.Frame(page, padding=0, style="Card.TFrame")
        content.grid(row=0, column=0)
        content.columnconfigure(0, weight=1)

        hero = ttk.Frame(content, padding=(36, 28), style="Hero.TFrame")
        hero.grid(row=0, column=0, sticky="ew")
        hero.columnconfigure(0, weight=1)

        title = ttk.Label(
            hero,
            text=APP_NAME,
            font=ui_font(30, "bold"),
            style="Hero.TLabel",
        )
        title.grid(row=0, column=0, sticky="w", pady=(0, 8))

        subtitle = ttk.Label(
            hero,
            text="A friendlier way to explore UVic prerequisites, unlocked courses, and degree paths.",
            font=ui_font(12),
            style="Hero.TLabel",
        )
        subtitle.grid(row=1, column=0, sticky="w")

        body = ttk.Frame(content, padding=36, style="Card.TFrame")
        body.grid(row=1, column=0, sticky="ew")
        body.columnconfigure(0, weight=1)

        message = ttk.Label(
            body,
            text="Start planning from your saved courses, target courses, notes, and flowcharts.",
            font=ui_font(12),
            style="Card.TLabel",
        )
        message.grid(row=0, column=0, sticky="w", pady=(0, 20))

        open_button = ttk.Button(
            body,
            text="Enter Course Planning Space",
            command=self.show_lookup_page,
            style="Primary.TButton",
        )
        open_button.grid(row=1, column=0, sticky="w")

    def show_lookup_page(self):
        self.clear_page()

        page = ttk.Frame(self.container, style="App.TFrame")
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)

        accent = tk.Canvas(
            page,
            height=96,
            background=APP_BACKGROUND,
            highlightthickness=0,
        )
        accent.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        accent.create_rectangle(0, 0, 4000, 96, fill=UVIC_DARK_BLUE, outline="")
        accent.create_rectangle(0, 84, 4000, 96, fill=UVIC_YELLOW, outline="")
        accent.create_oval(650, -120, 880, 110, fill=UVIC_BLUE, outline="")
        accent.create_oval(530, 28, 710, 208, fill=UVIC_GREEN, outline="")
        accent.create_oval(730, 36, 850, 156, fill=UVIC_YELLOW, outline="")
        accent.create_text(
            28,
            34,
            text="Planning Space",
            anchor="w",
            fill="#ffffff",
            font=ui_font(25, "bold"),
        )
        accent.create_text(
            30,
            68,
            text="Choose what you want to work on.",
            anchor="w",
            fill=UVIC_LIGHT_BLUE,
            font=ui_font(11),
        )

        actions = ttk.Frame(page, padding=18, style="Menu.TFrame")
        actions.grid(row=1, column=0, sticky="nsew", pady=(0, 16))

        for column in range(3):
            actions.columnconfigure(column, weight=1, uniform="menu")
        for row in range(3):
            actions.rowconfigure(row, weight=1, uniform="menu")

        menu_items = (
            ("My Plan", self.show_taken_courses_page, "Plan.TButton"),
            ("Unlocked", self.show_unlocked_courses_page, "Explore.TButton"),
            ("Flowchart", self.show_flowchart_page, "Explore.TButton"),
            ("Details", self.show_course_information_page, "Info.TButton"),
            ("Prereqs", self.show_course_prerequisites_page, "Info.TButton"),
            ("Targets", self.show_wanted_courses_page, "Personal.TButton"),
            ("Notes", self.show_notes_page, "Personal.TButton"),
            ("Browse Courses", self.show_browse_courses_page, "Info.TButton"),
        )

        for index, (label, command, style) in enumerate(menu_items):
            row = index // 3
            column = index % 3
            button = ttk.Button(
                actions,
                text=label,
                command=command,
                style=style,
            )
            button.grid(
                row=row,
                column=column,
                sticky="nsew",
                padx=(0 if column == 0 else 10, 0),
                pady=(0 if row == 0 else 10, 0),
                ipady=10,
            )

        back_button = ttk.Button(
            page,
            text="Back",
            command=self.show_home_page,
            style="Back.TButton",
        )
        back_button.grid(row=2, column=0, sticky="e")

    def show_placeholder_page(self, title_text, message_text):
        self.clear_page()

        page = ttk.Frame(self.container, padding=28, style="Panel.TFrame")
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)

        self.create_page_header(page, title_text)

        message = ttk.Label(
            page,
            text=message_text,
            font=ui_font(12),
            style="Panel.TLabel",
        )
        message.grid(row=1, column=0, sticky="w", pady=(0, 24))

    def show_taken_courses_page(self):
        self.clear_page()

        page = ttk.Frame(self.container, padding=28, style="Panel.TFrame")
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(4, weight=1)

        self.create_page_header(page, "My Plan")

        input_label = ttk.Label(
            page,
            text="Add completed courses",
            style="Section.TLabel",
        )
        input_label.grid(row=1, column=0, sticky="w", pady=(0, 4))

        input_example = ttk.Label(
            page,
            text="ex. ATWP 135 or CSC 225, SENG 310, etc.",
            font=ui_font(10),
            style="Panel.TLabel",
        )
        input_example.grid(row=2, column=0, sticky="w", pady=(0, 6))

        entry_row = ttk.Frame(page, style="Panel.TFrame")
        entry_row.grid(row=3, column=0, sticky="ew", pady=(0, 16))
        entry_row.columnconfigure(0, weight=1)

        self.completed_courses_text = tk.Text(
            entry_row,
            height=3,
            wrap=tk.WORD,
        )
        self.completed_courses_text.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.completed_courses_text.bind("<Control-Return>", self.add_completed_courses_from_input)

        add_button = ttk.Button(
            entry_row,
            text="Add",
            command=self.add_completed_courses_from_input,
            style="Plan.TButton",
        )
        add_button.grid(row=0, column=1, sticky="ns")

        list_frame = ttk.Frame(page, style="Panel.TFrame")
        list_frame.grid(row=4, column=0, sticky="nsew", pady=(0, 16))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.completed_course_list = tk.Listbox(
            list_frame,
            height=16,
            selectmode=tk.SINGLE,
            font=ui_font(10),
        )
        self.completed_course_list.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(
            list_frame,
            orient=tk.VERTICAL,
            command=self.completed_course_list.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.completed_course_list.configure(yscrollcommand=scrollbar.set)

        button_row = ttk.Frame(page, style="ButtonRow.TFrame")
        button_row.grid(row=5, column=0, sticky="ew")

        remove_button = ttk.Button(
            button_row,
            text="Remove",
            command=self.remove_selected_completed_course,
            style="Personal.TButton",
        )
        remove_button.grid(row=0, column=0, padx=(0, 8))

        self.refresh_completed_course_list()

    def normalize_course_input(self, text):
        cleaned = " ".join(text.strip().upper().split())

        if not cleaned:
            return ""

        match = COURSE_CODE_PATTERN.search(cleaned)

        if match:
            return f"{match.group(1)} {match.group(2)}"

        return cleaned

    def extract_course_codes(self, text):
        courses = []

        for subject, number in COURSE_CODE_PATTERN.findall(text.upper()):
            course = f"{subject} {number}"

            if course not in courses:
                courses.append(course)

        return courses

    def refresh_completed_course_list(self):
        self.completed_course_list.delete(0, tk.END)

        for course in sorted(self.completed_courses):
            self.completed_course_list.insert(tk.END, course)

    def known_course_codes(self):
        return self.course_graph.get("courses", {})

    def report_course_entry_results(self, added, already, rejected, already_label):
        lines = []

        if added:
            lines.append(f"Added: {', '.join(added)}")

        if already:
            lines.append(f"{already_label}: {', '.join(already)}")

        if rejected:
            lines.append(
                f"Not found in the current course database: {', '.join(rejected)}\n\n"
                f"{COURSE_NOT_FOUND_MESSAGE}\n"
                "(The database is a snapshot of the UVic calendar, so a missing course may still exist at UVic.)"
            )
            title = "Course Not Found" if not (added or already) else "Some Courses Not Found"
            messagebox.showwarning(title, "\n\n".join(lines))
        elif added:
            messagebox.showinfo("Courses Added", "\n\n".join(lines))
        else:
            messagebox.showinfo("Already Added", "\n\n".join(lines))

    def add_completed_courses_from_input(self, event=None):
        text = self.completed_courses_text.get("1.0", tk.END)
        courses, rejected = parse_course_entries(text, self.known_course_codes())

        if not courses and not rejected:
            messagebox.showinfo("No Courses Found", "Enter one or more course codes, such as CSC 110, MATH 100.")
            return "break"

        added = [course for course in courses if course not in self.completed_courses]
        already = [course for course in courses if course in self.completed_courses]

        if added:
            self.completed_courses = sorted(set(self.completed_courses + added))
            self.save_completed_courses()
            self.refresh_completed_course_list()

        # Leave anything rejected in the box so it can be corrected.
        self.completed_courses_text.delete("1.0", tk.END)
        self.completed_courses_text.insert("1.0", ", ".join(rejected))
        self.report_course_entry_results(added, already, rejected, "Already in your plan")
        return "break"

    def remove_selected_completed_course(self):
        selected_indexes = self.completed_course_list.curselection()

        if not selected_indexes:
            return

        selected_course = self.completed_course_list.get(selected_indexes[0])
        self.completed_courses = [
            course for course in self.completed_courses if course != selected_course
        ]
        self.save_completed_courses()
        self.refresh_completed_course_list()

    def show_unlocked_courses_page(self):
        self.clear_page()

        page = ttk.Frame(self.container, padding=28, style="Panel.TFrame")
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(3, weight=1)

        self.create_page_header(page, "Unlocked/Post-requisites")

        entry_row = ttk.Frame(page, style="Panel.TFrame")
        entry_row.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        entry_row.columnconfigure(0, weight=1)

        self.unlocked_course_entry = ttk.Entry(entry_row)
        self.unlocked_course_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.unlocked_course_entry.bind("<Return>", self.check_unlocked_courses)

        check_button = ttk.Button(
            entry_row,
            text="Check",
            command=self.check_unlocked_courses,
            style="Explore.TButton",
        )
        check_button.grid(row=0, column=1)

        graph_course_count = len(self.course_graph.get("courses", {}))
        summary_text = (
            "Enter a course code to see which courses list it as a prerequisite."
            if graph_course_count
            else "No graph data loaded. course_graph.json is missing or invalid."
        )

        self.unlocked_summary = ttk.Label(
            page,
            text=summary_text,
            style="Panel.TLabel",
        )
        self.unlocked_summary.grid(row=2, column=0, sticky="w", pady=(0, 8))

        result_frame = ttk.Frame(page, style="Panel.TFrame")
        result_frame.grid(row=3, column=0, sticky="nsew", pady=(0, 8))
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)

        self.unlocked_results = tk.Text(
            result_frame,
            wrap=tk.WORD,
            height=14,
            state=tk.DISABLED,
        )
        self.unlocked_results.grid(row=0, column=0, sticky="nsew")
        self.configure_unlocked_result_tags()

        scrollbar = ttk.Scrollbar(
            result_frame,
            orient=tk.VERTICAL,
            command=self.unlocked_results.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.unlocked_results.configure(yscrollcommand=scrollbar.set)

    def configure_unlocked_result_tags(self):
        text = self.unlocked_results
        text.tag_configure("unlocked_code", font=ui_font(11, "bold"), foreground=UVIC_DARK_BLUE, spacing1=12)
        text.tag_configure("unlocked_title", foreground=UVIC_BLUE)
        text.tag_configure("unlocked_line", lmargin1=16, lmargin2=16)
        text.tag_configure("unlocked_item", lmargin1=28, lmargin2=40)
        text.tag_configure("unlocked_note", lmargin1=16, lmargin2=16, foreground=UVIC_BLUE)

    def get_unlocked_courses(self, target_course):
        courses = self.course_graph.get("courses", {})
        unlocked = []

        for course, details in sorted(courses.items()):
            requirements = self.get_requirement_groups(details)
            matching_groups = [
                requirement for requirement in requirements
                if target_course in requirement["courses"]
            ]

            if not matching_groups:
                continue

            other_required_groups = [
                requirement for requirement in requirements
                if target_course not in requirement["courses"]
            ]
            unlocked.append((course, matching_groups, other_required_groups))

        return unlocked

    UNLOCKED_MAX_LINES = 6
    UNLOCKED_MAX_LISTED_OPTIONS = 4

    def requirement_timing_note(self, requirement):
        if requirement.get("category") == REQUIREMENT_COREQUISITE:
            return " (must be taken in the same term)"

        if requirement.get("concurrent_allowed"):
            return " (can be taken at the same time)"

        return ""

    @staticmethod
    def join_courses(courses, word):
        courses = list(courses)

        if len(courses) <= 1:
            return "".join(courses)

        return f"{', '.join(courses[:-1])} {word} {courses[-1]}"

    @staticmethod
    def clean_requirement_note(note):
        text = note.strip()
        alternative = False

        while text.lower().startswith("alternatively:"):
            text = text[len("alternatively:"):].strip()
            alternative = True

        if text.lower().startswith("or "):
            text = text[3:].strip()
            alternative = True

        text = text.rstrip(". ").strip()

        if not text:
            return ""

        if alternative:
            return f"Alternative way to qualify: {text}"

        return text[0].upper() + text[1:]

    def unlocked_role_line(self, target_course, matching_groups):
        required = [group for group in matching_groups if len(group["courses"]) == 1]
        requirement = required[0] if required else matching_groups[0]
        timing = self.requirement_timing_note(requirement)

        if required:
            return f"{target_course} is required{timing}."

        if len(matching_groups) > 1:
            return f"{target_course} is part of one of the accepted combinations{timing}."

        kind = {
            REQUIREMENT_PREREQUISITE: "prerequisite ",
            REQUIREMENT_COREQUISITE: "corequisite ",
        }.get(requirement.get("category"), "")
        return f"{target_course} is one of the accepted {kind}options{timing}."

    def summarize_unlocked_course(self, course, matching_groups, other_required_groups, target_course):
        """Short, readable summary of one course for the Unlocked page.

        Returns role (how the searched course counts), lines (other requirements), covered
        (which other groups each line stands for) and summarized (True when detail was left out,
        so the page points to Prereqs). Presentation only; nothing here changes requirement logic.
        """
        details = self.get_course_details(course) or {}
        summarized = bool(details.get("needs_review"))
        lines = []
        covered = []

        # Mandatory single courses, grouped by when they can be taken.
        mandatory = {}

        for index, requirement in enumerate(other_required_groups):
            if len(requirement["courses"]) == 1:
                timing = self.requirement_timing_note(requirement)
                mandatory.setdefault(timing, []).append((index, requirement["courses"][0]))

        for timing, items in mandatory.items():
            lines.append(self.join_courses([code for _index, code in items], "and") + timing)
            covered.append([index for index, _code in items])

        # Alternative groups. Groups that share courses are overlapping combinations of one
        # nested rule, so they are described in general terms instead of listed.
        alternatives = [
            index for index, requirement in enumerate(other_required_groups)
            if len(requirement["courses"]) > 1
        ]
        clusters = []

        for index in alternatives:
            options = set(other_required_groups[index]["courses"])
            joined = [cluster for cluster in clusters if options & cluster["courses"]]

            for cluster in joined:
                clusters.remove(cluster)

            clusters.append({
                "indexes": sorted([index] + [i for cluster in joined for i in cluster["indexes"]]),
                "courses": options.union(*[cluster["courses"] for cluster in joined]),
            })

        clusters.sort(key=lambda cluster: cluster["indexes"][0])

        for cluster in clusters:
            first = other_required_groups[cluster["indexes"][0]]
            timing = self.requirement_timing_note(first)

            if len(cluster["indexes"]) == 1:
                options = first["courses"]

                if len(options) <= self.UNLOCKED_MAX_LISTED_OPTIONS:
                    lines.append(f"One of {self.join_courses(options, 'or')}{timing}")
                else:
                    lines.append(f"One of {', '.join(options[:3])} or {len(options) - 3} other courses{timing}")
                    summarized = True
            else:
                subjects = {}
                for code in sorted(cluster["courses"]):
                    subject = code.split(" ")[0]
                    subjects[subject] = subjects.get(subject, 0) + 1
                top = sorted(subjects, key=lambda subject: -subjects[subject])[:2]
                lines.append(f"{'/'.join(top)} requirement — multiple accepted combinations{timing}")
                summarized = True

            covered.append(cluster["indexes"])

        notes = []
        for note in details.get("requirement_notes") or []:
            cleaned = self.clean_requirement_note(note)
            if cleaned and cleaned not in notes:
                notes.append(cleaned)

        lines.extend(notes)

        if len(lines) > self.UNLOCKED_MAX_LINES:
            hidden = len(lines) - (self.UNLOCKED_MAX_LINES - 1)
            lines = lines[: self.UNLOCKED_MAX_LINES - 1] + [f"{hidden} more requirements"]
            summarized = True

        return {
            "role": self.unlocked_role_line(target_course, matching_groups),
            "lines": lines,
            "covered": covered,
            "summarized": summarized,
        }

    def build_unlocked_course_segments(self, course, matching_groups, other_required_groups, target_course):
        """(text, tag) pieces for one course on the Unlocked page."""
        details = self.get_course_details(course) or {}
        summary = self.summarize_unlocked_course(course, matching_groups, other_required_groups, target_course)
        segments = [(course, "unlocked_code")]

        if details.get("title"):
            segments.append((f" — {details['title']}", "unlocked_title"))

        segments.append(("\n", "unlocked_code"))
        segments.append((f"{summary['role']}\n", "unlocked_line"))

        if summary["lines"]:
            segments.append(("Other requirements:\n", "unlocked_line"))
            segments.extend((f"• {line}\n", "unlocked_item") for line in summary["lines"])
        else:
            segments.append(("No other requirements listed.\n", "unlocked_line"))

        if summary["summarized"]:
            segments.append(("See Prereqs for full requirements.\n", "unlocked_note"))

        return segments

    def format_unlocked_course_result(self, course, matching_groups, other_required_groups, target_course):
        segments = self.build_unlocked_course_segments(
            course, matching_groups, other_required_groups, target_course
        )
        return "".join(text for text, _tag in segments).rstrip("\n")

    def format_requirement_group(self, group):
        if len(group) > 1:
            return f"Complete 1 of: {', '.join(group)}"

        return f"Complete all of: {group[0]}"

    def get_course_details(self, course):
        return self.course_graph.get("courses", {}).get(course)

    def get_requirement_groups(self, course_details):
        """Requirement groups as dicts: courses (any one satisfies the group), category, concurrent_allowed.

        Uses the structured requirement_groups from course_graph.json. Older data without them
        falls back to parsing the requirement text, which keeps "1 of" alternatives together
        (never the flattened stored groups, which listed every alternative as mandatory).
        """
        if not course_details:
            return []

        if isinstance(course_details.get("requirement_groups"), list):
            return [
                {
                    "courses": list(group.get("courses", [])),
                    "category": group.get("category", REQUIREMENT_PREREQUISITE),
                    "concurrent_allowed": bool(group.get("concurrent_allowed")),
                }
                for group in course_details["requirement_groups"]
                if isinstance(group, dict) and group.get("courses")
            ]

        parsed_groups = self.parse_prerequisite_text_groups(
            course_details.get("prerequisite_text", ""),
            with_metadata=True,
        )

        if parsed_groups:
            return parsed_groups

        return [
            {"courses": list(group), "category": REQUIREMENT_PREREQUISITE, "concurrent_allowed": False}
            for group in course_details.get("prerequisite_groups", [])
            if group
        ]

    def get_prerequisite_groups(self, course_details):
        return [group["courses"] for group in self.get_requirement_groups(course_details)]

    def parse_prerequisite_text_groups(self, prerequisite_text, with_metadata=False):
        if not prerequisite_text:
            return []

        marker_pattern = re.compile(
            r"Completed or concurrently enrolled in all of:"
            r"|Completed or concurrently enrolled in 1 of:"
            r"|Concurrently enrolled in 1 of:"
            r"|Concurrently enrolled in:"
            r"|Complete all of:"
            r"|Complete 1 of:",
            re.IGNORECASE,
        )
        matches = list(marker_pattern.finditer(prerequisite_text))
        groups = []

        for index, match in enumerate(matches):
            marker = match.group(0).lower()
            segment_start = match.end()
            segment_end = (
                matches[index + 1].start()
                if index + 1 < len(matches)
                else len(prerequisite_text)
            )
            segment = prerequisite_text[segment_start:segment_end]
            courses = self.extract_course_codes(segment)
            courses = [
                course for course in courses
                if self.is_displayable_course(course)
            ]

            if not courses:
                continue

            if marker.startswith("completed or concurrently"):
                category, concurrent = REQUIREMENT_PRE_OR_COREQUISITE, True
            elif marker.startswith("concurrently"):
                category, concurrent = REQUIREMENT_COREQUISITE, True
            else:
                category, concurrent = REQUIREMENT_PREREQUISITE, False

            if "1 of" in marker:
                new_groups = [courses]
            else:
                new_groups = [[course] for course in courses]

            for group in new_groups:
                groups.append(
                    {"courses": group, "category": category, "concurrent_allowed": concurrent}
                    if with_metadata
                    else group
                )

        return groups

    def requirement_prefix(self, requirement):
        courses = requirement["courses"]
        category = requirement.get("category", REQUIREMENT_PREREQUISITE)
        amount = "1 of" if len(courses) > 1 else "all of"

        if category == REQUIREMENT_COREQUISITE:
            return "Concurrently enrolled in 1 of" if len(courses) > 1 else "Concurrently enrolled in"

        if requirement.get("concurrent_allowed"):
            return f"Completed or concurrently enrolled in {amount}"

        return f"Complete {amount}"

    def format_requirement(self, requirement):
        return f"{self.requirement_prefix(requirement)}: {', '.join(requirement['courses'])}"

    def format_prerequisites(self, course_details):
        summary = (course_details or {}).get("requirement_summary")

        if summary:
            return summary

        requirements = self.get_requirement_groups(course_details)

        if not requirements:
            return "No prerequisites listed."

        return "\n".join(self.format_requirement(requirement) for requirement in requirements)

    def show_course_lookup_text_page(
        self,
        title_text,
        intro_text,
        check_command,
        back_command=None,
        back_text="Back",
    ):
        self.clear_page()

        page = ttk.Frame(self.container, padding=28, style="Panel.TFrame")
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(4, weight=1)

        self.create_page_header(
            page,
            title_text,
            back_command=back_command,
            back_text=back_text,
        )

        entry_row = ttk.Frame(page, style="Panel.TFrame")
        entry_row.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        entry_row.columnconfigure(0, weight=1)

        self.course_lookup_entry = ttk.Entry(entry_row)
        self.course_lookup_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.course_lookup_entry.bind("<Return>", check_command)

        check_button = ttk.Button(
            entry_row,
            text="Check",
            command=check_command,
            style="Info.TButton",
        )
        check_button.grid(row=0, column=1)

        self.course_lookup_summary = ttk.Label(
            page,
            text=intro_text,
            style="Panel.TLabel",
        )
        self.course_lookup_summary.grid(row=2, column=0, sticky="w", pady=(0, 8))

        result_frame = ttk.Frame(page, style="Panel.TFrame")
        result_frame.grid(row=3, column=0, sticky="nsew", pady=(0, 16))
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)

        self.course_lookup_results = tk.Text(
            result_frame,
            wrap=tk.WORD,
            height=14,
            state=tk.DISABLED,
        )
        self.course_lookup_results.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(
            result_frame,
            orient=tk.VERTICAL,
            command=self.course_lookup_results.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.course_lookup_results.configure(yscrollcommand=scrollbar.set)

    def show_course_information_page(self, course=None, back_command=None, back_text="Back"):
        self.show_course_lookup_text_page(
            "Course Information",
            "Enter a course code to see its title and catalog information.",
            self.check_course_information,
            back_command=back_command,
            back_text=back_text,
        )

        if course:
            self.course_lookup_entry.delete(0, tk.END)
            self.course_lookup_entry.insert(0, course)
            self.check_course_information()

    def show_course_prerequisites_page(self):
        self.show_course_lookup_text_page(
            "Course Prerequisites",
            "Enter a course code to see its prerequisite requirements.",
            self.check_course_prerequisites,
        )

    def show_browse_courses_page(self):
        self.clear_page()

        if not hasattr(self, "course_catalog"):
            self.course_catalog = build_course_catalog(self.course_graph)
            self.browse_query = ""
            self.browse_subject = ALL_SUBJECTS_LABEL
            self.browse_selected_course = None

        page = ttk.Frame(self.container, padding=28, style="Panel.TFrame")
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(3, weight=1)

        self.create_page_header(page, "Browse Courses")

        filter_row = ttk.Frame(page, style="Panel.TFrame")
        filter_row.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        filter_row.columnconfigure(1, weight=1)

        ttk.Label(filter_row, text="Search", style="Section.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))

        self.browse_search_var = tk.StringVar(value=self.browse_query)
        search_entry = ttk.Entry(filter_row, textvariable=self.browse_search_var)
        search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 16))

        ttk.Label(filter_row, text="Subject", style="Section.TLabel").grid(row=0, column=2, sticky="w", padx=(0, 8))

        subjects = sorted({code.split(" ")[0] for code, _title in self.course_catalog})
        self.browse_subject_var = tk.StringVar(value=self.browse_subject)
        subject_combo = ttk.Combobox(
            filter_row,
            textvariable=self.browse_subject_var,
            values=[ALL_SUBJECTS_LABEL] + subjects,
            state="readonly",
            width=14,
        )
        subject_combo.grid(row=0, column=3, sticky="e")

        self.browse_count_label = ttk.Label(page, text="", style="Panel.TLabel")
        self.browse_count_label.grid(row=2, column=0, sticky="w", pady=(0, 8))

        body = ttk.Frame(page, style="Panel.TFrame")
        body.grid(row=3, column=0, sticky="nsew")
        body.columnconfigure(2, weight=1)
        body.rowconfigure(0, weight=1)

        self.browse_course_list = tk.Listbox(body, width=44, exportselection=False)
        self.browse_course_list.grid(row=0, column=0, sticky="ns")
        self.browse_course_list.bind("<<ListboxSelect>>", self.show_selected_browse_course)

        list_scroll = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.browse_course_list.yview)
        list_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 16))
        self.browse_course_list.configure(yscrollcommand=list_scroll.set)

        result_frame = ttk.Frame(body, style="Panel.TFrame")
        result_frame.grid(row=0, column=2, sticky="nsew")
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)

        self.browse_details = tk.Text(result_frame, wrap=tk.WORD, state=tk.DISABLED)
        self.browse_details.grid(row=0, column=0, sticky="nsew")

        details_scroll = ttk.Scrollbar(result_frame, orient=tk.VERTICAL, command=self.browse_details.yview)
        details_scroll.grid(row=0, column=1, sticky="ns")
        self.browse_details.configure(yscrollcommand=details_scroll.set)

        self.browse_search_var.trace_add("write", self.refresh_browse_course_list)
        subject_combo.bind("<<ComboboxSelected>>", self.refresh_browse_course_list)

        self.refresh_browse_course_list()

        if self.browse_selected_course:
            self.display_browse_course(self.browse_selected_course)
        else:
            self.write_browse_details("Select a course to see its title, description, credits, and prerequisites.")

        search_entry.focus_set()

    def refresh_browse_course_list(self, *args):
        self.browse_query = self.browse_search_var.get()
        self.browse_subject = self.browse_subject_var.get()
        self.browse_visible_courses = filter_course_catalog(
            self.course_catalog,
            self.browse_query,
            self.browse_subject,
        )

        self.browse_course_list.delete(0, tk.END)

        for code, title in self.browse_visible_courses:
            self.browse_course_list.insert(tk.END, f"{code}  —  {title}" if title else code)

        shown = len(self.browse_visible_courses)
        total = len(self.course_catalog)
        noun = "course" if shown == 1 else "courses"
        self.browse_count_label.configure(
            text=f"Showing all {total} courses" if shown == total else f"{shown} matching {noun} (of {total})"
        )

        visible_codes = [code for code, _title in self.browse_visible_courses]

        if self.browse_selected_course in visible_codes:
            index = visible_codes.index(self.browse_selected_course)
            self.browse_course_list.selection_set(index)
            self.browse_course_list.see(index)

    def show_selected_browse_course(self, event=None):
        selected = self.browse_course_list.curselection()

        if not selected:
            return

        self.display_browse_course(self.browse_visible_courses[selected[0]][0])

    def display_browse_course(self, course):
        details = self.get_course_details(course)

        if not details:
            self.write_browse_details(f"{course}\n\n{COURSE_NOT_FOUND_MESSAGE}")
            return

        self.browse_selected_course = course
        self.write_browse_details(
            f"{self.format_course_information(course, details)}\n\n"
            f"{self.format_browse_requirements(details)}"
        )

    def format_browse_requirements(self, details):
        text = self.format_prerequisites(details)

        # The calendar-style summary already starts with its own section heading.
        if text.endswith(":") or text.split("\n", 1)[0].endswith(":"):
            return text

        return f"Prerequisites\n{text}"

    def write_browse_details(self, text):
        self.browse_details.configure(state=tk.NORMAL)
        self.browse_details.delete("1.0", tk.END)
        self.browse_details.insert(tk.END, text)
        self.browse_details.configure(state=tk.DISABLED)

    def write_course_lookup_result(self, summary, result):
        self.course_lookup_summary.configure(text=summary)
        self.course_lookup_results.configure(state=tk.NORMAL)
        self.course_lookup_results.delete("1.0", tk.END)
        self.course_lookup_results.insert(tk.END, result)
        self.course_lookup_results.configure(state=tk.DISABLED)

    def check_course_information(self, event=None):
        course = self.normalize_course_input(self.course_lookup_entry.get())

        if not course:
            self.write_course_lookup_result("Enter a course code first.", "")
            return

        details = self.get_course_details(course)

        if not details:
            self.write_course_lookup_result(
                f"{course} was not found in course_graph.json.",
                "Check the course code, or it may not be in the stored course data.",
            )
            return

        result = self.format_course_information(course, details)
        self.write_course_lookup_result(f"Showing information for {course}.", result)

    def format_course_information(self, course, details):
        title = details.get("title") or "(No title stored yet)"
        description = details.get("description") or "(No description stored yet)"
        credits = details.get("credits") or "Not listed"
        hours = details.get("hours") or "Not listed"
        return (
            f"{course}: {title}\n\n"
            f"Credits: {credits}\n"
            f"Hours: {hours}\n\n"
            f"{description}"
        )

    def check_course_prerequisites(self, event=None):
        course = self.normalize_course_input(self.course_lookup_entry.get())

        if not course:
            self.write_course_lookup_result("Enter a course code first.", "")
            return

        details = self.get_course_details(course)

        if not details:
            self.write_course_lookup_result(
                f"{course} was not found in course_graph.json.",
                "Check the course code, or it may not be in the stored course data.",
            )
            return

        title = details.get("title") or ""
        heading = f"{course}: {title}" if title else course
        result = f"{heading}\n\n{self.format_prerequisites(details)}"
        self.write_course_lookup_result(f"Showing prerequisites for {course}.", result)

    def show_notes_page(self):
        self.clear_page()

        page = ttk.Frame(self.container, padding=28, style="Panel.TFrame")
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(1, weight=1)
        page.rowconfigure(1, weight=1)

        self.create_page_header(page, "Notes")

        sidebar = ttk.Frame(page, style="Panel.TFrame")
        sidebar.grid(row=1, column=0, sticky="ns", padx=(0, 16))
        sidebar.rowconfigure(0, weight=1)

        self.notes_list = tk.Listbox(sidebar, width=24, exportselection=False)
        self.notes_list.grid(row=0, column=0, sticky="ns")
        self.notes_list.bind("<<ListboxSelect>>", self.select_note)

        note_buttons = ttk.Frame(sidebar, style="ButtonRow.TFrame")
        note_buttons.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        ttk.Button(note_buttons, text="New", command=self.add_note, style="Personal.TButton").grid(row=0, column=0, padx=(0, 6))
        ttk.Button(note_buttons, text="Delete", command=self.delete_note, style="Back.TButton").grid(row=0, column=1)

        editor = ttk.Frame(page, style="Panel.TFrame")
        editor.grid(row=1, column=1, sticky="nsew")
        editor.columnconfigure(0, weight=1)
        editor.rowconfigure(1, weight=1)

        self.note_title_entry = ttk.Entry(editor)
        self.note_title_entry.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.note_title_entry.bind("<KeyRelease>", self.update_current_note)

        self.note_body_text = tk.Text(editor, wrap=tk.WORD)
        self.note_body_text.grid(row=1, column=0, sticky="nsew")
        self.note_body_text.bind("<KeyRelease>", self.update_current_note)

        self.current_note_index = 0
        self.refresh_notes_list()
        self.load_note_into_editor(0)

    def refresh_notes_list(self):
        self.notes_list.delete(0, tk.END)

        for note in self.notes:
            self.notes_list.insert(tk.END, note.get("title") or "Untitled")

    def load_note_into_editor(self, index):
        if not self.notes:
            self.notes = [{"title": "New Note", "body": ""}]

        index = max(0, min(index, len(self.notes) - 1))
        self.current_note_index = index
        note = self.notes[index]
        self.notes_list.selection_clear(0, tk.END)
        self.notes_list.selection_set(index)
        self.note_title_entry.delete(0, tk.END)
        self.note_title_entry.insert(0, note.get("title", ""))
        self.note_body_text.delete("1.0", tk.END)
        self.note_body_text.insert("1.0", note.get("body", ""))

    def select_note(self, event=None):
        selected = self.notes_list.curselection()

        if selected:
            self.load_note_into_editor(selected[0])

    def update_current_note(self, event=None):
        if not hasattr(self, "current_note_index"):
            return

        title = self.note_title_entry.get().strip() or "Untitled"
        body = self.note_body_text.get("1.0", tk.END).rstrip()
        self.notes[self.current_note_index] = {"title": title, "body": body}
        self.save_notes()
        self.refresh_notes_list()
        self.notes_list.selection_set(self.current_note_index)

    def add_note(self):
        self.notes.append({"title": "New Note", "body": ""})
        self.save_notes()
        self.refresh_notes_list()
        self.load_note_into_editor(len(self.notes) - 1)

    def delete_note(self):
        if len(self.notes) == 1:
            self.notes = [{"title": "New Note", "body": ""}]
        else:
            del self.notes[self.current_note_index]

        self.save_notes()
        self.refresh_notes_list()
        self.load_note_into_editor(max(0, self.current_note_index - 1))

    def show_wanted_courses_page(self):
        self.clear_page()

        page = ttk.Frame(self.container, padding=28, style="Panel.TFrame")
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(3, weight=1)

        self.create_page_header(page, "Targets")

        entry_row = ttk.Frame(page, style="Panel.TFrame")
        entry_row.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        entry_row.columnconfigure(0, weight=1)

        self.wanted_course_entry = ttk.Entry(entry_row)
        self.wanted_course_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.wanted_course_entry.bind("<Return>", self.add_wanted_course)

        ttk.Button(entry_row, text="Add", command=self.add_wanted_course, style="Personal.TButton").grid(row=0, column=1)

        self.wanted_summary = ttk.Label(
            page,
            text="Add a target course to see what you need before registering.",
            style="Panel.TLabel",
        )
        self.wanted_summary.grid(row=2, column=0, sticky="w", pady=(0, 8))

        body = ttk.Frame(page, style="Panel.TFrame")
        body.grid(row=3, column=0, sticky="nsew", pady=(0, 16))
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self.wanted_course_list = tk.Listbox(body, width=24, exportselection=False)
        self.wanted_course_list.grid(row=0, column=0, sticky="ns", padx=(0, 16))
        self.wanted_course_list.bind("<<ListboxSelect>>", self.show_selected_wanted_course)

        result_frame = ttk.Frame(body, style="Panel.TFrame")
        result_frame.grid(row=0, column=1, sticky="nsew")
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)

        self.wanted_results = tk.Text(result_frame, wrap=tk.WORD, state=tk.DISABLED)
        self.wanted_results.grid(row=0, column=0, sticky="nsew")

        result_scroll = ttk.Scrollbar(result_frame, orient=tk.VERTICAL, command=self.wanted_results.yview)
        result_scroll.grid(row=0, column=1, sticky="ns")
        self.wanted_results.configure(yscrollcommand=result_scroll.set)

        button_row = ttk.Frame(page, style="ButtonRow.TFrame")
        button_row.grid(row=4, column=0, sticky="w")
        ttk.Button(button_row, text="Remove", command=self.remove_wanted_course, style="Back.TButton").grid(row=0, column=0, padx=(0, 8))
        ttk.Button(button_row, text="Path", command=self.show_selected_wanted_flowchart, style="Explore.TButton").grid(row=0, column=1, padx=(0, 8))

        self.refresh_wanted_course_list()

    def refresh_wanted_course_list(self):
        self.wanted_course_list.delete(0, tk.END)

        for course in sorted(self.wanted_courses):
            self.wanted_course_list.insert(tk.END, course)

    def add_wanted_course(self, event=None):
        courses, rejected = parse_course_entries(
            self.wanted_course_entry.get(),
            self.known_course_codes(),
        )

        if not courses and not rejected:
            return

        added = [course for course in courses if course not in self.wanted_courses]
        already = [course for course in courses if course in self.wanted_courses]

        if added:
            self.wanted_courses = sorted(set(self.wanted_courses + added))
            self.save_wanted_courses()
            self.refresh_wanted_course_list()

        self.wanted_course_entry.delete(0, tk.END)
        self.wanted_course_entry.insert(0, ", ".join(rejected))

        if courses:
            course = courses[-1]
            self.select_wanted_course(course)
            self.display_wanted_course_details(course)

        if rejected:
            self.report_course_entry_results(added, already, rejected, "Already in your targets")

    def remove_wanted_course(self):
        selected = self.wanted_course_list.curselection()

        if not selected:
            return

        course = self.wanted_course_list.get(selected[0])
        self.wanted_courses = [item for item in self.wanted_courses if item != course]
        self.save_wanted_courses()
        self.refresh_wanted_course_list()
        self.write_wanted_result("Course removed.", "")

    def select_wanted_course(self, course):
        for index in range(self.wanted_course_list.size()):
            if self.wanted_course_list.get(index) == course:
                self.wanted_course_list.selection_clear(0, tk.END)
                self.wanted_course_list.selection_set(index)
                self.wanted_course_list.see(index)
                return

    def show_selected_wanted_course(self, event=None):
        selected = self.wanted_course_list.curselection()

        if selected:
            self.display_wanted_course_details(self.wanted_course_list.get(selected[0]))

    def write_wanted_result(self, summary, result):
        self.wanted_summary.configure(text=summary)
        self.wanted_results.configure(state=tk.NORMAL)
        self.wanted_results.delete("1.0", tk.END)
        self.wanted_results.insert(tk.END, result)
        self.wanted_results.configure(state=tk.DISABLED)

    def display_wanted_course_details(self, course):
        details = self.get_course_details(course)

        if not details:
            self.write_wanted_result(
                f"{course} was not found.",
                "Check the course code, or it may not be in the stored course data.",
            )
            return

        completed = set(self.completed_courses)
        missing_lines = []

        for requirement in self.get_requirement_groups(details):
            completed_options = [option for option in requirement["courses"] if option in completed]

            if completed_options:
                missing_lines.append(f"Met: {self.format_requirement(requirement)}")
            elif requirement.get("concurrent_allowed"):
                missing_lines.append(f"Needed (can be taken at the same time): {self.format_requirement(requirement)}")
            else:
                missing_lines.append(f"Needed: {self.format_requirement(requirement)}")

        if details.get("requirement_notes"):
            missing_lines.extend(f"Also: {note}" for note in details["requirement_notes"])

        if not missing_lines:
            missing_lines.append("No prerequisites listed.")

        path_lines, possible_needed = self.describe_needed_prerequisite_path(course, completed)
        possible_needed.discard(course)

        if possible_needed:
            possible_text = "\n".join(
                f"- {needed_course}" for needed_course in sorted(possible_needed)
            )
        else:
            possible_text = "No additional prerequisite courses found."

        if not path_lines:
            path_text = "No prerequisite path found."
        else:
            path_text = "\n".join(path_lines)

        title = details.get("title") or ""
        can_take = self.course_is_available(course, completed)
        concurrent_pending = [
            requirement for requirement in self.get_requirement_groups(details)
            if requirement.get("concurrent_allowed")
            and not any(option in completed for option in requirement["courses"])
        ]

        if can_take and concurrent_pending:
            status = (
                "You can register if you also take these in the same term (or have already): "
                + "; ".join(self.format_requirement(requirement) for requirement in concurrent_pending)
            )
        elif can_take:
            status = "You can register based on saved completed courses."
        else:
            status = "You still have unmet prerequisites."
        result = f"{course}: {title}\n\n{status}\n\nDirect requirements:\n" + "\n".join(missing_lines)
        result += "\n\nAll possible prerequisite courses still in the path:\n" + possible_text
        result += "\n\nPrerequisite path details:\n" + path_text
        result += "\n\nUse 'Show Flowchart Path' to see this visually."
        self.write_wanted_result(f"Showing registration requirements for {course}.", result)

    def describe_needed_prerequisite_path(self, course, completed, depth=0, visiting=None):
        if visiting is None:
            visiting = set()

        if course in visiting:
            return [f"{'  ' * depth}- {course}: cycle detected, stopping here."], set()

        details = self.get_course_details(course)

        if not details:
            return [f"{'  ' * depth}- {course}: details not found in loaded graph."], set()

        requirements = self.get_requirement_groups(details)

        if not requirements:
            return [], set()

        visiting.add(course)
        lines = []
        possible_needed = set()
        indent = "  " * depth

        for requirement in requirements:
            group = requirement["courses"]
            timing = " (or take it at the same time)" if requirement.get("concurrent_allowed") else ""
            completed_options = [option for option in group if option in completed]

            if completed_options:
                lines.append(
                    f"{indent}- {course}: met by {', '.join(completed_options)}"
                )
                continue

            if len(group) == 1:
                prereq = group[0]
                lines.append(f"{indent}- {course}: need {prereq}{timing}")

                if prereq not in completed:
                    possible_needed.add(prereq)

                child_lines, child_needed = self.describe_needed_prerequisite_path(
                    prereq,
                    completed,
                    depth + 1,
                    visiting,
                )
                lines.extend(child_lines)
                possible_needed.update(child_needed)
            else:
                available_options = [option for option in group if option not in completed]
                lines.append(
                    f"{indent}- {course}: need 1 of {', '.join(group)}{timing}"
                )

                for option in available_options:
                    possible_needed.add(option)
                    lines.append(f"{indent}  Option {option}:")
                    child_lines, child_needed = self.describe_needed_prerequisite_path(
                        option,
                        completed,
                        depth + 2,
                        visiting,
                    )

                    if child_lines:
                        lines.extend(child_lines)
                    else:
                        lines.append(f"{indent}    No further prerequisites listed.")

                    possible_needed.update(child_needed)

        visiting.remove(course)
        return lines, possible_needed

    def show_selected_wanted_flowchart(self):
        selected = self.wanted_course_list.curselection()

        if selected:
            course = self.wanted_course_list.get(selected[0])
        else:
            course = self.normalize_course_input(self.wanted_course_entry.get())

        if not course:
            self.write_wanted_result(
                "Choose or enter a course first.",
                "Select a course from the list, or type one into the input box.",
            )
            return

        self.show_flowchart_page()
        self.flowchart_course_entry.delete(0, tk.END)
        self.flowchart_course_entry.insert(0, course)
        self.preview_flowchart_course()

    def check_unlocked_courses(self, event=None):
        target_course = self.normalize_course_input(self.unlocked_course_entry.get())
        self.unlocked_results.configure(state=tk.NORMAL)
        self.unlocked_results.delete("1.0", tk.END)

        if not target_course:
            self.unlocked_summary.configure(text="Enter a course code first.")
            self.unlocked_results.configure(state=tk.DISABLED)
            return

        unlocked_courses = self.get_unlocked_courses(target_course)

        if not unlocked_courses:
            self.unlocked_summary.configure(
                text=f"No loaded courses list {target_course} as a prerequisite."
            )
            self.unlocked_results.configure(state=tk.DISABLED)
            return

        self.unlocked_summary.configure(
            text=f"{len(unlocked_courses)} loaded courses list {target_course} as a prerequisite."
        )

        for index, (course, matching_groups, other_required_groups) in enumerate(unlocked_courses):
            for text, tag in self.build_unlocked_course_segments(
                course,
                matching_groups,
                other_required_groups,
                target_course,
            ):
                self.unlocked_results.insert(tk.END, text, tag)

        self.unlocked_results.configure(state=tk.DISABLED)
        self.unlocked_results.yview_moveto(0)

    def show_flowchart_page(self):
        self.clear_page()

        page = ttk.Frame(self.container, padding=28, style="Panel.TFrame")
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)

        self.create_page_header(page, "Flowchart", back_text="Back")

        main = ttk.Frame(page, style="Panel.TFrame")
        main.grid(row=1, column=0, sticky="nsew", pady=(0, 12))
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=1)

        canvas_frame = ttk.Frame(main, style="Panel.TFrame")
        canvas_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)

        self.flowchart_canvas = tk.Canvas(
            canvas_frame,
            background="#f8fafc",
            highlightthickness=1,
            highlightbackground="#cbd5e1",
        )
        self.flowchart_canvas.grid(row=0, column=0, sticky="nsew")

        x_scroll = ttk.Scrollbar(
            canvas_frame,
            orient=tk.HORIZONTAL,
            command=self.flowchart_canvas.xview,
        )
        x_scroll.grid(row=1, column=0, sticky="ew")

        y_scroll = ttk.Scrollbar(
            canvas_frame,
            orient=tk.VERTICAL,
            command=self.flowchart_canvas.yview,
        )
        y_scroll.grid(row=0, column=1, sticky="ns")

        controls = ttk.Frame(main, padding=(12, 0, 0, 0), style="Panel.TFrame")
        controls.grid(row=0, column=1, sticky="ns")
        controls.columnconfigure(0, weight=1)
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="Course to test", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))

        self.flowchart_course_entry = ttk.Entry(controls)
        self.flowchart_course_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.flowchart_course_entry.bind("<Return>", self.preview_flowchart_course)

        preview_button = ttk.Button(
            controls,
            text="Preview",
            command=self.preview_flowchart_course,
            style="Explore.TButton",
        )
        preview_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        progress_button = ttk.Button(
            controls,
            text="Progress",
            command=self.show_progress_flowchart,
            style="Plan.TButton",
        )
        progress_button.grid(row=3, column=0, sticky="ew", padx=(0, 6), pady=(0, 8))

        available_button = ttk.Button(
            controls,
            text="Available",
            command=self.show_available_flowchart,
            style="Explore.TButton",
        )
        available_button.grid(row=3, column=1, sticky="ew", pady=(0, 8))

        ttk.Label(controls, text="Subject", style="Section.TLabel").grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 4))

        self.flowchart_subject = tk.StringVar()
        subjects = self.get_available_subjects()
        self.flowchart_subject_combo = ttk.Combobox(
            controls,
            textvariable=self.flowchart_subject,
            values=subjects,
            state="readonly",
        )
        self.flowchart_subject_combo.grid(row=5, column=0, sticky="ew", padx=(0, 6), pady=(0, 8))

        if subjects:
            self.flowchart_subject.set(subjects[0])

        subject_graph_button = ttk.Button(
            controls,
            text="Show Subject",
            command=self.show_subject_flowchart,
            style="Explore.TButton",
        )
        subject_graph_button.grid(row=5, column=1, sticky="ew", pady=(0, 8))

        self.flowchart_info_button = ttk.Button(
            controls,
            text="Selected Info",
            command=self.show_selected_flowchart_course_info,
            state=tk.DISABLED,
            style="Info.TButton",
        )
        self.flowchart_info_button.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(0, 12))

        no_prereq_panel = ttk.Frame(controls, style="Panel.TFrame")
        no_prereq_panel.grid(row=7, column=0, columnspan=2, sticky="nsew")
        no_prereq_panel.columnconfigure(0, weight=1)
        no_prereq_panel.rowconfigure(1, weight=1)

        self.no_prereq_title = ttk.Label(
            no_prereq_panel,
            text="Starting-point courses",
            style="Section.TLabel",
        )
        self.no_prereq_title.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        self.no_prereq_list = tk.Listbox(
            no_prereq_panel,
            width=22,
            height=6,
            exportselection=False,
        )
        self.no_prereq_list.grid(row=1, column=0, sticky="nsew")

        no_prereq_scroll = ttk.Scrollbar(
            no_prereq_panel,
            orient=tk.VERTICAL,
            command=self.no_prereq_list.yview,
        )
        no_prereq_scroll.grid(row=1, column=1, sticky="ns")
        self.no_prereq_list.configure(yscrollcommand=no_prereq_scroll.set)

        status_box = ttk.Frame(page, padding=(14, 10), style="Card.TFrame")
        status_box.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        status_box.columnconfigure(0, weight=1)

        self.flowchart_summary = ttk.Label(
            status_box,
            text="Mode: use the buttons to choose a flowchart view.",
            style="Card.TLabel",
            font=("Segoe UI", 10, "bold"),
        )
        self.flowchart_summary.grid(row=0, column=0, sticky="w")

        legend = ttk.Frame(page, padding=(14, 10), style="Card.TFrame")
        legend.grid(row=3, column=0, sticky="ew")

        ttk.Label(
            legend,
            text="Legend",
            style="Card.TLabel",
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=(0, 18))

        self.draw_static_legend(legend)

        self.flowchart_canvas.configure(
            xscrollcommand=x_scroll.set,
            yscrollcommand=y_scroll.set,
        )
        self.flowchart_canvas.bind("<MouseWheel>", self.zoom_flowchart)
        self.flowchart_canvas.bind("<Button-4>", self.zoom_flowchart)
        self.flowchart_canvas.bind("<Button-5>", self.zoom_flowchart)
        self.flowchart_canvas.bind("<ButtonPress-1>", self.start_flowchart_pan)
        self.flowchart_canvas.bind("<B1-Motion>", self.pan_flowchart)

        self.show_progress_flowchart()

    def draw_static_legend(self, parent):
        node_items = (
            ("#dcfce7", "#16a34a", "completed/enrolled"),
            ("#dbeafe", "#2563eb", "available now"),
            ("#fef3c7", "#d97706", "preview course"),
            ("#ffffff", "#94a3b8", "not currently available"),
        )

        for index, (fill, outline, text) in enumerate(node_items, start=1):
            item = tk.Canvas(
                parent,
                width=178,
                height=28,
                background=CARD_BACKGROUND,
                highlightthickness=0,
            )
            item.grid(row=0, column=index, sticky="w", padx=(0, 12))
            item.create_rectangle(0, 5, 30, 23, fill=fill, outline=outline, width=2)
            item.create_text(38, 14, text=text, anchor="w", fill=UVIC_DARK_BLUE, font=("Segoe UI", 8))

        solid = tk.Canvas(parent, width=150, height=28, background=CARD_BACKGROUND, highlightthickness=0)
        solid.grid(row=1, column=1, sticky="w", padx=(0, 12), pady=(6, 0))
        solid.create_line(0, 14, 38, 14, arrow=tk.LAST, width=2, fill="#2563eb")
        solid.create_text(46, 14, text="required", anchor="w", fill=UVIC_DARK_BLUE, font=("Segoe UI", 8))

        dotted = tk.Canvas(parent, width=178, height=28, background=CARD_BACKGROUND, highlightthickness=0)
        dotted.grid(row=1, column=2, sticky="w", padx=(0, 12), pady=(6, 0))
        dotted.create_line(0, 14, 38, 14, arrow=tk.LAST, width=2, fill="#7c3aed", dash=(5, 3))
        dotted.create_text(46, 14, text="one option", anchor="w", fill=UVIC_DARK_BLUE, font=("Segoe UI", 8))

        return

    def course_is_available(self, course, completed_courses):
        details = self.get_course_details(course)

        if not details:
            return False

        return all(
            self.requirement_is_satisfied(requirement, completed_courses)
            for requirement in self.get_requirement_groups(details)
        )

    def requirement_is_satisfied(self, requirement, completed_courses, allow_concurrent=True):
        """A group is met by a completed option. Groups that allow concurrent enrollment are
        also met when an option could be taken in the same term (its own completed-before
        requirements are met), so they never wrongly demand prior completion."""
        options = requirement["courses"]

        if any(option in completed_courses for option in options):
            return True

        if not (allow_concurrent and requirement.get("concurrent_allowed")):
            return False

        for option in options:
            option_details = self.get_course_details(option)

            if option_details is None:
                continue

            if all(
                self.requirement_is_satisfied(option_requirement, completed_courses, allow_concurrent=False)
                for option_requirement in self.get_requirement_groups(option_details)
                if not option_requirement.get("concurrent_allowed")
            ):
                return True

        return False

    def get_courses_unlocked_by_completed(self, completed_courses):
        unlocked = []

        for course in self.course_graph.get("courses", {}):
            if not self.is_displayable_course(course):
                continue

            if course in completed_courses:
                continue

            if self.course_is_available(course, completed_courses):
                unlocked.append(course)

        return sorted(unlocked)

    def get_available_subjects(self):
        subjects = set()

        for course in self.course_graph.get("nodes", []):
            if not self.is_displayable_course(course):
                continue

            match = COURSE_CODE_PATTERN.search(course)

            if match:
                subjects.add(match.group(1))

        return sorted(subjects)

    def get_courses_for_subject(self, subject):
        return {
            course for course in self.course_graph.get("nodes", [])
            if course.startswith(f"{subject} ") and self.is_displayable_course(course)
        }

    def split_subject_flowchart_courses(self, subject):
        subject_courses = self.get_courses_for_subject(subject)
        no_prereq_courses = {
            course for course in subject_courses
            if not self.get_direct_prerequisites(course)
        }
        graph_courses = subject_courses - no_prereq_courses

        return graph_courses, sorted(no_prereq_courses)

    def update_no_prereq_list(self, courses=None, subject=None):
        courses = sorted(courses or [])
        self.flowchart_no_prereq_courses = courses

        if not hasattr(self, "no_prereq_list"):
            return

        self.no_prereq_list.delete(0, tk.END)

        if subject:
            self.no_prereq_title.configure(
                text=f"{subject} starting-point courses"
            )
        else:
            self.no_prereq_title.configure(text="Starting-point courses")

        if not courses:
            self.no_prereq_list.insert(tk.END, "None for this view")
            return

        for course in courses:
            self.no_prereq_list.insert(tk.END, course.replace(" ", ""))

    def is_displayable_course(self, course):
        match = COURSE_CODE_PATTERN.fullmatch(course.strip())

        if not match:
            return False

        number_text = match.group(2)
        number = int(number_text[:3])

        return number >= 100

    def get_direct_successors(self, course):
        successors = []

        for target_course, details in self.course_graph.get("courses", {}).items():
            if not self.is_displayable_course(target_course):
                continue

            prereq_groups = self.get_prerequisite_groups(details)

            if any(course in group for group in prereq_groups):
                successors.append(target_course)

        return sorted(set(successors))

    def get_direct_prerequisites(self, course):
        details = self.get_course_details(course)

        if not details:
            return []

        prereqs = []

        for group in self.get_prerequisite_groups(details):
            for prereq in group:
                if self.is_displayable_course(prereq) and prereq not in prereqs:
                    prereqs.append(prereq)

        return prereqs

    def collect_flowchart_nodes(self, focus_courses, include_successors=True):
        nodes = set(focus_courses)

        for course in list(focus_courses):
            nodes.update(self.get_direct_prerequisites(course))

            if include_successors:
                nodes.update(self.get_direct_successors(course))

        return nodes

    def get_flowchart_edges(self, nodes):
        edges = []
        nodes = {node for node in nodes if self.is_displayable_course(node)}

        for course in nodes:
            details = self.get_course_details(course)

            if not details:
                continue

            for group in self.get_prerequisite_groups(details):
                requirement_type = "any_of" if len(group) > 1 else "required"

                for prereq in group:
                    if prereq in nodes:
                        edges.append((prereq, course, requirement_type, group))

        return edges

    def get_prerequisite_path_nodes(self, course):
        path_nodes = set()

        def visit(current_course):
            if not self.is_displayable_course(current_course):
                return

            if current_course in path_nodes:
                return

            path_nodes.add(current_course)

            for prereq in self.get_direct_prerequisites(current_course):
                visit(prereq)

        visit(course)
        return path_nodes

    def get_easiest_prerequisite_path_nodes(self, course, completed_courses=None):
        completed_courses = set(completed_courses or [])
        memo = {}

        def choose_path(current_course, visiting=None):
            if visiting is None:
                visiting = set()

            if not self.is_displayable_course(current_course):
                return set(), 0

            if current_course in memo:
                cached_nodes, cached_cost = memo[current_course]
                return set(cached_nodes), cached_cost

            if current_course in visiting:
                return {current_course}, 1

            details = self.get_course_details(current_course)

            if not details:
                return {current_course}, 1

            visiting.add(current_course)
            path_nodes = {current_course}
            cost = 0 if current_course in completed_courses else 1

            for group in self.get_prerequisite_groups(details):
                options = [
                    option for option in group
                    if self.is_displayable_course(option)
                ]

                if not options:
                    continue

                best_option = None

                for option in options:
                    option_nodes, option_cost = choose_path(option, visiting)
                    completed_bonus = 0 if option in completed_courses else 1
                    score = (option_cost, completed_bonus, len(option_nodes), option)

                    if best_option is None or score < best_option[0]:
                        best_option = (score, option_nodes, option_cost)

                if best_option:
                    _score, option_nodes, option_cost = best_option
                    path_nodes.update(option_nodes)
                    cost += option_cost

            visiting.remove(current_course)
            memo[current_course] = (set(path_nodes), cost)
            return path_nodes, cost

        nodes, _cost = choose_path(course)
        return nodes

    def export_flowchart_dot(self, nodes, edges, render_svg=False):
        lines = self.build_flowchart_dot_lines(nodes, edges)
        FLOWCHART_DOT_FILE.write_text("\n".join(lines), encoding="utf-8")
        dot_command = self.graphviz_dot_command()

        if render_svg and dot_command:
            subprocess.run(
                [
                    dot_command,
                    "-Tsvg",
                    str(FLOWCHART_DOT_FILE),
                    "-o",
                    str(FLOWCHART_SVG_FILE),
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def build_flowchart_dot_lines(self, nodes, edges):
        lines = [
            "digraph CourseFlowchart {",
            '  graph [rankdir="LR", ranksep="1.0", nodesep="0.5", splines=ortho];',
            "  node [shape=box, style=\"rounded,filled\", fillcolor=white, fontname=\"Segoe UI\"];",
            "  edge [fontname=\"Segoe UI\", color=\"#2563eb\", arrowsize=0.8];",
        ]

        for node in sorted(nodes):
            label = node.replace('"', '\\"')
            lines.append(f'  "{label}";')

        for source, target, requirement_type, _group in edges:
            style = "solid" if requirement_type == "required" else "dashed"
            color = "#2563eb" if requirement_type == "required" else "#7c3aed"
            lines.append(
                f'  "{source}" -> "{target}" [style="{style}", color="{color}"];'
            )

        lines.append("}")
        return lines

    def graphviz_dot_command(self):
        if self.graphviz_dot_path:
            return self.graphviz_dot_path

        dot_command = shutil.which("dot")

        if dot_command:
            self.graphviz_dot_path = dot_command
            return dot_command

        for path in (
            Path("C:/Program Files/Graphviz/bin/dot.exe"),
            Path("C:/Program Files (x86)/Graphviz/bin/dot.exe"),
        ):
            if path.exists():
                self.graphviz_dot_path = str(path)
                return self.graphviz_dot_path

        return None

    def flowchart_layout_cache_key(self, nodes, edges):
        return (
            tuple(sorted(nodes)),
            tuple(
                sorted(
                    (source, target, requirement_type)
                    for source, target, requirement_type, _group in edges
                )
            ),
        )

    def calculate_graphviz_positions(self, nodes, edges, scale, node_width, node_height):
        dot_command = self.graphviz_dot_command()

        if not dot_command:
            return None

        cache_key = self.flowchart_layout_cache_key(nodes, edges)
        cached_layout = self.flowchart_layout_cache.get(cache_key)

        if cached_layout is None:
            dot_text = "\n".join(self.build_flowchart_dot_lines(nodes, edges))

            try:
                result = subprocess.run(
                    [dot_command, "-Tplain"],
                    input=dot_text,
                    text=True,
                    capture_output=True,
                    check=False,
                )
            except OSError:
                return None

            if result.returncode != 0:
                return None

            graph_height = None
            plain_positions = {}

            for line in result.stdout.splitlines():
                if not line.strip():
                    continue

                try:
                    parts = shlex.split(line)
                except ValueError:
                    continue

                if not parts:
                    continue

                if parts[0] == "graph" and len(parts) >= 4:
                    try:
                        graph_height = float(parts[3])
                    except ValueError:
                        graph_height = None

                if parts[0] != "node" or len(parts) < 4 or graph_height is None:
                    continue

                node = parts[1]

                if node not in nodes:
                    continue

                try:
                    graph_x = float(parts[2])
                    graph_y = float(parts[3])
                except ValueError:
                    continue

                plain_positions[node] = (graph_x, graph_y)

            if not graph_height or not all(node in plain_positions for node in nodes):
                return None

            cached_layout = (graph_height, plain_positions)
            self.flowchart_layout_cache[cache_key] = cached_layout

        graph_height, plain_positions = cached_layout
        pixels_per_inch = 120 * scale
        x_margin = 80 * scale
        y_margin = 70 * scale

        positions = {
            node: (
                x_margin + graph_x * pixels_per_inch - node_width / 2,
                y_margin + (graph_height - graph_y) * pixels_per_inch - node_height / 2,
            )
            for node, (graph_x, graph_y) in plain_positions.items()
        }

        return positions

    def calculate_flowchart_levels(self, nodes, edges):
        prereqs_by_course = {node: [] for node in nodes}

        for source, target, _requirement_type, _group in edges:
            if source in nodes and target in nodes:
                prereqs_by_course.setdefault(target, []).append(source)
                prereqs_by_course.setdefault(source, [])

        levels = {}
        visiting = set()

        def level_for(node):
            if node in levels:
                return levels[node]

            if node in visiting:
                return 0

            visiting.add(node)
            prereqs = prereqs_by_course.get(node, [])

            if prereqs:
                level = 1 + max(level_for(prereq) for prereq in prereqs)
            else:
                level = 0

            visiting.remove(node)
            levels[node] = level
            return level

        for node in nodes:
            level_for(node)

        return levels

    def course_subject(self, course):
        match = COURSE_CODE_PATTERN.fullmatch(course.strip())
        return match.group(1) if match else course

    def course_number_value(self, course):
        match = COURSE_CODE_PATTERN.fullmatch(course.strip())

        if not match:
            return 9999

        return int(match.group(2)[:3])

    def order_flowchart_level_nodes(self, level_nodes, positions, edges):
        preferred_y_by_subject = {}

        for node, (_x, y) in positions.items():
            subject = self.course_subject(node)
            preferred_y_by_subject.setdefault(subject, []).append(y)

        subject_y = {
            subject: sum(values) / len(values)
            for subject, values in preferred_y_by_subject.items()
        }

        def connected_y_values(node):
            values = []
            subject = self.course_subject(node)

            if subject in subject_y:
                values.append(subject_y[subject])

            for source, target, _requirement_type, _group in edges:
                if source == node and target in positions:
                    values.append(positions[target][1])

                if target == node and source in positions:
                    values.append(positions[source][1])

            return values

        def sort_key(node):
            values = connected_y_values(node)

            if values:
                connection_y = sum(values) / len(values)
            else:
                connection_y = 100000

            return (
                connection_y,
                self.course_subject(node),
                self.course_number_value(node),
                node,
            )

        return sorted(level_nodes, key=sort_key)

    def calculate_flowchart_positions(self, rows_by_level, edges, scale, node_width, node_height):
        x_gap = 240 * scale
        y_gap = 82 * scale
        group_gap = 34 * scale
        x_margin = 90 * scale
        y_cursor = 70 * scale
        positions = {}
        max_level = max(rows_by_level, default=0)

        def sort_nodes(nodes):
            return sorted(
                nodes,
                key=lambda node: (
                    self.course_subject(node),
                    self.course_number_value(node),
                    node,
                ),
            )

        for level in range(max_level, -1, -1):
            level_nodes = set(rows_by_level.get(level, []))
            placed = set()
            groups = []

            targets = sort_nodes(rows_by_level.get(level + 1, []))

            for target in targets:
                connected = [
                    source for source, edge_target, _requirement_type, _group in edges
                    if edge_target == target and source in level_nodes and source not in placed
                ]

                if connected:
                    ordered_group = sort_nodes(connected)
                    groups.append(ordered_group)
                    placed.update(ordered_group)

            remaining = sort_nodes(level_nodes - placed)
            groups.extend([node] for node in remaining)

            row = 0

            for group in groups:
                for node in group:
                    x = x_margin + level * x_gap
                    y = y_cursor + row * y_gap
                    positions[node] = (x, y)
                    row += 1

                row += 1

            level_height = max(row * y_gap, len(level_nodes) * y_gap)
            y_cursor += level_height + group_gap

        if not positions:
            return positions

        min_y = min(y for _x, y in positions.values())
        positions = {
            node: (x, y - min_y + 70 * scale)
            for node, (x, y) in positions.items()
        }

        return positions

    def calculate_direct_preview_positions(self, nodes, target_course, scale, node_width, node_height):
        prereqs = self.order_direct_preview_prerequisites(target_course, nodes)
        center_y = 230 * scale
        target_x = 410 * scale
        prereq_x = 190 * scale
        spacing = 58 * scale
        positions = {
            target_course: (target_x, center_y),
        }

        count = len(prereqs)

        for index, prereq in enumerate(prereqs):
            y = center_y + (index - (count - 1) / 2) * spacing
            positions[prereq] = (prereq_x, y)

        return positions

    def calculate_two_layer_preview_positions(self, nodes, target_course, scale, node_width, node_height):
        direct_prereqs = self.order_direct_preview_prerequisites(target_course, nodes)
        center_y = 300 * scale
        target_x = 900 * scale
        first_x = 600 * scale
        second_x = 150 * scale
        shared_x = 360 * scale
        direct_spacing = 108 * scale
        child_spacing = 82 * scale
        positions = {
            target_course: (target_x, center_y),
        }

        count = len(direct_prereqs)

        for index, prereq in enumerate(direct_prereqs):
            y = center_y + (index - (count - 1) / 2) * direct_spacing
            positions[prereq] = (first_x, y)

        for prereq in direct_prereqs:
            child_prereqs = [
                course for course in self.order_direct_preview_prerequisites(prereq, nodes)
                if course in nodes and course not in positions
            ]

            child_count = len(child_prereqs)

            for index, child in enumerate(child_prereqs):
                y = positions[prereq][1] + (index - (child_count - 1) / 2) * child_spacing
                positions[child] = (second_x, y)

        outgoing_counts = {}

        for source, target, _requirement_type, _group in self.get_flowchart_edges(nodes):
            if source in positions and target in positions:
                outgoing_counts[source] = outgoing_counts.get(source, 0) + 1

        for node, count in outgoing_counts.items():
            if count <= 1 or node == target_course:
                continue

            x, y = positions[node]

            if x < first_x:
                positions[node] = (shared_x, y)

        for source, target, _requirement_type, _group in self.get_flowchart_edges(nodes):
            if source not in positions or target not in positions:
                continue

            source_x, source_y = positions[source]
            target_x, _target_y = positions[target]

            if source_x >= target_x:
                positions[source] = (target_x - 230 * scale, source_y)

        return positions

    def order_direct_preview_prerequisites(self, target_course, nodes):
        details = self.get_course_details(target_course)
        groups = self.get_prerequisite_groups(details)

        def sort_courses(courses):
            return sorted(
                [course for course in courses if course in nodes],
                key=lambda course: (
                    self.course_subject(course),
                    self.course_number_value(course),
                    course,
                ),
            )

        required = []
        option_groups = []

        for group in groups:
            if len(group) == 1:
                required.extend(sort_courses(group))
            else:
                option_groups.append(sort_courses(group))

        midpoint = (len(required) + 1) // 2
        ordered = required[:midpoint]

        for group in option_groups:
            ordered.extend(group)

        ordered.extend(required[midpoint:])

        seen = set()
        unique_ordered = []

        for course in ordered:
            if course in seen:
                continue

            seen.add(course)
            unique_ordered.append(course)

        return unique_ordered

    def draw_flowchart(self, nodes, completed_courses=None, preview_course=None, scale=1.0):
        nodes = {node for node in nodes if self.is_displayable_course(node)}
        self.flowchart_nodes = set(nodes)
        self.flowchart_completed_courses = set(completed_courses or [])
        self.flowchart_preview_course = preview_course
        self.flowchart_scale = scale
        completed_courses = set(completed_courses or [])
        nodes = sorted(nodes)
        edges = self.get_flowchart_edges(nodes)
        self.export_flowchart_dot(nodes, edges, render_svg=False)
        availability_cache = {}

        def is_course_open(course):
            if course in completed_courses or course == preview_course:
                return True

            if course not in availability_cache:
                availability_cache[course] = self.course_is_available(course, completed_courses)

            return availability_cache[course]

        levels = self.calculate_flowchart_levels(nodes, edges)
        rows_by_level = {}

        for node in nodes:
            rows_by_level.setdefault(levels.get(node, 0), []).append(node)

        node_width = 120 * scale
        node_height = 42 * scale
        x_margin = 90 * scale
        y_margin = 50 * scale
        font_size = max(4, int(10 * scale))
        highlighted_nodes = None

        if self.flowchart_selected_course in nodes:
            highlighted_nodes = (
                self.get_prerequisite_path_nodes(self.flowchart_selected_course)
                & set(nodes)
            )

        self.flowchart_canvas.delete("all")
        positions = self.calculate_graphviz_positions(
            nodes,
            edges,
            scale,
            node_width,
            node_height,
        )

        if positions:
            pass
        elif self.flowchart_direct_preview and preview_course in nodes:
            positions = self.calculate_two_layer_preview_positions(
                nodes,
                preview_course,
                scale,
                node_width,
                node_height,
            )
        else:
            positions = self.calculate_flowchart_positions(
                rows_by_level,
                edges,
                scale,
                node_width,
                node_height,
            )

        if positions:
            min_y = min(y for _x, y in positions.values())
            max_y = max(y for _x, y in positions.values()) + node_height
            graph_height = max_y - min_y
            viewport_height = max(self.flowchart_canvas.winfo_height(), 320)

            if viewport_height > graph_height + y_margin:
                y_offset = ((viewport_height - graph_height) / 2) - min_y
                positions = {
                    node: (x, y + y_offset)
                    for node, (x, y) in positions.items()
                }

            if len(positions) == 1:
                node = next(iter(positions))
                viewport_width = max(self.flowchart_canvas.winfo_width(), 500)
                viewport_height = max(self.flowchart_canvas.winfo_height(), 320)
                positions[node] = (
                    max(40, (viewport_width - node_width) / 2),
                    max(40, (viewport_height - node_height) / 2),
                )

        source_edge_slots = {}
        target_edge_slots = {}

        for source, target, _requirement_type, _group in edges:
            if source not in positions or target not in positions:
                continue

            source_edge_slots.setdefault(source, []).append(target)
            target_edge_slots.setdefault(target, []).append(source)

        for source, targets in source_edge_slots.items():
            targets.sort(key=lambda target: (positions[target][1], positions[target][0], target))

        for target, sources in target_edge_slots.items():
            sources.sort(key=lambda source: (positions[source][1], positions[source][0], source))

        def anchor_y(node_y, index, count):
            if count <= 1:
                return node_y + node_height / 2

            return node_y + ((index + 1) / (count + 1)) * node_height

        def routed_mid_x(start_x, end_x, slot_index, slot_count):
            available_gap = end_x - start_x

            if available_gap <= 0:
                return min(start_x, end_x) - (42 + slot_index * 12) * scale

            lane_spacing = max(24 * scale, min(44 * scale, available_gap / 4))
            lane_from_target = (slot_count - slot_index) * lane_spacing
            mid_x = end_x - lane_from_target
            min_mid_x = start_x + 28 * scale
            max_mid_x = end_x - 28 * scale

            if min_mid_x > max_mid_x:
                return start_x + available_gap * 0.5

            return min(max(mid_x, min_mid_x), max_mid_x)

        def course_box_intersects_horizontal(y, x1, x2, source, target):
            left = min(x1, x2)
            right = max(x1, x2)

            for node, (box_x, box_y) in positions.items():
                if node in {source, target}:
                    continue

                if y <= box_y or y >= box_y + node_height:
                    continue

                if right <= box_x or left >= box_x + node_width:
                    continue

                return True

            return False

        def detour_y(source_y, target_y, source, target, x1, x2):
            candidates = [
                min(source_y, target_y) - (38 * scale),
                max(source_y, target_y) + node_height + (38 * scale),
                min(source_y, target_y) - (78 * scale),
                max(source_y, target_y) + node_height + (78 * scale),
            ]

            for candidate in candidates:
                if candidate < 20 * scale:
                    continue

                if not course_box_intersects_horizontal(candidate, x1, x2, source, target):
                    return candidate

            return None

        draw_edges = sorted(
            edges,
            key=lambda edge: (
                0 if edge[2] != "required" else 1,
                positions[edge[1]][0] if edge[1] in positions else 0,
                positions[edge[1]][1] if edge[1] in positions else 0,
                edge[0],
                edge[1],
            ),
        )

        for source, target, requirement_type, group in draw_edges:
            if source not in positions or target not in positions:
                continue

            source_x, source_y = positions[source]
            target_x, target_y = positions[target]
            targets_for_source = source_edge_slots.get(source, [])
            sources_for_target = target_edge_slots.get(target, [])
            source_slot_count = max(1, len(targets_for_source))
            target_slot_count = max(1, len(sources_for_target))
            source_slot_index = (
                targets_for_source.index(target)
                if target in targets_for_source
                else 0
            )
            target_slot_index = (
                sources_for_target.index(source)
                if source in sources_for_target
                else 0
            )
            source_anchor_y = anchor_y(source_y, source_slot_index, source_slot_count)
            target_anchor_y = anchor_y(target_y, target_slot_index, target_slot_count)
            is_highlighted_edge = (
                highlighted_nodes is None
                or (source in highlighted_nodes and target in highlighted_nodes)
            )
            line_color = "#2563eb" if requirement_type == "required" else "#7c3aed"
            line_width = 3 if is_highlighted_edge else 1
            source_is_open = is_course_open(source)
            target_is_open = is_course_open(target)

            if not is_highlighted_edge:
                line_color = "#cbd5e1"
            elif not source_is_open or not target_is_open:
                line_color = "#94a3b8"
                line_width = 1

            dash = () if requirement_type == "required" else (5, 3)
            start_x = source_x + node_width
            end_x = target_x

            if start_x < end_x:
                mid_x = routed_mid_x(
                    start_x,
                    end_x,
                    target_slot_index,
                    target_slot_count,
                )

                if course_box_intersects_horizontal(
                    source_anchor_y,
                    start_x,
                    mid_x,
                    source,
                    target,
                ):
                    bypass_y = detour_y(
                        source_y,
                        target_y,
                        source,
                        target,
                        start_x,
                        end_x,
                    )
                else:
                    bypass_y = None

                if bypass_y is None:
                    points = (
                        start_x,
                        source_anchor_y,
                        mid_x,
                        source_anchor_y,
                        mid_x,
                        target_anchor_y,
                        end_x,
                        target_anchor_y,
                    )
                else:
                    source_lane_x = start_x + 22 * scale
                    points = (
                        start_x,
                        source_anchor_y,
                        source_lane_x,
                        source_anchor_y,
                        source_lane_x,
                        bypass_y,
                        mid_x,
                        bypass_y,
                        mid_x,
                        target_anchor_y,
                        end_x,
                        target_anchor_y,
                    )
            else:
                route_offset = (42 + source_slot_index * 12) * scale
                mid_x = min(start_x, end_x) - route_offset
                points = (
                    start_x,
                    source_anchor_y,
                    mid_x,
                    source_anchor_y,
                    mid_x,
                    target_anchor_y,
                    end_x,
                    target_anchor_y,
                )

            self.flowchart_canvas.create_line(
                *points,
                arrow=tk.LAST,
                width=line_width,
                fill=line_color,
                dash=dash,
            )

        for node in nodes:
            x, y = positions[node]
            label = node.replace(" ", "")
            is_open = is_course_open(node)

            if node == preview_course:
                fill = "#fef3c7"
                outline = "#d97706"
            elif node in completed_courses:
                fill = "#dcfce7"
                outline = "#16a34a"
            elif is_open:
                fill = "#dbeafe"
                outline = "#2563eb"
            else:
                fill = "#f8fafc"
                outline = "#94a3b8"

            is_highlighted_node = highlighted_nodes is None or node in highlighted_nodes

            if not is_highlighted_node:
                fill = "#f8fafc"
                outline = "#e2e8f0"

            self.flowchart_canvas.create_rectangle(
                x,
                y,
                x + node_width,
                y + node_height,
                fill=fill,
                outline=outline,
                width=3 if node == self.flowchart_selected_course else 2,
                tags=("course_node", f"course:{node}"),
            )
            self.flowchart_canvas.create_text(
                x + node_width / 2,
                y + node_height / 2,
                text=label,
                width=0,
                font=("Segoe UI", font_size, "bold"),
                fill="#0f172a" if is_highlighted_node and (is_open or node == preview_course) else "#64748b",
                tags=("course_node", f"course:{node}"),
            )

        self.flowchart_canvas.tag_bind("course_node", "<Button-1>", self.select_flowchart_course)

        if positions:
            max_x = max(x for x, _y in positions.values()) + node_width + x_margin
            max_y = max(y for _x, y in positions.values()) + node_height + y_margin
        else:
            max_x = 600
            max_y = 400

        self.flowchart_canvas.configure(scrollregion=(0, 0, max_x, max_y))

    def zoom_flowchart(self, event):
        if getattr(event, "num", None) == 5 or getattr(event, "delta", 0) < 0:
            scale = 0.9
        else:
            scale = 1.1

        old_zoom = self.flowchart_scale
        next_zoom = self.flowchart_scale * scale

        if next_zoom < 0.3 or next_zoom > 3.0:
            return

        canvas_x = self.flowchart_canvas.canvasx(event.x)
        canvas_y = self.flowchart_canvas.canvasy(event.y)
        zoom_factor = next_zoom / old_zoom

        self.draw_flowchart(
            self.flowchart_nodes,
            completed_courses=self.flowchart_completed_courses,
            preview_course=self.flowchart_preview_course,
            scale=next_zoom,
        )

        self.flowchart_canvas.update_idletasks()
        new_region = self.flowchart_canvas.bbox("all")

        if not new_region:
            return

        scrollregion = self.flowchart_canvas.cget("scrollregion").split()

        if len(scrollregion) != 4:
            return

        _left, _top, right, bottom = (float(value) for value in scrollregion)
        new_width = max(1, right)
        new_height = max(1, bottom)
        viewport_width = max(1, self.flowchart_canvas.winfo_width())
        viewport_height = max(1, self.flowchart_canvas.winfo_height())
        max_x_fraction = max(0, (new_width - viewport_width) / new_width)
        max_y_fraction = max(0, (new_height - viewport_height) / new_height)
        target_x = (canvas_x * zoom_factor) - event.x
        target_y = (canvas_y * zoom_factor) - event.y

        self.flowchart_canvas.xview_moveto(
            max(0, min(max_x_fraction, target_x / new_width))
        )
        self.flowchart_canvas.yview_moveto(
            max(0, min(max_y_fraction, target_y / new_height))
        )

    def update_flowchart_info_button(self):
        if not hasattr(self, "flowchart_info_button"):
            return

        state = tk.NORMAL if self.flowchart_selected_course else tk.DISABLED
        self.flowchart_info_button.configure(state=state)

    def get_flowchart_snapshot(self):
        entry_text = ""

        if hasattr(self, "flowchart_course_entry"):
            entry_text = self.flowchart_course_entry.get()

        summary_text = ""

        if hasattr(self, "flowchart_summary"):
            summary_text = self.flowchart_summary.cget("text")

        no_prereq_title = "Starting-point courses"

        if hasattr(self, "no_prereq_title"):
            no_prereq_title = self.no_prereq_title.cget("text")

        xview = (0, 1)
        yview = (0, 1)

        if hasattr(self, "flowchart_canvas"):
            xview = self.flowchart_canvas.xview()
            yview = self.flowchart_canvas.yview()

        return {
            "nodes": set(self.flowchart_nodes),
            "completed_courses": set(self.flowchart_completed_courses),
            "preview_course": self.flowchart_preview_course,
            "direct_preview": self.flowchart_direct_preview,
            "scale": self.flowchart_scale,
            "selected_course": self.flowchart_selected_course,
            "entry_text": entry_text,
            "summary_text": summary_text,
            "no_prereq_courses": list(self.flowchart_no_prereq_courses),
            "no_prereq_title": no_prereq_title,
            "xview": xview,
            "yview": yview,
        }

    def restore_flowchart_snapshot(self, snapshot):
        self.show_flowchart_page()

        self.flowchart_course_entry.delete(0, tk.END)
        self.flowchart_course_entry.insert(0, snapshot.get("entry_text", ""))
        self.flowchart_selected_course = snapshot.get("selected_course")
        self.flowchart_direct_preview = snapshot.get("direct_preview", False)

        self.update_no_prereq_list(snapshot.get("no_prereq_courses", []))

        if hasattr(self, "no_prereq_title"):
            self.no_prereq_title.configure(
                text=snapshot.get("no_prereq_title", "Starting-point courses")
            )

        if snapshot.get("summary_text"):
            self.flowchart_summary.configure(text=snapshot["summary_text"])

        self.update_flowchart_info_button()
        self.draw_flowchart(
            snapshot.get("nodes", set()),
            completed_courses=snapshot.get("completed_courses", set()),
            preview_course=snapshot.get("preview_course"),
            scale=snapshot.get("scale", 1.0),
        )
        self.flowchart_canvas.update_idletasks()
        self.flowchart_canvas.xview_moveto(snapshot.get("xview", (0, 1))[0])
        self.flowchart_canvas.yview_moveto(snapshot.get("yview", (0, 1))[0])

    def show_selected_flowchart_course_info(self):
        if not self.flowchart_selected_course:
            return

        selected_course = self.flowchart_selected_course
        snapshot = self.get_flowchart_snapshot()

        self.show_course_information_page(
            selected_course,
            back_command=lambda snapshot=snapshot: self.restore_flowchart_snapshot(snapshot),
            back_text="Back to Flowchart",
        )

    def select_flowchart_course(self, event):
        clicked_item = self.flowchart_canvas.find_withtag(tk.CURRENT)
        
        if not clicked_item:
            return

        tags = self.flowchart_canvas.gettags(clicked_item[0])
        selected_course = None

        for tag in tags:
            if tag.startswith("course:"):
                selected_course = tag[len("course:"):]
                break

        if not selected_course:
            return

        if self.flowchart_selected_course == selected_course:
            self.flowchart_selected_course = None
            self.flowchart_summary.configure(text="Selection cleared.")
        else:
            self.flowchart_direct_preview = False
            self.flowchart_selected_course = selected_course
            path_nodes = self.get_prerequisite_path_nodes(selected_course)
            self.flowchart_nodes.update(path_nodes)
            required_count = len(path_nodes) - 1
            self.flowchart_summary.configure(
                text=(
                    f"Highlighting all possible prerequisite paths to {selected_course} "
                    f"({required_count} prerequisite courses/options shown). "
                    "Use View Selected Info for catalog details."
                )
            )

        self.update_flowchart_info_button()
        self.draw_flowchart(
            self.flowchart_nodes,
            completed_courses=self.flowchart_completed_courses,
            preview_course=self.flowchart_preview_course,
            scale=self.flowchart_scale,
        )

    def start_flowchart_pan(self, event):
        self.flowchart_canvas.scan_mark(event.x, event.y)

    def pan_flowchart(self, event):
        self.flowchart_canvas.scan_dragto(event.x, event.y, gain=1)

    def show_progress_flowchart(self):
        self.flowchart_selected_course = None
        self.flowchart_direct_preview = False
        self.update_flowchart_info_button()
        completed = set(self.completed_courses)
        nodes = completed
        self.update_no_prereq_list()
        self.flowchart_summary.configure(
            text=f"Currently displaying {len(completed)} completed/enrolled courses only."
        )
        self.draw_flowchart(nodes, completed_courses=completed, scale=self.flowchart_scale)

    def show_available_flowchart(self):
        self.flowchart_selected_course = None
        self.flowchart_direct_preview = False
        self.update_flowchart_info_button()
        completed = set(self.completed_courses)
        available = set(self.get_courses_unlocked_by_completed(completed))
        prerequisite_nodes = set()

        for course in available:
            prerequisite_nodes.update(
                prereq for prereq in self.get_direct_prerequisites(course)
                if prereq in completed
            )

        nodes = available | prerequisite_nodes
        self.update_no_prereq_list()
        self.flowchart_summary.configure(
            text=f"Currently displaying {len(available)} available courses."
        )
        self.draw_flowchart(nodes, completed_courses=completed, scale=self.flowchart_scale)

    def preview_flowchart_course(self, event=None):
        preview_course = self.normalize_course_input(self.flowchart_course_entry.get())

        if not preview_course:
            self.flowchart_summary.configure(text="Enter a course code to preview.")
            return

        if not self.is_displayable_course(preview_course):
            self.flowchart_summary.configure(text="Enter a normal course code, like CSC 360.")
            return

        completed = set(self.completed_courses)
        can_take_now = self.course_is_available(preview_course, completed)
        nodes = {preview_course}
        direct_prereqs = self.get_direct_prerequisites(preview_course)
        nodes.update(direct_prereqs)

        for prereq in direct_prereqs:
            nodes.update(self.get_direct_prerequisites(prereq))

        self.flowchart_selected_course = preview_course
        self.flowchart_direct_preview = True
        self.update_flowchart_info_button()
        self.update_no_prereq_list()
        status = "can be taken now" if can_take_now else "cannot be taken yet"
        self.flowchart_summary.configure(
            text=(
                f"Currently displaying {preview_course}, its prerequisites, and one prerequisite layer behind them. It {status}."
            )
        )
        self.draw_flowchart(
            nodes,
            completed_courses=completed,
            preview_course=preview_course,
            scale=self.flowchart_scale,
        )

    def show_subject_flowchart(self):
        self.flowchart_selected_course = None
        self.flowchart_direct_preview = False
        self.update_flowchart_info_button()
        subject = self.flowchart_subject.get()
        nodes, no_prereq_courses = self.split_subject_flowchart_courses(subject)
        self.update_no_prereq_list(no_prereq_courses, subject=subject)
        self.flowchart_summary.configure(
            text=(
                f"Currently displaying {len(nodes)} connected {subject} course nodes. "
                f"{len(no_prereq_courses)} starting-point courses are listed separately."
            )
        )
        self.draw_flowchart(
            nodes,
            completed_courses=set(self.completed_courses),
            scale=self.flowchart_scale,
        )


if __name__ == "__main__":
    app = CoursePostRequisitesApp()
    app.mainloop()
