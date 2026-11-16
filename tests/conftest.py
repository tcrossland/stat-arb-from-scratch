"""Shared test configuration.

Tests never touch the network. They run on small synthetic fixtures; only the
data build reads the cache or downloads.
"""

from __future__ import annotations

import socket

import pytest


class NetworkAccessError(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def guard(*args: object, **kwargs: object) -> None:
        raise NetworkAccessError("tests must not access the network")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket.socket, "connect_ex", guard)
    monkeypatch.setattr(socket, "create_connection", guard)
