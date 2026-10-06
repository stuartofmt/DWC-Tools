# plugin_tool

A small web app for developing DuetWebControl (DWC) plugins on a Raspberry Pi or a Windows PC.

It has two tools:

- **Create DWC Version** downloads a DWC release from GitHub, installs its dependencies and starts its dev server.
- **Create a Plugin** builds or zips one of your plugins into an installable `.zip`.

Each tool runs as a separate job, so a DWC dev server can keep running while you build plugins.

## Setup and starting

**Linux** (for example Raspberry Pi OS):

```
sudo apt install python3-venv git nodejs npm
./run.sh
```

`run.sh` runs the app with its own venv in this folder. If there is no venv yet, `run.sh` creates it (this needs `python3-venv`) and installs `code/requirements.txt` (Flask) into it with the venv's pip. The first start therefore needs internet access. After that, the requirements are installed again only when a `requirements.txt` has changed. Delete the `venv` folder to have it rebuilt from scratch.

**Windows** (10 or later): install Python 3.8 or later (tick "Add python.exe to PATH"), Git for Windows and Node.js (which includes npm), then:

```
pip install flask             (or: pip install -r code\requirements.txt)
python code\plugin_tools.py
```

No zip program is needed on either system, because the app makes zip files itself. On Windows, allow Python through the firewall on private networks so that other computers can open the page.

The app prints its address when it starts, and on a desktop it opens your browser there. It uses the preferred port from the Settings page if that port is free, and otherwise the first free port from 17800. (createStandalone uses ports from 17900, so the two can run at the same time.) The first time it runs, it opens on the Instructions page.

Keep the `web` folder next to `plugin_tools.py`.

## Folder layout

Both folders are set on the Settings page. Until you set them, both are the folder `plugin_tools.py` is in.

```
<DWC versions folder>/
    3.6.3/                    one folder per DWC version (Create DWC Version makes these)
    3.7.0-rc.2/
<Plugins folder>/
    <plugin name>/
        plugin3.7.x/          one folder per plugin version, with any name (shown as the version)
            Code/             the Code folder: the folder holding plugin.json
                plugin.json
                ...           the plugin's files
            <plugin name>-<manifest version>.zip   the result of Create a Plugin
        Documents/            ignored: no plugin.json in it
```

- **DWC versions** are the folders whose name starts with a digit (`3.5.1`, `3.6-dev` …). They are listed newest first.
- **Plugin version folders** can have any name (`plugin3.7.x`, `Version1` …). A folder counts as one if it has a **Code folder**, which is the folder holding `plugin.json`. That can be the version folder itself, or a folder up to 3 levels below it. `node_modules`, `dist`, `pkg`, `venv`, `__pycache__` and hidden folders are not searched. Plugin versions are listed newest first.
- **A plugin** is listed once it has at least one plugin version folder.

## Create DWC Version

1. Choose a downloaded version, or choose **New version…** and type one, such as `3.5.1` or `3.6-dev`. Don't type a leading `v`. It must match a release tag (`v3.5.1`) or branch of the [DuetWebControl repository](https://github.com/Duet3D/DuetWebControl).
2. Press **Start**. This runs `git clone`, `npm install`, `npm audit --omit=dev` and then the dev server: `npm run dev` (Vite) for DWC 3.7 and later, or `npm run serve` for older versions. For older versions on Node 17 or later, `--openssl-legacy-provider` is added to `NODE_OPTIONS` automatically.
3. When the dev server prints its `Local:` address and that address answers HTTP 200, the job is finished. The server keeps running in the background and its output keeps appearing in the log.
4. Press **Stop** to shut the dev server down.

Choosing a version that is already downloaded **deletes that folder and downloads it again**. You are asked to confirm first.

## Create a Plugin

1. Choose the **DWC** version, the **Plugin** and its **Version**.
2. Check the **Code folder**. It is filled in with the folder found holding `plugin.json`, relative to the plugin version folder (`.` means the version folder itself). If `plugin.json` is in more than one place, the others are listed and offered as you type. You can type another folder; it is remembered for that plugin version when you press Build. **Automatic** goes back to the folder that was found.
3. Press **Build**. What happens depends on `plugin.json`:
   - **No `dwcVersion` entry** (for example a plugin that only runs on the Pi): the contents of the Code folder are zipped. No build is needed.
   - **`dwcVersion` present**: the plugin is built against the chosen DWC version with that version's `scripts/build-plugin.js`. Old `dist` and `pkg` folders, and any `__pycache__`, `*.pyc` and `*.log` files, are cleared first.
4. The result is written in the **plugin version folder** as `<plugin name>-<manifest version>.zip`, even when the Code folder is a sub-folder. Older zips in that folder are removed first.

From DWC 3.7, building a stable plugin version (one without `-beta`, `-rc` …) also makes `<plugin name>-<manifest version>-srcmap.zip`. It holds the source maps, for looking up error stack traces, and is put next to the plugin zip. You don't need it to install the plugin.

### Leaving files out

These are always left out: `__pycache__` and `venv` folders, and `*.log` and `*.pyc` files. To leave out more, open **Exclude files** and tick the files you don't want.

- For a zip-only plugin, ticked files are left out of the zip. Nothing on disk changes.
- For a real build, ticked files are moved out of the Code folder while the build runs and put back afterwards, even if the build fails or you press Stop.
- Ticks are remembered separately for each combination of DWC version, plugin and plugin version.

## Settings

- **DWC versions folder** and **Plugins folder**: type a full path, or press **Browse…** to pick a folder. Browse shows the folders on the computer running the app, even when the page is open on another computer. Clear a box, or press Reset to defaults, to go back to the install folder.
- **Preferred port**: `0` means the first free port from 17800. A change takes effect the next time the app starts.
- **Listen on**: either the whole network or this computer only (`127.0.0.1`). There is no login, so on the network setting anyone who can reach the page can run builds and change settings. Only use that setting on a network you trust. Don't choose "this computer only" on a Pi without a screen, or you won't be able to open the page.

Settings can't be changed while a job is running.

### What is remembered

The folders, the port, where to listen, the last selections in each tool, the ticked exclusions and any Code folders you've changed are all stored in `code/.plugin_build_exclusions.json`. The file is created the first time you save settings or press Build or Start. Deleting it resets everything to the defaults. If you move the app, take the `web` folder and this file with it.

## Stopping

- **Stop** ends the running job in that tool, including the dev server.
- **Exit**, or Ctrl+C in the terminal, stops everything and shuts the app down.
- **Closing every tab of the app** also shuts it down, and that stops the DWC dev server too. This happens about 10 seconds after the last tab closes. Reloading a page or moving to another page of the app doesn't count. A tab that disappears without warning, for example after a browser crash, counts as closed after 90 seconds. Until a browser has opened the app for the first time, it keeps running.

## Troubleshooting

| You see | Try |
|---|---|
| "Could not start git / npm / node" | Install it (`sudo apt install git nodejs npm`, or Git for Windows / Node.js) |
| The clone fails | Check that the version exists as `v<version>` on GitHub, and that the computer has internet access |
| The plugin list is empty | Check the Plugins folder on Settings and the layout above: each plugin needs a version folder with `plugin.json` in it or below it |
| The DWC list is empty | Download a DWC version first with Create DWC Version |
| The build fails straight away | The DWC version needs `scripts/build-plugin.js`, and `plugin.json` needs a `version` |
| "Already running" | Wait for the job to finish, or press Stop |
| The address is different from last time | The preferred port was in use (often by another copy of the app); look at the terminal for the address |
| "Unknown error trying to get the local IP address" at start-up | Connect to a network, or set Listen on to "This computer only" |
| "Refused: this request came from another web page" | Open the app from the address it printed at start-up |
| Windows: "path too long" when cloning or deleting | Use a short DWC versions folder (such as `C:\DWC`) or turn on long paths in Windows |
