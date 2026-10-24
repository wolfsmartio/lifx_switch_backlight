"""Protocol tests against a fake LIFX Switch on localhost."""

from __future__ import annotations

import asyncio
import struct

import pytest

from custom_components.lifx_switch_backlight.protocol import (
    MSG_ACKNOWLEDGEMENT,
    MSG_GET_BUTTON_CONFIG,
    MSG_GET_LABEL,
    MSG_GET_SERVICE,
    MSG_SET_BUTTON_CONFIG,
    MSG_STATE_BUTTON_CONFIG,
    MSG_STATE_LABEL,
    MSG_STATE_SERVICE,
    MSG_STATE_UNHANDLED,
    ButtonConfig,
    Hsbk,
    LifxSwitch,
    LifxTimeoutError,
    LifxUnsupportedError,
    build_packet,
    discover_switches,
    parse_packet,
)

# Real UDP on localhost; the HA test plugin blocks sockets by default.
pytestmark = pytest.mark.usefixtures("socket_enabled")

SWITCH_MAC = "d0:73:d5:12:34:56"
LIGHT_MAC = "d0:73:d5:ab:cd:ef"


def test_header_layout() -> None:
    packet = build_packet(
        MSG_GET_BUTTON_CONFIG, source=0x11223344, sequence=7, target=SWITCH_MAC, res_required=True
    )
    assert len(packet) == 36
    size, proto = struct.unpack_from("<HH", packet)
    assert size == 36
    assert proto & 0x0FFF == 1024
    assert proto & (1 << 12)
    assert not proto & (1 << 13)  # not tagged when a target is given
    assert packet[8:16] == bytes.fromhex("d073d5123456") + b"\x00\x00"
    assert packet[22] == 0x01 and packet[23] == 7
    assert struct.unpack_from("<H", packet, 32)[0] == 909

    tagged = build_packet(MSG_GET_SERVICE, source=1, sequence=0)
    assert struct.unpack_from("<H", tagged, 2)[0] & (1 << 13)


def test_button_config_payload_matches_aiolifx_layout() -> None:
    config = ButtonConfig(30, Hsbk(1, 2, 3, 3500), Hsbk(4, 5, 6, 2700))
    payload = config.pack()
    assert payload == struct.pack("<9H", 30, 1, 2, 3, 3500, 4, 5, 6, 2700)
    assert ButtonConfig.unpack(payload) == config
    assert ButtonConfig.from_dict(config.as_dict()) == config


def test_user_unit_conversion() -> None:
    color = Hsbk.from_user(240, 100, 50, 3500)
    assert color == Hsbk(43690, 65535, 32768, 3500)
    assert round(color.hue_deg) == 240
    assert Hsbk.from_user(360, 0, 0, 2700).hue == 0
    assert color.updated(brightness_pct=100) == Hsbk(43690, 65535, 65535, 3500)


class FakeDevice(asyncio.DatagramProtocol):
    """Answers like a Switch (button config) or a light (StateUnhandled)."""

    def __init__(self, mac: str, label: str, is_switch: bool, drop_first: int = 0) -> None:
        self.mac = mac
        self.label = label
        self.is_switch = is_switch
        self.drop_first = drop_first
        self.config = ButtonConfig(30, Hsbk.from_user(240, 100, 100, 3500), Hsbk(0, 65535, 65535, 2700))
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport) -> None:
        self.transport = transport

    def _reply(self, msg, msg_type: int, payload: bytes, addr) -> None:
        packet = build_packet(
            msg_type, source=msg.source, sequence=msg.sequence, target=self.mac, payload=payload
        )
        self.transport.sendto(packet, addr)

    def datagram_received(self, data: bytes, addr) -> None:
        if (msg := parse_packet(data)) is not None:
            self.handle(msg, addr)

    def handle(self, msg, addr) -> None:
        if self.drop_first:
            self.drop_first -= 1
            return
        if msg.msg_type == MSG_GET_SERVICE:
            self._reply(msg, MSG_STATE_SERVICE, struct.pack("<BI", 1, 56700), addr)
        elif msg.msg_type == MSG_GET_LABEL:
            self._reply(msg, MSG_STATE_LABEL, self.label.encode().ljust(32, b"\x00"), addr)
        elif not self.is_switch:
            self._reply(msg, MSG_STATE_UNHANDLED, struct.pack("<H", msg.msg_type), addr)
        elif msg.msg_type == MSG_GET_BUTTON_CONFIG:
            self._reply(msg, MSG_STATE_BUTTON_CONFIG, self.config.pack(), addr)
        elif msg.msg_type == MSG_SET_BUTTON_CONFIG:
            self.config = ButtonConfig.unpack(msg.payload)
            self._reply(msg, MSG_ACKNOWLEDGEMENT, b"", addr)


async def _serve(device: asyncio.DatagramProtocol, host: str = "127.0.0.1") -> tuple[asyncio.DatagramTransport, int]:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(lambda: device, local_addr=(host, 0))
    return transport, transport.get_extra_info("sockname")[1]


async def test_identify_get_and_set() -> None:
    device = FakeDevice(SWITCH_MAC, "Kitchen", is_switch=True, drop_first=1)
    transport, port = await _serve(device)
    try:
        client = LifxSwitch("127.0.0.1", port=port, timeout=0.2)
        info = await client.identify()
        assert info.serial == SWITCH_MAC
        assert info.label == "Kitchen"
        assert info.config == device.config

        new = ButtonConfig(60, Hsbk.from_user(120, 50, 25, 4000), Hsbk(0, 0, 0, 2700))
        await client.set_button_config(new)
        assert device.config == new
        assert await client.get_button_config() == new
    finally:
        transport.close()


async def test_light_is_rejected_quickly() -> None:
    transport, port = await _serve(FakeDevice(LIGHT_MAC, "Lamp", is_switch=False))
    try:
        with pytest.raises(LifxUnsupportedError):
            await LifxSwitch("127.0.0.1", port=port, timeout=0.2).identify()
    finally:
        transport.close()


async def test_timeout() -> None:
    transport, port = await _serve(FakeDevice(SWITCH_MAC, "x", True, drop_first=99))
    try:
        with pytest.raises(LifxTimeoutError):
            await LifxSwitch("127.0.0.1", port=port, timeout=0.05, retries=2).get_button_config()
    finally:
        transport.close()


class FakeNetwork(asyncio.DatagramProtocol):
    """Several fake devices behind one socket, routed by target MAC."""

    def __init__(self, *devices: FakeDevice) -> None:
        self.devices = devices

    def connection_made(self, transport) -> None:
        for device in self.devices:
            device.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        if (msg := parse_packet(data)) is None:
            return
        for device in self.devices:
            if msg.serial in ("00:00:00:00:00:00", device.mac):
                device.handle(msg, addr)


async def test_discovery_keeps_only_switches() -> None:
    network = FakeNetwork(
        FakeDevice(SWITCH_MAC, "Hall", is_switch=True),
        FakeDevice(LIGHT_MAC, "Lamp", is_switch=False),
    )
    transport, port = await _serve(network)
    try:
        found = await discover_switches(["127.0.0.1"], port=port, timeout=0.3)
        assert [(s.serial, s.label, s.host) for s in found] == [(SWITCH_MAC, "Hall", "127.0.0.1")]
    finally:
        transport.close()
