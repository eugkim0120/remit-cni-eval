import socket

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("network access attempted inside the sandbox test session")

    monkeypatch.setattr(socket, "socket", blocked)
