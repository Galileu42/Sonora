"""Consulta, validação e instalação de versões do Sonora pelo GitHub Releases."""

from hashlib import sha256
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from zipfile import ZipFile
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parent
VERSION = "1.7.2"
DEFAULT_REPO = "Galileu42/Sonora"
ASSET = "Sonora_Windows.zip"
MAX_BYTES = 20 * 1024 * 1024
FILES = {
    "Abrir_Sonora.cmd", "Atualizar_Motor.cmd", "Criar_Atalhos.cmd", "Criar_Atalhos.ps1",
    "LEIA-ME.txt", "Preparar.cmd", "Preparar.ps1", "engine.py", "sonora.py", "updater.py", "Sonora.exe",
    "assets/marca.png", "assets/sonora.ico", "assets/sonora.png",
}


def version_tuple(tag):
    if not isinstance(tag, str) or not re.fullmatch(r"v?\d{1,6}\.\d{1,6}\.\d{1,6}", tag):
        raise ValueError("Use uma versão estável, como v1.2.0.")
    return tuple(int(part) for part in tag.lstrip("v").split("."))


def normalize_repo(value):
    repo = value.strip().rstrip("/")
    if repo.startswith("https://github.com/"):
        repo = repo.removeprefix("https://github.com/")
    repo = repo.removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", repo):
        raise ValueError("Informe dono/repositorio ou o endereço HTTPS do GitHub.")
    if repo.split("/")[1] in {".", ".."}:
        raise ValueError("Informe um repositório válido do GitHub.")
    return repo


def describe_error(error):
    if isinstance(error, HTTPError):
        if error.code == 404:
            return "Repositório sem uma release pública disponível."
        if error.code in {403, 429}:
            return "O GitHub limitou a consulta. Tente novamente mais tarde."
    if isinstance(error, (URLError, TimeoutError)):
        return "Falha de conexão com o GitHub. Tente novamente."
    message = str(error).strip() or type(error).__name__
    return f"Atualização indisponível · {message[:180]}"


def discard(staging):
    shutil.rmtree(staging, ignore_errors=True)


def latest_release(repo):
    endpoint = f"https://api.github.com/repos/{repo}/releases/latest"
    request = Request(endpoint, headers={"Accept": "application/vnd.github+json", "User-Agent": f"Sonora/{VERSION}"})
    with urlopen(request, timeout=15) as response:
        if urlsplit(response.geturl()).netloc != "api.github.com":
            raise ValueError("Resposta inesperada para a consulta ao GitHub.")
        release = json.loads(response.read(2 * 1024 * 1024))
    version = release["tag_name"]
    if release.get("draft") or release.get("prerelease") or version_tuple(version) <= version_tuple(VERSION):
        return None
    for asset in release.get("assets", []):
        if asset.get("name") != ASSET or asset.get("state") != "uploaded":
            continue
        url = urlsplit(asset["browser_download_url"])
        expected = f"/{repo}/releases/download/{version}/{ASSET}"
        digest = asset.get("digest") or ""
        size = asset.get("size")
        if (url.scheme != "https" or url.netloc != "github.com" or url.path.casefold() != expected.casefold()
                or url.query or url.fragment or not re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest)
                or not isinstance(size, int) or not 0 < size <= MAX_BYTES):
            raise ValueError("O GitHub retornou um pacote sem endereço, tamanho ou SHA-256 válido.")
        return version, url.geturl(), size, digest.split(":", 1)[1].lower()
    raise ValueError(f"A versão {version} precisa incluir o arquivo {ASSET} em GitHub Releases.")


def extract_package(archive, workspace, version):
    found = set()
    with ZipFile(archive) as package:
        for entry in package.infolist():
            path = PurePosixPath(entry.filename)
            if path.parts[:1] != ("Sonora",) or ".." in path.parts or "\\" in entry.filename:
                raise ValueError("Estrutura inesperada no arquivo de atualização.")
            relative = path.relative_to("Sonora").as_posix()
            if relative not in FILES:
                continue
            if relative in found or entry.is_dir() or entry.file_size > MAX_BYTES:
                raise ValueError("Há arquivos inválidos ou duplicados no pacote de atualização.")
            found.add(relative)
        if found != FILES or sum(package.getinfo(f"Sonora/{name}").file_size for name in found) > MAX_BYTES:
            raise ValueError("O pacote da atualização está incompleto ou é grande demais.")
        code = package.read("Sonora/updater.py")
        expected = f'VERSION = "{version.lstrip("v")}"'.encode()
        if expected not in code.splitlines():
            raise ValueError("A versão interna do pacote difere da publicação no GitHub.")
        for name in sorted(found):
            destination = workspace / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(package.read(f"Sonora/{name}"))


def stage(repo, on_download=None):
    release = latest_release(normalize_repo(repo))
    if release is None:
        return None
    version, url, size, checksum = release
    if on_download:
        on_download(version)
    staging = Path(tempfile.mkdtemp(prefix=".sonora-update-", dir=ROOT))
    try:
        package = staging / "release.zip"
        digest = sha256()
        total = 0
        request = Request(url, headers={"User-Agent": f"Sonora/{VERSION}"})
        with urlopen(request, timeout=30) as response, package.open("wb") as output:
            final = urlsplit(response.geturl())
            if final.scheme != "https" or final.hostname not in {
                "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com",
            }:
                raise ValueError("O pacote redirecionou para fora do GitHub.")
            deadline = time.monotonic() + 60
            for chunk in iter(lambda: response.read(128 * 1024), b""):
                if time.monotonic() >= deadline:
                    raise TimeoutError("O download da atualização excedeu o tempo limite.")
                total += len(chunk)
                if total > size:
                    raise ValueError("O tamanho do arquivo difere do informado pelo GitHub.")
                digest.update(chunk)
                output.write(chunk)
        if total != size or digest.hexdigest() != checksum:
            raise ValueError("O pacote está incompleto ou a verificação SHA-256 falhou.")
        extract_package(package, staging / "payload", version)
        package.unlink()
        return version, staging
    except BaseException:
        discard(staging)
        raise


def replace_files(root, staging):
    backup = staging / "backup"
    applied = []
    try:
        # Install the updater last, after the rest of the application.
        for name in sorted(FILES, key=lambda item: (item == "updater.py", item)):
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            previous = backup / name
            existed = destination.is_file()
            if existed:
                previous.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, previous)
            source = staging / "payload" / name
            for attempt in range(20):
                try:
                    os.replace(source, destination)
                    break
                except PermissionError:
                    if name != "Sonora.exe" or attempt == 19:
                        raise
                    # The window has closed, but Windows can still be releasing the image.
                    time.sleep(0.25)
            applied.append((destination, previous, existed))
    except OSError:
        for destination, previous, existed in reversed(applied):
            if existed:
                os.replace(previous, destination)
            else:
                destination.unlink(missing_ok=True)
        raise


def install(staging, lock_path):
    root = staging.parent
    deadline = time.monotonic() + 30
    with lock_path.open("a+b") as lock:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Feche todos os processos do Sonora antes de atualizar.")
                time.sleep(0.25)
        # A simultaneous launcher or installer may have already installed a newer version.
        def installed_version(path):
            code = path.read_text(encoding="utf-8")
            match = re.search(r'^VERSION = "([^"]+)"$', code, re.MULTILINE)
            if not match:
                raise ValueError("O pacote não informa uma versão válida.")
            return version_tuple(match[1])

        if installed_version(staging / "payload" / "updater.py") > installed_version(root / "updater.py"):
            replace_files(root, staging)


def launch(staging, lock_path, restart=False):
    # Run a copy so Windows can replace updater.py along with the app.
    helper = staging / "install.py"
    shutil.copyfile(__file__, helper)
    python = ROOT / ".venv" / "Scripts" / "python.exe" if os.name == "nt" else sys.executable
    args = [str(python), str(helper), "--install", str(staging), str(lock_path)]
    if restart:
        args.append("--restart")
    subprocess.Popen(args,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                     start_new_session=os.name != "nt")


def install_from_helper(staging, lock, restart):
    root = staging.parent
    try:
        install(staging, lock)
    except Exception as error:
        (lock.parent / "update_error.txt").write_text(str(error), encoding="utf-8")
        if not (staging / "backup").is_dir():
            discard(staging)
    else:
        discard(staging)
    if restart:
        executable = [str(root / "Sonora.exe")] if os.name == "nt" else [sys.executable, str(root / "sonora.py")]
        subprocess.Popen(executable, cwd=root, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__" and len(sys.argv) in {4, 5} and sys.argv[1] == "--install":
    staging, lock = (Path(argument) for argument in sys.argv[2:4])
    install_from_helper(staging, lock, sys.argv[4:] == ["--restart"])
