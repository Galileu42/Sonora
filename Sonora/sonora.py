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


BG = "#111318"
PANEL = "#1a1e26"
FIELD = "#252b36"
BORDER = "#313847"
INK = "#f2f5fc"
MUTED = "#b4bfce"
ACCENT = "#a9caff"
BLUE = "#275ed6"
ASSETS = media.ROOT / "assets"
APP_ID = "Sonora.Windows.Desktop"
SAFE_START = "--safe-start" in sys.argv
FONT = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
FONT_STYLES = ((9, "normal"), (9, "bold"), (10, "normal"), (10, "bold"),
               (11, "normal"), (11, "bold"), (14, "bold"), (15, "bold"), (20, "bold"))


def font_name(size, weight="normal"):
    return f"SonoraFont{size}{weight}"


DEFAULT_FOLDER = str(Path.home() / "Downloads" / "Sonora")


def open_path(path):
    if os.name == "nt":
        os.startfile(str(path))
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


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
        self.mode = tk.StringVar(value=settings.get("mode", "Áudio"))
        self.format = tk.StringVar(value=settings.get("format", "MP3"))
        self.quality = tk.StringVar(value=settings.get("quality", "192"))
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
        self.startup_font_pending = False
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
        if SAFE_START or self.closing:
            signal_startup_ready()
            return
        log_startup("Aplicando o tema arredondado")
        self.apply_rounded_style()
        if os.name != "nt":
            self.complete_visual_startup()
            return

        log_startup("Carregando a fonte Nunito")
        self.startup_font_pending = True
        self.root.after(1800, self.finish_font_startup)
        Thread(target=self.register_font_for_startup, daemon=True).start()

    def register_font_for_startup(self):
        try:
            registered = self.register_font()
        except (OSError, ValueError) as error:
            log_startup(f"Fonte arredondada indisponível: {error}")
            registered = False
        self.events.put(("rounded_font", registered))

    def complete_visual_startup(self):
        self.startup_font_pending = False
        # Let Tk lay out and draw the updated widgets before dismissing recovery.
        self.root.after_idle(lambda: self.root.after(0, signal_startup_ready))

    def finish_font_startup(self, registered=False):
        if not self.startup_font_pending:
            return
        if registered and not self.closing:
            log_startup("Aplicando a fonte Nunito")
            for font in self.fonts:
                font.configure(family="Nunito")
            if self.fonts[0].actual("family").casefold() != "nunito":
                for font in self.fonts:
                    font.configure(family=FONT)
                log_startup("O Tk não selecionou a fonte Nunito")
        self.complete_visual_startup()

    def apply_rounded_style(self):
        if self.closing:
            return
        style = ttk.Style(self.root)
        try:
            style.theme_create("sonora", parent="clam")
            style.theme_use("sonora")
            self.configure_style(style)
            self.rounded_styles(style)
        except tk.TclError as error:
            style.theme_use("clam")
            log_startup(f"Tema arredondado indisponível: {error}")

    def register_font(self):
        import ctypes as ct
        from ctypes import wintypes as wt

        kernel = ct.windll.kernel32
        kernel.FindResourceW.argtypes = (wt.HMODULE, ct.c_void_p, ct.c_void_p)
        kernel.FindResourceW.restype = wt.HRSRC
        kernel.LoadResource.argtypes = (wt.HMODULE, wt.HRSRC)
        kernel.LoadResource.restype = wt.HGLOBAL
        kernel.SizeofResource.argtypes = (wt.HMODULE, wt.HRSRC)
        kernel.SizeofResource.restype = wt.DWORD
        kernel.LockResource.argtypes = (wt.HGLOBAL,)
        kernel.LockResource.restype = ct.c_void_p
        kernel.LoadLibraryExW.argtypes = (wt.LPCWSTR, wt.HANDLE, wt.DWORD)
        kernel.LoadLibraryExW.restype = wt.HMODULE
        kernel.FreeLibrary.argtypes = (wt.HMODULE,)
        module = kernel.LoadLibraryExW(str(ASSETS.parent / "Sonora.exe"), None, 0x22)
        if not module:
            log_startup("Não foi possível abrir os recursos de fonte")
            return False
        add = ct.windll.gdi32.AddFontResourceExW
        add.argtypes = (wt.LPCWSTR, wt.DWORD, ct.c_void_p)
        add.restype = ct.c_int
        try:
            folder = media.DATA / "fontes"
            folder.mkdir(exist_ok=True)
            for resource_id in (301, 302):
                resource = kernel.FindResourceW(module, resource_id, 10)
                if not resource:
                    return False
                loaded = kernel.LoadResource(module, resource)
                pointer = kernel.LockResource(loaded) if loaded else None
                if not pointer:
                    return False
                data = ct.string_at(pointer, kernel.SizeofResource(module, resource))
                path = folder / f"Nunito-{resource_id}.ttf"
                if not path.exists() or path.read_bytes() != data:
                    path.write_bytes(data)
                if not add(str(path), 0x10, None):
                    return False
        except (OSError, ValueError) as error:
            log_startup(f"Fonte arredondada indisponível: {error}")
            return False
        finally:
            kernel.FreeLibrary(module)
        return True

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
        style.configure("TButton", padding=(12, 7), background=FIELD, borderwidth=0,
                        focuscolor=ACCENT, focusthickness=1)
        style.map("TButton", foreground=[("disabled", "#9aa6b9")])
        style.configure("Primary.TButton", background=BLUE, foreground="#ffffff", font=font_name(11, "bold"))
        style.configure("Selected.TButton", background="#294878", foreground="#edf3ff",
                        font=font_name(11, "bold"))
        style.configure("Queue.TButton", padding=(9, 4), background=PANEL, foreground=MUTED)
        style.configure("QueueSelected.TButton", padding=(9, 4), background="#293a54", foreground=ACCENT)
        style.configure("TCheckbutton", background=PANEL, indicatorbackground=FIELD, padding=(0, 3))
        style.map("TCheckbutton", indicatorcolor=[("selected", ACCENT)], background=[("active", PANEL)])
        style.configure("TEntry", fieldbackground=FIELD, foreground=INK, insertcolor=INK, padding=7,
                        bordercolor=BORDER, lightcolor=FIELD, darkcolor=FIELD)
        style.configure("TCombobox", fieldbackground=FIELD, background=FIELD, arrowcolor=INK, padding=6,
                        bordercolor=BORDER, lightcolor=FIELD, darkcolor=FIELD)
        style.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", INK)],
                  bordercolor=[("focus", ACCENT)])
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
        style.configure("Link.TFrame", background=BG)
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=FIELD)
        if style.theme_use() == "clam":
            style.map("TButton", background=[("disabled", PANEL), ("active", "#384456")])

    def surface(self, fill, radius, outline=None, chevron=False):
        """Draw a transparent, antialiased surface for Tk's stretchable elements."""
        key = (fill, radius, outline, chevron)
        if key in self.style_images:
            return self.style_images[key]
        from base64 import b64encode
        from struct import pack
        import zlib

        if chevron:
            size = max(12, round(14 * self.scale))
        else:
            size = 2 * radius + 3
        rgb = bytes.fromhex(fill[1:])
        edge = bytes.fromhex(outline[1:]) if outline else rgb
        pixels = bytearray()
        for y in range(size):
            pixels.append(0)
            for x in range(size):
                if chevron:
                    horizontal = abs(x + 0.5 - size / 2)
                    stroke = abs(y + 0.5 - size * 0.59 + horizontal)
                    alpha = max(0.0, min(1.0, size * 0.31 - horizontal, 1.35 - stroke))
                    color = rgb
                else:
                    dx = max(radius - x - 0.5, x + 0.5 - size + radius, 0)
                    dy = max(radius - y - 0.5, y + 0.5 - size + radius, 0)
                    distance = (dx * dx + dy * dy) ** 0.5
                    alpha = max(0.0, min(1.0, radius + 0.5 - distance))
                    color = edge if outline and (distance >= radius - 1 or x in (0, size - 1)
                                                 or y in (0, size - 1)) else rgb
                pixels.extend(color)
                pixels.append(round(alpha * 255))

        def chunk(name, data):
            content = name + data
            return pack(">I", len(data)) + content + pack(">I", zlib.crc32(content))

        png = b"\x89PNG\r\n\x1a\n"
        png += chunk(b"IHDR", pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        png += chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")
        image = tk.PhotoImage(master=self.root, data=b64encode(png))
        self.style_images[key] = image
        return image

    def rounded_styles(self, style):
        self.style_images = {}
        control = round(9 * self.scale)
        panel = round(15 * self.scale)
        pill = round(13 * self.scale)

        def element(name, radius, fill, states=(), outline=None):
            normal = self.surface(fill, radius, outline=outline)
            variants = [(*state, self.surface(color, radius, outline=border))
                        for state, color, border in states]
            style.element_create(name, "image", normal, *variants, border=radius + 1, padding=0,
                                 width=1, height=1, sticky="nswe")

        for variant, radius, fill, hover, pressed in (
            ("", control, FIELD, "#353e4e", "#3d485c"),
            ("Primary.", control, BLUE, "#326bec", "#2252bc"),
            ("Selected.", control, "#294878", "#35578e", "#25416e"),
            ("Queue.", pill, PANEL, FIELD, "#2e3a50"),
            ("QueueSelected.", pill, "#293a54", "#334b6c", "#24364e"),
        ):
            style.configure(variant + "TButton", background=PANEL, width=0)
            surface = variant + "Sonora.Button"
            element(surface, radius, fill, (
                (("disabled",), PANEL, BORDER),
                (("pressed",), pressed, None),
                (("active", "focus"), hover, ACCENT),
                (("focus",), fill, ACCENT),
                (("active",), hover, None),
            ))
            style.layout(variant + "TButton", [(surface, {"sticky": "nswe", "children": [
                ("Button.padding", {"sticky": "nswe", "children": [
                    ("Button.label", {"sticky": "nswe"}),
                ]}),
            ]})])

        scroll_radius = max(3, round(4 * self.scale))
        scroll_track = self.surface(BG, scroll_radius)
        scroll_thumb = self.surface("#445169", scroll_radius)
        scroll_hover = self.surface("#596a86", scroll_radius)
        style.element_create("Sonora.Scrollbar.trough", "image", scroll_track, width=9, height=1,
                             border=scroll_radius, sticky="nswe")
        style.element_create("Sonora.Scrollbar.thumb", "image", scroll_thumb, ("active", scroll_hover),
                             width=9, height=18, border=scroll_radius, sticky="nswe")
        style.layout("Vertical.TScrollbar", [("Sonora.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Sonora.Scrollbar.thumb", {"expand": 1, "sticky": "nswe"}),
        ]})])
        track = self.surface(FIELD, max(2, round(3 * self.scale)))
        fill = self.surface(ACCENT, max(2, round(3 * self.scale)))
        style.element_create("Sonora.Progress.trough", "image", track, border=3, width=1, height=7, sticky="nswe")
        style.element_create("Sonora.Progress.pbar", "image", fill, border=3, width=1, height=7, sticky="nswe")
        style.layout("Horizontal.TProgressbar", [("Sonora.Progress.trough", {"sticky": "nswe", "children": [
            ("Sonora.Progress.pbar", {"side": "left", "sticky": "ns"}),
        ]})])

        element("Sonora.Card", panel, PANEL, outline=BORDER)
        style.configure("Card.TFrame", background=BG)
        style.layout("Card.TFrame", [("Sonora.Card", {"sticky": "nswe"})])
        element("Sonora.Link", control, BG, outline=BORDER)
        style.configure("Link.TFrame", background=PANEL)
        style.layout("Link.TFrame", [("Sonora.Link", {"sticky": "nswe"})])
        element("Sonora.Field", control, FIELD, ((("focus",), FIELD, ACCENT),), outline=BORDER)
        style.configure("TEntry", background=PANEL)
        style.configure("TCombobox", background=PANEL)
        style.layout("TEntry", [("Sonora.Field", {"sticky": "nswe", "children": [
            ("Entry.padding", {"sticky": "nswe", "children": [
                ("Entry.textarea", {"sticky": "nswe"}),
            ]}),
        ]})])
        arrow = self.surface(INK, control, chevron=True)
        style.element_create("Sonora.Combobox.downarrow", "image", arrow, padding=(0, 0, 8, 0))
        style.layout("TCombobox", [("Sonora.Field", {"sticky": "nswe", "children": [
            ("Sonora.Combobox.downarrow", {"side": "right", "sticky": "e"}),
            ("Combobox.padding", {"expand": 1, "sticky": "nswe", "children": [
                ("Combobox.textarea", {"sticky": "nswe"}),
            ]}),
        ]})])

    def build(self):
        toolbar = tk.Frame(self.root, bg=PANEL, padx=22, pady=11)
        toolbar.pack(fill="x")
        self.brand = tk.PhotoImage(file=ASSETS / "marca.png")
        tk.Label(toolbar, image=self.brand, bg=PANEL).pack(side="left", padx=(0, 11))
        tk.Label(toolbar, text="Sonora", bg=PANEL, fg=INK, font=font_name(20, "bold")).pack(side="left")
        self.update_button = ttk.Button(toolbar, text="Atualizações", command=self.update_dialog)
        self.update_button.pack(side="right")
        ttk.Button(toolbar, text="Abrir pasta", command=self.open_folder).pack(side="right", padx=8)
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
        sidebar.configure(width=max(246, round(self.root.winfo_fpixels("2.54i"))))
        sidebar.pack_propagate(False)
        self.label(sidebar, "Configurações de saída", heading=True).pack(anchor="w", pady=(0, 15))
        self.label(sidebar, "Tipo de mídia").pack(anchor="w")
        modes = tk.Frame(sidebar, bg=PANEL)
        modes.pack(fill="x", pady=(5, 13))
        self.mode_buttons = {}
        for name in ("Áudio", "Vídeo"):
            button = ttk.Button(modes, text=name, command=lambda value=name: self.select_mode(value))
            button.pack(side="left", fill="x", expand=True, padx=(0, 4) if name == "Áudio" else (4, 0))
            self.mode_buttons[name] = button

        self.label(sidebar, "Formato").pack(anchor="w")
        self.format_box = ttk.Combobox(sidebar, textvariable=self.format, state="readonly", width=15)
        self.format_box.pack(fill="x", pady=(5, 12))
        self.format_box.bind("<<ComboboxSelected>>", self.update_options)
        self.label(sidebar, "Qualidade").pack(anchor="w")
        self.quality_box = ttk.Combobox(sidebar, state="readonly", width=15)
        self.quality_box.pack(fill="x", pady=(5, 5))
        self.quality_box.bind("<<ComboboxSelected>>", self.set_quality)
        note_panel = ttk.Frame(sidebar, style="Link.TFrame", padding=(9, 3))
        note_panel.pack(fill="x", pady=(3, 0))
        tk.Label(note_panel, textvariable=self.summary, bg=BG, fg=ACCENT, font=font_name(10),
                 wraplength=max(175, round(195 * self.scale)), justify="left", anchor="w", height=2).pack(fill="x")
        tk.Frame(sidebar, bg=BORDER, height=1).pack(fill="x", pady=(13, 12))
        self.label(sidebar, "Pasta de destino").pack(anchor="w")
        ttk.Entry(sidebar, textvariable=self.folder, width=16).pack(fill="x", pady=(5, 7))
        ttk.Button(sidebar, text="Alterar pasta", command=self.choose_folder).pack(anchor="w")

        work = tk.Frame(workspace, bg=BG)
        work.pack(side="left", fill="both", expand=True)
        links = self.card(work)
        links.pack(fill="x", pady=(0, 12))
        header = tk.Frame(links, bg=PANEL)
        header.pack(fill="x", pady=(0, 7))
        self.label(header, "Adicionar links", heading=True).pack(anchor="w")
        self.label(header, "YouTube, Shorts ou playlists. Cole um link por linha.").pack(anchor="w", pady=(3, 0))
        input_frame = ttk.Frame(links, style="Link.TFrame", padding=(7, 5))
        input_frame.pack(fill="x")
        self.links = tk.Text(input_frame, height=2, width=1, wrap="word", font="TkTextFont", bg=BG, fg=INK,
                             insertbackground=INK, highlightthickness=0, relief="flat",
                             padx=4, pady=3, undo=True)
        self.links.pack(fill="x")
        actions = tk.Frame(links, bg=PANEL)
        actions.pack(fill="x", pady=(7, 0))
        ttk.Button(actions, text="Adicionar à fila", style="Primary.TButton", command=self.enqueue).pack(side="right")
        ttk.Button(actions, text="Colar", command=self.paste).pack(side="left")
        self.inspect_button = ttk.Button(actions, text="Ver formatos", command=self.inspect)
        self.inspect_button.pack(side="left", padx=(6, 8))
        ttk.Checkbutton(actions, text="Playlist inteira", variable=self.playlist).pack(side="left")

        queue = self.card(work)
        queue.pack(fill="both", expand=True)
        header = tk.Frame(queue, bg=PANEL)
        header.pack(fill="x", pady=(0, 9))
        self.label(header, "Fila de downloads", heading=True).pack(side="left")
        self.counts = tk.StringVar()
        self.label(header, "", self.counts).pack(side="left", padx=(10, 0))
        self.start_button = ttk.Button(header, text="Iniciar fila", style="Primary.TButton", command=self.toggle)
        self.start_button.pack(side="right")

        filters = tk.Frame(queue, bg=PANEL)
        filters.pack(fill="x", pady=(0, 7))
        self.filter_buttons = {}
        for name in ("Todos", "Pendentes", "Concluídos", "Falhas"):
            button = ttk.Button(filters, text=name, style="Queue.TButton",
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
            button = ttk.Button(footer, text=caption, command=action)
            button.pack(side="left", padx=(0, 5))
            self.action_buttons[key] = button
        self.clear_button = ttk.Button(footer, text="Limpar concluídos", command=self.clear_done)
        self.clear_button.pack(side="right")
        table = ttk.Frame(queue, style="Link.TFrame", padding=(6, 4))
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
        self.tree.tag_configure("even", background="#191e28")
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

    @staticmethod
    def card(parent):
        return ttk.Frame(parent, style="Card.TFrame", padding=(15, 12))

    @staticmethod
    def label(parent, text, variable=None, heading=False):
        return tk.Label(parent, text=text, textvariable=variable, bg=PANEL,
                        fg=INK if heading else MUTED, font=font_name(14, "bold") if heading else font_name(10))

    @staticmethod
    def make_table(parent, columns, stretch):
        tree = ttk.Treeview(parent, columns=[column[0] for column in columns], show="headings")
        for key, label, width in columns:
            tree.heading(key, text=label, anchor="w")
            tree.column(key, minwidth=45, width=width, stretch=key == stretch)
        bar = ttk.Scrollbar(parent, command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y", padx=(2, 0))
        tree.pack(fill="both", expand=True)
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
            self.format.set(formats[0])
        self.quality_values = {"Máxima disponível": "Máxima"}
        fmt = self.format.get()
        if self.mode.get() == "Vídeo":
            self.quality_values.update({f"Até {height}p": f"{height}p" for height in media.HEIGHTS})
        elif fmt not in {"FLAC", "WAV", "Original"}:
            self.quality_values.update({f"{rate} kbps": str(rate) for rate in media.RATES})
        self.quality_box.configure(values=list(self.quality_values))
        fallback = "192 kbps" if "192 kbps" in self.quality_values else "Máxima disponível"
        label = next((key for key, value in self.quality_values.items() if value == self.quality.get()), fallback)
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

    def choose_folder(self):
        directory = filedialog.askdirectory(initialdir=self.folder.get(), parent=self.root)
        if directory:
            self.folder.set(directory)
            self.persist()

    def destination(self):
        value = self.folder.get().strip()
        return str(Path(value or DEFAULT_FOLDER).expanduser().resolve())

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
            folder = self.destination()
            jobs = [
                media.Job(url, self.mode.get(), self.format.get(), self.quality.get(), folder,
                          self.playlist.get() or url.split("?", 1)[0].rstrip("/").endswith("/playlist"))
                for url in self.urls()
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
        body_panel = ttk.Frame(pane, style="Link.TFrame", padding=(6, 4))
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

        copy_button = ttk.Button(buttons, text="Copiar detalhes", command=copy)
        copy_button.pack(side="left")
        ttk.Button(buttons, text="Fechar", command=dialog.destroy).pack(side="right")
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
                "update_repo": self.update_repo
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
        table = ttk.Frame(pane, style="Link.TFrame", padding=(6, 4))
        table.pack(fill="both", expand=True)
        tree = self.make_table(table, columns, "codec")
        tree.tag_configure("even", background="#191e28")
        for index, row in enumerate(rows):
            tree.insert("", "end", values=row, tags=("even",) if index % 2 == 0 else ())

        def add():
            if not tree.selection():
                messagebox.showinfo("Escolher faixa", "Selecione uma ou mais faixas na tabela.", parent=dialog)
                return
            if self.closing:
                return
            try:
                folder = self.destination()
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

        ttk.Button(footer, text="Adicionar faixas selecionadas", style="Primary.TButton",
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
        self.update_check_button = ttk.Button(actions, text="Verificar agora",
                                              command=lambda: self.check_updates(manual=True))
        self.update_check_button.pack(side="left")
        self.update_install_button = ttk.Button(actions, text="Atualizar e reiniciar",
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
            if event == "rounded_font":
                self.finish_font_startup(registered=data)
                continue
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
    if ready:
        log_startup("Interface respondeu aos eventos de abertura")
    faulthandler.cancel_dump_traceback_later()
    handle = os.environ.pop("SONORA_STARTUP_EVENT", None)
    if handle and os.name == "nt":
        import ctypes

        ctypes.windll.kernel32.SetEvent(ctypes.c_void_p(int(handle)))


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
    window.mainloop()


if __name__ == "__main__":
    main()
