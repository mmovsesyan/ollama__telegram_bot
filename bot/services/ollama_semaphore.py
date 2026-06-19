"""Global concurrency limiter for Ollama LLM requests.

A single semaphore protects the network calls so a burst of proactive jobs,
chat completions, and background analyses cannot overwhelm the local model.
"""

import asyncio

from bot.settings import OLLAMA_MAX_CONCURRENT

ollama_semaphore: asyncio.Semaphore = asyncio.Semaphore(max(1, OLLAMA_MAX_CONCURRENT))
