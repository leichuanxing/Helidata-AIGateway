"""Bounded incremental SSE framing. Buffer one event, never the whole answer."""
from app.providers.base import ProviderFailure

MAX_EVENT_BYTES = 1024 * 1024


async def events(chunks):
    buffer = bytearray()
    data = []
    event = ''
    size = 0
    first = True

    async def terminated():
        async for chunk in chunks:
            yield chunk
        if buffer.endswith(b'\r'):
            yield b'\n'  # Complete a final lone CR without inventing a data frame.

    async for chunk in terminated():
        # Small slices allow many short events in one large network chunk.
        for start in range(0, len(chunk), 16384):
            buffer.extend(chunk[start:start + 16384])
            while True:
                positions = [p for p in (buffer.find(b'\n'), buffer.find(b'\r')) if p >= 0]
                if not positions:
                    break
                end = min(positions)
                if buffer[end] == 13 and end == len(buffer) - 1:
                    break  # CRLF may be split across two network reads.
                line = bytes(buffer[:end])
                consumed = end + (2 if buffer[end:end + 2] == b'\r\n' else 1)
                del buffer[:consumed]
                if first:
                    line = line.removeprefix(b'\xef\xbb\xbf')
                    first = False
                size += len(line) + consumed - end
                if size > MAX_EVENT_BYTES:
                    raise ProviderFailure('UPSTREAM_EVENT_TOO_LARGE')
                if not line:
                    if data:
                        try:
                            yield event, b'\n'.join(data).decode('utf-8')
                        except UnicodeError:
                            raise ProviderFailure('UPSTREAM_INVALID_RESPONSE') from None
                    data, event, size = [], '', 0
                elif line.startswith(b':'):
                    yield 'heartbeat', ''
                else:
                    field, _, value = line.partition(b':')
                    value = value[1:] if value.startswith(b' ') else value
                    if field == b'data':
                        data.append(value)
                    elif field == b'event':
                        event = value.decode('utf-8', errors='replace')
            if len(buffer) + size > MAX_EVENT_BYTES:
                raise ProviderFailure('UPSTREAM_EVENT_TOO_LARGE')
    # A partial frame at EOF is never presented as a successful completion.
    if buffer or data:
        raise ProviderFailure('UPSTREAM_STREAM_INTERRUPTED')
