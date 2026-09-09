#!/bin/bash
# SDRC Osteo Collector launcher
# Runs the tkinter UI with the correct venv and working directory,
# logging to a rotating file alongside the script.
cd /opt/sdrc/sdrc-dexa-worker/worker
exec /opt/sdrc/sdrc-dexa-worker/venv/bin/python collector_osteo_ui.py \
  2>> /opt/sdrc/sdrc-dexa-worker/collector.log
