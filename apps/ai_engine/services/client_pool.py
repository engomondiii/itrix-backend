"""Reuse SDK connection pools without caching prompts, answers or source data."""
import os
from threading import local

_state = local()


def reusable_client(provider, configuration, factory):
    """One client per provider and generation thread, isolated across worker forks.

    Credentials and transport settings are part of the key so rotations and test
    overrides cannot accidentally reuse an old client. Query results stay fresh.
    """
    clients = getattr(_state, "clients", None)
    if clients is None:
        clients = _state.clients = {}
    key = (os.getpid(), configuration)
    previous = clients.get(provider)
    if previous is not None and previous[0] == key:
        return previous[1]
    client = factory()
    clients[provider] = (key, client)
    if previous is not None and previous[0][0] == os.getpid():
        close = getattr(previous[1], "close", None)
        if close:
            close()
    return client
