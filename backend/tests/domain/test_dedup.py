from backend.app.domain.dedup import company_identity, contact_identity, payload_fingerprint
from backend.app.domain.models import LeadRecord


def test_company_identity_uses_normalized_city_and_name() -> None:
    assert company_identity(' 深圳市 ', ' 深圳 示例 科技有限公司 ') == '深圳市:深圳示例科技有限公司'


def test_contact_identity_returns_mobile_email_and_wechat_keys() -> None:
    lead = LeadRecord(
        id='lead-1',
        task_id='task-1',
        city='深圳市',
        company_name='深圳示例科技有限公司',
        mobile='13800138000',
        email='sales@example.com',
        wechat='example_sales',
    )

    assert contact_identity(lead) == {
        'mobile:13800138000',
        'email:sales@example.com',
        'wechat:example_sales',
    }


def test_payload_fingerprint_ignores_capture_timestamps() -> None:
    first = {'company': 'A', 'captured_at': '2026-08-05T10:00:00Z'}
    second = {'company': 'A', 'captured_at': '2026-08-05T10:01:00Z'}

    assert payload_fingerprint(first) == payload_fingerprint(second)
