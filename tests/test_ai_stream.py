import asyncio
import json
import re
import time
from pathlib import Path

import httpx
import pytest

from saturday import Saturday, SaturdayError


def frame(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


START = frame("message_start", {"conversation_id": "conv-1"})
END = frame("message_end", {"conversation_id": "conv-1"})


class Chunks(httpx.AsyncByteStream):
    def __init__(self, data, split=4096, stall=False):
        self.data = data
        self.split = split
        self.stall = stall
        self.closed = False

    async def __aiter__(self):
        for offset in range(0, len(self.data), self.split):
            yield self.data[offset:offset + self.split]
        if self.stall:
            await asyncio.Future()

    async def aclose(self):
        self.closed = True


def install(monkeypatch, data, split=4096, status=200, content_type="text/event-stream", stall=False):
    chunks = Chunks(data, split, stall)
    requests = []
    async def respond(request):
        requests.append(request)
        return httpx.Response(status, headers={"Content-Type": content_type, "Retry-After": "17"}, stream=chunks)
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(respond)))
    return requests, chunks


async def collect(context):
    async with context as stream:
        return [event async for event in stream]


def test_id_is_per_event(monkeypatch):
    data = START + "id: 7\n" + frame("text_delta", {"delta": "a"}) + frame("text_delta", {"delta": "b"}) + END
    requests, chunks = install(monkeypatch, data.encode())
    with Saturday(api_key="placeholder") as client:
        events = asyncio.run(collect(client.ai.send_message_stream("conv", "hello")))
    assert [event.get("id") for event in events] == [None, "7", None, None]
    assert len(requests) == 1 and chunks.closed


def test_stream_deadline_defaults_to_60s_unless_configured(monkeypatch):
    timeouts = []
    original = httpx.AsyncClient

    async def respond(request):
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=Chunks((START + END).encode()))

    def record(**kwargs):
        timeouts.append(kwargs["timeout"])
        return original(**kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(httpx, "AsyncClient", record)
    with Saturday(api_key="placeholder") as client:
        asyncio.run(collect(client.ai.create_conversation_stream("athlete", "hello")))
    with Saturday(api_key="placeholder", timeout=5.0) as client:
        asyncio.run(collect(client.ai.send_message_stream("conv", "hello")))
        asyncio.run(collect(client.ai.send_message_stream("conv", "hello", timeout=12.5)))
    assert timeouts == [60.0, 5.0, 12.5]


@pytest.mark.parametrize("method", ["create_conversation", "send_message"])
def test_legacy_rejects_without_request(method):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, text=START + END)
    with Saturday(api_key="placeholder") as client:
        client._client.close()
        client._client = httpx.Client(transport=httpx.MockTransport(respond), base_url="https://example.invalid")
        with pytest.raises(SaturdayError) as error:
            getattr(client.ai, method)("athlete", "hello")
        assert error.value.code == "streaming_required"
        assert requests == []


@pytest.mark.parametrize("split", [1, 2, 7, 4096])
def test_utf8_and_all_events(monkeypatch, split):
    kinds = ["text_delta", "safety_warning", "tool_call", "tool_result", "action", "replay", "future_event"]
    data = "\ufeff: heartbeat\r\n\r\n" + START + "".join(frame(kind, {"value": "é🚲日本語"}) for kind in kinds) + END
    requests, chunks = install(monkeypatch, data.encode(), split)
    with Saturday(api_key="placeholder") as client:
        events = asyncio.run(collect(client.ai.create_conversation_stream("athlete", "hello")))
    assert [event["event"] for event in events] == ["message_start"] + kinds + ["message_end"]
    assert events[1]["data"] == {"value": "é🚲日本語"}
    assert json.loads(events[1]["raw_data"]) == events[1]["data"]
    assert json.loads(requests[0].content) == {"athlete_id": "athlete", "message": "hello"}
    assert requests[0].headers["Accept"] == "text/event-stream"
    assert len(requests) == 1
    assert chunks.closed


@pytest.mark.parametrize("newline", ["\n", "\r", "\r\n"])
def test_multiline_and_framing(monkeypatch, newline):
    block = newline.join(["id: abc", "retry: 500", "event: future", 'data: {"one": 1,', 'data: "two": 2}', "", ""])
    requests, chunks = install(monkeypatch, (START + block + END).encode(), 1)
    with Saturday(api_key="placeholder") as client:
        events = asyncio.run(collect(client.ai.send_message_stream("a/b", "hello")))
    assert events[1]["data"] == {"one": 1, "two": 2}
    assert events[1]["id"] == "abc"
    assert requests[0].url.raw_path.endswith(b"/a%2Fb/messages")
    assert chunks.closed


@pytest.mark.parametrize("data,code", [
    ((START + "event: text_delta\ndata: {bad}\n\n").encode(), "malformed_stream"),
    ((START + frame("text_delta", {"delta": "partial"})).encode(), "incomplete_stream"),
    ((START + END[:-1]).encode(), "incomplete_stream"),
    (b"", "incomplete_stream"),
    (START.encode() + b"\xf0\x9f", "malformed_stream"),
    ((START + 'data: {"delta":NaN}\n\n').encode(), "malformed_stream"),
    (END.encode(), "malformed_stream"),
    ((START + frame("message_end", {"conversation_id": "other"})).encode(), "malformed_stream"),
    ((START + START + END).encode(), "malformed_stream"),
    ((START + END + END).encode(), "malformed_stream"),
    ((START + END + frame("message_start", {"conversation_id": "two"}) + frame("text_delta", {"delta": "partial"})).encode(), "malformed_stream"),
])
def test_malformed_and_eof_never_replay(monkeypatch, data, code):
    requests, chunks = install(monkeypatch, data)
    with Saturday(api_key="placeholder", max_retries=3) as client:
        with pytest.raises(SaturdayError) as error:
            asyncio.run(collect(client.ai.send_message_stream("conv", "hello")))
    assert error.value.code == code
    assert len(requests) == 1
    assert chunks.closed


@pytest.mark.parametrize("finish", [True, False])
def test_errors_are_preserved_and_never_success(monkeypatch, finish):
    data = START + frame("error", {"message": "failed", "future": 1}) + frame("safety_warning", {"message": "warning"}) + (END if finish else "")
    requests, chunks = install(monkeypatch, data.encode())
    seen = []
    with Saturday(api_key="placeholder") as client:
        async def read():
            async with client.ai.send_message_stream("conv", "hello") as events:
                async for event in events:
                    seen.append(event)
        with pytest.raises(SaturdayError) as error:
            asyncio.run(read())
    assert error.value.code == "stream_error"
    assert error.value.event["data"] == {"message": "failed", "future": 1}
    assert "safety_warning" in [event["event"] for event in seen]
    assert len(requests) == 1 and chunks.closed


def test_events_after_message_end_are_preserved(monkeypatch):
    data = START + END + frame("safety_warning", {"message": "Keep visible"}) + frame("future_event", {"flag": True}) + frame("error", {"message": "late failure"})
    requests, chunks = install(monkeypatch, data.encode())
    seen = []
    with Saturday(api_key="placeholder") as client:
        async def run():
            async with client.ai.send_message_stream("conv", "hello") as events:
                async for event in events:
                    seen.append(event["event"])
        with pytest.raises(SaturdayError) as error:
            asyncio.run(run())
    assert error.value.code == "stream_error"
    assert seen == ["message_start", "message_end", "safety_warning", "future_event", "error"]
    assert len(requests) == 1 and chunks.closed


@pytest.mark.parametrize("status", [400, 401, 429, 503])
def test_http_errors_do_not_replay(monkeypatch, status):
    requests, chunks = install(monkeypatch, b'{"error":{"message":"No","code":"denied"}}', status=status, content_type="application/json")
    with Saturday(api_key="placeholder", max_retries=3) as client:
        with pytest.raises(SaturdayError) as error:
            asyncio.run(collect(client.ai.send_message_stream("conv", "hello")))
    assert error.value.status == status and error.value.code == "denied"
    if status == 429:
        assert error.value.retry_after == 17
    assert len(requests) == 1 and chunks.closed


def test_cancellation_and_break_close(monkeypatch):
    requests, chunks = install(monkeypatch, START.encode(), stall=True)
    with Saturday(api_key="placeholder") as client:
        async def run():
            async with client.ai.send_message_stream("conv", "hello") as events:
                assert (await events.__anext__())["event"] == "message_start"
                pending = asyncio.create_task(events.__anext__())
                await asyncio.sleep(0)
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
        asyncio.run(run())
    assert len(requests) == 1 and chunks.closed


def test_consumer_break_closes_without_pending_read(monkeypatch):
    requests, chunks = install(monkeypatch, START.encode(), stall=True)
    with Saturday(api_key="placeholder") as client:
        async def run():
            async with client.ai.send_message_stream("conv", "hello") as events:
                async for event in events:
                    assert event["event"] == "message_start"
                    break
        asyncio.run(run())
    assert len(requests) == 1 and chunks.closed


@pytest.mark.parametrize("error", [ValueError("caller failure"), httpx.ReadError("caller HTTP failure"), asyncio.CancelledError()])
def test_cleanup_failure_preserves_caller_error(monkeypatch, error):
    requests, chunks = install(monkeypatch, START.encode(), stall=True)
    async def broken_close():
        chunks.closed = True
        raise httpx.ReadError("cleanup failure")
    chunks.aclose = broken_close
    with Saturday(api_key="placeholder") as client:
        async def run():
            with pytest.raises(type(error)) as caught:
                async with client.ai.send_message_stream("conv", "hello") as events:
                    await events.__anext__()
                    raise error
            assert caught.value is error
        asyncio.run(run())
    assert len(requests) == 1 and chunks.closed


def test_external_cancellation_during_cleanup_propagates(monkeypatch):
    requests, chunks = install(monkeypatch, START.encode(), stall=True)
    with Saturday(api_key="placeholder") as client:
        async def run():
            async with client.ai.send_message_stream("conv", "hello") as events:
                await events.__anext__()
                asyncio.get_running_loop().call_soon(asyncio.current_task().cancel)
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(run())
    assert len(requests) == 1 and chunks.closed


@pytest.mark.parametrize("data", [b"null", b'"failure"', b"{not JSON}"])
def test_malformed_http_error_body(monkeypatch, data):
    requests, chunks = install(monkeypatch, data, status=503)
    with Saturday(api_key="placeholder") as client:
        with pytest.raises(SaturdayError) as error:
            asyncio.run(collect(client.ai.send_message_stream("conv", "hello")))
    assert error.value.status == 503 and error.value.code == "unknown"
    assert len(requests) == 1 and chunks.closed


def test_successful_json_is_not_a_stream(monkeypatch):
    requests, chunks = install(monkeypatch, b'{"text":"not SSE"}', content_type="application/json")
    with Saturday(api_key="placeholder") as client:
        with pytest.raises(SaturdayError) as error:
            asyncio.run(collect(client.ai.send_message_stream("conv", "hello")))
    assert error.value.code == "invalid_stream_response"
    assert len(requests) == 1 and chunks.closed


def test_warning_before_malformed_frame(monkeypatch):
    requests, chunks = install(monkeypatch, (START + frame("safety_warning", {"message": "Keep visible"}) + "data: invalid\n\n").encode())
    seen = []
    with Saturday(api_key="placeholder") as client:
        async def run():
            async with client.ai.send_message_stream("conv", "hello") as events:
                async for event in events:
                    seen.append(event["event"])
        with pytest.raises(SaturdayError):
            asyncio.run(run())
    assert seen == ["message_start", "safety_warning"]
    assert chunks.closed


def test_warning_before_invalid_utf8_same_chunk(monkeypatch):
    requests, chunks = install(monkeypatch, (START + frame("safety_warning", {"message": "Keep visible"})).encode() + b"\xff")
    seen = []
    with Saturday(api_key="placeholder") as client:
        async def run():
            async with client.ai.send_message_stream("conv", "hello") as events:
                async for event in events:
                    seen.append(event["event"])
        with pytest.raises(SaturdayError) as error:
            asyncio.run(run())
        assert error.value.code == "malformed_stream"
    assert seen == ["message_start", "safety_warning"]
    assert len(requests) == 1 and chunks.closed


def test_deadline_during_consumer_pause(monkeypatch):
    requests, chunks = install(monkeypatch, (START + END).encode())
    with Saturday(api_key="placeholder") as client:
        async def run():
            async with client.ai.send_message_stream("conv", "hello", timeout=0.01) as events:
                await events.__anext__()
                await asyncio.sleep(0.03)
                assert chunks.closed
                with pytest.raises(SaturdayError) as error:
                    await events.__anext__()
                assert error.value.code == "timeout"
        asyncio.run(run())
    assert len(requests) == 1


def test_deadline_during_synchronous_consumer_pause(monkeypatch):
    requests, chunks = install(monkeypatch, (START + END).encode())
    with Saturday(api_key="placeholder") as client:
        async def run():
            async with client.ai.send_message_stream("conv", "hello", timeout=0.02) as events:
                await events.__anext__()
                until = time.monotonic() + 0.06
                while time.monotonic() < until:
                    pass
                with pytest.raises(SaturdayError) as error:
                    await events.__anext__()
                assert error.value.code == "timeout"
        asyncio.run(run())
    assert len(requests) == 1 and chunks.closed


def test_exact_ai_readme_example(monkeypatch, capsys):
    requests, chunks = install(monkeypatch, (START + frame("safety_warning", {"message": "Keep visible"}) + frame("future_event", {"nested": 1}) + END).encode())
    section = Path(__file__).parents[1].joinpath("README.md").read_text().split("## AI writes")[1]
    code = re.search(r"```python\n(.*?)```", section, re.S).group(1)
    exec(compile(code, "README.md AI streaming", "exec"), {})
    output = capsys.readouterr().out
    assert "safety_warning" in output and "future_event" in output
    assert len(requests) == 1 and chunks.closed


@pytest.mark.parametrize("mode", ["headers", "body", "error", "trickle", "redirect307", "redirect308", "disconnect"])
def test_native_deadlines_failures_and_cleanup(mode):
    async def run():
        requests = []
        tasks = set()
        async def handler(reader, writer):
            tasks.add(asyncio.current_task())
            try:
                header = await reader.readuntil(b"\r\n\r\n")
                requests.append(header)
                length = next(int(line.split(b":", 1)[1]) for line in header.split(b"\r\n") if line.lower().startswith(b"content-length:"))
                await reader.readexactly(length)
                if mode.startswith("redirect"):
                    writer.write(f"HTTP/1.1 {mode[8:]} Redirect\r\nLocation: /target\r\nContent-Length: 0\r\n\r\n".encode())
                    await writer.drain()
                    return
                if mode == "headers":
                    await reader.read()
                    return
                status = "503 Unavailable" if mode == "error" else "200 OK"
                content_type = "application/json" if mode == "error" else "text/event-stream"
                writer.write(f"HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nTransfer-Encoding: chunked\r\n\r\n".encode())
                payload = b'{"error":' if mode == "error" else START.encode()
                writer.write(f"{len(payload):x}\r\n".encode() + payload + b"\r\n")
                await writer.drain()
                if mode == "disconnect":
                    return
                if mode == "trickle":
                    while True:
                        await asyncio.sleep(0.01)
                        writer.write(b"3\r\n:\n\n\r\n")
                        await writer.drain()
                else:
                    await reader.read()
            except (ConnectionError, asyncio.CancelledError):
                pass
            finally:
                writer.close()
                tasks.discard(asyncio.current_task())
        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            with Saturday(api_key="placeholder", base_url=f"http://127.0.0.1:{port}", timeout=0.15) as client:
                with pytest.raises(SaturdayError) as error:
                    await asyncio.wait_for(collect(client.ai.send_message_stream("conv", "hello")), 2)
                expected = "redirect" if mode.startswith("redirect") else "connection_error" if mode == "disconnect" else "timeout"
                assert error.value.code == expected
            assert len(requests) == 1
            assert b" /target " not in requests[0]
        finally:
            server.close()
            await server.wait_closed()
            remaining = list(tasks)
            for task in remaining:
                task.cancel()
            await asyncio.gather(*remaining, return_exceptions=True)
    asyncio.run(run())
