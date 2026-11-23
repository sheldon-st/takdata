import asyncio

from app.enablements.base import EnablementStats, emit_cot


async def test_queues_event_and_counts_it():
    queue: asyncio.Queue = asyncio.Queue(maxsize=2)
    stats = EnablementStats()

    assert await emit_cot(queue, b"a", stats) is True
    assert queue.qsize() == 1
    assert (stats.events_sent, stats.events_dropped) == (1, 0)


async def test_full_queue_drops_oldest_instead_of_blocking():
    queue: asyncio.Queue = asyncio.Queue(maxsize=2)
    stats = EnablementStats()

    for item in (b"1", b"2", b"3"):
        await asyncio.wait_for(emit_cot(queue, item, stats), timeout=1)

    assert [queue.get_nowait(), queue.get_nowait()] == [b"2", b"3"]
    assert (stats.events_sent, stats.events_dropped) == (3, 1)
