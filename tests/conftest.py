import socket

import pytest

_real_socket = socket.socket


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    # Unix-domain sockets are local IPC (the Claude CLI tool bridge), not network; everything else is blocked.
    def guarded(family=socket.AF_INET, *args, **kwargs):
        if family != socket.AF_UNIX:
            raise AssertionError("network access attempted inside the sandbox test session")
        return _real_socket(family, *args, **kwargs)

    monkeypatch.setattr(socket, "socket", guarded)
