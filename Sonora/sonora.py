"""Interface desktop do Sonora."""

from pathlib import Path
from queue import Empty, Queue
from threading import Thread
import os
import re
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import engine as media
import updater


BG = "#18191b"
PANEL = "#222326"
FIELD = "#2c2e32"
BORDER = "#36383d"
INK = "#f4f4f6"
MUTED = "#b4b6be"
ACCENT = "#a9c6ff"
BLUE = "#2e68e8"
ASSETS = media.ROOT / "assets"
APP_ID = "Sonora.Windows.Desktop"
FONT = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
DEFAULT_FOLDER = str(Path.home() / "Downloads" / "Sonora")


def open_path(path):
    if os.name == "nt":
        os.startfile(str(path))
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


class Sonora:
    def __init__(self, root):
        self.root = root
        self.root.title("Sonora — Downloads do YouTube")
        scale = max(1, self.root.winfo_fpixels("1i") / 96)
        width = min(round(890 * scale), self.root.winfo_screenwidth() - 35)
        height = min(round(655 * scale), self.root.winfo_screenheight() - 110)
        self.root.minsize(width, height)
        self.root.geometry(f"{max(width, min(1130, self.root.winfo_screenwidth() - 35))}x"
                           f"{max(height, min(730, self.root.winfo_screenheight() - 110))}")
        self.window_icon = tk.PhotoImage(file=ASSETS / "sonora.png")
        self.root.iconphoto(True, self.window_icon)
        if os.name == "nt":
            self.root.iconbitmap(default=str(ASSETS / "sonora.ico"))
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.events = Queue()
        state = media.load_state()
        settings = state["settings"]
        self.jobs = state["jobs"]
        self.queue_filter = "Todos"
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
        self.update_repo = settings.get("update_repo", updater.DEFAULT_REPO)
        self.update_thread = None
        self.update_pending = None
        self.update_status = tk.StringVar(value=f"Versão {updater.VERSION}")
        self.style()
        self.build()
        self.update_options()
        self.refresh()
        self.root.after(70, self.poll)
        self.root.after(1500, self.check_updates)
        self.root.after(200, self.report_update_error)

    def style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=INK, font=(FONT, 10))
        style.configure("TButton", padding=(12, 7), background=FIELD, borderwidth=0,
                        focuscolor=ACCENT, focusthickness=1)
        style.map("TButton", background=[("active", "#3b3d43")], foreground=[("disabled", "#858892")])
        style.configure("Primary.TButton", background=BLUE, foreground="#ffffff", font=(FONT, 10, "bold"))
        style.map("Primary.TButton", background=[("disabled", FIELD), ("active", "#3e78fa")])
        style.configure("Selected.TButton", background="#314973", foreground="#edf3ff",
                        font=(FONT, 10, "bold"))
        style.map("Selected.TButton", background=[("active", "#3c5787")])
        style.configure("Queue.TButton", padding=(9, 4), background=PANEL, foreground=MUTED)
        style.configure("QueueSelected.TButton", padding=(9, 4), background=FIELD, foreground=ACCENT)
        style.map("Queue.TButton", background=[("active", FIELD)])
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
                        borderwidth=0, rowheight=max(31, round(self.root.winfo_fpixels("0.33i"))))
        style.configure("Treeview.Heading", background=FIELD, foreground=MUTED, relief="flat",
                        padding=(8, 7), font=(FONT, 9, "bold"))
        style.map("Treeview", background=[("selected", "#304672")], foreground=[("selected", INK)])
        style.configure("Vertical.TScrollbar", background=FIELD, troughcolor=PANEL, arrowcolor=MUTED, borderwidth=0)
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=FIELD, borderwidth=0)

    def build(self):
        toolbar = tk.Frame(self.root, bg=PANEL, padx=18, pady=10)
        toolbar.pack(fill="x")
        self.brand = tk.PhotoImage(file=ASSETS / "marca.png")
        tk.Label(toolbar, image=self.brand, bg=PANEL).pack(side="left", padx=(0, 11))
        tk.Label(toolbar, text="Sonora", bg=PANEL, fg=INK, font=(FONT, 19, "bold")).pack(side="left")
        tk.Label(toolbar, text="Downloads", bg=PANEL, fg=MUTED, font=(FONT, 10)).pack(side="left", padx=20)
        ttk.Button(toolbar, text="Atualizações", command=self.update_dialog).pack(side="right")
        ttk.Button(toolbar, text="Abrir pasta", command=self.open_folder).pack(side="right", padx=8)
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")

        status = tk.Frame(self.root, bg=PANEL, padx=17, pady=8)
        status.pack(side="bottom", fill="x")
        tk.Label(status, text=f"Sonora {updater.VERSION}", bg=PANEL, fg=MUTED, font=(FONT, 9)).pack(side="right")
        self.progress_label = tk.StringVar(value="0%")
        tk.Label(status, textvariable=self.progress_label, bg=PANEL, fg=ACCENT,
                 font=(FONT, 9, "bold"), width=5).pack(side="right", padx=(6, 12))
        ttk.Progressbar(status, variable=self.percent, maximum=100, length=130).pack(side="right")
        tk.Label(status, textvariable=self.status, bg=PANEL, fg=MUTED, anchor="w", font=(FONT, 9)).pack(
            side="left", fill="x", expand=True
        )
        self.percent.trace_add("write", lambda *_: self.progress_label.set(f"{self.percent.get():.0f}%"))

        workspace = tk.Frame(self.root, bg=BG, padx=13, pady=12)
        workspace.pack(fill="both", expand=True)
        sidebar = self.card(workspace)
        sidebar.pack(side="right", fill="y", padx=(9, 0))
        sidebar.configure(width=255)
        sidebar.pack_propagate(False)
        self.label(sidebar, "Saída", heading=True).pack(anchor="w", pady=(0, 14))
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
        note = self.label(sidebar, "", self.summary)
        note.configure(wraplength=216, justify="left", anchor="w", height=2)
        note.pack(fill="x")
        tk.Frame(sidebar, bg=BORDER, height=1).pack(fill="x", pady=(13, 12))
        self.label(sidebar, "Pasta de destino").pack(anchor="w")
        ttk.Entry(sidebar, textvariable=self.folder, width=16).pack(fill="x", pady=(5, 7))
        ttk.Button(sidebar, text="Alterar pasta…", command=self.choose_folder).pack(anchor="w")

        work = tk.Frame(workspace, bg=BG)
        work.pack(side="left", fill="both", expand=True)
        links = self.card(work)
        links.pack(fill="x", pady=(0, 9))
        header = tk.Frame(links, bg=PANEL)
        header.pack(fill="x", pady=(0, 7))
        self.label(header, "Origem", heading=True).pack(side="left")
        self.label(header, "Links do YouTube · um por linha").pack(side="left", padx=12)
        self.links = tk.Text(links, height=3, width=1, wrap="word", font=(FONT, 10), bg=BG, fg=INK,
                             insertbackground=INK, highlightthickness=1, highlightcolor=ACCENT,
                             highlightbackground=BORDER, relief="flat", padx=9, pady=7, undo=True)
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
        table = tk.Frame(queue, bg=BG, highlightthickness=1, highlightbackground=BORDER)
        table.pack(fill="both", expand=True)
        columns = (("title", "Título", 235), ("format", "Formato", 75),
                   ("quality", "Qualidade", 85), ("status", "Estado", 105))
        self.tree = self.make_table(table, columns, stretch="title")
        self.tree.bind("<Double-1>", lambda _: self.details())
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.update_controls())
        self.empty = tk.Frame(table, bg=BG)
        self.empty_title = tk.StringVar()
        tk.Label(self.empty, textvariable=self.empty_title, bg=BG, fg=INK, font=(FONT, 13, "bold")).pack()
        self.empty_hint = tk.StringVar()
        tk.Label(self.empty, textvariable=self.empty_hint, bg=BG, fg=MUTED,
                 font=(FONT, 10)).pack(pady=(5, 0))
        self.tree.tag_configure("even", background="#1e1f22")
        self.tree.tag_configure(media.DONE, foreground="#a9e7cc")
        self.tree.tag_configure(media.FAILED, foreground="#ffc5c2")
        self.tree.tag_configure(media.STOPPED, foreground=MUTED)
        self.root.bind("<Control-Return>", lambda _: self.enqueue())
        self.links.focus_set()

    def select_mode(self, mode):
        self.mode.set(mode)
        self.update_options()

    @staticmethod
    def card(parent):
        return tk.Frame(parent, bg=PANEL, padx=13, pady=10, highlightbackground=BORDER, highlightthickness=1)

    @staticmethod
    def label(parent, text, variable=None, heading=False):
        return tk.Label(parent, text=text, textvariable=variable, bg=PANEL,
                        fg=INK if heading else MUTED, font=(FONT, 13, "bold") if heading else (FONT, 9))

    @staticmethod
    def make_table(parent, columns, stretch):
        tree = ttk.Treeview(parent, columns=[column[0] for column in columns], show="headings")
        for key, label, width in columns:
            tree.heading(key, text=label, anchor="w")
            tree.column(key, minwidth=45, width=width, stretch=key == stretch)
        bar = ttk.Scrollbar(parent, command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
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
        ids = set(self.tree.selection())
        return [job for job in self.jobs if job.id in ids]

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
        pane = tk.Frame(dialog, bg=BG, padx=15, pady=13)
        pane.pack(fill="both", expand=True)
        tk.Label(pane, text=hint or media.error_hint(details), bg=BG, fg=INK,
                 anchor="w", justify="left", wraplength=510, font=(FONT, 11, "bold")).pack(fill="x")
        body = tk.Text(pane, height=9, width=58, wrap="word", bg=FIELD, fg=INK,
                       relief="flat", padx=8, pady=6, font=(FONT, 9))
        body.insert("1.0", details)
        body.configure(state="disabled")
        body.pack(fill="both", expand=True, pady=(9, 8))
        buttons = tk.Frame(pane, bg=BG)
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
        selected = set(self.tree.selection())
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        statuses = {
            "Pendentes": {media.PENDING, media.ACTIVE},
            "Concluídos": {media.DONE},
            "Falhas": {media.FAILED, media.STOPPED},
        }.get(self.queue_filter)
        visible = [job for job in self.jobs if statuses is None or job.status in statuses]
        for name, button in self.filter_buttons.items():
            button.configure(style="QueueSelected.TButton" if name == self.queue_filter else "Queue.TButton")
        for index, job in enumerate(visible):
            quality = job.quality
            if job.mode == "Áudio" and quality.isdigit():
                quality += " kbps"
            fmt = ("Faixa " + quality) if job.mode == "Faixa nativa" else job.format
            self.tree.insert("", "end", iid=job.id, values=(
                job.title or job.url, fmt, quality, job.status
            ), tags=(job.status, "even") if index % 2 == 0 else (job.status,))
            if job.id in selected:
                self.tree.selection_add(job.id)
        if visible:
            self.empty.place_forget()
        else:
            self.empty_title.set("A fila está vazia" if self.queue_filter == "Todos" else "Nenhum item nesta lista")
            self.empty_hint.set("Cole um link em Origem para começar." if self.queue_filter == "Todos" else "")
            self.empty.place(relx=0.5, rely=0.56, anchor="center")
        pending = sum(job.status == media.PENDING for job in self.jobs)
        done = sum(job.status == media.DONE for job in self.jobs)
        self.counts.set(f"{pending} na fila  ·  {done} concluídos")
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
        can_start = self.running or any(job.status == media.PENDING for job in self.jobs)
        self.start_button.state(["!disabled" if can_start else "disabled"])
        self.clear_button.state(["!disabled" if any(job.status == media.DONE for job in self.jobs) else "disabled"])

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
        pane = tk.Frame(dialog, bg=BG, padx=16, pady=14)
        pane.pack(fill="both", expand=True)
        tk.Label(pane, bg=BG, fg=INK, text=document.get("title") or url, font=(FONT, 14, "bold"),
                 anchor="w", wraplength=720, justify="left").pack(fill="x", pady=(0, 8))
        footer = tk.Frame(pane, bg=BG)
        footer.pack(side="bottom", fill="x", pady=(9, 0))
        tk.Label(footer, bg=BG, fg=MUTED, text="¹ O tamanho listado é só da faixa de vídeo. O áudio é somado no MKV.",
                 font=(FONT, 9)).pack(side="left")
        columns = (("id", "ID", 62), ("kind", "Tipo", 174), ("ext", "Formato", 73), ("res", "Resolução", 83),
                   ("fps", "FPS", 55), ("rate", "kbps", 65), ("size", "Tamanho", 104), ("codec", "Codec", 170))
        tree = self.make_table(pane, columns, "codec")
        tree.tag_configure("even", background="#1e1f22")
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
        dialog = tk.Toplevel(self.root)
        dialog.title("Atualizações do Sonora")
        dialog.configure(bg=PANEL)
        dialog.transient(self.root)
        panel = self.card(dialog)
        panel.pack(fill="both", expand=True)
        self.label(panel, "", self.update_status, heading=True).pack(anchor="w")
        self.label(panel, "Repositório público do Sonora no GitHub (dono/repositorio)").pack(
            anchor="w", pady=(9, 4)
        )
        value = tk.StringVar(value=self.update_repo)
        entry = ttk.Entry(panel, textvariable=value, width=51)
        entry.pack(fill="x")
        tk.Label(panel, bg=PANEL, fg=MUTED, justify="left", wraplength=415,
                 text="As versões são baixadas em segundo plano e instaladas ao sair. "
                      "Use um repositório seu ou de um mantenedor em quem você confia. "
                      "Deixe o campo vazio para desativar.").pack(anchor="w", pady=(8, 10))

        def save():
            if self.update_thread is not None:
                messagebox.showinfo("Atualizações", "Aguarde a consulta atual terminar.", parent=dialog)
                return
            try:
                repo = updater.normalize_repo(value.get()) if value.get().strip() else ""
            except ValueError as exc:
                messagebox.showwarning("Atualizações", str(exc), parent=dialog)
                return
            if repo != self.update_repo and self.update_pending:
                updater.discard(self.update_pending[1])
                self.update_pending = None
            self.update_repo = repo
            self.persist()
            self.update_status.set(f"Versão {updater.VERSION}")
            self.check_updates(manual=True)

        ttk.Button(panel, text="Salvar e verificar", style="Primary.TButton", command=save).pack(anchor="e")
        entry.focus_set()

    def check_updates(self, manual=False):
        if self.closing:
            return
        if not manual:
            self.root.after(6 * 60 * 60 * 1000, self.check_updates)
        if not self.update_repo or self.update_thread is not None:
            return
        if self.update_pending:
            self.update_status.set(f"Versão {self.update_pending[0]} pronta para instalar ao sair")
            return
        repo = self.update_repo
        self.update_status.set("Consultando o GitHub…")

        def work():
            try:
                pending = updater.stage(repo)
            except Exception as error:
                self.events.put(("update_error", updater.describe_error(error)))
            else:
                self.events.put(("update_ready", pending))

        self.update_thread = Thread(target=work, daemon=True)
        self.update_thread.start()

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
        while True:
            try:
                event, data = self.events.get_nowait()
            except Empty:
                break
            if event in {"update_ready", "update_error"}:
                self.update_thread = None
                if event == "update_error":
                    self.update_status.set(data)
                elif data:
                    self.update_pending = data
                    self.update_status.set(f"Versão {data[0]} pronta para instalar ao sair")
                    self.status.set(f"Sonora {data[0]} baixado. A instalação será feita ao fechar.")
                else:
                    self.update_status.set(f"Versão {updater.VERSION} · você está em dia")
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
                if stage == "Preparando" and details:
                    job.title = details
                    self.refresh()
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
            self.next_job()
        if self.closing:
            if not any(thread and thread.is_alive() for thread in (self.worker, self.lookup_thread, self.update_thread)):
                if self.update_pending:
                    try:
                        updater.launch(self.update_pending[1], media.DATA / "instance.lock")
                    except OSError as error:
                        updater.discard(self.update_pending[1])
                        messagebox.showerror("Atualizações do Sonora", str(error), parent=self.root)
                self.root.destroy()
                return
        self.root.after(70, self.poll)

    def close(self):
        if self.closing:
            return
        if self.active and not messagebox.askyesno(
            "Sair do Sonora", "Interromper o download atual e deixá-lo na fila para a próxima sessão?", parent=self.root
        ):
            return
        self.closing = True
        self.running = False
        self.persist()
        self.cancel()
        if self.update_thread and not self.active:
            self.status.set("Finalizando a verificação de atualizações…")
        if self.lookup:
            Thread(target=self.lookup.stop, daemon=True).start()


def main():
    if os.name == "nt":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    window = tk.Tk()
    media.DATA.mkdir(parents=True, exist_ok=True)
    with (media.DATA / "instance.lock").open("a+b") as instance:
        try:
            if os.name == "nt":
                import msvcrt
                instance.seek(0)
                msvcrt.locking(instance.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(instance, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            window.withdraw()
            messagebox.showinfo("Sonora", "O Sonora já está aberto.", parent=window)
        else:
            Sonora(window)
            window.mainloop()


if __name__ == "__main__":
    main()
