import hashlib
import json
from datetime import date, datetime
from typing import Any

from backend.app.domain.models import LeadRecord
from backend.app.domain.normalization import (
    normalize_company_name,
    normalize_email,
    normalize_mobile,
    normalize_wechat,
)


def _normalized_city(value: object) -> str:
    return ''.join(str(value or '').split()).casefold()


def company_identity(city: object, company_name: object) -> str:
    normalized_name = normalize_company_name(company_name) or ''
    return f'{_normalized_city(city)}:{normalized_name.casefold()}'


def contact_identity(lead: LeadRecord) -> set[str]:
    identities: set[str] = set()
    mobile = normalize_mobile(lead.mobile)
    email = normalize_email(lead.email)
    wechat = normalize_wechat(lead.wechat)
    if mobile:
        identities.add(f'mobile:{mobile}')
    if email:
        identities.add(f'email:{email}')
    if wechat:
        identities.add(f'wechat:{wechat.casefold()}')
    return identities


def _stable_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _stable_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key).casefold() not in {'captured_at', 'last_updated_at'}
        }
    if isinstance(value, (list, tuple)):
        return [_stable_value(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def payload_fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(_stable_value(payload), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()
