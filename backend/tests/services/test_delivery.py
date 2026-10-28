from backend.app.domain.models import DeliveryResult, LeadRecord
from backend.app.domain.task_state import SearchTask
from backend.app.services.delivery import DeliveryService


class FakeErp:
    def __init__(self) -> None:
        self.calls = 0

    def build_payload(self, task, lead):
        return {'company': lead.company_name, 'captured_at': 'now'}

    def fingerprint(self, payload):
        return 'fingerprint-1'

    def deliver(self, payload):
        self.calls += 1
        return DeliveryResult(status='delivered', operation_id=f'op-{self.calls}', payload=payload)


def make_lead(**changes) -> LeadRecord:
    values = {
        'id': 'lead-1',
        'task_id': 'task-1',
        'city': '深圳市',
        'company_name': '深圳示例科技有限公司',
        'mobile': '13800138000',
        'source_url': 'https://example.com/company',
        'company_name_verification_status': 'verified_map',
        'contact_verification_status': 'verified_public_web',
    }
    values.update(changes)
    return LeadRecord(**values)


def test_delivery_service_blocks_unverified_lead_without_calling_erp() -> None:
    erp = FakeErp()
    task = SearchTask(id='task-1', company_name='深圳示例科技有限公司', city='深圳市')
    lead = make_lead(contact_verification_status='captured')
    service = DeliveryService(erp)

    result = service.deliver(task, lead)

    assert result.status == 'display_only'
    assert 'contact_unverified' in result.reasons
    assert erp.calls == 0


def test_delivery_service_returns_duplicate_for_same_fingerprint() -> None:
    erp = FakeErp()
    task = SearchTask(id='task-1', company_name='深圳示例科技有限公司', city='深圳市')
    lead = make_lead()
    service = DeliveryService(erp)

    first = service.deliver(task, lead)
    second = service.deliver(task, lead)

    assert first.status == 'delivered'
    assert second.status == 'duplicate'
    assert erp.calls == 1
