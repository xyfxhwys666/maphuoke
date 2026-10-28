from __future__ import annotations

from typing import Any

from backend.app.providers.amap_api import AmapApiProvider
from backend.app.providers.amap_web import AmapWebProvider
from backend.app.providers.fake import FakeMapDiscoveryProvider


def build_map_provider(
    provider_id: str,
    *,
    api_key: str | None = None,
    browser: Any | None = None,
    **kwargs: Any,
):
    if provider_id == 'fake_map':
        return FakeMapDiscoveryProvider()
    if provider_id == 'amap_api':
        return AmapApiProvider(api_key=api_key, **kwargs)
    if provider_id == 'amap_web':
        return AmapWebProvider(browser=browser, **kwargs)
    raise ValueError(f'unknown map provider: {provider_id}')
