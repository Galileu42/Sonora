"""Fila local, seleção de formatos e processamento de mídia do Sonora."""

from collections import deque
from dataclasses import asdict, dataclass, field
from importlib.util import find_spec
from pathlib import Path
from threading import Event, Lock
from urllib.parse import urlsplit
from uuid import uuid4
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "Sonora"
RATES = (32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 192, 224, 256, 288, 320)
HEIGHTS = (144, 240, 360, 480, 720, 1080, 1440, 2160, 2880, 4320)
AUDIO = ("MP3", "M4A", "OPUS", "OGG", "FLAC", "WAV", "Original")
VIDEO = ("MP4", "MKV", "WEBM")
ENCODERS = {
    "MP3": "libmp3lame", "M4A": "aac", "OPUS": "libopus",
    "OGG": "libvorbis", "FLAC": "flac", "WAV": "pcm_s16le",
}
PENDING = "Na fila"
ACTIVE = "Processando"
DONE = "Concluído"
FAILED = "Falhou"
STOPPED = "Cancelado"


class Cancelled(Exception):
    pass


def youtube_url(value):
    try:
        url = urlsplit(value)
        youtube = url.hostname in {
            "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
            "youtu.be", "www.youtu.be",
        }
        valid = url.scheme in {"http", "https"} and youtube and not url.username and url.port is None
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f"Link inválido do YouTube: {value}")
    return value


def executable(name):
    local = ROOT / "tools" / (name + (".exe" if os.name == "nt" else ""))
    return str(local) if local.is_file() else shutil.which(name)


def binary_pair():
    ffmpeg = executable("ffmpeg")
    if not ffmpeg:
        return None, None
    sibling = Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    return ffmpeg, str(sibling) if sibling.is_file() else executable("ffprobe")


def downloader():
    if find_spec("yt_dlp") is None:
        raise RuntimeError("Motor de download ausente. Execute Preparar.cmd e abra o app novamente.")
    ffmpeg, ffprobe = binary_pair()
    if not (ffmpeg and ffprobe):
        raise RuntimeError("FFmpeg ou FFprobe ausente. Execute Preparar.cmd e abra o app novamente.")
    python = Path(sys.executable)
    if python.name.lower() == "pythonw.exe":
        python = python.with_name("python.exe")
    command = [str(python), "-m", "yt_dlp", "--ignore-config", "--no-colors", "--encoding", "utf-8",
               "--socket-timeout", "20", "--ffmpeg-location", str(Path(ffmpeg).parent)]
    deno = executable("deno")
    if deno:
        command += ["--js-runtimes", f"deno:{deno}"]
    elif executable("node"):
        command += ["--js-runtimes", f"node:{executable('node')}"]
    return command


@dataclass
class Job:
    url: str
    mode: str
    format: str
    quality: str
    folder: str
    playlist: bool = False
    title: str = ""
    id: str = field(default_factory=lambda: uuid4().hex)
    status: str = PENDING
    result: str = ""
    error: str = ""


def load_state():
    defaults = {"settings": {}, "jobs": [], "warning": ""}
    path = DATA / "state.json"
    try:
        contents = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(contents, dict) or not isinstance(contents.get("jobs", []), list):
            raise ValueError("Estrutura da fila inválida")
    except FileNotFoundError:
        return defaults
    except OSError:
        defaults["warning"] = "Não foi possível ler a fila salva."
        return defaults
    except ValueError:
        backup = DATA / f"state.recuperacao-{uuid4().hex[:8]}.json"
        try:
            path.replace(backup)
        except OSError:
            defaults["warning"] = "A fila salva está inválida e não pôde ser movida para recuperação."
        else:
            defaults["warning"] = "Fila inválida. Uma cópia foi guardada na pasta de dados do Sonora."
        return defaults

    settings = contents.get("settings")
    if isinstance(settings, dict):
        defaults["settings"] = {
            key: value for key, value in settings.items()
            if (isinstance(value, bool) if key == "playlist" else isinstance(value, str))
        }
    known_fields = Job.__dataclass_fields__
    used_ids = set()
    for data in contents.get("jobs", []):
        try:
            job = Job(**{key: value for key, value in data.items() if key in known_fields})
            if not all(isinstance(getattr(job, field), str) for field in known_fields if field != "playlist"):
                raise ValueError("Campos inválidos")
            youtube_url(job.url)
            download_flags(job)
        except (ValueError, TypeError, AttributeError):
            defaults["warning"] = "Alguns itens da fila salva eram inválidos."
            continue
        if not job.id or job.id in used_ids:
            job.id = uuid4().hex
        used_ids.add(job.id)
        if job.status not in {DONE, FAILED, STOPPED}:
            job.status = PENDING
        job.playlist = job.playlist is True
        defaults["jobs"].append(job)
    return defaults


def save_state(settings, jobs):
    DATA.mkdir(parents=True, exist_ok=True)
    stream = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=DATA,
                                         suffix=".tmp", delete=False)
    temporary = Path(stream.name)
    try:
        with stream:
            json.dump({"settings": settings, "jobs": [asdict(job) for job in jobs]},
                      stream, ensure_ascii=False, indent=2)
        os.replace(temporary, DATA / "state.json")
    finally:
        temporary.unlink(missing_ok=True)


class Process:
    """Executa um processo por vez, com cancelamento dos subprocessos."""

    def __init__(self):
        self.cancelled = Event()
        self.lock = Lock()
        self.child = None

    def stop(self):
        self.cancelled.set()
        with self.lock:
            child = self.child
            if child is None or child.poll() is not None:
                return
            if os.name == "nt":
                try:
                    subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW, check=False, timeout=8)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                if child.poll() is None:
                    try:
                        child.kill()
                    except OSError:
                        pass
            else:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def check(self):
        if self.cancelled.is_set():
            raise Cancelled()

    def run(self, args, receive=None):
        options = ({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt"
                   else {"start_new_session": True})
        with self.lock:
            self.check()
            child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                                     errors="replace", **options)
            self.child = child

        tail = deque(maxlen=14)
        try:
            with child.stdout:
                for line in child.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    tail.append(line)
                    if receive:
                        receive(line)
            code = child.wait()
        except BaseException:
            self.stop()
            child.wait()
            raise
        finally:
            with self.lock:
                self.child = None
        self.check()
        if code:
            raise RuntimeError("\n".join(tail)[-5000:] or f"Processo encerrado com código {code}.")
        return list(tail)


def inspect(url, playlist, runner):
    document = None

    def collect(line):
        nonlocal document
        if line.startswith("{"):
            document = json.loads(line)

    flags = ["--flat-playlist", "--yes-playlist"] if playlist else ["--no-playlist"]
    runner.run(downloader() + flags + ["--dump-single-json", "--", youtube_url(url)], collect)
    if not document:
        raise RuntimeError("O YouTube não retornou informações para esse link.")
    return document


def playlist_entries(document, fallback):
    if "entries" not in document:
        return [(fallback, document.get("title") or "")]
    entries = []
    for entry in document.get("entries") or []:
        if not entry:
            continue
        identifier = entry.get("id", "")
        if re.fullmatch(r"[\w-]{11}", identifier):
            entries.append((f"https://www.youtube.com/watch?v={identifier}", entry.get("title") or ""))
    if not entries:
        raise RuntimeError("Nenhum vídeo encontrado na playlist.")
    return entries


def has_codec(stream, key):
    return stream.get(key) not in (None, "none", "")


def format_rows(document):
    formats = document.get("formats")
    if not isinstance(formats, list):
        return
    for stream in reversed(formats):
        if not isinstance(stream, dict):
            continue
        identifier = str(stream.get("format_id", ""))
        if stream.get("has_drm") or not re.fullmatch(r"[\w.-]+", identifier):
            continue
        video = has_codec(stream, "vcodec")
        audio = has_codec(stream, "acodec")
        if not (video or audio):
            continue
        size = stream.get("filesize") or stream.get("filesize_approx")
        estimated = not stream.get("filesize")
        rate = (stream.get("tbr") if video else stream.get("abr")) or stream.get("tbr")
        size, rate, duration = (
            value if isinstance(value, (int, float)) and math.isfinite(value) and value > 0 else 0
            for value in (size, rate, document.get("duration"))
        )
        if not size and rate and duration:
            size = rate * 1000 / 8 * duration
        kind = "Vídeo + áudio" if audio and video else "Vídeo + melhor áudio¹" if video else "Áudio"
        resolution = f'{stream["height"]}p' if video and stream.get("height") else "—"
        codecs = " / ".join(str(stream[key]) for key in ("vcodec", "acodec") if has_codec(stream, key))
        yield identifier, kind, stream.get("ext", "—"), resolution, stream.get("fps") or "—", (
            f"{rate:.0f}" if rate else "—"
        ), (f"{'≈ ' if estimated else ''}{size / 1_000_000:.1f} MB" if size else "—"), codecs


def download_flags(job):
    if job.mode == "Faixa nativa":
        identifier = job.quality
        if not re.fullmatch(r"[\w.-]+", identifier):
            raise ValueError("Código de formato inválido.")
        if job.format == "Vídeo + melhor áudio¹":
            return ["-f", f"{identifier}+ba", "--merge-output-format", "mkv"]
        return ["-f", identifier]
    if job.mode == "Áudio":
        if job.format not in AUDIO or job.quality not in {"Máxima", *(str(rate) for rate in RATES)}:
            raise ValueError("Formato ou taxa de áudio inválidos.")
        if job.quality != "Máxima" and job.format in {"FLAC", "WAV", "Original"}:
            raise ValueError("Esse formato usa a qualidade máxima disponível.")
        return ["-f", "ba/b"]
    if job.mode != "Vídeo" or job.format not in VIDEO or job.quality not in {
        "Máxima", *(f"{height}p" for height in HEIGHTS)
    }:
        raise ValueError("Formato ou resolução de vídeo inválidos.")
    cap = "" if job.quality == "Máxima" else f"[height<={int(job.quality.removesuffix('p'))}]"
    if job.format == "WEBM":
        return ["-f", f"bv[ext=webm]{cap}+ba[ext=webm]/b[ext=webm]{cap}",
                "--merge-output-format", "webm"]
    return ["-f", f"bv{cap}+ba/b{cap}", "--merge-output-format", "mkv"]


def convert(job, source, runner, notify):
    ffmpeg, ffprobe = binary_pair()
    target = source.parent / f"convertido.{job.format.lower()}"
    if job.mode == "Faixa nativa":
        return source
    if job.format == "Original":
        lines = runner.run([ffprobe, "-v", "error", "-show_entries",
                            "stream=codec_type,codec_name", "-of", "json=compact=1", str(source)])
        streams = json.loads("\n".join(lines))["streams"]
        audio = next((s for s in streams if s["codec_type"] == "audio"), None)
        if audio is None:
            raise RuntimeError("O arquivo não possui uma faixa de áudio.")
        if len(streams) == 1:
            return source
        extension = {"aac": "m4a", "mp3": "mp3", "opus": "opus", "vorbis": "ogg",
                     "flac": "flac", "alac": "m4a"}.get(audio["codec_name"], "mka")
        target = source.parent / f"original.{extension}"
        notify("Separando áudio", 100, "")
        runner.run([ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                    "-i", str(source), "-map", "0:a:0", "-c:a", "copy", str(target)])
        return target
    if job.mode == "Vídeo" and source.suffix.casefold() == target.suffix and job.format != "MP4":
        return source

    args = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-i", str(source)]
    if job.mode == "Áudio":
        args += ["-map", "0:a:0", "-c:a", ENCODERS[job.format]]
        if job.quality != "Máxima":
            args += ["-b:a", f"{int(job.quality)}k"]
            # Em estéreo, o libvorbis rejeita 32 kbps a 44,1/48 kHz.
            if job.format == "OGG" and int(job.quality) <= 48:
                args += ["-ac", "1", "-ar", "32000"]
        elif job.format == "MP3":
            args += ["-q:a", "0"]
        elif job.format == "M4A":
            args += ["-b:a", "320k"]
        elif job.format == "OPUS":
            args += ["-b:a", "320k"]
        elif job.format == "OGG":
            args += ["-q:a", "10"]
        if job.format == "OPUS":
            args += ["-vbr", "on"]
    else:
        args += ["-map", "0:v:0", "-map", "0:a:0"]
        if job.format == "MP4":
            lines = runner.run([ffprobe, "-v", "error", "-show_entries",
                                "stream=codec_type,codec_name", "-of", "json=compact=1", str(source)])
            codecs = {s["codec_type"]: s["codec_name"] for s in json.loads("\n".join(lines))["streams"]}
            args += ["-c:v", "copy" if codecs.get("video") in {"h264", "hevc", "av1", "vp9"} else "libx264",
                     "-c:a", "copy" if codecs.get("audio") == "aac" else "aac", "-movflags", "+faststart"]
            if codecs.get("audio") != "aac":
                args += ["-b:a", "256k"]
        else:
            args += ["-c", "copy"]
    notify("Convertendo", 100, "")
    runner.run(args + [str(target)])
    return target



def error_hint(details):
    message = details.casefold()
    if any(fragment in message for fragment in ("winerror 112", "errno 28", "no space left", "disk full")):
        return "Libere espaço ou escolha outra pasta de destino."
    if any(fragment in message for fragment in ("winerror 5", "permission denied", "acesso negado")):
        return "Verifique a permissão da pasta e se outro programa está usando o arquivo."
    if "requested format is not available" in message:
        return "Consulte os formatos do link ou escolha outra resolução."
    if any(fragment in message for fragment in ("sign in", "private video", "members-only", "confirm your age")):
        return "O YouTube restringiu o acesso a esse vídeo."
    if any(fragment in message for fragment in ("http error 429", "too many requests")):
        return "O YouTube limitou as consultas. Aguarde e tente novamente."
    if any(fragment in message for fragment in ("timed out", "connection", "certificate", "ssl", "unable to download webpage")):
        return "Verifique a conexão e tente novamente."
    if any(fragment in message for fragment in ("motor de download ausente", "ffmpeg ou ffprobe ausente")):
        return "Execute Preparar.cmd e abra o Sonora novamente."
    return "Confira os detalhes abaixo. Se vários links falharem, execute Atualizar_Motor.cmd."


def publish(source, folder, stem, suffix):
    """Reserva o nome e publica o arquivo completo no mesmo volume."""
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .") or "Mídia"
    if safe.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                                        *(f"LPT{i}" for i in range(1, 10))}:
        safe = "_" + safe
    safe = safe[:110].rstrip(" .")
    index = 1
    while True:
        serial = "" if index == 1 else f" ({index})"
        target = folder / f"{safe}{serial}{suffix}"
        try:
            with target.open("xb"):
                pass
        except FileExistsError:
            index += 1
            continue
        try:
            os.replace(source, target)
        except OSError:
            target.unlink(missing_ok=True)
            raise
        return target


def download(job, runner, notify):
    folder = Path(job.folder).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sonora-", dir=folder) as temporary:
        source = None
        title = job.title

        def receive(line):
            nonlocal source, title
            if line.startswith("SONORA_FILE "):
                source = Path(json.loads(line.removeprefix("SONORA_FILE ")))
            elif line.startswith("SONORA_TITLE "):
                title = json.loads(line.removeprefix("SONORA_TITLE "))
                notify("Preparando", 0, title)
            elif line.startswith("SONORA_PROGRESS "):
                progress, speed, eta = line.removeprefix("SONORA_PROGRESS ").split("|", 2)
                match = re.search(r"[\d.]+", progress)
                percent = float(match.group()) if match else 0
                detail = "  ·  ".join(item.strip() for item in (speed, eta) if item.strip() != "NA")
                notify("Baixando", percent, detail)

        template = str(Path(temporary)).replace("%", "%%") + os.sep + "source.%(ext)s"
        runner.run(downloader() + [
            "--no-playlist", "--no-simulate", "--newline", "--progress", "--progress-delta", "0.35",
            "--no-mtime", "-o", template,
            "--progress-template", "download:SONORA_PROGRESS %(progress._percent_str)s|"
                                   "%(progress._speed_str)s|%(progress._eta_str)s",
            "--print", "before_dl:SONORA_TITLE %(title)j",
            "--print", "after_move:SONORA_FILE %(filepath)j",
            *download_flags(job), "--", youtube_url(job.url),
        ], receive)
        if source is None or not source.is_file() or source.resolve().parent != Path(temporary).resolve():
            raise RuntimeError("O download terminou sem gerar um arquivo de mídia.")
        result = convert(job, source, runner, notify)
        runner.check()
        if job.mode == "Faixa nativa":
            label = f"faixa {job.quality}"
        elif job.mode == "Áudio" and job.quality.isdigit():
            label = f"{job.quality} kbps"
        elif job.mode == "Vídeo" and job.quality != "Máxima":
            label = f"até {job.quality}"
        else:
            label = job.format.lower()
        return title, str(publish(result, folder, f"{title or 'Mídia'} [{label}]", result.suffix))
