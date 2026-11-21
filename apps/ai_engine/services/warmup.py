"""Load AI SDK code before the web server accepts its first chat request.

No provider calls, credentials, answers, or retrieved documents are cached here.
Connections remain lazily created in the generation thread.
"""
import importlib
import logging

from django.conf import settings

logger = logging.getLogger('itrix')


def preload_ai_runtime():
    if not getattr(settings, 'ENABLE_AI_ENGINE', False):
        return
    for module, symbol in (('anthropic', 'Anthropic'), ('openai', 'OpenAI'), ('pinecone', 'Pinecone')):
        try:
            getattr(importlib.import_module(module), symbol)
        except (ImportError, AttributeError):
            # Preserve the existing graceful fallback for optional integrations.
            logger.warning('AI runtime preload unavailable: %s', module)
