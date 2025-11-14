#!/bin/sh
# Executa migrations e inicia o servidor
python run_migrations.py
exec gunicorn -w 4 -b 0.0.0.0:${PORT:-5000} "app:app"
