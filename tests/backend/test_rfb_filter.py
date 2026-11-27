"""Shared console: the relay holds back resize requests from the client stream."""

from __future__ import annotations

import struct
import zlib

import pytest

from kvmstudio.console.rfb_filter import ClientStream

HANDSHAKE = b"RFB 003.008\n" + b"\x01" + b"\x01"
SET_ENCODINGS = struct.pack(">BxH3i", 2, 3, 7, -223, -308)
UPDATE_REQUEST = struct.pack(">BBHHHH", 3, 1, 0, 0, 1024, 768)
POINTER = struct.pack(">BBHH", 5, 0, 10, 20)
KEY = struct.pack(">BBxxI", 4, 1, 0x61)
CUT_TEXT = struct.pack(">BxxxI", 6, 5) + b"hello"
EXTENDED_CUT = struct.pack(">Bxxxi", 6, -8) + b"\x00" * 8
FENCE = struct.pack(">BxxxIB", 248, 0, 3) + b"abc"
QEMU_KEY = struct.pack(">BBHII", 255, 0, 1, 0x61, 30)
RESIZE = struct.pack(">BxHHBx", 251, 1280, 800, 1) + struct.pack(">IHHHHI", 0, 0, 0, 1280, 800, 0)
OTHERS = SET_ENCODINGS + UPDATE_REQUEST + POINTER + KEY + CUT_TEXT + EXTENDED_CUT + FENCE + QEMU_KEY


def run(chunks: list[bytes], *, hold: bool) -> bytes:
    stream = ClientStream(lambda: hold)
    return b"".join(stream.feed(c) for c in chunks)


def test_one_person_resizes_the_guest() -> None:
    data = HANDSHAKE + OTHERS + RESIZE + POINTER
    assert run([data], hold=False) == data


def test_resize_requests_are_dropped_when_shared() -> None:
    data = HANDSHAKE + OTHERS + RESIZE + POINTER + RESIZE
    assert run([data], hold=True) == HANDSHAKE + OTHERS + POINTER


@pytest.mark.parametrize("size", [1, 3, 7])
def test_messages_split_anywhere(size: int) -> None:
    data = HANDSHAKE + OTHERS + RESIZE + POINTER
    chunks = [data[i : i + size] for i in range(0, len(data), size)]
    assert run(chunks, hold=True) == HANDSHAKE + OTHERS + POINTER


def test_the_handshake_is_passed_at_once() -> None:
    stream = ClientStream(lambda: True)
    assert stream.feed(b"RFB 003.") == b"RFB 003."
    assert stream.feed(b"008\n\x01") == b"008\n\x01"
    assert stream.feed(b"\x01" + RESIZE + POINTER) == b"\x01" + POINTER


def test_version_3_3_sends_no_security_type() -> None:
    data = b"RFB 003.003\n" + b"\x01" + RESIZE + POINTER
    assert run([data], hold=True) == b"RFB 003.003\n\x01" + POINTER


def test_an_unknown_message_turns_the_filter_off() -> None:
    data = HANDSHAKE + POINTER + b"\x99unknown" + RESIZE
    assert run([data], hold=True) == data


def test_the_decision_is_taken_per_message() -> None:
    people = [1]
    stream = ClientStream(lambda: people[0] >= 2)
    assert stream.feed(HANDSHAKE + RESIZE) == HANDSHAKE + RESIZE
    people[0] = 2
    assert stream.feed(RESIZE + POINTER) == POINTER
    people[0] = 1
    assert stream.feed(RESIZE) == RESIZE


def provide(text: bytes, flags: int = (1 << 28) | 1) -> bytes:
    payload = struct.pack(">I", flags) + zlib.compress(struct.pack(">I", len(text)) + text)
    return struct.pack(">Bxxxi", 6, -len(payload)) + payload


def provided_text(message: bytes) -> bytes:
    data = zlib.decompress(message[12:])
    return data[4 : 4 + struct.unpack(">I", data[:4])[0]]


def test_pasted_text_loses_its_trailing_nul() -> None:
    """noVNC ends the text with NUL; QEMU would give it to the guest as it is."""
    text = "Grüße, été 2026\r\nmot de passe".encode()
    out = run([HANDSHAKE + provide(text + b"\0") + POINTER], hold=False)
    assert out.startswith(HANDSHAKE)
    message = out[len(HANDSHAKE) : -len(POINTER)]
    assert provided_text(message) == text
    assert out.endswith(POINTER)


def test_other_clipboard_messages_are_left_alone() -> None:
    caps = provide(b"", flags=(1 << 24) | 1)
    legacy = struct.pack(">BxxxI", 6, 4) + b"abc\0"
    no_nul = provide(b"abc")
    zip_bomb = provide(b"a" * (3 << 20) + b"\0")
    for message in (caps, legacy, no_nul, zip_bomb):
        assert run([HANDSHAKE + message], hold=False) == HANDSHAKE + message
