import asyncio

from app.core import runtime_manager as rm_module
from app.core.runtime_manager import RuntimeManager


class FakeCLITool:
    """Stands in for pytak.CLITool: one long-lived worker future we can kill."""

    def __init__(self) -> None:
        self.tx_queue: asyncio.Queue = asyncio.Queue(maxsize=10)
        self.worker: asyncio.Future = asyncio.get_running_loop().create_future()
        self.running_tasks = {self.worker}


async def test_dead_worker_triggers_reconnect(monkeypatch):
    monkeypatch.setattr(rm_module, "RECONNECT_BACKOFF", (0,))
    tools: list[FakeCLITool] = []
    manager = RuntimeManager()

    async def fake_open(tak_config: dict) -> None:
        tool = FakeCLITool()
        tools.append(tool)
        manager._clitool = tool
        manager._tx_queue = tool.tx_queue
        manager._connected = True
        manager._connect_error = None
        manager._tak_config = tak_config

    monkeypatch.setattr(manager, "_open_connection", fake_open)

    await manager.connect_tak({"cot_url": "tls://tak:8089"})
    assert manager.is_connected and len(tools) == 1

    tools[0].worker.set_exception(ConnectionResetError("peer closed"))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if len(tools) == 2:
            break

    assert len(tools) == 2, "supervisor did not reconnect"
    assert manager.is_connected
    assert manager.tx_queue is tools[1].tx_queue

    await manager.disconnect_tak()
    assert not manager.is_connected


async def test_failure_reason_is_reported(monkeypatch):
    manager = RuntimeManager()
    loop = asyncio.get_running_loop()
    failed = loop.create_future()
    failed.set_exception(OSError("tlsv1 alert"))

    assert "OSError: tlsv1 alert" in manager._describe_failure({failed})
