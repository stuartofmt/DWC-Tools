# DWC-Tools

Tools for DuetWebControl plugin development and for releasing standalone Python programs. Each tool lives on its own branch, with its own README and its own releases:

| Branch | What it is |
|---|---|
| [`plugin_tool`](../../tree/plugin_tool) | A web app for DWC plugin development: downloads and runs a DWC version's dev server, and builds or zips plugins. |
| [`Prep_and_Package`](../../tree/Prep_and_Package) | A web app that prepares a standalone Python program (`requirements.txt` from its imports, a venv) and packages it as a release zip with its own `install.py`. |
| [`scripts`](../../tree/scripts) | Helper scripts, such as `installnvm.sh`, which installs Node.js with nvm. |

This `main` branch only holds this index.

## Getting a tool

Download the zip from the tool's release on the [Releases](../../releases) page, or clone just that branch:

```
git clone -b plugin_tool --single-branch https://github.com/stuartofmt/DWC-Tools.git plugin_tool
```

## Releases

Each release is tagged with the tool's name and version, for example `plugin_tool-v1.0.0` or `Prep_and_Package-v1.0.0`, and the tag points at a commit on that tool's branch. On the GitHub Releases page, choose that tag and attach the zip made by Prep_and_Package's Make Zip.
