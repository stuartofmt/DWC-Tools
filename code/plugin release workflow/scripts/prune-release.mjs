#!/usr/bin/env node
/**
 * Remove the files that should not be in the release ZIP from the plugin's Code folder (the folder that
 * holds plugin.json, found by ./manifest.mjs): the patterns in scripts/release-exclude.txt, plus the
 * leftovers plugin_tools always leaves out (__pycache__/, venv/, .git/, *.pyc, *.log).
 *
 * Usage:
 *   node scripts/prune-release.mjs --list     show what would be removed - changes nothing
 *   node scripts/prune-release.mjs --delete   remove it. The release workflow does this on a copy of the
 *                                             Code folder (--dir), never on the checkout itself. Outside
 *                                             GitHub Actions it is refused unless --force is added too, so a
 *                                             working copy is not emptied by mistake.
 *   --dir <folder>                            work on this folder instead of the Code folder (e.g. a copy of it)
 *
 * A repository with no plugin.json is released as a standalone ZIP of the whole repository, so the
 * repository root is pruned instead, and the release workflow's own files (.github/, the scripts it adds)
 * and standalone-zip/ are always left out too.
 *
 * Pattern rules (a subset of .gitignore) are described in scripts/release-exclude.txt.
 */
import { existsSync, lstatSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { isStandalone, manifestPath, repoRoot } from "./manifest.mjs";

const EXCLUDE_FILE = join(repoRoot, "scripts", "release-exclude.txt");
const standalone = isStandalone();
const ALWAYS = ["__pycache__/", "venv/", ".git/", "*.pyc", "*.log",
	// A standalone ZIP is the whole repository: leave out the release workflow itself and prebuilt ZIPs
	...(standalone ? [".github/", "standalone-zip/", "scripts/manifest.mjs", "scripts/prune-release.mjs",
		"scripts/release-*.mjs", "scripts/release-*.txt", "scripts/release.sh"] : [])];

const argv = process.argv.slice(2);
const args = new Set(argv);
const remove = args.has("--delete");
const dirIndex = argv.indexOf("--dir");
if ((!remove && !args.has("--list")) || (dirIndex >= 0 && !argv[dirIndex + 1])) {
	console.error("Usage: node scripts/prune-release.mjs --list | --delete [--force] [--dir <folder>]");
	process.exit(2);
}
if (remove && process.env.GITHUB_ACTIONS !== "true" && !args.has("--force")) {
	console.error("Refusing to delete files outside GitHub Actions - use --list to preview, or add --force.");
	process.exit(2);
}

/** A pattern as a regular expression matched against paths relative to the Code folder. */
function compile(pattern) {
	let p = pattern.replace(/^\/+/, "");
	const dirOnly = p.endsWith("/");
	p = p.replace(/\/+$/, "");
	const anywhere = !p.includes("/");   // no "/" inside: the name matches at any depth
	let re = "";
	for (let i = 0; i < p.length; i++) {
		const c = p[i];
		if (p.startsWith("**/", i)) { re += "(?:[^/]+/)*"; i += 2; }
		else if (p.startsWith("**", i)) { re += ".*"; i += 1; }
		else if (c === "*") re += "[^/]*";
		else if (c === "?") re += "[^/]";
		else re += c.replace(/[.+^${}()|[\]\\]/g, "\\$&");
	}
	return { pattern, dirOnly, regex: new RegExp(anywhere ? `(^|/)${re}$` : `^${re}$`), matched: 0 };
}

function readPatterns() {
	if (!existsSync(EXCLUDE_FILE)) return [];
	return readFileSync(EXCLUDE_FILE, "utf8").split(/\r?\n/)
		.map((line) => line.trim())
		.filter((line) => line && !line.startsWith("#"));
}

const own = readPatterns().map(compile);
const rules = [...ALWAYS.map(compile), ...own];
const codeDir = dirIndex >= 0 ? resolve(argv[dirIndex + 1])
	: standalone ? repoRoot : dirname(join(repoRoot, manifestPath()));
if (!standalone && !existsSync(join(codeDir, "plugin.json"))) {
	console.error(`${codeDir} has no plugin.json - is it the plugin's Code folder?`);
	process.exit(2);
}
const found = [];

// Walk the Code folder; a matching folder is taken whole and not looked inside
(function walk(dir) {
	for (const entry of readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
		const full = join(dir, entry.name);
		const rel = relative(codeDir, full).split("\\").join("/");
		const isDir = entry.isDirectory() && !lstatSync(full).isSymbolicLink();
		const rule = rules.find((r) => (!r.dirOnly || isDir) && r.regex.test(rel));
		if (rule) {
			rule.matched++;
			found.push({ full, rel: isDir ? `${rel}/` : rel });
		} else if (isDir) {
			walk(full);
		}
	}
})(codeDir);

const where = dirIndex >= 0 ? codeDir : relative(repoRoot, codeDir) || ".";
console.log(`${standalone ? "Standalone (no plugin.json), zipping" : "Code folder:"} ${where}  (exclude list: ${existsSync(EXCLUDE_FILE) ? relative(repoRoot, EXCLUDE_FILE) : "none"})`);
for (const { full, rel } of found) {
	console.log(`${remove ? "removed" : "would remove"}: ${rel}`);
	if (remove) rmSync(full, { recursive: true, force: true });
}
if (!found.length) console.log("Nothing to leave out.");
// A pattern that matched nothing is probably a typo (or a file that has since been removed)
for (const rule of own.filter((r) => !r.matched)) {
	console.log(`::warning::scripts/release-exclude.txt: "${rule.pattern}" matched nothing in ${where}`);
}
