from datetime import UTC, datetime

from backend.app.collection.intent import parse_collection_intent
from backend.app.collection.models import CollectionSummary, CollectionTask
from backend.app.collection.planner import build_work_units
from backend.app.db import Base, create_database
from backend.app.domain.models import LeadRecord
from backend.app.storage import models as _storage_models  # noqa: F401
from backend.app.storage.models import CollectionTaskRow, DeliveryLedgerRow
from backend.app.storage.repositories import CollectionRepository


def test_collection_repository_restores_plan_and_checkpoint_after_reload() -> None:
    engine, session_factory = create_database('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    intent = parse_collection_intent(
        '深圳找软装公司，需要手机号，使用豆包',
        configured_models={'doubao'},
    )
    task = CollectionTask(
        id='collection-storage-1',
        name='深圳软装',
        request_text=intent.request_text,
        intent=intent,
        work_units=build_work_units(intent, task_seed='collection-storage-1'),
        summary=CollectionSummary(total_work_units=1),
    )
    task.checkpoint.current_stage = 'running'
    task.checkpoint.current_work_unit_id = task.work_units[0].id
    repository = CollectionRepository(session_factory)

    repository.save(task)
    restored = repository.get(task.id)

    assert restored is not None
    assert restored.intent.request_text == task.request_text
    assert restored.work_units[0].id == task.work_units[0].id
    assert restored.checkpoint.current_stage == 'running'
    assert restored.checkpoint.current_work_unit_id == task.work_units[0].id


def test_collection_repository_uses_database_creation_time() -> None:
    engine, session_factory = create_database('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    intent = parse_collection_intent(
        '深圳找设计公司，需要手机号',
        configured_models=set(),
    )
    task = CollectionTask(
        id='collection-created-at',
        name='深圳设计公司',
        request_text=intent.request_text,
        intent=intent,
    )
    repository = CollectionRepository(session_factory)
    repository.save(task)
    stored_created_at = datetime(2026, 8, 11, 8, 40, tzinfo=UTC)
    with session_factory() as session:
        row = session.get(CollectionTaskRow, task.id)
        assert row is not None
        row.created_at = stored_created_at
        session.commit()

    restored = repository.get(task.id)
    listed = repository.list()

    assert restored is not None
    assert restored.created_at == stored_created_at
    assert listed[0].created_at == stored_created_at


def test_collection_repository_backfills_delivery_time_from_ledger() -> None:
    engine, session_factory = create_database('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    intent = parse_collection_intent('查询深圳设计公司，需要手机号', configured_models=set())
    task = CollectionTask(
        id='collection-delivery-history',
        name='深圳设计公司',
        request_text=intent.request_text,
        intent=intent,
        results=[LeadRecord(
            id='lead-history-1',
            task_id='collection-delivery-history',
            city='深圳市',
            company_name='历史设计公司',
            delivery_status='delivered',
            delivery_fingerprint='history-fingerprint',
        )],
    )
    repository = CollectionRepository(session_factory)
    repository.save(task)
    delivered_at = datetime(2026, 8, 17, 9, 30, tzinfo=UTC)
    with session_factory() as session:
        session.add(DeliveryLedgerRow(
            id='history-fingerprint',
            task_id=task.id,
            lead_id='lead-history-1',
            fingerprint='history-fingerprint',
            status='delivered',
            payload={},
            attempts=1,
            created_at=delivered_at,
        ))
        session.commit()

    restored = repository.get(task.id)

    assert restored is not None
    assert restored.results[0].delivery_at == delivered_at


def test_collection_repository_persists_result_consumption_by_account_scope() -> None:
    engine, session_factory = create_database('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    repository = CollectionRepository(session_factory)

    assert repository.is_result_consumed(
        account_scope='tenant-a:member-1',
        result_fingerprint='fingerprint-1',
    ) is False

    repository.record_result_consumption(
        account_scope='tenant-a:member-1',
        result_fingerprint='fingerprint-1',
        source_task_id='collection-1',
    )

    assert repository.is_result_consumed(
        account_scope='tenant-a:member-1',
        result_fingerprint='fingerprint-1',
    ) is True
    assert repository.is_result_consumed(
        account_scope='tenant-b:member-2',
        result_fingerprint='fingerprint-1',
    ) is False


def test_collection_repository_claims_result_once_across_account_scopes() -> None:
    engine, session_factory = create_database('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    repository = CollectionRepository(session_factory)

    assert repository.claim_result_consumption(
        result_fingerprint='global-fingerprint-1',
        source_task_id='collection-1',
    ) is True
    assert repository.claim_result_consumption(
        result_fingerprint='global-fingerprint-1',
        source_task_id='collection-1',
    ) is False

    repository.record_result_consumption(
        account_scope='tenant-a:member-1',
        result_fingerprint='legacy-fingerprint-1',
        source_task_id='collection-legacy',
    )

    assert repository.claim_result_consumption(
        result_fingerprint='legacy-fingerprint-1',
        source_task_id='collection-legacy',
    ) is False
