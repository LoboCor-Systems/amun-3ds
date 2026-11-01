"""Tkinter application for AMUN profile authoring and memory research."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable

from .brand import (
    BRAND_GOLD,
    BRAND_MARK_64,
    BRAND_MARK_256,
    BRAND_MIDNIGHT,
    BRAND_PAPYRUS,
    metal_tier_icon,
)
from compiler.metal_tiers import MetalTier, format_tier_counts, metal_tier, tier_counts
from .cli import CliError, CliResult, StudioSettings, format_command, parse_command
from .deployment import (
    DeploymentError,
    DeploymentTransaction,
    SdDeployer,
    detect_sd_cards,
)
from .debugger import ConditionDebugger, DebugReport
from .library import LibraryConflict, LibraryEntry, LibraryError, ProfileLibrary
from .project import ProfileProject, ProjectError, resolver_summary
from .live import (
    GdbMiClient,
    LiveError,
    LiveMemoryClient,
    LiveWatch,
    LumaRspClient,
    ProcessInfo,
    WatchSymbol,
    WatchValue,
    suggest_process,
)
from .scanner import (
    MemorySnapshot,
    ScanError,
    SnapshotScanner,
    VALUE_TYPES,
    format_scan_value,
)


def achievement_metal_summary(achievements: Any) -> str:
    """One-line per-metal count for the achievement table, e.g. ``Metals: Bronze 6, Silver 20``.

    Tiers are derived from ``points`` (docs/metal-tiers.md); 0-point helpers are
    reported separately as unranked because they are excluded from completion %.
    """
    points = [definition.get("points") for definition in achievements if isinstance(definition, dict)]
    counts = tier_counts(points)
    ranked = format_tier_counts(counts)
    unranked = counts[MetalTier.NONE]
    parts = [f"Metals: {ranked}" if ranked else "Metals: none"]
    if unranked:
        parts.append(f"{unranked} unranked")
    return " · ".join(parts)


class JsonObjectDialog(tk.Toplevel):
    """Small modal JSON-object editor used by the profile tables."""

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        value: dict[str, Any],
        *,
        identifier: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.result: tuple[str | None, dict[str, Any]] | None = None
        self.identifier_var = tk.StringVar(value=identifier or "")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        if identifier is not None:
            row = ttk.Frame(self, padding=(8, 8, 8, 0))
            row.grid(row=0, column=0, sticky="ew")
            row.columnconfigure(1, weight=1)
            ttk.Label(row, text="Identifier").grid(row=0, column=0, padx=(0, 8))
            ttk.Entry(row, textvariable=self.identifier_var).grid(row=0, column=1, sticky="ew")

        text_row = 1 if identifier is not None else 0
        frame = ttk.Frame(self, padding=8)
        frame.grid(row=text_row, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.editor = tk.Text(frame, width=72, height=22, wrap="none", undo=True)
        y_scroll = ttk.Scrollbar(frame, orient="vertical", command=self.editor.yview)
        x_scroll = ttk.Scrollbar(frame, orient="horizontal", command=self.editor.xview)
        self.editor.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.editor.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.editor.insert("1.0", json.dumps(value, indent=2, ensure_ascii=False))

        buttons = ttk.Frame(self, padding=(8, 0, 8, 8))
        buttons.grid(row=text_row + 1, column=0, sticky="e")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(buttons, text="Apply", command=self._accept).pack(side="right")
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Control-Return>", lambda _event: self._accept())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.geometry("680x520")
        self.grab_set()
        self.editor.focus_set()

    def _accept(self) -> None:
        try:
            value = json.loads(self.editor.get("1.0", "end-1c"))
            if not isinstance(value, dict):
                raise ValueError("The definition must be a JSON object")
            identifier = self.identifier_var.get().strip() if self.identifier_var.get() else None
            if self.identifier_var.get() and not identifier:
                raise ValueError("Identifier cannot be empty")
        except (json.JSONDecodeError, ValueError) as error:
            messagebox.showerror("Invalid definition", str(error), parent=self)
            return
        self.result = (identifier, value)
        self.destroy()


class StudioApplication:
    RESULT_DISPLAY_LIMIT = 5000
    DIRECT_LUMA_BACKEND = "Direct Luma RSP (recommended)"
    EXTERNAL_GDB_BACKEND = "External GDB/MI"

    def __init__(
        self,
        root: tk.Tk,
        settings: StudioSettings | None = None,
        initial_project: str | os.PathLike[str] | None = None,
    ) -> None:
        self.root = root
        self.settings = settings or StudioSettings.load()
        self.project: ProfileProject | None = None
        self.scanner = SnapshotScanner()
        self.initial_snapshot: MemorySnapshot | None = None
        self.next_snapshot: MemorySnapshot | None = None
        self.latest_snapshot: MemorySnapshot | None = None
        self.last_transaction: DeploymentTransaction | None = None
        self.live_client: LiveMemoryClient | None = None
        self.live_watch: LiveWatch | None = None
        self.condition_debugger: ConditionDebugger | None = None
        self.library = ProfileLibrary(self.settings.library_directory)
        self.library_rows: dict[str, LibraryEntry] = {}
        self.jobs: queue.Queue[tuple[str, object | None, BaseException | None, Callable[[object], None] | None]] = queue.Queue()

        self.brand_icon = self._load_brand_image(BRAND_MARK_256)
        self.brand_header_mark = self._load_brand_image(BRAND_MARK_64)
        # Platform metal-tier trophies for achievement rows (derived from points).
        self.metal_icons: dict[MetalTier, tk.PhotoImage] = {}
        for tier in MetalTier:
            if tier is MetalTier.NONE:
                continue
            image = self._load_brand_image(metal_tier_icon(tier.slug, 16))
            if image is not None:
                self.metal_icons[tier] = image

        root.title("AMUN Studio")
        if self.brand_icon is not None:
            try:
                root.iconphoto(True, self.brand_icon)
            except tk.TclError:
                # Some window managers do not expose iconphoto; branding must
                # never prevent the authoring tool from opening.
                pass
        root.minsize(980, 680)
        root.geometry("1240x820")
        root.protocol("WM_DELETE_WINDOW", self._close)
        self._create_menu()
        self._create_layout()
        self.root.after(100, self._poll_jobs)
        if initial_project:
            self.open_project(initial_project)

    @staticmethod
    def _load_brand_image(path: Path) -> tk.PhotoImage | None:
        try:
            return tk.PhotoImage(file=str(path))
        except (OSError, tk.TclError):
            return None

    def _create_menu(self) -> None:
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="New Profile…", accelerator="Ctrl+N", command=self.new_project)
        file_menu.add_command(label="Open Profile…", accelerator="Ctrl+O", command=self.choose_profile)
        file_menu.add_command(label="Open Project Directory…", command=self.choose_project_directory)
        file_menu.add_separator()
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save_project)
        file_menu.add_command(label="Save As…", command=self.save_project_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._close)
        menu.add_cascade(label="File", menu=file_menu)

        tools_menu = tk.Menu(menu, tearoff=False)
        tools_menu.add_command(label="Validate Profile", command=self.validate_profile)
        tools_menu.add_command(label="Build Pack", command=self.build_profile)
        tools_menu.add_separator()
        tools_menu.add_command(label="Configure CLI…", command=self.configure_cli)
        tools_menu.add_command(label="Configure Backup Directory…", command=self.configure_backup_directory)
        tools_menu.add_command(label="Configure Profile Library…", command=self.choose_library_directory)
        menu.add_cascade(label="Tools", menu=tools_menu)
        self.root.configure(menu=menu)
        self.root.bind_all("<Control-n>", lambda _event: self.new_project())
        self.root.bind_all("<Control-o>", lambda _event: self.choose_profile())
        self.root.bind_all("<Control-s>", lambda _event: self.save_project())

    def _create_layout(self) -> None:
        brand = tk.Frame(self.root, background=BRAND_MIDNIGHT, padx=12, pady=8)
        brand.pack(fill="x", side="top")
        if self.brand_header_mark is not None:
            tk.Label(
                brand,
                image=self.brand_header_mark,
                background=BRAND_MIDNIGHT,
                borderwidth=0,
            ).pack(side="left", padx=(0, 10))
        identity = tk.Frame(brand, background=BRAND_MIDNIGHT)
        identity.pack(side="left", fill="y")
        tk.Label(
            identity,
            text="AMUN Studio",
            background=BRAND_MIDNIGHT,
            foreground=BRAND_GOLD,
            font=("TkDefaultFont", 16, "bold"),
            anchor="w",
        ).pack(fill="x", anchor="w")
        tk.Label(
            identity,
            text="Achievement authoring · memory research · safe deployment",
            background=BRAND_MIDNIGHT,
            foreground=BRAND_PAPYRUS,
            anchor="w",
        ).pack(fill="x", anchor="w")

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)
        self.profile_tab = ttk.Frame(self.notebook, padding=8)
        self.debugger_tab = ttk.Frame(self.notebook, padding=8)
        self.scanner_tab = ttk.Frame(self.notebook, padding=8)
        self.live_tab = ttk.Frame(self.notebook, padding=8)
        self.deploy_tab = ttk.Frame(self.notebook, padding=8)
        self.log_tab = ttk.Frame(self.notebook, padding=8)
        self.library_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.profile_tab, text="Profile")
        self.notebook.add(self.debugger_tab, text="Condition Debugger")
        self.notebook.add(self.scanner_tab, text="Memory Scanner")
        self.notebook.add(self.live_tab, text="Live 3DS")
        self.notebook.add(self.deploy_tab, text="Deploy to SD")
        self.notebook.add(self.log_tab, text="Log")
        self.notebook.add(self.library_tab, text="Local Library")
        self._create_profile_tab()
        self._create_debugger_tab()
        self._create_scanner_tab()
        self._create_live_tab()
        self._create_deploy_tab()
        self._create_log_tab()
        self._create_library_tab()
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self.root, textvariable=self.status_var, anchor="w", relief="sunken").pack(
            fill="x", side="bottom"
        )
        self.refresh_library()

    def _create_profile_tab(self) -> None:
        tab = self.profile_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(tab)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.project_var = tk.StringVar(value="No project open")
        ttk.Label(toolbar, textvariable=self.project_var).pack(side="left", fill="x", expand=True)
        for label, callback in (
            ("Apply JSON", self.apply_editor),
            ("Format", self.format_editor),
            ("Save", self.save_project),
            ("Validate", self.validate_profile),
            ("Build", self.build_profile),
        ):
            ttk.Button(toolbar, text=label, command=callback).pack(side="left", padx=(6, 0))

        panes = ttk.Panedwindow(tab, orient="horizontal")
        panes.grid(row=1, column=0, sticky="nsew")
        raw_frame = ttk.LabelFrame(panes, text="Source profile JSON", padding=4)
        raw_frame.columnconfigure(0, weight=1)
        raw_frame.rowconfigure(0, weight=1)
        self.raw_editor = tk.Text(raw_frame, wrap="none", undo=True, font=("TkFixedFont", 10))
        raw_y = ttk.Scrollbar(raw_frame, orient="vertical", command=self.raw_editor.yview)
        raw_x = ttk.Scrollbar(raw_frame, orient="horizontal", command=self.raw_editor.xview)
        self.raw_editor.configure(yscrollcommand=raw_y.set, xscrollcommand=raw_x.set)
        self.raw_editor.grid(row=0, column=0, sticky="nsew")
        raw_y.grid(row=0, column=1, sticky="ns")
        raw_x.grid(row=1, column=0, sticky="ew")
        self.raw_editor.bind("<<Modified>>", self._raw_modified)

        tables = ttk.Notebook(panes)
        symbol_frame = ttk.Frame(tables, padding=4)
        achievement_frame = ttk.Frame(tables, padding=4)
        tables.add(symbol_frame, text="Symbols")
        tables.add(achievement_frame, text="Achievements")
        panes.add(raw_frame, weight=3)
        panes.add(tables, weight=2)

        self.symbol_tree = self._table(
            symbol_frame,
            ("identifier", "type", "resolver", "poll"),
            ("Identifier", "Type", "Resolver", "Polling"),
        )
        self.symbol_tree.bind("<Double-1>", lambda _event: self.edit_symbol())
        symbol_buttons = ttk.Frame(symbol_frame)
        symbol_buttons.grid(row=1, column=0, sticky="e", pady=(6, 0))
        ttk.Button(symbol_buttons, text="Add", command=self.add_symbol).pack(side="left")
        ttk.Button(symbol_buttons, text="Edit", command=self.edit_symbol).pack(side="left", padx=6)
        ttk.Button(symbol_buttons, text="Delete", command=self.delete_symbol).pack(side="left")

        self.achievement_tree = self._table(
            achievement_frame,
            ("id", "title", "points", "metal", "category", "secret"),
            ("ID", "Title", "Points", "Metal", "Category", "Secret"),
        )
        # Tree column #0 carries the 16 px metal trophy for each row.
        self.achievement_tree.configure(show=("tree", "headings"))
        self.achievement_tree.heading("#0", text="")
        self.achievement_tree.column("#0", width=34, minwidth=34, stretch=False)
        self.achievement_tree.column("metal", width=80, minwidth=55, stretch=False)
        self.achievement_metal_summary = ttk.Label(achievement_frame, text="")
        self.achievement_metal_summary.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.achievement_tree.bind("<Double-1>", lambda _event: self.edit_achievement())
        achievement_buttons = ttk.Frame(achievement_frame)
        achievement_buttons.grid(row=1, column=0, sticky="e", pady=(6, 0))
        ttk.Button(achievement_buttons, text="Add", command=self.add_achievement).pack(side="left")
        ttk.Button(achievement_buttons, text="Edit", command=self.edit_achievement).pack(side="left", padx=6)
        ttk.Button(achievement_buttons, text="Delete", command=self.delete_achievement).pack(side="left")

    @staticmethod
    def _table(parent: ttk.Frame, columns: tuple[str, ...], labels: tuple[str, ...]) -> ttk.Treeview:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="browse")
        scroll = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        for column, label in zip(columns, labels):
            tree.heading(column, text=label)
            tree.column(column, width=110, minwidth=55, stretch=True)
        return tree

    def _create_debugger_tab(self) -> None:
        tab = self.debugger_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)

        controls = ttk.LabelFrame(tab, text="Achievement under test", padding=8)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)
        self.debug_achievement_var = tk.StringVar()
        self.debug_time_var = tk.StringVar(value="0")
        ttk.Label(controls, text="Achievement").grid(row=0, column=0, sticky="e")
        self.debug_achievement_combo = ttk.Combobox(
            controls, textvariable=self.debug_achievement_var, state="readonly"
        )
        self.debug_achievement_combo.grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(controls, text="Load", command=self.load_condition_debugger).grid(row=0, column=2)
        ttk.Label(controls, text="Monotonic ms").grid(row=0, column=3, padx=(14, 4))
        ttk.Entry(controls, textvariable=self.debug_time_var, width=12).grid(row=0, column=4)
        ttk.Button(controls, text="Evaluate tick", command=self.tick_condition_debugger).grid(
            row=0, column=5, padx=(8, 0)
        )
        ttk.Button(controls, text="Reset state", command=self.reset_condition_debugger).grid(
            row=0, column=6, padx=(6, 0)
        )

        values = ttk.LabelFrame(tab, text="Current symbol values (JSON object)", padding=4)
        values.grid(row=1, column=0, sticky="ew", pady=8)
        values.columnconfigure(0, weight=1)
        self.debug_values_editor = tk.Text(values, height=7, wrap="none", font=("TkFixedFont", 10))
        self.debug_values_editor.grid(row=0, column=0, sticky="ew")
        self.debug_values_editor.insert("1.0", "{}")

        panes = ttk.Panedwindow(tab, orient="horizontal")
        panes.grid(row=2, column=0, sticky="nsew")
        result_frame = ttk.LabelFrame(panes, text="Why it did or did not fire", padding=4)
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)
        self.debug_result_tree = ttk.Treeview(
            result_frame, columns=("state", "path", "detail"), show="headings"
        )
        for column, label, width in (
            ("state", "Result", 70),
            ("path", "Condition path", 230),
            ("detail", "Observed state", 520),
        ):
            self.debug_result_tree.heading(column, text=label)
            self.debug_result_tree.column(column, width=width, stretch=column != "state")
        debug_scroll = ttk.Scrollbar(result_frame, orient="vertical", command=self.debug_result_tree.yview)
        self.debug_result_tree.configure(yscrollcommand=debug_scroll.set)
        self.debug_result_tree.grid(row=0, column=0, sticky="nsew")
        debug_scroll.grid(row=0, column=1, sticky="ns")

        bytecode_frame = ttk.LabelFrame(panes, text="Compiled bytecode", padding=4)
        bytecode_frame.columnconfigure(0, weight=1)
        bytecode_frame.rowconfigure(0, weight=1)
        self.debug_bytecode_text = tk.Text(
            bytecode_frame, width=46, state="disabled", wrap="none", font=("TkFixedFont", 10)
        )
        self.debug_bytecode_text.grid(row=0, column=0, sticky="nsew")
        panes.add(result_frame, weight=3)
        panes.add(bytecode_frame, weight=2)
        self.debug_status_var = tk.StringVar(value="Open a profile, choose an achievement, and load it")
        ttk.Label(tab, textvariable=self.debug_status_var).grid(row=3, column=0, sticky="w", pady=(6, 0))

    def _create_scanner_tab(self) -> None:
        tab = self.scanner_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)

        files = ttk.LabelFrame(tab, text="Snapshots", padding=8)
        files.grid(row=0, column=0, sticky="ew")
        files.columnconfigure(1, weight=1)
        self.initial_snapshot_var = tk.StringVar(value="Not loaded")
        self.next_snapshot_var = tk.StringVar(value="Not loaded")
        ttk.Button(files, text="Load baseline…", command=lambda: self.load_snapshot("initial")).grid(row=0, column=0, padx=(0, 8))
        ttk.Label(files, textvariable=self.initial_snapshot_var).grid(row=0, column=1, sticky="w")
        ttk.Button(files, text="Load next…", command=lambda: self.load_snapshot("next")).grid(row=1, column=0, padx=(0, 8), pady=(6, 0))
        ttk.Label(files, textvariable=self.next_snapshot_var).grid(row=1, column=1, sticky="w", pady=(6, 0))
        ttk.Button(files, text="Save latest as .amunsnap…", command=self.save_snapshot).grid(row=0, column=2, rowspan=2, padx=(8, 0))

        controls = ttk.LabelFrame(tab, text="Scan", padding=8)
        controls.grid(row=1, column=0, sticky="ew", pady=8)
        for column in range(10):
            controls.columnconfigure(column, weight=1 if column in (3, 5, 7) else 0)
        self.scan_base_var = tk.StringVar(value="0x00000000")
        self.scan_type_var = tk.StringVar(value="u32")
        self.scan_mode_var = tk.StringVar(value="unknown")
        self.scan_value_var = tk.StringVar()
        self.scan_second_var = tk.StringVar()
        self.scan_mask_var = tk.StringVar()
        self.scan_stride_var = tk.StringVar(value="1")
        ttk.Label(controls, text="Raw base").grid(row=0, column=0, sticky="e")
        ttk.Entry(controls, textvariable=self.scan_base_var, width=14).grid(row=0, column=1, padx=(4, 10))
        ttk.Label(controls, text="Type").grid(row=0, column=2, sticky="e")
        ttk.Combobox(controls, textvariable=self.scan_type_var, values=tuple(VALUE_TYPES), state="readonly", width=7).grid(row=0, column=3, padx=(4, 10), sticky="w")
        ttk.Label(controls, text="Mode").grid(row=0, column=4, sticky="e")
        ttk.Combobox(
            controls,
            textvariable=self.scan_mode_var,
            values=("unknown", "exact", "changed", "unchanged", "increased", "decreased", "by", "between", "bit-changed"),
            state="readonly",
            width=12,
        ).grid(row=0, column=5, padx=(4, 10), sticky="w")
        ttk.Label(controls, text="Stride").grid(row=0, column=6, sticky="e")
        ttk.Entry(controls, textvariable=self.scan_stride_var, width=7).grid(row=0, column=7, padx=(4, 10), sticky="w")

        ttk.Label(controls, text="Value / delta").grid(row=1, column=0, sticky="e", pady=(7, 0))
        ttk.Entry(controls, textvariable=self.scan_value_var, width=16).grid(row=1, column=1, padx=(4, 10), pady=(7, 0))
        ttk.Label(controls, text="Upper").grid(row=1, column=2, sticky="e", pady=(7, 0))
        ttk.Entry(controls, textvariable=self.scan_second_var, width=16).grid(row=1, column=3, padx=(4, 10), pady=(7, 0), sticky="w")
        ttk.Label(controls, text="Bit mask").grid(row=1, column=4, sticky="e", pady=(7, 0))
        ttk.Entry(controls, textvariable=self.scan_mask_var, width=16).grid(row=1, column=5, padx=(4, 10), pady=(7, 0), sticky="w")
        ttk.Button(controls, text="Start baseline", command=self.start_scan).grid(row=1, column=7, pady=(7, 0), sticky="e")
        ttk.Button(controls, text="Refine with next", command=self.refine_scan).grid(row=1, column=8, columnspan=2, padx=(6, 0), pady=(7, 0), sticky="e")

        results_frame = ttk.LabelFrame(tab, text="Candidates", padding=4)
        results_frame.grid(row=2, column=0, sticky="nsew")
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)
        self.result_tree = ttk.Treeview(results_frame, columns=("address", "previous", "current"), show="headings")
        for column, label, width in (("address", "Address", 150), ("previous", "Previous", 180), ("current", "Current", 180)):
            self.result_tree.heading(column, text=label)
            self.result_tree.column(column, width=width, stretch=True)
        result_scroll = ttk.Scrollbar(results_frame, orient="vertical", command=self.result_tree.yview)
        self.result_tree.configure(yscrollcommand=result_scroll.set)
        self.result_tree.grid(row=0, column=0, sticky="nsew")
        result_scroll.grid(row=0, column=1, sticky="ns")
        self.scan_status_var = tk.StringVar(value="No active scan")
        ttk.Label(results_frame, textvariable=self.scan_status_var).grid(row=1, column=0, sticky="w", pady=(5, 0))

    def _create_live_tab(self) -> None:
        tab = self.live_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        connection = ttk.LabelFrame(tab, text="Luma debugger (read-only developer mode)", padding=8)
        connection.grid(row=0, column=0, sticky="ew")
        connection.columnconfigure(5, weight=1)
        self.live_host_var = tk.StringVar(value="192.168.1.100")
        self.live_port_var = tk.StringVar(value="4000")
        self.live_gdb_var = tk.StringVar(value="arm-none-eabi-gdb --interpreter=mi2 --quiet")
        ttk.Label(connection, text="Console IP").grid(row=0, column=0)
        ttk.Entry(connection, textvariable=self.live_host_var, width=18).grid(row=0, column=1, padx=(4, 10))
        ttk.Label(connection, text="Port").grid(row=0, column=2)
        ttk.Entry(connection, textvariable=self.live_port_var, width=7).grid(row=0, column=3, padx=(4, 10))
        ttk.Button(connection, text="Connect", command=self.connect_live).grid(row=0, column=4)
        ttk.Button(connection, text="Disconnect", command=self.disconnect_live).grid(row=0, column=5, sticky="w", padx=6)
        self.live_backend_var = tk.StringVar(value=self.DIRECT_LUMA_BACKEND)
        ttk.Label(connection, text="Backend").grid(row=1, column=0, pady=(7, 0))
        ttk.Combobox(
            connection,
            textvariable=self.live_backend_var,
            values=(self.DIRECT_LUMA_BACKEND, self.EXTERNAL_GDB_BACKEND),
            state="readonly",
        ).grid(row=1, column=1, columnspan=5, sticky="ew", padx=(4, 0), pady=(7, 0))
        ttk.Label(connection, text="External GDB command").grid(row=2, column=0, pady=(7, 0))
        ttk.Entry(connection, textvariable=self.live_gdb_var).grid(
            row=2, column=1, columnspan=5, sticky="ew", padx=(4, 0), pady=(7, 0)
        )

        process_frame = ttk.LabelFrame(tab, text="Processes", padding=4)
        process_frame.grid(row=1, column=0, sticky="ew", pady=8)
        process_frame.columnconfigure(0, weight=1)
        self.live_process_tree = ttk.Treeview(
            process_frame, columns=("pid", "description"), show="headings", height=4, selectmode="browse"
        )
        self.live_process_tree.heading("pid", text="PID")
        self.live_process_tree.heading("description", text="Description")
        self.live_process_tree.column("pid", width=100, stretch=False)
        self.live_process_tree.column("description", width=500)
        self.live_process_tree.grid(row=0, column=0, sticky="ew")
        process_actions = ttk.Frame(process_frame)
        process_actions.grid(row=0, column=1, padx=(8, 0), sticky="n")
        ttk.Button(process_actions, text="Refresh", command=self.refresh_live_processes).pack(fill="x")
        ttk.Button(process_actions, text="Attach selected", command=self.attach_live).pack(fill="x", pady=5)
        ttk.Button(process_actions, text="Detach / resume", command=self.detach_live).pack(fill="x")

        watch_frame = ttk.LabelFrame(tab, text="Live watch", padding=4)
        watch_frame.grid(row=2, column=0, sticky="nsew")
        watch_frame.columnconfigure(0, weight=1)
        watch_frame.rowconfigure(0, weight=1)
        self.live_watch_tree = ttk.Treeview(
            watch_frame,
            columns=("symbol", "address", "type", "previous", "current"),
            show="headings",
        )
        for column, label, width in (
            ("symbol", "Symbol", 210), ("address", "Address", 120), ("type", "Type", 70),
            ("previous", "Previous", 140), ("current", "Current", 140),
        ):
            self.live_watch_tree.heading(column, text=label)
            self.live_watch_tree.column(column, width=width)
        self.live_watch_tree.grid(row=0, column=0, sticky="nsew")
        live_scroll = ttk.Scrollbar(watch_frame, orient="vertical", command=self.live_watch_tree.yview)
        self.live_watch_tree.configure(yscrollcommand=live_scroll.set)
        live_scroll.grid(row=0, column=1, sticky="ns")
        actions = ttk.Frame(watch_frame)
        actions.grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Button(actions, text="Load absolute symbols from profile", command=self.load_live_symbols).pack(side="left")
        ttk.Button(actions, text="Sample once", command=self.sample_live).pack(side="left", padx=6)
        ttk.Button(actions, text="Capture range as snapshot…", command=self.capture_live_snapshot).pack(side="left")
        self.live_status_var = tk.StringVar(
            value="Disconnected; direct Luma mode needs no GDB or WSL installation"
        )
        ttk.Label(watch_frame, textvariable=self.live_status_var).grid(row=2, column=0, sticky="w", pady=(5, 0))

    def _create_deploy_tab(self) -> None:
        tab = self.deploy_tab
        tab.columnconfigure(1, weight=1)
        self.deploy_source_var = tk.StringVar(value=str((Path.cwd() / "dist" / "sd-root").resolve()))
        self.sd_root_var = tk.StringVar()
        self.backup_var = tk.StringVar(value=str(self.settings.backup_directory))
        ttk.Label(tab, text="Packaged SD-root").grid(row=0, column=0, sticky="e", pady=6)
        ttk.Entry(tab, textvariable=self.deploy_source_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(tab, text="Browse…", command=self.choose_deploy_source).grid(row=0, column=2)
        ttk.Label(tab, text="3DS SD card root").grid(row=1, column=0, sticky="e", pady=6)
        ttk.Entry(tab, textvariable=self.sd_root_var).grid(row=1, column=1, sticky="ew", padx=8)
        target_buttons = ttk.Frame(tab)
        target_buttons.grid(row=1, column=2)
        ttk.Button(target_buttons, text="Detect", command=self.detect_sd).pack(side="left")
        ttk.Button(target_buttons, text="Browse…", command=self.choose_sd_root).pack(side="left", padx=(6, 0))
        ttk.Label(tab, text="Local backup store").grid(row=2, column=0, sticky="e", pady=6)
        ttk.Entry(tab, textvariable=self.backup_var, state="readonly").grid(row=2, column=1, sticky="ew", padx=8)
        ttk.Button(tab, text="Configure…", command=self.configure_backup_directory).grid(row=2, column=2)

        explanation = (
            "Deployment creates or replaces only files present in the packaged SD-root. "
            "Overwritten files are copied to the local backup store first. Rollback refuses "
            "to overwrite files changed after deployment."
        )
        ttk.Label(tab, text=explanation, wraplength=850, justify="left").grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(14, 8)
        )
        actions = ttk.Frame(tab)
        actions.grid(row=4, column=0, columnspan=3, sticky="w")
        ttk.Button(actions, text="Deploy", command=self.deploy_to_sd).pack(side="left")
        ttk.Button(actions, text="Rollback last deployment", command=self.rollback_deployment).pack(side="left", padx=8)
        ttk.Button(actions, text="Choose transaction to rollback…", command=self.choose_transaction_rollback).pack(side="left")
        self.deploy_status_var = tk.StringVar(value="No deployment in this session")
        ttk.Label(tab, textvariable=self.deploy_status_var).grid(row=5, column=0, columnspan=3, sticky="w", pady=(12, 0))

    def connect_live(self) -> None:
        try:
            host = self.live_host_var.get().strip()
            port = int(self.live_port_var.get(), 10)
            backend = self.live_backend_var.get()
            if backend not in (self.DIRECT_LUMA_BACKEND, self.EXTERNAL_GDB_BACKEND):
                raise LiveError("select a supported live-debugging backend")
            command = (
                parse_command(self.live_gdb_var.get())
                if backend == self.EXTERNAL_GDB_BACKEND
                else ()
            )
            if self.live_client is not None:
                raise LiveError("disconnect the existing debugger session first")
        except (CliError, ValueError, LiveError) as error:
            self._error("Cannot connect", error)
            return

        def operation() -> tuple[LiveMemoryClient, list[ProcessInfo]]:
            client: LiveMemoryClient
            if backend == self.DIRECT_LUMA_BACKEND:
                client = LumaRspClient(timeout=10)
            else:
                client = GdbMiClient(command, timeout=10)
            try:
                client.connect(host, port)
                return client, client.list_processes()
            except BaseException:
                client.close()
                raise

        self._run_background("Connecting to Luma debugger", operation, self._live_connected)

    def _live_connected(self, result: object) -> None:
        if (
            not isinstance(result, tuple)
            or len(result) != 2
            or not isinstance(result[0], (GdbMiClient, LumaRspClient))
            or not isinstance(result[1], list)
        ):
            return
        self.live_client = result[0]
        self._populate_live_processes(result[1])

    def _profile_live_hints(self) -> tuple[str, ...]:
        if self.project is None:
            return ()
        game = self.project.document.get("game", {})
        if not isinstance(game, dict):
            return ()
        return tuple(
            str(value) for value in (game.get("name"), game.get("titleId"))
            if isinstance(value, str) and value.strip()
        )

    def _populate_live_processes(self, processes: list[ProcessInfo]) -> None:
        self.live_process_tree.delete(*self.live_process_tree.get_children())
        row_by_pid: dict[int, str] = {}
        for process in processes:
            if isinstance(process, ProcessInfo):
                row = self.live_process_tree.insert(
                    "", "end", iid=f"pid-{process.pid}", values=(process.pid, process.description)
                )
                row_by_pid[process.pid] = row
        suggestion = suggest_process(processes, self._profile_live_hints())
        if suggestion is None:
            self.live_status_var.set("Connected, but Luma returned no process rows")
            return
        row = row_by_pid.get(suggestion.process.pid)
        if row is not None:
            self.live_process_tree.selection_set(row)
            self.live_process_tree.focus(row)
            self.live_process_tree.see(row)
        self.live_status_var.set(
            f"Connected. Suggested PID {suggestion.process.pid} "
            f"({suggestion.process.description}): {suggestion.reason}. Verify, then attach."
        )

    def refresh_live_processes(self) -> None:
        if self.live_client is None:
            self._error("Cannot refresh", "Connect to the Luma debugger first")
            return
        if self.live_client.attached_pid is not None:
            self._error("Cannot refresh", "Detach/resume the current process before refreshing")
            return
        self._run_background(
            "Refreshing Luma process list",
            self.live_client.list_processes,
            lambda result: self._populate_live_processes(result) if isinstance(result, list) else None,
        )

    def disconnect_live(self) -> None:
        client, self.live_client = self.live_client, None
        self.live_watch = None
        if client is not None:
            try:
                client.close()
            except LiveError as error:
                self.log(f"WARNING: debugger close reported: {error}")
        self.live_status_var.set("Disconnected")

    def attach_live(self) -> None:
        if self.live_client is None:
            self._error("Cannot attach", "Connect to the Luma debugger first")
            return
        if self.live_client.attached_pid is not None:
            self._error("Cannot attach", f"Already attached to PID {self.live_client.attached_pid}")
            return
        selection = self.live_process_tree.selection()
        if not selection:
            self._error("Cannot attach", "Select a process first")
            return
        pid = int(self.live_process_tree.item(selection[0], "values")[0])
        self._run_background(
            f"Attaching read-only developer session to PID {pid}",
            lambda: self.live_client.attach(pid) if self.live_client else None,
            lambda _result: self.live_status_var.set(
                f"Attached to PID {pid}; game is paused. Capture/sample, then Detach / resume."
            ),
        )

    def detach_live(self) -> None:
        if self.live_client is None or self.live_client.attached_pid is None:
            self._error("Cannot detach", "No process is currently attached")
            return
        pid = self.live_client.attached_pid

        def detached(_result: object) -> None:
            self.live_watch = None
            self.live_status_var.set(f"Detached from PID {pid}; game resumed")

        self._run_background(
            f"Detaching from PID {pid}",
            lambda: self.live_client.detach() if self.live_client else None,
            detached,
        )

    def load_live_symbols(self) -> None:
        if self.live_client is None or self.live_client.attached_pid is None or self.project is None:
            self._error("Cannot load watch", "Open a profile and connect/attach to the console first")
            return
        symbols: list[WatchSymbol] = []
        for name, definition in self.project.document.get("symbols", {}).items():
            if not isinstance(definition, dict) or definition.get("type") not in VALUE_TYPES:
                continue
            resolver = definition.get("resolver", {})
            if not isinstance(resolver, dict) or resolver.get("kind") != "absolute":
                continue
            try:
                address = int(str(resolver.get("address", "")), 0)
                symbols.append(WatchSymbol(str(name), address, str(definition["type"])))
            except ValueError:
                continue
        try:
            self.live_watch = LiveWatch(self.live_client, symbols)
        except ScanError as error:
            self._error("Cannot load watch", error)
            return
        self.live_watch_tree.delete(*self.live_watch_tree.get_children())
        for symbol in symbols:
            self.live_watch_tree.insert(
                "", "end", iid=symbol.name,
                values=(symbol.name, f"0x{symbol.address:08X}", symbol.value_type, "—", "—"),
            )
        self.live_status_var.set(f"Loaded {len(symbols)} absolute scalar symbols")

    def sample_live(self) -> None:
        if self.live_watch is None:
            self._error("Cannot sample", "Load profile symbols into the live watch first")
            return
        self._run_background("Sampling live watch", self.live_watch.sample, self._live_sampled)

    def _live_sampled(self, result: object) -> None:
        if not isinstance(result, list):
            return
        for value in result:
            if not isinstance(value, WatchValue):
                continue
            previous = "—" if value.previous is None else str(value.previous)
            row = (value.symbol.name, f"0x{value.symbol.address:08X}", value.symbol.value_type,
                   previous, str(value.current))
            if self.live_watch_tree.exists(value.symbol.name):
                self.live_watch_tree.item(value.symbol.name, values=row)
        self.live_status_var.set(f"Sampled {len(result)} symbols")

    def capture_live_snapshot(self) -> None:
        if self.live_client is None or self.live_client.attached_pid is None:
            self._error("Cannot capture", "Connect and attach to the console first")
            return
        address_text = simpledialog.askstring("Capture", "Start address (for example 0x08000000):", parent=self.root)
        if address_text is None:
            return
        size_text = simpledialog.askstring("Capture", "Bytes (maximum 1 MiB per capture):", initialvalue="65536", parent=self.root)
        if size_text is None:
            return
        try:
            address = int(address_text, 0)
            size = int(size_text, 0)
            if not 1 <= size <= 1024 * 1024:
                raise ValueError("capture size must be between 1 and 1,048,576 bytes")
        except ValueError as error:
            self._error("Cannot capture", error)
            return
        destination = filedialog.asksaveasfilename(
            title="Save live snapshot", defaultextension=".amunsnap",
            filetypes=(("AMUN snapshot", "*.amunsnap"),), parent=self.root,
        )
        if not destination:
            return
        self._run_background(
            "Capturing bounded read-only snapshot",
            lambda: self.live_client.capture_snapshot(address, size, "live") if self.live_client else None,
            lambda value: self._save_live_capture(value, Path(destination)),
        )

    def _save_live_capture(self, value: object, destination: Path) -> None:
        if isinstance(value, MemorySnapshot):
            value.save(destination)
            self.latest_snapshot = value
            self.live_status_var.set(f"Saved snapshot: {destination}")

    def _create_log_tab(self) -> None:
        self.log_tab.columnconfigure(0, weight=1)
        self.log_tab.rowconfigure(0, weight=1)
        self.log_text = tk.Text(self.log_tab, state="disabled", wrap="word", font=("TkFixedFont", 10))
        scroll = ttk.Scrollbar(self.log_tab, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

    def _create_library_tab(self) -> None:
        tab = self.library_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        controls = ttk.LabelFrame(tab, text="Filesystem-backed pack library", padding=8)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        controls.columnconfigure(1, weight=1)
        self.library_root_var = tk.StringVar(value=str(self.library.root))
        ttk.Label(controls, text="Library root").grid(row=0, column=0, padx=(0, 8))
        ttk.Entry(controls, textvariable=self.library_root_var, state="readonly").grid(
            row=0, column=1, sticky="ew"
        )
        ttk.Button(controls, text="Choose…", command=self.choose_library_directory).grid(
            row=0, column=2, padx=(8, 0)
        )
        ttk.Button(controls, text="Refresh", command=self.refresh_library).grid(
            row=0, column=3, padx=(6, 0)
        )
        ttk.Button(controls, text="Import .amunpack…", command=self.import_library_pack).grid(
            row=0, column=4, padx=(14, 0)
        )
        ttk.Button(controls, text="Export selected…", command=self.export_library_pack).grid(
            row=0, column=5, padx=(6, 0)
        )
        ttk.Button(controls, text="Open details", command=self.open_library_entry).grid(
            row=0, column=6, padx=(6, 0)
        )

        panes = ttk.Panedwindow(tab, orient="vertical")
        panes.grid(row=1, column=0, sticky="nsew")
        list_frame = ttk.LabelFrame(panes, text="Local packs", padding=4)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        columns = ("game", "title_id", "builds", "achievements", "version", "status", "file")
        self.library_tree = ttk.Treeview(
            list_frame, columns=columns, show="headings", selectmode="browse"
        )
        for column, label, width in (
            ("game", "Game", 190),
            ("title_id", "Title ID", 135),
            ("builds", "Builds", 170),
            ("achievements", "Achievements", 95),
            ("version", "Profile", 80),
            ("status", "Validation", 120),
            ("file", "Library file", 210),
        ):
            self.library_tree.heading(column, text=label)
            self.library_tree.column(column, width=width, minwidth=60, stretch=True)
        library_scroll = ttk.Scrollbar(
            list_frame, orient="vertical", command=self.library_tree.yview
        )
        self.library_tree.configure(yscrollcommand=library_scroll.set)
        self.library_tree.grid(row=0, column=0, sticky="nsew")
        library_scroll.grid(row=0, column=1, sticky="ns")
        self.library_tree.bind("<Double-1>", lambda _event: self.open_library_entry())

        details_frame = ttk.LabelFrame(panes, text="Read-only pack details", padding=4)
        details_frame.columnconfigure(0, weight=1)
        details_frame.rowconfigure(0, weight=1)
        self.library_details = tk.Text(
            details_frame, height=10, state="disabled", wrap="word", font=("TkFixedFont", 10)
        )
        detail_scroll = ttk.Scrollbar(
            details_frame, orient="vertical", command=self.library_details.yview
        )
        self.library_details.configure(yscrollcommand=detail_scroll.set)
        self.library_details.grid(row=0, column=0, sticky="nsew")
        detail_scroll.grid(row=0, column=1, sticky="ns")
        panes.add(list_frame, weight=3)
        panes.add(details_frame, weight=1)

        self.library_status_var = tk.StringVar(
            value="Scan and open are read-only; import/export are explicit copies"
        )
        ttk.Label(tab, textvariable=self.library_status_var).grid(
            row=2, column=0, sticky="w", pady=(6, 0)
        )

    def _selected_library_entry(self) -> LibraryEntry | None:
        selected = self.library_tree.selection()
        return self.library_rows.get(selected[0]) if selected else None

    def _set_library_details(self, entry: LibraryEntry) -> None:
        lines = [
            f"File: {entry.path}",
            f"Relative key: {entry.key}",
            f"Size: {entry.size} bytes",
            f"SHA-256: {entry.sha256 or 'unavailable'}",
        ]
        summary = entry.summary
        if summary:
            lines.extend(
                (
                    "Validation: valid AMUN pack structure",
                    f"Game: {summary.game_name}",
                    f"Title ID: {summary.title_id}",
                    f"Profile version: {summary.profile_version or '(unspecified)'}",
                    f"Format: {summary.format_version}",
                    f"Source hash: {summary.source_hash}",
                    f"Symbols: {summary.symbol_count}",
                    f"Achievements: {summary.achievement_count}",
                    f"Assets: {summary.asset_count}",
                    "Builds:",
                )
            )
            lines.extend(
                f"  {build.identifier}: {build.label} - {build.fingerprint}"
                for build in summary.builds
            )
            if not summary.builds:
                lines.append("  (none)")
        else:
            lines.append(f"Validation: invalid - {entry.error or 'unknown error'}")
        self.library_details.configure(state="normal")
        self.library_details.delete("1.0", "end")
        self.library_details.insert("1.0", "\n".join(lines) + "\n")
        self.library_details.configure(state="disabled")

    def refresh_library(self) -> None:
        self.library_tree.delete(*self.library_tree.get_children())
        self.library_rows.clear()
        try:
            entries = self.library.scan()
        except LibraryError as error:
            self.library_status_var.set(str(error))
            self.status_var.set(str(error))
            return
        for index, entry in enumerate(entries):
            row_id = f"library-{index}"
            self.library_rows[row_id] = entry
            summary = entry.summary
            builds = ", ".join(build.label for build in summary.builds) if summary else ""
            self.library_tree.insert(
                "",
                "end",
                iid=row_id,
                values=(
                    summary.game_name if summary else "",
                    summary.title_id if summary else "",
                    builds,
                    summary.achievement_count if summary else "",
                    summary.profile_version if summary else "",
                    "Valid" if entry.valid else "Invalid",
                    entry.key,
                ),
            )
        valid_count = sum(entry.valid for entry in entries)
        self.library_status_var.set(
            f"{len(entries)} pack(s); {valid_count} structurally valid - no files changed by scan"
        )

    def choose_library_directory(self) -> None:
        directory = filedialog.askdirectory(
            title="Choose local AMUN profile library", initialdir=self.library.root
        )
        if not directory:
            return
        try:
            library = ProfileLibrary(directory)
            self.settings.library_directory = library.root
            self.settings.save()
            self.library = library
            self.library_root_var.set(str(library.root))
            self.refresh_library()
            self.status_var.set(f"Profile library: {library.root}")
        except (LibraryError, OSError) as error:
            self._error("Cannot configure profile library", error)

    def open_library_entry(self) -> None:
        selected = self._selected_library_entry()
        if not selected:
            self._error("No library pack", "Select a library pack first")
            return
        try:
            entry = self.library.open(selected.relative_path)
        except LibraryError as error:
            self._error("Cannot open library pack", error)
            return
        self._set_library_details(entry)
        self.library_status_var.set(
            f"Opened metadata read-only: {entry.key}"
            if entry.valid
            else f"Pack is invalid: {entry.error}"
        )

    def import_library_pack(self) -> None:
        source = filedialog.askopenfilename(
            title="Import AMUN pack into local library",
            filetypes=(("AMUN pack", "*.amunpack"),),
            parent=self.root,
        )
        if not source:
            return
        destination = Path(source).name
        try:
            entry = self.library.import_pack(source, destination)
        except LibraryConflict:
            if not messagebox.askyesno(
                "Replace library pack?",
                f"{destination} already exists in the library. Replace only that file?",
                parent=self.root,
            ):
                return
            try:
                entry = self.library.import_pack(source, destination, replace=True)
            except LibraryError as error:
                self._error("Cannot import pack", error)
                return
        except LibraryError as error:
            self._error("Cannot import pack", error)
            return
        self.refresh_library()
        self.status_var.set(f"Imported copy: {entry.path}")
        self.log(f"Imported pack copy: {source} -> {entry.path}")

    def export_library_pack(self) -> None:
        entry = self._selected_library_entry()
        if not entry:
            self._error("No library pack", "Select a library pack first")
            return
        destination = filedialog.asksaveasfilename(
            title="Export selected AMUN pack",
            initialfile=entry.relative_path.name,
            defaultextension=".amunpack",
            filetypes=(("AMUN pack", "*.amunpack"),),
            parent=self.root,
        )
        if not destination:
            return
        destination_path = Path(destination)
        replace = destination_path.exists()
        if replace and not messagebox.askyesno(
            "Replace exported file?",
            f"Replace only this destination file?\n{destination_path}",
            parent=self.root,
        ):
            return
        try:
            output = self.library.export_pack(
                entry.relative_path, destination_path, replace=replace
            )
        except LibraryError as error:
            self._error("Cannot export pack", error)
            return
        self.status_var.set(f"Exported copy: {output}")
        self.log(f"Exported pack copy: {entry.path} -> {output}")

    def log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _error(self, title: str, error: BaseException | str) -> None:
        self.status_var.set(str(error))
        self.log(f"ERROR: {error}")
        messagebox.showerror(title, str(error), parent=self.root)

    def _raw_modified(self, _event: tk.Event[Any]) -> None:
        if self.raw_editor.edit_modified():
            if self.project:
                self.project.dirty = True
                self._update_title()
            self.raw_editor.edit_modified(False)

    def _update_title(self) -> None:
        if not self.project:
            self.root.title("AMUN Studio")
            self.project_var.set("No project open")
            return
        marker = " *" if self.project.dirty else ""
        self.root.title(f"AMUN Studio — {self.project.profile_path.name}{marker}")
        self.project_var.set(str(self.project.profile_path) + marker)

    def _set_editor(self, text: str) -> None:
        self.raw_editor.delete("1.0", "end")
        self.raw_editor.insert("1.0", text)
        self.raw_editor.edit_modified(False)

    def _confirm_discard(self) -> bool:
        if not self.project or not self.project.dirty:
            return True
        result = messagebox.askyesnocancel(
            "Unsaved profile", "Save changes before continuing?", parent=self.root
        )
        if result is None:
            return False
        if result:
            return self.save_project()
        return True

    def new_project(self) -> None:
        if not self._confirm_discard():
            return
        directory = filedialog.askdirectory(title="Choose new AMUN profile directory")
        if not directory:
            return
        try:
            project = ProfileProject.create(directory)
            if project.profile_path.exists() and not messagebox.askyesno(
                "Replace profile?", f"{project.profile_path} already exists. Replace it?", parent=self.root
            ):
                return
            self.project = project
            self._set_editor(project.raw_text)
            self.refresh_profile_tables()
            self._update_title()
            self.status_var.set("New profile ready; save to create it")
        except ProjectError as error:
            self._error("Cannot create profile", error)

    def choose_profile(self) -> None:
        path = filedialog.askopenfilename(
            title="Open AMUN source profile", filetypes=(("JSON profile", "*.json"), ("All files", "*"))
        )
        if path:
            self.open_project(path)

    def choose_project_directory(self) -> None:
        path = filedialog.askdirectory(title="Open AMUN project directory")
        if path:
            self.open_project(path)

    def open_project(self, path: str | os.PathLike[str]) -> None:
        if not self._confirm_discard():
            return
        try:
            project = ProfileProject.open(path)
            self.project = project
            self._set_editor(project.raw_text)
            self.refresh_profile_tables()
            self._update_title()
            self.status_var.set(f"Opened {project.profile_path}")
            self.log(f"Opened profile: {project.profile_path}")
        except ProjectError as error:
            self._error("Cannot open profile", error)

    def apply_editor(self) -> bool:
        if not self.project:
            self._error("No profile", "Create or open a profile first")
            return False
        try:
            self.project.apply_raw(self.raw_editor.get("1.0", "end-1c"))
            self.refresh_profile_tables()
            self._update_title()
            self.status_var.set("JSON applied")
            return True
        except ProjectError as error:
            self._error("Invalid profile JSON", error)
            return False

    def format_editor(self) -> None:
        if self.apply_editor() and self.project:
            self._set_editor(self.project.reformat())
            self._update_title()

    def save_project(self) -> bool:
        if not self.project:
            self._error("No profile", "Create or open a profile first")
            return False
        try:
            path = self.project.save(self.raw_editor.get("1.0", "end-1c"))
            self._set_editor(self.project.raw_text)
            self.refresh_profile_tables()
            self._update_title()
            self.status_var.set(f"Saved {path}")
            self.log(f"Saved profile: {path}")
            return True
        except ProjectError as error:
            self._error("Cannot save profile", error)
            return False

    def save_project_as(self) -> bool:
        if not self.project:
            self._error("No profile", "Create or open a profile first")
            return False
        path = filedialog.asksaveasfilename(
            title="Save AMUN profile as", defaultextension=".json", filetypes=(("JSON profile", "*.json"),)
        )
        if not path:
            return False
        try:
            self.project.save_as(path, self.raw_editor.get("1.0", "end-1c"))
            self._set_editor(self.project.raw_text)
            self._update_title()
            return True
        except ProjectError as error:
            self._error("Cannot save profile", error)
            return False

    def refresh_profile_tables(self) -> None:
        for tree in (self.symbol_tree, self.achievement_tree):
            tree.delete(*tree.get_children())
        if not self.project:
            self.achievement_metal_summary.configure(text="")
            self.debug_achievement_combo.configure(values=())
            return
        for identifier, definition in self.project.symbols():
            self.symbol_tree.insert(
                "", "end", iid=identifier,
                values=(identifier, definition.get("type", ""), resolver_summary(definition), definition.get("poll", definition.get("polling", ""))),
            )
        for index, definition in enumerate(self.project.achievements()):
            points = definition.get("points", "")
            tier = metal_tier(points)
            row: dict[str, Any] = {}
            if tier in self.metal_icons:
                row["image"] = self.metal_icons[tier]
            self.achievement_tree.insert(
                "", "end", iid=str(index),
                values=(definition.get("id", ""), definition.get("title", ""), points, tier.label, definition.get("category", ""), "yes" if definition.get("secret") else ""),
                **row,
            )
        self.achievement_metal_summary.configure(
            text=achievement_metal_summary(self.project.achievements())
        )
        achievement_ids = tuple(
            str(definition.get("id", f"achievement[{index}]"))
            for index, definition in enumerate(self.project.achievements())
        )
        self.debug_achievement_combo.configure(values=achievement_ids)
        if achievement_ids and self.debug_achievement_var.get() not in achievement_ids:
            self.debug_achievement_var.set(achievement_ids[0])
        self.condition_debugger = None

    def load_condition_debugger(self) -> None:
        if not self._sync_table_edit() or not self.project:
            self._error("Cannot load debugger", "Open a valid profile first")
            return
        achievement_id = self.debug_achievement_var.get()
        achievement = next(
            (item for item in self.project.achievements() if str(item.get("id", "")) == achievement_id),
            None,
        )
        if achievement is None:
            self._error("Cannot load debugger", "Choose an achievement")
            return
        trigger = achievement.get("trigger")
        if trigger is None:
            self._error("Cannot load debugger", f"{achievement_id} has no trigger")
            return
        symbol_names = [identifier for identifier, _definition in self.project.symbols()]
        try:
            self.condition_debugger = ConditionDebugger(
                symbol_names, trigger, path=f"achievements/{achievement_id}/trigger"
            )
        except Exception as error:
            self._error("Cannot compile condition", error)
            return
        self.debug_result_tree.delete(*self.debug_result_tree.get_children())
        self._set_debug_bytecode(())
        self.debug_status_var.set(
            f"Loaded {achievement_id}; state persists across Evaluate tick until Reset state"
        )

    def tick_condition_debugger(self) -> None:
        if self.condition_debugger is None:
            self.load_condition_debugger()
        if self.condition_debugger is None:
            return
        try:
            raw_values = json.loads(self.debug_values_editor.get("1.0", "end-1c"))
            if not isinstance(raw_values, dict):
                raise ValueError("symbol values must be a JSON object")
            values: dict[str, int | float | bytes] = {}
            for name, value in raw_values.items():
                if isinstance(value, bool):
                    values[str(name)] = int(value)
                elif isinstance(value, (int, float)):
                    values[str(name)] = value
                elif isinstance(value, str) and value.startswith("hex:"):
                    values[str(name)] = bytes.fromhex(value[4:])
                else:
                    raise ValueError(
                        f"{name}: expected number, boolean, or a fixed byte value such as hex:00ff"
                    )
            monotonic_ms = int(self.debug_time_var.get(), 0)
            if monotonic_ms < 0:
                raise ValueError("monotonic time cannot be negative")
            report = self.condition_debugger.tick(values, monotonic_ms)
        except (ValueError, json.JSONDecodeError, RuntimeError) as error:
            self._error("Condition evaluation failed", error)
            return
        self._display_debug_report(report)

    def reset_condition_debugger(self) -> None:
        if self.condition_debugger is not None:
            self.condition_debugger.reset()
        self.debug_result_tree.delete(*self.debug_result_tree.get_children())
        self._set_debug_bytecode(())
        self.debug_status_var.set("Condition state reset")

    def _display_debug_report(self, report: DebugReport) -> None:
        self.debug_result_tree.delete(*self.debug_result_tree.get_children())
        for index, line in enumerate(report.lines):
            state = "PASS" if line.passed is True else "FAIL" if line.passed is False else "STATE"
            self.debug_result_tree.insert("", "end", iid=str(index), values=(state, line.path, line.text))
        self._set_debug_bytecode(report.disassembly)
        self.debug_status_var.set(
            f"condition={report.condition} progress={report.progress} instructions={report.instructions}"
        )

    def _set_debug_bytecode(self, lines: tuple[str, ...]) -> None:
        self.debug_bytecode_text.configure(state="normal")
        self.debug_bytecode_text.delete("1.0", "end")
        if lines:
            self.debug_bytecode_text.insert("1.0", "\n".join(lines))
        self.debug_bytecode_text.configure(state="disabled")

    def _sync_table_edit(self) -> bool:
        return self.apply_editor()

    def add_symbol(self) -> None:
        if not self._sync_table_edit() or not self.project:
            return
        dialog = JsonObjectDialog(self.root, "Add symbol", {"type": "u32", "resolver": {"kind": "absolute", "address": "0x00000000"}}, identifier="new.symbol")
        self.root.wait_window(dialog)
        if dialog.result:
            identifier, value = dialog.result
            try:
                self.project.replace_symbol(identifier or "", value)
                self._set_editor(self.project.raw_text)
                self.refresh_profile_tables()
                self._update_title()
            except ProjectError as error:
                self._error("Cannot add symbol", error)

    def edit_symbol(self) -> None:
        if not self._sync_table_edit() or not self.project:
            return
        selected = self.symbol_tree.selection()
        if not selected:
            return
        identifier = selected[0]
        definitions = dict(self.project.symbols())
        dialog = JsonObjectDialog(self.root, "Edit symbol", definitions[identifier], identifier=identifier)
        self.root.wait_window(dialog)
        if dialog.result:
            new_identifier, value = dialog.result
            try:
                self.project.replace_symbol(new_identifier or "", value, identifier)
                self._set_editor(self.project.raw_text)
                self.refresh_profile_tables()
                self._update_title()
            except ProjectError as error:
                self._error("Cannot edit symbol", error)

    def delete_symbol(self) -> None:
        if not self._sync_table_edit() or not self.project:
            return
        selected = self.symbol_tree.selection()
        if selected and messagebox.askyesno("Delete symbol", f"Delete {selected[0]}?", parent=self.root):
            self.project.remove_symbol(selected[0])
            self._set_editor(self.project.raw_text)
            self.refresh_profile_tables()
            self._update_title()

    def add_achievement(self) -> None:
        if not self._sync_table_edit() or not self.project:
            return
        value = {"id": "new_achievement", "title": "New achievement", "description": "", "points": 5, "trigger": {}}
        dialog = JsonObjectDialog(self.root, "Add achievement", value)
        self.root.wait_window(dialog)
        if dialog.result:
            self.project.replace_achievement(dialog.result[1])
            self._set_editor(self.project.raw_text)
            self.refresh_profile_tables()
            self._update_title()

    def edit_achievement(self) -> None:
        if not self._sync_table_edit() or not self.project:
            return
        selected = self.achievement_tree.selection()
        if not selected:
            return
        index = int(selected[0])
        achievements = self.project.achievements()
        dialog = JsonObjectDialog(self.root, "Edit achievement", achievements[index])
        self.root.wait_window(dialog)
        if dialog.result:
            self.project.replace_achievement(dialog.result[1], index)
            self._set_editor(self.project.raw_text)
            self.refresh_profile_tables()
            self._update_title()

    def delete_achievement(self) -> None:
        if not self._sync_table_edit() or not self.project:
            return
        selected = self.achievement_tree.selection()
        if selected and messagebox.askyesno("Delete achievement", "Delete the selected achievement?", parent=self.root):
            self.project.remove_achievement(int(selected[0]))
            self._set_editor(self.project.raw_text)
            self.refresh_profile_tables()
            self._update_title()

    def configure_cli(self) -> None:
        current = format_command(self.settings.cli_command)
        text = simpledialog.askstring(
            "AMUN CLI", "Command used to launch the AMUN CLI:", initialvalue=current, parent=self.root
        )
        if text is None:
            return
        try:
            self.settings.cli_command = parse_command(text)
            self.settings.save()
            self.status_var.set(f"CLI: {format_command(self.settings.cli_command)}")
        except (CliError, OSError) as error:
            self._error("Cannot save CLI setting", error)

    def configure_backup_directory(self) -> None:
        directory = filedialog.askdirectory(
            title="Choose local deployment backup directory", initialdir=self.settings.backup_directory
        )
        if not directory:
            return
        self.settings.backup_directory = Path(directory).expanduser().resolve()
        try:
            self.settings.save()
            self.backup_var.set(str(self.settings.backup_directory))
        except OSError as error:
            self._error("Cannot save backup setting", error)

    def _run_background(
        self,
        description: str,
        operation: Callable[[], object],
        on_success: Callable[[object], None] | None = None,
    ) -> None:
        self.status_var.set(description)
        self.log(description)

        def worker() -> None:
            try:
                result = operation()
                self.jobs.put((description, result, None, on_success))
            except BaseException as error:
                self.jobs.put((description, None, error, on_success))

        threading.Thread(target=worker, name="amun-studio-job", daemon=True).start()

    def _poll_jobs(self) -> None:
        while True:
            try:
                description, result, error, callback = self.jobs.get_nowait()
            except queue.Empty:
                break
            if error:
                self._error(description, error)
            else:
                self.status_var.set(f"{description}: complete")
                if callback:
                    callback(result)
        self.root.after(100, self._poll_jobs)

    def _profile_for_cli(self) -> Path | None:
        if not self.project:
            self._error("No profile", "Create or open a profile first")
            return None
        if self.project.dirty and not self.save_project():
            return None
        return self.project.root

    def validate_profile(self) -> None:
        project = self._profile_for_cli()
        if project:
            self._run_background("Validating profile", lambda: self.settings.hooks().validate(project), self._cli_finished)

    def build_profile(self) -> None:
        project = self._profile_for_cli()
        if project:
            self._run_background("Building achievement pack", lambda: self.settings.hooks().build(project), self._cli_finished)

    def _cli_finished(self, raw_result: object) -> None:
        result = raw_result if isinstance(raw_result, CliResult) else None
        if not result:
            return
        self.log(f"$ {format_command(result.command)}")
        if result.stdout:
            self.log(result.stdout)
        if result.stderr:
            self.log(result.stderr)
        self.log(f"Exit {result.returncode} in {result.elapsed_seconds:.3f}s")
        self.notebook.select(self.log_tab)
        if not result.ok:
            messagebox.showerror("AMUN CLI failed", f"Command exited with status {result.returncode}", parent=self.root)

    @staticmethod
    def _parse_address(text: str) -> int:
        try:
            value = int(text.strip(), 0)
        except ValueError as error:
            raise ScanError(f"Invalid base address: {text!r}") from error
        if not 0 <= value <= 0xFFFFFFFFFFFFFFFF:
            raise ScanError("Base address is outside 64-bit range")
        return value

    def load_snapshot(self, destination: str) -> None:
        path = filedialog.askopenfilename(
            title="Load memory snapshot",
            filetypes=(("AMUN snapshot", "*.amunsnap"), ("Raw memory dump", "*.bin *.dump *.raw"), ("All files", "*")),
        )
        if not path:
            return
        try:
            selected = Path(path)
            if selected.suffix.lower() == ".amunsnap":
                snapshot = MemorySnapshot.load(selected)
                self.scan_base_var.set(f"0x{snapshot.base_address:X}")
            else:
                snapshot = MemorySnapshot.from_raw_file(selected, self._parse_address(self.scan_base_var.get()))
            label = f"{snapshot.name} — {len(snapshot.data):,} bytes @ 0x{snapshot.base_address:X}"
            if destination == "initial":
                self.initial_snapshot = snapshot
                self.initial_snapshot_var.set(label)
                self.scanner.clear()
                self._display_scan_results()
            else:
                self.next_snapshot = snapshot
                self.next_snapshot_var.set(label)
            self.latest_snapshot = snapshot
            self.status_var.set(f"Loaded {path}")
        except ScanError as error:
            self._error("Cannot load snapshot", error)

    def save_snapshot(self) -> None:
        if not self.latest_snapshot:
            self._error("No snapshot", "Load a snapshot first")
            return
        path = filedialog.asksaveasfilename(
            title="Save persistent AMUN snapshot", defaultextension=".amunsnap", filetypes=(("AMUN snapshot", "*.amunsnap"),)
        )
        if path:
            try:
                saved = self.latest_snapshot.save(path)
                self.status_var.set(f"Saved {saved}")
            except (OSError, ScanError) as error:
                self._error("Cannot save snapshot", error)

    def _scan_arguments(self, mode: str) -> dict[str, int | float | None]:
        codec = VALUE_TYPES[self.scan_type_var.get()]
        arguments: dict[str, int | float | None] = {}
        normalized = mode.replace("-", "_")
        if normalized in ("exact", "between"):
            arguments["value"] = codec.parse(self.scan_value_var.get())
        elif normalized == "by":
            text = self.scan_value_var.get().strip()
            try:
                arguments["value"] = int(text, 0) if codec.integral else float(text)
            except ValueError as error:
                raise ScanError(f"Invalid delta: {text!r}") from error
        if normalized == "between":
            arguments["second"] = codec.parse(self.scan_second_var.get())
        if normalized == "bit_changed" and self.scan_mask_var.get().strip():
            try:
                arguments["mask"] = int(self.scan_mask_var.get().strip(), 0)
            except ValueError as error:
                raise ScanError(f"Invalid bit mask: {self.scan_mask_var.get()!r}") from error
        return arguments

    def start_scan(self) -> None:
        if not self.initial_snapshot:
            self._error("No baseline", "Load a baseline snapshot first")
            return
        mode = self.scan_mode_var.get()
        try:
            arguments = self._scan_arguments(mode)
            stride = int(self.scan_stride_var.get().strip(), 0)
            count = self.scanner.start(
                self.initial_snapshot,
                self.scan_type_var.get(),
                mode,
                value=arguments.get("value"),
                second=arguments.get("second"),
                stride=stride,
            )
            self._display_scan_results()
            self.status_var.set(f"Initial scan retained {count:,} candidates")
        except (ScanError, ValueError) as error:
            self._error("Cannot start scan", error)

    def refine_scan(self) -> None:
        if not self.next_snapshot:
            self._error("No next snapshot", "Load the next snapshot first")
            return
        mode = self.scan_mode_var.get()
        try:
            arguments = self._scan_arguments(mode)
            count = self.scanner.refine(
                self.next_snapshot,
                mode,
                value=arguments.get("value"),
                second=arguments.get("second"),
                mask=arguments.get("mask") if isinstance(arguments.get("mask"), int) else None,
            )
            self.initial_snapshot = self.next_snapshot
            self.initial_snapshot_var.set(self.next_snapshot_var.get())
            self.next_snapshot = None
            self.next_snapshot_var.set("Not loaded")
            self._display_scan_results()
            self.status_var.set(f"Refinement retained {count:,} candidates")
        except ScanError as error:
            self._error("Cannot refine scan", error)

    def _display_scan_results(self) -> None:
        self.result_tree.delete(*self.result_tree.get_children())
        total = len(self.scanner.candidates)
        for index, result in enumerate(self.scanner.results(self.RESULT_DISPLAY_LIMIT)):
            self.result_tree.insert(
                "", "end", iid=str(index),
                values=(f"0x{result.address:08X}", format_scan_value(result.previous), format_scan_value(result.current)),
            )
        suffix = f"; showing first {self.RESULT_DISPLAY_LIMIT:,}" if total > self.RESULT_DISPLAY_LIMIT else ""
        self.scan_status_var.set(f"{total:,} candidates{suffix}")

    def choose_deploy_source(self) -> None:
        path = filedialog.askdirectory(title="Choose packaged SD-root", initialdir=self.deploy_source_var.get())
        if path:
            self.deploy_source_var.set(path)

    def choose_sd_root(self) -> None:
        path = filedialog.askdirectory(title="Choose 3DS SD card root")
        if path:
            self.sd_root_var.set(path)

    def detect_sd(self) -> None:
        try:
            candidates = detect_sd_cards()
            if not candidates:
                messagebox.showinfo("SD detection", "No likely SD card was detected. Choose its root manually.", parent=self.root)
                return
            self.sd_root_var.set(str(candidates[0].root))
            self.log("SD candidates:")
            for candidate in candidates:
                self.log(f"  {candidate.root} score={candidate.score}: {', '.join(candidate.reasons)}")
            self.status_var.set(f"Selected detected SD root {candidates[0].root}")
        except OSError as error:
            self._error("SD detection failed", error)

    def deploy_to_sd(self) -> None:
        source = Path(self.deploy_source_var.get()).expanduser()
        target = Path(self.sd_root_var.get()).expanduser()
        if not source.is_dir() or not target.is_dir():
            self._error("Cannot deploy", "Select existing source and SD-root directories")
            return
        file_count = sum(1 for path in source.rglob("*") if path.is_file())
        if not messagebox.askyesno(
            "Deploy to SD",
            f"Deploy {file_count} packaged files to:\n{target}\n\nExisting target files will be backed up first.",
            parent=self.root,
        ):
            return
        deployer = SdDeployer(self.settings.backup_directory)
        self._run_background(
            "Deploying to SD",
            lambda: deployer.deploy(source, target),
            self._deployment_finished,
        )

    def _deployment_finished(self, raw_transaction: object) -> None:
        if not isinstance(raw_transaction, DeploymentTransaction):
            return
        self.last_transaction = raw_transaction
        changed = sum(entry.action != "unchanged" for entry in raw_transaction.entries)
        self.deploy_status_var.set(
            f"Deployment {raw_transaction.identifier}: {changed} changed, "
            f"{len(raw_transaction.entries) - changed} unchanged"
        )
        self.log(f"Deployment complete: {raw_transaction.manifest_path}")

    def rollback_deployment(self) -> None:
        transaction = self.last_transaction
        if transaction is None:
            recent = SdDeployer(self.settings.backup_directory).recent_transactions(1)
            transaction = recent[0] if recent else None
        if transaction is None:
            self._error("No deployment", "No deployment transaction was found")
            return
        self._rollback(transaction)

    def choose_transaction_rollback(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose deployment transaction",
            initialdir=self.settings.backup_directory,
            filetypes=(("AMUN transaction", "transaction.json"), ("JSON", "*.json")),
        )
        if not path:
            return
        try:
            self._rollback(DeploymentTransaction.load(path))
        except DeploymentError as error:
            self._error("Cannot load transaction", error)

    def _rollback(self, transaction: DeploymentTransaction) -> None:
        if not messagebox.askyesno(
            "Rollback deployment",
            f"Restore deployment {transaction.identifier} on:\n{transaction.sd_root}?\n\n"
            "Rollback will stop if any deployed file has since changed.",
            parent=self.root,
        ):
            return
        deployer = SdDeployer(transaction.backup_root)
        self._run_background(
            "Rolling back SD deployment",
            lambda: deployer.rollback(transaction),
            self._rollback_finished,
        )

    def _rollback_finished(self, raw_transaction: object) -> None:
        if isinstance(raw_transaction, DeploymentTransaction):
            self.last_transaction = raw_transaction
            self.deploy_status_var.set(f"Rolled back {raw_transaction.identifier}")
            self.log(f"Rollback complete: {raw_transaction.manifest_path}")

    def _close(self) -> None:
        if self._confirm_discard():
            self.disconnect_live()
            self.root.destroy()


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AMUN Studio profile editor and memory scanner")
    parser.add_argument("project", nargs="?", help="Profile JSON file or project directory to open")
    parser.add_argument("--cli", help="AMUN CLI launch command for this session")
    parser.add_argument("--backup-dir", help="Local deployment backup directory for this session")
    parser.add_argument("--library-dir", help="Local .amunpack library for this session")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_argument_parser().parse_args(argv)
    try:
        settings = StudioSettings.load()
    except CliError as error:
        # A corrupt preference file must not make the authoring tool unusable.
        settings = StudioSettings()
        settings_error = str(error)
    else:
        settings_error = ""
    if arguments.cli:
        settings.cli_command = parse_command(arguments.cli)
    if arguments.backup_dir:
        settings.backup_directory = Path(arguments.backup_dir).expanduser().resolve()
    if arguments.library_dir:
        settings.library_directory = Path(arguments.library_dir).expanduser().resolve()

    root = tk.Tk()
    application = StudioApplication(root, settings, arguments.project)
    if settings_error:
        application.log(f"WARNING: {settings_error}; defaults are active")
    root.mainloop()
    return 0
