#!/usr/bin/env python3
"""Standalone tools - one small web app that releases and installs standalone Python programs.
  /          Home        choose a tool
  /makezip   Make Zip    build dist/<name>-<version>.zip (or dist/<name>.zip) from the project
  /install   Install     copy the program to an install folder, install system packages, create its venv
  /settings  Settings    the folder project browsing starts in, the preferred port and where to listen
  /readme    Instructions on use

A project is a folder holding a code folder with the program in it:
  <project>/README.md            (optional)
  <project>/code/<main>.py       the program; it may set its version, e.g. progVersion = '1.0.0'
  <project>/code/requirements.txt  what pip installs into the venv (or <project>/requirements.txt)
The project's name is its folder name. Nothing needs adding to the project: this app does the work, and
the only thing it writes into the project is the zip in dist/.

The zip unzips to a <name>/ folder holding README.md, code/ and an install.py made by this app
(see INSTALL_TEMPLATE), so the release can be installed on a computer without this app.
Install here runs that same install.py, from a temporary folder, so both always install the same way.

Nothing is installed system-wide (no apt, no sudo): the venv is created and requirements.txt is installed into it
with the venv's own pip, which also works where the system Python is "externally managed".
Each project has options, kept in the settings file: the main program, and whether its venv can see
Python packages already installed on the system.

Setup (Linux, e.g. Raspberry Pi OS):  sudo apt install python3-flask
Setup (Windows 10 or later):          install Python 3.8+, then: pip install flask
         (or: pip install -r requirements.txt)
Run:     python3 standalone_tools.py       (Windows: python standalone_tools.py)
Keep the web folder (the pages' HTML, CSS and JS) next to this script.
Open:    the address printed at start-up: this computer's network address (or 127.0.0.1 when Settings says
         "This computer only"), on the preferred port from the Settings page, or else the first free port from 17900.
         The first time (no settings file yet) the browser opens at /readme instead of Home.

The app stops by itself (stopping any running job) once every page of it has been closed: each open page sends
/api/alive every few seconds and /api/bye when it closes (see the "open pages" section).

The settings, the recent projects and each project's options are stored together in
.standalone_tools.json, in the same folder as this script.
"""
import json
import logging
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser
import zipfile
from glob import glob

from flask import Flask, Response, jsonify, request, send_from_directory

PLATFORM = platform.system()          # "Linux", "Windows", ...
IS_WINDOWS = PLATFORM == "Windows"    # everything else is handled like Linux
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))   # where this script is installed
# Until it is set on the Settings page, project browsing starts in the user's home folder
DEFAULT_PROJECTS = os.path.expanduser("~")
# Who can open this tool's page: "network" (any computer on the network) or "local" (this computer only)
DEFAULT_LISTEN = "network"
START_PORT = 17900   # plugin_tools searches from 17800, so the two apps can run side by side
# The address this tool listens on is worked out at start-up by validate_port() (see main())
HOST = "127.0.0.1"
PORT = 0
SETTINGS_NAME = ".standalone_tools.json"
SETTINGS_FILE = os.path.join(SCRIPT_DIR, SETTINGS_NAME)
RECENT_MAX = 8   # most recent projects remembered
CODE_DIR = "code"
README = "README.md"
# Never part of a release
SKIP_DIRS = ("__pycache__", "venv")
SKIP_SUFFIXES = (".pyc",)
# Project options until they are changed on a tool page
DEFAULT_SITE_PACKAGES = True
# Where the project's requirements.txt can be, in the order looked at (relative to the project)
REQUIREMENTS = (CODE_DIR + "/requirements.txt", "requirements.txt")
# The program's version, if it sets one: progVersion = '1.0.0' (also __version__ / VERSION / version)
VERSION_LINE = re.compile(r"""^\s*(?:progVersion|__version__|VERSION|version)\s*=\s*['"]([^'"\s]+)['"]""", re.M)
VERSION_OK = re.compile(r"[0-9A-Za-z._+-]+")   # it becomes part of the zip's file name

app = Flask(__name__)
logger = logging.getLogger("standalone_tools")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def force_quit(code=1):
    """Stop the app straight away (used when start-up cannot continue)."""
    logger.critical("Exiting")
    sys.exit(code)


def port_in_use(ip_address, port):
    #  A successful connection means something is already listening there
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex((ip_address, port)) == 0


def validate_port(port=0, local=False, start_port=START_PORT, max_tries=100):
    #  Get the local ip address (this computer only: the loopback address, which needs no network)
    this_ip_address = '127.0.0.1' if local else ''
    if not local:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('10.255.255.255', 1))  # doesn't even have to be reachable
            this_ip_address = s.getsockname()[0]
        except Exception as e:
            logger.critical(f'''Unknown error trying to get the local IP address''')
            logger.critical(f'''{e}''')
            force_quit(1)
        finally:
            s.close()

    if port:
        #  A port was provided - check that it is available
        if port_in_use(this_ip_address, port):
            logger.warning(f'''Port {port} is already in use - falling back to searching from {start_port}''')
            port = 0
    else:
        logger.info(f'''No port number was provided - searching for a free port starting at {start_port}''')

    if not port:
        #  No usable port yet - search for one starting at start_port
        for candidate in range(start_port, start_port + max_tries):
            if not port_in_use(this_ip_address, candidate):
                port = candidate
                break
        else:
            logger.critical(f'''No free port found between {start_port} and {start_port + max_tries - 1}''')
            force_quit(1)

    logger.info(f'''IP address {this_ip_address} with port {port} is available''')
    return this_ip_address, port


# ---------- running and stopping programs (Linux and Windows) ----------
def popen(cmd, cwd=None):
    """Start cmd with its output piped back and no input. It gets its own process group (Linux: session)
    so that Stop can end it together with everything it starts (pip ...)."""
    extra = {}
    if IS_WINDOWS:
        extra["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    else:
        extra["start_new_session"] = True
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    return subprocess.Popen(
        cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        bufsize=1, **extra)


def kill_tree(proc, force_after=None):
    """End proc and everything it started. With force_after (seconds), make sure it is really gone."""
    if IS_WINDOWS:
        # taskkill /T ends the whole tree. /F is needed: console programs ignore a polite close request.
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            try:
                proc.kill()
            except OSError:
                pass
        if force_after:
            try:
                proc.wait(timeout=force_after)
            except subprocess.TimeoutExpired:
                pass
        return
    pgid = proc.pid  # start_new_session=True makes the group id equal the pid
    try:
        os.killpg(pgid, signal.SIGTERM)
        if force_after:
            for _ in range(int(force_after * 10)):
                try:
                    os.killpg(pgid, 0)
                except ProcessLookupError:
                    return
                time.sleep(0.1)
            os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


# ---------- background jobs ----------
class Job:
    """One background job whose output the page polls. Each tool has its own Job, so they can run at the same time."""

    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.run = 0
        self.lines = []
        self.stopping = False
        self.busy = False

    def begin(self):
        """Claim the job. Returns a fresh list for the output, or None if already running."""
        with self.lock:
            if self.busy:
                return None
            self.lines = []
            self.proc = None
            self.run += 1
            self.stopping = False
            self.busy = True
            return self.lines

    def step(self, lines, cmd, cwd, title=None):
        """Run one command, streaming its output. Returns the exit code, or None if stopped."""
        if title:
            lines.append(f"=== {title} ===")
        lines.append("$ " + " ".join(cmd))
        with self.lock:
            if self.stopping:
                return None
            try:
                proc = popen(cmd, cwd)
            except OSError as e:
                lines.append(f"Could not start {cmd[0]}: {e}")
                return 127
            self.proc = proc
        for line in proc.stdout:
            lines.append(ANSI.sub("", line.rstrip("\n")))
        code = proc.wait()
        return None if self.stopping else code

    def terminate(self, force_after=None):
        """Stop the current command and everything it started."""
        with self.lock:
            self.stopping = True
            p = self.proc
        if p is None or p.poll() is not None:
            return
        kill_tree(p, force_after)

    def view(self, n, run):
        if run != self.run:
            n = 0  # a new run started: send its output from the top
        lines = self.lines
        return {"run": self.run, "total": len(lines), "lines": lines[n:], "running": self.busy}


zip_job = Job()       # Make Zip
install_job = Job()   # Install
JOBS = (zip_job, install_job)


def shut_down(reason):
    """Stop every running job, then end this app."""
    logger.info(f"{reason} - stopping")
    for j in JOBS:
        j.terminate(force_after=5)
    os._exit(0)


# ---------- open pages: the app stops once the last one has gone ----------
PAGE_GRACE = 10     # seconds to wait after the last page closed: a reload or a link opens the next page well within this
PAGE_TIMEOUT = 90   # a page not heard from for this long counts as closed. Browsers slow the timers of a
                    # background tab to about once a minute, so this must be well above that
pages = {}          # page id -> when it was last heard from
pages_lock = threading.Lock()
page_seen = False   # until a page has opened, the app keeps waiting (e.g. on a Pi without a screen)


def watch_pages():
    """Stop the app once every page has closed (or gone quiet for PAGE_TIMEOUT)."""
    empty_since = None
    while True:
        time.sleep(2)
        now = time.monotonic()
        with pages_lock:
            for page, last in list(pages.items()):
                if now - last > PAGE_TIMEOUT:
                    del pages[page]
            open_pages = len(pages)
        if not page_seen or open_pages:
            empty_since = None
        elif empty_since is None:
            empty_since = now
        elif now - empty_since > PAGE_GRACE:
            shut_down("Every page has been closed")


# ---------- settings file ----------
save_lock = threading.Lock()


def load_store():
    """Settings file layout: {"format": 1, "config": {...}, "project": "<last project>", "recent": [...],
    "projects": {project: {options}}}. A missing or unrecognised file counts as empty."""
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict) or data.get("format") != 1:
        data = {"format": 1}
    if not isinstance(data.get("config"), dict):
        data["config"] = {}
    if not isinstance(data.get("project"), str):
        data["project"] = ""
    if not isinstance(data.get("recent"), list):
        data["recent"] = []
    data["recent"] = [x for x in data["recent"] if isinstance(x, str)]
    if not isinstance(data.get("projects"), dict):
        data["projects"] = {}
    return data


def write_store(data):
    """Write the settings file (call with save_lock held). Returns an error message, or None."""
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE) or ".", exist_ok=True)
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, SETTINGS_FILE)  # atomic, so a crash can't leave half a file
    except OSError as e:
        return str(e)
    return None


def projects_dir(data=None):
    """Folder the project chooser starts in when no project has been chosen yet."""
    v = (data or load_store())["config"].get("projects_dir")
    return v if isinstance(v, str) and v.strip() else DEFAULT_PROJECTS


def listen(data=None):
    """"local" (this computer only) or "network". Only read at start-up."""
    v = (data or load_store())["config"].get("listen")
    return v if v in ("local", "network") else DEFAULT_LISTEN


def preferred_port(data=None):
    """Port this tool's web page should use (0 = no preference: the first free port from START_PORT).
    Only read at start-up."""
    v = (data or load_store())["config"].get("preferred_port", 0)
    ok = isinstance(v, int) and not isinstance(v, bool) and (v == 0 or 1024 <= v <= 65535)
    return v if ok else 0


def remember_project(project, **options):
    """Make project the last one used (and the most recent), and store any options given for it.
    Returns an error message, or None."""
    with save_lock:
        data = load_store()
        data["project"] = project
        data["recent"] = ([project] + [x for x in data["recent"] if x != project])[:RECENT_MAX]
        if options:
            saved = data["projects"].get(project)
            saved = saved if isinstance(saved, dict) else {}
            saved.update(options)
            data["projects"][project] = saved
        return write_store(data)


# ---------- folders and projects ----------
def natural(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def subdirs(path):
    """Sub-folder names of path, naturally sorted (v3.6 before v3.10). Hidden folders are left out."""
    try:
        names = [d for d in os.listdir(path)
                 if os.path.isdir(os.path.join(path, d)) and not d.startswith(".")]
    except OSError:
        return []
    return sorted(names, key=natural)


def full_path(raw):
    """A typed folder as a full, normalised path, or None if it is not a full path."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = os.path.expanduser(raw.strip())
    return os.path.normpath(path) if os.path.isabs(path) else None


def programs(project):
    """The .py files at the top of the project's code folder: the candidates for its main program."""
    try:
        names = os.listdir(os.path.join(project, CODE_DIR))
    except OSError:
        return []
    return sorted((n for n in names if n.endswith(".py") and os.path.isfile(os.path.join(project, CODE_DIR, n))),
                  key=natural)


def is_project(folder):
    return bool(programs(folder))


def options_for(project, data=None):
    """The project's options: saved ones where valid, defaults for the rest."""
    data = data or load_store()
    saved = data["projects"].get(project)
    saved = saved if isinstance(saved, dict) else {}
    found = programs(project)
    main = saved.get("main")
    if main not in found:
        name = os.path.basename(project)
        main = next((p for p in found if p.lower() == (name + ".py").lower()), found[0] if len(found) == 1 else "")

    site = saved.get("site_packages")
    target = saved.get("install_target")
    return {"main": main,
            "site_packages": site if isinstance(site, bool) else DEFAULT_SITE_PACKAGES,
            "install_target": target if isinstance(target, str) else ""}


def requirements_file(project):
    """The project's requirements.txt, relative to the project ("code/requirements.txt" or "requirements.txt"), or ""."""
    return next((r for r in REQUIREMENTS if os.path.isfile(os.path.join(project, r))), "")


def program_version(project, main):
    """The version set in the main program, or None."""
    if not main:
        return None
    try:
        with open(os.path.join(project, CODE_DIR, main), encoding="utf-8", errors="replace") as f:
            m = VERSION_LINE.search(f.read())
    except OSError:
        return None
    return m.group(1) if m and VERSION_OK.fullmatch(m.group(1)) else None


def dist_zips(project):
    """The zip files in the project's dist folder, newest first."""
    out = []
    for f in glob(os.path.join(project, "dist", "*.zip")):
        try:
            st = os.stat(f)
        except OSError:
            continue
        out.append({"name": os.path.basename(f), "size": st.st_size, "mtime": st.st_mtime,
                    "when": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))})
    return sorted(out, key=lambda z: z["mtime"], reverse=True)


def default_target(project):
    return os.path.join(os.path.expanduser("~"), os.path.basename(project))


def project_view(path, data=None):
    """What the pages need to know about a project folder."""
    found = programs(path)
    view = {"path": path, "name": os.path.basename(path), "exists": True, "is_project": bool(found)}
    if found:
        opts = options_for(path, data)
        view.update(programs=found, options=opts, version=program_version(path, opts["main"]),
                    has_readme=os.path.isfile(os.path.join(path, README)),
                    requirements=requirements_file(path),
                    zips=dist_zips(path), default_target=default_target(path))
    return view


def check_project(raw):
    """(path, options, None) for a project with its main program chosen, else (None, None, error message)."""
    path = full_path(raw)
    if path is None:
        return None, None, "Choose a project: enter or browse to the full path of its folder"
    if not os.path.isdir(path):
        return None, None, f"'{path}' is not an existing folder"
    if not is_project(path):
        return None, None, f"'{path}' has no {CODE_DIR} folder with a .py program in it"
    if not requirements_file(path):
        return None, None, f"'{path}' has no requirements.txt (in {CODE_DIR} or the project folder): it lists what pip installs into the venv"
    opts = options_for(path)
    if not opts["main"]:
        return None, None, "Choose the main program in the project options"
    return path, opts, None


# ---------- the install.py that goes into each release ----------
# Filled in by make_install_py(). Its job is that of the original scanCam install.py, with the project's
# name, main program and packages filled in. It also takes the install folder and the folder holding the
# program as arguments, which is how this app's Install runs it (from a temporary folder, on the project).
INSTALL_TEMPLATE = r'''#!/usr/bin/env python3
"""
One-time setup for __NAME__: asks for an install directory, copies the
program there, then creates its Python venv and installs requirements.txt into it with pip.
Nothing is installed system-wide, so no sudo is needed.

Run from the unzipped folder with: python3 install.py  (on Windows: py install.py)
The install directory can also be given straight away: python3 install.py /home/pi/__NAME__
Running it again updates the program files and recreates the venv.
(Made by standalone_tools.py.)
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

NAME = __NAME_R__
MAIN = __MAIN_R__            # the program, in the code folder
REQUIREMENTS = __REQ_R__     # what pip installs into the venv
SYSTEM_SITE_PACKAGES = __SITE_R__   # whether the venv can also use Python packages already installed on the system

IS_WINDOWS = sys.platform == 'win32'

here = Path(__file__).resolve().parent
default_target = Path.home() / NAME
# Copied into the install directory; the venv and launcher are created there.
program_files = ['README.md', 'code', 'requirements.txt']

if IS_WINDOWS:
    launcher_name = 'run.bat'
    launcher_script = ('@echo off\n'
                       f'rem Start {NAME} using its venv (recreate it with install.py).\n'
                       'cd /d "%~dp0"\n'
                       f'venv\\Scripts\\python.exe -u code\\{MAIN} %*\n')
else:
    launcher_name = 'run.sh'
    launcher_script = ('#!/bin/bash\n'
                       f'# Start {NAME} using its venv (recreate it with python3 install.py).\n'
                       'cd "$(dirname "$0")"\n'
                       f'exec venv/bin/python -u code/{MAIN} "$@"\n')


def ask_target() -> Path:
    try:
        answer = input(f"Enter the directory to install {NAME} into [{default_target}]: ").strip()
    except EOFError:
        # No terminal to answer from (e.g. piped input), so take the default.
        answer = ''
    return Path(answer).expanduser().resolve() if answer else default_target


def copy_program(source: Path, target: Path):
    target.mkdir(parents=True, exist_ok=True)
    if target != source:
        print(f"Copying {NAME} into {target}")
        for name in program_files:
            path = source / name
            if path.is_dir():
                shutil.copytree(path, target / name, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'venv'))
            elif path.is_file():
                shutil.copy2(path, target / name)
    launcher = target / launcher_name
    launcher.write_text(launcher_script)
    launcher.chmod(0o755)


def create_venv(target: Path):
    # Use the base Python, since sys.executable may be inside the venv being deleted.
    venv = target / 'venv'
    if IS_WINDOWS:
        python = Path(sys.base_prefix) / 'python.exe'
        venv_python = venv / 'Scripts' / 'python.exe'
        venv_options = []
    else:
        python = Path(sys.base_prefix) / 'bin' / 'python3'
        venv_python = venv / 'bin' / 'python'
        venv_options = ['--system-site-packages'] if SYSTEM_SITE_PACKAGES else []
    shutil.rmtree(venv, ignore_errors=True)
    print(f"Creating the venv in {venv}")
    if subprocess.run([str(python), '-m', 'venv', *venv_options, str(venv)]).returncode != 0:
        # Debian / Raspberry Pi OS leave venv's pip out of the base Python package
        sys.exit("Could not create the venv. On Debian or Raspberry Pi OS the venv module needs the python3-venv "
                 "package, which the system administrator installs with: sudo apt install python3-venv")
    # The venv's own pip, so this works where the system Python is "externally managed"
    subprocess.run([str(venv_python), '-m', 'pip', 'install', '-r', str(target / REQUIREMENTS)], check=True)
    print('venv ready')


def main():
    parser = argparse.ArgumentParser(description=f'Install {NAME}')
    parser.add_argument('target', nargs='?', help=f'the directory to install into (asked for when left out)')
    parser.add_argument('--source', help='the folder holding README.md and code (default: the folder this script is in)')
    args = parser.parse_args()
    source = Path(args.source).expanduser().resolve() if args.source else here
    target = Path(args.target).expanduser().resolve() if args.target else ask_target()
    try:
        copy_program(source, target)
        create_venv(target)
    except subprocess.CalledProcessError as e:
        sys.exit(f"Install failed: {' '.join(e.cmd)} exited with {e.returncode}")
    except OSError as e:
        sys.exit(f"Install failed: {e}")
    print()
    print(f"{NAME} is installed in {target}. Start it with: {target / launcher_name}")


if __name__ == '__main__':
    main()
'''


def make_install_py(name, opts, requirements):
    """The install.py for a project, with its name, options and requirements.txt (relative path) filled in."""
    values = {"__NAME_R__": repr(name), "__MAIN_R__": repr(opts["main"]), "__REQ_R__": repr(requirements),
              "__SITE_R__": repr(opts["site_packages"])}
    text = INSTALL_TEMPLATE
    for key, value in values.items():
        text = text.replace(key, value)
    return text.replace("__NAME__", name)


# ---------- Make Zip: the job ----------
def release_files(project):
    """(path on disk, path inside the zip below <name>/) for README.md, requirements.txt and everything in code."""
    for top in (README, "requirements.txt"):
        path = os.path.join(project, top)
        if os.path.isfile(path):
            yield path, top
    code_dir = os.path.join(project, CODE_DIR)
    for dirpath, dirnames, filenames in os.walk(code_dir):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if not name.endswith(SKIP_SUFFIXES):
                path = os.path.join(dirpath, name)
                yield path, os.path.relpath(path, project).replace(os.sep, "/")


def run_zip_job(lines, project, opts):
    job = zip_job
    ok = False
    name = os.path.basename(project)
    out = None
    try:
        version = program_version(project, opts["main"])
        lines.append(f"=== Make zip of {name}" + (f" version {version} ===" if version else " (no version set) ==="))
        out = os.path.join(project, "dist", f"{name}-{version}.zip" if version else f"{name}.zip")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        count = 0
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as z:
            for path, rel in release_files(project):
                if job.stopping:
                    raise InterruptedError
                z.write(path, f"{name}/{rel}")
                lines.append(f"  adding: {name}/{rel}")
                count += 1
            z.writestr(f"{name}/install.py", make_install_py(name, opts, requirements_file(project)))
            lines.append(f"  adding: {name}/install.py   (made by this app for {CODE_DIR}/{opts['main']})")
        st = os.stat(out)
        lines.append("")
        lines.append("Resulting ZIP file")
        lines.append(f"{st.st_size:>10} bytes  {time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime))}  {out}")
        ok = True
    except InterruptedError:
        pass
    except Exception as e:
        lines.append(f"Error: {e}")
    finally:
        if not ok and out and os.path.exists(out):
            os.remove(out)   # never leave a partial zip behind
        if job.stopping:
            lines.append("--- stopped ---")
        else:
            lines.append("--- finished OK ---" if ok else "--- FAILED ---")
        job.busy = False


# ---------- Install: the job ----------
def run_install_job(lines, project, opts, target):
    job = install_job
    code = None
    name = os.path.basename(project)
    try:
        with tempfile.TemporaryDirectory(prefix="standalone-") as tmp:
            script = os.path.join(tmp, "install.py")
            with open(script, "w", encoding="utf-8") as f:
                f.write(make_install_py(name, opts, requirements_file(project)))
            code = job.step(lines, [sys.executable, "-u", script, "--source", project, target], project,
                            title=f"Install {name} into {target}")
    except Exception as e:
        lines.append(f"Error: {e}")
    finally:
        if job.stopping:
            lines.append("--- stopped ---")
        else:
            lines.append("--- finished OK ---" if code == 0 else f"--- FAILED (exit code {code}) ---")
        job.busy = False


# ---------- routes: shared ----------
@app.before_request
def same_origin_only():
    """Refuse a POST sent by another web page. Browsers add Origin to every POST, so without this any site
    open in the same browser could start installs or shut this app down. Tools such as curl send no Origin."""
    if request.method != "POST":
        return None
    origin = request.headers.get("Origin")
    if origin is not None and urllib.parse.urlsplit(origin).netloc != request.host:
        return jsonify(error="Refused: this request came from another web page"), 403
    return None


def add_job_routes(prefix, name, job):
    """Stop and log endpoints for one tool."""
    def stop():
        if job.busy:
            job.terminate()
        return jsonify(ok=True)

    def log():
        return jsonify(job.view(int(request.args.get("from", 0)), int(request.args.get("run", 0))))

    app.add_url_rule(f"{prefix}/api/stop", f"{name}_stop", stop, methods=["POST"])
    app.add_url_rule(f"{prefix}/api/log", f"{name}_log", log, methods=["GET"])


add_job_routes("/makezip", "zip", zip_job)
add_job_routes("/install", "install", install_job)


@app.get("/api/status")
def api_status():
    return jsonify(makezip=zip_job.busy, install=install_job.busy)


@app.post("/api/exit")
def api_exit():
    """Stop every running job, then shut down this web server."""
    threading.Timer(0.5, shut_down, args=("Exit pressed",)).start()  # let this response reach the browser first
    return jsonify(ok=True)


def page_id():
    """The page id sent by common.js: JSON from fetch, plain text from navigator.sendBeacon."""
    try:
        page = json.loads(request.get_data(as_text=True) or "{}").get("page")
    except (ValueError, AttributeError):
        return None
    return page if isinstance(page, str) and 0 < len(page) <= 64 else None


@app.post("/api/alive")
def api_alive():
    """An open page says it is still there."""
    global page_seen
    page = page_id()
    if page:
        with pages_lock:
            pages[page] = time.monotonic()
            page_seen = True
    return jsonify(ok=True)


@app.post("/api/bye")
def api_bye():
    """A page is being closed (or left for another page)."""
    page = page_id()
    if page:
        with pages_lock:
            pages.pop(page, None)
    return jsonify(ok=True)


@app.get("/api/browse")
def api_browse():
    """Sub-folders of a folder, each marked if it is a project. With no path: the folder of
    the last project used, else the projects folder from Settings."""
    data = load_store()
    raw = request.args.get("path", "")
    path = full_path(raw) if raw else None
    if path is None or not os.path.isdir(path):
        last = data["project"]
        path = os.path.dirname(last) if last and os.path.isdir(last) else projects_dir(data)
        if not os.path.isdir(path):
            path = DEFAULT_PROJECTS
    dirs = [{"name": d, "path": os.path.join(path, d), "is_project": is_project(os.path.join(path, d))}
            for d in subdirs(path)]
    parent = os.path.dirname(path)
    return jsonify(path=path, parent=parent if parent != path else "", dirs=dirs, is_project=is_project(path))


@app.get("/api/project")
def api_project():
    """The last project used and the recent ones (no path), or details of the folder in `path`."""
    data = load_store()
    raw = request.args.get("path")
    if raw is None:
        return jsonify(project=data["project"], recent=[x for x in data["recent"] if os.path.isdir(x)])
    path = full_path(raw)
    if path is None:
        return jsonify(exists=False, error="Enter the full path of a project folder (~ is fine)")
    if not os.path.isdir(path):
        return jsonify(exists=False, path=path, error=f"'{path}' is not an existing folder")
    return jsonify(project_view(path, data))


@app.post("/api/project")
def api_project_select():
    """Remember the project chosen in a tool, so the other tool (and next time) starts with it."""
    path = full_path((request.get_json(silent=True) or {}).get("path", ""))
    if path is None or not is_project(path):
        return jsonify(error="Not a project folder"), 400
    err = remember_project(path)
    return (jsonify(error=f"Could not save the settings file: {err}"), 500) if err else jsonify(ok=True)


@app.post("/api/project/options")
def api_project_options():
    """Save a project's options. Returns the project's details."""
    d = request.get_json(silent=True) or {}
    path = full_path(d.get("path", ""))
    if path is None or not is_project(path):
        return jsonify(error="Not a project folder"), 400
    main = d.get("main", "")
    if main not in programs(path):
        return jsonify(error=f"Main program: choose one of the .py files in {CODE_DIR}"), 400
    site = d.get("site_packages")
    if not isinstance(site, bool):
        return jsonify(error="System site packages: invalid value"), 400
    err = remember_project(path, main=main, site_packages=site)
    if err:
        return jsonify(error=f"Could not save the settings file: {err}"), 500
    return jsonify(project_view(path))


@app.get("/api/project/installpy")
def api_install_py():
    """The install.py that Make Zip puts into this project's zip, to look at."""
    path = full_path(request.args.get("path", ""))
    if path is None or not is_project(path):
        return Response("Not a project folder", 404, mimetype="text/plain")
    opts = options_for(path)
    if not opts["main"]:
        return Response("Choose the main program first", 400, mimetype="text/plain")
    return Response(make_install_py(os.path.basename(path), opts, requirements_file(path) or "requirements.txt"), mimetype="text/plain")


def config_view():
    data = load_store()
    p = projects_dir(data)
    return {
        "projects_dir": p, "projects_dir_found": os.path.isdir(p),
        "defaults": {"projects_dir": DEFAULT_PROJECTS, "listen": DEFAULT_LISTEN, "start_port": START_PORT},
        "preferred_port": preferred_port(data),
        "listen": listen(data),
        "url": f"http://{HOST}:{PORT}/" if PORT else "",   # where this tool is listening right now
        "python": sys.executable,
        "settings_file": SETTINGS_FILE,
        "first_run": not os.path.isfile(SETTINGS_FILE),
    }


@app.get("/api/config")
def api_config_get():
    return jsonify(config_view())


@app.post("/api/config")
def api_config_set():
    d = request.get_json(silent=True) or {}
    new = {}
    raw = d.get("projects_dir", "")
    if not isinstance(raw, str):
        return jsonify(error="Projects folder: invalid value"), 400
    if raw.strip():   # empty means "use the default"
        path = full_path(raw)
        if path is None:
            return jsonify(error="Projects folder: enter a full path, such as /home/pi or C:\\Projects"), 400
        if not os.path.isdir(path):
            return jsonify(error=f"Projects folder: '{path}' is not an existing folder"), 400
        if path != os.path.normpath(DEFAULT_PROJECTS):
            new["projects_dir"] = path   # the default is simply not stored
    raw_port = d.get("preferred_port", 0)
    if isinstance(raw_port, str):
        raw_port = raw_port.strip() or "0"
    try:
        if isinstance(raw_port, float) and not raw_port.is_integer():
            raise ValueError
        port = int(raw_port)
    except (TypeError, ValueError):
        return jsonify(error="Preferred port: enter a whole number"), 400
    if isinstance(raw_port, bool) or (port != 0 and not 1024 <= port <= 65535):
        return jsonify(error="Preferred port: use 0 (no preference) or a port from 1024 to 65535"), 400
    if port:
        new["preferred_port"] = port   # 0 is the default, so it is simply not stored
    where = d.get("listen", DEFAULT_LISTEN)
    if where not in ("local", "network"):
        return jsonify(error="Listen on: invalid value"), 400
    if where != DEFAULT_LISTEN:
        new["listen"] = where   # the default is simply not stored
    with save_lock:
        data = load_store()
        data["config"] = new
        err = write_store(data)
    if err:
        return jsonify(error=f"Could not save the settings file: {err}"), 500
    return jsonify(config_view())


# ---------- routes: Make Zip ----------
@app.post("/makezip/api/start")
def zip_start():
    project, opts, err = check_project((request.get_json(silent=True) or {}).get("project", ""))
    if err:
        return jsonify(error=err), 400
    lines = zip_job.begin()
    if lines is None:
        return jsonify(error="Already running - stop it first"), 409
    err = remember_project(project)
    if err:
        lines.append(f"Could not remember this selection: {err}")
    threading.Thread(target=run_zip_job, args=(lines, project, opts), daemon=True).start()
    return jsonify(ok=True)


@app.get("/makezip/api/download")
def zip_download():
    """Download one of the zips in a project's dist folder."""
    project = full_path(request.args.get("project", ""))
    name = request.args.get("name", "")
    if project is None or not os.path.isdir(project) or name not in {z["name"] for z in dist_zips(project)}:
        return jsonify(error="No such zip file"), 404
    return send_from_directory(os.path.join(project, "dist"), name, as_attachment=True)


# ---------- routes: Install ----------
@app.post("/install/api/start")
def install_start():
    d = request.get_json(silent=True) or {}
    project, opts, err = check_project(d.get("project", ""))
    if err:
        return jsonify(error=err), 400
    raw = d.get("target", "")
    if not isinstance(raw, str):
        return jsonify(error="Install folder: invalid value"), 400
    target = default_target(project)
    if raw.strip():   # empty: ~/<project name>
        target = full_path(raw)
        if target is None:
            return jsonify(error="Install folder: enter a full path, or leave it empty"), 400
    if os.path.exists(target) and not os.path.isdir(target):
        return jsonify(error=f"Install folder: '{target}' is a file"), 400
    lines = install_job.begin()
    if lines is None:
        return jsonify(error="Already running - stop it first"), 409
    err = remember_project(project, install_target=target if raw.strip() else "")
    if err:
        lines.append(f"Could not remember these selections: {err}")
    threading.Thread(target=run_install_job, args=(lines, project, opts, target), daemon=True).start()
    return jsonify(ok=True)


# ---------- pages ----------
# The pages' HTML, CSS and JS live in the web folder next to this script. base.html is the frame every page
# shares (style.css and common.js go into it); each page is <name>.html for its body plus <name>.js if it has a script.
WEB_DIR = os.path.join(SCRIPT_DIR, "web")


def web_file(name):
    with open(os.path.join(WEB_DIR, name), encoding="utf-8") as f:
        return f.read()


def render(title, page):
    script = web_file(page + ".js") if os.path.isfile(os.path.join(WEB_DIR, page + ".js")) else ""
    return (web_file("base.html").replace("__CSS__", web_file("style.css"))
            .replace("__TITLE__", title).replace("__BODY__", web_file(page + ".html"))
            .replace("__SCRIPT__", script).replace("__COMMON_JS__", web_file("common.js")))


HOME_PAGE = render("Standalone tools", "home")
ZIP_PAGE = render("Make Zip", "makezip")
INSTALL_PAGE = render("Install", "install")
SETTINGS_PAGE = render("Standalone tools - Settings", "settings")
_README_TEMPLATE = render("Standalone tools - Instructions", "readme")


def build_readme(is_windows):
    """The instructions page, with the setup steps and examples for Windows or Linux."""
    if is_windows:
        text = {
            "__SETUP__": (
                '<p><b>Windows</b> (10 or later). Install Python 3.8 or later (from python.org, tick "Add python.exe to PATH"). '
                'Then open Command Prompt or PowerShell and install Flask:</p>'
                '<pre>pip install flask</pre><p>Then start the app:</p><pre>python standalone_tools.py</pre>'
                '<p>Windows may ask whether to allow Python through the firewall. Allow it on private networks, '
                'or other computers will not be able to open the page.</p>'),
            "__EXAMPLE__": r"C:\Users\me\scanCam",
            "__HIDDEN_NOTE__": "The name starts with a dot, but Windows does not hide it: it shows in File Explorer like any other file.",
        }
    else:
        text = {
            "__SETUP__": (
                '<p><b>Linux</b> (for example Raspberry Pi OS / Debian Trixie): install Flask:</p>'
                '<pre>sudo apt install python3-flask</pre>'
                '<p>Then start the app from a terminal:</p><pre>python3 standalone_tools.py</pre>'),
            "__EXAMPLE__": "/home/pi/scanCam",
            "__HIDDEN_NOTE__": "The name starts with a dot, so it is hidden: use <code>ls -a</code> in that folder to see it.",
        }
    page = _README_TEMPLATE
    for key, value in text.items():
        page = page.replace(key, value)
    return page


README_PAGE = build_readme(IS_WINDOWS)


@app.get("/readme")
def readme_page():
    return README_PAGE


@app.get("/")
def home():
    return HOME_PAGE


@app.get("/makezip")
def makezip_page():
    return ZIP_PAGE


@app.get("/install")
def install_page():
    return INSTALL_PAGE


@app.get("/settings")
def settings_page():
    return SETTINGS_PAGE


def open_browser(path="/"):
    # Only when a desktop session exists - on a headless Pi, Python could otherwise
    # launch a text browser inside the terminal
    if not IS_WINDOWS and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return
    host = "localhost" if HOST in ("0.0.0.0", "127.0.0.1", "::") else HOST
    webbrowser.open(f"http://{host}:{PORT}{path}")


def check_settings_writable():
    """Warn at start-up if settings cannot be saved where they are meant to live."""
    target = SETTINGS_FILE if os.path.exists(SETTINGS_FILE) else os.path.dirname(SETTINGS_FILE)
    if not os.access(target, os.W_OK):
        logger.warning(f"Settings cannot be saved: {target} is not writable. "
                       f"Install the app in a folder you can write to")


def main():
    global HOST, PORT
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger.info(f"Running on {PLATFORM}" + (" (Windows code paths)" if IS_WINDOWS else ""))
    if PLATFORM not in ("Linux", "Windows"):
        logger.warning(f"{PLATFORM} has not been tested: it is being treated like Linux")
    logger.info(f"Installs run with {sys.executable}")
    logger.info(f"Settings file: {SETTINGS_FILE} ({'found' if os.path.isfile(SETTINGS_FILE) else 'not found'})")
    check_settings_writable()
    data = load_store()
    local = listen(data) == "local"
    logger.info("Listening for this computer only" if local else "Listening for any computer on the network")
    HOST, PORT = validate_port(preferred_port(data), local)
    # No settings file yet = first run: start on the instructions. Otherwise start on Home as normal.
    path = "/" if os.path.isfile(SETTINGS_FILE) else "/readme"
    host = "localhost" if HOST in ("0.0.0.0", "127.0.0.1", "::") else HOST
    print(f" * Standalone tools: http://{host}:{PORT}{path}")
    threading.Timer(1.0, open_browser, args=(path,)).start()  # give the server a moment to start
    threading.Thread(target=watch_pages, daemon=True).start()
    logger.info("The app stops by itself once every page of it has been closed")
    app.run(host=HOST, port=PORT, threaded=True)


if __name__ == "__main__":
    main()
