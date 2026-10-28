from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx
from backend.app.domain.dedup import company_identity, payload_fingerprint
from backend.app.domain.models import DeliveryResult, LeadRecord
from backend.app.domain.task_state import SearchTask


class ErpHttpAdapter:
    def __init__(
        self,
        *,
        target_url: str | None,
        bearer_token: str | None = None,
        timeout_seconds: float = 30.0,
        client: Any | None = None,
        source_account_name: str = '高德地图',
        source_channel: str = '高德地图',
    ) -> None:
        self.target_url = target_url
        self.bearer_token = bearer_token
        self.client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=True)
        self.source_account_name = source_account_name
        self.source_channel = source_channel

    @property
    def configured(self) -> bool:
        return bool(self.target_url)

    @staticmethod
    def _captured_at(lead: LeadRecord) -> str:
        captured_at = str(lead.source_metadata.get('captured_at') or '').strip()
        value = captured_at or datetime.now(UTC).isoformat()
        try:
            return datetime.fromisoformat(value).strftime(
                '%Y-%m-%d %H:%M:%S'
            )
        except ValueError:
            return value

    @staticmethod
    def _contact_type(lead: LeadRecord) -> str:
        labels = [
            label
            for value, label in (
                (lead.mobile, '手机号'),
                (lead.email, '邮箱'),
                (lead.wechat, '微信号'),
            )
            if value
        ]
        return '、'.join(labels) or '其他联系方式'

    @staticmethod
    def _other_contact(lead: LeadRecord) -> str:
        parts: list[str] = []
        if lead.telephone:
            parts.append(f'座机：{lead.telephone}')
        if lead.address:
            parts.append(f'地址：{lead.address}')
        if lead.source_url:
            parts.append(f'来源：{lead.source_url}')
        poi_id = str(lead.source_metadata.get('amap_poi_id') or '').strip()
        if poi_id:
            parts.append(f'高德 POI：{poi_id}')
        return '；'.join(parts)

    def build_payload(self, task: SearchTask, lead: LeadRecord) -> dict[str, Any]:
        account_guid = str(uuid5(NAMESPACE_URL, f'map-lead:{company_identity(lead.city, lead.company_name)}'))
        contact_info = {
            'contactInfoType': self._contact_type(lead),
            **({'mobilePhone': lead.mobile} if lead.mobile else {}),
            **({'email': lead.email} if lead.email else {}),
            **({'wechatId': lead.wechat} if lead.wechat else {}),
        }
        if other_contact := self._other_contact(lead):
            contact_info['otherContact'] = other_contact
        poi_id = str(lead.source_metadata.get('amap_poi_id') or '').strip()
        payload = {
            'sourceAccountName': self.source_account_name,
            'customerAccountGuid': account_guid,
            'customerSourceChannel': self.source_channel,
            'customerCapturedAt': self._captured_at(lead),
            'customerAccountName': lead.company_name,
            'customerProfileBio': lead.service_intro or '',
            'customerIpRegion': lead.city,
            'customerType': 'B端客资',
            'cEndCustomerRequirement': str(getattr(task, 'request_text', '') or ''),
            'sourceMethod': '高德地图网页精确查询',
            'contactInfo': contact_info,
        }
        if poi_id:
            payload['userRealUniqueUuid'] = poi_id
        return payload

    @staticmethod
    def fingerprint(payload: dict[str, Any]) -> str:
        stable_payload = {
            key: value
            for key, value in payload.items()
            if key != 'customerCapturedAt'
        }
        return payload_fingerprint(stable_payload)

    def deliver(self, payload: dict[str, Any]) -> DeliveryResult:
        if not self.target_url:
            return DeliveryResult(status='failed', error='ERP is not configured')
        headers = {'Content-Type': 'application/json; charset=utf-8'}
        if self.bearer_token:
            headers['Authorization'] = f'Bearer {self.bearer_token}'
        try:
            response = self.client.post(self.target_url, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return DeliveryResult(status='failed', error=str(exc))
        if not isinstance(body, dict):
            return DeliveryResult(status='failed', error='ERP returned an invalid JSON object')
        if body.get('errCode') != 0:
            return DeliveryResult(status='failed', error=str(body.get('errMsg') or f"ERP errCode={body.get('errCode')}"))
        operation_id = body.get('operationId') or body.get('operation_id')
        if operation_id is None and isinstance(body.get('data'), dict):
            operation_id = body['data'].get('operationId') or body['data'].get('operation_id')
        if operation_id is None and isinstance(body.get('result'), dict):
            operation_id = (
                body['result'].get('requestId')
                or body['result'].get('operationId')
                or body['result'].get('operation_id')
            )
        return DeliveryResult(status='delivered', operation_id=str(operation_id) if operation_id else None)
