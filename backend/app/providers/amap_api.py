from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock
from typing import Any
from urllib.parse import urlencode

import httpx
from backend.app.domain.models import MapPoiCandidate
from backend.app.domain.normalization import normalize_mobile, normalize_telephone
from backend.app.providers.map_evidence import attach_map_snapshot


class AmapApiProviderError(RuntimeError):
    pass


def _text(value: object) -> str:
    if isinstance(value, list):
        return ';'.join(str(item).strip() for item in value if str(item).strip())
    return str(value or '').strip()


class AmapApiProvider:
    id = 'amap_api'
    label = '高德 Place Text API'

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str = 'https://restapi.amap.com',
        max_pages: int = 3,
        request_interval_seconds: float = 0.3,
        retry_limit: int = 3,
        client: Any | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        page_size: int = 25,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.max_pages = max_pages
        self.request_interval_seconds = request_interval_seconds
        self.retry_limit = retry_limit
        self.client = client or httpx.Client(timeout=30, follow_redirects=True)
        self.sleep_fn = sleep_fn
        self.page_size = page_size
        self._request_lock = Lock()
        self._last_request_at = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def search_company(self, *, company_name: str, city: str, max_results: int = 5) -> list[MapPoiCandidate]:
        if not self.api_key:
            raise AmapApiProviderError('amap api is not configured')
        candidates: list[MapPoiCandidate] = []
        seen: set[str] = set()
        for page in range(1, self.max_pages + 1):
            payload = self._request({
                'keywords': company_name,
                'city': city,
                'citylimit': 'true',
                'extensions': 'all',
                'offset': self.page_size,
                'page': page,
            })
            pois = payload.get('pois') or []
            for poi in pois:
                if not isinstance(poi, dict):
                    continue
                candidate = self.candidate_from_poi(poi, city=city)
                if not candidate.company_name or not candidate.address:
                    continue
                identity = candidate.poi_id or candidate.candidate_id
                if identity in seen:
                    continue
                seen.add(identity)
                candidates.append(candidate)
                if len(candidates) >= max_results:
                    return candidates
            total = self._int_or_zero(payload.get('count'))
            if not pois or page * self.page_size >= total:
                break
        return candidates

    def _request(self, params: dict[str, object]) -> dict[str, Any]:
        request_params = {**params, 'key': self.api_key}
        for attempt in range(self.retry_limit + 1):
            try:
                with self._request_lock:
                    wait_seconds = self.request_interval_seconds - (time.monotonic() - self._last_request_at)
                    if wait_seconds > 0:
                        self.sleep_fn(wait_seconds)
                    response = self.client.get(f'{self.base_url}/v3/place/text', params=request_params)
                    self._last_request_at = time.monotonic()
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                if attempt < self.retry_limit:
                    self.sleep_fn(max(self.request_interval_seconds, 0.5 * (attempt + 1)))
                    continue
                raise AmapApiProviderError('amap request failed') from exc
            if payload.get('status') == '1':
                return payload
            info = str(payload.get('info') or payload.get('infocode') or 'unknown error')
            retryable = any(marker in info.upper() for marker in ('LIMIT', 'QPS', 'OVER_LIMIT', 'TIMEOUT'))
            if retryable and attempt < self.retry_limit:
                self.sleep_fn(max(self.request_interval_seconds, 0.5 * (attempt + 1)))
                continue
            raise AmapApiProviderError(f'amap error: {info}')
        raise AmapApiProviderError('amap retry limit exhausted')

    def candidate_from_poi(self, poi: dict[str, Any], *, city: str) -> MapPoiCandidate:
        name = _text(poi.get('name'))
        address = _text(poi.get('address')) or None
        telephone_value = _text(poi.get('tel'))
        mobile = self._extract_mobile(telephone_value)
        telephone = None if mobile else normalize_telephone(telephone_value)
        location = _text(poi.get('location'))
        longitude, latitude = self._coordinates(location)
        poi_id = _text(poi.get('id')) or None
        marker_params = {
            'position': location,
            'name': name,
            'src': 'map-lead-platform',
            'coordinate': 'gaode',
            'callnative': '0',
        }
        source_url = 'https://uri.amap.com/marker?' + urlencode(marker_params)
        raw_text = '\n'.join(value for value in (name, address or '', telephone_value, _text(poi.get('type'))) if value)
        stable_key = '|'.join((poi_id or '', name, address or '', location))
        candidate_id = f'amap-api-{hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:16]}'
        captured_at = datetime.now(UTC)
        return attach_map_snapshot(MapPoiCandidate(
            candidate_id=candidate_id,
            company_name=name,
            city=city.strip(),
            address=address,
            telephone=telephone,
            mobile=mobile,
            category=_text(poi.get('type')) or None,
            longitude=longitude,
            latitude=latitude,
            poi_id=poi_id,
            source_url=source_url,
            source_urls=[source_url],
            discovery_channel=self.id,
            raw_text=raw_text or None,
            source_metadata={'provider': self.id, 'poi_id': poi_id, 'raw_poi': poi},
            captured_at=captured_at,
        ))

    @staticmethod
    def _extract_mobile(value: str) -> str | None:
        digits = ''.join(char for char in value if char.isdigit())
        for index in range(max(0, len(digits) - 10)):
            mobile = normalize_mobile(digits[index:index + 11])
            if mobile:
                return mobile
        return normalize_mobile(digits)

    @staticmethod
    def _coordinates(value: str) -> tuple[float | None, float | None]:
        try:
            longitude, latitude = value.split(',', 1)
            return float(longitude), float(latitude)
        except (ValueError, TypeError):
            return None, None

    @staticmethod
    def _int_or_zero(value: object) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
