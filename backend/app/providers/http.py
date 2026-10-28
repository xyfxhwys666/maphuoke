from __future__ import annotations

from typing import Any, Protocol


class HttpTransport(Protocol):
    def get(self, url: str, **kwargs: Any): ...
