import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

_subscribers: set[asyncio.Queue] = set()
_lock = asyncio.Lock()


async def publish(event_type: str, data: dict[str, Any]) -> None:
    event = {
        "type": event_type,
        "data": data,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    async with _lock:
        dead: list[asyncio.Queue] = []
        for queue in _subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(queue)
        for queue in dead:
            _subscribers.discard(queue)


async def subscribe() -> AsyncGenerator[str, None]:
    queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    async with _lock:
        _subscribers.add(queue)
    try:
        yield f"data: {json.dumps({'type': 'connected', 'data': {}, 'timestamp': datetime.now(UTC).isoformat()})}\n\n"
        while True:
            event = await queue.get()
            yield f"data: {json.dumps(event, default=str)}\n\n"
    finally:
        async with _lock:
            _subscribers.discard(queue)
