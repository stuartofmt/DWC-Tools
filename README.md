# DWC-Tools

Tools for DuetWebControl (DWC) plugin development and for preparing Python programs. Each tool lives on its own branch, with its own README and its own releases:

| Branch | What it is |
|---|---|
| [`plugin_tool`](../../tree/plugin_tool) | A web app for DWC plugin development: downloads and runs a DWC version's dev server, and builds or zips plugins. |
| [`Prep_and_Package`](../../tree/Prep_and_Package) | A web app that prepares a Python program (`requirements.txt` from its imports, and creates a venv), It optionally copies a GitHub release workflow for DWC plugins into a plugin's folder on disk, ready for you to commit. |
| [`scripts`](../../tree/scripts) | Helper scripts, such as `installnvm.sh`, which installs Node.js with nvm. |

This `main` branch only holds this index. Each tool's own README is on its branch.

## Getting a tool

Download the zip from the tool's release on the [Releases](../../releases) page. The release title says which tool it is. Unzip it and follow the tool's README: `plugin_tool` installs with the `install.py` inside its zip. Prep_and_Package has no release zip: download its branch (choose the branch, then **Code → Download ZIP**) and follow its README.

## Releasing your DWC plugins

Prep_and_Package's **Copy Plugin Release Workflow** puts a GitHub release workflow into a plugin's own folder: `.github/workflows/release.yml`, its notes `release.yml.md`, and the `scripts` it uses. It only writes the files on disk. They reach GitHub when you commit and push them in the plugin's repository. From then on, pushing a version tag such as `v1.2.3-dwc3.7` builds the plugin's ZIP on GitHub and publishes a release. `release.yml.md` explains how to release and the one-time setup each plugin repository needs.

This is for your plugins' repositories, not for this one.

## Making a release of these tools

The `plugin_tool` and `scripts` branches have a GitHub Actions workflow, `.github/workflows/release-zips.yml`, that attaches the branch's zips to a release:

1. **Put the release zip in the tool's branch** and commit it. The workflow looks for zips in this order:
   - `standalone-zip/` and `plugin-zip/`. If both have zips, each file is prefixed `standalone-` or `plugin-` so the names can't clash.
   - Otherwise `dist/`.
   (The `scripts` branch only uses `dist/`.)
2. **Tag a commit on that branch** and push the tag, for example:

   ```bash
   git tag plugin_tool-v1.2 plugin_tool
   git push origin plugin_tool-v1.2
   ```

3. **Publish a release** for that tag on the [Releases](../../releases) page. The workflow then uploads the zips to it, replacing files of the same name.

To attach the zips to an existing release again, run the workflow by hand from the **Actions** tab ("Run workflow"), choose the branch, and give the release's tag.

Tags are shared by the whole repository, not by a branch, so two tools can't both have a `V1.2`. Put the tool's name in the tag, as in `plugin_tool-v1.2` or `Prep_and_Package-v1.0`. The existing tags `V1.0` and `V1.1` are plugin_tool releases.
