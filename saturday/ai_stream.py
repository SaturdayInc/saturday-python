"""Single-attempt, context-managed AI event streams."""

from __future__ import annotations

import asyncio
import codecs
import json
import math
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, AsyncIterator, Awaitable, Dict, Iterator, List, Optional, TypedDict

import httpx

from saturday.errors import RateLimitError, SaturdayError


class _AIStreamEventRequired(TypedDict):
    event: str
    data: Any
    raw_data: str


class AIStreamEvent(_AIStreamEventRequired, total=False):
    """`id` is present only when the event's block carried an SSE `id:` line; not a reconnect buffer. The server sends none today."""

    id: str


class AIStreamError(SaturdayError):
    def __init__(self, code: str, message: str, event: Optional[AIStreamEvent] = None):
        super().__init__(message=message, code=code)
        self.event = event


class _EventParser:
    def __init__(self) -> None:
        self.line = ""
        self.skip_lf = False
        self.name = ""
        self.data: List[str] = []
        self.event_id: Optional[str] = None

    def push(self, text: str) -> Iterator[AIStreamEvent]:
        for char in text:
            if self.skip_lf:
                self.skip_lf = False
                if char == "\n":
                    continue
            if char not in ("\r", "\n"):
                self.line += char
                continue
            self.skip_lf = char == "\r"
            line, self.line = self.line, ""
            if not line:
                # An id line belongs to the event dispatched by its own block, never to later events.
                name, data, event_id = self.name, self.data, self.event_id
                self.name, self.data, self.event_id = "", [], None
                if data:
                    raw = "\n".join(data)
                    event: AIStreamEvent = {"event": name or "message", "data": None, "raw_data": raw}
                    if event_id is not None:
                        event["id"] = event_id
                    try:
                        event["data"] = json.loads(raw, parse_constant=self.invalid_constant)
                    except ValueError as exc:
                        raise AIStreamError("malformed_stream", "AI event contains invalid JSON. The request was not replayed.", event) from exc
                    yield event
                continue
            if line.startswith(":"):
                continue
            field, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
            if field == "event":
                self.name = value
            elif field == "data":
                self.data.append(value)
            elif field == "id" and "\0" not in value:
                self.event_id = value
            # SSE retry fields do not authorize another inference request.

    @staticmethod
    def invalid_constant(value: str) -> None:
        raise ValueError("Non-JSON constant: " + value)

    def finish(self) -> None:
        if self.data or self.name or (self.line and not self.line.startswith(":")):
            raise AIStreamError("incomplete_stream", "AI stream ended inside an event. The request was not replayed.")


def _line_bytes(data: bytes) -> Iterator[bytes]:
    start = 0
    for index, value in enumerate(data):
        if value in (10, 13):
            yield data[start:index + 1]
            start = index + 1
    if start < len(data):
        yield data[start:]


@asynccontextmanager
async def stream_ai(
    base_url: str,
    headers: Dict[str, str],
    path: str,
    body: Dict[str, Any],
    timeout: float,
) -> AsyncIterator[AsyncIterator[AIStreamEvent]]:
    """A total deadline covers acquisition, headers and body; never retries POST."""
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("AI stream timeout must be a positive finite number.")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    def check_deadline() -> float:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise AIStreamError("timeout", "AI stream deadline exceeded. The request may have been accepted; it was not replayed.")
        return remaining

    async def within(operation):
        remaining = check_deadline()
        try:
            return await asyncio.wait_for(operation(), remaining)
        except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
            raise AIStreamError("timeout", "AI stream deadline exceeded. The request may have been accepted; it was not replayed.") from exc
        except httpx.HTTPError as exc:
            check_deadline()
            raise AIStreamError("connection_error", "AI stream connection failed. The request may have been accepted; it was not replayed.") from exc

    stream_headers = httpx.Headers(headers)
    stream_headers["Accept"] = "text/event-stream"
    client = httpx.AsyncClient(base_url=base_url, headers=stream_headers, timeout=timeout, follow_redirects=False)
    response = None
    expiration = None
    events = None
    try:
        request = client.build_request("POST", path, json=body)
        response = await within(lambda: client.send(request, stream=True))
        if response.is_redirect:
            raise AIStreamError("redirect", "AI request was redirected. It was not forwarded or replayed.")
        if not response.is_success:
            await within(response.aread)
            try:
                detail = response.json()
                detail = detail.get("error", detail) if isinstance(detail, dict) else None
            except ValueError:
                detail = None
            if not isinstance(detail, dict) or not isinstance(detail.get("message"), str):
                detail = {"code": "unknown", "message": "AI request failed without a structured error message."}
            error = SaturdayError.from_response(response.status_code, detail)
            if isinstance(error, RateLimitError):
                try:
                    error.retry_after = max(0, int(response.headers.get("Retry-After", "60")))
                except ValueError:
                    pass
            raise error
        if response.headers.get("Content-Type", "").split(";")[0].strip().lower() != "text/event-stream":
            raise AIStreamError("invalid_stream_response", "Expected an AI text/event-stream response. The request was not replayed.")

        async def expire() -> None:
            await asyncio.sleep(max(0, deadline - loop.time()))
            await response.aclose()

        expiration = asyncio.create_task(expire())

        async def read_events() -> AsyncGenerator[AIStreamEvent, None]:
            decoder = codecs.getincrementaldecoder("utf-8-sig")("strict")
            parser = _EventParser()
            chunks = response.aiter_bytes().__aiter__()
            ended = False
            conversation_id = None
            server_error = None
            while True:
                done = False
                try:
                    chunk = await within(chunks.__anext__)
                except StopAsyncIteration:
                    chunk, done = b"", True
                # Later corrupt bytes must not erase prior complete events.
                for part in [b""] if done else _line_bytes(chunk):
                    try:
                        text = decoder.decode(part, final=done)
                    except UnicodeError as exc:
                        raise AIStreamError("malformed_stream", "AI stream contains invalid or incomplete UTF-8. The request was not replayed.") from exc
                    for event in parser.push(text):
                        check_deadline()
                        if event["event"] in ("message_start", "message_end"):
                            event_id = event["data"].get("conversation_id") if isinstance(event["data"], dict) else None
                            if (not isinstance(event_id, str) or not event_id
                                    or (event["event"] == "message_start" and conversation_id is not None)
                                    or (event["event"] == "message_end" and (ended or event_id != conversation_id))):
                                raise AIStreamError("malformed_stream", "AI stream has an invalid conversation boundary. The request was not replayed.", event)
                            if event["event"] == "message_start":
                                conversation_id = event_id
                        if event["event"] == "error":
                            server_error = event
                        if event["event"] == "message_end":
                            ended = True
                        yield event
                if done:
                    break
            check_deadline()
            if server_error:
                raise AIStreamError("stream_error", "The AI server reported an error. Inspect the preserved event; the request was not replayed.", server_error)
            parser.finish()
            if not ended:
                raise AIStreamError("incomplete_stream", "AI stream ended without message_end. The request was not replayed.")

        events = read_events()
        yield events
    finally:
        primary_error = sys.exc_info()[1]
        cleanup_error: Optional[BaseException] = None

        async def finish(operation: Awaitable[None]) -> None:
            nonlocal cleanup_error
            try:
                await operation
            except BaseException as exc:
                if cleanup_error is None:
                    cleanup_error = exc

        if expiration is not None:
            expiration.cancel()

            async def collect_expiration() -> None:
                result = (await asyncio.gather(expiration, return_exceptions=True))[0]
                if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                    raise result

            await finish(collect_expiration())
        if events is not None:
            await finish(events.aclose())
        if response is not None:
            await finish(response.aclose())
        await finish(client.aclose())
        if primary_error is None and cleanup_error is not None:
            if isinstance(cleanup_error, httpx.HTTPError):
                raise AIStreamError("connection_error", "AI stream cleanup failed. The request was not replayed.") from cleanup_error
            raise cleanup_error
