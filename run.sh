#!/bin/bash
# Start plugin_tools with its own venv. If there is no venv yet it is created first, and the requirements.txt
# files are installed into it, again whenever one of them has changed since the last install.
cd "$(dirname "$0")"
STAMP=venv/.requirements-installed   # touched after a successful install
REQS=()
for r in code/requirements.txt requirements.txt; do
	[ -f "$r" ] && REQS+=("$r")
done

if [ ! -x venv/bin/python ]; then
	echo "Creating the venv in $PWD/venv"
	if ! python3 -m venv venv; then
		rm -rf venv   # never leave a half-made venv: it would be taken as ready next time
		echo "Could not create the venv. On Debian or Raspberry Pi OS install the venv module with: sudo apt install python3-venv" >&2
		exit 1
	fi
fi

need=
for r in "${REQS[@]}"; do
	if [ ! -f "$STAMP" ] || [ "$r" -nt "$STAMP" ]; then
		need=1
	fi
done
if [ -n "$need" ]; then
	for r in "${REQS[@]}"; do
		echo "Installing $r into the venv"
		if ! venv/bin/python -m pip install -r "$r"; then
			echo "Could not install $r into the venv" >&2
			exit 1
		fi
	done
	touch "$STAMP"
fi

exec venv/bin/python -u code/plugin_tools.py "$@"
