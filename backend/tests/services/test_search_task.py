from backend.app.browser.lifecycle import LoginRequired
from backend.app.domain.models import DeliveryResult, DoubaoEnrichment, EvidenceResult, EvidenceValue, LeadRecord
from backend.app.providers.fake import (
    FakeDoubaoGateway,
    FakeErpAdapter,
    FakeEvidenceVerifier,
    FakeMapDiscoveryProvider,
)
from backend.app.services.search_task import CompanySearchService


def make_service() -> tuple[CompanySearchService, FakeErpAdapter]:
    erp = FakeErpAdapter()
    service = CompanySearchService(
        map_provider=FakeMapDiscoveryProvider(),
        doubao_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        erp_adapter=erp,
    )
    return service, erp


def test_fake_pipeline_keeps_candidate_without_map_contact() -> None:
    service, _ = make_service()

    task = service.create_task(company_name='深圳示例科技有限公司', city='深圳市')
    service.discover(task.id)
    discovered = service.get_task(task.id)

    assert discovered.status == 'candidates_ready'
    assert discovered.candidates[0].address == '广东省深圳市南山区示例路 1 号'
    assert discovered.candidates[0].telephone is None


def test_pipeline_records_checkpoint_and_does_not_auto_deliver_unverified_lead() -> None:
    service, erp = make_service()

    task = service.create_task(company_name='深圳示例科技有限公司', city='深圳市')
    service.discover(task.id)
    candidate_id = service.get_task(task.id).candidates[0].candidate_id
    service.enrich(task.id, candidate_id=candidate_id)
    service.verify(task.id)
    result = service.deliver(task.id, candidate_id=candidate_id)
    current = service.get_task(task.id)

    assert result.status == 'display_only'
    assert 'contact_unverified' in result.reasons
    assert current.checkpoint.current_stage == 'verifying'
    assert erp.payloads == []


def test_service_can_accept_a_verified_lead_for_fake_erp() -> None:
    service, erp = make_service()
    task = service.create_task(company_name='深圳示例科技有限公司', city='深圳市')
    service.discover(task.id)
    candidate_id = service.get_task(task.id).candidates[0].candidate_id
    service.enrich(task.id, candidate_id=candidate_id)
    service.evidence_verifier.result.contact_verification_status = 'verified_public_web'
    service.evidence_verifier.result.source_urls = ['https://example.com/company']
    service.verify(task.id)

    result = service.deliver(task.id, candidate_id=candidate_id)

    assert result.status == 'delivered'
    assert len(erp.payloads) == 1
    assert isinstance(service.get_task(task.id).leads[0], LeadRecord)


def test_auto_deliver_runs_after_verification_gate_passes() -> None:
    erp = FakeErpAdapter()
    service = CompanySearchService(
        map_provider=FakeMapDiscoveryProvider(),
        doubao_gateway=FakeDoubaoGateway(
            enrichment=DoubaoEnrichment(
                mobile='13800138000',
                email='sales@example.com',
                source_urls=['https://public.example/company'],
            )
        ),
        evidence_verifier=FakeEvidenceVerifier(
            EvidenceResult(
                company_name_verification_status='verified_map',
                contact_verification_status='verified_public_web',
                source_urls=['https://public.example/company'],
            )
        ),
        erp_adapter=erp,
    )
    task = service.create_task(
        company_name='深圳示例科技有限公司',
        city='深圳市',
        auto_deliver=True,
    )
    service.discover(task.id)
    candidate_id = service.get_task(task.id).candidates[0].candidate_id
    service.enrich(task.id, candidate_id=candidate_id)

    verified = service.verify(task.id, candidate_id=candidate_id)

    assert verified.status == 'completed'
    assert verified.leads[0].delivery_status == 'delivered'
    assert len(erp.payloads) == 1


def test_discovery_pauses_and_can_resume_when_map_requires_login() -> None:
    erp = FakeErpAdapter()

    class LoginBlockedMap:
        id = 'amap_web'
        label = '高德地图网页'
        configured = True

        def search_company(self, **_):
            raise LoginRequired()

    service = CompanySearchService(
        map_provider=LoginBlockedMap(),
        doubao_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        erp_adapter=erp,
    )
    task = service.create_task(company_name='深圳示例科技有限公司', city='深圳市')

    paused = service.discover(task.id)

    assert paused.status == 'waiting_for_login'
    assert paused.checkpoint.browser_state == 'waiting_for_login'
    assert paused.checkpoint.resume_stage == 'discovering_map'
    assert paused.errors == ['Amap login is required']


def test_start_continues_paused_discovery_after_manual_login() -> None:
    attempts = 0

    class LoginThenMap(FakeMapDiscoveryProvider):
        def search_company(self, *, company_name: str, city: str, max_results: int = 5):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise LoginRequired()
            return super().search_company(company_name=company_name, city=city, max_results=max_results)

    service = CompanySearchService(
        map_provider=LoginThenMap(),
        doubao_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        erp_adapter=FakeErpAdapter(),
    )
    task = service.create_task(company_name='深圳示例科技有限公司', city='深圳市')
    paused = service.discover(task.id)
    paused_status = paused.status

    resumed = service.start(task.id)

    assert paused_status == 'waiting_for_login'
    assert resumed.status == 'candidates_ready'
    assert resumed.candidates
    assert attempts == 2


def test_successful_discovery_clears_stale_browser_pause_state() -> None:
    service, _ = make_service()
    task = service.create_task(company_name='深圳示例科技有限公司', city='深圳市')
    task.checkpoint.browser_state = 'waiting_for_challenge'

    discovered = service.discover(task.id)

    assert discovered.status == 'candidates_ready'
    assert discovered.checkpoint.browser_state == 'ready'


def test_discovery_records_checkpoint_query_time_and_company_progress_timestamp() -> None:
    service, _ = make_service()

    task = service.create_task(company_name='深圳示例科技有限公司', city='深圳市')
    discovered = service.discover(task.id)
    candidate_id = discovered.candidates[0].candidate_id

    assert discovered.checkpoint.current_company_index == 0
    assert discovered.checkpoint.last_successful_query_at is not None
    assert discovered.progress[candidate_id].last_updated_at is not None


def test_enrichment_pauses_and_keeps_map_candidate_when_doubao_requires_login() -> None:
    erp = FakeErpAdapter()

    class LoginBlockedDoubao:
        id = 'doubao_web'

        def enrich_company(self, **_):
            raise LoginRequired('Doubao login is required')

    service = CompanySearchService(
        map_provider=FakeMapDiscoveryProvider(),
        doubao_gateway=LoginBlockedDoubao(),
        evidence_verifier=FakeEvidenceVerifier(),
        erp_adapter=erp,
    )
    task = service.create_task(company_name='深圳示例科技有限公司', city='深圳市')
    service.discover(task.id)
    candidate_id = service.get_task(task.id).candidates[0].candidate_id

    paused = service.enrich(task.id, candidate_id=candidate_id)

    assert paused.status == 'waiting_for_login'
    assert paused.candidates[0].address == '广东省深圳市南山区示例路 1 号'
    assert paused.checkpoint.resume_stage == 'enriching_doubao'
    assert paused.errors == ['Doubao login is required']


def test_verify_uses_independent_public_contact_evidence_before_delivery() -> None:
    erp = FakeErpAdapter()

    class PublicVerifier:
        def verify_contact(self, **_):
            return EvidenceResult(
                company_name_verification_status='verified_public_web',
            contact_verification_status='verified_public_web',
            source_urls=['https://public.example/company'],
            quotes=['深圳示例科技有限公司 13800138000'],
            field_evidence={
                'mobile': EvidenceValue(
                    value='13800138000',
                    status='verified',
                    source_urls=['https://public.example/company'],
                )
            },
            grade='A',
                score=95,
            )

    service = CompanySearchService(
        map_provider=FakeMapDiscoveryProvider(),
        doubao_gateway=FakeDoubaoGateway(
            enrichment=DoubaoEnrichment(
                mobile='13800138000',
                source_urls=['https://public.example/company'],
            )
        ),
        evidence_verifier=FakeEvidenceVerifier(),
        public_evidence_verifier=PublicVerifier(),
        erp_adapter=erp,
    )
    task = service.create_task(company_name='深圳示例科技有限公司', city='深圳市')
    service.discover(task.id)
    candidate_id = service.get_task(task.id).candidates[0].candidate_id
    service.enrich(task.id, candidate_id=candidate_id)

    verified = service.verify(task.id, candidate_id=candidate_id)

    assert verified.leads[0].contact_verification_status == 'verified_public_web'
    assert verified.leads[0].contact_evidence_grade == 'A'
    assert verified.leads[0].field_evidence['mobile'].status == 'verified'


def test_failed_delivery_does_not_consume_fingerprint_and_can_be_retried() -> None:
    class FlakyErp(FakeErpAdapter):
        def deliver(self, payload):
            if not self.payloads:
                self.payloads.append(payload)
                return DeliveryResult(status='failed', error='temporary ERP failure')
            return super().deliver(payload)

    erp = FlakyErp()
    service = CompanySearchService(
        map_provider=FakeMapDiscoveryProvider(),
        doubao_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(
            EvidenceResult(
                company_name_verification_status='verified_map',
                contact_verification_status='verified_public_web',
            )
        ),
        erp_adapter=erp,
    )
    task = service.create_task(company_name='深圳示例科技有限公司', city='深圳市')
    service.discover(task.id)
    candidate_id = service.get_task(task.id).candidates[0].candidate_id
    service.enrich(task.id, candidate_id=candidate_id)
    service.verify(task.id, candidate_id=candidate_id)

    first = service.deliver(task.id, candidate_id=candidate_id)
    second = service.deliver(task.id, candidate_id=candidate_id)

    assert first.status == 'failed'
    assert second.status == 'delivered'
    assert len(erp.payloads) == 2


def test_retry_errors_replays_failed_delivery_and_clears_current_failure() -> None:
    class FlakyErp(FakeErpAdapter):
        def deliver(self, payload):
            if not self.payloads:
                self.payloads.append(payload)
                return DeliveryResult(status='failed', error='temporary ERP failure')
            return super().deliver(payload)

    erp = FlakyErp()
    service = CompanySearchService(
        map_provider=FakeMapDiscoveryProvider(),
        doubao_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(
            EvidenceResult(contact_verification_status='verified_public_web')
        ),
        erp_adapter=erp,
    )
    task = service.create_task(company_name='深圳示例科技有限公司', city='深圳市')
    service.discover(task.id)
    candidate_id = service.get_task(task.id).candidates[0].candidate_id
    service.enrich(task.id, candidate_id=candidate_id)
    service.verify(task.id, candidate_id=candidate_id)
    failed = service.deliver(task.id, candidate_id=candidate_id)

    retried = service.retry_errors(task.id)

    assert failed.status == 'failed'
    assert retried.status == 'completed'
    assert retried.checkpoint.failed_company_ids == []
    assert retried.progress[candidate_id].last_error is None


def test_delivery_ledger_prevents_duplicate_erp_call_after_service_reload() -> None:
    from backend.app.db import Base, create_database
    from backend.app.storage.repositories import TaskRepository

    engine, session_factory = create_database('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    repository = TaskRepository(session_factory)
    evidence_result = EvidenceResult(
        company_name_verification_status='verified_map',
        contact_verification_status='verified_public_web',
    )

    first_erp = FakeErpAdapter()
    first_service = CompanySearchService(
        map_provider=FakeMapDiscoveryProvider(),
        doubao_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(evidence_result),
        erp_adapter=first_erp,
        repository=repository,
    )
    first_task = first_service.create_task(company_name='深圳示例科技有限公司', city='深圳市')
    first_service.discover(first_task.id)
    first_candidate_id = first_task.candidates[0].candidate_id
    first_service.enrich(first_task.id, candidate_id=first_candidate_id)
    first_service.verify(first_task.id, candidate_id=first_candidate_id)
    first_result = first_service.deliver(first_task.id, candidate_id=first_candidate_id)

    second_erp = FakeErpAdapter()
    second_service = CompanySearchService(
        map_provider=FakeMapDiscoveryProvider(),
        doubao_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(evidence_result),
        erp_adapter=second_erp,
        repository=repository,
    )
    second_task = second_service.create_task(company_name='深圳示例科技有限公司', city='深圳市')
    second_service.discover(second_task.id)
    second_candidate_id = second_task.candidates[0].candidate_id
    second_service.enrich(second_task.id, candidate_id=second_candidate_id)
    second_service.verify(second_task.id, candidate_id=second_candidate_id)
    second_result = second_service.deliver(second_task.id, candidate_id=second_candidate_id)

    assert first_result.status == 'delivered'
    assert second_result.status == 'duplicate'
    assert second_result.operation_id == first_result.operation_id
    assert second_erp.payloads == []


def test_task_required_contacts_are_used_by_delivery_gate() -> None:
    erp = FakeErpAdapter()
    service = CompanySearchService(
        map_provider=FakeMapDiscoveryProvider(),
        doubao_gateway=FakeDoubaoGateway(enrichment=DoubaoEnrichment(wechat='example_sales')),
        evidence_verifier=FakeEvidenceVerifier(
            EvidenceResult(contact_verification_status='verified_public_web')
        ),
        erp_adapter=erp,
    )
    task = service.create_task(
        company_name='深圳示例科技有限公司',
        city='深圳市',
        required_contacts=['wechat'],
    )
    service.discover(task.id)
    candidate_id = task.candidates[0].candidate_id
    service.enrich(task.id, candidate_id=candidate_id)
    service.verify(task.id, candidate_id=candidate_id)

    result = service.deliver(task.id, candidate_id=candidate_id)

    assert result.status == 'delivered'
    assert len(erp.payloads) == 1


def test_same_task_duplicate_delivery_returns_original_operation_id() -> None:
    erp = FakeErpAdapter()
    service = CompanySearchService(
        map_provider=FakeMapDiscoveryProvider(),
        doubao_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(
            EvidenceResult(contact_verification_status='verified_public_web')
        ),
        erp_adapter=erp,
    )
    task = service.create_task(company_name='深圳示例科技有限公司', city='深圳市')
    service.discover(task.id)
    candidate_id = task.candidates[0].candidate_id
    service.enrich(task.id, candidate_id=candidate_id)
    service.verify(task.id, candidate_id=candidate_id)

    first = service.deliver(task.id, candidate_id=candidate_id)
    second = service.deliver(task.id, candidate_id=candidate_id)

    assert second.status == 'duplicate'
    assert second.operation_id == first.operation_id
