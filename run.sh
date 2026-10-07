#!/bin/bash
# Start the program with its venv (made by Prepare in Prep_and_Package).
cd "$(dirname "$0")"
exec venv/bin/python -u code/prep_and_package.py "$@"
