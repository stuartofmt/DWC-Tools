#!/usr/bin/env python3
"""Prep and Package - one small web app that prepares and releases standalone Python programs.
  /          Home        choose a tool
  /prepare   Prepare     make the project's requirements.txt from its imports, create its venv and install into it
  /makezip   Make Zip    build standalone-zip/<name>-<version>.zip (or standalone-zip/<name>.zip) from the project
  /settings  Settings    the folder project browsing starts in, the preferred port and where to listen
  /readme    Instructions on use

A project is any folder with a .py file in it or anywhere below it. One of those files is its main program
(a project option), and the main program's folder is the project's code folder:
  <project>/README.md                     (optional)
  <project>/<code folder>/<main>.py       the program, e.g. code/scanCam.py; it may set its version: progVersion = '1.0.0'
  <project>/<code folder>/requirements.txt  what pip installs into the venv (or <project>/requirements.txt)
The project's name is its folder name.

Prepare works on the project folder itself: it adds any missing packages the code folder imports to requirements.txt
(making <code folder>/requirements.txt if there is none), creates <project>/venv, installs requirements.txt into it,
checks that the venv can import every package, and adds a run.sh / run.bat launcher if there is none.

The zip unzips to a <name>/ folder holding README.md, the code folder and an install.py made by this app
(see INSTALL_TEMPLATE), so the release can be installed on another computer without this app, plus
run.sh and run.bat that start install.py with the system Python (see INSTALL_LAUNCHERS).

Nothing is installed system-wide (no apt, no sudo): the venv is created and requirements.txt is installed into it
with the venv's own pip, which also works where the system Python is "externally managed".
Each project has options, kept in the settings file: the main program, and whether its venv can see
Python packages already installed on the system.

Setup (Linux, e.g. Raspberry Pi OS):  sudo apt install python3-venv, then in the Prep_and_Package folder, once:
         python3 -m venv venv; venv/bin/python -m pip install -r code/requirements.txt
Setup (Windows 10 or later):          install Python 3.8+, then once: py -m venv venv;
         venv\\Scripts\\python -m pip install -r code\\requirements.txt
Run:     ./run.sh                    (Windows: venv\\Scripts\\python code\\prep_and_package.py)
Keep the web folder (the pages' HTML, CSS and JS) next to this script.
Open:    the address printed at start-up: this computer's network address (or 127.0.0.1 when Settings says
         "This computer only"), on the preferred port from the Settings page, or else the first free port from 17900.
         The first time (no settings file yet) the browser opens at /readme instead of Home.

The app stops by itself (stopping any running job) once every page of it has been closed: each open page sends
/api/alive every few seconds (saying whether it is hidden) and /api/bye when it closes (see the "open pages" section).
A hidden page never times out, so minimizing the browser or leaving the page alone does not stop the app.

The settings, the recent projects and each project's options are stored together in
.prep_and_package.json, in the same folder as this script.
"""
import ast
import json
import logging
import os
import platform
import posixpath
import re
import shutil
import signal
import socket
import subprocess
import sys
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
SETTINGS_NAME = ".prep_and_package.json"
SETTINGS_FILE = os.path.join(SCRIPT_DIR, SETTINGS_NAME)
RECENT_MAX = 8   # most recent projects remembered
FILES_LIMIT = 3000   # most files Make Zip's Exclude files list shows
README = "README.md"
# Never part of a release, and never looked in for .py files. Other files can be left out with Make Zip's
# Exclude files list (remembered per project). At the top of the project, the folder Make Zip puts zips in and the
# dist folder (where other tools, such as plugin_tool, put theirs) are left out too.
SKIP_DIRS = ("__pycache__", "venv", ".venv", ".git", "node_modules")
ZIP_DIR = "standalone-zip"
SKIP_TOP_DIRS = (ZIP_DIR, "dist")
SKIP_SUFFIXES = (".pyc",)
SEARCH_LIMIT = 2000     # most folders looked in for a project's .py files
PROGRAMS_LIMIT = 1000   # most .py files offered as a project's main program
# Project options until they are changed on a tool page
DEFAULT_SITE_PACKAGES = True
# The program's version, if it sets one: progVersion = '1.0.0' (also __version__ / VERSION / version)
VERSION_LINE = re.compile(r"""^\s*(?:progVersion|__version__|VERSION|version)\s*=\s*['"]([^'"\s]+)['"]""", re.M)
VERSION_OK = re.compile(r"[0-9A-Za-z._+-]+")   # it becomes part of the zip's file name

app = Flask(__name__)
logger = logging.getLogger("prep_and_package")
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

    def step(self, lines, cmd, cwd, title=None, shown=None):
        """Run one command, streaming its output. Returns the exit code, or None if stopped.
        shown: what to log for the command, when it is too long to show as it is."""
        if title:
            lines.append(f"=== {title} ===")
        lines.append("$ " + (shown or " ".join(cmd)))
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
prepare_job = Job()   # Prepare
JOBS = (zip_job, prepare_job)


def shut_down(reason):
    """Stop every running job, then end this app."""
    logger.info(f"{reason} - stopping")
    for j in JOBS:
        j.terminate(force_after=5)
    os._exit(0)


# ---------- open pages: the app stops once the last one has gone ----------
PAGE_GRACE = 10     # seconds to wait after the last page closed: a reload or a link opens the next page well within this
PAGE_TIMEOUT = 90   # a visible page not heard from for this long counts as closed (a browser that crashed or was killed).
                    # A hidden page (minimized, another tab or app in front) never times out: browsers slow, freeze or
                    # discard hidden pages, so its silence says nothing. Closing it still sends /api/bye.
pages = {}          # page id -> {"seen": when it was last heard from, "hidden": bool, "seq": number of its last message}
closed_pages = {}   # page id -> number of its /api/bye, so a message sent before it but arriving later is ignored
pages_lock = threading.Lock()
page_seen = False   # until a page has opened, the app keeps waiting (e.g. on a Pi without a screen)


def watch_pages():
    """Stop the app once every page has closed (or, while visible, gone quiet for PAGE_TIMEOUT)."""
    empty_since = None
    while True:
        time.sleep(2)
        now = time.monotonic()
        with pages_lock:
            for page, p in list(pages.items()):
                if not p["hidden"] and now - p["seen"] > PAGE_TIMEOUT:
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


def py_tree(folder):
    """os.walk of folder, leaving out SKIP_DIRS, hidden folders and its SKIP_TOP_DIRS, and stopping after
    SEARCH_LIMIT folders (so a huge folder, such as a home folder, cannot hold things up)."""
    for seen, (dirpath, dirnames, filenames) in enumerate(os.walk(folder)):
        if seen >= SEARCH_LIMIT:
            return
        dirnames[:] = sorted((d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")
                              and not (dirpath == folder and d in SKIP_TOP_DIRS)), key=natural)
        yield dirpath, dirnames, sorted(filenames, key=natural)


def programs(project):
    """The .py files in the project folder and below it, as paths relative to it ("code/scanCam.py"):
    the candidates for its main program. The ones nearest the top come first."""
    out = []
    for dirpath, _, filenames in py_tree(project):
        for n in filenames:
            if n.endswith(".py"):
                out.append(os.path.relpath(os.path.join(dirpath, n), project).replace(os.sep, "/"))
                if len(out) >= PROGRAMS_LIMIT:
                    return out
    return out


def is_project(folder):
    """Whether there is a .py file in folder or anywhere below it."""
    return any(n.endswith(".py") for _, _, filenames in py_tree(folder) for n in filenames)


def code_dir(opts):
    """The project's code folder, relative to the project: the main program's folder ("" for the project folder)."""
    return posixpath.dirname(opts["main"])


def options_for(project, data=None):
    """The project's options: saved ones where valid, defaults for the rest."""
    data = data or load_store()
    saved = data["projects"].get(project)
    saved = saved if isinstance(saved, dict) else {}
    found = programs(project)
    main = saved.get("main")
    if isinstance(main, str) and main not in found and "code/" + main in found:
        main = "code/" + main   # saved by an older version, which only looked in the code folder
    if main not in found:
        # Picked for you: the one named after the project, else the only .py file, else the only one at the top
        # of a code folder (any case)
        name = (os.path.basename(project) + ".py").lower()
        in_code = [p for p in found if posixpath.dirname(p).lower() == "code"]
        main = next((p for p in found if posixpath.basename(p).lower() == name),
                    found[0] if len(found) == 1 else in_code[0] if len(in_code) == 1 else "")

    site = saved.get("site_packages")
    return {"main": main,
            "site_packages": site if isinstance(site, bool) else DEFAULT_SITE_PACKAGES}


def requirements_places(opts):
    """Where the project's requirements.txt can be, relative to the project, in the order looked at:
    in the code folder, then in the project folder."""
    return list(dict.fromkeys([posixpath.join(code_dir(opts), "requirements.txt"), "requirements.txt"]))


def requirements_file(project, opts):
    """The project's requirements.txt, relative to the project (e.g. "code/requirements.txt"), or ""."""
    return next((r for r in requirements_places(opts) if os.path.isfile(os.path.join(project, r))), "")


def program_version(project, main):
    """The version set in the main program, or None."""
    if not main:
        return None
    try:
        with open(os.path.join(project, main), encoding="utf-8", errors="replace") as f:
            m = VERSION_LINE.search(f.read())
    except OSError:
        return None
    return m.group(1) if m and VERSION_OK.fullmatch(m.group(1)) else None


def release_zips(project):
    """The zip files Make Zip made, in the project's standalone-zip folder, newest first."""
    out = []
    for f in glob(os.path.join(project, ZIP_DIR, "*.zip")):
        try:
            st = os.stat(f)
        except OSError:
            continue
        out.append({"name": os.path.basename(f), "size": st.st_size, "mtime": st.st_mtime,
                    "when": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))})
    return sorted(out, key=lambda z: z["mtime"], reverse=True)


def venv_python(venv):
    return os.path.join(venv, "Scripts", "python.exe") if IS_WINDOWS else os.path.join(venv, "bin", "python")


def launcher_name():
    return "run.bat" if IS_WINDOWS else "run.sh"


def project_view(path, data=None):
    """What the pages need to know about a project folder."""
    found = programs(path)
    view = {"path": path, "name": os.path.basename(path), "exists": True, "is_project": bool(found)}
    if found:
        opts = options_for(path, data)
        view.update(programs=found, options=opts, version=program_version(path, opts["main"]),
                    has_readme=os.path.isfile(os.path.join(path, README)),
                    requirements=requirements_file(path, opts),
                    venv=os.path.isfile(venv_python(os.path.join(path, "venv"))),
                    launcher=launcher_name() if os.path.isfile(os.path.join(path, launcher_name())) else "",
                    zips=release_zips(path))
        files, excluded, truncated = zip_files(path, opts, data)
        view.update(files=files, excluded=excluded, files_truncated=truncated,
                    needed=sorted(needed_files(path, opts)))
    return view


def check_project(raw, need_requirements=True):
    """(path, options, None) for a project with its main program chosen (and a requirements.txt, unless
    need_requirements is False), else (None, None, error message)."""
    path = full_path(raw)
    if path is None:
        return None, None, "Choose a project: enter or browse to the full path of its folder"
    if not os.path.isdir(path):
        return None, None, f"'{path}' is not an existing folder"
    if not is_project(path):
        return None, None, f"'{path}' has no .py file in it or below it"
    opts = options_for(path)
    if not opts["main"]:
        return None, None, "Choose the main program in the project options"
    if need_requirements and not requirements_file(path, opts):
        return None, None, (f"'{path}' has no requirements.txt (in {code_dir(opts) or 'the project folder'}"
                            f"{' or the project folder' if code_dir(opts) else ''}): press Prepare to make one")
    return path, opts, None


# ---------- the install.py that goes into each release ----------
# Filled in by make_install_py(). Its job is that of the original scanCam install.py, with the project's
# name, main program and packages filled in. It goes into each release, to install it on another computer.
# The install folder can be given as an argument, and --source names the folder holding the program.
INSTALL_TEMPLATE = r'''#!/usr/bin/env python3
"""
One-time setup for __NAME__: asks for an install directory, copies the
program there, then creates its Python venv and installs requirements.txt into it with pip.
Nothing is installed system-wide, so no sudo is needed.

Run from the unzipped folder with: ./run.sh or python3 install.py  (on Windows: run.bat or py install.py)
The install directory is chosen in a folder window when there is a desktop and Python has tkinter
(otherwise it is asked for in the terminal; --no-gui always asks in the terminal).
It can also be given straight away: python3 install.py /home/pi/__NAME__
Once installed, the program is started with its launcher (run.sh, or run.bat on Windows);
add --no-run to install without starting it.
Running it again updates the program files and recreates the venv.
(Made by prep_and_package.py.)
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

NAME = __NAME_R__
MAIN = __MAIN_R__            # the program, relative to the install directory
REQUIREMENTS = __REQ_R__     # what pip installs into the venv
SYSTEM_SITE_PACKAGES = __SITE_R__   # whether the venv can also use Python packages already installed on the system

IS_WINDOWS = sys.platform == 'win32'

here = Path(__file__).resolve().parent
default_target = Path.home() / NAME
# Copied into the install directory; the venv and launcher are created there.
program_files = __FILES_R__
MAIN_WINDOWS = MAIN.replace('/', '\\')

if IS_WINDOWS:
    launcher_name = 'run.bat'
    launcher_script = ('@echo off\n'
                       f'rem Start {NAME} using its venv (recreate it with install.py).\n'
                       'cd /d "%~dp0"\n'
                       f'venv\\Scripts\\python.exe -u {MAIN_WINDOWS} %*\n')
else:
    launcher_name = 'run.sh'
    launcher_script = ('#!/bin/bash\n'
                       f'# Start {NAME} using its venv (recreate it with python3 install.py).\n'
                       'cd "$(dirname "$0")"\n'
                       f'exec venv/bin/python -u {MAIN} "$@"\n')


def gui():
    """A hidden Tk window for showing dialogs, or None when there is no desktop or Python has no tkinter
    (e.g. over SSH, on a Pi without a screen, or Debian without the python3-tk package). Says why when there is none."""
    if not IS_WINDOWS and not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        print("No folder window: no desktop here (DISPLAY is not set), so asking in the terminal")
        return None
    try:
        import tkinter
        root = tkinter.Tk()
    except Exception as e:
        print(f"No folder window ({type(e).__name__}: {e}), so asking in the terminal")
        return None
    # A hidden window's "on top" setting does not reach its dialogs on every desktop (they can open behind an
    # editor or the terminal), so show a tiny transparent window, raised and focused, for the dialogs to open over
    root.title(f"Install {NAME}")
    root.geometry('1x1+0+0')
    try:
        root.attributes('-alpha', 0.0)
    except Exception:
        pass
    root.attributes('-topmost', True)
    root.deiconify()
    root.lift()
    root.focus_force()
    root.update()
    return root


def ask_target_gui(root) -> Path:
    """Choose the install directory in a folder window. Returns None if cancelled."""
    from tkinter import filedialog, messagebox
    while True:
        picked = filedialog.askdirectory(
            parent=root, initialdir=str(Path.home()), mustexist=False,
            title=f"Choose where to install {NAME} (a {NAME} folder is made in it), or type a new folder")
        if not picked:
            return None
        picked = Path(picked).expanduser().resolve()
        # A folder typed in that does not exist yet is made and used as it is. Choosing an existing install (a folder
        # called NAME) installs over it; any other existing folder gets a NAME folder made in it
        target = picked if not picked.exists() or picked.name == NAME else picked / NAME
        if target.exists() and not target.is_dir():
            messagebox.showerror(f"Install {NAME}", f"{target} is a file, not a folder.", parent=root)
            continue
        answer = messagebox.askyesnocancel(
            f"Install {NAME}", f"Install {NAME} into\n\n{target}\n\n"
            "Yes to install, No to choose another folder, Cancel to stop.", parent=root)
        if answer is None:
            return None
        if answer:
            return target


def ask_target_text() -> Path:
    try:
        answer = input(f"Enter the directory to install {NAME} into [{default_target}]: ").strip()
    except EOFError:
        # No terminal to answer from (e.g. piped input), so take the default.
        answer = ''
    return Path(answer).expanduser().resolve() if answer else default_target


def show_error(root, text):
    """Report a failed install in a message box too, when the folder was chosen in a window."""
    if root is not None:
        from tkinter import messagebox
        messagebox.showerror(f"Install {NAME}", text, parent=root)


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
    parser.add_argument('--source', help='the folder holding the program (default: the folder this script is in)')
    parser.add_argument('--no-run', action='store_true', help=f'do not start {NAME} once it is installed')
    parser.add_argument('--no-gui', action='store_true', help='ask for the install directory in the terminal, not in a window')
    args = parser.parse_args()
    source = Path(args.source).expanduser().resolve() if args.source else here
    root = None
    if args.target:
        target = Path(args.target).expanduser().resolve()
    else:
        root = None if args.no_gui else gui()
        target = ask_target_gui(root) if root is not None else ask_target_text()
        if target is None:
            sys.exit("Install cancelled")
        print(f"Installing {NAME} into {target}", flush=True)
    try:
        copy_program(source, target)
        create_venv(target)
    except SystemExit as e:   # create_venv's own message (the venv module is missing)
        show_error(root, str(e))
        raise
    except subprocess.CalledProcessError as e:
        message = f"Install failed: {' '.join(e.cmd)} exited with {e.returncode}"
        show_error(root, message + "\n\nThe terminal shows what went wrong.")
        sys.exit(message)
    except OSError as e:
        show_error(root, f"Install failed: {e}")
        sys.exit(f"Install failed: {e}")
    if root is not None:
        root.destroy()
    launcher = target / launcher_name
    print()
    print(f"{NAME} is installed in {target}. Start it with: {launcher}")
    if args.no_run:
        return
    print(f"Starting {NAME} with {launcher}")
    print(flush=True)   # before the program's own output
    try:
        # run.bat needs cmd; run.sh is executable
        code = subprocess.call(['cmd', '/c', str(launcher)] if IS_WINDOWS else [str(launcher)], cwd=str(target))
    except KeyboardInterrupt:   # Ctrl+C stops the program; nothing more to report
        code = 130
    except OSError as e:
        sys.exit(f"Could not start {launcher}: {e}")
    sys.exit(code)


if __name__ == '__main__':
    main()
'''


# Beside install.py in each release, so it can be started without typing the Python command.
# The zip may be unzipped on either system, so it holds both.
INSTALL_LAUNCHERS = {
    "run.sh": ('#!/bin/sh\n'
               '# Install the program (made by prep_and_package.py). Arguments go to install.py.\n'
               'cd "$(dirname "$0")"\n'
               'exec python3 install.py "$@"\n'),
    "run.bat": ('@echo off\r\n'
                'rem Install the program (made by prep_and_package.py). Arguments go to install.py.\r\n'
                'cd /d "%~dp0"\r\n'
                'where py >nul 2>nul\r\n'
                'if %errorlevel%==0 (py -3 install.py %*) else (python install.py %*)\r\n'
                'if errorlevel 1 pause\r\n'),
}


def make_install_py(name, opts, requirements, files):
    """The install.py for a project, with its name, options, requirements.txt (relative path) and the top-level
    files and folders it copies (those of the zip) filled in."""
    values = {"__NAME_R__": repr(name), "__MAIN_R__": repr(opts["main"]), "__REQ_R__": repr(requirements),
              "__SITE_R__": repr(opts["site_packages"]), "__FILES_R__": repr(sorted(files))}
    text = INSTALL_TEMPLATE
    for key, value in values.items():
        text = text.replace(key, value)
    return text.replace("__NAME__", name)


# ---------- Make Zip: the job ----------
# Made by Make Zip itself, so never taken from the project folder
MADE_FILES = {"install.py", "run.sh", "run.bat"}


def release_files(project, opts, exclude=()):
    """(path on disk, path inside the zip below <name>/) for README.md, requirements.txt and everything in the
    code folder, leaving out the paths (relative to the project) in exclude."""
    skip, given = set(exclude), set()
    for top in (README, "requirements.txt"):
        path = os.path.join(project, top)
        if os.path.isfile(path) and top not in skip:
            given.add(top)
            yield path, top
    top_dir = os.path.join(project, code_dir(opts))
    for dirpath, dirnames, filenames in os.walk(top_dir):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not (dirpath == project and d in SKIP_TOP_DIRS))
        for name in sorted(filenames):
            if name.endswith(SKIP_SUFFIXES) or (dirpath == project and name in MADE_FILES):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, project).replace(os.sep, "/")
            if rel not in skip and rel not in given:
                yield path, rel


def top_level(files):
    """The top-level names (what install.py copies) of paths inside a release."""
    return {rel.split("/")[0] for rel in files}


def needed_files(project, opts):
    """Files a release cannot do without (install.py runs the main program and installs requirements.txt)."""
    return {opts["main"], requirements_file(project, opts)} - {""}


def zip_files(project, opts, data=None):
    """For Make Zip's Exclude files list: (files, excluded, truncated). files are the paths (relative to the project)
    that can go into the zip, at most FILES_LIMIT of them; excluded the ones ticked last time for this project
    that still exist (none until something has been ticked)."""
    files = []
    for _, rel in release_files(project, opts):
        files.append(rel)
        if len(files) > FILES_LIMIT:
            break
    truncated = len(files) > FILES_LIMIT
    files = files[:FILES_LIMIT]
    saved = (data or load_store())["projects"].get(project)
    saved = saved.get("exclude") if isinstance(saved, dict) else None
    present = set(files)
    excluded = [x for x in saved if isinstance(x, str) and x in present] if isinstance(saved, list) else []
    needed = needed_files(project, opts)
    return files, [x for x in excluded if x not in needed], truncated


def run_zip_job(lines, project, opts, exclude):
    job = zip_job
    ok = False
    name = os.path.basename(project)
    out = None
    try:
        version = program_version(project, opts["main"])
        lines.append(f"=== Make zip of {name}" + (f" version {version} ===" if version else " (no version set) ==="))
        out = os.path.join(project, ZIP_DIR, f"{name}-{version}.zip" if version else f"{name}.zip")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        added = []
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as z:
            if exclude:
                lines.append("Left out (Exclude files): " + ", ".join(exclude))
            for path, rel in release_files(project, opts, exclude):
                if job.stopping:
                    raise InterruptedError
                z.write(path, f"{name}/{rel}")
                lines.append(f"  adding: {name}/{rel}")
                added.append(rel)
            z.writestr(f"{name}/install.py", make_install_py(name, opts, requirements_file(project, opts), top_level(added)))
            lines.append(f"  adding: {name}/install.py   (made by this app for {opts['main']})")
            for launcher, text in INSTALL_LAUNCHERS.items():
                info = zipfile.ZipInfo(f"{name}/{launcher}", time.localtime()[:6])
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3                  # Unix, so unzip keeps the mode below
                info.external_attr = 0o100755 << 16     # executable
                z.writestr(info, text)
                lines.append(f"  adding: {name}/{launcher}   (runs install.py with the system Python)")
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


# ---------- Prepare: the job ----------
# Run with the Python outside any venv (see base_python): what Python's standard library holds, and which pip
# package provides each importable top-level name on this computer
PROBE = r"""
import json, os, sys, sysconfig
try:
    std = set(sys.stdlib_module_names)
except AttributeError:   # Python before 3.10
    std = set(sys.builtin_module_names)
    lib = sysconfig.get_paths()["stdlib"]
    std.update(n[:-3] if n.endswith(".py") else n for n in os.listdir(lib))
try:
    from importlib.metadata import packages_distributions
    dists = packages_distributions()
except ImportError:
    dists = {}
print(json.dumps({"stdlib": sorted(std), "dists": dists}))
"""
# Run in the project's venv with the module names as arguments: imports each one
CHECK = r"""
import importlib, sys
bad = 0
for name in sys.argv[1:]:
    try:
        importlib.import_module(name)
        print("  ok      " + name)
    except BaseException as e:
        bad += 1
        print("  FAILED  %s: %s: %s" % (name, type(e).__name__, e))
sys.exit(1 if bad else 0)
"""
# pip package names that differ from the import name, for packages not installed on this computer
# (for installed ones, their own metadata says which package they came from)
PIP_NAMES = {"cv2": "opencv-python", "PIL": "Pillow", "yaml": "PyYAML", "serial": "pyserial",
             "sklearn": "scikit-learn", "skimage": "scikit-image", "bs4": "beautifulsoup4",
             "dateutil": "python-dateutil", "dotenv": "python-dotenv", "usb": "pyusb", "jwt": "PyJWT",
             "Crypto": "pycryptodome", "OpenSSL": "pyOpenSSL", "zmq": "pyzmq", "gi": "PyGObject",
             "magic": "python-magic", "attr": "attrs", "RPi": "RPi.GPIO", "websocket": "websocket-client"}
# Modules that more than one pip package provides: any of them listed in requirements.txt covers the import
# (these packages conflict, so adding a second one would break the first)
ALTERNATIVES = {"cv2": ["opencv-python", "opencv-python-headless", "opencv-contrib-python",
                        "opencv-contrib-python-headless"]}
REQ_NAME = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def base_python():
    """The Python this app's Python was made from, outside any venv: it sees the packages installed on the
    system, and new venvs are made with it (as install.py does)."""
    exe = os.path.join(sys.base_prefix, "python.exe") if IS_WINDOWS else os.path.join(sys.base_prefix, "bin", "python3")
    return exe if os.path.isfile(exe) else sys.executable


def pip_key(name):
    """A pip package name in the form pip compares them (Flask, flask and FLASK are the same package)."""
    return re.sub(r"[-_.]+", "-", name).lower()




IMPORT_ERRORS = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}


def optional_imports(tree):
    """The import statements inside a try whose except catches ImportError (or a bare except): the program
    copes without those modules."""
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        caught = set()
        for h in node.handlers:
            types = h.type.elts if isinstance(h.type, ast.Tuple) else [h.type]
            caught.update("BaseException" if t is None else getattr(t, "id", getattr(t, "attr", "")) for t in types)
        if caught & IMPORT_ERRORS:
            for stmt in node.body:
                out.update(id(n) for n in ast.walk(stmt) if isinstance(n, (ast.Import, ast.ImportFrom)))
    return out


def imported_modules(project, opts, stdlib, lines):
    """({top-level module name: [files importing it]}, {the same for optional imports}) for the modules the code
    folder imports that are neither in Python's standard library nor part of the project (any .py file or folder in
    the code folder). An import is optional when try/except ImportError guards it everywhere it appears."""
    local, files = set(), []
    for dirpath, dirnames, filenames in py_tree(os.path.join(project, code_dir(opts))):
        local.update(dirnames)
        for n in filenames:
            if n.endswith(".py"):
                local.add(n[:-3])
                files.append(os.path.join(dirpath, n))
    found, optional = {}, {}
    for path in files:
        rel = os.path.relpath(path, project).replace(os.sep, "/")
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                tree = ast.parse(f.read(), rel)
        except (SyntaxError, ValueError, OSError) as e:
            lines.append(f"Could not read {rel}, so its imports are not counted: {e}")
            continue
        guarded = optional_imports(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]   # from x import y (relative imports are always the project's own)
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top not in stdlib and top not in local and top != "__future__":
                    where = optional if id(node) in guarded else found
                    where.setdefault(top, [])
                    if rel not in where[top]:
                        where[top].append(rel)
    order = lambda d: dict(sorted(d.items(), key=lambda kv: kv[0].lower()))
    return order(found), order({k: v for k, v in optional.items() if k not in found})


def listed_requirements(text):
    """[(package name, environment marker or "")] for each package line of a requirements.txt's text."""
    listed = []
    for line in text.splitlines():
        line = line.split("#")[0]
        m = REQ_NAME.match(line)
        if m and not line.lstrip().startswith("-"):
            listed.append((m.group(1), line.partition(";")[2].strip()))
    return listed


def marker_applies(marker):
    """Whether a requirement's environment marker (e.g. sys_platform == "win32") holds on this computer, as
    pip decides it. True when there is none, or it can't be evaluated."""
    if not marker:
        return True
    try:
        try:
            from packaging.markers import Marker
        except ImportError:
            from pip._vendor.packaging.markers import Marker   # every venv has pip, and pip has packaging
        return Marker(marker).evaluate()
    except Exception:
        return True


def update_requirements(project, opts, packages, lines, other_platform=()):
    """Add the pip packages not yet listed to the project's requirements.txt (one is made in the code folder
    if there is none). Nothing already in it is changed or removed. other_platform: listed packages the code
    imports that are for another platform (not added, but not reported as unused either).
    Returns its path relative to the project."""
    rel = requirements_file(project, opts) or requirements_places(opts)[0]
    path = os.path.join(project, rel)
    text = ""
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as f:
            text = f.read()
    listed = [name for name, _ in listed_requirements(text)]
    have = {pip_key(x) for x in listed}
    add = [p for p in packages if pip_key(p) not in have]
    wanted = {pip_key(p) for p in [*packages, *other_platform]}
    if not text:
        text = ("# What pip installs into the program's venv. Made by Prepare from the program's imports:\n"
                "# edit it as needed (Prepare only ever adds packages that are missing).\n")
    if add or not os.path.isfile(path):
        if not text.endswith("\n"):
            text += "\n"
        text += "".join(p + "\n" for p in add)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    lines.append(f"{rel}: " + ("added " + ", ".join(add) if add else "nothing to add")
                 + (" (new file)" if not listed and add else ""))
    unused = [x for x in listed if pip_key(x) not in wanted]
    if unused:
        lines.append("Listed but not imported by the code (left in, as the program may still need them): " + ", ".join(unused))
    return rel


def venv_uses_system(venv):
    """Whether an existing venv can see the system's packages (from its pyvenv.cfg); None if unknown."""
    try:
        with open(os.path.join(venv, "pyvenv.cfg"), encoding="utf-8") as f:
            for line in f:
                key, _, value = line.partition("=")
                if key.strip() == "include-system-site-packages":
                    return value.strip().lower() == "true"
    except OSError:
        pass
    return None


def write_launcher(project, opts, lines):
    """Add run.sh (Windows: run.bat) to the project, to start the program with its venv, unless there is one."""
    name = launcher_name()
    path = os.path.join(project, name)
    if os.path.exists(path):
        lines.append(f"{name}: already there, left as it is")
        return
    main = opts["main"]
    if IS_WINDOWS:
        text = ("@echo off\r\nrem Start the program with its venv (made by Prepare in Prep_and_Package).\r\n"
                f'cd /d "%~dp0"\r\nvenv\\Scripts\\python.exe -u {main.replace("/", os.sep)} %*\r\n')
    else:
        text = ("#!/bin/bash\n# Start the program with its venv (made by Prepare in Prep_and_Package).\n"
                f'cd "$(dirname "$0")"\nexec venv/bin/python -u {main} "$@"\n')
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.chmod(path, 0o755)
    lines.append(f"{name}: made, to start {main} with the venv")


def run_prepare_job(lines, project, opts):
    """requirements.txt from the imports -> venv -> pip install -> import check -> launcher."""
    job = prepare_job
    ok = False
    name = os.path.basename(project)
    try:
        lines.append(f"=== Find the packages {name} imports ===")
        py = base_python()
        probe = subprocess.run([py, "-c", PROBE], capture_output=True, text=True, timeout=120,
                               stdin=subprocess.DEVNULL)
        if probe.returncode != 0:
            raise RuntimeError(f"Could not ask {py} about its packages: {probe.stderr.strip()}")
        info = json.loads(probe.stdout)
        lines.append(f"Code folder: {code_dir(opts) or 'the project folder'} (where the main program {opts['main']} is)")
        modules, optional = imported_modules(project, opts, set(info["stdlib"]), lines)
        req_path = os.path.join(project, requirements_file(project, opts)) if requirements_file(project, opts) else ""
        listed = {}
        if req_path:
            with open(req_path, encoding="utf-8-sig") as f:
                listed = {pip_key(name): (name, marker) for name, marker in listed_requirements(f.read())}
        packages, other_platform, other_platform_packages = [], set(), []
        for module, files in modules.items():
            dists = info["dists"].get(module) or []
            # A package already in requirements.txt that provides the module covers it, whichever one it is
            providers = dists + ALTERNATIVES.get(module, []) + [PIP_NAMES.get(module, module)]
            listed_as = next((listed[pip_key(p)] for p in providers if pip_key(p) in listed), None)
            if listed_as and not marker_applies(listed_as[1]):
                # e.g. a Windows-only package, imported only when the program runs on Windows
                other_platform.add(module)
                other_platform_packages.append(listed_as[0])
                lines.append(f"  {module:<20} -> {listed_as[0]} (listed for {listed_as[1]}: not for this computer, "
                             f"so not installed or checked here)   imported in {', '.join(files)}")
                continue
            if listed_as:
                package, how = listed_as[0], ""
            elif dists:
                package, how = dists[0], ""
                if len(set(map(pip_key, dists))) > 1:
                    how = f" (also provided by {', '.join(dists[1:])})"
            else:
                package, how = PIP_NAMES.get(module, module), " (not installed on this computer: pip name guessed)"
            if pip_key(package) not in map(pip_key, packages):
                packages.append(package)
            lines.append(f"  {module:<20} -> {package}{how}   imported in {', '.join(files)}")
        if not modules:
            lines.append("  Only Python's standard library and the project's own modules are imported")
        for module, files in optional.items():
            lines.append(f"  {module:<20} optional (try/except ImportError) in {', '.join(files)}: not added, "
                         f"add it to requirements.txt yourself if you want it")

        lines.append("=== requirements.txt ===")
        req = update_requirements(project, opts, packages, lines, other_platform_packages)

        venv = os.path.join(project, "venv")
        site = opts["site_packages"] and not IS_WINDOWS   # as install.py does
        in_use = os.path.realpath(sys.prefix) == os.path.realpath(venv)   # this app is running from it
        if os.path.isdir(venv) and venv_uses_system(venv) != site and not in_use:
            lines.append(f"Removing {venv}: it was made with a different 'system packages' option")
            shutil.rmtree(venv)
        if os.path.isfile(venv_python(venv)):
            lines.append(f"=== Using the existing venv in {venv} ===")
        else:
            code = job.step(lines, [py, "-m", "venv", *(["--system-site-packages"] if site else []), venv],
                            project, title="Create the venv")
            if code != 0:
                if code is not None:
                    lines.append("Could not create the venv. On Debian or Raspberry Pi OS the venv module needs the "
                                 "python3-venv package: sudo apt install python3-venv")
                    shutil.rmtree(venv, ignore_errors=True)   # a half-made venv would be taken as ready next time
                return
        vpy = venv_python(venv)
        code = job.step(lines, [vpy, "-m", "pip", "install", "-r", os.path.join(project, req)], project,
                        title=f"Install {req} into the venv")
        if code != 0:
            if code is not None:
                lines.append(f"pip could not install everything in {req}: correct it and press Prepare again")
            return
        to_check = [m for m in modules if m not in other_platform]
        if to_check:
            code = job.step(lines, [vpy, "-u", "-c", CHECK, *to_check], os.path.join(project, code_dir(opts)),
                            title="Check that the venv can import them",
                            shown=f"{vpy} -c <import each of: {' '.join(to_check)}>")
            if code is None:
                return
            if code != 0:
                lines.append("Some packages could not be imported: fix requirements.txt (or install what the error "
                             "asks for) and press Prepare again")
        lines.append("=== Launcher ===")
        write_launcher(project, opts, lines)

        version = program_version(project, opts["main"])
        lines.append("")
        lines.append("Ready for Make Zip:" if code == 0 else "Make Zip would use:")
        lines.append(f"  main program  {opts['main']}" + (f", version {version}" if version else ", no version set"))
        lines.append(f"  requirements  {req}")
        lines.append("  README.md     " + ("yes" if os.path.isfile(os.path.join(project, README)) else
                                         "none (optional: it goes into the zip with the program)"))
        ok = code == 0
    except Exception as e:
        lines.append(f"Error: {e}")
    finally:
        if job.stopping:
            lines.append("--- stopped ---")
        else:
            lines.append("--- finished OK ---" if ok else "--- FAILED ---")
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
add_job_routes("/prepare", "prepare", prepare_job)


@app.get("/api/status")
def api_status():
    return jsonify(makezip=zip_job.busy, prepare=prepare_job.busy)


@app.post("/api/exit")
def api_exit():
    """Stop every running job, then shut down this web server."""
    threading.Timer(0.5, shut_down, args=("Exit pressed",)).start()  # let this response reach the browser first
    return jsonify(ok=True)


def page_message():
    """(page id, message number, hidden) sent by common.js, as JSON from fetch or plain text from
    navigator.sendBeacon; (None, 0, False) if it is not usable."""
    try:
        d = json.loads(request.get_data(as_text=True) or "{}")
        page, seq = d.get("page"), d.get("seq", 0)
    except (ValueError, AttributeError):
        return None, 0, False
    if not (isinstance(page, str) and 0 < len(page) <= 64) or not isinstance(seq, int) or isinstance(seq, bool):
        return None, 0, False
    return page, seq, bool(d.get("hidden"))


def outdated(page, seq):
    """Whether a message was overtaken by a newer one from the same page (call with pages_lock held)."""
    return (page in pages and seq < pages[page]["seq"]) or seq <= closed_pages.get(page, -1)


@app.post("/api/alive")
def api_alive():
    """An open page says it is still there, and whether it is hidden."""
    global page_seen
    page, seq, hidden = page_message()
    if page:
        with pages_lock:
            if not outdated(page, seq):
                closed_pages.pop(page, None)   # back again (from the browser's back/forward cache)
                pages[page] = {"seen": time.monotonic(), "hidden": hidden, "seq": seq}
                page_seen = True
    return jsonify(ok=True)


@app.post("/api/bye")
def api_bye():
    """A page is being closed (or left for another page)."""
    page, seq, _ = page_message()
    if page:
        with pages_lock:
            if not outdated(page, seq):
                pages.pop(page, None)
                closed_pages[page] = seq
    return jsonify(ok=True)


@app.get("/api/browse")
def api_browse():
    """Sub-folders of a folder, each marked if it is a project, and the folders above it (crumbs, from the top).
    With no path: the folder of the last project used, else the Startup Folder from Settings. With exact
    (for suggestions while a path is typed), a path that is not a folder gives no folders instead."""
    data = load_store()
    raw = request.args.get("path", "")
    path = full_path(raw) if raw else None
    if request.args.get("exact") and (path is None or not os.path.isdir(path)):
        return jsonify(path="", dirs=[], is_project=False, crumbs=[], sep=os.sep)
    if path is None or not os.path.isdir(path):
        last = data["project"]
        path = os.path.dirname(last) if last and os.path.isdir(last) else projects_dir(data)
        if not os.path.isdir(path):
            path = DEFAULT_PROJECTS
    dirs = [{"name": d, "path": os.path.join(path, d), "is_project": is_project(os.path.join(path, d))}
            for d in subdirs(path)]
    crumbs, p = [], path
    while True:
        crumbs.append({"name": os.path.basename(p) or p, "path": p})   # the top (/ or C:\) has no basename
        up = os.path.dirname(p)
        if up == p:
            break
        p = up
    return jsonify(path=path, dirs=dirs, is_project=is_project(path),
                   crumbs=crumbs[::-1], sep=os.sep)


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
        return jsonify(error="Main program: choose one of the project's .py files"), 400
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
    files = top_level(rel for _, rel in release_files(path, opts, zip_files(path, opts)[1]))
    req = requirements_file(path, opts) or requirements_places(opts)[0]
    return Response(make_install_py(os.path.basename(path), opts, req, files), mimetype="text/plain")


def config_view():
    data = load_store()
    p = projects_dir(data)
    return {
        "projects_dir": p, "projects_dir_found": os.path.isdir(p),
        "defaults": {"projects_dir": DEFAULT_PROJECTS, "listen": DEFAULT_LISTEN, "start_port": START_PORT},
        "preferred_port": preferred_port(data),
        "listen": listen(data),
        "url": f"http://{HOST}:{PORT}/" if PORT else "",   # where this tool is listening right now
        "python": base_python(),   # the Python venvs are made with
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
        return jsonify(error="Startup Folder: invalid value"), 400
    if raw.strip():   # empty means "use the default"
        path = full_path(raw)
        if path is None:
            return jsonify(error="Startup Folder: enter a full path, such as /home/pi or C:\\Projects"), 400
        if not os.path.isdir(path):
            return jsonify(error=f"Startup Folder: '{path}' is not an existing folder"), 400
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
    d = request.get_json(silent=True) or {}
    project, opts, err = check_project(d.get("project", ""))
    if err:
        return jsonify(error=err), 400
    exclude = d.get("exclude", [])
    if not isinstance(exclude, list) or not all(isinstance(x, str) for x in exclude):
        return jsonify(error="Invalid exclusion list"), 400
    if not set(exclude) <= {rel for _, rel in release_files(project, opts)}:
        return jsonify(error="An excluded file is not in the project"), 400
    needed = set(exclude) & needed_files(project, opts)
    if needed:
        return jsonify(error=f"{', '.join(sorted(needed))} cannot be left out: install.py needs it"), 400
    lines = zip_job.begin()
    if lines is None:
        return jsonify(error="Already running - stop it first"), 409
    err = remember_project(project, exclude=sorted(exclude))   # the ticks come back next time
    if err:
        lines.append(f"Could not remember these selections: {err}")
    threading.Thread(target=run_zip_job, args=(lines, project, opts, exclude), daemon=True).start()
    return jsonify(ok=True)


@app.get("/makezip/api/download")
def zip_download():
    """Download one of the zips in a project's standalone-zip folder."""
    project = full_path(request.args.get("project", ""))
    name = request.args.get("name", "")
    if project is None or not os.path.isdir(project) or name not in {z["name"] for z in release_zips(project)}:
        return jsonify(error="No such zip file"), 404
    return send_from_directory(os.path.join(project, ZIP_DIR), name, as_attachment=True)


# ---------- routes: Prepare ----------
@app.post("/prepare/api/start")
def prepare_start():
    project, opts, err = check_project((request.get_json(silent=True) or {}).get("project", ""), need_requirements=False)
    if err:
        return jsonify(error=err), 400
    lines = prepare_job.begin()
    if lines is None:
        return jsonify(error="Already running - stop it first"), 409
    err = remember_project(project)
    if err:
        lines.append(f"Could not remember this selection: {err}")
    threading.Thread(target=run_prepare_job, args=(lines, project, opts), daemon=True).start()
    return jsonify(ok=True)


# ---------- pages ----------
# The pages' HTML, CSS and JS live in the web folder next to this script. base.html is the frame every page
# shares (style.css and common.js go into it); each page is <name>.html, its Vue template, plus <name>.js if it has a script.
# Vue and Vuetify are in web/vendor (fetched by update_vendor.py), so the pages work without internet access.
WEB_DIR = os.path.join(SCRIPT_DIR, "web")
VENDOR_DIR = os.path.join(WEB_DIR, "vendor")


@app.get("/vendor/<path:name>")
def vendor_file(name):
    return send_from_directory(VENDOR_DIR, name, max_age=86400)


def web_file(name):
    with open(os.path.join(WEB_DIR, name), encoding="utf-8") as f:
        return f.read()


def render(title, page):
    script = web_file(page + ".js") if os.path.isfile(os.path.join(WEB_DIR, page + ".js")) else ""
    return (web_file("base.html").replace("__CSS__", web_file("style.css"))
            .replace("__TITLE__", title).replace("__BODY__", web_file(page + ".html"))
            .replace("__SCRIPT__", script).replace("__COMMON_JS__", web_file("common.js")))


HOME_PAGE = render("Prep and Package", "home")
ZIP_PAGE = render("Make Zip", "makezip")
PREPARE_PAGE = render("Prepare", "prepare")
SETTINGS_PAGE = render("Prep and Package - Settings", "settings")
_README_TEMPLATE = render("Prep and Package - Instructions", "readme")


def build_readme(is_windows):
    """The instructions page, with the setup steps and examples for Windows or Linux."""
    if is_windows:
        text = {
            "__SETUP__": (
                '<p><b>Windows</b> (10 or later). Install Python 3.8 or later (from python.org, tick "Add python.exe to PATH"). '
                'Then, in Command Prompt in the <code>Prep_and_Package</code> folder, create the app\'s venv and install Flask into it, once:</p>'
                '<pre>py -m venv venv\nvenv\\Scripts\\python -m pip install -r code\\requirements.txt</pre>'
                '<p>Then start the app:</p><pre>venv\\Scripts\\python code\\prep_and_package.py</pre>'
                '<p>Windows may ask whether to allow Python through the firewall. Allow it on private networks, '
                'or other computers will not be able to open the page.</p>'),
            "__HIDDEN_NOTE__": "The name starts with a dot, but Windows does not hide it: it shows in File Explorer like any other file.",
        }
    else:
        text = {
            "__SETUP__": (
                '<p><b>Linux</b> (for example Raspberry Pi OS / Debian Trixie). In the <code>Prep_and_Package</code> folder, '
                'create the app\'s venv and install Flask into it, once:</p>'
                '<pre>sudo apt install python3-venv\npython3 -m venv venv\nvenv/bin/python -m pip install -r code/requirements.txt</pre>'
                '<p>Then start the app from a terminal:</p><pre>./run.sh</pre>'),
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


@app.get("/prepare")
def prepare_page():
    return PREPARE_PAGE


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
    logger.info(f"Venvs are made with {base_python()}")
    logger.info(f"Settings file: {SETTINGS_FILE} ({'found' if os.path.isfile(SETTINGS_FILE) else 'not found'})")
    check_settings_writable()
    data = load_store()
    local = listen(data) == "local"
    logger.info("Listening for this computer only" if local else "Listening for any computer on the network")
    HOST, PORT = validate_port(preferred_port(data), local)
    # No settings file yet = first run: start on the instructions. Otherwise start on Home as normal.
    path = "/" if os.path.isfile(SETTINGS_FILE) else "/readme"
    host = "localhost" if HOST in ("0.0.0.0", "127.0.0.1", "::") else HOST
    print(f" * Prep and Package: http://{host}:{PORT}{path}")
    threading.Timer(1.0, open_browser, args=(path,)).start()  # give the server a moment to start
    threading.Thread(target=watch_pages, daemon=True).start()
    logger.info("The app stops by itself once every page of it has been closed")
    app.run(host=HOST, port=PORT, threaded=True)


if __name__ == "__main__":
    main()
