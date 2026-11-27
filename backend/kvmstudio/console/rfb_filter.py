"""Reads what a VNC client sends, message by message, to hold back resize requests
and to clean the text a client pastes.

When several people share the console of a VM, one of them asking the guest
for a new resolution would change the picture of all the others. The relay
then drops SetDesktopSize: the guest keeps its resolution and each client
scales the picture locally.

Pasted text comes in extended clipboard Provide messages, NUL-terminated as
the protocol asks. QEMU hands it to the guest agent as it is, so the guest
clipboard would end with a NUL character (a pasted password then fails): the
relay removes it.

Only the client to server direction is read. Anything not understood turns the
filter off for the rest of the connection: bytes are then passed on unchanged.
"""

from __future__ import annotations

import logging
import struct
import zlib
from collections.abc import Callable

log = logging.getLogger(__name__)

SET_DESKTOP_SIZE = 251
CLIENT_CUT_TEXT = 6
# Extended clipboard flags (community extension of RFB).
CLIPBOARD_TEXT = 1 << 0
CLIPBOARD_PROVIDE = 1 << 28
# Longer messages are not held in memory but passed on (QEMU refuses a
# clipboard over 1 MiB and drops the connection anyway).
MAX_HELD = (1 << 20) + 16

# Client message types of fixed length (RFC 6143 and its community extensions).
_FIXED = {
    0: 20,  # SetPixelFormat
    3: 10,  # FramebufferUpdateRequest
    4: 8,  # KeyEvent
    5: 6,  # PointerEvent
    150: 10,  # EnableContinuousUpdates
    250: 4,  # xvp
}


def _message_length(data: bytes | bytearray) -> int | None:
    """Length of the message at the start of data; 0 if more bytes are needed,
    None if the message type is not known."""
    if not data:
        return 0
    kind = data[0]
    if kind in _FIXED:
        return _FIXED[kind]
    if kind == 2:  # SetEncodings
        return 4 + 4 * int.from_bytes(data[2:4], "big") if len(data) >= 4 else 0
    if kind == 6:  # ClientCutText, negative length for the extended clipboard
        if len(data) < 8:
            return 0
        return 8 + abs(int.from_bytes(data[4:8], "big", signed=True))
    if kind == 248:  # Fence
        return 9 + data[8] if len(data) >= 9 else 0
    if kind == SET_DESKTOP_SIZE:
        return 8 + 16 * data[6] if len(data) >= 7 else 0
    if kind == 255:  # QEMU: extended key event, audio
        if len(data) < 2:
            return 0
        if data[1] == 0:
            return 12
        if data[1] == 1:
            if len(data) < 4:
                return 0
            operation = int.from_bytes(data[2:4], "big")
            return {0: 4, 1: 4, 2: 10}.get(operation)
    return None


class ClientStream:
    """Splits the client stream into messages; drops SetDesktopSize when told to."""

    def __init__(self, hold_resize: Callable[[], bool]) -> None:
        self._hold_resize = hold_resize
        self._buffer = bytearray()
        self._version = bytearray()  # "RFB 003.008\n", as sent by the client
        self._handshake = 12  # bytes still to pass before the first message
        self._passthrough = False

    def feed(self, data: bytes) -> bytes:
        """Bytes received from the client; returns those to send to the server."""
        if self._passthrough:
            return data
        out = bytearray()
        # Passed on at once. After the version, 3.7 and 3.8 pick a security
        # type and send ClientInit (one byte each); 3.3 only sends ClientInit.
        # libvirt's socket uses no security, which asks for nothing more.
        while self._handshake and data:
            take = data[: self._handshake]
            data = data[len(take) :]
            out += take
            self._handshake -= len(take)
            if len(self._version) < 12:
                self._version += take[: 12 - len(self._version)]
                if len(self._version) == 12:
                    self._handshake += 1 if self._version[8:11] == b"003" else 2
        if self._handshake:
            return bytes(out)
        self._buffer += data
        while self._buffer:
            length = _message_length(self._buffer)
            if length is None or length > MAX_HELD:
                log.warning("VNC client message %d not filtered", self._buffer[0])
                self._passthrough = True
                out += self._buffer
                self._buffer.clear()
                break
            if length == 0 or len(self._buffer) < length:
                break
            message = bytes(self._buffer[:length])
            del self._buffer[:length]
            if message[0] == SET_DESKTOP_SIZE and self._hold_resize():
                continue
            if message[0] == CLIENT_CUT_TEXT:
                message = provide_without_nul(message)
            out += message
        return bytes(out)


def provide_without_nul(message: bytes) -> bytes:
    """An extended clipboard Provide with the trailing NUL of its text removed.

    Anything else (legacy cut text, other actions, data that does not unpack)
    is returned unchanged.
    """
    (length,) = struct.unpack(">i", message[4:8])
    if length >= 0 or len(message) < 12:
        return message
    (flags,) = struct.unpack(">I", message[8:12])
    if not flags & CLIPBOARD_PROVIDE or flags & 0xFFFF != CLIPBOARD_TEXT:
        return message
    inflate = zlib.decompressobj()
    try:
        data = inflate.decompress(message[12:], MAX_HELD)
    except zlib.error:
        return message
    if inflate.unconsumed_tail or len(data) < 4:
        return message  # larger than anything held here: passed on as it is
    (size,) = struct.unpack(">I", data[:4])
    text = data[4 : 4 + size]
    if len(text) != size or not text.endswith(b"\0"):
        return message
    text = text.rstrip(b"\0")
    payload = struct.pack(">I", flags) + zlib.compress(struct.pack(">I", len(text)) + text)
    return message[:4] + struct.pack(">i", -len(payload)) + payload
