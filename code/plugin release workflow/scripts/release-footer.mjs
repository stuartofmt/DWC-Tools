#!/usr/bin/env node
/**
 * Print the static footer appended to every GitHub Release body: install instructions and the
 * DuetWebControl version the ZIP was built against.
 *
 * Everything plugin-specific comes from plugin.json (found by ./manifest.mjs), so this works unchanged
 * for any plugin: the ZIP name from id + version (+ dwcVersion when it is built), the project link from homepage, and the SBC note from
 * sbcRequired. A docs/Installation-Configuration.md in the repository is linked if present.
 * The DWC details come from the CI build environment (the release workflow sets these after it checks
 * out DuetWebControl), so it also reads sensibly when run locally.
 *
 * A repository with no plugin.json is released as a standalone ZIP, <name>-<version>.zip: the name and
 * version come from PLUGIN_NAME and PLUGIN_VERSION (set by the release workflow), else the repository's
 * name and the tag.
 */
import { existsSync } from "node:fs";
import { join } from "node:path";
import { isStandalone, needsDwcBuild, readManifest, repoRoot, standaloneName } from "./manifest.mjs";

if (isStandalone()) {
	const name = process.env.PLUGIN_NAME || standaloneName();
	const version = process.env.PLUGIN_VERSION || (process.env.GITHUB_REF_NAME || "").replace(/^v/, "");
	const asset = `${name}-${version}.zip`;
	process.stdout.write(`---

### 📦 Download ${name}
Download \`${asset}\` from the **Assets** below and unzip it.

> 🔧 Standalone release - not a DWC plugin, so it does not depend on any DuetWebControl version.
`);
	process.exit(0);
}

const manifest = readManifest();
const pkgVersion = manifest.version;
const built = needsDwcBuild(manifest);   // false: no DWC interface - the ZIP was made without a DWC build
const asset = built ? `${manifest.id}-${pkgVersion}-${manifest.dwcVersion}.zip` : `${manifest.id}-${pkgVersion}.zip`;
const ref = process.env.GITHUB_REF_NAME || "main";

const dwcVersion = process.env.DWC_VERSION || "";

// Resolve the manifest's dwcVersion the same way DWC's build does ("auto" -> full DWC version,
// "auto-major" -> major.minor), so the metadata below matches the requirement DWC actually enforces
// at install. This is what the update checker compares the running DWC version against.
function resolveDwcRequirement(value, reference) {
	if (value === "auto") return reference;
	if (value === "auto-major") return reference.split(".").slice(0, 2).join(".");
	return value || "";
}
const requiredDwc = resolveDwcRequirement(manifest.dwcVersion, dwcVersion);
const dwcSha = process.env.DWC_SHA || "";
const dwcRef = process.env.DWC_REF || "next";
const dwcBuiltAgainst = dwcVersion
	? `**DuetWebControl ${dwcVersion}**${dwcSha ? ` (\`${dwcSha}\`, ref \`${dwcRef}\`)` : ` (ref \`${dwcRef}\`)`}`
	: `DuetWebControl (ref \`${dwcRef}\`)`;

// Optional links, included only when the information exists.
const guide = "docs/Installation-Configuration.md";
const links = [];
if (existsSync(join(repoRoot, guide))) {
	links.push(`[installation and configuration guide](${manifest.homepage ? `${manifest.homepage}/blob/${ref}/${guide}` : guide})`);
}
if (manifest.homepage) links.push(`[project page](${manifest.homepage})`);
const seeAlso = links.length ? `\nSee the ${links.join(" and the ")} for setup details.\n` : "";

const requirement = (built
	? `Requires DuetWebControl ${requiredDwc || dwcVersion || "(see plugin.json)"}`
	: "Works with any DuetWebControl version")
	+ (manifest.sbcRequired ? " on a Duet running in SBC mode" : "");
const buildNote = built
	? `Built against ${dwcBuiltAgainst}.`
	: "Packaged without a DWC build (this plugin has no DWC interface).";

const out = `
---

### 📦 Install ${manifest.name || manifest.id}
1. Download \`${asset}\` from the **Assets** below.
2. In DuetWebControl, go to **Settings → General → Plugins** and click **Install Plugin**.
3. Select the downloaded ZIP and accept the third-party-plugin prompt.
4. Reload DWC if asked.
${seeAlso}
> 🔧 ${buildNote} ${requirement}.

<!-- dwc-plugin-update ${JSON.stringify({ version: pkgVersion, dwcVersion: requiredDwc, asset })} -->
`;

process.stdout.write(out.replace(/^\n/, ""));
