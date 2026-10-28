from backend.app.domain.evidence import evaluate_delivery_gate
from backend.app.domain.models import DeliveryPolicy, LeadRecord


def test_unverified_model_mobile_is_display_only() -> None:
    lead = LeadRecord(
        id='lead-1',
        task_id='task-1',
        city='深圳市',
        company_name='深圳示例科技有限公司',
        mobile='13800138000',
        source_url='https://uri.amap.com/marker?id=poi-1',
        company_name_verification_status='verified_map',
        contact_verification_status='captured',
    )

    decision = evaluate_delivery_gate(DeliveryPolicy(), lead)

    assert decision.status == 'display_only'
    assert 'contact_unverified' in decision.reasons


def test_verified_public_contact_can_pass_default_gate() -> None:
    lead = LeadRecord(
        id='lead-2',
        task_id='task-1',
        city='深圳市',
        company_name='深圳示例科技有限公司',
        mobile='13800138000',
        source_url='https://example.com/company',
        company_name_verification_status='verified_map',
        contact_verification_status='verified_public_web',
    )

    decision = evaluate_delivery_gate(DeliveryPolicy(), lead)

    assert decision.status == 'ready'
    assert decision.reasons == []


def test_required_contact_policy_can_use_wechat_without_mobile_or_email() -> None:
    lead = LeadRecord(
        id='lead-3',
        task_id='task-1',
        city='深圳市',
        company_name='深圳示例科技有限公司',
        wechat='example_sales',
        source_url='https://example.com/company',
        company_name_verification_status='verified_map',
        contact_verification_status='verified_public_web',
    )

    decision = evaluate_delivery_gate(DeliveryPolicy(required_contacts=['wechat']), lead)

    assert decision.status == 'ready'
    assert decision.reasons == []
