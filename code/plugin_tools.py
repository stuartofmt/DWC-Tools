#!/usr/bin/env python3
"""DWC tools - one small web app for DuetWebControl plugin development.
  /              Home          choose a tool
  /createplugin  Create a Plugin  build / zip a DWC plugin
  /dwcversion    Create DWC Version    clone a DWC version, npm install, run its dev server
  /settings      Settings      the folders holding the DWC versions and the plugins
  /readme        Instructions on use

The two tools have separate jobs, so a DWC dev server can keep running while you build plugins.

Setup (Linux, e.g. Raspberry Pi OS):  sudo apt install python3-venv git nodejs npm
Setup (Windows 10 or later):          install Python 3.8+, Git for Windows and Node.js
Install: unzip the release and run ./run.sh (Windows: run.bat), which runs install.py. It copies the app to an install folder,
         creates its venv with Flask in it and adds run.sh / run.bat, then starts the app (unless --no-run is given).
Run:     run.sh (Windows: run.bat) in the install folder; from a copy of the repository, ./run.sh once the venv exists
         (made by Prepare in Prep_and_Package, or: python3 -m venv venv; venv/bin/python -m pip install -r code/requirements.txt)
The operating system (Linux or Windows) is detected at start-up; no zip program is needed on either.
Keep the web folder (the pages' HTML, CSS and JS) next to this script.
Open:    the address printed at start-up: this computer's network address (or 127.0.0.1 when Settings says
         "This computer only"), on the preferred port from the Settings page, or else the first free port from 17800.
         The first time (no settings file yet) the browser opens at /readme instead of Home.

Folder layout (both folders can be changed on the Settings page; until then they are the folder this script is in):
  <DWC versions folder>/<dwc version>/                  <- DWCVersion clones into here
  <Plugins folder>/<plugin name>/<plugin version>/<Code folder>/plugin.json
  <plugin version> is any folder name (e.g. plugin3.7.x). The Code folder is the folder holding plugin.json, found
  automatically (the plugin version folder itself, or a folder up to 3 levels below it, e.g. Code); it can be
  changed per plugin version on the Create a Plugin page.
Result of CreatePlugin:
  <Plugins folder>/<plugin name>/<plugin version>/<plugin name>-<manifest version>.zip

The folders, the preferred port, where to listen, the remembered CreatePlugin exclusions and the last selections made in
each tool (they become the defaults next time) are stored together in .plugin_build_exclusions.json,
in the install folder.
"""
import json
import logging
import os
import platform
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import queue
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from glob import glob

from flask import Flask, jsonify, request

pluginVersion = '1.0.0'

PLATFORM = platform.system()          # "Linux", "Windows", ...
IS_WINDOWS = PLATFORM == "Windows"    # everything else is handled like Linux
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))   # where this script is installed (<install folder>/code)
INSTALL_DIR = os.path.dirname(SCRIPT_DIR)                   # the install folder (holds run.sh / run.bat)
# Until they are set on the Settings page, both folders are the install folder
DEFAULT_DWC_VERSIONS = INSTALL_DIR
DEFAULT_PLUGINS = INSTALL_DIR
DEFAULTS = {"dwc_versions_dir": DEFAULT_DWC_VERSIONS, "plugins_dir": DEFAULT_PLUGINS}
# How deep below a plugin version folder plugin.json is looked for, and folders never looked in
FIND_DEPTH = 3
NOT_CODE_DIRS = ("node_modules", "dist", "pkg")
# Who can open this tool's page: "network" (any computer on the network) or "local" (this computer only)
DEFAULT_LISTEN = "network"
# The address this tool listens on is worked out at start-up by validate_port() (see main())
HOST = "127.0.0.1"
PORT = 0
# Settings file: the two folders above, the preferred port, the ticked exclusion files remembered per
# DWC version / plugin / plugin version, and the last selections made in each tool. It lives in the install
# folder. No other location is ever looked at, and no environment variable changes it.
SETTINGS_NAME = ".plugin_build_exclusions.json"
SETTINGS_FILE = os.path.join(INSTALL_DIR, SETTINGS_NAME)
# Always left out of a zip-only build (files ticked in the UI are left out as well)
ALWAYS_SKIP_DIRS = ("__pycache__", "venv")
STASH_PREFIX = ".excluded-"   # folders holding files moved aside during a build; never part of a plugin
ALWAYS_SKIP_SUFFIXES = (".log", ".pyc")
REPO = "https://github.com/Duet3D/DuetWebControl"
GIT_ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0")  # never hang waiting for a git password

app = Flask(__name__)
logger = logging.getLogger("plugin_tools")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# Both dev servers print their address: Vite "  ➜  Local:   http://localhost:3000/" (DWC 3.7+) and
# Vue CLI "  - Local:   http://localhost:8080/" (older DWC)
LOCAL_URL = re.compile(r"Local:\s+(https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?\S*)")
READY_TIMEOUT = 30   # seconds to wait for that URL to answer HTTP 200
READY = "ready"      # returned by Job.serve() when the dev server is up and left running
CODE_FILES_LIMIT = 3000   # most files the Exclude list shows


# The dev server is on this computer, so never send the check through a proxy set in the environment
NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_status(url):
    """HTTP status of url (0 = no answer)."""
    try:
        with NO_PROXY.open(url, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def force_quit(code=1):
    """Stop the app straight away (used when start-up cannot continue)."""
    logger.critical("Exiting")
    sys.exit(code)


def port_in_use(ip_address, port):
    #  A successful connection means something is already listening there
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex((ip_address, port)) == 0


def validate_port(port=0, local=False, start_port=17800, max_tries=100):
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
def popen(cmd, cwd=None, env=None):
    """Start cmd with its output piped back. It gets its own process group (Linux: session) so that
    Stop can end it together with everything it starts (npm -> node -> the dev server ...)."""
    exe = shutil.which(cmd[0])   # on Windows this finds npm.cmd, which Popen cannot find by the bare name
    full = [exe or cmd[0]] + list(cmd[1:])
    extra = {}
    if IS_WINDOWS:
        extra["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    else:
        extra["start_new_session"] = True
    return subprocess.Popen(
        full, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",   # npm prints UTF-8 whatever the Windows code page is
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


def rmtree_force(path, ignore_errors=False):
    """Delete a folder tree. Windows refuses to delete read-only files (git makes plenty), so those are
    made writable first, and the long-path prefix is used because node_modules gets very deep."""
    if IS_WINDOWS:
        path = os.path.abspath(path)
        path = "\\\\?\\UNC\\" + path[2:] if path.startswith("\\\\") else "\\\\?\\" + path

    def retry(func, failed_path, *_):
        os.chmod(failed_path, stat.S_IWRITE)
        func(failed_path)

    handler = {"onexc": retry} if sys.version_info >= (3, 12) else {"onerror": retry}
    try:
        shutil.rmtree(path, **handler)
    except OSError:
        if not ignore_errors:
            raise


# ---------- background jobs ----------
class Job:
    """One background job (a run of commands) whose output the page polls.
    Each tool has its own Job, so they can run at the same time."""

    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.run = 0
        self.lines = []
        self.stopping = False
        self.busy = False
        self.service = None       # a server left running in the background after the job finished
        self.service_url = ""

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

    def step(self, lines, cmd, cwd, title=None, env=None):
        """Run one command, streaming its output. Returns the exit code, or None if stopped."""
        if title:
            lines.append(f"=== {title} ===")
        lines.append("$ " + " ".join(cmd))
        with self.lock:
            if self.stopping:
                return None
            try:
                proc = popen(cmd, cwd, env)
            except OSError as e:
                lines.append(f"Could not start {cmd[0]}: {e}")
                return 127
            self.proc = proc
        for line in proc.stdout:
            lines.append(ANSI.sub("", line.rstrip("\n")))
        return proc.wait()

    def serve(self, lines, cmd, cwd, title=None, env=None):
        """Run a long-lived dev server. As soon as it prints its Local URL and that URL answers HTTP 200,
        return READY and leave it running in the background (its output keeps flowing into the log).
        Otherwise wait for it to exit and return the exit code, like step()."""
        if title:
            lines.append(f"=== {title} ===")
        lines.append("$ " + " ".join(cmd))
        with self.lock:
            if self.stopping:
                return None
            try:
                proc = popen(cmd, cwd, env)
            except OSError as e:
                lines.append(f"Could not start {cmd[0]}: {e}")
                return 127
            self.proc = proc
        # The output is read in its own thread, so the server never stalls on a full pipe while the URL is checked
        urls = queue.Queue()
        threading.Thread(target=self._read_server, args=(lines, proc, urls), daemon=True).start()
        while True:
            url = urls.get()
            if url is None:   # its output has ended: the server has exited
                return proc.wait()
            if self._answers_200(lines, proc, url):
                self.service, self.service_url = proc, url
                return READY

    def _read_server(self, lines, proc, urls):
        """Copy the dev server's output into the log for as long as it runs (also after the job has
        finished), passing each Local URL it prints to serve(). None is passed when the output ends."""
        for line in proc.stdout:
            text = ANSI.sub("", line.rstrip("\n"))
            lines.append(text)
            m = LOCAL_URL.search(text)
            if m:
                urls.put(m.group(1))
        urls.put(None)
        code = proc.wait()
        if self.service is proc:   # it had been left running after the job finished
            lines.append("--- dev server stopped ---" if self.stopping else f"--- dev server exited (code {code}) ---")
            self.service, self.service_url = None, ""

    def _answers_200(self, lines, proc, url):
        lines.append(f"Checking {url} ...")
        status = None
        for _ in range(READY_TIMEOUT):
            if self.stopping or proc.poll() is not None:
                return False
            status = http_status(url)
            if status == 200:
                lines.append("HTTP 200 - dev server is up, so the job is done "
                             "(the server keeps running; the job does not wait for any further bundling)")
                return True
            time.sleep(1)
        lines.append(f"No HTTP 200 yet (last status: {status}) - still waiting for the dev server")
        return False

    def service_running(self):
        p = self.service
        return p is not None and p.poll() is None

    def terminate(self, force_after=None):
        """Stop the current command and everything it started (npm, node, ...)."""
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
        return {"run": self.run, "total": len(lines), "lines": lines[n:], "running": self.busy,
                "service": self.service_url if self.service_running() else ""}


plugin_job = Job()   # CreatePlugin
dwc_job = Job()      # DWCVersion
JOBS = (plugin_job, dwc_job)


# ---------- settings file: folders + remembered exclusions ----------
save_lock = threading.Lock()


def load_store():
    """Settings file layout: {"format": 2, "config": {...}, "last": {tool: {...}},
    "exclusions": {dwc: {plugin: {pver: [files]}}}, "code_paths": {plugin: {pver: code folder}}}. A missing or unrecognised file counts as empty."""
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict) or data.get("format") != 2:
        data = {"format": 2}
    if not isinstance(data.get("config"), dict):
        data["config"] = {}
    if not isinstance(data.get("exclusions"), dict):
        data["exclusions"] = {}
    if not isinstance(data.get("last"), dict):
        data["last"] = {}
    if not isinstance(data.get("code_paths"), dict):
        data["code_paths"] = {}
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


# The settings readers below take the already loaded settings as `data`, to save reading the file again
def text_setting(key, default, data=None):
    v = (data or load_store())["config"].get(key)
    return v if isinstance(v, str) and v.strip() else default


def dwc_versions_dir(data=None):
    return text_setting("dwc_versions_dir", DEFAULT_DWC_VERSIONS, data)


def plugins_dir(data=None):
    return text_setting("plugins_dir", DEFAULT_PLUGINS, data)


def listen(data=None):
    """"local" (this computer only) or "network". Only read at start-up."""
    v = (data or load_store())["config"].get("listen")
    return v if v in ("local", "network") else DEFAULT_LISTEN


def code_dir_for(plugin, pver, code):
    return os.path.normpath(os.path.join(plugins_dir(), plugin, pver, code))


def skip_dir(name):
    return name in ALWAYS_SKIP_DIRS or name.startswith(STASH_PREFIX)


def is_old_zip(top, rel):
    """A .zip at the top of the Code folder when that is the plugin version folder itself (top): a previous
    result, which is deleted before each run, so it is never listed or zipped."""
    return top and "/" not in rel and rel.lower().endswith(".zip")


def preferred_port(data=None):
    """Port this tool's web page should use (0 = no preference: the first free port from 17800).
    Only read at start-up."""
    v = (data or load_store())["config"].get("preferred_port", 0)
    ok = isinstance(v, int) and not isinstance(v, bool) and (v == 0 or 1024 <= v <= 65535)
    return v if ok else 0


def saved_excludes(dwc, plugin, pver):
    """Files ticked the last time this DWC version / plugin / plugin version was run."""
    try:
        files = load_store()["exclusions"][dwc][plugin][pver]
    except (KeyError, TypeError):
        return []
    return [x for x in files if isinstance(x, str)] if isinstance(files, list) else []


def saved_last(tool):
    """The selections made the last time this tool was run (empty if never)."""
    v = load_store()["last"].get(tool)
    return v if isinstance(v, dict) else {}


def save_last(tool, values):
    """Remember a tool's selections as the next defaults. Returns an error message, or None."""
    with save_lock:
        data = load_store()
        data["last"][tool] = values
        return write_store(data)


def saved_code_path(plugin, pver):
    """The Code folder chosen on Create a Plugin for this plugin version (None if it was left automatic)."""
    try:
        v = load_store()["code_paths"][plugin][pver]
    except (KeyError, TypeError):
        return None
    return v if isinstance(v, str) else None


def remember_plugin_run(dwc, plugin, pver, files, custom_code):
    """CreatePlugin: remember the exclusions for this combination, the Code folder when it was changed from the
    one found automatically (custom_code; None = automatic), and the selections themselves.
    Returns an error message, or None."""
    with save_lock:
        data = load_store()
        codes = data["code_paths"]
        if not isinstance(codes.get(plugin), dict):
            codes[plugin] = {}
        if custom_code is None:
            codes[plugin].pop(pver, None)
            if not codes[plugin]:
                del codes[plugin]
        else:
            codes[plugin][pver] = custom_code
        node = data["exclusions"]
        for key in (dwc, plugin):
            if not isinstance(node.get(key), dict):
                node[key] = {}
            node = node[key]
        if files:
            node[pver] = files
        else:
            node.pop(pver, None)
        data["last"]["createplugin"] = {"dwc": dwc, "plugin": plugin, "plugin_version": pver}
        return write_store(data)


# ---------- folder listings ----------
def natural(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def subdirs(path):
    """Sub-folder names of path, naturally sorted (3.6 before 3.10)."""
    try:
        names = [d for d in os.listdir(path)
                 if os.path.isdir(os.path.join(path, d)) and not d.startswith(".")]
    except OSError:
        return []
    return sorted(names, key=natural)


VERSION_NAME = re.compile(r"[0-9][0-9A-Za-z._-]*")  # 3.5.1, 3.6-dev ... (git tag is "v" + this)


def version_key(name):
    """Sort key for a version name: 3.10 after 3.6, and a release after its pre-releases
    (3.7.0-beta.2 < 3.7.0-rc.2 < 3.7.0)."""
    release, _, pre = name.partition("-")
    return natural(release), not pre, natural(pre)


def dwc_versions(base=None):
    """DWC version folders: sub-folders of the DWC versions folder (base) whose name looks like a version,
    newest first."""
    return sorted((d for d in subdirs(base or dwc_versions_dir()) if VERSION_NAME.fullmatch(d)),
                  key=version_key, reverse=True)


def has_manifest(pvd, code):
    return os.path.isfile(os.path.join(pvd, code, "plugin.json"))


def find_code_paths(pvd):
    """Folders holding plugin.json in the plugin version folder pvd: pvd itself ("") and the folders up to
    FIND_DEPTH levels below it, as relative paths with forward slashes, shallowest first.
    A folder holding plugin.json is not looked inside."""
    found, level = [], [""]
    for _ in range(FIND_DEPTH + 1):
        below = []
        for rel in level:
            if has_manifest(pvd, rel):
                found.append(rel)
                continue
            below += [f"{rel}/{d}" if rel else d for d in subdirs(os.path.join(pvd, rel))
                      if not skip_dir(d) and d not in NOT_CODE_DIRS]
        level = below
    return found


def clean_code_path(raw):
    """A Code folder as typed ("Code", "/Code", "src\\Code", "." ...) as stored: "Code", "src/Code", or ""
    for the plugin version folder itself. None if it is not a path inside the plugin version folder."""
    if not isinstance(raw, str) or ":" in raw:
        return None
    parts = [x for x in re.split(r"[\\/]+", raw.strip()) if x and x != "."]
    return None if ".." in parts else "/".join(parts)


def code_path_for(plugin, pver, base=None):
    """Code folder of a plugin version, relative to its folder: the one chosen on Create a Plugin while it still
    holds plugin.json, otherwise the first one found automatically. None if there is none."""
    pvd = os.path.join(base or plugins_dir(), plugin, pver)
    saved = saved_code_path(plugin, pver)
    if saved is not None and has_manifest(pvd, saved):
        return saved
    found = find_code_paths(pvd)
    return found[0] if found else None


def plugin_versions(name, base=None):
    """Plugin version folders: sub-folders of the plugin's folder (base = the Plugins folder) whatever their name,
    as long as they have a Code folder (one holding plugin.json). The folder name is the version. Newest first."""
    return sorted((d for d in subdirs(os.path.join(base or plugins_dir(), name))
                   if code_path_for(name, d, base) is not None), key=version_key, reverse=True)


def code_files(plugin, pver, code, limit=CODE_FILES_LIMIT):
    """Files under the plugin's Code folder (code, relative to the plugin version folder; paths relative to it)
    that could be excluded. Things the default exclusions already remove are left out of the list.
    Returns (files, truncated): at most `limit` files, and whether there were more than that."""
    code_dir = code_dir_for(plugin, pver, code)
    out = []
    for dirpath, dirnames, filenames in os.walk(code_dir):
        dirnames[:] = [d for d in dirnames if not skip_dir(d)]
        for f in filenames:
            rel = os.path.relpath(os.path.join(dirpath, f), code_dir).replace(os.sep, "/")
            if f.endswith(ALWAYS_SKIP_SUFFIXES) or is_old_zip(code == "", rel):
                continue
            out.append(rel)
            if len(out) > limit:
                out.pop()   # one too many: there are more files than the list shows
                return sorted(out, key=str.lower), True
    return sorted(out, key=str.lower), False


def zip_folder(job, lines, out_zip, code_dir, exclude):
    """Zip the contents of code_dir into out_zip (paths inside the zip start at code_dir), leaving out
    __pycache__ and venv folders, *.log and *.pyc files, and the files in `exclude`.
    Done with Python's zipfile so that no zip program is needed (Windows has none).
    Returns the number of files added, or None if the job was stopped. A partial or empty zip is never left behind."""
    skip = set(exclude)
    count = 0
    top = os.path.normpath(code_dir) == os.path.normpath(os.path.dirname(out_zip))   # Code is the plugin version folder
    out_abs = os.path.abspath(out_zip)   # may be inside code_dir when that is the plugin version folder
    try:
        # strict_timestamps=False: files dated before 1980 are accepted instead of raising an error
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as z:
            for dirpath, dirnames, filenames in os.walk(code_dir):
                dirnames[:] = sorted(d for d in dirnames if not skip_dir(d))
                rel_dir = os.path.relpath(dirpath, code_dir).replace(os.sep, "/")
                if rel_dir != ".":
                    z.write(dirpath, rel_dir + "/")   # a folder entry, as zip -r makes
                for name in sorted(filenames):
                    rel = name if rel_dir == "." else f"{rel_dir}/{name}"
                    if name.endswith(ALWAYS_SKIP_SUFFIXES) or rel in skip or is_old_zip(top, rel):
                        continue
                    if os.path.abspath(os.path.join(dirpath, name)) == out_abs:
                        continue   # the zip being written
                    if job.stopping:
                        raise InterruptedError
                    z.write(os.path.join(dirpath, name), rel)
                    lines.append(f"  adding: {rel}")
                    count += 1
    except InterruptedError:
        count = None
    except BaseException:
        if os.path.exists(out_zip):
            os.remove(out_zip)
        raise
    if not count and os.path.exists(out_zip):   # stopped, or nothing was added: no empty zip is left behind
        os.remove(out_zip)
    return count


# ---------- CreatePlugin: file helpers ----------
def rm_zips(folder):
    for f in glob(os.path.join(folder, "*.zip")):
        os.remove(f)


def rm_build_dirs(code_dir):
    for d in ("dist", "pkg"):
        rmtree_force(os.path.join(code_dir, d), ignore_errors=True)


def stash_files(code_dir, rels, stash, moved):
    """Move the chosen files out of the Code folder into `stash`. `moved` records progress,
    so a failure half way still leaves a full list of what needs putting back."""
    for rel in rels:
        src = os.path.join(code_dir, rel)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(stash, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        moved.append(rel)


def restore_files(code_dir, moved, stash, lines):
    """Put stashed files back. Never overwrites: if the build recreated a file, the
    stashed copy is kept and reported."""
    kept = False
    for rel in moved:
        dst = os.path.join(code_dir, rel)
        if os.path.exists(dst):
            lines.append(f"Not restored (already exists): {rel}")
            kept = True
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(os.path.join(stash, rel), dst)
    if kept:
        lines.append(f"Kept copies in {stash}")
    else:
        rmtree_force(stash, ignore_errors=True)
        if moved:
            lines.append("Restored the excluded files")


def clean_bloat(root):
    """Delete __pycache__ folders, *.pyc and *.log files."""
    for dirpath, dirnames, filenames in os.walk(root):
        for d in list(dirnames):
            if d == "__pycache__":
                p = os.path.join(dirpath, d)
                if os.path.islink(p):
                    os.unlink(p)
                else:
                    rmtree_force(p, ignore_errors=True)
                dirnames.remove(d)
        for f in filenames:
            if f.endswith((".pyc", ".log")):
                os.unlink(os.path.join(dirpath, f))


# ---------- CreatePlugin: the job ----------
def run_plugin_job(lines, dwc_version, plugin, pver, code, exclude):
    job = plugin_job
    dwc_dir = os.path.join(dwc_versions_dir(), dwc_version)
    pvd = os.path.join(plugins_dir(), plugin, pver)  # plugin version dir
    code_dir = code_dir_for(plugin, pver, code)

    ok = False
    try:
        with open(os.path.join(code_dir, "plugin.json"), encoding="utf-8-sig") as f:
            manifest = json.load(f)
        this_version = manifest.get("version")
        if not this_version or not re.fullmatch(r"[0-9A-Za-z._+-]+", str(this_version)):
            raise ValueError("plugin.json has no usable 'version'")
        dwc_manifest = manifest.get("dwcVersion")
        lines.append(f"dwcVersion was reported as {'null' if dwc_manifest is None else dwc_manifest}")

        zip_file = f"{plugin}-{this_version}.zip"
        out_zip = os.path.join(pvd, zip_file)   # the name the DWC build gives it

        if dwc_manifest is None:
            lines.append("No dwcVersion in manifest therefore do not need to build")
            lines.append(f"Zipping {plugin} ({pver}) for DWC version {dwc_version}")
            if exclude:
                lines.append("Also excluding: " + ", ".join(exclude))
            rm_zips(pvd)
            lines.append(f"$ zip {out_zip}   (made by this app, no zip program needed)")
            count = zip_folder(job, lines, out_zip, code_dir, exclude)
            if count == 0:
                lines.append("Nothing to zip: every file was left out")
                if os.path.exists(out_zip):
                    os.remove(out_zip)
            ok = bool(count)
        else:
            lines.append("Cleaning out bloat and old builds")
            clean_bloat(pvd)
            rm_build_dirs(code_dir)
            lines.append(f"Build {plugin} ({pver}) for DWC version {dwc_version}")
            stash, moved = None, []
            try:
                if exclude:
                    # Moved out of Code so the build cannot include them, and put back afterwards.
                    # Kept in the plugin folder, as the Code folder may be the plugin version folder itself
                    stash = tempfile.mkdtemp(prefix=STASH_PREFIX, dir=os.path.dirname(pvd))
                    stash_files(code_dir, exclude, stash, moved)
                    lines.append("Kept out of this build (restored afterwards): " + ", ".join(moved))
                rm_zips(pvd)
                rm_zips(code_dir)
                # build-plugin.js must exist in the DWC version's ./scripts folder
                code = job.step(lines, ["node", "./scripts/build-plugin.js", code_dir], dwc_dir)
                if code == 0:
                    built = os.path.join(code_dir, zip_file)
                    if os.path.isfile(built):
                        # Move every zip the build made (from DWC 3.7 also <id>-<version>-srcmap.zip, the source
                        # maps of a stable version) next to the result. Code held no zips before the build.
                        # When Code is the plugin version folder itself, the build already put them there.
                        if os.path.normpath(code_dir) != os.path.normpath(pvd):
                            for z in sorted(glob(os.path.join(code_dir, "*.zip"))):
                                dst = os.path.join(pvd, os.path.basename(z))
                                lines.append(f"Move {z} to {dst}")
                                shutil.move(z, dst)
                        ok = True
                    else:
                        lines.append(f"Build finished but {built} was not created")
            finally:
                if stash:
                    restore_files(code_dir, moved, stash, lines)
                rm_build_dirs(code_dir)

        if ok and os.path.isfile(out_zip):
            st = os.stat(out_zip)
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
            lines.append("")
            lines.append("Resulting ZIP file")
            lines.append(f"{st.st_size:>10} bytes  {when}  {out_zip}")
    except Exception as e:
        lines.append(f"Error: {e}")
    finally:
        if job.stopping:
            lines.append("--- stopped ---")
        else:
            lines.append("--- finished OK ---" if ok else "--- FAILED ---")
        job.busy = False


# ---------- DWCVersion: the job ----------
def dev_script(version):
    """npm script that starts the dev server: 'dev' (Vite) from DWC 3.7 on, 'serve' (Vue CLI) before that."""
    m = re.match(r"(\d+)(?:\.(\d+))?", version)   # 3.5.1 -> (3, 5), 3.6-dev -> (3, 6), 3.10 -> (3, 10)
    major, minor = int(m.group(1)), int(m.group(2) or 0)
    return "dev" if (major, minor) >= (3, 7) else "serve"


def node_major():
    """Major version of the installed Node.js (None if it cannot be found or read)."""
    try:
        out = subprocess.run([shutil.which("node") or "node", "--version"], capture_output=True, text=True,
                             timeout=15, stdin=subprocess.DEVNULL).stdout
        return int(re.match(r"v?(\d+)", out.strip()).group(1))
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        return None


def serve_env(lines, script):
    """Environment for the dev server. DWC before 3.7 uses Vue CLI 4 / webpack 4, which fails with
    ERR_OSSL_EVP_UNSUPPORTED on Node 17 or later unless NODE_OPTIONS has --openssl-legacy-provider.
    Older Node refuses that option, so it is only added when Node is new enough."""
    if script != "serve":
        return None
    major = node_major()
    if major is None or major < 17:
        return None
    env = dict(os.environ)
    opts = env.get("NODE_OPTIONS", "")
    if "--openssl-legacy-provider" not in opts:
        env["NODE_OPTIONS"] = (opts + " --openssl-legacy-provider").strip()
    lines.append(f"Node {major}: NODE_OPTIONS={env['NODE_OPTIONS']} (needed by DWC versions before 3.7)")
    return env


def run_dwc_job(lines, version):
    """git clone -> npm install -> npm audit -> npm run dev, streaming output into `lines`."""
    job = dwc_job
    target = os.path.join(dwc_versions_dir(), version)
    code = None
    up_at = None   # set once the dev server answers HTTP 200
    try:
        lines.append(f"Create version v{version} in {target}")
        if os.path.isdir(target):
            lines.append("Removing existing folder")
            rmtree_force(target)
        os.makedirs(dwc_versions_dir(), exist_ok=True)

        code = job.step(lines, ["git", "clone", "--branch", "v" + version, REPO, target],
                        dwc_versions_dir(), title="Download version", env=GIT_ENV)
        if code == 0:
            code = job.step(lines, ["npm", "install"], target, title="Setup dev environment")
        if code == 0:
            # A non-zero exit here only means vulnerabilities were found, so carry on
            job.step(lines, ["npm", "audit", "--omit=dev"], target, title="Audit check")
            script = dev_script(version)
            code = job.serve(lines, ["npm", "run", script], target, title=f"Start the service (npm run {script})",
                             env=serve_env(lines, script))
            if code == READY:
                up_at = job.service_url
    except Exception as e:  # e.g. folder could not be deleted
        lines.append(f"Error: {e}")
    finally:
        if up_at:
            lines.append(f"--- finished OK - dev server running at {up_at} (press Stop to shut it down) ---")
        elif job.stopping:
            lines.append("--- stopped ---")
        else:
            lines.append(f"--- finished (exit code {code}) ---")
        job.busy = False


# ---------- routes: shared ----------
@app.before_request
def same_origin_only():
    """Refuse a POST sent by another web page. Browsers add Origin to every POST, so without this any site
    open in the same browser could stop the jobs or shut this app down. Tools such as curl send no Origin."""
    if request.method != "POST":
        return None
    origin = request.headers.get("Origin")
    if origin is not None and urllib.parse.urlsplit(origin).netloc != request.host:
        return jsonify(error="Refused: this request came from another web page"), 403
    return None


def add_job_routes(prefix, name, job):
    """Stop and log endpoints for one tool."""
    def stop():
        if job.busy or job.service_running():
            job.terminate()
        return jsonify(ok=True)

    def log():
        return jsonify(job.view(int(request.args.get("from", 0)), int(request.args.get("run", 0))))

    app.add_url_rule(f"{prefix}/api/stop", f"{name}_stop", stop, methods=["POST"])
    app.add_url_rule(f"{prefix}/api/log", f"{name}_log", log, methods=["GET"])


add_job_routes("/createplugin", "plugin", plugin_job)
add_job_routes("/dwcversion", "dwc", dwc_job)


@app.get("/api/status")
def api_status():
    up = dwc_job.service_running()
    return jsonify(createplugin=plugin_job.busy, dwcversion=dwc_job.busy or up,
                   dev_url=dwc_job.service_url if up else "")


def shutdown():
    """Stop every running job (and the dev server), then end this app."""
    for j in JOBS:
        j.terminate(force_after=5)
    for _ in range(50):  # let a job finish putting back any files it moved aside
        if not any(j.busy for j in JOBS):
            break
        time.sleep(0.1)
    os._exit(0)


@app.post("/api/exit")
def api_exit():
    """Stop every running job, then shut down this web server."""
    threading.Timer(0.5, shutdown).start()  # let this response reach the browser first
    return jsonify(ok=True)


# ---------- stop when the last browser tab is closed ----------
# Every page posts to /api/tab when it opens, every TAB_PING seconds while open, and once more when it closes.
# When no tab is left, the app shuts down after CLOSE_GRACE seconds (time for a reload or a move to another page
# to check in again). Nothing happens until the first tab checks in, so the app keeps running until a browser opens it.
TAB_TIMEOUT = 90   # seconds without a ping before a tab counts as closed (browsers slow background tabs to about one a minute)
CLOSE_GRACE = 10
tabs = {}          # tab id -> time.monotonic() of its last ping
tabs_lock = threading.Lock()
empty_since = None   # when the last tab went; None while a tab is open or before any has checked in


@app.post("/api/tab")
def api_tab():
    global empty_since
    d = request.get_json(silent=True) or {}
    tab = d.get("id")
    if not isinstance(tab, str) or not 0 < len(tab) <= 64:
        return jsonify(error="Invalid tab id"), 400
    with tabs_lock:
        if d.get("closing"):
            tabs.pop(tab, None)
            if not tabs:
                empty_since = time.monotonic()
        else:
            tabs[tab] = time.monotonic()
            empty_since = None
    return jsonify(ok=True)


def watch_tabs():
    """Shut the app down once every tab has been closed (see above)."""
    global empty_since
    while True:
        time.sleep(1)
        now = time.monotonic()
        with tabs_lock:
            for tab, seen in list(tabs.items()):
                if now - seen > TAB_TIMEOUT:
                    del tabs[tab]
                    if not tabs:
                        empty_since = now
            done = not tabs and empty_since is not None and now - empty_since > CLOSE_GRACE
        if done:
            logger.info("Every browser tab has been closed - shutting down")
            shutdown()


def config_view():
    data = load_store()
    d, p = dwc_versions_dir(data), plugins_dir(data)
    return {
        "dwc_versions_dir": d, "plugins_dir": p,
        "defaults": {"dwc_versions_dir": DEFAULT_DWC_VERSIONS, "plugins_dir": DEFAULT_PLUGINS,
                     "listen": DEFAULT_LISTEN},
        "preferred_port": preferred_port(data),
        "listen": listen(data),
        "url": f"http://{HOST}:{PORT}/" if PORT else "",   # where this tool is listening right now
        "dwc_count": len(dwc_versions(d)) if os.path.isdir(d) else None,   # None = folder not found
        "plugin_count": sum(1 for x in subdirs(p) if plugin_versions(x, p)) if os.path.isdir(p) else None,
        "settings_file": SETTINGS_FILE,
        "first_run": not os.path.isfile(SETTINGS_FILE),
    }


def drives():
    """Windows drive roots that exist (C:\\, D:\\ ...)."""
    if hasattr(os, "listdrives"):   # Python 3.12+
        return sorted(os.listdrives())
    return [f"{c}:\\" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.isdir(f"{c}:\\")]


@app.get("/api/browse")
def api_browse():
    """Sub-folders of a folder on this computer, for the Browse buttons on the Settings page. The page may be
    open on another computer, so the browser's own folder picker (which shows that computer's folders) is no use.
    An empty path lists the drives on Windows and means / elsewhere. A path that does not exist falls back to the
    nearest folder above it that does, and a relative one to the install folder."""
    raw = request.args.get("path", "").strip()
    if not raw and IS_WINDOWS:
        return jsonify(path="", parent=None, dirs=[{"name": d, "path": d} for d in drives()], readable=True)
    path = os.path.expanduser(raw or os.sep)
    if not os.path.isabs(path):
        path = INSTALL_DIR
    path = os.path.normpath(path)
    while not os.path.isdir(path) and os.path.dirname(path) != path:
        path = os.path.dirname(path)
    parent = os.path.dirname(path)
    if parent == path:   # a root: on Windows, Up goes on to the list of drives
        parent = "" if IS_WINDOWS else None
    return jsonify(path=path, parent=parent, readable=os.access(path, os.R_OK | os.X_OK),
                   dirs=[{"name": d, "path": os.path.join(path, d)} for d in subdirs(path)])


@app.get("/api/config")
def api_config_get():
    return jsonify(config_view())


@app.post("/api/config")
def api_config_set():
    if any(j.busy for j in JOBS):
        return jsonify(error="A job is running - wait for it to finish or stop it first"), 409
    d = request.get_json(silent=True) or {}
    new = {}
    for key, label in (("dwc_versions_dir", "DWC versions folder"), ("plugins_dir", "Plugins folder")):
        raw = d.get(key, "")
        if not isinstance(raw, str):
            return jsonify(error=f"{label}: invalid value"), 400
        raw = raw.strip()
        if not raw:
            continue  # empty means "use the default"
        path = os.path.expanduser(raw)
        if not os.path.isabs(path):
            return jsonify(error=f"{label}: enter a full path, such as /home/pi/DWC or C:\\DWC"), 400
        path = os.path.normpath(path)
        if not os.path.isdir(path):
            return jsonify(error=f"{label}: '{path}' is not an existing folder"), 400
        if path != os.path.normpath(DEFAULTS[key]):
            new[key] = path   # the default is simply not stored, so it keeps following the install folder
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


# ---------- routes: CreatePlugin ----------
@app.get("/createplugin/api/options")
def plugin_options():
    plugins = []
    base = plugins_dir()
    for p in subdirs(base):
        versions = plugin_versions(p, base)
        if versions:  # a folder without any plugin version folder is not a plugin
            plugins.append({"name": p, "versions": versions})
    return jsonify(dwc=dwc_versions(), plugins=plugins, last=saved_last("createplugin"), plugins_dir=base)


@app.get("/createplugin/api/files")
def plugin_files():
    dwc = request.args.get("dwc", "")
    plugin = request.args.get("plugin", "")
    pver = request.args.get("version", "")
    out = {"files": [], "selected": [], "truncated": False, "code": None, "found": [], "custom": False}
    if plugin not in subdirs(plugins_dir()) or pver not in plugin_versions(plugin):
        return jsonify(out)
    # The Code folder: as typed on the page (code=...), or else the remembered / automatic one
    pvd = os.path.join(plugins_dir(), plugin, pver)
    found = find_code_paths(pvd)
    raw = request.args.get("code")
    code = code_path_for(plugin, pver) if raw is None else clean_code_path(raw)
    out["found"] = found
    if code is None:
        out["error"] = "Use a folder inside the plugin version folder, such as Code or src/Code (. for the folder itself)"
        return jsonify(out)
    out["code"], out["custom"] = code, code != (found[0] if found else None)
    if not has_manifest(pvd, code):
        out["error"] = "There is no plugin.json in that folder"
        return jsonify(out)
    listed, truncated = code_files(plugin, pver, code)
    # Only pre-tick remembered files that still exist
    present = set(listed)
    selected = [f for f in saved_excludes(dwc, plugin, pver) if f in present]
    out.update(files=listed, selected=selected, truncated=truncated)
    return jsonify(out)


@app.post("/createplugin/api/start")
def plugin_start():
    d = request.get_json(silent=True) or {}
    dwc, plugin, pver = (str(d.get(k, "")).strip() for k in ("dwc", "plugin", "plugin_version"))
    exclude = d.get("exclude", [])
    # Only accept values that match real folders (also blocks path tricks)
    if dwc not in dwc_versions():
        return jsonify(error="Choose an existing DWC version"), 400
    if plugin not in subdirs(plugins_dir()):
        return jsonify(error="Choose an existing plugin"), 400
    if pver not in plugin_versions(plugin):
        return jsonify(error="Choose an existing plugin version"), 400
    pvd = os.path.join(plugins_dir(), plugin, pver)
    code = clean_code_path(d.get("code", ""))
    if code is None or not has_manifest(pvd, code):
        return jsonify(error="Code folder: choose a folder inside the plugin version folder that holds plugin.json"), 400
    found = find_code_paths(pvd)
    custom_code = None if found and code == found[0] else code
    if not isinstance(exclude, list) or not all(isinstance(x, str) for x in exclude):
        return jsonify(error="Invalid exclusion list"), 400
    if not set(exclude) <= set(code_files(plugin, pver, code)[0]):
        return jsonify(error="An excluded file does not exist in the Code folder"), 400
    lines = plugin_job.begin()
    if lines is None:
        return jsonify(error="Already running - stop it first"), 409
    lines.append(f"Build: DWC {dwc}, plugin {plugin}, plugin version {pver}, Code folder {code or '.'}")
    err = remember_plugin_run(dwc, plugin, pver, exclude, custom_code)
    if err:
        lines.append(f"Could not remember these selections: {err}")
    threading.Thread(target=run_plugin_job, args=(lines, dwc, plugin, pver, code, exclude), daemon=True).start()
    return jsonify(ok=True)


# ---------- routes: DWCVersion ----------
@app.get("/dwcversion/api/options")
def dwc_options():
    return jsonify(dwc=dwc_versions(), last=saved_last("dwcversion"))


@app.post("/dwcversion/api/start")
def dwc_start():
    version = str((request.get_json(silent=True) or {}).get("version", "")).strip()
    # The version becomes a folder name that gets deleted, so keep it strict. Starting with a digit
    # also means it can never name an ordinary folder (Documents, ...) or this script's own files when the folder is the install folder.
    if not VERSION_NAME.fullmatch(version):
        return jsonify(error="Invalid version: start with a digit, no leading 'v' (e.g. 3.5.1 or 3.6-dev)"), 400
    if dwc_job.service_running():
        return jsonify(error="The dev server is still running - press Stop first"), 409
    lines = dwc_job.begin()
    if lines is None:
        return jsonify(error="Already running - stop it first"), 409
    err = save_last("dwcversion", {"version": version})
    if err:
        lines.append(f"Could not remember this selection: {err}")
    threading.Thread(target=run_dwc_job, args=(lines, version), daemon=True).start()
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


HOME_PAGE = render("DWC tools", "home")
PLUGIN_PAGE = render("Create a Plugin", "createplugin")
DWC_PAGE = render("Create DWC Version", "dwcversion")
SETTINGS_PAGE = render("DWC tools - Settings", "settings")
_README_TEMPLATE = render("DWC tools - Instructions", "readme")


def build_readme(is_windows):
    """The instructions page, with the setup steps, paths and examples for Windows or Linux."""
    if is_windows:
        text = {
            "__SETUP__": (
                '<p><b>Windows</b> (10 or later). Install Python 3.8 or later (from python.org, tick "Add python.exe to PATH"), '
                '<b>Git for Windows</b> (git-scm.com) and <b>Node.js</b> (nodejs.org, which includes npm).</p>'
                '<p>Then unzip the release (<code>plugin_tool.zip</code>) and, in the unzipped <code>plugin_tool</code> folder, run:</p>'
                '<pre>run.bat</pre>'
                '<p>(double-click it, or run it in Command Prompt). It runs <code>install.py</code>, which '
                'asks for the install folder (in a folder window on a desktop, otherwise in the terminal), copies the app there, creates its own venv and installs Flask into it '
                '(internet access is needed), and adds a <code>run.bat</code> there that starts the app. <b>When the install succeeds it starts the app straight away</b> '
                '(add <code>--no-run</code> to install without starting it). After that, start it with <code>run.bat</code> in the install folder. '
                'Running the installer again updates the app and keeps your settings.</p>'
                '<p>No zip program is needed: the app makes zip files itself. Windows may ask whether to allow Python through '
                'the firewall. Allow it on private networks, or other computers will not be able to open the page.</p>'),
            "__HIDDEN_NOTE__": "The name starts with a dot, but Windows does not hide it: it shows in File Explorer like any other file.",
            "__NOT_FOUND_ROW__": '<tr><td>"Could not start git / npm / node"</td><td>Install Git for Windows or Node.js, '
                                 'then close and reopen the Command Prompt so that it finds them</td></tr>',
            "__OS_ROWS__": (
                '  <tr><td>Cloning or deleting fails with a "path too long" message</td><td>Node.js makes very deep folders. '
                r'Keep the DWC versions folder short (for example <code>C:\DWC</code>) or turn on long paths in Windows</td></tr>' '\n'
                '  <tr><td>Other computers cannot open the page</td><td>Allow Python through Windows Defender Firewall '
                'for private networks</td></tr>'),
        }
    else:
        text = {
            "__SETUP__": (
                '<p><b>Linux</b> (for example Raspberry Pi OS / Debian Trixie): install what the tools use:</p>'
                '<pre>sudo apt install python3-venv git nodejs npm</pre>'
                '<p>Then unzip the release (<code>plugin_tool.zip</code>) and, in the unzipped <code>plugin_tool</code> folder, run:</p>'
                '<pre>./run.sh</pre>'
                '<p>It runs <code>install.py</code>, which '
                'asks for the install folder (in a folder window on a desktop, otherwise in the terminal), copies the app there, creates its own venv and installs Flask into it '
                '(internet access is needed), and adds a <code>run.sh</code> there that starts the app. <b>When the install succeeds it starts the app straight away</b> '
                '(add <code>--no-run</code> to install without starting it). After that, start it with <code>run.sh</code> in the install folder. '
                'Running the installer again updates the app and keeps your settings.</p>'
                '<p>From a copy of the repository, create the venv once (or run Prepare in Prep_and_Package on the folder), '
                'then start it with <code>./run.sh</code>.</p>'
                '<p>No zip program is needed: the app makes zip files itself.</p>'),
            "__HIDDEN_NOTE__": "The name starts with a dot, so it is hidden: use <code>ls -a</code> in that folder to see it.",
            "__NOT_FOUND_ROW__": '<tr><td>"Could not start git / npm / node"</td><td>Install it: '
                                 '<code>sudo apt install git nodejs npm</code></td></tr>',
            "__OS_ROWS__": "",
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


@app.get("/createplugin")
def createplugin_page():
    return PLUGIN_PAGE


@app.get("/dwcversion")
def dwcversion_page():
    return DWC_PAGE


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
    target = os.path.abspath(SETTINGS_FILE)
    if not os.path.exists(target):
        # Saving creates missing folders, so what matters is the nearest folder that already exists
        target = os.path.dirname(target)
        while not os.path.exists(target) and os.path.dirname(target) != target:
            target = os.path.dirname(target)
    if not os.access(target, os.W_OK):
        logger.warning(f"Settings cannot be saved: {target} is not writable. "
                       f"Install the app in a folder you can write to")


def main():
    global HOST, PORT
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    # Check which operating system this is running on (Linux and Windows are supported)
    logger.info(f"Running on {PLATFORM}" + (" (Windows code paths)" if IS_WINDOWS else ""))
    if PLATFORM not in ("Linux", "Windows"):
        logger.warning(f"{PLATFORM} has not been tested: it is being treated like Linux")
    logger.info(f"Settings file: {SETTINGS_FILE} ({'found' if os.path.isfile(SETTINGS_FILE) else 'not found'})")
    check_settings_writable()
    # Use the preferred port from the settings if it is free (else the first free port from 17800),
    # and from here on this tool's address and port are whatever validate_port() returned
    data = load_store()
    local = listen(data) == "local"
    logger.info("Listening for this computer only" if local else "Listening for any computer on the network")
    HOST, PORT = validate_port(preferred_port(data), local)
    # No settings file yet = first run: start on the instructions. Otherwise start on Home as normal.
    path = "/" if os.path.isfile(SETTINGS_FILE) else "/readme"
    host = "localhost" if HOST in ("0.0.0.0", "127.0.0.1", "::") else HOST
    print(f" * DWC tools: http://{host}:{PORT}{path}")
    threading.Timer(1.0, open_browser, args=(path,)).start()  # give the server a moment to start
    threading.Thread(target=watch_tabs, daemon=True).start()
    app.run(host=HOST, port=PORT, threaded=True)


if __name__ == "__main__":
    main()
