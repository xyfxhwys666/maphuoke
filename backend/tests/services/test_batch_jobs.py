from __future__ import annotations

from backend.app.batch.importers import CompanyInput
from backend.app.db import Base, create_database
from backend.app.providers.fake import FakeDoubaoGateway, FakeErpAdapter, FakeEvidenceVerifier, FakeMapDiscoveryProvider
from backend.app.services.batch_jobs import BatchJobManager
from backend.app.services.search_task import CompanySearchService
from backend.app.storage.repositories import TaskRepository


def make_service(map_provider=None) -> CompanySearchService:
    return CompanySearchService(
        map_provider=map_provider or FakeMapDiscoveryProvider(),
        doubao_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        erp_adapter=FakeErpAdapter(),
    )


def test_batch_job_runs_discovery_sequentially_and_exposes_child_tasks() -> None:
    service = make_service()
    manager = BatchJobManager(service, request_interval_seconds=0, background=False)
    job = manager.create_job(
        filename='companies.csv',
        items=[
            CompanyInput(company_name='成功公司', city='深圳市', row_number=2),
            CompanyInput(company_name='另一家公司', city='广州市', row_number=3),
        ],
    )

    started = manager.start(job.id)

    assert started.status == 'completed'
    assert [item.status for item in started.items] == ['completed', 'completed']
    assert all(item.task_id for item in started.items)
    assert all(item.candidate_count == 1 for item in started.items)
    assert all(service.get_task(item.task_id).status == 'candidates_ready' for item in started.items if item.task_id)


def test_batch_job_deduplicates_inputs_before_assigning_result_rows() -> None:
    manager = BatchJobManager(make_service(), request_interval_seconds=0, background=False)

    job = manager.create_job(
        filename='companies.csv',
        items=[
            CompanyInput(company_name='重复公司', city='深圳市', row_number=2),
            CompanyInput(company_name='重复公司', city='深圳市', row_number=3),
            CompanyInput(company_name='另一家公司', city='广州市', row_number=4),
        ],
    )

    assert job.total == 2
    assert [(item.company_name, item.row_number) for item in job.items] == [
        ('重复公司', 2),
        ('另一家公司', 4),
    ]


def test_batch_job_retries_only_failed_company() -> None:
    attempts: dict[str, int] = {}

    class FlakyMap(FakeMapDiscoveryProvider):
        def search_company(self, *, company_name: str, city: str, max_results: int = 5):
            attempts[company_name] = attempts.get(company_name, 0) + 1
            if company_name == '失败公司' and attempts[company_name] == 1:
                raise RuntimeError('temporary map failure')
            return super().search_company(company_name=company_name, city=city, max_results=max_results)

    manager = BatchJobManager(
        make_service(FlakyMap()),
        request_interval_seconds=0,
        background=False,
    )
    job = manager.create_job(
        filename='companies.csv',
        items=[
            CompanyInput(company_name='成功公司', city='深圳市', row_number=2),
            CompanyInput(company_name='失败公司', city='广州市', row_number=3),
        ],
    )

    first = manager.start(job.id)
    retried = manager.retry_errors(job.id)

    assert first.status == 'completed_with_errors'
    assert [item.status for item in first.items] == ['completed', 'failed']
    assert first.items[1].task_id
    assert retried.status == 'completed'
    assert [item.status for item in retried.items] == ['completed', 'completed']
    assert retried.items[1].retry_count == 1
    assert retried.items[1].task_id == first.items[1].task_id
    assert attempts == {'成功公司': 1, '失败公司': 2}


def test_batch_job_state_and_child_tasks_survive_manager_reload() -> None:
    engine, session_factory = create_database('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    repository = TaskRepository(session_factory)
    service = make_service()
    first_manager = BatchJobManager(
        service,
        request_interval_seconds=0,
        background=False,
        repository=repository,
    )
    job = first_manager.create_job(
        filename='companies.csv',
        items=[CompanyInput(company_name='重启公司', city='深圳市', row_number=2)],
    )
    started = first_manager.start(job.id)

    second_manager = BatchJobManager(
        service,
        request_interval_seconds=0,
        background=False,
        repository=repository,
    )
    restored = second_manager.get_job(job.id)

    assert started.status == 'completed'
    assert restored.status == 'completed'
    assert restored.items[0].task_id == started.items[0].task_id
