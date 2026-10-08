# -*- coding: utf-8 -*-
"""火山引擎 / 豆包语音 WebSocket 二进制协议编解码模块。

基于火山引擎官方 DoubaoVoice Bidirectional Streaming TTS 协议规范：
- Header (Version, HeaderSize, MsgType, Flags, Serialization, Compression)
- EventType, MsgType, Message 编解码
- 连接与会话帧生成函数

# Modification History
| Version | Date       | Author      | Description |
| ------- | ---------- | ----------- | ----------- |
| 1.0.0   | 2026-10-08 | Antigravity | 初始创建，集成火山引擎官方 WebSocket 二进制协议 |
"""

import io
import logging
import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, List

import websockets

logger = logging.getLogger(__name__)


class MsgType(IntEnum):
    """Message type enumeration"""

    Invalid = 0
    FullClientRequest = 0b1
    AudioOnlyClient = 0b10
    FullServerResponse = 0b1001
    AudioOnlyServer = 0b1011
    FrontEndResultServer = 0b1100
    Error = 0b1111

    ServerACK = AudioOnlyServer

    def __str__(self) -> str:
        return self.name if self.name else f"MsgType({self.value})"


class MsgTypeFlagBits(IntEnum):
    """Message type flag bits"""

    NoSeq = 0
    PositiveSeq = 0b1
    LastNoSeq = 0b10
    NegativeSeq = 0b11
    WithEvent = 0b100


class VersionBits(IntEnum):
    """Version bits"""

    Version1 = 1
    Version2 = 2
    Version3 = 3
    Version4 = 4


class HeaderSizeBits(IntEnum):
    """Header size bits"""

    HeaderSize4 = 1
    HeaderSize8 = 2
    HeaderSize12 = 3
    HeaderSize16 = 4


class SerializationBits(IntEnum):
    """Serialization method bits"""

    Raw = 0
    JSON = 0b1
    Thrift = 0b11
    Custom = 0b1111


class CompressionBits(IntEnum):
    """Compression method bits"""

    None_ = 0
    Gzip = 0b1
    Custom = 0b1111


class EventType(IntEnum):
    """Event type enumeration"""

    None_ = 0

    # Upstream Connection events
    StartConnection = 1
    StartTask = 1
    FinishConnection = 2
    FinishTask = 2

    # Downstream Connection events
    ConnectionStarted = 50
    TaskStarted = 50
    ConnectionFailed = 51
    TaskFailed = 51
    ConnectionFinished = 52
    TaskFinished = 52

    # Upstream Session events
    StartSession = 100
    CancelSession = 101
    FinishSession = 102

    # Downstream Session events
    SessionStarted = 150
    SessionCanceled = 151
    SessionFinished = 152
    SessionFailed = 153
    UsageResponse = 154
    ChargeData = 154

    # Upstream general events
    TaskRequest = 200
    UpdateConfig = 201

    # Downstream general events
    AudioMuted = 250

    # Downstream TTS events
    TTSSentenceStart = 350
    TTSSentenceEnd = 351
    TTSResponse = 352
    TTSSubtitle = 364
    TTSEnded = 359

    def __str__(self) -> str:
        return self.name if self.name else f"EventType({self.value})"


@dataclass
class Message:
    """Message object representing Doubao TTS binary protocol frames."""

    version: VersionBits = VersionBits.Version1
    header_size: HeaderSizeBits = HeaderSizeBits.HeaderSize4
    type: MsgType = MsgType.Invalid
    flag: MsgTypeFlagBits = MsgTypeFlagBits.NoSeq
    serialization: SerializationBits = SerializationBits.JSON
    compression: CompressionBits = CompressionBits.None_

    event: EventType = EventType.None_
    session_id: str = ""
    connect_id: str = ""
    sequence: int = 0
    error_code: int = 0

    payload: bytes = b""

    @classmethod
    def from_bytes(cls, data: bytes) -> "Message":
        if len(data) < 3:
            raise ValueError(f"Data too short: expected at least 3 bytes, got {len(data)}")

        type_and_flag = data[1]
        msg_type = MsgType(type_and_flag >> 4)
        flag = MsgTypeFlagBits(type_and_flag & 0b00001111)

        msg = cls(type=msg_type, flag=flag)
        msg.unmarshal(data)
        return msg

    def marshal(self) -> bytes:
        buffer = io.BytesIO()
        header = [
            (self.version << 4) | self.header_size,
            (self.type << 4) | self.flag,
            (self.serialization << 4) | self.compression,
        ]

        header_size = 4 * self.header_size
        if padding := header_size - len(header):
            header.extend([0] * padding)

        buffer.write(bytes(header))

        for writer in self._get_writers():
            writer(buffer)

        return buffer.getvalue()

    def unmarshal(self, data: bytes) -> None:
        buffer = io.BytesIO(data)

        version_and_header_size = buffer.read(1)[0]
        self.version = VersionBits(version_and_header_size >> 4)
        self.header_size = HeaderSizeBits(version_and_header_size & 0b00001111)

        buffer.read(1)

        serialization_compression = buffer.read(1)[0]
        self.serialization = SerializationBits(serialization_compression >> 4)
        self.compression = CompressionBits(serialization_compression & 0b00001111)

        header_size = 4 * self.header_size
        read_size = 3
        if padding_size := header_size - read_size:
            buffer.read(padding_size)

        for reader in self._get_readers():
            reader(buffer)

        remaining = buffer.read()
        if remaining:
            raise ValueError(f"Unexpected data after message: {remaining}")

    def _get_writers(self) -> List[Callable[[io.BytesIO], None]]:
        writers = []
        if self.flag == MsgTypeFlagBits.WithEvent:
            writers.extend([self._write_event, self._write_session_id])

        if self.type in [
            MsgType.FullClientRequest,
            MsgType.FullServerResponse,
            MsgType.FrontEndResultServer,
            MsgType.AudioOnlyClient,
            MsgType.AudioOnlyServer,
        ]:
            if self.flag in [MsgTypeFlagBits.PositiveSeq, MsgTypeFlagBits.NegativeSeq]:
                writers.append(self._write_sequence)
        elif self.type == MsgType.Error:
            writers.append(self._write_error_code)
        else:
            raise ValueError(f"Unsupported message type: {self.type}")

        writers.append(self._write_payload)
        return writers

    def _get_readers(self) -> List[Callable[[io.BytesIO], None]]:
        readers = []
        if self.type in [
            MsgType.FullClientRequest,
            MsgType.FullServerResponse,
            MsgType.FrontEndResultServer,
            MsgType.AudioOnlyClient,
            MsgType.AudioOnlyServer,
        ]:
            if self.flag in [MsgTypeFlagBits.PositiveSeq, MsgTypeFlagBits.NegativeSeq]:
                readers.append(self._read_sequence)
        elif self.type == MsgType.Error:
            readers.append(self._read_error_code)
        else:
            raise ValueError(f"Unsupported message type: {self.type}")

        if self.flag == MsgTypeFlagBits.WithEvent:
            readers.extend([self._read_event, self._read_session_id, self._read_connect_id])

        readers.append(self._read_payload)
        return readers

    def _write_event(self, buffer: io.BytesIO) -> None:
        buffer.write(struct.pack(">i", self.event))

    def _write_session_id(self, buffer: io.BytesIO) -> None:
        if self.event in [
            EventType.StartConnection,
            EventType.FinishConnection,
            EventType.ConnectionStarted,
            EventType.ConnectionFailed,
        ]:
            return

        session_id_bytes = self.session_id.encode("utf-8")
        size = len(session_id_bytes)
        if size > 0xFFFFFFFF:
            raise ValueError(f"Session ID size ({size}) exceeds max(uint32)")

        buffer.write(struct.pack(">I", size))
        if size > 0:
            buffer.write(session_id_bytes)

    def _write_sequence(self, buffer: io.BytesIO) -> None:
        buffer.write(struct.pack(">i", self.sequence))

    def _write_error_code(self, buffer: io.BytesIO) -> None:
        buffer.write(struct.pack(">I", self.error_code))

    def _write_payload(self, buffer: io.BytesIO) -> None:
        size = len(self.payload)
        if size > 0xFFFFFFFF:
            raise ValueError(f"Payload size ({size}) exceeds max(uint32)")

        buffer.write(struct.pack(">I", size))
        buffer.write(self.payload)

    def _read_event(self, buffer: io.BytesIO) -> None:
        event_bytes = buffer.read(4)
        if event_bytes:
            event_value = struct.unpack(">i", event_bytes)[0]
            try:
                self.event = EventType(event_value)
            except ValueError:
                self.event = event_value

    def _read_session_id(self, buffer: io.BytesIO) -> None:
        if self.event in [
            EventType.StartConnection,
            EventType.FinishConnection,
            EventType.ConnectionStarted,
            EventType.ConnectionFailed,
            EventType.ConnectionFinished,
        ]:
            return

        size_bytes = buffer.read(4)
        if size_bytes:
            size = struct.unpack(">I", size_bytes)[0]
            if size > 0:
                session_id_bytes = buffer.read(size)
                if len(session_id_bytes) == size:
                    self.session_id = session_id_bytes.decode("utf-8")

    def _read_connect_id(self, buffer: io.BytesIO) -> None:
        if self.event in [
            EventType.ConnectionStarted,
            EventType.ConnectionFailed,
            EventType.ConnectionFinished,
        ]:
            size_bytes = buffer.read(4)
            if size_bytes:
                size = struct.unpack(">I", size_bytes)[0]
                if size > 0:
                    self.connect_id = buffer.read(size).decode("utf-8")

    def _read_sequence(self, buffer: io.BytesIO) -> None:
        sequence_bytes = buffer.read(4)
        if sequence_bytes:
            self.sequence = struct.unpack(">i", sequence_bytes)[0]

    def _read_error_code(self, buffer: io.BytesIO) -> None:
        error_code_bytes = buffer.read(4)
        if error_code_bytes:
            self.error_code = struct.unpack(">I", error_code_bytes)[0]

    def _read_payload(self, buffer: io.BytesIO) -> None:
        size_bytes = buffer.read(4)
        if size_bytes:
            size = struct.unpack(">I", size_bytes)[0]
            if size > 0:
                self.payload = buffer.read(size)


async def receive_message(websocket: websockets.WebSocketClientProtocol) -> Message:
    data = await websocket.recv()
    if isinstance(data, str):
        raise ValueError(f"Unexpected text message: {data}")
    elif isinstance(data, bytes):
        return Message.from_bytes(data)
    else:
        raise ValueError(f"Unexpected message type: {type(data)}")


async def wait_for_event(
    websocket: websockets.WebSocketClientProtocol,
    msg_type: MsgType,
    event_type: EventType,
) -> Message:
    while True:
        msg = await receive_message(websocket)
        if msg.type == MsgType.Error:
            raise RuntimeError(f"Server error: {msg.error_code}, payload: {msg.payload.decode('utf-8', 'ignore')}")
        if msg.type == msg_type and msg.event == event_type:
            return msg


async def start_connection(websocket: websockets.WebSocketClientProtocol) -> None:
    msg = Message(type=MsgType.FullClientRequest, flag=MsgTypeFlagBits.WithEvent)
    msg.event = EventType.StartConnection
    msg.payload = b"{}"
    await websocket.send(msg.marshal())


async def finish_connection(websocket: websockets.WebSocketClientProtocol) -> None:
    msg = Message(type=MsgType.FullClientRequest, flag=MsgTypeFlagBits.WithEvent)
    msg.event = EventType.FinishConnection
    msg.payload = b"{}"
    await websocket.send(msg.marshal())


async def start_session(
    websocket: websockets.WebSocketClientProtocol, payload: bytes, session_id: str
) -> None:
    msg = Message(type=MsgType.FullClientRequest, flag=MsgTypeFlagBits.WithEvent)
    msg.event = EventType.StartSession
    msg.session_id = session_id
    msg.payload = payload
    await websocket.send(msg.marshal())


async def finish_session(
    websocket: websockets.WebSocketClientProtocol, session_id: str
) -> None:
    msg = Message(type=MsgType.FullClientRequest, flag=MsgTypeFlagBits.WithEvent)
    msg.event = EventType.FinishSession
    msg.session_id = session_id
    msg.payload = b"{}"
    await websocket.send(msg.marshal())


async def task_request(
    websocket: websockets.WebSocketClientProtocol, payload: bytes, session_id: str
) -> None:
    msg = Message(type=MsgType.FullClientRequest, flag=MsgTypeFlagBits.WithEvent)
    msg.event = EventType.TaskRequest
    msg.session_id = session_id
    msg.payload = payload
    await websocket.send(msg.marshal())
