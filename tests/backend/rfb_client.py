"""Minimal RFB client for tests: handshake and the Extended Clipboard extension.

Reference: rfbproto, "Extended Clipboard Pseudo-Encoding".
"""

from __future__ import annotations

import socket
import struct
import zlib

EXTENDED_CLIPBOARD = -1063131698  # 0xC0A1E5CE as a signed 32-bit integer

FORMAT_TEXT = 1 << 0
ACTION_CAPS = 1 << 24
ACTION_REQUEST = 1 << 25
ACTION_PEEK = 1 << 26
ACTION_NOTIFY = 1 << 27
ACTION_PROVIDE = 1 << 28
ACTIONS = ACTION_CAPS | ACTION_REQUEST | ACTION_PEEK | ACTION_NOTIFY | ACTION_PROVIDE


class RfbClient:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        sock.settimeout(5)
        version = self._recv(12)
        if not version.startswith(b"RFB 003."):
            raise ValueError(f"not an RFB server: {version!r}")
        sock.sendall(b"RFB 003.008\n")
        count = self._recv(1)[0]
        if count == 0:
            raise ValueError("server refused the connection")
        if 1 not in self._recv(count):
            raise ValueError("server requires authentication")
        sock.sendall(b"\x01")
        if struct.unpack(">I", self._recv(4))[0] != 0:
            raise ValueError("security handshake failed")
        sock.sendall(b"\x01")  # shared session
        _w, _h = struct.unpack(">HH", self._recv(4))
        self._recv(16)  # pixel format
        (name_len,) = struct.unpack(">I", self._recv(4))
        self.name = self._recv(name_len).decode("utf-8", "replace")
        encodings = [0, EXTENDED_CLIPBOARD]
        sock.sendall(
            struct.pack(">BxH", 2, len(encodings)) + struct.pack(f">{len(encodings)}i", *encodings)
        )

    def _recv(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("connection closed")
            data += chunk
        return data

    def read_clipboard_message(self) -> tuple[int, bytes]:
        """Wait for the next extended ServerCutText; return (flags, payload)."""
        while True:
            msg_type = self._recv(1)[0]
            if msg_type == 2:  # bell
                continue
            if msg_type != 3:
                raise ValueError(f"unexpected server message {msg_type}")
            (length,) = struct.unpack(">3xi", self._recv(7))
            if length >= 0:
                self._recv(length)  # legacy Latin-1 cut text, ignored
                continue
            body = self._recv(-length)
            (flags,) = struct.unpack(">I", body[:4])
            return flags, body[4:]

    def _send_extended(self, flags: int, payload: bytes = b"") -> None:
        body = struct.pack(">I", flags) + payload
        self.sock.sendall(struct.pack(">B3xi", 6, -len(body)) + body)

    def send_caps(self, max_text: int = 1 << 20) -> None:
        self._send_extended(ACTIONS | FORMAT_TEXT, struct.pack(">I", max_text))

    def provide_text(self, text: str) -> None:
        data = text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8") + b"\0"
        self._send_extended(
            ACTION_PROVIDE | FORMAT_TEXT, zlib.compress(struct.pack(">I", len(data)) + data)
        )

    def notify_text(self) -> None:
        self._send_extended(ACTION_NOTIFY | FORMAT_TEXT)

    def request_text(self) -> None:
        self._send_extended(ACTION_REQUEST | FORMAT_TEXT)

    @staticmethod
    def decode_text(payload: bytes) -> str:
        raw = zlib.decompress(payload)
        (size,) = struct.unpack(">I", raw[:4])
        return raw[4 : 4 + size].rstrip(b"\0").decode("utf-8").replace("\r\n", "\n")

    def close(self) -> None:
        self.sock.close()
