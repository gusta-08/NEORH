#!/bin/sh
# Ensure DB tables exist (create_all) and then start the server
# Calls the app's `create_tables()` function (safe no-op if tables exist)
python -c 'from app import create_tables; create_tables()'
exec gunicorn -w 4 -b 0.0.0.0:${PORT:-5000} "app:app"
