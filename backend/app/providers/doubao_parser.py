from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from backend.app.collection.models import RelevanceDecision
from backend.app.domain.models import DoubaoEnrichment
from backend.app.domain.normalization import (
    normalize_company_name,
    normalize_email,
    normalize_mobile,
    normalize_telephone,
    normalize_wechat,
)


class DoubaoWebResponseError(ValueError):
    """Raised when visible Doubao output cannot be parsed safely."""


_MOBILE_IN_TEXT = re.compile(r'(?<!\d)1[3-9](?:[\s-]?\d){9}(?!\d)')
_URL = re.compile(r'https?://[^\s｜|,，;；)）]+', re.IGNORECASE)
_GUESS_MARKERS = ('guess', 'guessed', 'infer', 'inferred', 'speculat', '猜测', '推测', '推断', '估计', '可能')


def parse_contact_response(text: str, *, company_name: str) -> DoubaoEnrichment:
    raw = text.strip()
    if not raw:
        raise DoubaoWebResponseError('豆包返回为空')

    payload = _json_payload(raw)
    if payload is None:
        return _parse_natural_language(raw, company_name=company_name)
    if isinstance(payload, list):
        payload = payload[0] if payload else None
    if not isinstance(payload, dict):
        raise DoubaoWebResponseError('豆包 JSON 返回不是对象')

    parsed_name = _clean_value(payload.get('company_name') or payload.get('公司名称'))
    if parsed_name and not _company_names_match(company_name, parsed_name):
        raise DoubaoWebResponseError('豆包返回的公司名与请求不匹配')
    guessed_fields = _guessed_fields(payload)
    urls = _normalize_urls(payload.get('source_urls') or payload.get('source_url'))
    quotes = _clean_list(payload.get('evidence_quotes') or payload.get('evidence_quote'))
    return DoubaoEnrichment(
        company_name=company_name.strip(),
        mobile=normalize_mobile(_safe_field(payload, ('mobile', '手机号'), guessed_fields, 'mobile')),
        telephone=normalize_telephone(_safe_field(payload, ('telephone', '座机', '电话'), guessed_fields, 'telephone')),
        contact_person_name=_clean_optional(_safe_field(payload, ('contact_person_name', '联系人', '联系人姓名'), guessed_fields, 'contact_person_name')),
        contact_person_role=_clean_optional(_safe_field(payload, ('contact_person_role', '职务', '职位'), guessed_fields, 'contact_person_role')),
        email=normalize_email(_safe_field(payload, ('email', '邮箱'), guessed_fields, 'email')),
        wechat=normalize_wechat(_safe_field(payload, ('wechat', '微信', '微信号'), guessed_fields, 'wechat')),
        address=_clean_optional(payload.get('address') or payload.get('地址')),
        service_intro=_clean_optional(payload.get('service_intro') or payload.get('服务简介') or payload.get('服务介绍')),
        source_urls=urls,
        evidence_quotes=quotes,
        contact_evidence_grade=_clean_optional(payload.get('contact_evidence_grade')),
        contact_evidence_score=_int_or_none(payload.get('contact_evidence_score')),
    )


def parse_relevance_response(
    text: str,
    *,
    candidate_id: str,
    model_id: str,
) -> RelevanceDecision:
    payload = _json_payload(text.strip())
    if not isinstance(payload, dict):
        raise DoubaoWebResponseError('相关性判断不是JSON对象')
    status = str(payload.get('status') or '').strip().lower()
    if status not in {'relevant', 'not_relevant', 'review'}:
        raise DoubaoWebResponseError('相关性判断状态无效')
    reason = _clean_value(payload.get('reason')) or '模型未提供判断理由'
    try:
        confidence = float(payload['confidence']) if payload.get('confidence') is not None else None
    except (TypeError, ValueError):
        confidence = None
    if confidence is not None:
        confidence = max(0.0, min(1.0, confidence))
    return RelevanceDecision(
        candidate_id=candidate_id,
        model_id=model_id,
        status=status,
        reason=reason,
        confidence=confidence,
    )


def parse_intent_keyword_response(text: str) -> list[str]:
    payload = _json_payload(text.strip())
    if not isinstance(payload, dict) or not isinstance(payload.get('keywords'), list):
        raise DoubaoWebResponseError('关键词扩展不是JSON对象')
    keywords: list[str] = []
    for value in payload['keywords']:
        keyword = _clean_value(value)
        if keyword and keyword not in keywords:
            keywords.append(keyword)
    return keywords


def _json_payload(raw: str) -> Any | None:
    fenced = re.search(r'```(?:json)?\s*(.*?)```', raw, re.IGNORECASE | re.DOTALL)
    candidate = fenced.group(1).strip() if fenced else raw
    if not candidate.startswith(('{', '[')):
        return None
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise DoubaoWebResponseError('豆包 JSON 返回无法解析') from exc


def _parse_natural_language(raw: str, *, company_name: str) -> DoubaoEnrichment:
    if _company_key(company_name) not in _company_key(raw):
        raise DoubaoWebResponseError('豆包联系方式返回格式无法解析')
    mobile = _extract_mobile(raw)
    if mobile is None:
        raise DoubaoWebResponseError('豆包自然语言回答中没有有效手机号')
    return DoubaoEnrichment(
        company_name=company_name.strip(),
        mobile=mobile,
        contact_person_name=_labeled_value(raw, '联系人', '联系人姓名'),
        contact_person_role=_labeled_value(raw, '职务', '职位'),
        email=normalize_email(_labeled_value(raw, '邮箱', '电子邮箱', 'email')),
        wechat=normalize_wechat(_labeled_value(raw, '微信', '微信号', 'wechat')),
        address=_labeled_value(raw, '公司地址', '地址'),
        service_intro=_labeled_value(raw, '服务简介', '服务介绍', '公司简介', '简介'),
        source_urls=_normalize_urls(raw),
        evidence_quotes=[],
    )


def _guessed_fields(payload: dict[str, Any]) -> set[str]:
    guessed: set[str] = set()
    for key in ('guessed_fields', 'inferred_fields', 'speculative_fields'):
        values = payload.get(key)
        if isinstance(values, list):
            guessed.update(str(value) for value in values)
    if _is_guess_marker(payload.get('guessed')) or _is_guess_marker(payload.get('inferred')):
        guessed.update({'mobile', 'telephone', 'contact_person_name', 'contact_person_role', 'email', 'wechat'})
    return guessed


def _safe_field(
    payload: dict[str, Any],
    keys: tuple[str, ...],
    guessed_fields: set[str],
    canonical_key: str,
) -> object | None:
    if canonical_key in guessed_fields or any(key in guessed_fields for key in keys):
        return None
    for key in keys:
        if key in payload:
            value = payload[key]
            if isinstance(value, dict):
                if _is_guess_marker(value.get('status')) or _is_guess_marker(value.get('evidence_status')):
                    return None
                return value.get('value')
            return value
    return None


def _is_guess_marker(value: object) -> bool:
    text = str(value or '').strip().lower()
    return bool(text) and any(marker in text for marker in _GUESS_MARKERS)


def _extract_mobile(value: object) -> str | None:
    for match in _MOBILE_IN_TEXT.finditer(str(value or '')):
        mobile = normalize_mobile(match.group())
        if mobile:
            return mobile
    return None


def _normalize_urls(value: object) -> list[str]:
    values = value if isinstance(value, list) else _URL.findall(str(value or ''))
    result: list[str] = []
    for item in values:
        parsed = urlparse(str(item).strip())
        if parsed.scheme.lower() not in {'http', 'https'} or not parsed.netloc:
            continue
        query = urlencode(parse_qsl(parsed.query, keep_blank_values=True))
        normalized = urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or '/', '', query, ''))
        if normalized not in result:
            result.append(normalized)
    return result


def _clean_list(value: object) -> list[str]:
    values = value if isinstance(value, list) else [value]
    result: list[str] = []
    for item in values:
        cleaned = _clean_value(item)
        if cleaned and cleaned.lower() not in {'null', '未公开', '未提供来源'} and cleaned not in result:
            result.append(cleaned)
    return result


def _clean_value(value: object) -> str:
    return str(value or '').strip()


def _clean_optional(value: object) -> str | None:
    cleaned = _clean_value(value)
    return cleaned or None


def _labeled_value(text: str, *labels: str) -> str | None:
    label_pattern = '|'.join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    match = re.search(rf'(?:{label_pattern})\s*[：:]\s*([^；;。\n]+)', text, re.IGNORECASE)
    return _clean_optional(match.group(1)) if match else None


def _company_key(value: object) -> str:
    normalized = normalize_company_name(value) or ''
    return re.sub(r'[^0-9A-Za-z\u4e00-\u9fff]+', '', normalized).casefold()


def _company_names_match(requested: str, parsed: str) -> bool:
    requested_key = _company_key(requested)
    parsed_key = _company_key(parsed)
    if not requested_key or not parsed_key:
        return False
    return requested_key == parsed_key or (
        len(parsed_key) >= 4 and (parsed_key in requested_key or requested_key in parsed_key)
    )


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None and str(value).strip() else None
    except (TypeError, ValueError):
        return None
