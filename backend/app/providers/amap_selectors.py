from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from backend.app.domain.models import MapPoiCandidate
from backend.app.domain.normalization import extract_mobile, normalize_telephone

_PHONE_PATTERN = re.compile(
    r'(?<!\d)(?:\+?86[\s-]*)?(?:0\d{2,3}[\s-]?\d{7,8}|400[\s-]?\d{3}[\s-]?\d{4}|1[3-9]\d[\s-]?\d{4}[\s-]?\d{4})(?!\d)'
)
_COORDINATE_PATTERN = re.compile(r'(-?\d{1,3}\.\d+)\s*[,，]\s*(-?\d{1,2}\.\d+)')
_ID_PATTERN = re.compile(r'(?:POI\s*ID|poi_id|id)\s*[:：]?\s*([\w-]+)', re.IGNORECASE)
_PATH_ID_PATTERN = re.compile(r'/(?:place|detail|marker)/([^/?#]+)', re.IGNORECASE)
_PROVINCE_PREFIX_PATTERN = re.compile(r'^[\u4e00-\u9fff]{2,8}?(?:省|自治区)')
_CITY_PATTERN = re.compile(r'([\u4e00-\u9fff]{2,7}?市)')


def _strip_prefix(value: str) -> str:
    return re.sub(r'^\s*(?:地址|详细地址|电话|联系电话|热线|分类|类型|坐标|经纬度|POI\s*ID|poi_id)\s*[:：]?\s*', '', value, flags=re.IGNORECASE).strip()


def _line_value(lines: list[str], prefixes: tuple[str, ...]) -> str | None:
    for line in lines:
        if any(line.lower().startswith(prefix.lower()) for prefix in prefixes):
            value = _strip_prefix(line)
            if value:
                return value
    return None


def _poi_id(source_url: str | None, text: str) -> str | None:
    match = _ID_PATTERN.search(text)
    if match:
        return match.group(1)
    if source_url:
        query = parse_qs(urlparse(source_url).query)
        for key in ('pid', 'poi_id', 'id'):
            if query.get(key):
                return query[key][0]
        path_match = _PATH_ID_PATTERN.search(urlparse(source_url).path)
        if path_match:
            return path_match.group(1)
    return None


def _actual_city(lines: list[str], *, company_name: str, address: str | None) -> str | None:
    evidence_lines = ([address] if address else []) + [
        line for line in lines if company_name not in line
    ]
    for line in evidence_lines:
        cleaned = _PROVINCE_PREFIX_PATTERN.sub('', _strip_prefix(line))
        match = _CITY_PATTERN.search(cleaned)
        if match:
            return match.group(1)
    return None


def parse_result_card_text(
    text: str,
    *,
    city: str,
    source_url: str | None = None,
    company_name_hint: str | None = None,
) -> MapPoiCandidate:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    company_name = company_name_hint or (lines[0] if lines else '未命名 POI')
    address = _line_value(lines, ('地址', '详细地址'))
    actual_city = _actual_city(lines, company_name=company_name, address=address)
    telephone_value = _line_value(lines, ('电话', '联系电话', '热线'))
    phone_text = telephone_value or text
    mobile = extract_mobile(phone_text)
    phone_match = _PHONE_PATTERN.search(phone_text)
    raw_phone = phone_match.group(0) if phone_match else telephone_value
    telephone = None if mobile else normalize_telephone(raw_phone)
    category = _line_value(lines, ('分类', '类型'))
    coordinate_value = _line_value(lines, ('坐标', '经纬度')) or text
    coordinate_match = _COORDINATE_PATTERN.search(coordinate_value)
    longitude = float(coordinate_match.group(1)) if coordinate_match else None
    latitude = float(coordinate_match.group(2)) if coordinate_match else None
    poi_id = _poi_id(source_url, text)
    stable_key = '|'.join((source_url or '', poi_id or '', company_name, address or ''))
    candidate_id = f'amap-web-{hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:16]}'
    captured_at = datetime.now(UTC)
    return MapPoiCandidate(
        candidate_id=candidate_id,
        company_name=company_name,
        city=actual_city or city,
        address=address,
        telephone=telephone,
        mobile=mobile,
        category=category,
        longitude=longitude,
        latitude=latitude,
        poi_id=poi_id,
        source_url=source_url,
        source_urls=[source_url] if source_url else [],
        discovery_channel='amap_web',
        raw_text='\n'.join(lines)[:4000] or None,
        source_metadata={
            'provider': 'amap_web',
            'poi_id': poi_id,
            'map_detail_url': source_url,
            'captured_at': captured_at.isoformat(),
            'requested_city': city,
            'actual_city': actual_city,
        },
        captured_at=captured_at,
    )


def _count(locator: Any) -> int:
    try:
        return int(locator.count())
    except (AttributeError, TypeError):
        return 0


def _safe_locator(factory: Callable[[], Any]) -> Any | None:
    try:
        return factory()
    except Exception:  # noqa: BLE001 - a page may not support one selector API
        return None


def _safe_attribute(locator: Any, name: str) -> str | None:
    try:
        value = locator.get_attribute(name)
    except (AttributeError, TypeError):
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


def find_search_input(page: Any) -> Any:
    role_factories = (
        lambda: page.get_by_role('textbox', name=re.compile('搜索|地点|关键字')),
        lambda: page.get_by_role('textbox'),
    )
    for factory in role_factories:
        locator = _safe_locator(factory)
        if locator is not None and _count(locator):
            return locator.first
    for selector in (
        'input[placeholder*="搜索"]',
        'input[placeholder*="地点"]',
        'input.amap-search',
        '[contenteditable="true"]',
    ):
        locator = _safe_locator(lambda selector=selector: page.locator(selector))
        if locator is not None and _count(locator):
            return locator.first
    raise LookupError('Amap search input was not found')


def find_result_cards(page: Any) -> Any:
    for selector in (
        '.poi-item',
        '.search-list-item',
        '[class*="poi-item"]',
        '[class*="search-list"] > li',
    ):
        locator = _safe_locator(lambda selector=selector: page.locator(selector))
        if locator is not None and _count(locator):
            return locator
    locator = _safe_locator(lambda: page.get_by_role('listitem'))
    if locator is not None and _count(locator):
        return locator
    return None


def find_detail_link(card: Any) -> str | None:
    direct = _safe_attribute(card, 'href')
    if direct:
        return direct
    for selector in ('a[href]', '[data-href]', '[data-url]'):
        locator = _safe_locator(lambda selector=selector: card.locator(selector))
        if locator is None or not _count(locator):
            continue
        first = locator.first
        for attribute in ('href', 'data-href', 'data-url'):
            value = _safe_attribute(first, attribute)
            if value:
                return value
    return None


def merge_detail_candidate(candidate: MapPoiCandidate, detail: MapPoiCandidate) -> MapPoiCandidate:
    update: dict[str, Any] = {}
    for field in ('address', 'category', 'longitude', 'latitude', 'poi_id'):
        if getattr(detail, field) is not None:
            update[field] = getattr(detail, field)
    update['telephone'] = detail.telephone
    update['mobile'] = detail.mobile
    if detail.source_metadata.get('actual_city'):
        update['city'] = detail.city

    source_url = candidate.source_url
    if detail.source_url and detail.source_url != source_url:
        source_url = detail.source_url
    source_urls = list(dict.fromkeys([*candidate.source_urls, *detail.source_urls, source_url]))
    source_urls = [value for value in source_urls if value]
    raw_parts = [value for value in (candidate.raw_text, detail.raw_text) if value]
    metadata = {**candidate.source_metadata, **detail.source_metadata}
    if detail.source_url:
        metadata['map_detail_url'] = detail.source_url
    metadata['detail_verified'] = True
    metadata['detail_raw_text'] = detail.raw_text or ''
    update.update(
        {
            'source_url': source_url,
            'source_urls': source_urls,
            'raw_text': '\n'.join(dict.fromkeys(raw_parts))[:4000] or candidate.raw_text,
            'source_metadata': metadata,
        }
    )
    return candidate.model_copy(update=update)


def _first_card_attribute(card: Any, names: tuple[str, ...]) -> str | None:
    for name in names:
        value = _safe_attribute(card, name)
        if value:
            return value
    return None


def _card_data_text(card: Any, visible_text: str) -> tuple[str, str | None]:
    name = _first_card_attribute(card, ('data-poiinfo-name', 'data-name'))
    address = _first_card_attribute(card, ('data-poiinfo-address', 'data-address'))
    telephone = _first_card_attribute(
        card,
        ('data-poiinfo-tel', 'data-poiinfo-phone', 'data-poiinfo-telephone'),
    )
    category = _first_card_attribute(card, ('data-poiinfo-type', 'data-poiinfo-category'))
    longitude = _first_card_attribute(card, ('data-poiinfo-x', 'data-longitude'))
    latitude = _first_card_attribute(card, ('data-poiinfo-y', 'data-latitude'))
    poi_id = _first_card_attribute(card, ('data-poiinfo-id', 'data-poi-id', 'data-poiinfo-poiid', 'id'))
    attributes = [visible_text]
    if name:
        attributes.insert(0, name)
    if address:
        attributes.append(f'地址：{address}')
    if telephone:
        attributes.append(f'电话：{telephone}')
    if category:
        attributes.append(f'分类：{category}')
    if longitude and latitude:
        attributes.append(f'坐标：{longitude},{latitude}')
    if poi_id:
        attributes.append(f'POI ID：{poi_id}')
    return '\n'.join(value for value in attributes if value), name


def extract_visible_candidate_cards(
    page: Any,
    *,
    city: str,
    company_name: str,
    max_results: int = 5,
) -> list[tuple[MapPoiCandidate, Any]]:
    cards = find_result_cards(page)
    if cards is None:
        return []
    candidates: list[tuple[MapPoiCandidate, Any]] = []
    for index in range(min(_count(cards), max_results)):
        card = cards.nth(index)
        text, company_name_hint = _card_data_text(card, card.inner_text())
        href = find_detail_link(card)
        candidate = parse_result_card_text(
                text,
                city=city,
                source_url=href or getattr(page, 'url', None),
                company_name_hint=company_name_hint,
            )
        candidates.append((candidate, card))
    return candidates


def extract_visible_candidates(
    page: Any,
    *,
    city: str,
    company_name: str,
    max_results: int = 5,
) -> list[MapPoiCandidate]:
    return [
        candidate
        for candidate, _card in extract_visible_candidate_cards(
            page,
            city=city,
            company_name=company_name,
            max_results=max_results,
        )
    ]
