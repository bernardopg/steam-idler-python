"""Tkinter desktop GUI for Steam Idle Bot."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Literal, cast

from .config.settings import Settings, _parse_int_list
from .main import SteamIdleBot, _stop_app_ids

APP_LOGGER_NAME = "steam_idle_bot"

BACKEND_CHOICES = ("python", "steam_utility")
LOG_LEVEL_CHOICES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
BROWSER_CHOICES = ("auto", "chrome", "firefox", "edge", "brave", "chromium", "opera", "vivaldi", "librewolf")


def _is_number_input(proposed: str) -> bool:
    """Tk key-validation: allow only an empty field or a non-negative number."""
    if proposed in ("", "."):
        return True
    try:
        return float(proposed) >= 0
    except ValueError:
        return False


PALETTE = {
    "bg": "#1a1b26",
    "surface": "#24283b",
    "surface_alt": "#1f2335",
    "overlay": "#292e42",
    "border": "#3b4261",
    "border_focus": "#7aa2f7",
    "text": "#c0caf5",
    "text_dim": "#565f89",
    "text_bright": "#e0e6ff",
    "accent": "#7aa2f7",
    "accent_hover": "#89b4fa",
    "accent_muted": "#2a3555",
    "success": "#9ece6a",
    "success_bg": "#1a2e1a",
    "success_fg": "#9ece6a",
    "warning": "#e0af68",
    "warning_bg": "#2e2a1a",
    "warning_fg": "#e0af68",
    "error": "#f7768e",
    "error_bg": "#2e1a1a",
    "error_fg": "#f7768e",
    "info": "#7dcfff",
    "input_bg": "#1f2335",
    "input_fg": "#c0caf5",
    "console_bg": "#16161e",
    "console_fg": "#a9b1d6",
    "report_bg": "#1f2335",
    "report_fg": "#c0caf5",
    "tree_bg": "#1f2335",
    "tree_fg": "#c0caf5",
    "tree_select": "#283457",
    "tree_heading_bg": "#292e42",
    "tree_heading_fg": "#7aa2f7",
    "scrollbar_bg": "#292e42",
    "scrollbar_fg": "#3b4261",
    "tab_bg": "#1f2335",
    "tab_active": "#24283b",
    "tab_fg": "#565f89",
    "tab_active_fg": "#c0caf5",
    "section_bg": "#24283b",
    "section_header_bg": "#292e42",
    "section_header_fg": "#7aa2f7",
    "badge_idle_bg": "#2a3555",
    "badge_idle_fg": "#7aa2f7",
    "badge_running_bg": "#1a2e1a",
    "badge_running_fg": "#9ece6a",
    "badge_stopping_bg": "#2e2a1a",
    "badge_stopping_fg": "#e0af68",
    "badge_error_bg": "#2e1a1a",
    "badge_error_fg": "#f7768e",
}


class QueueLogHandler(logging.Handler):
    """Forward log records into a thread-safe queue for the GUI."""

    def __init__(self, ui_queue: queue.Queue[tuple[str, object]]) -> None:
        super().__init__()
        self._ui_queue = ui_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:
            message = record.getMessage()
        self._ui_queue.put(("log", message))


@dataclass
class AuthCodeRequest:
    """A blocking auth-code request from the worker thread to the UI thread."""

    is_2fa: bool
    code_mismatch: bool
    event: threading.Event
    code: str | None = None


class _ToolTip:
    """Lightweight hover tooltip for any Tk widget."""

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self._tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _show(self, _event: tk.Event | None = None) -> None:
        if self._tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self._tip = tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tip,
            text=self.text,
            justify="left",
            bg=PALETTE["overlay"],
            fg=PALETTE["text_bright"],
            relief="solid",
            borderwidth=1,
            padx=8,
            pady=4,
            wraplength=320,
        ).pack()

    def _hide(self, _event: tk.Event | None = None) -> None:
        if self._tip is not None:
            with suppress(tk.TclError):
                self._tip.destroy()
            self._tip = None


class SteamIdleBotGUI:
    """Desktop window for configuring and running the bot."""

    def __init__(
        self,
        root: tk.Tk,
        config_path: str | None = None,
        *,
        initial_settings: Settings | None = None,
        initial_dry_run: bool = False,
    ) -> None:
        self.root = root
        self.root.title("Steam Idle Control Center")
        self.root.geometry("1280x820")
        self.root.minsize(1020, 700)
        self.root.configure(bg=PALETTE["bg"])

        self._config_path = config_path
        self._initial_settings = initial_settings
        self._ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._current_bot: SteamIdleBot | None = None
        self._log_handler: QueueLogHandler | None = None
        self._status_badge: tk.Label | None = None
        self._account_badge: tk.Label | None = None
        self._form_canvas: tk.Canvas | None = None
        self._form_window_id: int | None = None
        self._auto_scroll = True
        self.status_tree: ttk.Treeview
        self.status_summary_var = tk.StringVar(value="Waiting to start...")
        self.start_button: ttk.Button
        self.stop_button: ttk.Button
        self.log_text: tk.Text
        self.report_text: tk.Text

        self.status_var = tk.StringVar(value="Idle")
        self.account_var = tk.StringVar(value="Not logged in")
        self.username_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.api_key_var = tk.StringVar()
        self.log_level_var = tk.StringVar(value="INFO")
        self.log_file_var = tk.StringVar(value="steam_card_idler.log")
        self.game_ids_var = tk.StringVar()
        self.exclude_ids_var = tk.StringVar()
        self.max_games_var = tk.StringVar(value="32")
        self.max_checks_var = tk.StringVar()
        self.refresh_interval_var = tk.StringVar(value="600")
        self.checkpoint_minutes_var = tk.StringVar(value="0")
        self.duration_minutes_var = tk.StringVar(value="0")
        self.post_run_verify_seconds_var = tk.StringVar(value="0")
        self.api_timeout_var = tk.StringVar(value="10")
        self.rate_limit_var = tk.StringVar(value="0.5")
        self.idling_backend_var = tk.StringVar(value="python")
        self.steam_utility_path_var = tk.StringVar()
        self.steam_web_cookies_var = tk.StringVar()
        self.browser_cookies_browser_var = tk.StringVar(value="auto")
        self.cache_path_var = tk.StringVar(value=".cache/trading_cards.json")
        self.cache_ttl_var = tk.StringVar(value="30")
        self.drop_cache_path_var = tk.StringVar(value=".cache/no_drop_cards.json")
        self.drop_cache_ttl_var = tk.StringVar(value="90")
        self.stop_app_ids_var = tk.StringVar()
        self.filter_cards_var = tk.BooleanVar(value=True)
        self.use_owned_games_var = tk.BooleanVar(value=True)
        self.filter_completed_var = tk.BooleanVar(value=True)
        self.enable_cache_var = tk.BooleanVar(value=True)
        self.auto_browser_cookies_var = tk.BooleanVar(value=True)
        self.skip_failures_var = tk.BooleanVar(value=False)
        self.enable_encryption_var = tk.BooleanVar(value=False)
        self.dry_run_var = tk.BooleanVar(value=initial_dry_run)

        self.title_font = self._pick_font(("Aptos Display", "SF Pro Display", "Segoe UI Variable Display", "Segoe UI", "Helvetica"))
        self.ui_font = self._pick_font(("Aptos", "SF Pro Text", "Segoe UI Variable Text", "Segoe UI", "Helvetica"))
        self.mono_font = self._pick_font(("JetBrains Mono", "Cascadia Code", "SF Mono", "Consolas", "Courier New"))
        self.style = ttk.Style(self.root)

        self._configure_theme()
        self._build_ui()
        self._load_initial_values()
        self._refresh_status_badges()
        self._poll_ui_queue()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._bind_keyboard_shortcuts()
        self._center_window()

    def _center_window(self) -> None:
        """Place the window in the middle of the screen on launch."""
        with suppress(tk.TclError):
            self.root.update_idletasks()
            width = self.root.winfo_width() or 1280
            height = self.root.winfo_height() or 820
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            x = max(0, (screen_w - width) // 2)
            y = max(0, (screen_h - height) // 3)
            self.root.geometry(f"+{x}+{y}")

    @staticmethod
    def _pick_font(candidates: tuple[str, ...]) -> str:
        available = set(tkfont.families())
        for family in candidates:
            if family in available:
                return family
        return "TkDefaultFont"

    def _configure_theme(self) -> None:
        self.style.theme_use("clam")
        P = PALETTE

        default_font = (self.ui_font, 10)
        section_font = (self.ui_font, 10, "bold")

        self.style.configure(".", background=P["bg"], foreground=P["text"], font=default_font)
        self.style.configure("TFrame", background=P["bg"])
        self.style.configure("App.TFrame", background=P["bg"])
        self.style.configure("Surface.TFrame", background=P["surface"])
        self.style.configure("Header.TFrame", background=P["surface"])
        self.style.configure("Section.TFrame", background=P["surface"])

        self.style.configure(
            "Card.TLabelframe",
            background=P["surface"],
            bordercolor=P["border"],
            relief="solid",
            borderwidth=1,
        )
        self.style.configure(
            "Card.TLabelframe.Label",
            background=P["surface"],
            foreground=P["accent"],
            font=section_font,
        )

        self.style.configure(
            "Title.TLabel",
            background=P["surface"],
            foreground=P["text_bright"],
            font=(self.title_font, 22, "bold"),
        )
        self.style.configure(
            "Subtitle.TLabel",
            background=P["surface"],
            foreground=P["text_dim"],
            font=(self.ui_font, 10),
        )
        self.style.configure(
            "Meta.TLabel",
            background=P["surface"],
            foreground=P["text_dim"],
            font=(self.ui_font, 9),
        )
        self.style.configure(
            "FieldLabel.TLabel",
            background=P["surface"],
            foreground=P["text_dim"],
            font=(self.ui_font, 9, "bold"),
        )
        self.style.configure(
            "Hint.TLabel",
            background=P["surface"],
            foreground=P["text_dim"],
            font=(self.ui_font, 8),
        )

        self.style.configure(
            "App.TEntry",
            fieldbackground=P["input_bg"],
            foreground=P["input_fg"],
            bordercolor=P["border"],
            lightcolor=P["border"],
            darkcolor=P["border"],
            insertcolor=P["text"],
            padding=(8, 6),
        )
        self.style.map(
            "App.TEntry",
            bordercolor=[("focus", P["border_focus"])],
            lightcolor=[("focus", P["border_focus"])],
            darkcolor=[("focus", P["border_focus"])],
            fieldbackground=[("focus", P["overlay"])],
        )

        self.style.configure(
            "Primary.TButton",
            background=P["accent"],
            foreground=P["console_bg"],
            borderwidth=0,
            font=(self.ui_font, 10, "bold"),
            padding=(16, 10),
        )
        self.style.map(
            "Primary.TButton",
            background=[("active", P["accent_hover"]), ("disabled", P["overlay"])],
            foreground=[("disabled", P["text_dim"])],
        )
        self.style.configure(
            "Danger.TButton",
            background=P["error"],
            foreground=P["console_bg"],
            borderwidth=0,
            font=(self.ui_font, 10, "bold"),
            padding=(16, 10),
        )
        self.style.map(
            "Danger.TButton",
            background=[("active", "#ff8fa3"), ("disabled", P["overlay"])],
            foreground=[("disabled", P["text_dim"])],
        )
        self.style.configure(
            "Secondary.TButton",
            background=P["overlay"],
            foreground=P["text"],
            borderwidth=0,
            font=(self.ui_font, 10),
            padding=(12, 8),
        )
        self.style.map(
            "Secondary.TButton",
            background=[("active", P["accent_muted"]), ("disabled", P["surface_alt"])],
            foreground=[("disabled", P["text_dim"])],
        )
        self.style.configure(
            "SectionToggle.TButton",
            background=P["section_header_bg"],
            foreground=P["section_header_fg"],
            borderwidth=0,
            font=(self.ui_font, 10, "bold"),
            padding=(10, 7),
            anchor="w",
        )
        self.style.map(
            "SectionToggle.TButton",
            background=[("active", P["accent_muted"])],
        )
        self.style.configure(
            "App.TCheckbutton",
            background=P["surface"],
            foreground=P["text"],
            font=(self.ui_font, 10),
            padding=2,
        )
        self.style.map(
            "App.TCheckbutton",
            indicatorcolor=[("selected", P["accent"]), ("active", P["accent_muted"])],
        )

        self.style.configure(
            "App.TCombobox",
            fieldbackground=P["input_bg"],
            background=P["overlay"],
            foreground=P["input_fg"],
            arrowcolor=P["accent"],
            bordercolor=P["border"],
            lightcolor=P["border"],
            darkcolor=P["border"],
            selectbackground=P["accent_muted"],
            selectforeground=P["text"],
            padding=(8, 6),
        )
        self.style.map(
            "App.TCombobox",
            fieldbackground=[("readonly", P["input_bg"]), ("focus", P["overlay"])],
            foreground=[("readonly", P["input_fg"])],
            bordercolor=[("focus", P["border_focus"])],
            lightcolor=[("focus", P["border_focus"])],
            darkcolor=[("focus", P["border_focus"])],
        )
        # Drop-down listbox (a classic Tk widget, not themed by ttk).
        self.root.option_add("*TCombobox*Listbox.background", P["surface_alt"])
        self.root.option_add("*TCombobox*Listbox.foreground", P["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", P["accent_muted"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", P["text_bright"])

        self.style.configure(
            "App.TNotebook",
            background=P["bg"],
            borderwidth=0,
        )
        self.style.configure(
            "App.TNotebook.Tab",
            background=P["tab_bg"],
            foreground=P["tab_fg"],
            padding=(14, 8),
            font=(self.ui_font, 10, "bold"),
        )
        self.style.map(
            "App.TNotebook.Tab",
            background=[
                ("selected", P["tab_active"]),
                ("active", P["overlay"]),
            ],
            foreground=[
                ("selected", P["tab_active_fg"]),
                ("active", P["text"]),
            ],
        )

        self.style.configure("App.TPanedwindow", background=P["bg"], sashrelief="flat")

        for orient in ("Vertical", "Horizontal"):
            sname = f"{orient}.App.TScrollbar"
            self.style.layout(sname, self.style.layout(f"{orient}.TScrollbar"))
            self.style.configure(
                sname,
                background=P["scrollbar_fg"],
                troughcolor=P["scrollbar_bg"],
                bordercolor=P["bg"],
                arrowcolor=P["text_dim"],
            )
            self.style.map(
                sname,
                background=[("active", P["text_dim"])],
            )

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        header = ttk.Frame(self.root, padding=(18, 14, 18, 10), style="Header.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        hero = ttk.Frame(header, style="Header.TFrame")
        hero.grid(row=0, column=0, sticky="w")
        ttk.Label(hero, text="Steam Idle Control Center", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            hero,
            text="Configure and monitor your Steam card-dropping sessions",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        status_frame = ttk.Frame(header, style="Header.TFrame")
        status_frame.grid(row=0, column=1, sticky="e", padx=(0, 4))
        status_frame.rowconfigure(0, weight=0)
        status_frame.rowconfigure(1, weight=0)

        ttk.Label(status_frame, text="STATUS", style="Meta.TLabel").grid(row=0, column=0, sticky="e", padx=(0, 8))
        self._status_badge = tk.Label(
            status_frame,
            textvariable=self.status_var,
            padx=12,
            pady=5,
            bd=0,
            font=(self.ui_font, 9, "bold"),
            relief="flat",
        )
        self._status_badge.grid(row=0, column=1, sticky="e")

        ttk.Label(status_frame, text="ACCOUNT", style="Meta.TLabel").grid(row=1, column=0, sticky="e", padx=(0, 8), pady=(6, 0))
        self._account_badge = tk.Label(
            status_frame,
            textvariable=self.account_var,
            padx=12,
            pady=5,
            bd=0,
            font=(self.ui_font, 9, "bold"),
            relief="flat",
        )
        self._account_badge.grid(row=1, column=1, sticky="e", pady=(6, 0))

        body = ttk.PanedWindow(self.root, orient="horizontal", style="App.TPanedwindow")
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        form_host = ttk.Frame(body, style="Surface.TFrame")
        form_host.columnconfigure(0, weight=1)
        form_host.rowconfigure(0, weight=1)
        body.add(form_host, weight=1)

        form_canvas = tk.Canvas(
            form_host,
            bg=PALETTE["surface"],
            highlightthickness=0,
            bd=0,
            relief="flat",
        )
        form_canvas.grid(row=0, column=0, sticky="nsew")

        form_scrollbar = ttk.Scrollbar(form_host, orient="vertical", command=form_canvas.yview, style="App.TScrollbar")
        form_scrollbar.grid(row=0, column=1, sticky="ns")
        form_canvas.configure(yscrollcommand=form_scrollbar.set)

        form = ttk.Frame(form_canvas, padding=(14, 12, 14, 12), style="Surface.TFrame")
        form.columnconfigure(0, weight=1)
        self._form_canvas = form_canvas
        self._form_window_id = form_canvas.create_window((0, 0), window=form, anchor="nw")

        form.bind("<Configure>", self._update_form_scrollregion)
        form_canvas.bind("<Configure>", self._resize_form_canvas_window)
        form_canvas.bind("<Enter>", self._bind_form_mousewheel)
        form_canvas.bind("<Leave>", self._unbind_form_mousewheel)

        console = ttk.Frame(body, padding=0, style="App.TFrame")
        console.columnconfigure(0, weight=1)
        console.rowconfigure(0, weight=1)
        body.add(console, weight=2)

        self._build_form(form)
        self._build_console(console)

    def _update_form_scrollregion(self, _event: tk.Event | None = None) -> None:
        if self._form_canvas:
            self._form_canvas.configure(scrollregion=self._form_canvas.bbox("all"))

    def _resize_form_canvas_window(self, event: tk.Event) -> None:
        if self._form_canvas and self._form_window_id is not None:
            self._form_canvas.itemconfigure(self._form_window_id, width=event.width)

    def _bind_form_mousewheel(self, _event: tk.Event) -> None:
        self.root.bind_all("<MouseWheel>", self._on_form_mousewheel)
        self.root.bind_all("<Button-4>", self._on_form_mousewheel)
        self.root.bind_all("<Button-5>", self._on_form_mousewheel)

    def _unbind_form_mousewheel(self, _event: tk.Event) -> None:
        self.root.unbind_all("<MouseWheel>")
        self.root.unbind_all("<Button-4>")
        self.root.unbind_all("<Button-5>")

    def _on_form_mousewheel(self, event: tk.Event) -> None:
        if not self._form_canvas:
            return
        if hasattr(event, "delta") and event.delta:
            self._form_canvas.yview_scroll(int(-event.delta / 120), "units")
            return
        if getattr(event, "num", None) == 4:
            self._form_canvas.yview_scroll(-3, "units")
        elif getattr(event, "num", None) == 5:
            self._form_canvas.yview_scroll(3, "units")

    def _create_collapsible_section(
        self,
        parent: ttk.Frame,
        *,
        row: int,
        title: str,
        default_open: bool = True,
        top_padding: int = 8,
    ) -> ttk.LabelFrame:
        container = ttk.Frame(parent, style="Section.TFrame")
        container.grid(row=row, column=0, sticky="ew", pady=(top_padding, 0))
        container.columnconfigure(0, weight=1)

        state = {"open": default_open}
        header = ttk.Button(container, style="SectionToggle.TButton")
        header.grid(row=0, column=0, sticky="ew")

        content = ttk.LabelFrame(container, text=title, padding=12, style="Card.TLabelframe")
        content.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        content.columnconfigure(1, weight=1)

        def render_header() -> None:
            icon = "\u25be" if state["open"] else "\u25b8"
            header.configure(text=f"  {icon}  {title}")

        def toggle() -> None:
            state["open"] = not state["open"]
            if state["open"]:
                content.grid(row=1, column=0, sticky="ew", pady=(4, 0))
            else:
                content.grid_remove()
            render_header()
            self.root.after_idle(self._update_form_scrollregion)

        header.configure(command=toggle)
        if not default_open:
            content.grid_remove()
        render_header()
        return content

    def _build_form(self, parent: ttk.Frame) -> None:
        row = 0

        steam_frame = self._create_collapsible_section(parent, row=row, title="Steam Access", default_open=True, top_padding=0)
        self._add_labeled_entry(steam_frame, 0, "Username", self.username_var, hint="Your Steam account login name.")
        password_entry = self._add_labeled_entry(steam_frame, 1, "Password", self.password_var, show="*", hint="Only stored locally in .env when you Save; only sent to Steam.")
        self.show_password_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            steam_frame,
            text="Show password",
            variable=self.show_password_var,
            style="App.TCheckbutton",
            command=lambda: password_entry.configure(show="" if self.show_password_var.get() else "*"),
        ).grid(row=2, column=1, sticky="w", pady=(0, 4))
        self._add_labeled_entry(steam_frame, 3, "API Key (optional)", self.api_key_var, show="*", hint="Steam Web API key — enables the owned-games and badge APIs (fewer page scrapes).")
        row += 1

        behavior_frame = self._create_collapsible_section(parent, row=row, title="Session Behavior", default_open=True)
        self._add_labeled_entry(behavior_frame, 0, "Max Games", self.max_games_var, numeric=True, hint="How many games to idle at once (Steam hard limit is 32).")
        self._add_labeled_entry(behavior_frame, 1, "Refresh Interval (sec)", self.refresh_interval_var, numeric=True, hint="How often the game-selection pipeline re-runs while idling (min 10).")
        self._add_labeled_entry(behavior_frame, 2, "Duration (min, 0=unlimited)", self.duration_minutes_var, numeric=True, hint="Stop idling after this many minutes. 0 keeps running until you stop it.")
        self._add_labeled_entry(behavior_frame, 3, "Checkpoint (min, 0=off)", self.checkpoint_minutes_var, numeric=True, hint="Write a JSON/Markdown snapshot of the live session every N minutes.")
        self._add_labeled_entry(behavior_frame, 4, "Post-run Verify (sec)", self.post_run_verify_seconds_var, numeric=True, hint="Re-scrape card counts N seconds after stopping (badge pages lag behind real drops).")
        self._add_labeled_entry(behavior_frame, 5, "Max Checks", self.max_checks_var, numeric=True, hint="Cap how many games get card-checked per run. Blank = no cap.")
        row += 1

        backend_frame = self._create_collapsible_section(parent, row=row, title="Idle Backend", default_open=False)
        self._add_labeled_combobox(backend_frame, 0, "Backend", self.idling_backend_var, BACKEND_CHOICES, hint="python = built-in Steam client; steam_utility = external native idler.")
        self._add_labeled_entry(backend_frame, 1, "steam-utility Path", self.steam_utility_path_var, hint="Path to the steam-utility-multiplataform repo (auto-discovered if blank).")
        self._add_labeled_entry(backend_frame, 2, "API Timeout (sec)", self.api_timeout_var, numeric=True, hint="HTTP timeout for Steam Web API / scraping requests.")
        self._add_labeled_entry(backend_frame, 3, "Rate Limit Delay (sec)", self.rate_limit_var, numeric=True, hint="Pause between scrape requests to stay under Steam rate limits.")
        row += 1

        selection_frame = self._create_collapsible_section(parent, row=row, title="Game Selection", default_open=False)
        self._add_labeled_entry(selection_frame, 0, "Manual App IDs (CSV)", self.game_ids_var)
        self._add_labeled_entry(selection_frame, 1, "Exclude App IDs (CSV)", self.exclude_ids_var)
        row += 1

        cache_frame = self._create_collapsible_section(parent, row=row, title="Cache", default_open=False)
        self._add_labeled_entry(cache_frame, 0, "Card Cache Path", self.cache_path_var)
        self._add_labeled_entry(cache_frame, 1, "Card Cache TTL (days)", self.cache_ttl_var, numeric=True, hint="How long a cached has-cards verdict stays valid.")
        self._add_labeled_entry(cache_frame, 2, "No-drop Cache Path", self.drop_cache_path_var)
        self._add_labeled_entry(cache_frame, 3, "No-drop Cache TTL (days)", self.drop_cache_ttl_var, numeric=True, hint="How long a cached no-remaining-drops verdict stays valid.")
        row += 1

        web_frame = self._create_collapsible_section(parent, row=row, title="Web Session", default_open=False)
        self._add_labeled_entry(web_frame, 0, "Steam Web Cookies (JSON)", self.steam_web_cookies_var, hint="Optional manual community cookies. Usually auto-recovered from a browser instead.")
        self._add_labeled_combobox(web_frame, 1, "Browser", self.browser_cookies_browser_var, BROWSER_CHOICES, hint="Which browser to pull a logged-in Steam community session from. auto tries all.")
        row += 1

        options_frame = self._create_collapsible_section(parent, row=row, title="Runtime Options", default_open=False)
        options = [
            ("Filter by trading cards", self.filter_cards_var),
            ("Use owned games API", self.use_owned_games_var),
            ("Skip already-farmed games (no drops left)", self.filter_completed_var),
            ("Enable card cache", self.enable_cache_var),
            ("Auto-detect browser cookies", self.auto_browser_cookies_var),
            ("Skip card-check failures", self.skip_failures_var),
            ("Enable encryption", self.enable_encryption_var),
        ]
        for index, (label, variable) in enumerate(options):
            ttk.Checkbutton(options_frame, text=label, variable=variable, style="App.TCheckbutton").grid(row=index, column=0, columnspan=2, sticky="w", pady=2)
        row += 1

        log_frame = self._create_collapsible_section(parent, row=row, title="Logging", default_open=False)
        self._add_labeled_combobox(log_frame, 0, "Log Level", self.log_level_var, LOG_LEVEL_CHOICES, hint="Verbosity of the log output. DEBUG is very chatty.")
        self._add_labeled_entry(log_frame, 1, "Log File", self.log_file_var)
        row += 1

        maintenance_frame = self._create_collapsible_section(parent, row=row, title="Maintenance", default_open=False)
        self._add_labeled_entry(maintenance_frame, 0, "Stop App IDs (CSV)", self.stop_app_ids_var)
        ttk.Button(
            maintenance_frame,
            text="Stop App IDs Now",
            command=self._stop_app_ids_now,
            style="Danger.TButton",
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        row += 1

        button_row = ttk.Frame(parent, padding=(0, 12, 0, 0), style="Surface.TFrame")
        button_row.grid(row=row, column=0, sticky="ew")
        button_row.columnconfigure(0, weight=1)
        button_row.columnconfigure(1, weight=1)
        button_row.columnconfigure(2, weight=1)

        dry_run_check = ttk.Checkbutton(
            button_row,
            text="Dry run — print the plan, never contact Steam",
            variable=self.dry_run_var,
            style="App.TCheckbutton",
        )
        dry_run_check.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        _ToolTip(dry_run_check, "Loads settings and prints the chosen games without logging in or idling. Good for a sanity check.")

        self.start_button = ttk.Button(button_row, text="Start Session", command=self._start_bot, style="Primary.TButton")
        self.start_button.grid(row=1, column=0, sticky="ew", padx=(0, 4))

        self.stop_button = ttk.Button(
            button_row,
            text="Stop Session",
            command=self._stop_bot,
            state="disabled",
            style="Danger.TButton",
        )
        self.stop_button.grid(row=1, column=1, sticky="ew", padx=(4, 4))

        self.save_button = ttk.Button(button_row, text="Save Settings", command=self._save_settings, style="Secondary.TButton")
        self.save_button.grid(row=1, column=2, sticky="ew", padx=(4, 0))

    def _build_console(self, parent: ttk.Frame) -> None:
        notebook = ttk.Notebook(parent, style="App.TNotebook")
        notebook.grid(row=0, column=0, sticky="nsew")

        log_container = ttk.Frame(notebook, style="Surface.TFrame")
        log_container.columnconfigure(0, weight=1)
        log_container.rowconfigure(1, weight=1)
        notebook.add(log_container, text="  Live Logs  ")

        log_toolbar = ttk.Frame(log_container, style="Surface.TFrame", padding=(8, 4))
        log_toolbar.grid(row=0, column=0, sticky="ew")
        self._auto_scroll_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            log_toolbar,
            text="Auto-scroll",
            variable=self._auto_scroll_var,
            style="App.TCheckbutton",
            command=self._toggle_auto_scroll,
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            log_toolbar,
            text="Clear",
            command=self._clear_logs,
            style="Secondary.TButton",
        ).grid(row=0, column=1, sticky="e")
        log_toolbar.columnconfigure(0, weight=1)

        log_frame = ttk.Frame(log_container, style="Surface.TFrame")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        log_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        self.log_text = tk.Text(
            log_frame,
            wrap="word",
            state="disabled",
            bg=PALETTE["console_bg"],
            fg=PALETTE["console_fg"],
            insertbackground=PALETTE["console_fg"],
            selectbackground=PALETTE["accent_muted"],
            selectforeground=PALETTE["text"],
            relief="flat",
            padx=10,
            pady=10,
            font=(self.mono_font, 10),
            borderwidth=0,
            highlightthickness=0,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview, style="App.TScrollbar")
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.tag_configure("INFO", foreground=PALETTE["console_fg"])
        self.log_text.tag_configure("WARNING", foreground=PALETTE["warning"])
        self.log_text.tag_configure("ERROR", foreground=PALETTE["error"])
        self.log_text.tag_configure("DEBUG", foreground=PALETTE["text_dim"])
        self.log_text.tag_configure("SUCCESS", foreground=PALETTE["success"])

        status_container = ttk.Frame(notebook, style="Surface.TFrame")
        status_container.columnconfigure(0, weight=1)
        status_container.rowconfigure(0, weight=1)
        notebook.add(status_container, text="  Status Panel  ")
        self._build_status_panel(status_container)

        report_container = ttk.Frame(notebook, style="Surface.TFrame")
        report_container.columnconfigure(0, weight=1)
        report_container.rowconfigure(0, weight=1)
        notebook.add(report_container, text="  Session Report  ")

        report_toolbar = ttk.Frame(report_container, style="Surface.TFrame", padding=(8, 4))
        report_toolbar.grid(row=0, column=0, sticky="ew")
        ttk.Button(
            report_toolbar,
            text="Clear",
            command=self._clear_report,
            style="Secondary.TButton",
        ).grid(row=0, column=0, sticky="e")
        report_toolbar.columnconfigure(0, weight=1)

        report_frame = ttk.Frame(report_container, style="Surface.TFrame")
        report_frame.columnconfigure(0, weight=1)
        report_frame.rowconfigure(0, weight=1)
        report_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        self.report_text = tk.Text(
            report_frame,
            wrap="word",
            state="disabled",
            bg=PALETTE["report_bg"],
            fg=PALETTE["report_fg"],
            insertbackground=PALETTE["report_fg"],
            selectbackground=PALETTE["accent_muted"],
            selectforeground=PALETTE["text"],
            relief="flat",
            padx=10,
            pady=10,
            font=(self.mono_font, 10),
            borderwidth=0,
            highlightthickness=0,
        )
        self.report_text.grid(row=0, column=0, sticky="nsew")
        report_scroll = ttk.Scrollbar(report_frame, orient="vertical", command=self.report_text.yview, style="App.TScrollbar")
        report_scroll.grid(row=0, column=1, sticky="ns")
        self.report_text.configure(yscrollcommand=report_scroll.set)

        self._status_update_job: Any = None
        self._start_status_updates()

    def _stop_status_updates(self) -> None:
        if self._status_update_job is not None:
            self.root.after_cancel(self._status_update_job)
            self._status_update_job = None

    def _build_status_panel(self, parent: ttk.Frame) -> None:
        columns = ("index", "app_id", "game", "cards_remaining", "idle_time")
        self.status_tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="browse")
        self.status_tree.heading("index", text="#")
        self.status_tree.heading("app_id", text="App ID")
        self.status_tree.heading("game", text="Game")
        self.status_tree.heading("cards_remaining", text="Cards Left")
        self.status_tree.heading("idle_time", text="Idle Time")
        self.status_tree.column("index", width=40, anchor="center", stretch=False)
        self.status_tree.column("app_id", width=80, anchor="center", stretch=False)
        self.status_tree.column("game", width=260, anchor="w")
        self.status_tree.column("cards_remaining", width=100, anchor="center")
        self.status_tree.column("idle_time", width=90, anchor="center")

        style = self.style
        style.configure("Treeview", background=PALETTE["tree_bg"], foreground=PALETTE["tree_fg"], fieldbackground=PALETTE["tree_bg"], borderwidth=0, font=(self.ui_font, 10))
        style.configure("Treeview.Heading", background=PALETTE["tree_heading_bg"], foreground=PALETTE["tree_heading_fg"], borderwidth=0, font=(self.ui_font, 9, "bold"))
        style.map("Treeview", background=[("selected", PALETTE["tree_select"])], foreground=[("selected", PALETTE["text_bright"])])
        style.map("Treeview.Heading", background=[("active", PALETTE["accent_muted"])])

        self.status_tree.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        status_scroll = ttk.Scrollbar(parent, orient="vertical", command=self.status_tree.yview, style="App.TScrollbar")
        status_scroll.grid(row=0, column=1, sticky="ns", pady=8)
        self.status_tree.configure(yscrollcommand=status_scroll.set)

        summary_frame = ttk.Frame(parent, style="Surface.TFrame")
        summary_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))
        summary_frame.columnconfigure(0, weight=1)
        ttk.Label(summary_frame, textvariable=self.status_summary_var, style="Subtitle.TLabel", anchor="w").grid(row=0, column=0, sticky="ew")

    def _start_status_updates(self) -> None:
        self._update_status_panel()
        self._status_update_job = self.root.after(2000, self._start_status_updates)

    def _update_status_panel(self) -> None:
        if not self._current_bot:
            self.status_summary_var.set("Waiting to start...")
            for item in self.status_tree.get_children():
                self.status_tree.delete(item)
            return

        tracker = self._current_bot._idle_tracker
        if not tracker:
            return

        game_names = self._current_bot._game_name_map()
        games = list(tracker.games.values())

        if not games:
            self.status_summary_var.set("No games idling")
            for item in self.status_tree.get_children():
                self.status_tree.delete(item)
            return

        existing_items = {int(self.status_tree.item(item, "values")[1]): item for item in self.status_tree.get_children()}

        total_cards = 0
        for index, game in enumerate(sorted(games, key=lambda g: g.app_id), start=1):
            name = game_names.get(game.app_id) or game.name or f"App {game.app_id}"
            # Prefer the most recent count: cards_after is updated while idling;
            # cards_before is the snapshot taken when the game was added.
            latest = game.cards_after if game.cards_after is not None else game.cards_before
            cards = str(latest) if latest is not None else "?"
            if latest is not None:
                total_cards += latest
            idle_min = f"{game.idle_minutes:.0f} min"

            values = (str(index), str(game.app_id), name, cards, idle_min)

            if game.app_id in existing_items:
                self.status_tree.item(existing_items[game.app_id], values=values)
                del existing_items[game.app_id]
            else:
                self.status_tree.insert("", "end", values=values)

        for item in existing_items.values():
            self.status_tree.delete(item)

        session_min = tracker.session_minutes
        cards_label = str(total_cards) if total_cards > 0 else "unknown (badge API empty)"
        self.status_summary_var.set(f"{len(games)} games idling  |  cards remaining: {cards_label}  |  session: {session_min:.0f} min")

    @staticmethod
    def _add_labeled_entry(
        parent: tk.Misc,
        row: int,
        label: str,
        variable: tk.StringVar,
        *,
        show: str | None = None,
        hint: str | None = None,
        numeric: bool = False,
    ) -> ttk.Entry:
        label_widget = ttk.Label(parent, text=label, style="FieldLabel.TLabel")
        label_widget.grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        entry = ttk.Entry(parent, textvariable=variable, show=show or "", style="App.TEntry")
        if numeric:
            vcmd = (entry.register(_is_number_input), "%P")
            entry.configure(validate="key", validatecommand=vcmd)
        entry.grid(row=row, column=1, sticky="ew", pady=3)
        if hint:
            _ToolTip(label_widget, hint)
            _ToolTip(entry, hint)
        return entry

    @staticmethod
    def _add_labeled_combobox(
        parent: tk.Misc,
        row: int,
        label: str,
        variable: tk.StringVar,
        values: tuple[str, ...],
        *,
        hint: str | None = None,
    ) -> ttk.Combobox:
        label_widget = ttk.Label(parent, text=label, style="FieldLabel.TLabel")
        label_widget.grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        combo = ttk.Combobox(parent, textvariable=variable, values=list(values), state="readonly", style="App.TCombobox")
        combo.grid(row=row, column=1, sticky="ew", pady=3)
        if hint:
            _ToolTip(label_widget, hint)
            _ToolTip(combo, hint)
        return combo

    def _load_initial_values(self) -> None:
        settings = self._try_load_settings()
        if settings is None:
            return

        self.username_var.set(settings.username)
        self.password_var.set(settings.password)
        self.api_key_var.set(settings.steam_api_key or "")
        self.log_level_var.set(settings.log_level)
        self.log_file_var.set(settings.log_file or "steam_card_idler.log")
        self.game_ids_var.set(",".join(str(item) for item in settings.game_app_ids) if settings.game_app_ids else "")
        self.exclude_ids_var.set(",".join(str(item) for item in settings.exclude_app_ids) if settings.exclude_app_ids else "")
        self.max_games_var.set(str(settings.max_games_to_idle))
        self.max_checks_var.set("" if settings.max_checks is None else str(settings.max_checks))
        self.refresh_interval_var.set(str(settings.refresh_interval_seconds))
        self.checkpoint_minutes_var.set(str(settings.checkpoint_minutes))
        self.duration_minutes_var.set(str(settings.duration_minutes))
        self.post_run_verify_seconds_var.set(str(settings.post_run_verify_seconds))
        self.api_timeout_var.set(str(settings.api_timeout))
        self.rate_limit_var.set(str(settings.rate_limit_delay))
        self.idling_backend_var.set(settings.idling_backend)
        self.steam_utility_path_var.set(settings.steam_utility_path or "")
        self.steam_web_cookies_var.set(json.dumps(settings.steam_web_cookies) if settings.steam_web_cookies else "")
        self.browser_cookies_browser_var.set(settings.browser_cookies_browser)
        self.cache_path_var.set(settings.card_cache_path)
        self.cache_ttl_var.set(str(settings.card_cache_ttl_days))
        self.drop_cache_path_var.set(settings.drop_cache_path)
        self.drop_cache_ttl_var.set(str(settings.drop_cache_ttl_days))
        self.filter_cards_var.set(settings.filter_trading_cards)
        self.use_owned_games_var.set(settings.use_owned_games)
        self.filter_completed_var.set(settings.filter_completed_card_drops)
        self.enable_cache_var.set(settings.enable_card_cache)
        self.auto_browser_cookies_var.set(settings.auto_browser_cookies)
        self.skip_failures_var.set(settings.skip_failures)
        self.enable_encryption_var.set(settings.enable_encryption)

    def _try_load_settings(self) -> Settings | None:
        if self._initial_settings is not None:
            return self._initial_settings
        config_path = Path(self._config_path) if self._config_path else None
        try:
            return Settings.load_from_file(config_path)
        except Exception:
            return None

    def _build_settings_from_form(self) -> Settings:
        game_ids = _parse_int_list(self.game_ids_var.get())
        exclude_ids = _parse_int_list(self.exclude_ids_var.get())
        max_checks_raw = self.max_checks_var.get().strip()
        log_file_raw = self.log_file_var.get().strip()
        steam_utility_path_raw = self.steam_utility_path_var.get().strip()
        steam_web_cookies_raw = self.steam_web_cookies_var.get().strip()
        steam_web_cookies = json.loads(steam_web_cookies_raw) if steam_web_cookies_raw else {}

        return Settings(
            username=self.username_var.get().strip(),
            password=self.password_var.get(),
            steam_api_key=self.api_key_var.get().strip() or None,
            game_app_ids=game_ids if isinstance(game_ids, list) else [],
            filter_trading_cards=self.filter_cards_var.get(),
            use_owned_games=self.use_owned_games_var.get(),
            filter_completed_card_drops=self.filter_completed_var.get(),
            exclude_app_ids=exclude_ids if isinstance(exclude_ids, list) else [],
            max_games_to_idle=int(self.max_games_var.get().strip() or "32"),
            refresh_interval_seconds=int(self.refresh_interval_var.get().strip() or "600"),
            idling_backend=cast(Literal["python", "steam_utility"], self.idling_backend_var.get().strip() or "python"),
            steam_utility_path=steam_utility_path_raw or None,
            steam_web_cookies=steam_web_cookies,
            log_level=self.log_level_var.get().strip().upper() or "INFO",
            log_file=log_file_raw or None,
            api_timeout=int(self.api_timeout_var.get().strip() or "10"),
            rate_limit_delay=float(self.rate_limit_var.get().strip() or "0.5"),
            enable_card_cache=self.enable_cache_var.get(),
            card_cache_path=self.cache_path_var.get().strip() or ".cache/trading_cards.json",
            card_cache_ttl_days=int(self.cache_ttl_var.get().strip() or "30"),
            drop_cache_path=self.drop_cache_path_var.get().strip() or ".cache/no_drop_cards.json",
            drop_cache_ttl_days=int(self.drop_cache_ttl_var.get().strip() or "90"),
            auto_browser_cookies=self.auto_browser_cookies_var.get(),
            browser_cookies_browser=self.browser_cookies_browser_var.get().strip() or "auto",
            max_checks=int(max_checks_raw) if max_checks_raw else None,
            skip_failures=self.skip_failures_var.get(),
            checkpoint_minutes=int(self.checkpoint_minutes_var.get().strip() or "0"),
            duration_minutes=int(self.duration_minutes_var.get().strip() or "0"),
            post_run_verify_seconds=int(self.post_run_verify_seconds_var.get().strip() or "0"),
            enable_encryption=self.enable_encryption_var.get(),
        )

    def _start_bot(self) -> None:
        if self._worker and self._worker.is_alive():
            return

        try:
            settings = self._build_settings_from_form()
        except Exception as exc:
            messagebox.showerror("Invalid settings", str(exc), parent=self.root)
            return

        self._clear_report()
        self._append_log("Starting bot...\n")
        self.status_var.set("Starting")
        self.account_var.set("Connecting")
        self._refresh_status_badges()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")

        worker = threading.Thread(
            target=self._run_bot_worker,
            args=(settings, self.dry_run_var.get()),
            daemon=True,
        )
        self._worker = worker
        worker.start()

    def _run_bot_worker(self, settings: Settings, dry_run: bool) -> None:
        bot = SteamIdleBot(settings, console_output=False)
        bot.client.auth_code_provider = self._request_auth_code

        runs_dir = Path("logs") / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_log_path = runs_dir / f"run_{time.strftime('%Y%m%d_%H%M%SZ', time.gmtime())}.log"
        self._ui_queue.put(("log", f"Run log: {run_log_path}"))

        def emit_report(report: str) -> None:
            self._ui_queue.put(("report", report))
            with suppress(Exception), run_log_path.open("a", encoding="utf-8") as handle:
                handle.write("\n")
                handle.write(report)
                handle.write("\n")

        bot.report_callback = emit_report

        log_handler = QueueLogHandler(self._ui_queue)
        formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S")
        log_handler.setFormatter(formatter)
        run_log_handler = logging.FileHandler(run_log_path, encoding="utf-8")
        run_log_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
        logger = logging.getLogger(APP_LOGGER_NAME)
        logger.addHandler(log_handler)
        logger.addHandler(run_log_handler)

        self._current_bot = bot
        self._log_handler = log_handler
        self._ui_queue.put(("status", "Running"))

        try:
            bot.run(dry_run=dry_run)
        except Exception as exc:
            self._ui_queue.put(("error", str(exc)))
        finally:
            logger.removeHandler(log_handler)
            logger.removeHandler(run_log_handler)
            run_log_handler.close()
            self._current_bot = None
            self._log_handler = None
            self._ui_queue.put(("finished", bot.last_report))

    def _stop_bot(self) -> None:
        if not self._current_bot:
            return
        self.status_var.set("Stopping")
        self._refresh_status_badges()
        self._append_log("Stop requested...\n")
        self._current_bot.stop()
        self._stop_status_updates()

    def _stop_app_ids_now(self) -> None:
        if self._worker and self._worker.is_alive():
            messagebox.showwarning(
                "Bot running",
                "Stop App IDs is only available when no session is running.",
                parent=self.root,
            )
            return

        raw_app_ids = self.stop_app_ids_var.get().strip()
        if not raw_app_ids:
            raw_app_ids = simpledialog.askstring("Stop App IDs", "App IDs to stop (comma-separated):", parent=self.root) or ""

        app_ids = _parse_int_list(raw_app_ids)
        if not app_ids:
            messagebox.showwarning("No App IDs", "Enter at least one App ID to stop.", parent=self.root)
            return

        try:
            settings = self._build_settings_from_form()
            status = _stop_app_ids(settings, app_ids)
        except Exception as exc:
            messagebox.showerror("Could not stop App IDs", str(exc), parent=self.root)
            return

        self._append_log(f"Stop App IDs {app_ids} finished (status {status})\n")
        if status == 0:
            messagebox.showinfo(
                "Stop App IDs",
                f"Stopped App IDs: {', '.join(str(app_id) for app_id in app_ids)}",
                parent=self.root,
            )
        else:
            messagebox.showerror("Stop App IDs", f"Stop command failed with status {status}", parent=self.root)

    def _save_settings(self) -> None:
        try:
            settings = self._build_settings_from_form()
            target = settings.save_to_env_file(Path(".env"))
        except Exception as exc:
            messagebox.showerror("Could not save settings", str(exc), parent=self.root)
            return
        messagebox.showinfo("Settings saved", f"Saved to {target}", parent=self.root)

    def _request_auth_code(self, is_2fa: bool, code_mismatch: bool) -> str | None:
        request = AuthCodeRequest(is_2fa=is_2fa, code_mismatch=code_mismatch, event=threading.Event())
        self._ui_queue.put(("auth", request))
        request.event.wait()
        return request.code

    def _poll_ui_queue(self) -> None:
        while True:
            try:
                event_type, payload = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_ui_event(event_type, payload)
        self.root.after(100, self._poll_ui_queue)

    def _handle_ui_event(self, event_type: str, payload: object) -> None:
        if event_type == "log":
            self._append_log(f"{payload}\n")
            self._sync_account_from_username()
            return
        if event_type == "status":
            self.status_var.set(str(payload))
            self._refresh_status_badges()
            return
        if event_type == "report":
            self._set_report(str(payload))
            return
        if event_type == "error":
            self.status_var.set("Error")
            self._refresh_status_badges()
            self._append_log(f"ERROR: {payload}\n")
            self._stop_status_updates()
            return
        if event_type == "finished":
            self.status_var.set("Idle")
            self._refresh_status_badges()
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            self._sync_account_from_username()
            self._stop_status_updates()
            return
        if event_type == "auth":
            self._resolve_auth_request(payload)

    def _resolve_auth_request(self, payload: object) -> None:
        request = payload
        if not isinstance(request, AuthCodeRequest):
            return
        code_type = "2FA" if request.is_2fa else "email"
        prompt = f"Previous {code_type} code rejected. Enter a new code:" if request.code_mismatch else f"Enter the {code_type} code from Steam:"
        request.code = simpledialog.askstring("Steam Authentication", prompt, parent=self.root)
        request.event.set()

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        tag: str | None = None
        for level in ("ERROR", "WARNING", "INFO", "DEBUG"):
            if f" | {level} " in message or message.startswith(level):
                tag = level
                break
        if "connected" in message.lower() or "started" in message.lower():
            tag = "SUCCESS"
        if tag:
            self.log_text.insert("end", message, tag)
        else:
            self.log_text.insert("end", message)
        if self._auto_scroll:
            self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_report(self, report: str) -> None:
        self.report_text.configure(state="normal")
        self.report_text.delete("1.0", "end")
        self.report_text.insert("1.0", report)
        self.report_text.configure(state="disabled")

    def _clear_report(self) -> None:
        self.report_text.configure(state="normal")
        self.report_text.delete("1.0", "end")
        self.report_text.configure(state="disabled")

    def _clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _toggle_auto_scroll(self) -> None:
        self._auto_scroll = self._auto_scroll_var.get()

    def _sync_account_from_username(self) -> None:
        account = self.username_var.get().strip() or "Not logged in"
        self.account_var.set(account)

    def _refresh_status_badges(self) -> None:
        status = self.status_var.get().strip().lower()
        if self._status_badge:
            if status in {"running", "starting"}:
                bg, fg = PALETTE["badge_running_bg"], PALETTE["badge_running_fg"]
            elif status == "stopping":
                bg, fg = PALETTE["badge_stopping_bg"], PALETTE["badge_stopping_fg"]
            elif status == "error":
                bg, fg = PALETTE["badge_error_bg"], PALETTE["badge_error_fg"]
            else:
                bg, fg = PALETTE["badge_idle_bg"], PALETTE["badge_idle_fg"]
            self._status_badge.configure(bg=bg, fg=fg)

        if self._account_badge:
            account = self.account_var.get().strip()
            if account and account != "Not logged in" and account != "Connecting":
                bg, fg = PALETTE["badge_running_bg"], PALETTE["badge_running_fg"]
            elif account == "Connecting":
                bg, fg = PALETTE["badge_stopping_bg"], PALETTE["badge_stopping_fg"]
            else:
                bg, fg = PALETTE["badge_idle_bg"], PALETTE["badge_idle_fg"]
            self._account_badge.configure(bg=bg, fg=fg)

    def _bind_keyboard_shortcuts(self) -> None:
        self.root.bind("<Control-Return>", lambda _: self._start_bot())
        self.root.bind("<Escape>", lambda _: self._stop_bot())
        self.root.bind("<Control-l>", lambda _: self._clear_logs())
        self.root.bind("<Control-s>", lambda _: self._save_settings())

    def _on_close(self) -> None:
        if self._current_bot:
            if not messagebox.askyesno(
                "Steam Idle Bot",
                "The bot is still running. Stop it and close?",
                parent=self.root,
            ):
                return
            self._stop_bot()
        self.root.after(100, self.root.destroy)


def launch_gui(
    config_path: str | None = None,
    *,
    initial_settings: Settings | None = None,
    initial_dry_run: bool = False,
) -> None:
    """Launch the Tkinter desktop GUI."""
    import signal

    root = tk.Tk()
    gui = SteamIdleBotGUI(
        root,
        config_path=config_path,
        initial_settings=initial_settings,
        initial_dry_run=initial_dry_run,
    )

    def _handle_signal(signum: int, _frame: object) -> None:
        if gui._current_bot:
            gui._current_bot.signal_stop(signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(ValueError, OSError, AttributeError):
            signal.signal(sig, _handle_signal)

    root.mainloop()
