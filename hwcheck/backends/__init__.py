"""Бэкенды: источники данных о железе (реальный Windows или фейковый для тестов и демо)."""

from __future__ import annotations

from hwcheck.backends.base import HardwareBackend


def create_backend(demo: str | None = None, time_scale: float = 0.0) -> HardwareBackend:
    """Создаёт бэкенд: фейковый для демо-сценария `demo` или реальный для этого компьютера."""
    if demo:
        from hwcheck.backends.fake import FakeBackend

        return FakeBackend(demo, time_scale=time_scale)
    from hwcheck.backends.windows import WindowsBackend

    return WindowsBackend()
