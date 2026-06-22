"""Tkinter desktop GUI for Steam Idle Bot."""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from .config.settings import Settings, _parse_int_list
from .main import SteamIdleBot

APP_LOGGER_NAME = "steam_idle_bot"
PALETTE = {
    "bg": "#f3f6fb",
    "panel": "#fbfdff",
    "panel_alt": "#eef3f9",
    "border": "#d6dfec",
    "text": "#18212f",
    "muted": "#627086",
    "accent": "#0f5bd8",
    "accent_hover": "#0b4ab4",
    "accent_soft": "#dce9ff",
    "success_bg": "#dff4e8",
    "success_fg": "#155b35",
    "warning_bg": "#fff1d8",
    "warning_fg": "#8a5a00",
    "error_bg": "#ffe1df",
    "error_fg": "#9a2d20",
    "input_bg": "#ffffff",
    "console_bg": "#111927",
    "console_fg": "#e4ecf7",
    "report_bg": "#f7f9fc",
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


class SteamIdleBotGUI:
    """Desktop window for configuring and running the bot."""

    def __init__(self, root: tk.Tk, config_path: str | None = None) -> None:
        self.root = root
        self.root.title("Steam Idle Control Center")
        self.root.geometry("1200x760")
        self.root.minsize(980, 680)

        self._config_path = config_path
        self._ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._current_bot: SteamIdleBot | None = None
        self._log_handler: QueueLogHandler | None = None
        self._status_badge: tk.Label | None = None
        self._account_badge: tk.Label | None = None
        self._form_canvas: tk.Canvas | None = None
        self._form_window_id: int | None = None

        self.status_var = tk.StringVar(value="Idle")
        self.account_var = tk.StringVar(value="Not logged in")
        self.username_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.api_key_var = tk.StringVar()
        self.log_level_var = tk.StringVar(value="INFO")
        self.log_file_var = tk.StringVar(value="steam_card_idler.log")
        self.game_ids_var = tk.StringVar(value="570,730")
        self.exclude_ids_var = tk.StringVar()
        self.max_games_var = tk.StringVar(value="30")
        self.max_checks_var = tk.StringVar()
        self.api_timeout_var = tk.StringVar(value="10")
        self.rate_limit_var = tk.StringVar(value="0.5")
        self.cache_path_var = tk.StringVar(value=".cache/trading_cards.json")
        self.cache_ttl_var = tk.StringVar(value="30")
        self.filter_cards_var = tk.BooleanVar(value=True)
        self.use_owned_games_var = tk.BooleanVar(value=True)
        self.filter_completed_var = tk.BooleanVar(value=True)
        self.enable_cache_var = tk.BooleanVar(value=True)
        self.skip_failures_var = tk.BooleanVar(value=False)
        self.dry_run_var = tk.BooleanVar(value=False)
        self.title_font = self._pick_font(
            (
                "Aptos Display",
                "SF Pro Display",
                "Segoe UI Variable Display",
                "Segoe UI",
                "Helvetica",
            )
        )
        self.ui_font = self._pick_font(("Aptos", "SF Pro Text", "Segoe UI Variable Text", "Segoe UI", "Helvetica"))
        self.mono_font = self._pick_font(("JetBrains Mono", "Cascadia Code", "SF Mono", "Consolas", "Courier New"))
        self.style = ttk.Style(self.root)

        self._configure_theme()
        self._build_ui()
        self._load_initial_values()
        self._refresh_status_badges()
        self._poll_ui_queue()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    @staticmethod
    def _pick_font(candidates: tuple[str, ...]) -> str:
        available = set(tkfont.families())
        for family in candidates:
            if family in available:
                return family
        return "TkDefaultFont"

    def _configure_theme(self) -> None:
        self.style.theme_use("clam")
        self.root.configure(bg=PALETTE["bg"])

        default_font = (self.ui_font, 10)
        section_font = (self.ui_font, 11, "bold")

        self.style.configure(".", background=PALETTE["bg"], foreground=PALETTE["text"], font=default_font)
        self.style.configure("App.TFrame", background=PALETTE["bg"])
        self.style.configure("Surface.TFrame", background=PALETTE["panel"])
        self.style.configure("Header.TFrame", background=PALETTE["panel"])
        self.style.configure(
            "Card.TLabelframe",
            background=PALETTE["panel"],
            bordercolor=PALETTE["border"],
            relief="solid",
            borderwidth=1,
        )
        self.style.configure(
            "Card.TLabelframe.Label",
            background=PALETTE["panel"],
            foreground=PALETTE["text"],
            font=section_font,
        )
        self.style.configure(
            "Title.TLabel",
            background=PALETTE["panel"],
            foreground=PALETTE["text"],
            font=(self.title_font, 24, "bold"),
        )
        self.style.configure(
            "Subtitle.TLabel",
            background=PALETTE["panel"],
            foreground=PALETTE["muted"],
            font=(self.ui_font, 11),
        )
        self.style.configure(
            "Meta.TLabel",
            background=PALETTE["panel"],
            foreground=PALETTE["muted"],
            font=(self.ui_font, 10),
        )
        self.style.configure(
            "FieldLabel.TLabel",
            background=PALETTE["panel"],
            foreground=PALETTE["muted"],
            font=(self.ui_font, 10, "bold"),
        )
        self.style.configure(
            "App.TEntry",
            fieldbackground=PALETTE["input_bg"],
            foreground=PALETTE["text"],
            bordercolor=PALETTE["border"],
            lightcolor=PALETTE["border"],
            darkcolor=PALETTE["border"],
            insertcolor=PALETTE["text"],
            padding=(10, 8),
        )
        self.style.map(
            "App.TEntry",
            bordercolor=[("focus", PALETTE["accent"])],
            lightcolor=[("focus", PALETTE["accent"])],
            darkcolor=[("focus", PALETTE["accent"])],
        )
        self.style.configure(
            "Primary.TButton",
            background=PALETTE["accent"],
            foreground="#ffffff",
            borderwidth=0,
            font=(self.ui_font, 10, "bold"),
            padding=(14, 12),
        )
        self.style.map(
            "Primary.TButton",
            background=[
                ("active", PALETTE["accent_hover"]),
                ("disabled", PALETTE["border"]),
            ],
            foreground=[("disabled", PALETTE["muted"])],
        )
        self.style.configure(
            "Secondary.TButton",
            background=PALETTE["panel_alt"],
            foreground=PALETTE["text"],
            borderwidth=0,
            font=(self.ui_font, 10, "bold"),
            padding=(14, 12),
        )
        self.style.map(
            "Secondary.TButton",
            background=[
                ("active", PALETTE["accent_soft"]),
                ("disabled", PALETTE["border"]),
            ],
            foreground=[("disabled", PALETTE["muted"])],
        )
        self.style.configure(
            "SectionToggle.TButton",
            background=PALETTE["panel_alt"],
            foreground=PALETTE["text"],
            borderwidth=0,
            font=(self.ui_font, 10, "bold"),
            padding=(10, 8),
            anchor="w",
        )
        self.style.map(
            "SectionToggle.TButton",
            background=[("active", PALETTE["accent_soft"])],
        )
        self.style.configure(
            "App.TCheckbutton",
            background=PALETTE["panel"],
            foreground=PALETTE["text"],
            font=(self.ui_font, 10),
            padding=2,
        )
        self.style.map(
            "App.TCheckbutton",
            indicatorcolor=[
                ("selected", PALETTE["accent"]),
                ("active", PALETTE["accent_soft"]),
            ],
        )
        self.style.configure(
            "App.TNotebook",
            background=PALETTE["bg"],
            borderwidth=0,
        )
        self.style.configure(
            "App.TNotebook.Tab",
            background=PALETTE["panel_alt"],
            foreground=PALETTE["muted"],
            padding=(16, 10),
            font=(self.ui_font, 10, "bold"),
        )
        self.style.map(
            "App.TNotebook.Tab",
            background=[
                ("selected", PALETTE["panel"]),
                ("active", PALETTE["accent_soft"]),
            ],
            foreground=[("selected", PALETTE["text"]), ("active", PALETTE["text"])],
        )
        self.style.configure("App.TPanedwindow", background=PALETTE["bg"], sashrelief="flat")
        self.style.layout("Vertical.App.TScrollbar", self.style.layout("Vertical.TScrollbar"))
        self.style.layout("Horizontal.App.TScrollbar", self.style.layout("Horizontal.TScrollbar"))
        for scrollbar_style in ("Vertical.App.TScrollbar", "Horizontal.App.TScrollbar"):
            self.style.configure(
                scrollbar_style,
                background=PALETTE["panel_alt"],
                troughcolor=PALETTE["bg"],
                bordercolor=PALETTE["bg"],
                arrowcolor=PALETTE["muted"],
            )

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        header = ttk.Frame(self.root, padding=18, style="Header.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        hero = ttk.Frame(header, style="Header.TFrame")
        hero.grid(row=0, column=0, sticky="w")
        ttk.Label(hero, text="Steam Idle Control Center", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            hero,
            text="Configure sessions, review live logs and submit Steam auth codes in one place.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        status_frame = ttk.Frame(header, style="Header.TFrame")
        status_frame.grid(row=0, column=1, sticky="e")
        ttk.Label(status_frame, text="Status da sessão", style="Meta.TLabel").grid(row=0, column=0, sticky="e", padx=(0, 10))
        self._status_badge = tk.Label(
            status_frame,
            textvariable=self.status_var,
            padx=14,
            pady=8,
            bd=0,
            font=(self.ui_font, 10, "bold"),
        )
        self._status_badge.grid(row=0, column=1, sticky="e")
        ttk.Label(status_frame, text="Conta ativa", style="Meta.TLabel").grid(row=1, column=0, sticky="e", padx=(0, 10), pady=(10, 0))
        self._account_badge = tk.Label(
            status_frame,
            textvariable=self.account_var,
            padx=14,
            pady=8,
            bd=0,
            font=(self.ui_font, 10, "bold"),
            bg=PALETTE["accent_soft"],
            fg=PALETTE["text"],
        )
        self._account_badge.grid(row=1, column=1, sticky="e", pady=(10, 0))

        body = ttk.PanedWindow(self.root, orient="horizontal", style="App.TPanedwindow")
        body.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))

        form_host = ttk.Frame(body, style="Surface.TFrame")
        form_host.columnconfigure(0, weight=1)
        form_host.rowconfigure(0, weight=1)
        body.add(form_host, weight=1)

        form_canvas = tk.Canvas(
            form_host,
            bg=PALETTE["panel"],
            highlightthickness=0,
            bd=0,
            relief="flat",
        )
        form_canvas.grid(row=0, column=0, sticky="nsew")

        form_scrollbar = ttk.Scrollbar(
            form_host,
            orient="vertical",
            command=form_canvas.yview,
            style="App.TScrollbar",
        )
        form_scrollbar.grid(row=0, column=1, sticky="ns")
        form_canvas.configure(yscrollcommand=form_scrollbar.set)

        form = ttk.Frame(form_canvas, padding=16, style="Surface.TFrame")
        form.columnconfigure(1, weight=1)
        self._form_canvas = form_canvas
        self._form_window_id = form_canvas.create_window((0, 0), window=form, anchor="nw")

        form.bind("<Configure>", self._update_form_scrollregion)
        form_canvas.bind("<Configure>", self._resize_form_canvas_window)
        form_canvas.bind("<Enter>", self._bind_form_mousewheel)
        form_canvas.bind("<Leave>", self._unbind_form_mousewheel)

        console = ttk.Frame(body, padding=(0, 0, 0, 0), style="App.TFrame")
        console.columnconfigure(0, weight=1)
        console.rowconfigure(0, weight=1)
        body.add(console, weight=2)

        self._build_form(form)
        self._build_console(console)

    def _update_form_scrollregion(self, _event: tk.Event | None = None) -> None:
        if not self._form_canvas:
            return
        self._form_canvas.configure(scrollregion=self._form_canvas.bbox("all"))

    def _resize_form_canvas_window(self, event: tk.Event) -> None:
        if not self._form_canvas or self._form_window_id is None:
            return
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
        top_padding: int = 12,
    ) -> ttk.LabelFrame:
        container = ttk.Frame(parent, style="Surface.TFrame")
        container.grid(row=row, column=0, sticky="ew", pady=(top_padding, 0))
        container.columnconfigure(0, weight=1)

        state = {"open": default_open}
        header = ttk.Button(container, style="SectionToggle.TButton")
        header.grid(row=0, column=0, sticky="ew")

        content = ttk.LabelFrame(
            container,
            text=title,
            padding=16,
            style="Card.TLabelframe",
        )
        content.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        content.columnconfigure(1, weight=1)

        def render_header() -> None:
            icon = "▾" if state["open"] else "▸"
            header.configure(text=f"{icon} {title}")

        def toggle() -> None:
            state["open"] = not state["open"]
            if state["open"]:
                content.grid(row=1, column=0, sticky="ew", pady=(8, 0))
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

        steam_frame = self._create_collapsible_section(
            parent,
            row=row,
            title="🔐 Steam Access",
            default_open=True,
            top_padding=0,
        )
        self._add_labeled_entry(steam_frame, 0, "Username", self.username_var)
        self._add_labeled_entry(steam_frame, 1, "Password", self.password_var, show="*")
        self._add_labeled_entry(steam_frame, 2, "API Key", self.api_key_var, show="*")
        row += 1

        behavior_frame = self._create_collapsible_section(
            parent,
            row=row,
            title="⚙️ Session Behavior",
            default_open=True,
        )
        self._add_labeled_entry(behavior_frame, 0, "Max Games", self.max_games_var)
        self._add_labeled_entry(behavior_frame, 1, "Max Checks", self.max_checks_var)
        self._add_labeled_entry(behavior_frame, 2, "API Timeout", self.api_timeout_var)
        self._add_labeled_entry(behavior_frame, 3, "Rate Limit Delay", self.rate_limit_var)
        self._add_labeled_entry(behavior_frame, 4, "Log Level", self.log_level_var)
        self._add_labeled_entry(behavior_frame, 5, "Log File", self.log_file_var)
        row += 1

        selection_frame = self._create_collapsible_section(
            parent,
            row=row,
            title="🎮 Game Selection",
            default_open=False,
        )
        self._add_labeled_entry(selection_frame, 0, "Manual App IDs", self.game_ids_var)
        self._add_labeled_entry(selection_frame, 1, "Exclude App IDs", self.exclude_ids_var)
        row += 1

        cache_frame = self._create_collapsible_section(
            parent,
            row=row,
            title="🗂 Cache",
            default_open=False,
        )
        self._add_labeled_entry(cache_frame, 0, "Cache Path", self.cache_path_var)
        self._add_labeled_entry(cache_frame, 1, "Cache TTL (days)", self.cache_ttl_var)
        row += 1

        options_frame = self._create_collapsible_section(
            parent,
            row=row,
            title="✨ Runtime Options",
            default_open=False,
        )
        options = [
            ("Filter trading cards", self.filter_cards_var),
            ("Use owned games", self.use_owned_games_var),
            ("Filter completed drops", self.filter_completed_var),
            ("Enable cache", self.enable_cache_var),
            ("Skip card-check failures", self.skip_failures_var),
            ("Dry run", self.dry_run_var),
        ]
        for index, (label, variable) in enumerate(options):
            ttk.Checkbutton(options_frame, text=label, variable=variable, style="App.TCheckbutton").grid(row=index, column=0, sticky="w", pady=2)
        row += 1

        button_row = ttk.Frame(parent, padding=(0, 16, 0, 0))
        button_row.grid(row=row, column=0, sticky="ew")
        button_row.columnconfigure(0, weight=1)

        self.start_button = ttk.Button(
            button_row,
            text="▶ Start Session",
            command=self._start_bot,
            style="Primary.TButton",
        )
        self.start_button.grid(row=0, column=0, sticky="ew")

        self.stop_button = ttk.Button(
            button_row,
            text="■ Stop Session",
            command=self._stop_bot,
            state="disabled",
            style="Secondary.TButton",
        )
        self.stop_button.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        self.save_button = ttk.Button(
            button_row,
            text="💾 Save Settings",
            command=self._save_settings,
            style="Secondary.TButton",
        )
        self.save_button.grid(row=2, column=0, sticky="ew", pady=(8, 0))

    def _build_console(self, parent: ttk.Frame) -> None:
        notebook = ttk.Notebook(parent, style="App.TNotebook")
        notebook.grid(row=0, column=0, sticky="nsew")

        log_frame = ttk.Frame(notebook, padding=12, style="Surface.TFrame")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        notebook.add(log_frame, text="📝 Live Logs")

        report_frame = ttk.Frame(notebook, padding=12, style="Surface.TFrame")
        report_frame.columnconfigure(0, weight=1)
        report_frame.rowconfigure(0, weight=1)
        notebook.add(report_frame, text="📊 Session Report")

        self.log_text = tk.Text(
            log_frame,
            wrap="word",
            state="disabled",
            bg=PALETTE["console_bg"],
            fg=PALETTE["console_fg"],
            insertbackground=PALETTE["console_fg"],
            relief="flat",
            padx=14,
            pady=14,
            font=(self.mono_font, 10),
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(
            log_frame,
            orient="vertical",
            command=self.log_text.yview,
            style="App.TScrollbar",
        )
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

        self.report_text = tk.Text(
            report_frame,
            wrap="word",
            state="disabled",
            bg=PALETTE["report_bg"],
            fg=PALETTE["text"],
            insertbackground=PALETTE["text"],
            relief="flat",
            padx=16,
            pady=16,
            font=(self.ui_font, 11),
        )
        self.report_text.grid(row=0, column=0, sticky="nsew")
        report_scroll = ttk.Scrollbar(
            report_frame,
            orient="vertical",
            command=self.report_text.yview,
            style="App.TScrollbar",
        )
        report_scroll.grid(row=0, column=1, sticky="ns")
        self.report_text.configure(yscrollcommand=report_scroll.set)

    @staticmethod
    def _add_labeled_entry(
        parent: tk.Misc,
        row: int,
        label: str,
        variable: tk.StringVar,
        *,
        show: str | None = None,
    ) -> None:
        ttk.Label(parent, text=label, style="FieldLabel.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 12), pady=6)
        entry = ttk.Entry(parent, textvariable=variable, show=show or "", style="App.TEntry")
        entry.grid(row=row, column=1, sticky="ew", pady=4)

    def _load_initial_values(self) -> None:
        settings = self._try_load_settings()
        if settings is None:
            return

        self.username_var.set(settings.username)
        self.password_var.set(settings.password)
        self.api_key_var.set(settings.steam_api_key or "")
        self.log_level_var.set(settings.log_level)
        self.log_file_var.set(settings.log_file or "steam_card_idler.log")
        self.game_ids_var.set(",".join(str(item) for item in settings.game_app_ids))
        self.exclude_ids_var.set(",".join(str(item) for item in settings.exclude_app_ids))
        self.max_games_var.set(str(settings.max_games_to_idle))
        self.max_checks_var.set("" if settings.max_checks is None else str(settings.max_checks))
        self.api_timeout_var.set(str(settings.api_timeout))
        self.rate_limit_var.set(str(settings.rate_limit_delay))
        self.cache_path_var.set(settings.card_cache_path)
        self.cache_ttl_var.set(str(settings.card_cache_ttl_days))
        self.filter_cards_var.set(settings.filter_trading_cards)
        self.use_owned_games_var.set(settings.use_owned_games)
        self.filter_completed_var.set(settings.filter_completed_card_drops)
        self.enable_cache_var.set(settings.enable_card_cache)
        self.skip_failures_var.set(settings.skip_failures)

    def _try_load_settings(self) -> Settings | None:
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

        return Settings(
            username=self.username_var.get().strip(),
            password=self.password_var.get(),
            steam_api_key=self.api_key_var.get().strip() or None,
            game_app_ids=game_ids if isinstance(game_ids, list) else [],
            filter_trading_cards=self.filter_cards_var.get(),
            use_owned_games=self.use_owned_games_var.get(),
            filter_completed_card_drops=self.filter_completed_var.get(),
            exclude_app_ids=exclude_ids if isinstance(exclude_ids, list) else [],
            max_games_to_idle=int(self.max_games_var.get().strip()),
            log_level=self.log_level_var.get().strip().upper(),
            log_file=log_file_raw or None,
            api_timeout=int(self.api_timeout_var.get().strip()),
            rate_limit_delay=float(self.rate_limit_var.get().strip()),
            enable_card_cache=self.enable_cache_var.get(),
            card_cache_path=self.cache_path_var.get().strip(),
            card_cache_ttl_days=int(self.cache_ttl_var.get().strip()),
            max_checks=int(max_checks_raw) if max_checks_raw else None,
            skip_failures=self.skip_failures_var.get(),
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
        self._append_log("Starting bot from GUI...\n")
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
        bot.report_callback = lambda report: self._ui_queue.put(("report", report))
        bot.client.auth_code_provider = self._request_auth_code

        log_handler = QueueLogHandler(self._ui_queue)
        log_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
        logger = logging.getLogger(APP_LOGGER_NAME)
        logger.addHandler(log_handler)

        self._current_bot = bot
        self._log_handler = log_handler
        self._ui_queue.put(("status", "Running"))

        try:
            bot.run(dry_run=dry_run)
        except Exception as exc:
            self._ui_queue.put(("error", str(exc)))
        finally:
            logger.removeHandler(log_handler)
            self._current_bot = None
            self._log_handler = None
            self._ui_queue.put(("finished", bot.last_report))

    def _stop_bot(self) -> None:
        if not self._current_bot:
            return
        self.status_var.set("Stopping")
        self._refresh_status_badges()
        self._append_log("Stop requested from GUI...\n")
        self._current_bot.stop()

    def _save_settings(self) -> None:
        try:
            settings = self._build_settings_from_form()
            target = settings.save_to_env_file(Path(".env"))
        except Exception as exc:
            messagebox.showerror("Could not save settings", str(exc), parent=self.root)
            return

        messagebox.showinfo("Settings saved", f"Saved to {target}", parent=self.root)

    def _request_auth_code(self, is_2fa: bool, code_mismatch: bool) -> str | None:
        request = AuthCodeRequest(
            is_2fa=is_2fa,
            code_mismatch=code_mismatch,
            event=threading.Event(),
        )
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
            messagebox.showerror("Bot error", str(payload), parent=self.root)
            return

        if event_type == "finished":
            self.status_var.set("Idle")
            self._refresh_status_badges()
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            self._sync_account_from_username()
            return

        if event_type == "auth":
            self._resolve_auth_request(payload)

    def _resolve_auth_request(self, payload: object) -> None:
        request = payload
        if not isinstance(request, AuthCodeRequest):
            return

        code_type = "2FA" if request.is_2fa else "email"
        prompt = f"The previous {code_type} code was rejected. Enter a new code:" if request.code_mismatch else f"Enter the {code_type} code from Steam:"

        request.code = simpledialog.askstring(
            "Steam Authentication",
            prompt,
            parent=self.root,
        )
        request.event.set()

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message)
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

    def _sync_account_from_username(self) -> None:
        account = self.username_var.get().strip() or "Not logged in"
        self.account_var.set(account)
        if self._account_badge:
            self._account_badge.configure(bg=PALETTE["accent_soft"], fg=PALETTE["text"])

    def _refresh_status_badges(self) -> None:
        if not self._status_badge:
            return

        status = self.status_var.get().strip().lower()
        bg = PALETTE["accent_soft"]
        fg = PALETTE["accent"]
        if status in {"running", "starting"}:
            bg = PALETTE["success_bg"]
            fg = PALETTE["success_fg"]
        elif status == "stopping":
            bg = PALETTE["warning_bg"]
            fg = PALETTE["warning_fg"]
        elif status == "error":
            bg = PALETTE["error_bg"]
            fg = PALETTE["error_fg"]

        self._status_badge.configure(bg=bg, fg=fg)

    def _on_close(self) -> None:
        if self._current_bot:
            if not messagebox.askyesno(
                "Steam Idle Bot",
                "The bot is still running. Stop it and close the window?",
                parent=self.root,
            ):
                return
            self._stop_bot()

        self.root.after(100, self.root.destroy)


def launch_gui(config_path: str | None = None) -> None:
    """Launch the Tkinter desktop GUI."""
    root = tk.Tk()
    SteamIdleBotGUI(root, config_path=config_path)
    root.mainloop()
