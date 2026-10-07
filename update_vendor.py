#!/usr/bin/env python3
"""Fetch the browser libraries the web pages use into code/web/vendor, so the app (and its release zip)
works without internet access. Run it again after changing the versions below, or after using a new
mdi-... icon in code/web: only the icons the pages and Vuetify use are kept in mdi.css.

Not part of the app or its zip: run it with any Python 3.8+, from anywhere."""
import io
import json
import os
import re
import sys
import tarfile
import urllib.request

VUE = "3.5.43"
VUETIFY = "4.2.4"
MDI = "7.4.47"

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "code", "web")
VENDOR = os.path.join(WEB, "vendor")
ICON = re.compile(r"\bmdi-[a-z0-9]+(?:-[a-z0-9]+)*\b")


def package(name, version):
    """The files of one npm package, as {path inside the package: bytes}."""
    url = f"https://registry.npmjs.org/{name}/-/{name.split('/')[-1]}-{version}.tgz"
    print("Fetching", url)
    with urllib.request.urlopen(url, timeout=60) as r:
        data = r.read()
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            if member.isfile():
                files[member.name.split("/", 1)[1]] = tar.extractfile(member).read()
    return files


def used_icons(vuetify):
    """mdi-... names in Vuetify's icon aliases and in the pages."""
    names = set(ICON.findall(vuetify["lib/iconsets/mdi.js"].decode()))
    for name in os.listdir(WEB):
        if name.endswith((".html", ".js")):
            with open(os.path.join(WEB, name), encoding="utf-8") as f:
                names |= set(ICON.findall(f.read()))
    return names


def mdi_css(css, names):
    """Only the font and the rules for these icons, from the full materialdesignicons.css."""
    rules = dict(re.findall(r'\.(mdi-[a-z0-9-]+)::before\{content:"(\\[0-9A-F]+)"\}', css))
    missing = sorted(n for n in names if n not in rules and n != "mdi-set")
    if missing:
        sys.exit(f"Not in Material Design Icons {MDI}: {', '.join(missing)}")
    out = [f"/* Material Design Icons {MDI} (Apache 2.0, pictogrammers.com), only the icons this app uses. Made by update_vendor.py */",
           '@font-face{font-family:"Material Design Icons";src:url("materialdesignicons-webfont.woff2") format("woff2");'
           "font-weight:normal;font-style:normal;font-display:block}",
           '.mdi:before,.mdi-set{display:inline-block;font:normal normal normal 24px/1 "Material Design Icons";font-size:inherit;'
           "text-rendering:auto;line-height:inherit;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale}"]
    out += [f'.{n}::before{{content:"{rules[n]}"}}' for n in sorted(names) if n in rules]
    return "\n".join(out) + "\n"


def main():
    vue = package("vue", VUE)
    vuetify = package("vuetify", VUETIFY)
    mdi = package("@mdi/font", MDI)
    wanted = {
        "vue.global.prod.js": vue["dist/vue.global.prod.js"],
        "vuetify.min.js": vuetify["dist/vuetify.min.js"],
        "vuetify.min.css": vuetify["dist/vuetify.min.css"],
        "materialdesignicons-webfont.woff2": mdi["fonts/materialdesignicons-webfont.woff2"],
        "mdi.css": mdi_css(mdi["css/materialdesignicons.min.css"].decode(), used_icons(vuetify)).encode(),
    }
    os.makedirs(VENDOR, exist_ok=True)
    for name in os.listdir(VENDOR):   # leave nothing from an earlier version behind
        if name not in wanted and name != "versions.json":
            os.remove(os.path.join(VENDOR, name))
    for name, data in wanted.items():
        with open(os.path.join(VENDOR, name), "wb") as f:
            f.write(data)
        print(f"  {name:36} {len(data) / 1024:8.1f} KB")
    with open(os.path.join(VENDOR, "versions.json"), "w", encoding="utf-8") as f:
        json.dump({"vue": VUE, "vuetify": VUETIFY, "@mdi/font": MDI}, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
