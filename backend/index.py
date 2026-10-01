"""Vercel serverless entrypoint: re-export the FastAPI app.

Vercel's Python runtime auto-detects an ASGI `app` in index.py at the
project root.
"""
from app.main import app  # noqa: F401
