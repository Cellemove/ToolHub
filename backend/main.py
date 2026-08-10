"""Vercel entrypoint — exposes the FastAPI app with an absolute import."""

from app.main import app as app
