from dataclasses import dataclass
from typing import TYPE_CHECKING, final
from urllib.parse import unquote, urlsplit

import anyio.lowlevel
from anyio import BrokenResourceError, EndOfStream, connect_tcp, fail_after
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

if TYPE_CHECKING:
    from anyio.abc import SocketStream


@final
class PostgresHealthProbe:
    _engine: AsyncEngine

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @classmethod
    def from_url(cls, database_url: str) -> PostgresHealthProbe:
        return cls(create_async_engine(database_url, pool_pre_ping=True))

    async def check(self) -> bool:
        try:
            async with self._engine.connect() as connection:
                _ = await connection.execute(text("SELECT 1"))
                return True
        except OSError, SQLAlchemyError:
            return False

    async def close(self) -> None:
        await self._engine.dispose()


@final
@dataclass(frozen=True, slots=True)
class ValkeyHealthProbe:
    host: str
    port: int
    username: str | None
    password: str | None
    database: int

    @classmethod
    def from_url(cls, valkey_url: str) -> ValkeyHealthProbe:
        parsed_url = urlsplit(valkey_url)
        if parsed_url.scheme not in {"redis", "valkey"} or parsed_url.hostname is None:
            msg = "Valkey URL must include a redis or valkey scheme and host"
            raise ValueError(msg)
        database_path = parsed_url.path.removeprefix("/")
        return cls(
            host=parsed_url.hostname,
            port=parsed_url.port or 6379,
            username=unquote(parsed_url.username) if parsed_url.username else None,
            password=unquote(parsed_url.password) if parsed_url.password else None,
            database=int(database_path) if database_path else 0,
        )

    async def check(self) -> bool:
        try:
            with fail_after(2):
                stream = await connect_tcp(self.host, self.port)
                async with stream:
                    if self.password is not None:
                        auth_parts = (
                            ("AUTH", self.username, self.password)
                            if self.username is not None
                            else ("AUTH", self.password)
                        )
                        auth_response = await send_valkey_command(stream, *auth_parts)
                        if not auth_response.startswith(b"+OK"):
                            return False
                    if self.database != 0:
                        select_response = await send_valkey_command(
                            stream,
                            "SELECT",
                            str(self.database),
                        )
                        if not select_response.startswith(b"+OK"):
                            return False
                    response = await send_valkey_command(stream, "PING")
                    return response.startswith(b"+PONG")
        except BrokenResourceError, EndOfStream, OSError, TimeoutError, ValueError:
            return False

    async def close(self) -> None:
        await anyio.lowlevel.checkpoint()


async def send_valkey_command(stream: SocketStream, *parts: str) -> bytes:
    encoded_parts = tuple(part.encode() for part in parts)
    payload = bytearray(f"*{len(encoded_parts)}\r\n".encode())
    for part in encoded_parts:
        payload.extend(f"${len(part)}\r\n".encode())
        payload.extend(part)
        payload.extend(b"\r\n")
    await stream.send(bytes(payload))
    return await stream.receive(512)
