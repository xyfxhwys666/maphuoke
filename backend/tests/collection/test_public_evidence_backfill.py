from types import SimpleNamespace

from backend.app.collection.evidence_backfill import refresh_task_public_evidence
from backend.app.collection.intent import parse_collection_intent
from backend.app.collection.models import CollectionTask
from backend.app.domain.models import EvidenceResult, LeadRecord


def test_public_evidence_backfill_updates_captured_lead_without_delivery() -> None:
    task = CollectionTask(
        id='backfill-task',
        name='深圳软装',
        request_text='查询深圳软装公司，找 1 条有效信息。',
        intent=parse_collection_intent(
            '查询深圳软装公司，找 1 条有效信息。',
            configured_models=set(),
        ),
        status='completed',
        results=[
            LeadRecord(
                id='captured-lead',
                task_id='backfill-task',
                city='深圳市',
                company_name='深圳示例软装有限公司',
                mobile='13800138000',
                source_urls=['https://amap.example/poi'],
                contact_verification_status='captured',
            )
        ],
    )

    class Verifier:
        def verify_contact(self, **_kwargs):
            return EvidenceResult(
                company_name_verification_status='verified_public_web',
                contact_verification_status='verified_public_web',
                source_urls=['https://company.example/contact'],
                quotes=['深圳示例软装有限公司 电话：13800138000'],
            )

    persisted = []
    service = SimpleNamespace(
        public_evidence_verifier=Verifier(),
        _persist=lambda value: persisted.append(value.id),
    )

    summary = refresh_task_public_evidence(service, task)

    assert summary.checked_count == 1
    assert summary.verified_count == 1
    assert task.results[0].contact_verification_status == 'verified_public_web'
    assert task.results[0].contact_evidence_urls == ['https://company.example/contact']
    assert task.results[0].delivery_status == 'display_only'
    assert persisted == ['backfill-task']
