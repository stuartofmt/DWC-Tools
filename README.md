# Prep_and_Package

A small web app for preparing and releasing standalone Python programs on a Raspberry Pi or a Windows PC.

It has two tools, normally used in this order:

- **Prepare** gets a project folder ready. It works out `requirements.txt` from the program's imports, creates the project's own Python venv, installs `requirements.txt` into it and checks that every package can be imported.
- **Make Zip** builds a release zip of the project. The zip includes its own `install.py`, so the program can be installed on any computer without this app.

Nothing is installed system-wide: there is no `apt` and no `sudo`. Every package goes into the program's own venv, installed with the venv's pip. This works on Linux systems whose Python is "externally managed" and refuses `pip install`.

## Setup and starting

**Linux** (for example Raspberry Pi OS):

```
sudo apt install python3-venv
python3 -m venv venv                                     # once: the app's own venv
venv/bin/python -m pip install -r code/requirements.txt  # once: Flask, into the venv
./run.sh
```

`run.sh` starts the app with the `venv` in this folder (it is the launcher Prepare makes), so the venv must exist first. Once the app is running, Prepare can also look after the venv: run it on this folder.

**Windows** (10 or later): install Python 3.8 or later, then:

```
py -m venv venv
venv\Scripts\python -m pip install -r code\requirements.txt
venv\Scripts\python code\prep_and_package.py
```

The app prints its address when it starts, and on a desktop it opens your browser there. It uses the preferred port from the Settings page if that port is free, and otherwise the first free port from 17900. (plugin_tool uses ports from 17800, so the two can run at the same time.) The first time it runs, it opens on the Instructions page.

Keep the `web` folder next to `prep_and_package.py`.

## What a project looks like

A project is a folder with a `code` folder holding the program. The project's name is the folder's name.

```
scanCam/                   the project folder
    README.md              optional, included in the release
    code/
        scanCam.py         the main program; it may set its version: progVersion = '1.0.0'
        requirements.txt   what pip installs into the venv: made by Prepare (or keep it in the project folder)
        ...                everything else in code/ is included too
    venv/                  made by Prepare (never part of the release)
    run.sh                 made by Prepare if there is none (Windows: run.bat)
    dist/                  made by Make Zip
```

You only need the `code` folder with the program in it. Prepare makes the rest.

You choose a project by typing its path, picking a recent one, or pressing **Browse…**. Browse shows the folders on the computer running the app and marks the ones that are projects. The project you choose in one tool is also chosen in the other, and is remembered for next time.

### Project options

These are saved per project and used by both tools:

- **Main program**: the `.py` file in `code/` that starts the program. It is picked automatically when it has the project's name (`scanCam.py`) or is the only one. If it sets a version (`progVersion`, `__version__`, `VERSION` or `version`), the version goes into the zip's name.
- **The venv can also use system packages** (ticked by default): the venv also sees Python packages that came with the operating system, such as `picamera2` on Raspberry Pi OS. Untick it for a venv that holds only what `requirements.txt` lists. This applies to the venv Prepare makes and to the one `install.py` makes on the target computer. A change takes effect at the next Prepare, which then makes the venv again.

## Prepare

Prepare works on the project folder itself:

1. **requirements.txt**: every `.py` file in `code/` is read for its `import` lines. Python's standard library and the project's own modules (any `.py` file or folder in `code/`) are skipped. Each remaining import is turned into the pip package that provides it.
   - For packages installed on this computer, the name comes from the package's own metadata, so `yaml` becomes `PyYAML`.
   - For packages that aren't installed, the name comes from a short list of well-known names (`cv2` becomes `opencv-python`, `PIL` becomes `Pillow`), or is otherwise assumed to be the import name.
   - Missing packages are added to the project's `requirements.txt`, which is created in `code/` if there is none. Nothing already in the file is changed or removed, so your own additions and version pins are kept. Listed packages that nothing imports are reported, but left in.
   - An import inside `try: ... except ImportError:` is optional, because the program copes without it. It is reported but not added.
   - An import is covered by any package in `requirements.txt` that provides it, so a listed `opencv-python-headless` covers `cv2` and the conflicting `opencv-python` isn't added.
   - For a package only some platforms need, give it an environment marker in `requirements.txt`, e.g. `pygrabber; sys_platform == "win32"`. On other platforms, Prepare doesn't install or check it, and pip skips it there too. Prepare can't tell when code only imports a package on some platforms, so it adds such a package without a marker: add the marker yourself.
2. **venv**: `<project>/venv` is created, using the system packages option. An existing venv is reused, unless it was made with the other setting of that option.
3. **Install**: `requirements.txt` is installed into the venv with the venv's own pip.
4. **Check**: the venv imports each package the program needs. A failure means something is missing from `requirements.txt`, or the package needs something from the operating system.
5. **Launcher**: `run.sh` (Windows: `run.bat`) is added to the project folder, unless one exists already, so you can run the program in place with its venv.

The log ends by listing what Make Zip will use. Run Prepare again whenever the program's imports change.

Creating a venv needs Python's `venv` module. On Debian and Raspberry Pi OS this comes in a separate package, so if the venv can't be created, install it once with `sudo apt install python3-venv`. Venvs are made with the system Python, the one outside any venv that this app's Python comes from.

## Make Zip

Make Zip needs a `requirements.txt`, so run Prepare first.

This creates `dist/<name>-<version>.zip`, or `dist/<name>.zip` when the program sets no version. A zip of the same name is replaced. It unzips to:

```
<name>/
    README.md
    requirements.txt       when it is in the project folder
    code/                  without __pycache__, venv, .git, *.pyc or the files you exclude
    install.py             made by this app from the project options
    run.sh, run.bat        start install.py with the system Python (python3, or py on Windows)
```

**Exclude files** lists every file that would go into the zip. Tick the ones to leave out, such as a settings file that belongs to this computer (for example plugin_tool's `.plugin_build_exclusions.json`). The ticks are remembered for each project when you press Make Zip. Nothing is left out until you tick it, hidden files (names starting with a dot) included. The main program and `requirements.txt` can't be left out, because `install.py` needs them.

The page lists the zips already in `dist/`, newest first, and you can click one to download it. It can also show you the `install.py` it will generate.

## Installing a release (install.py)

On the target computer, unzip the release and run `./run.sh` (Windows: `run.bat`, or double-click it), which starts `install.py` with the system Python and passes on any arguments. Or run `install.py` yourself:

```
python3 install.py                      (Windows: py install.py)
python3 install.py /home/pi/scanCam     (give the install folder straight away)
python3 install.py --no-run             (install without starting the program)
python3 install.py --no-gui             (ask for the install folder in the terminal, not in a window)
```

It does three things:

1. It copies `README.md`, `code/` and `requirements.txt` into the install folder. If you don't give the folder, it asks for it:
   - **On a desktop**, a folder window opens. Go to where you want to install and press OK: a `<name>` folder is made there, or an existing `<name>` folder you picked is installed over. To name the folder yourself, type its full path in the **Selection** box: a folder that doesn't exist yet is created and used as typed (parent folders too). You then confirm the final path. This needs Python's tkinter: Windows has it, and on Debian or Raspberry Pi OS it's the `python3-tk` package.
   - **Otherwise** (over SSH, on a computer without a screen, without tkinter, or with `--no-gui`), it asks in the terminal. The default is `~/<name>`.
2. It writes a launcher, `run.sh` on Linux or `run.bat` on Windows, which starts the main program with the venv's Python.
3. It deletes and recreates `venv/` in the install folder, then runs `venv/bin/python -m pip install -r requirements.txt`.

When the install succeeds, it starts the program straight away with `run.sh` (Windows: `run.bat`), unless you add `--no-run`. Its exit code is the program's. Later, start the program with `<install folder>/run.sh`. Running `install.py` again updates the program files and recreates the venv. On Debian and Raspberry Pi OS, the target computer also needs `python3-venv`.

## Settings

- **Projects folder**: where Browse starts when no project has been chosen yet. The default is your home folder.
- **Preferred port**: `0` means the first free port from 17900. A change takes effect the next time the app starts.
- **Listen on**: either the whole network or this computer only (`127.0.0.1`). There is no login, so on the network setting anyone who can reach the page can prepare projects and make zips. Only use that setting on a network you trust.

The settings, the current and recent projects, and each project's options are stored in `code/.prep_and_package.json`. Deleting that file resets everything to the defaults.

## Stopping

- **Stop** ends the running job in that tool, along with everything it started (such as pip). A stopped zip is deleted. A stopped Prepare can leave the venv without every package: run Prepare again.
- **Exit**, or Ctrl+C in the terminal, stops everything and shuts the app down.
- **Closing every page of the app** also shuts it down, about 10 seconds after the last page closes. Reloading a page or moving to another page of the app doesn't count. A page that stops responding, for example after a browser crash, counts as closed after 90 seconds. Until a page has been opened for the first time, the app keeps running. Keep a page open while Prepare is running, because closing it stops Prepare.

## Troubleshooting

| You see | Try |
|---|---|
| "... has no code folder with a .py program in it" | Choose the project's top folder, the one holding `code`, not `code` itself |
| "... has no requirements.txt" (Make Zip) | Run Prepare first: it makes one |
| "Could not create the venv" | `sudo apt install python3-venv` |
| "pip could not install everything" | A name in `requirements.txt` is wrong (often a guessed one), or that version doesn't exist: correct it and run Prepare again |
| A package FAILED in the import check | Read the error: add the missing package to `requirements.txt`, or install what the operating system needs, then run Prepare again |
| The installed program can't import a package | Add the package to `requirements.txt`, run Prepare to check it, and make a new zip |
| The address is different from last time | The preferred port was in use; look at the terminal for the address |
| "Refused: this request came from another web page" | Open the app from the address it printed at start-up |
