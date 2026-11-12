"""Vercel serverless entrypoint. Exposes the Flask WSGI app.

NOTE: Vercel functions are short-lived, so the background trading bot / price-feed threads cannot
run reliably there. Deploy the bot on a persistent host (Render, Railway, Docker, VPS) - see
render.yaml / Dockerfile - and use Vercel only for the web UI if you must.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from run import app  # noqa: E402,F401
