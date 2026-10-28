from backend.app.db import Base, create_database
from backend.app.providers.fake import (
    FakeDoubaoGateway,
    FakeErpAdapter,
    FakeEvidenceVerifier,
    FakeMapDiscoveryProvider,
)
from backend.app.services.search_task import CompanySearchService
from backend.app.storage import models
from backend.app.storage.repositories import TaskRepository
from sqlalchemy import inspect


def make_service(repository: TaskRepository) -> CompanySearchService:
    return CompanySearchService(
        map_provider=FakeMapDiscoveryProvider(),
        doubao_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        erp_adapter=FakeErpAdapter(),
        repository=repository,
    )


def test_task_and_checkpoint_survive_service_reload() -> None:
    engine, session_factory = create_database('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    assert models.TaskRow.__tablename__ == 'search_tasks'
    assert set(inspect(engine).get_table_names()) == {
        'batch_jobs',
        'search_tasks',
        'map_candidates',
        'lead_records',
        'task_checkpoints',
        'delivery_ledger',
        'collection_tasks',
        'collection_work_units',
            'collection_candidates',
            'collection_checkpoints',
            'collection_result_consumptions',
        }
    repository = TaskRepository(session_factory)

    first_service = make_service(repository)
    task = first_service.create_task(company_name='深圳示例科技有限公司', city='深圳市')
    first_service.discover(task.id)

    second_service = make_service(repository)
    restored = second_service.get_task(task.id)

    assert restored.status == 'candidates_ready'
    assert restored.checkpoint.current_stage == 'candidates_ready'
    assert restored.candidates[0].candidate_id == 'fake-poi-1'


def test_candidates_with_same_provider_id_are_isolated_by_task() -> None:
    engine, session_factory = create_database('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    repository = TaskRepository(session_factory)
    service = make_service(repository)

    first = service.create_task(company_name='第一家公司', city='深圳市')
    second = service.create_task(company_name='第二家公司', city='广州市')

    first_result = service.discover(first.id)
    second_result = service.discover(second.id)

    assert first_result.status == 'candidates_ready'
    assert second_result.status == 'candidates_ready'
    assert first_result.candidates[0].candidate_id == second_result.candidates[0].candidate_id
