"""Groq LLM factory for the reasoning agents."""

from __future__ import annotations

import os
from functools import lru_cache

from api.config import settings


@lru_cache(maxsize=4)
def get_llm(temperature: float = 0.1):
    """Return a cached ChatGroq client. Raises if Groq isn't configured."""
    if not settings.groq_enabled:
        raise RuntimeError("Groq not configured (set GROQ_API_KEY).")
    # langchain-groq reads GROQ_API_KEY from the environment.
    os.environ.setdefault("GROQ_API_KEY", settings.groq_api_key)
    from langchain_groq import ChatGroq

    return ChatGroq(
        model=settings.groq_model,
        temperature=temperature,
        max_retries=2,
        timeout=30,
    )
