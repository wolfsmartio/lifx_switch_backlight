"""Minimal LIFX LAN protocol client for LIFX Switch button settings.

Only the packets needed to find Switches and read/write their button config
(haptic feedback duration and backlight colors) are implemented. This module
has no Home Assistant imports so it can be tested on its own.

Packet layout follows https://lan.developer.lifx.com/docs/packet-contents and
matches what aiolifx sends for SetButtonConfig (910).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
import random
import struct
from typing import Any

DEFAULT_PORT = 56700

_PROTOCOL = 1024
_ADDRESSABLE = 1 << 12
_TAGGED = 1 << 13
_RES_REQUIRED = 0x01
_ACK_REQUIRED = 0x02

# size, protocol bits, source, target, reserved, flags, sequence, reserved, type, reserved
_HEADER = struct.Struct("<HHI8s6sBB8sHH")
# haptic_duration_ms, on (h, s, b, k), off (h, s, b, k)
_BUTTON_CONFIG = struct.Struct("<H4H4H")

MSG_GET_SERVICE = 2
MSG_STATE_SERVICE = 3
MSG_GET_LABEL = 23
MSG_STATE_LABEL = 25
MSG_ACKNOWLEDGEMENT = 45
MSG_STATE_UNHANDLED = 223
MSG_GET_BUTTON_CONFIG = 909
MSG_SET_BUTTON_CONFIG = 910
MSG_STATE_BUTTON_CONFIG = 911

UINT16_MAX = 65535


class LifxError(Exception):
    """Base error for LIFX communication."""


class LifxTimeoutError(LifxError):
    """The device did not answer in time."""


class LifxUnsupportedError(LifxError):
    """The device answered but does not support button config (not a Switch)."""


def _scale_to_raw(value: float, full_scale: float) -> int:
    return max(0, min(UINT16_MAX, round(value / full_scale * UINT16_MAX)))


@dataclass(frozen=True)
class Hsbk:
    """A backlight color in raw protocol units (0-65535; kelvin as-is)."""

    hue: int
    saturation: int
    brightness: int
    kelvin: int

    @classmethod
    def from_user(
        cls, hue_deg: float, saturation_pct: float, brightness_pct: float, kelvin: int
    ) -> Hsbk:
        """Build from degrees, percentages and kelvin."""
        return cls(0, 0, 0, 0).updated(
            hue_deg=hue_deg,
            saturation_pct=saturation_pct,
            brightness_pct=brightness_pct,
            kelvin=kelvin,
        )

    def updated(
        self,
        *,
        hue_deg: float | None = None,
        saturation_pct: float | None = None,
        brightness_pct: float | None = None,
        kelvin: int | None = None,
    ) -> Hsbk:
        """Return a copy with only the given user-unit fields changed."""
        changes: dict[str, int] = {}
        if hue_deg is not None:
            changes["hue"] = _scale_to_raw(hue_deg % 360, 360)
        if saturation_pct is not None:
            changes["saturation"] = _scale_to_raw(saturation_pct, 100)
        if brightness_pct is not None:
            changes["brightness"] = _scale_to_raw(brightness_pct, 100)
        if kelvin is not None:
            changes["kelvin"] = int(kelvin)
        return replace(self, **changes)

    @property
    def hue_deg(self) -> float:
        return self.hue * 360 / UINT16_MAX

    @property
    def saturation_pct(self) -> float:
        return self.saturation * 100 / UINT16_MAX

    @property
    def brightness_pct(self) -> float:
        return self.brightness * 100 / UINT16_MAX

    def as_list(self) -> list[int]:
        return [self.hue, self.saturation, self.brightness, self.kelvin]


@dataclass(frozen=True)
class ButtonConfig:
    """Switch button config: haptic feedback and backlight colors."""

    haptic_duration_ms: int
    on: Hsbk
    off: Hsbk

    def pack(self) -> bytes:
        return _BUTTON_CONFIG.pack(
            self.haptic_duration_ms, *self.on.as_list(), *self.off.as_list()
        )

    @classmethod
    def unpack(cls, payload: bytes) -> ButtonConfig:
        if len(payload) < _BUTTON_CONFIG.size:
            raise LifxError(f"Short StateButtonConfig payload ({len(payload)} bytes)")
        values = _BUTTON_CONFIG.unpack_from(payload)
        return cls(values[0], Hsbk(*values[1:5]), Hsbk(*values[5:9]))

    def as_dict(self) -> dict[str, Any]:
        return {
            "haptic_duration_ms": self.haptic_duration_ms,
            "on": self.on.as_list(),
            "off": self.off.as_list(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ButtonConfig:
        return cls(data["haptic_duration_ms"], Hsbk(*data["on"]), Hsbk(*data["off"]))


@dataclass(frozen=True)
class Message:
    """A decoded LIFX packet."""

    msg_type: int
    source: int
    sequence: int
    serial: str
    payload: bytes


@dataclass(frozen=True)
class SwitchInfo:
    """A Switch that answered a button-config probe."""

    host: str
    serial: str
    label: str
    config: ButtonConfig


def normalize_mac(mac: str) -> str:
    """Return a MAC as lowercase aa:bb:cc:dd:ee:ff."""
    digits = mac.lower().replace(":", "").replace("-", "")
    if len(digits) != 12:
        raise ValueError(f"Invalid MAC address: {mac}")
    bytes.fromhex(digits)
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def _mac_to_target(mac: str) -> bytes:
    return bytes.fromhex(normalize_mac(mac).replace(":", "")) + bytes(2)


def _target_to_mac(target: bytes) -> str:
    return ":".join(f"{b:02x}" for b in target[:6])


def build_packet(
    msg_type: int,
    *,
    source: int,
    sequence: int,
    target: str | None = None,
    payload: bytes = b"",
    ack_required: bool = False,
    res_required: bool = False,
) -> bytes:
    """Encode a LIFX packet. A target of None addresses all devices (tagged)."""
    protocol = _PROTOCOL | _ADDRESSABLE | (_TAGGED if target is None else 0)
    flags = (_ACK_REQUIRED if ack_required else 0) | (_RES_REQUIRED if res_required else 0)
    header = _HEADER.pack(
        _HEADER.size + len(payload),
        protocol,
        source,
        bytes(8) if target is None else _mac_to_target(target),
        bytes(6),
        flags,
        sequence,
        bytes(8),
        msg_type,
        0,
    )
    return header + payload


def parse_packet(data: bytes) -> Message | None:
    """Decode a LIFX packet, or return None if it is malformed."""
    if len(data) < _HEADER.size:
        return None
    size, _, source, target, _, _, sequence, _, msg_type, _ = _HEADER.unpack_from(data)
    if size < _HEADER.size or size > len(data):
        return None
    return Message(msg_type, source, sequence, _target_to_mac(target), data[_HEADER.size : size])


class _Receiver(asyncio.DatagramProtocol):
    def __init__(self, on_message: Callable[[Message, tuple[str, int]], None]) -> None:
        self._on_message = on_message

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if (msg := parse_packet(data)) is not None:
            self._on_message(msg, addr)


class LifxSwitch:
    """Talks to one LIFX Switch over UDP."""

    def __init__(
        self,
        host: str,
        serial: str | None = None,
        *,
        port: int = DEFAULT_PORT,
        timeout: float = 0.5,
        retries: int = 4,
    ) -> None:
        self.host = host
        self.serial = normalize_mac(serial) if serial else None
        self.port = port
        self.timeout = timeout
        self.retries = retries
        self._source = random.randint(2, 0xFFFFFFFF)
        self._sequence = random.randint(0, 255)

    async def _request(self, msg_type: int, expect: int, payload: bytes = b"") -> Message:
        loop = asyncio.get_running_loop()
        self._sequence = (self._sequence + 1) % 256
        sequence = self._sequence
        packet = build_packet(
            msg_type,
            source=self._source,
            sequence=sequence,
            target=self.serial,
            payload=payload,
            ack_required=expect == MSG_ACKNOWLEDGEMENT,
            res_required=expect != MSG_ACKNOWLEDGEMENT,
        )
        future: asyncio.Future[Message] = loop.create_future()

        def on_message(msg: Message, addr: tuple[str, int]) -> None:
            if future.done() or msg.source != self._source or msg.sequence != sequence:
                return
            if msg.msg_type == expect:
                future.set_result(msg)
            elif msg.msg_type == MSG_STATE_UNHANDLED:
                future.set_exception(
                    LifxUnsupportedError(f"{self.host} does not support message {msg_type}")
                )

        try:
            transport, _ = await loop.create_datagram_endpoint(
                lambda: _Receiver(on_message), remote_addr=(self.host, self.port)
            )
        except OSError as err:
            raise LifxError(f"Cannot open UDP socket to {self.host}: {err}") from err
        try:
            for _ in range(self.retries):
                transport.sendto(packet)
                try:
                    msg = await asyncio.wait_for(asyncio.shield(future), self.timeout)
                except asyncio.TimeoutError:
                    continue
                if self.serial is None:
                    self.serial = msg.serial
                return msg
            raise LifxTimeoutError(f"No response from {self.host} to message {msg_type}")
        finally:
            transport.close()
            if not future.done():
                future.cancel()

    async def get_button_config(self) -> ButtonConfig:
        msg = await self._request(MSG_GET_BUTTON_CONFIG, MSG_STATE_BUTTON_CONFIG)
        return ButtonConfig.unpack(msg.payload)

    async def set_button_config(self, config: ButtonConfig) -> None:
        await self._request(MSG_SET_BUTTON_CONFIG, MSG_ACKNOWLEDGEMENT, config.pack())

    async def get_label(self) -> str:
        msg = await self._request(MSG_GET_LABEL, MSG_STATE_LABEL)
        return msg.payload[:32].split(b"\x00", 1)[0].decode("utf-8", errors="replace")

    async def identify(self) -> SwitchInfo:
        """Confirm this is a Switch and learn its serial and label."""
        config = await self.get_button_config()
        try:
            label = await self.get_label()
        except LifxError:
            label = ""
        assert self.serial is not None
        return SwitchInfo(self.host, self.serial, label, config)


async def discover_hosts(
    broadcast_addresses: Iterable[str] = ("255.255.255.255",),
    *,
    port: int = DEFAULT_PORT,
    timeout: float = 1.5,
) -> dict[str, str]:
    """Broadcast GetService and return {serial: host} for every LIFX device."""
    loop = asyncio.get_running_loop()
    source = random.randint(2, 0xFFFFFFFF)
    found: dict[str, str] = {}

    def on_message(msg: Message, addr: tuple[str, int]) -> None:
        if msg.msg_type == MSG_STATE_SERVICE and msg.source == source:
            found.setdefault(msg.serial, addr[0])

    try:
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _Receiver(on_message), local_addr=("0.0.0.0", 0), allow_broadcast=True
        )
    except OSError as err:
        raise LifxError(f"Cannot open UDP broadcast socket: {err}") from err
    packet = build_packet(MSG_GET_SERVICE, source=source, sequence=0)
    try:
        for _ in range(3):
            for address in broadcast_addresses:
                transport.sendto(packet, (address, port))
            await asyncio.sleep(timeout / 3)
    finally:
        transport.close()
    return found


async def discover_switches(
    broadcast_addresses: Iterable[str] = ("255.255.255.255",),
    *,
    port: int = DEFAULT_PORT,
    timeout: float = 1.5,
) -> list[SwitchInfo]:
    """Find LIFX devices, then keep the ones that answer GetButtonConfig."""
    hosts = await discover_hosts(broadcast_addresses, port=port, timeout=timeout)

    async def probe(serial: str, host: str) -> SwitchInfo | None:
        try:
            return await LifxSwitch(host, serial, port=port, retries=2).identify()
        except LifxError:
            return None

    results = await asyncio.gather(*(probe(s, h) for s, h in hosts.items()))
    return [info for info in results if info is not None]
