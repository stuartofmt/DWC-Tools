#!/bin/bash
# Start standalone_tools: with its venv when there is one, else with the system python3 (needs python3-flask).
cd "$(dirname "$0")"
if [ -x venv/bin/python ]; then
	exec venv/bin/python -u code/standalone_tools.py "$@"
fi
exec python3 -u code/standalone_tools.py "$@"
