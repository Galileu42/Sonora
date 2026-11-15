"""Interface desktop do Sonora."""

from pathlib import Path
from queue import Empty, Queue
from threading import Thread
import faulthandler
import os
import re
import subprocess
import traceback
import time
import sys
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk

import engine as media
import updater


BG = "#10141d"
PANEL = "#192130"
FIELD = "#263247"
BORDER = "#35445b"
INK = "#f1f5ff"
MUTED = "#b5c4dc"
ACCENT = "#b7d9ff"
BLUE = "#3269e8"
ASSETS = media.ROOT / "assets"
APP_ID = "Sonora.Windows.Desktop"
SAFE_START = "--safe-start" in sys.argv
STARTUP_EVENT = next((arg.partition("=")[2] for arg in sys.argv[1:]
                      if arg.startswith("--startup-event=")), None)
FONT = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
FONT_STYLES = ((9, "normal"), (9, "bold"), (10, "normal"), (10, "bold"),
               (11, "normal"), (11, "bold"), (14, "bold"), (15, "bold"), (20, "bold"))


def font_name(size, weight="normal"):
    return f"SonoraFont{size}{weight}"


DEFAULT_FOLDER = str(Path.home() / "Downloads" / "Sonora")
DEFAULT_QUALITY = "Máxima"
DEFAULT_AUDIO_FORMAT = "Original"


def open_path(path):
    if os.name == "nt":
        os.startfile(str(path))
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


def rounded_outline(width, height, radius):
    x, y = max(0, width - 1), max(0, height - 1)
    r = min(radius, x // 2, y // 2)
    d = r * 0.5523
    return (r, 0, r, 0, x-r, 0, x-r, 0, x-r+d, 0, x, r-d, x, r,
            x, r, x, y-r, x, y-r, x, y-r+d, x-r+d, y, x-r, y,
            x-r, y, r, y, r, y, r-d, y, 0, y-r+d, 0, y-r,
            0, y-r, 0, r, 0, r, 0, r-d, r-d, 0, r, 0)


class RoundedButton(ttk.Frame):
    """A native focusable button surrounded by a vector border."""

    def __init__(self, parent, *, text, command, style="TButton"):
        super().__init__(parent, style="Card.TFrame")
        self.style_engine = ttk.Style(self)
        self.canvas = tk.Canvas(self, bg=PANEL, highlightthickness=0, bd=0, takefocus=False)
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.shape = self.canvas.create_polygon(0, 0, 0, 0, 0, 0, smooth="raw")
        self.inner = ttk.Button(self, text=text, command=command, style=style)
        self.inner.pack(fill="both", expand=True, padx=6, pady=2)
        self.variant = style
        self.canvas.bind("<Configure>", self.redraw)
        for event in ("<Enter>", "<Leave>", "<FocusIn>", "<FocusOut>", "<ButtonPress-1>", "<ButtonRelease-1>"):
            self.inner.bind(event, self.defer_redraw, add="+")
        self.canvas.tk.call("lower", self.canvas)

    def defer_redraw(self, _event):
        self.after_idle(self.redraw)

    def redraw(self, _event=None):
        states = self.inner.state()
        fill = self.style_engine.lookup(self.variant, "background", states)
        outline = ACCENT if self.inner.instate(("focus", "!disabled")) else fill
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        self.canvas.coords(self.shape, *rounded_outline(width, height, 10))
        self.canvas.itemconfigure(self.shape, fill=fill, outline=outline)

    def configure(self, cnf=None, **kwargs):
        options = {**(cnf or {}), **kwargs} if cnf is None or isinstance(cnf, dict) else kwargs
        inner = {key: options.pop(key) for key in ("text", "command", "style") if key in options}
        if inner:
            self.inner.configure(**inner)
            self.variant = inner.get("style", self.variant)
            self.redraw()
        if options or not inner:
            return super().configure(cnf if isinstance(cnf, str) else None, **options)

    config = configure

    def cget(self, key):
        return self.inner.cget(key) if key in {"text", "command", "style"} else super().cget(key)

    def state(self, statespec=None):
        result = self.inner.state(statespec)
        if statespec is not None:
            self.redraw()
        return result

    def instate(self, statespec, callback=None, *args):
        return self.inner.instate(statespec, callback, *args)

    def invoke(self):
        return self.inner.invoke()


Button = ttk.Button if SAFE_START else RoundedButton


class Sonora:
    def __init__(self, root):
        self.root = root
        log_startup("Preparando a janela")
        self.root.title("Sonora")
        self.scale = max(1, self.root.winfo_fpixels("1i") / 96)
        scale = self.scale
        width = min(round(890 * scale), self.root.winfo_screenwidth() - 35)
        height = min(round(655 * scale), self.root.winfo_screenheight() - 110)
        self.root.minsize(width, height)
        self.root.geometry(f"{max(width, min(round(1130 * scale), self.root.winfo_screenwidth() - 35))}x"
                           f"{max(height, min(round(730 * scale), self.root.winfo_screenheight() - 110))}")
        self.window_icon = tk.PhotoImage(file=ASSETS / "sonora.png")
        self.root.iconphoto(True, self.window_icon)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.events = Queue()
        log_startup("Lendo a fila e as configurações")
        state = media.load_state()
        settings = state["settings"]
        self.jobs = state["jobs"]
        self.queue_filter = "Todos"
        self.queue_rows = {}
        self.jobs_by_id = {}
        self.pending_count = 0
        self.done_count = 0
        self.folder = tk.StringVar(value=settings.get("folder", DEFAULT_FOLDER))
        self.recent_folders = settings.get("recent_folders", [])
        self.destination_dialog = None
        self.ask_destination = tk.BooleanVar(value=settings.get("ask_destination", False))
        mode = settings.get("mode")
        mode = mode if mode in {"Áudio", "Vídeo"} else "Áudio"
        fmt = settings.get("format", DEFAULT_AUDIO_FORMAT if mode == "Áudio" else media.VIDEO[0])
        quality = settings.get("quality", DEFAULT_QUALITY)
        if not settings.get("original_audio_default_migrated") and (mode, fmt, quality) == ("Áudio", "MP3", "192"):
            fmt, quality = DEFAULT_AUDIO_FORMAT, DEFAULT_QUALITY
        self.mode = tk.StringVar(value=mode)
        self.format = tk.StringVar(value=fmt)
        self.quality = tk.StringVar(value=quality)
        self.playlist = tk.BooleanVar(value=settings.get("playlist", False))
        self.status = tk.StringVar(value=state.get("warning", "") or "Pronto para adicionar links.")
        self.summary = tk.StringVar(value="")
        self.percent = tk.DoubleVar(value=0)
        self.active = None
        self.worker = None
        self.lookup = None
        self.lookup_thread = None
        self.running = False
        self.closing = False
        self.cancelling = False
        self.update_repo = settings.get("update_repo") or updater.DEFAULT_REPO
        self.update_thread = None
        self.update_pending = None
        self.restart_after_update = False
        self.update_after_job = False
        self.update_status = tk.StringVar(value=f"Versão {updater.VERSION}")
        self.update_dialog_window = None
        log_startup("Configurando o tema")
        self.style()
        log_startup("Criando os controles")
        self.build()
        self.update_options()
        log_startup("Montando a fila")
        self.refresh()
        self.root.after(70, self.poll)
        self.root.after(5000 if SAFE_START else 1500, self.check_updates)
        self.root.after(200, self.report_update_error)
        self.root.after_idle(self.finish_startup)

    def finish_startup(self):
        # Paint the completed layout before notifying the Windows launcher.
        self.root.after(0, signal_startup_ready)

    def style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        family = FONT
        self.fonts = [tkfont.Font(self.root, name=font_name(size, weight), family=family, size=size, weight=weight)
                      for size, weight in FONT_STYLES]
        for name in ("TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkMenuFont"):
            native_font = tkfont.nametofont(name, self.root)
            native_font.configure(family=family, size=11)
            self.fonts.append(native_font)
        self.configure_style(style)

    def configure_style(self, style):
        self.root.option_add("*TCombobox*Listbox.font", "TkTextFont")
        style.configure(".", background=BG, foreground=INK, font=font_name(11))
        style.configure("TButton", padding=(7, 6), width=0, background=FIELD, borderwidth=0,
                        focuscolor=ACCENT, focusthickness=0, relief="flat")
        style.map("TButton", foreground=[("disabled", "#9aa6b9")])
        style.configure("Primary.TButton", background=BLUE, foreground="#ffffff", font=font_name(11, "bold"))
        style.configure("Selected.TButton", background="#2d4b7c", foreground="#edf3ff",
                        font=font_name(11, "bold"))
        style.configure("Queue.TButton", padding=(6, 3), background=PANEL, foreground=MUTED)
        style.configure("QueueSelected.TButton", padding=(6, 3), background="#29436c", foreground=ACCENT)
        style.configure("TCheckbutton", background=PANEL, indicatorbackground=FIELD, padding=(0, 3))
        style.map("TCheckbutton", indicatorcolor=[("selected", ACCENT)], background=[("active", PANEL)])
        style.configure("TEntry", fieldbackground=FIELD, foreground=INK, insertcolor=INK, padding=7,
                        bordercolor=BORDER, lightcolor=FIELD, darkcolor=FIELD)
        style.configure("TCombobox", fieldbackground=FIELD, background=FIELD, arrowcolor=INK, padding=6,
                        bordercolor=BORDER, lightcolor=FIELD, darkcolor=FIELD)
        style.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", INK)],
                  bordercolor=[("focus", ACCENT)])
        style.configure("Inset.TEntry", bordercolor=FIELD, padding=3)
        style.configure("Inset.TCombobox", bordercolor=FIELD, padding=3)
        self.root.option_add("*TCombobox*Listbox.background", FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", INK)
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#304672")
        self.root.option_add("*TCombobox*Listbox.selectForeground", INK)
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.configure("Treeview", background=BG, fieldbackground=BG, foreground=INK,
                        borderwidth=0, rowheight=max(36, round(self.root.winfo_fpixels("0.37i"))))
        style.configure("Treeview.Heading", background=FIELD, foreground=MUTED, relief="flat",
                        padding=(10, 8), font=font_name(10, "bold"))
        style.map("Treeview", background=[("selected", "#304672")], foreground=[("selected", INK)])
        style.configure("Card.TFrame", background=PANEL)
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=FIELD)
        for variant, hover in (("TButton", "#384456"), ("Primary.TButton", "#326bec"),
                               ("Selected.TButton", "#35578e"), ("Queue.TButton", FIELD),
                               ("QueueSelected.TButton", "#334b6c")):
            style.map(variant, background=[("disabled", PANEL), ("active", hover)])
        style.layout("Sonora.Vertical.TScrollbar", [
            ("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
                ("Vertical.Scrollbar.thumb", {"expand": 1, "sticky": "nswe"}),
            ]}),
        ])
        style.configure("Sonora.Vertical.TScrollbar", background="#526783", troughcolor=BG,
                        bordercolor=BG, lightcolor="#526783", darkcolor="#526783", width=10)
        style.configure("Horizontal.TProgressbar", bordercolor=PANEL, lightcolor=ACCENT, darkcolor=ACCENT)

    def build(self):
        toolbar = tk.Frame(self.root, bg=PANEL, padx=22, pady=11)
        toolbar.pack(fill="x")
        self.brand = tk.PhotoImage(file=ASSETS / "marca.png")
        tk.Label(toolbar, image=self.brand, bg=PANEL).pack(side="left", padx=(0, 11))
        tk.Label(toolbar, text="Sonora", bg=PANEL, fg=INK, font=font_name(20, "bold")).pack(side="left")
        self.update_button = Button(toolbar, text="Atualizações", command=self.update_dialog)
        self.update_button.pack(side="right")
        Button(toolbar, text="Abrir pasta", command=self.open_folder).pack(side="right", padx=8)
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")

        status = tk.Frame(self.root, bg=PANEL, padx=17, pady=8)
        status.pack(side="bottom", fill="x")
        tk.Label(status, text=f"Sonora {updater.VERSION}", bg=PANEL, fg=MUTED, font=font_name(9)).pack(side="right")
        self.progress_label = tk.StringVar(value="0%")
        tk.Label(status, textvariable=self.progress_label, bg=PANEL, fg=ACCENT,
                 font=font_name(9, "bold"), width=5).pack(side="right", padx=(6, 12))
        ttk.Progressbar(status, variable=self.percent, maximum=100, length=130).pack(side="right")
        tk.Label(status, textvariable=self.status, bg=PANEL, fg=MUTED, anchor="w", font=font_name(9)).pack(
            side="left", fill="x", expand=True
        )
        self.percent.trace_add("write", lambda *_: self.progress_label.set(f"{self.percent.get():.0f}%"))

        workspace = tk.Frame(self.root, bg=BG, padx=16, pady=15)
        workspace.pack(fill="both", expand=True)
        sidebar = self.card(workspace)
        sidebar.pack(side="right", fill="y", padx=(12, 0))
        sidebar.configure(width=max(262, round(250 * self.scale)))
        sidebar.pack_propagate(False)
        self.label(sidebar, "Saída", heading=True).pack(anchor="w", pady=(0, 15))
        self.label(sidebar, "Tipo de mídia").pack(anchor="w")
        modes = tk.Frame(sidebar, bg=PANEL)
        modes.pack(fill="x", pady=(5, 13))
        self.mode_buttons = {}
        for name in ("Áudio", "Vídeo"):
            button = Button(modes, text=name, command=lambda value=name: self.select_mode(value))
            button.pack(side="left", fill="x", expand=True, padx=(0, 4) if name == "Áudio" else (4, 0))
            self.mode_buttons[name] = button

        self.label(sidebar, "Formato").pack(anchor="w")
        format_panel = self.rounded_panel(sidebar, FIELD, PANEL, (8, 4), 10)
        format_panel.pack(fill="x", pady=(5, 12))
        self.format_box = ttk.Combobox(format_panel, textvariable=self.format, state="readonly", width=15,
                                       style="Inset.TCombobox")
        self.format_box.pack(fill="x")
        self.format_box.bind("<<ComboboxSelected>>", self.update_options)
        self.label(sidebar, "Qualidade").pack(anchor="w")
        quality_panel = self.rounded_panel(sidebar, FIELD, PANEL, (8, 4), 10)
        quality_panel.pack(fill="x", pady=(5, 5))
        self.quality_box = ttk.Combobox(quality_panel, state="readonly", width=15, style="Inset.TCombobox")
        self.quality_box.pack(fill="x")
        self.quality_box.bind("<<ComboboxSelected>>", self.set_quality)
        note_panel = self.rounded_panel(sidebar, BG, PANEL, (9, 5), 7)
        note_panel.pack(fill="x", pady=(3, 0))
        tk.Label(note_panel, textvariable=self.summary, bg=BG, fg=ACCENT, font=font_name(10),
                 wraplength=max(175, round(195 * self.scale)), justify="left", anchor="w", height=2).pack(fill="x")
        tk.Frame(sidebar, bg=BORDER, height=1).pack(fill="x", pady=(13, 12))
        self.label(sidebar, "Pasta de destino").pack(anchor="w")
        folder_panel = self.rounded_panel(sidebar, FIELD, PANEL, (8, 4), 10)
        folder_panel.pack(fill="x", pady=(5, 7))
        ttk.Entry(folder_panel, textvariable=self.folder, width=16, style="Inset.TEntry").pack(fill="x")
        Button(sidebar, text="Escolher pasta…", command=self.choose_folder).pack(anchor="w")
        ttk.Checkbutton(sidebar, text="Perguntar a cada lote", variable=self.ask_destination,
                        command=self.persist).pack(anchor="w", pady=(9, 0))

        work = tk.Frame(workspace, bg=BG)
        work.pack(side="left", fill="both", expand=True)
        links = self.card(work)
        links.pack(fill="x", pady=(0, 12))
        header = tk.Frame(links, bg=PANEL)
        header.pack(fill="x", pady=(0, 7))
        self.label(header, "Adicionar mídia", heading=True).pack(anchor="w")
        self.label(header, "Cole um link do YouTube, Short ou playlist por linha.").pack(anchor="w", pady=(3, 0))
        input_frame = self.rounded_panel(links, BG, PANEL, (12, 8), 11)
        input_frame.pack(fill="x")
        self.links = tk.Text(input_frame, height=2, width=1, wrap="word", font="TkTextFont", bg=BG, fg=INK,
                             insertbackground=INK, highlightthickness=0, relief="flat",
                             padx=4, pady=3, undo=True)
        self.links.pack(fill="x")
        actions = tk.Frame(links, bg=PANEL)
        actions.pack(fill="x", pady=(7, 0))
        Button(actions, text="Adicionar à fila", style="Primary.TButton", command=self.enqueue).pack(side="right")
        Button(actions, text="Colar", command=self.paste).pack(side="left")
        self.inspect_button = Button(actions, text="Ver formatos", command=self.inspect)
        self.inspect_button.pack(side="left", padx=(6, 8))
        ttk.Checkbutton(actions, text="Playlist inteira", variable=self.playlist).pack(side="left")

        queue = self.card(work)
        queue.pack(fill="both", expand=True)
        header = tk.Frame(queue, bg=PANEL)
        header.pack(fill="x", pady=(0, 9))
        self.label(header, "Fila de downloads", heading=True).pack(side="left")
        self.counts = tk.StringVar()
        self.label(header, "", self.counts).pack(side="left", padx=(13, 0))
        self.start_button = Button(header, text="Iniciar fila", style="Primary.TButton", command=self.toggle)
        self.start_button.pack(side="right")

        filters = tk.Frame(queue, bg=PANEL)
        filters.pack(fill="x", pady=(0, 7))
        self.filter_buttons = {}
        for name in ("Todos", "Pendentes", "Concluídos", "Falhas"):
            button = Button(filters, text=name, style="Queue.TButton",
                                command=lambda value=name: self.select_queue(value))
            button.pack(side="left", padx=(0, 5))
            self.filter_buttons[name] = button

        footer = tk.Frame(queue, bg=PANEL)
        footer.pack(side="bottom", fill="x", pady=(9, 0))
        self.action_buttons = {}
        for key, caption, action in (
            ("Detalhes / abrir", "Abrir / detalhes", self.details),
            ("Tentar novamente", "Repetir", self.retry),
            ("Remover", "Remover", self.remove),
            ("Cancelar atual", "Cancelar atual", self.cancel),
        ):
            button = Button(footer, text=caption, command=action)
            button.pack(side="left", padx=(0, 5))
            self.action_buttons[key] = button
        self.clear_button = Button(footer, text="Limpar concluídos", command=self.clear_done)
        self.clear_button.pack(side="right")
        table = self.rounded_panel(queue, BG, PANEL, (7, 6), 7)
        table.pack(fill="both", expand=True)
        columns = (("title", "Título", 235), ("format", "Formato", 75),
                   ("quality", "Qualidade", 85), ("status", "Estado", 105))
        self.tree = self.make_table(table, columns, stretch="title")
        self.tree.bind("<Double-1>", lambda _: self.details())
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.update_controls())
        self.empty = tk.Frame(table, bg=BG)
        self.empty_title = tk.StringVar()
        tk.Label(self.empty, textvariable=self.empty_title, bg=BG, fg=INK, font=font_name(15, "bold")).pack()
        self.empty_hint = tk.StringVar()
        tk.Label(self.empty, textvariable=self.empty_hint, bg=BG, fg=MUTED,
                 font=font_name(10)).pack(pady=(5, 0))
        self.tree.tag_configure("even", background="#151e2d")
        self.tree.tag_configure(media.ACTIVE, foreground=ACCENT)
        self.tree.tag_configure(media.DONE, foreground="#a9e7cc")
        self.tree.tag_configure(media.FAILED, foreground="#ffc5c2")
        self.tree.tag_configure(media.STOPPED, foreground=MUTED)
        self.root.bind("<Control-Return>", lambda _: self.enqueue())
        self.root.bind("<Control-l>", lambda _: self.links.focus_set())
        self.root.bind("<Control-L>", lambda _: self.links.focus_set())

    def select_mode(self, mode):
        self.mode.set(mode)
        self.update_options()

    def card(self, parent):
        return self.rounded_panel(parent, PANEL, BG, (17, 13), 16)

    def rounded_panel(self, parent, fill, background, padding, radius):
        panel = ttk.Frame(parent, style="Card.TFrame", padding=padding)
        canvas = tk.Canvas(panel, bg=background, highlightthickness=0, borderwidth=0, takefocus=False)
        # The decoration must span the outer frame, including its padding.
        canvas.place(x=0, y=0, relwidth=1, relheight=1, bordermode="ignore")
        corners = canvas.create_polygon(0, 0, 0, 0, 0, 0, fill=fill, outline=BORDER, smooth="raw")

        def layout(event):
            canvas.coords(corners, *rounded_outline(event.width, event.height, round(radius * self.scale)))

        canvas.bind("<Configure>", layout)
        # Tk's Canvas.lower acts on drawing items. Lower the canvas widget itself.
        canvas.tk.call("lower", canvas)
        return panel

    @staticmethod
    def label(parent, text, variable=None, heading=False):
        return tk.Label(parent, text=text, textvariable=variable, bg=PANEL,
                        fg=INK if heading else MUTED, font=font_name(14, "bold") if heading else font_name(10))

    def make_table(self, parent, columns, stretch):
        tree = ttk.Treeview(parent, columns=[column[0] for column in columns], show="headings")
        heading_font = tkfont.nametofont(font_name(10, "bold"), self.root)
        for key, label, width in columns:
            tree.heading(key, text=label, anchor="w")
            min_width = heading_font.measure(label) + 24
            tree.column(key, minwidth=min_width, width=max(min_width, round(width * self.scale)),
                        stretch=key == stretch)
        bar = ttk.Scrollbar(parent, command=tree.yview, orient="vertical", style="Sonora.Vertical.TScrollbar")
        tree.pack(fill="both", expand=True)

        def update_scrollbar(first, last):
            bar.set(first, last)
            if float(first) == 0 and float(last) == 1:
                if bar.winfo_manager():
                    bar.pack_forget()
            elif not bar.winfo_manager():
                bar.pack(side="right", fill="y", padx=(3, 0), before=tree)

        tree.configure(yscrollcommand=update_scrollbar)
        return tree

    def paste(self):
        try:
            data = self.root.clipboard_get()
        except tk.TclError:
            return
        if self.links.get("1.0", "end-1c").strip():
            self.links.insert("end", "\n")
        self.links.insert("end", data.strip())

    def update_options(self, _event=None):
        for name, button in self.mode_buttons.items():
            button.configure(style="Selected.TButton" if self.mode.get() == name else "TButton")
        formats = media.AUDIO if self.mode.get() == "Áudio" else media.VIDEO
        self.format_box.configure(values=formats)
        if self.format.get() not in formats:
            self.format.set(DEFAULT_AUDIO_FORMAT if self.mode.get() == "Áudio" else formats[0])
        self.quality_values = {"Máxima disponível": "Máxima"}
        fmt = self.format.get()
        if self.mode.get() == "Vídeo":
            self.quality_values.update({f"Até {height}p": f"{height}p" for height in media.HEIGHTS})
        elif fmt not in {"FLAC", "WAV", "Original"}:
            self.quality_values.update({f"{rate} kbps": str(rate) for rate in media.RATES})
        self.quality_box.configure(values=list(self.quality_values))
        label = next((key for key, value in self.quality_values.items() if value == self.quality.get()),
                     "Máxima disponível")
        self.quality_box.set(label)
        self.set_quality()

    def set_quality(self, _event=None):
        self.quality.set(self.quality_values[self.quality_box.get()])
        fmt = self.format.get()
        if self.mode.get() == "Vídeo":
            hint = "Cada link oferece resoluções diferentes."
        elif self.quality.get().isdigit():
            size = int(self.quality.get()) * 180 / 8000
            hint = f"Áudio de 3 min · cerca de {size:.1f} MB".replace(".", ",")
            if fmt == "OGG" and int(self.quality.get()) <= 48:
                hint += " · mono"
        elif fmt == "Original":
            hint = "Melhor faixa de áudio disponível, sem recodificação."
        elif fmt in {"FLAC", "WAV"}:
            hint = "Conversão sem perdas adicionais de compressão."
        else:
            hint = "Maior qualidade de codificação oferecida pelo app."
        self.summary.set(hint)

    def choose_folder(self, parent=None, *, remember=True):
        if self.destination_dialog is not None:
            self.destination_dialog.lift()
            return None
        owner = parent or self.root
        dialog = tk.Toplevel(owner, bg=BG)
        self.destination_dialog = dialog
        dialog.title("Pasta de download")
        dialog.transient(owner)
        panel = self.card(dialog)
        panel.pack(fill="both", expand=True, padx=10, pady=10)
        self.label(panel, "Onde salvar?", heading=True).pack(anchor="w")
        subtitle = "Escolha a pasta padrão do Sonora." if remember else "Escolha o destino deste lote."
        self.label(panel, subtitle).pack(anchor="w", pady=(4, 14))

        path = tk.StringVar(dialog, self.folder.get())
        custom = self.rounded_panel(panel, FIELD, PANEL, (8, 4), 10)
        custom.pack(fill="x")
        field = ttk.Entry(custom, textvariable=path, width=54, style="Inset.TEntry")
        field.pack(fill="x")
        shortcuts = tk.Frame(panel, bg=PANEL)
        shortcuts.pack(fill="x", pady=(8, 12))
        Button(shortcuts, text="Downloads", command=lambda: path.set(str(Path(DEFAULT_FOLDER).parent))).pack(side="left")
        Button(shortcuts, text="Downloads / Sonora", command=lambda: path.set(DEFAULT_FOLDER)).pack(side="left", padx=6)
        Button(shortcuts, text="Procurar…", command=lambda: self.browse_destination(dialog, path)).pack(side="right")

        if self.recent_folders:
            self.label(panel, "Pastas recentes").pack(anchor="w")
            recent = ttk.Combobox(panel, state="readonly", width=54, values=self.recent_folders,
                                  style="Inset.TCombobox")
            recent.pack(fill="x", pady=(4, 12))
            recent.bind("<<ComboboxSelected>>", lambda _event: path.set(recent.get()))

        use_default = tk.BooleanVar(dialog, remember)
        if not remember:
            ttk.Checkbutton(panel, text="Salvar também como pasta padrão", variable=use_default).pack(anchor="w")
        error = tk.StringVar(dialog)
        tk.Label(panel, textvariable=error, bg=PANEL, fg="#ffc5c2", font=font_name(10),
                 wraplength=430, justify="left").pack(fill="x", pady=6)

        chosen = None

        def confirm(_event=None):
            nonlocal chosen
            try:
                chosen = self.destination(path.get())
            except (OSError, ValueError, RuntimeError) as exc:
                error.set(str(exc))
                return
            key = os.path.normcase(chosen)
            self.recent_folders = [chosen, *(value for value in self.recent_folders
                                            if os.path.normcase(value) != key)][:6]
            if use_default.get():
                self.folder.set(chosen)
            self.persist()
            dialog.destroy()

        actions = tk.Frame(panel, bg=PANEL)
        actions.pack(fill="x")
        Button(actions, text="Salvar pasta padrão" if remember else "Usar neste lote",
               command=confirm, style="Primary.TButton").pack(side="right")
        Button(actions, text="Cancelar", command=dialog.destroy).pack(side="right", padx=8)
        dialog.bind("<Return>", confirm)
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        field.focus_set()
        dialog.grab_set()
        try:
            self.root.wait_window(dialog)
        finally:
            self.destination_dialog = None
        return chosen

    def browse_destination(self, parent, path):
        try:
            start = Path(self.destination(path.get()))
            while not start.is_dir() and start != start.parent:
                start = start.parent
        except (OSError, ValueError, RuntimeError):
            start = Path.home()
        directory = filedialog.askdirectory(title="Procurar pasta de download", initialdir=str(start),
                                             mustexist=True, parent=parent)
        if directory:
            path.set(directory)

    def destination(self, value=None):
        value = self.folder.get() if value is None else value
        path = Path(os.path.expandvars(value.strip() or DEFAULT_FOLDER)).expanduser().resolve()
        # Reject ordinary files even when they are an ancestor of the destination.
        for directory in (path, *path.parents):
            if directory.is_dir():
                break
            if directory.exists():
                raise ValueError(f"O destino contém um arquivo no lugar de uma pasta: {directory}")
        return str(path)

    def batch_destination(self, parent=None):
        return self.choose_folder(parent, remember=False) if self.ask_destination.get() else self.destination()

    def open_folder(self):
        try:
            path = Path(self.destination())
            path.mkdir(parents=True, exist_ok=True)
            open_path(path)
        except (OSError, ValueError, RuntimeError) as exc:
            messagebox.showerror("Pasta indisponível", str(exc), parent=self.root)

    def urls(self):
        items = list(dict.fromkeys(re.split(r"\s+", self.links.get("1.0", "end").strip())))
        if not items or not items[0]:
            raise ValueError("Cole pelo menos um link do YouTube.")
        return [media.youtube_url(item) for item in items]

    def enqueue(self):
        if self.closing:
            return
        try:
            urls = self.urls()
            folder = self.batch_destination()
            if folder is None or self.closing:
                return
            jobs = [
                media.Job(url, self.mode.get(), self.format.get(), self.quality.get(), folder,
                          self.playlist.get() or url.split("?", 1)[0].rstrip("/").endswith("/playlist"))
                for url in urls
            ]
        except (OSError, ValueError, RuntimeError) as exc:
            messagebox.showwarning("Verifique os links ou a pasta", str(exc), parent=self.root)
            return
        self.jobs.extend(jobs)
        self.queue_filter = "Todos"
        self.links.delete("1.0", "end")
        self.changed()
        self.status.set(f"{len(jobs)} link(s) adicionado(s).")
        self.next_job()

    def selected(self):
        return [self.jobs_by_id[item] for item in self.tree.selection() if item in self.jobs_by_id]

    def clear_done(self):
        self.jobs[:] = [job for job in self.jobs if job.status != media.DONE]
        self.changed()

    def remove(self):
        ids = {job.id for job in self.selected() if job.status != media.ACTIVE}
        self.jobs[:] = [job for job in self.jobs if job.id not in ids]
        self.changed()

    def retry(self):
        for job in self.selected():
            if job.status in {media.FAILED, media.STOPPED}:
                job.status, job.error = media.PENDING, ""
        self.changed()
        self.next_job()

    def details(self):
        selected = self.selected()
        if not selected:
            return
        job = selected[0]
        if job.status == media.DONE and job.result:
            try:
                open_path(Path(job.result))
            except OSError as exc:
                messagebox.showerror("Arquivo indisponível", str(exc), parent=self.root)
        elif job.error:
            self.show_error("Erro no download", job.error)
        else:
            messagebox.showinfo(job.status, f"{job.title or job.url}\n\n{job.folder}", parent=self.root)

    def show_error(self, title, details, hint=None):
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        pane = self.card(dialog)
        pane.pack(fill="both", expand=True, padx=7, pady=7)
        tk.Label(pane, text=hint or media.error_hint(details), bg=PANEL, fg=INK,
                 anchor="w", justify="left", wraplength=510, font=font_name(11, "bold")).pack(fill="x")
        body_panel = self.rounded_panel(pane, BG, PANEL, (7, 6), 7)
        body_panel.pack(fill="both", expand=True, pady=(9, 8))
        body = tk.Text(body_panel, height=9, width=58, wrap="word", bg=BG, fg=INK,
                       relief="flat", padx=8, pady=6, font=font_name(9))
        body.insert("1.0", details)
        body.configure(state="disabled")
        body.pack(fill="both", expand=True)
        buttons = tk.Frame(pane, bg=PANEL)
        buttons.pack(fill="x")

        def copy():
            self.root.clipboard_clear()
            self.root.clipboard_append(details)
            copy_button.configure(text="Copiado")

        copy_button = Button(buttons, text="Copiar detalhes", command=copy)
        copy_button.pack(side="left")
        Button(buttons, text="Fechar", command=dialog.destroy).pack(side="right")
        dialog.bind("<Escape>", lambda _: dialog.destroy())

    def select_queue(self, name):
        self.queue_filter = name
        self.refresh()

    def refresh(self):
        statuses = {
            "Pendentes": {media.PENDING, media.ACTIVE},
            "Concluídos": {media.DONE},
            "Falhas": {media.FAILED, media.STOPPED},
        }.get(self.queue_filter)
        self.jobs_by_id = {job.id: job for job in self.jobs}
        visible = [job for job in self.jobs if statuses is None or job.status in statuses]
        children = tuple(job.id for job in visible)
        removed = self.queue_rows.keys() - self.jobs_by_id.keys()
        if removed:
            self.tree.delete(*removed)
            for item in removed:
                del self.queue_rows[item]
        for name, button in self.filter_buttons.items():
            style = "QueueSelected.TButton" if name == self.queue_filter else "Queue.TButton"
            if button.cget("style") != style:
                button.configure(style=style)
        for index, job in enumerate(visible):
            quality = job.quality
            if job.mode == "Áudio" and quality.isdigit():
                quality += " kbps"
            fmt = ("Faixa " + quality) if job.mode == "Faixa nativa" else job.format
            values = (job.title or job.url, fmt, quality, job.status)
            tags = (job.status, "even") if index % 2 == 0 else (job.status,)
            if job.id not in self.queue_rows:
                self.tree.insert("", "end", iid=job.id, values=values, tags=tags)
            elif self.queue_rows[job.id] != (values, tags):
                self.tree.item(job.id, values=values, tags=tags)
            self.queue_rows[job.id] = (values, tags)
        if self.tree.get_children() != children:
            self.tree.set_children("", *children)
        if visible:
            self.empty.place_forget()
        else:
            self.empty_title.set("A fila está vazia" if self.queue_filter == "Todos" else "Nenhum item nesta lista")
            self.empty_hint.set("Cole um link do YouTube para começar." if self.queue_filter == "Todos" else "")
            self.empty.place(relx=0.5, rely=0.56, anchor="center")
        self.pending_count = sum(job.status == media.PENDING for job in self.jobs)
        self.done_count = sum(job.status == media.DONE for job in self.jobs)
        self.counts.set(f"{self.pending_count} pend.  ·  {self.done_count} prontos")
        self.update_controls()

    def update_controls(self):
        selected = self.selected()
        self.action_buttons["Detalhes / abrir"].state(["!disabled" if selected else "disabled"])
        can_retry = any(job.status in {media.FAILED, media.STOPPED} for job in selected)
        self.action_buttons["Tentar novamente"].state(["!disabled" if can_retry else "disabled"])
        can_remove = any(job.status != media.ACTIVE for job in selected)
        self.action_buttons["Remover"].state(["!disabled" if can_remove else "disabled"])
        can_cancel = self.active and not self.cancelling
        self.action_buttons["Cancelar atual"].state(["!disabled" if can_cancel else "disabled"])
        can_start = self.running or self.pending_count
        self.start_button.state(["!disabled" if can_start else "disabled"])
        self.clear_button.state(["!disabled" if self.done_count else "disabled"])

    def persist(self):
        try:
            media.save_state({
                "folder": self.folder.get(), "mode": self.mode.get(), "format": self.format.get(),
                "quality": self.quality.get(), "playlist": self.playlist.get(),
                "update_repo": self.update_repo,
                "ask_destination": self.ask_destination.get(),
                "recent_folders": self.recent_folders,
                "original_audio_default_migrated": True
            }, self.jobs)
        except OSError as exc:
            self.status.set(f"Falha ao salvar a fila: {exc}")

    def changed(self):
        self.refresh()
        self.persist()

    def toggle(self):
        if self.closing:
            return
        self.running = not self.running
        self.start_button.configure(text="Pausar fila" if self.running else "Iniciar fila")
        if self.running:
            self.next_job()
        else:
            self.status.set("Fila pausada. O item atual pode terminar.")
        self.update_controls()

    def cancel(self):
        if self.active and not self.cancelling:
            self.cancelling = True
            self.update_controls()
            self.status.set("Cancelando o item atual…")
            Thread(target=self.active[1].stop, daemon=True).start()

    def next_job(self):
        if not self.running or self.active or self.closing:
            return
        job = next((job for job in self.jobs if job.status == media.PENDING), None)
        if not job:
            self.running = False
            self.start_button.configure(text="Iniciar fila")
            self.update_controls()
            if not self.jobs:
                self.status.set("Fila sem itens pendentes.")
            return
        runner = media.Process()
        self.active = (job, runner)
        job.status = media.ACTIVE
        self.percent.set(0)
        self.status.set("Consultando playlist…" if job.playlist else "Consultando o YouTube…")
        self.changed()

        def work():
            try:
                if job.playlist:
                    entries = media.playlist_entries(media.inspect(job.url, True, runner), job.url)
                    self.events.put(("expanded", entries))
                else:
                    outcome = media.download(job, runner, lambda *args: self.events.put(("progress", args)))
                    self.events.put(("done", outcome))
            except media.Cancelled:
                self.events.put(("cancelled", None))
            except Exception as exc:
                self.events.put(("failed", str(exc)))

        self.worker = Thread(target=work, daemon=True)
        self.worker.start()

    def inspect(self):
        if self.lookup or self.closing:
            return
        try:
            url = self.urls()[0]
        except ValueError as exc:
            messagebox.showwarning("Ver formatos", str(exc), parent=self.root)
            return
        runner = media.Process()
        self.lookup = runner
        self.inspect_button.state(["disabled"])
        self.status.set("Consultando formatos do primeiro link…")

        def work():
            try:
                document = media.inspect(url, False, runner)
                self.events.put(("inspected", (url, document)))
            except Exception as exc:
                self.events.put(("inspect_error", str(exc)))

        self.lookup_thread = Thread(target=work, daemon=True)
        self.lookup_thread.start()

    def formats_dialog(self, url, document):
        rows = list(media.format_rows(document))
        if not rows:
            messagebox.showinfo("Ver formatos", "Cole o link de um vídeo para ver suas faixas.", parent=self.root)
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Formatos e tamanhos")
        dialog.configure(bg=BG)
        dialog.geometry(f"{min(1020, self.root.winfo_screenwidth() - 35)}x510")
        dialog.minsize(775, 370)
        dialog.transient(self.root)
        pane = self.card(dialog)
        pane.pack(fill="both", expand=True, padx=7, pady=7)
        tk.Label(pane, bg=PANEL, fg=INK, text=document.get("title") or url, font=font_name(14, "bold"),
                 anchor="w", wraplength=720, justify="left").pack(fill="x", pady=(0, 8))
        footer = tk.Frame(pane, bg=PANEL)
        footer.pack(side="bottom", fill="x", pady=(9, 0))
        tk.Label(footer, bg=PANEL, fg=MUTED, text="¹ O tamanho da faixa exclui o áudio anexado ao MKV.",
                 font=font_name(9), wraplength=390, justify="left").pack(side="left")
        columns = (("id", "ID", 62), ("kind", "Tipo", 174), ("ext", "Formato", 73), ("res", "Resolução", 83),
                   ("fps", "FPS", 55), ("rate", "kbps", 65), ("size", "Tamanho", 104), ("codec", "Codec", 170))
        table = self.rounded_panel(pane, BG, PANEL, (7, 6), 7)
        table.pack(fill="both", expand=True)
        tree = self.make_table(table, columns, "codec")
        tree.tag_configure("even", background="#151e2d")
        for index, row in enumerate(rows):
            tree.insert("", "end", values=row, tags=("even",) if index % 2 == 0 else ())

        def add():
            if not tree.selection():
                messagebox.showinfo("Escolher faixa", "Selecione uma ou mais faixas na tabela.", parent=dialog)
                return
            if self.closing:
                return
            try:
                folder = self.batch_destination(dialog)
                if folder is None or self.closing:
                    return
            except (OSError, ValueError, RuntimeError) as exc:
                messagebox.showwarning("Pasta de destino", str(exc), parent=dialog)
                return
            for item in tree.selection():
                identifier, kind, *_ = tree.item(item, "values")
                self.jobs.append(media.Job(url, "Faixa nativa", kind, str(identifier), folder,
                                           title=document.get("title") or ""))
            self.queue_filter = "Todos"
            self.changed()
            self.status.set("Faixas adicionadas à fila.")
            dialog.destroy()
            self.next_job()

        Button(footer, text="Adicionar faixas selecionadas", style="Primary.TButton",
                   command=add).pack(side="right")

    def update_dialog(self):
        if self.closing:
            return
        if self.update_dialog_window and self.update_dialog_window.winfo_exists():
            self.update_dialog_window.lift()
            self.check_updates(manual=True)
            return
        dialog = tk.Toplevel(self.root)
        self.update_dialog_window = dialog
        dialog.title("Atualizações do Sonora")
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        panel = self.card(dialog)
        panel.pack(fill="both", expand=True, padx=7, pady=7)
        self.label(panel, f"Sonora {updater.VERSION}", heading=True).pack(anchor="w")
        tk.Label(panel, textvariable=self.update_status, bg=PANEL, fg=MUTED, justify="left",
                 wraplength=380, anchor="w", width=49, height=3).pack(fill="x")
        actions = tk.Frame(panel, bg=PANEL)
        actions.pack(fill="x")
        self.update_check_button = Button(actions, text="Verificar agora",
                                              command=lambda: self.check_updates(manual=True))
        self.update_check_button.pack(side="left")
        self.update_install_button = Button(actions, text="Atualizar e reiniciar",
                                                command=self.apply_update, style="Primary.TButton")
        self.update_install_button.pack(side="right")
        self.refresh_update_button()
        self.check_updates(manual=True)

    def refresh_update_button(self):
        if self.update_after_job:
            caption, command = "Aguardando download…", self.update_dialog
        elif self.update_pending:
            caption, command = "Atualizar e reiniciar", self.apply_update
        else:
            caption, command = "Atualizações", self.update_dialog
        self.update_button.configure(text=caption, command=command,
                                     style="Primary.TButton" if self.update_pending else "TButton")
        if self.update_dialog_window and self.update_dialog_window.winfo_exists():
            self.update_check_button.state(["disabled" if self.update_thread or self.update_pending else "!disabled"])
            ready = self.update_pending and not self.update_after_job
            self.update_install_button.state(["!disabled" if ready else "disabled"])

    def apply_update(self):
        if not self.update_pending or self.closing or self.update_after_job:
            return
        if self.active:
            self.update_after_job = True
            self.update_status.set("O Sonora vai atualizar assim que o download atual terminar.")
            self.refresh_update_button()
        else:
            self.close(restart=True)

    def check_updates(self, manual=False):
        if self.closing:
            return
        if not manual:
            self.root.after(6 * 60 * 60 * 1000, self.check_updates)
        if not self.update_repo or self.update_thread is not None:
            return
        if self.update_pending:
            self.update_status.set(f"Versão {self.update_pending[0]} pronta para instalar")
            return
        repo = self.update_repo
        self.update_status.set("Consultando o GitHub…")

        def work():
            try:
                pending = updater.stage(repo, on_download=lambda version: self.events.put(("update_download", version)))
            except Exception as error:
                self.events.put(("update_error", updater.describe_error(error)))
            else:
                self.events.put(("update_ready", pending))

        self.update_thread = Thread(target=work, daemon=True)
        self.update_thread.start()
        self.refresh_update_button()

    def report_update_error(self):
        path = media.DATA / "update_error.txt"
        try:
            error = path.read_text(encoding="utf-8")
            path.unlink()
        except OSError:
            return
        self.update_status.set("A instalação da atualização falhou")
        self.show_error("Atualizações do Sonora", error, hint="Confira as permissões da pasta do Sonora e tente novamente.")

    def poll(self):
        # Yield to Tk even when a large playlist or download keeps producing events.
        for _ in range(50):
            try:
                event, data = self.events.get_nowait()
            except Empty:
                break
            if event == "update_download":
                self.update_status.set(f"Baixando Sonora {data}…")
                continue
            if event in {"update_ready", "update_error"}:
                self.update_thread = None
                if event == "update_error":
                    self.update_status.set(data)
                elif data:
                    self.update_pending = data
                    self.update_status.set(f"Versão {data[0]} pronta para instalar")
                    self.status.set(f"Sonora {data[0]} baixado. Clique em Atualizar e reiniciar.")
                else:
                    self.update_status.set("Você já está na versão mais recente.")
                self.refresh_update_button()
                continue
            if event in {"inspected", "inspect_error"}:
                self.lookup = None
                self.inspect_button.state(["!disabled"])
                if self.closing:
                    continue
                if event == "inspected":
                    self.status.set("Formatos consultados.")
                    self.formats_dialog(*data)
                else:
                    self.status.set("Falha ao consultar formatos.")
                    self.show_error("Consulta de formatos", data)
                continue
            if self.active is None:
                continue
            job, _ = self.active
            if event == "progress":
                if self.cancelling:
                    continue
                stage, percent, details = data
                self.percent.set(percent)
                if stage == "Preparando" and details and job.title != details:
                    job.title = details
                    if job.id in self.queue_rows:
                        values, tags = self.queue_rows[job.id]
                        values = (details, *values[1:])
                        self.tree.item(job.id, values=values)
                        self.queue_rows[job.id] = (values, tags)
                baseline = job.title or job.url
                text = details or baseline
                self.status.set(f"{stage} · {text[:95] + '…' if len(text) > 95 else text}")
                continue
            self.active = None
            self.cancelling = False
            if event == "expanded":
                index = self.jobs.index(job)
                self.jobs[index:index + 1] = [
                    media.Job(url, job.mode, job.format, job.quality, job.folder, title=title)
                    for url, title in data
                ]
                self.status.set(f"{len(data)} vídeo(s) na playlist.")
            elif event == "done":
                job.title, job.result = data
                job.status = media.DONE
                self.percent.set(100)
                filename = Path(job.result).name
                self.status.set(f"Salvo · {filename[:95] + '…' if len(filename) > 95 else filename}")
            elif event == "failed":
                job.status, job.error = media.FAILED, data
                self.status.set("Download falhou. Abra os detalhes do item para ver o erro.")
            elif event == "cancelled":
                job.status = media.PENDING if self.closing else media.STOPPED
                self.status.set("Download interrompido.")
            self.changed()
            if self.update_after_job and not self.closing:
                self.close(restart=True)
            else:
                self.next_job()
        if self.closing:
            if not any(thread and thread.is_alive() for thread in (self.worker, self.lookup_thread, self.update_thread)):
                if self.update_pending:
                    try:
                        updater.launch(self.update_pending[1], media.DATA / "instance.lock",
                                       restart=self.restart_after_update)
                    except OSError as error:
                        if self.restart_after_update:
                            self.closing = False
                            self.update_after_job = False
                            self.start_button.configure(text="Iniciar fila")
                            self.update_controls()
                            self.refresh_update_button()
                            self.show_error("Atualizações do Sonora", str(error))
                            self.root.after(70, self.poll)
                            return
                        updater.discard(self.update_pending[1])
                        messagebox.showerror("Atualizações do Sonora", str(error), parent=self.root)
                self.root.destroy()
                return
        self.root.after(70, self.poll)

    def close(self, restart=False):
        if self.closing:
            return
        if self.active and not messagebox.askyesno(
            "Sair do Sonora", "Interromper o download atual e deixá-lo na fila para a próxima sessão?", parent=self.root
        ):
            return
        self.restart_after_update = restart or self.update_after_job
        self.closing = True
        signal_startup_ready(ready=False)
        self.running = False
        self.persist()
        self.cancel()
        if self.update_thread and not self.active:
            self.status.set("Finalizando a verificação de atualizações…")
        if self.lookup:
            Thread(target=self.lookup.stop, daemon=True).start()


def log_startup(stage):
    try:
        with (media.DATA / "erro-sonora.log").open("a", encoding="utf-8") as log:
            log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {updater.VERSION} | {stage}\n")
    except OSError:
        pass


def signal_startup_ready(ready=True):
    global STARTUP_EVENT
    handle, STARTUP_EVENT = STARTUP_EVENT, None
    faulthandler.cancel_dump_traceback_later()
    if handle and os.name == "nt":
        import ctypes

        signal = ctypes.WinDLL("kernel32", use_last_error=True).SetEvent
        signal.argtypes = (ctypes.c_void_p,)
        signal.restype = ctypes.c_int
        if not signal(ctypes.c_void_p(int(handle))):
            log_startup(f"Falha ao avisar o lançador: erro Win32 {ctypes.get_last_error()}")
        else:
            log_startup("Lançador recebeu o sinal de abertura")
    if ready:
        log_startup("Interface respondeu aos eventos de abertura")


def main():
    if os.name == "nt":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    media.DATA.mkdir(parents=True, exist_ok=True)
    with (media.DATA / "instance.lock").open("a+b") as instance:
        try:
            if os.name == "nt":
                import msvcrt
                attempts = 20 if SAFE_START else 1
                for attempt in range(attempts):
                    instance.seek(0)
                    try:
                        msvcrt.locking(instance.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if attempt + 1 == attempts:
                            raise
                        time.sleep(0.15)
            else:
                import fcntl
                fcntl.flock(instance, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log_startup("A trava da instância está ocupada")
            signal_startup_ready(ready=False)
            window = tk.Tk()
            window.withdraw()
            messagebox.showinfo("Sonora", "O Sonora já está aberto.", parent=window)
        else:
            run_with_startup_diagnostics()


def run_with_startup_diagnostics():
    log_startup(f"Modo: {'compatibilidade' if SAFE_START else 'normal'}")
    try:
        log = (media.DATA / "erro-sonora.log").open("a", encoding="utf-8")
    except OSError:
        run_interface()
        return
    with log:
        faulthandler.dump_traceback_later(8, file=log)
        try:
            run_interface()
        finally:
            faulthandler.cancel_dump_traceback_later()


def run_interface():
    log_path = media.DATA / "erro-sonora.log"

    def report_error(error_type, error, stack):
        with log_path.open("a", encoding="utf-8") as log:
            traceback.print_exception(error_type, error, stack, file=log)

    log_startup("Inicializando o Tk")
    try:
        window = tk.Tk()
        window.withdraw()
    except Exception:
        report_error(*sys.exc_info())
        raise

    window.report_callback_exception = report_error
    try:
        Sonora(window)
    except Exception:
        report_error(*sys.exc_info())
        signal_startup_ready(ready=False)
        window.withdraw()
        messagebox.showerror("Sonora", f"Falha ao abrir o aplicativo. Consulte o diagnóstico em:\n{log_path}",
                             parent=window)
        window.destroy()
        return
    window.deiconify()
    window.mainloop()


if __name__ == "__main__":
    main()
