#!/usr/bin/env python3
"""Prep and Package - one small web app that prepares standalone Python programs and DWC plugin folders.
  /          Home        choose a tool
  /prepare   Prepare     make the project's requirements.txt from its imports, create its venv and install into it
  /workflow  Copy Plugin Release Workflow   copy the GitHub release workflow for DWC plugins into a plugin's folder
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
checks that the venv can import every package, and adds run.sh and run.bat launchers (both, for Linux and Windows) where they are missing.

Copy Plugin Release Workflow copies the files in the "plugin release workflow" folder next to this script
(.github/workflows/release.yml and its notes, and scripts/) into the top of a plugin's git checkout on disk; it never
commits or pushes, so the files reach GitHub when the user commits and pushes them. The workflow's
settings files (WORKFLOW_SETTINGS) belong to the plugin, so one already there is kept unless asked to replace it.

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
import filecmp
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

from flask import Flask, jsonify, request, send_from_directory

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
RECENT_MAX = 8   # most recent projects (and plugin folders) remembered
README = "README.md"
# Never looked in for .py files, and nor are a project's own folders of release zips at its top
SKIP_DIRS = ("__pycache__", "venv", ".venv", ".git", "node_modules")
SKIP_TOP_DIRS = ("standalone-zip", "dist")
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


prepare_job = Job()   # Prepare
JOBS = (prepare_job,)


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
                    launcher=launcher_name() if os.path.isfile(os.path.join(path, launcher_name())) else "")
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


# ---------- Copy Plugin Release Workflow ----------
# The GitHub release workflow for DWC plugins lives in the "plugin release workflow" folder next to this script, laid
# out as it goes into a plugin's folder: .github/workflows/release.yml (and its notes) and scripts/. It is copied into
# the top of the plugin's git checkout on disk, as GitHub only runs workflows from the top of a repository. Only files on
# disk are written: nothing is committed or pushed.
WORKFLOW_DIR = os.path.join(SCRIPT_DIR, "plugin release workflow")
# The workflow's settings: they belong to the plugin, so a copy already in its folder is kept unless asked otherwise
WORKFLOW_SETTINGS = ("scripts/release-channel.txt", "scripts/release-exclude.txt", "scripts/release-titles.txt")
# Not looked in for plugin.json (as the workflow and release.sh skip them)
MANIFEST_SKIP = (".git", "node_modules", "venv")
MANIFEST_DEPTH = 3   # how far below a folder Browse looks for a plugin.json when marking plugin folders


def workflow_files():
    """The workflow's files, as paths relative to its folder with forward slashes."""
    out = []
    for dirpath, dirnames, filenames in os.walk(WORKFLOW_DIR):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        out += [os.path.relpath(os.path.join(dirpath, n), WORKFLOW_DIR).replace(os.sep, "/") for n in sorted(filenames)]
    return out


def plugin_manifests(repo):
    """The plugin.json files in repo, relative to it: the one at the top first, then the shallowest, as the workflow
    and release.sh choose them (they use the first)."""
    found = []
    for seen, (dirpath, dirnames, filenames) in enumerate(os.walk(repo)):
        if seen >= SEARCH_LIMIT:
            break
        dirnames[:] = [d for d in dirnames if d not in MANIFEST_SKIP]
        if "plugin.json" in filenames:
            found.append(os.path.relpath(os.path.join(dirpath, "plugin.json"), repo).replace(os.sep, "/"))
    return sorted(found, key=lambda p: (p.count("/"), p.lower()))


def has_manifest(folder, depth=MANIFEST_DEPTH):
    """Whether there is a plugin.json in folder or up to depth levels below it (for marking folders in Browse)."""
    level = [folder]
    for _ in range(depth + 1):
        below = []
        for f in level:
            if os.path.isfile(os.path.join(f, "plugin.json")):
                return True
            below += [os.path.join(f, d) for d in subdirs(f) if d not in MANIFEST_SKIP]
        level = below[:200]
    return False


def git_top(folder):
    """The top of the git repository folder is in (the nearest folder at or above it with a .git), or None."""
    p = folder
    while True:
        if os.path.exists(os.path.join(p, ".git")):
            return p
        up = os.path.dirname(p)
        if up == p:
            return None
        p = up


def workflow_plan(repo, replace_settings):
    """What copying the workflow into repo would do to each file: new, replace, same (already identical) or keep
    (a settings file of the plugin's own, left as it is)."""
    plan = []
    for rel in workflow_files():
        src, dst = os.path.join(WORKFLOW_DIR, rel), os.path.join(repo, rel)
        setting = rel in WORKFLOW_SETTINGS
        if not os.path.lexists(dst):
            action = "new"
        elif not os.path.isfile(dst):
            action = "blocked"   # a folder (or something else) is in the way
        elif filecmp.cmp(src, dst, shallow=False):
            action = "same"
        elif setting and not replace_settings:
            action = "keep"
        else:
            action = "replace"
        plan.append({"file": rel, "action": action, "setting": setting})
    return plan


def workflow_view(raw, replace_settings=False):
    """What the Copy Plugin Release Workflow page needs to know about a folder."""
    path = full_path(raw)
    if path is None:
        return {"exists": False, "error": "Enter the full path of the plugin's folder (~ is fine)"}
    if not os.path.isdir(path):
        return {"exists": False, "path": path, "error": f"'{path}' is not an existing folder"}
    top = git_top(path)
    manifests = plugin_manifests(path)
    problems, warnings = [], []
    if top and top != path:
        problems.append(f"This folder is inside the git checkout {top}. GitHub only runs workflows from the top of a "
                        f"repository, so choose {top} instead.")
    if not manifests:
        warnings.append("There is no plugin.json in this folder or below it, so this is not a DWC plugin: the workflow "
                        "will release a standalone ZIP of the whole repository (<repository>-<version>.zip, the version "
                        "taken from the tag), with no build and no DWC dependency.")
    elif len(manifests) > 1 and "/" in manifests[0]:
        problems.append("There is more than one plugin.json (" + ", ".join(manifests) + ") and none at the top: the "
                        "workflow would stop with an error. Remove the extra ones first.")
    elif len(manifests) > 1:
        warnings.append(f"More than one plugin.json: the workflow uses {manifests[0]} (the one at the top).")
    if not top:
        warnings.append("This folder is not a git checkout yet. The workflow only runs once it is committed and pushed to GitHub.")
    if not os.path.isdir(WORKFLOW_DIR):
        problems.append(f"The workflow's files are missing: there is no {WORKFLOW_DIR}")
    return {"exists": True, "path": path, "name": os.path.basename(path), "git": top == path,
            "manifests": manifests, "problems": problems, "warnings": warnings,
            "plan": workflow_plan(path, replace_settings) if os.path.isdir(WORKFLOW_DIR) else []}


def copy_workflow(repo, replace_settings):
    """Copy the workflow's files into repo as workflow_plan says. Returns [(file, what was done)]."""
    done = []
    for item in workflow_plan(repo, replace_settings):
        rel, action = item["file"], item["action"]
        if action in ("new", "replace"):
            dst = os.path.join(repo, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(WORKFLOW_DIR, rel), dst)   # keeps release.sh executable
            done.append((rel, "added" if action == "new" else "replaced"))
        elif action == "blocked":
            raise OSError(f"{rel} cannot be copied: something that is not a file is in the way")
    return done


def remember_workflow_target(path):
    """Make path the last plugin folder used (and the most recent). Returns an error message, or None."""
    with save_lock:
        data = load_store()
        recent = data.get("workflow_recent")
        recent = [x for x in recent if isinstance(x, str)] if isinstance(recent, list) else []
        data["workflow_target"] = path
        data["workflow_recent"] = ([path] + [x for x in recent if x != path])[:RECENT_MAX]
        return write_store(data)


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


def write_launcher(project, opts, req, lines):
    """Add run.sh and run.bat to the project, to start the program with its venv, unless they are there already. Both
    are made whichever computer Prepare runs on, so a release of the project (zipped from its repository) can be
    started on Linux and on Windows. With no venv - e.g. the project just unzipped from a release, which never holds
    one - the launcher makes it first and installs req (requirements.txt, relative to the project) into it. On Linux
    the venv can see the system's packages (--system-site-packages); on Windows it cannot, as Prepare makes it."""
    main = opts["main"]
    win_main, win_req = main.replace("/", "\\"), req.replace("/", "\\")
    launchers = {
        "run.sh": ("#!/bin/bash\n"
                   "# Start the program with its venv (made by Prepare in Prep_and_Package). With no venv - e.g. just\n"
                   f"# unzipped from a release - it is made first, able to see the system's packages, and {req}\n"
                   "# is installed into it.\n"
                   'cd "$(dirname "$0")" || exit 1\n'
                   "if [ ! -x venv/bin/python ]; then\n"
                   f'\techo "First run: making the venv and installing {req} into it"\n'
                   f"\tpython3 -m venv --system-site-packages venv && venv/bin/python -m pip install -r {req} || {{\n"
                   '\t\techo "Could not make the venv. On Debian or Raspberry Pi OS the venv module needs: sudo apt install python3-venv"\n'
                   "\t\trm -rf venv   # a half-made venv would be taken as ready next time\n"
                   "\t\texit 1\n"
                   "\t}\n"
                   "fi\n"
                   f'exec venv/bin/python -u {main} "$@"\n'),
        "run.bat": ("@echo off\r\n"
                    "rem Start the program with its venv (made by Prepare in Prep_and_Package). With no venv - e.g. just\r\n"
                    f"rem unzipped from a release - it is made first and {win_req} is installed into it.\r\n"
                    'cd /d "%~dp0"\r\n'
                    "if not exist venv\\Scripts\\python.exe (\r\n"
                    f"  echo First run: making the venv and installing {win_req} into it\r\n"
                    "  py -3 -m venv venv 2>nul || python -m venv venv || goto failed\r\n"
                    f"  venv\\Scripts\\python.exe -m pip install -r {win_req} || goto failed\r\n"
                    ")\r\n"
                    f"venv\\Scripts\\python.exe -u {win_main} %*\r\n"
                    "exit /b\r\n"
                    ":failed\r\n"
                    "echo Could not make the venv: install Python 3 from python.org and run this again\r\n"
                    "rmdir /s /q venv 2>nul\r\n"
                    "exit /b 1\r\n"),
    }
    for name, text in launchers.items():
        path = os.path.join(project, name)
        if os.path.exists(path):
            lines.append(f"{name}: already there, left as it is")
            continue
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
        write_launcher(project, opts, req.replace(os.sep, "/"), lines)

        version = program_version(project, opts["main"])
        lines.append("")
        lines.append("Ready:" if code == 0 else "Prepared, with the problems above:")
        lines.append(f"  main program  {opts['main']}" + (f", version {version}" if version else ", no version set"))
        lines.append(f"  requirements  {req}")
        lines.append(f"  venv          {venv}")
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


add_job_routes("/prepare", "prepare", prepare_job)


@app.get("/api/status")
def api_status():
    return jsonify(prepare=prepare_job.busy)


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
    """Sub-folders of a folder, each marked if it is a project (with kind=plugin: if it holds a plugin.json),
    and the folders above it (crumbs, from the top).
    With no path: the folder of the last project used, else the Startup Folder from Settings. With exact
    (for suggestions while a path is typed), a path that is not a folder gives no folders instead."""
    data = load_store()
    raw = request.args.get("path", "")
    path = full_path(raw) if raw else None
    # kind=plugin: for Copy Plugin Release Workflow, which marks folders holding a plugin.json instead of projects
    plugins = request.args.get("kind") == "plugin"
    marks = has_manifest if plugins else is_project
    if request.args.get("exact") and (path is None or not os.path.isdir(path)):
        return jsonify(path="", dirs=[], is_project=False, crumbs=[], sep=os.sep)
    if path is None or not os.path.isdir(path):
        last = data.get("workflow_target") if plugins else data["project"]
        last = last if isinstance(last, str) else ""
        path = os.path.dirname(last) if last and os.path.isdir(last) else projects_dir(data)
        if not os.path.isdir(path):
            path = DEFAULT_PROJECTS
    dirs = [{"name": d, "path": os.path.join(path, d), "is_project": marks(os.path.join(path, d))}
            for d in subdirs(path)]
    crumbs, p = [], path
    while True:
        crumbs.append({"name": os.path.basename(p) or p, "path": p})   # the top (/ or C:\) has no basename
        up = os.path.dirname(p)
        if up == p:
            break
        p = up
    return jsonify(path=path, dirs=dirs, is_project=marks(path),
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


# ---------- routes: Copy Plugin Release Workflow ----------
@app.get("/workflow/api/target")
def workflow_target():
    """The last plugin folder used and the recent ones (no path), or what copying into `path` would do."""
    if request.args.get("path") is None:
        data = load_store()
        recent = data.get("workflow_recent") if isinstance(data.get("workflow_recent"), list) else []
        last = data.get("workflow_target") if isinstance(data.get("workflow_target"), str) else ""
        return jsonify(target=last, recent=[x for x in recent if isinstance(x, str) and os.path.isdir(x)])
    return jsonify(workflow_view(request.args["path"], request.args.get("replace_settings") == "1"))


@app.post("/workflow/api/copy")
def workflow_copy():
    d = request.get_json(silent=True) or {}
    replace_settings = d.get("replace_settings") is True
    view = workflow_view(d.get("path", ""), replace_settings)
    if not view["exists"]:
        return jsonify(error=view["error"]), 400
    if view["problems"]:
        return jsonify(error=view["problems"][0]), 400
    try:
        done = copy_workflow(view["path"], replace_settings)
    except OSError as e:
        return jsonify(error=f"Could not copy the workflow: {e}"), 500
    err = remember_workflow_target(view["path"])
    return jsonify(done=[{"file": f, "what": w} for f, w in done], remember_error=err,
                   view=workflow_view(view["path"], replace_settings))


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
WORKFLOW_PAGE = render("Copy Plugin Release Workflow", "workflow")
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


@app.get("/workflow")
def workflow_page():
    return WORKFLOW_PAGE


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
