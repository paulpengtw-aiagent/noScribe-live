"""Backend for noScribe Live: tails the CLI's NDJSON feeds and serves them to the browser.

Modules: feed (tailing + run registry), app (FastAPI), peaks (waveform), replay (rehearsal tool),
and __main__ (``python -m server``). Keep this file import-free so that ``python -m server.replay``
does not pull in FastAPI.
"""
