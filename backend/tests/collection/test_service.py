from threading import Event

from backend.app.collection.models import (
    CollectionSummary,
    CompanyNameCandidate,
    RelevanceDecision,
)
from backend.app.collection.service import CollectionService
from backend.app.domain.models import (
    DoubaoEnrichment,
    EvidenceResult,
    EvidenceValue,
    LeadRecord,
    MapPoiCandidate,
)
from backend.app.providers.fake import (
    FakeDoubaoGateway,
    FakeErpAdapter,
    FakeEvidenceVerifier,
    FakeRelevanceJudge,
)
from backend.app.providers.protocols import ProviderPaused


class FakeKeywordDiscoveryProvider:
    id = 'amap_web'
    label = 'Fake Amap keyword provider'
    configured = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.pause_on_query: tuple[str, str] | None = None

    @property
    def call_counts(self) -> dict[tuple[str, str], int]:
        return {
            query: self.calls.count(query)
            for query in set(self.calls)
        }

    def search_keyword(self, *, city: str, keyword: str, max_results: int = 20) -> list[MapPoiCandidate]:
        query = (city, keyword)
        self.calls.append(query)
        if query == self.pause_on_query:
            raise ProviderPaused(
                'manual Amap login required',
                task_status='needs_attention',
                browser_state='waiting_for_login',
            )
        return [
            MapPoiCandidate(
                candidate_id=f'poi-{city}',
                company_name=f'{city}示例软装公司',
                city=city,
                address=f'{city}南山区示例路 1 号',
                mobile='13800138000',
                source_url=f'https://uri.amap.com/marker?pid={city}',
                raw_text=f'{city}示例软装公司\n地址：{city}南山区示例路 1 号',
                discovery_channel=self.id,
            )
        ][:max_results]


class BlockingKeywordDiscoveryProvider(FakeKeywordDiscoveryProvider):
    def __init__(self) -> None:
        super().__init__()
        self.started = Event()
        self.release = Event()

    def search_keyword(self, *, city: str, keyword: str, max_results: int = 20) -> list[MapPoiCandidate]:
        self.started.set()
        self.release.wait(timeout=2)
        return super().search_keyword(city=city, keyword=keyword, max_results=max_results)


class FakePublicEvidenceVerifier:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def verify_contact(
        self,
        *,
        company_name: str,
        mobile: str | None = None,
        email: str | None = None,
        source_urls: list[str] | None = None,
    ) -> EvidenceResult:
        self.calls.append({
            'company_name': company_name,
            'mobile': mobile,
            'email': email,
            'source_urls': source_urls or [],
        })
        return EvidenceResult(
            company_name_verification_status='verified_public_web',
            contact_verification_status='verified_public_web',
            source_urls=['https://public.example.test/company'],
            field_evidence={
                'mobile': EvidenceValue(
                    value=mobile,
                    status='verified',
                    source_urls=['https://public.example.test/company'],
                    quotes=['示例公司 13800138000'],
                )
            },
        )


class FlakyEnrichmentGateway(FakeDoubaoGateway):
    id = 'fake_doubao'

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def enrich_company(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError('temporary enrichment failure')
        return super().enrich_company(**kwargs)


class MultiSourceKeywordDiscoveryProvider(FakeKeywordDiscoveryProvider):
    def search_keyword(self, *, city: str, keyword: str, max_results: int = 20) -> list[MapPoiCandidate]:
        source_index = len(self.calls) + 1
        self.calls.append((city, keyword))
        return [
            MapPoiCandidate(
                candidate_id=f'poi-{source_index}',
                company_name=f'{city}示例软装公司',
                city=city,
                address=f'{city}南山区示例路 {source_index} 号',
                source_url=f'https://amap.example.test/poi/{source_index}',
                source_urls=[f'https://amap.example.test/poi/{source_index}'],
                raw_text=f'{city}示例软装公司 {keyword}',
                discovery_channel=self.id,
            )
        ][:max_results]


class RelevantJudge:
    id = 'doubao'
    configured = True

    def judge(self, *, request_text: str, city: str, keyword: str, candidate: MapPoiCandidate) -> RelevanceDecision:
        return RelevanceDecision(
            candidate_id=candidate.candidate_id,
            model_id=self.id,
            status='relevant',
            reason=f'matched {keyword}',
        )


class MapOnlyKeywordDiscoveryProvider(FakeKeywordDiscoveryProvider):
    def search_keyword(self, *, city: str, keyword: str, max_results: int = 20) -> list[MapPoiCandidate]:
        self.calls.append((city, keyword))
        return [
            MapPoiCandidate(
                candidate_id='map-only-poi',
                company_name=f'{city}示例软装设计有限公司',
                city=city,
                address=f'{city}南山区示例路 1 号',
                telephone='0755-12345678',
                category='装修设计',
                poi_id='map-only-poi',
                source_url='https://uri.amap.com/marker?pid=map-only-poi',
                discovery_channel='amap_web',
            )
        ][:max_results]


class FakeCompanyCandidateDiscoveryProvider:
    id = 'public_web_company_names'
    label = 'Fake public company-name discovery'
    configured = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def discover_company_names(
        self,
        *,
        city: str,
        keyword: str,
        request_text: str,
        max_results: int,
    ) -> list[CompanyNameCandidate]:
        self.calls.append((city, keyword))
        return [
            CompanyNameCandidate(
                company_name='深圳智林装饰软装设计工程有限公司',
                city=city,
                matched_keyword=keyword,
                source_urls=['https://www.example.com/zhi-lin'],
                evidence_quotes=['深圳智林装饰软装设计工程有限公司 软装设计 联系方式'],
            )
        ][:max_results]


class FirstCompanyCandidateLookupFailsProvider(
    FakeCompanyCandidateDiscoveryProvider
):
    def discover_company_names(self, **kwargs) -> list[CompanyNameCandidate]:
        if not self.calls:
            self.calls.append((kwargs['city'], kwargs['keyword']))
            raise RuntimeError('temporary company-name lookup failure')
        return super().discover_company_names(**kwargs)


class EmptyCompanyCandidateDiscoveryProvider(FakeCompanyCandidateDiscoveryProvider):
    def discover_company_names(self, **kwargs) -> list[CompanyNameCandidate]:
        self.calls.append((kwargs['city'], kwargs['keyword']))
        return []


class MixedResidentialCompanyCandidateDiscoveryProvider(
    FakeCompanyCandidateDiscoveryProvider
):
    def discover_company_names(self, **kwargs) -> list[CompanyNameCandidate]:
        self.calls.append((kwargs['city'], kwargs['keyword']))
        return [
            CompanyNameCandidate(
                company_name='深圳金牌高端婚礼活动策划公司',
                city=kwargs['city'],
                matched_keyword=kwargs['keyword'],
            ),
            CompanyNameCandidate(
                company_name='深圳智林装饰软装设计工程有限公司',
                city=kwargs['city'],
                matched_keyword=kwargs['keyword'],
            ),
        ]


class FakeExactCompanyMapProvider:
    id = 'amap_web'
    label = 'Fake Amap exact company provider'
    configured = True
    last_state = 'ready'

    def __init__(self) -> None:
        self.keyword_calls: list[tuple[str, str]] = []
        self.company_calls: list[tuple[str, str]] = []

    def search_keyword(self, *, city: str, keyword: str, max_results: int = 20) -> list[MapPoiCandidate]:
        self.keyword_calls.append((city, keyword))
        return []

    def search_company(self, *, company_name: str, city: str, max_results: int = 5) -> list[MapPoiCandidate]:
        self.company_calls.append((city, company_name))
        return [
            MapPoiCandidate(
                candidate_id='amap-zhi-lin',
                company_name=company_name,
                city=city,
                address='深圳市南山区科技园 1 号',
                mobile='17665736111',
                category='装饰设计',
                longitude=113.93,
                latitude=22.54,
                poi_id='amap-zhi-lin',
                source_url='https://uri.amap.com/marker?pid=amap-zhi-lin',
                discovery_channel='amap_web',
            )
        ][:max_results]


class RefreshExactMobileMapProvider(FakeExactCompanyMapProvider):
    def search_company(self, *, company_name: str, city: str, max_results: int = 5) -> list[MapPoiCandidate]:
        self.company_calls.append((city, company_name))
        return [
            MapPoiCandidate(
                candidate_id=f'amap-refresh-{company_name}',
                company_name=company_name,
                city=city,
                address='深圳市南山区详情路 1 号',
                mobile='13800138000',
                category='软装设计',
                poi_id=f'amap-refresh-{company_name}',
                source_url='https://www.amap.com/place/amap-refresh',
                raw_text=f'{company_name}\n电话：13800138000',
                source_metadata={
                    'provider': 'amap_web',
                    'detail_verified': True,
                    'detail_raw_text': f'{company_name} 电话：13800138000',
                },
                discovery_channel='amap_web',
            )
        ][:max_results]


class RefreshLandlineMapProvider(RefreshExactMobileMapProvider):
    def search_company(self, *, company_name: str, city: str, max_results: int = 5) -> list[MapPoiCandidate]:
        self.company_calls.append((city, company_name))
        return [
            MapPoiCandidate(
                candidate_id=f'amap-landline-refresh-{company_name}',
                company_name=company_name,
                city=city,
                telephone='0755-82793362',
                source_url='https://www.amap.com/place/amap-landline-refresh',
                raw_text=f'{company_name}\n电话：0755-82793362',
                source_metadata={
                    'provider': 'amap_web',
                    'detail_verified': True,
                    'detail_raw_text': f'{company_name} 电话：0755-82793362',
                },
            )
        ][:max_results]


class RefreshPausedMapProvider(RefreshExactMobileMapProvider):
    def search_company(self, *, company_name: str, city: str, max_results: int = 5) -> list[MapPoiCandidate]:
        raise ProviderPaused(
            'manual Amap challenge required',
            task_status='needs_attention',
            browser_state='waiting_for_challenge',
        )


class KeywordFallbackExactMapProvider(FakeExactCompanyMapProvider):
    def search_keyword(self, *, city: str, keyword: str, max_results: int = 20) -> list[MapPoiCandidate]:
        self.keyword_calls.append((city, keyword))
        return [
            MapPoiCandidate(
                candidate_id='amap-keyword-candidate',
                company_name='深圳候选软装设计有限公司',
                city=city,
                address='深圳市南山区候选路 1 号',
                telephone='0755-00000000',
                poi_id='amap-keyword-candidate',
                source_url='https://www.amap.com/place/amap-keyword-candidate',
                discovery_channel='amap_web',
            )
        ][:max_results]


class PlacePoiKeywordFallbackProvider(FakeExactCompanyMapProvider):
    def search_keyword(self, *, city: str, keyword: str, max_results: int = 20) -> list[MapPoiCandidate]:
        self.keyword_calls.append((city, keyword))
        return [
            MapPoiCandidate(candidate_id='poi-back-bay', company_name='后海', city=city),
            MapPoiCandidate(candidate_id='poi-exit', company_name='后海(出口)', city=city),
            MapPoiCandidate(candidate_id='poi-tower', company_name='阿里中心深圳后海T3座', city=city),
            MapPoiCandidate(candidate_id='poi-village', company_name='后海村', city=city),
            MapPoiCandidate(candidate_id='poi-post', company_name='深圳后海实业有限公司', city=city),
            MapPoiCandidate(
                candidate_id='poi-target',
                company_name='深圳目标软装设计有限公司',
                city=city,
                raw_text='深圳目标软装设计有限公司\n分类：室内装饰设计',
            ),
        ][:max_results]


class CrossCityKeywordFallbackMapProvider(KeywordFallbackExactMapProvider):
    def search_keyword(self, *, city: str, keyword: str, max_results: int = 20) -> list[MapPoiCandidate]:
        candidates = super().search_keyword(city=city, keyword=keyword, max_results=max_results)
        return [candidate.model_copy(update={'city': '广州市'}) for candidate in candidates]


class LandlineOnlyExactMapProvider(FakeExactCompanyMapProvider):
    def search_company(self, *, company_name: str, city: str, max_results: int = 5) -> list[MapPoiCandidate]:
        self.company_calls.append((city, company_name))
        return [
            MapPoiCandidate(
                candidate_id='amap-landline-only',
                company_name=company_name,
                city=city,
                address='深圳市南山区座机路 1 号',
                telephone='0755-82793362',
                poi_id='amap-landline-only',
                source_url='https://www.amap.com/place/amap-landline-only',
                discovery_channel='amap_web',
            )
        ][:max_results]


class FuzzyExactCompanyMapProvider(FakeExactCompanyMapProvider):
    def search_company(self, *, company_name: str, city: str, max_results: int = 5) -> list[MapPoiCandidate]:
        self.company_calls.append((city, company_name))
        return [
            MapPoiCandidate(
                candidate_id='amap-fuzzy-name',
                company_name='深圳市标美照明设计工程有限公司',
                city=city,
                address='深圳市南山区科技园 2 号',
                telephone='0755-12345678',
                poi_id='amap-fuzzy-name',
                source_url='https://uri.amap.com/marker?pid=amap-fuzzy-name',
                discovery_channel='amap_web',
            )
        ][:max_results]


class CrossCityExactCompanyMapProvider(FakeExactCompanyMapProvider):
    def search_company(self, *, company_name: str, city: str, max_results: int = 5) -> list[MapPoiCandidate]:
        self.company_calls.append((city, company_name))
        return [
            MapPoiCandidate(
                candidate_id='amap-cross-city',
                company_name=company_name,
                city='广州市',
                address='广州市天河区示例路 1 号',
                telephone='020-12345678',
                poi_id='amap-cross-city',
                source_url='https://uri.amap.com/marker?pid=amap-cross-city',
                discovery_channel='amap_web',
            )
        ][:max_results]


class TwoCompanyNameDiscoveryProvider(FakeCompanyCandidateDiscoveryProvider):
    def discover_company_names(self, **kwargs) -> list[CompanyNameCandidate]:
        first = super().discover_company_names(**kwargs)[0]
        return [
            first,
            CompanyNameCandidate(
                company_name='深圳市超时软装设计有限公司',
                city=first.city,
                matched_keyword=first.matched_keyword,
                source_urls=['https://www.example.com/timeout-company'],
                evidence_quotes=['深圳市超时软装设计有限公司 软装设计'],
            ),
        ]


class PartiallyTimingOutMapProvider(FakeExactCompanyMapProvider):
    def search_company(self, *, company_name: str, city: str, max_results: int = 5) -> list[MapPoiCandidate]:
        if company_name == '深圳市超时软装设计有限公司':
            self.company_calls.append((city, company_name))
            raise TimeoutError('Amap exact lookup timed out')
        return super().search_company(company_name=company_name, city=city, max_results=max_results)


def test_collection_discovers_real_company_names_before_exact_amap_lookup() -> None:
    names = FakeCompanyCandidateDiscoveryProvider()
    amap = FakeExactCompanyMapProvider()
    service = CollectionService(
        map_provider=amap,
        candidate_discovery_provider=names,
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    task = service.create_from_text('找深圳软装设计公司，需要电话和地址。')

    completed = service.start(task.id)

    assert completed.status == 'completed'
    assert names.calls
    assert amap.keyword_calls == [('深圳市', '软装设计公司')]
    assert amap.company_calls == [
        ('深圳市', '深圳智林装饰软装设计工程有限公司')
    ]
    assert completed.company_name_candidates[0].company_name == '深圳智林装饰软装设计工程有限公司'
    assert completed.candidates[0].source_metadata['discovery_channel'] == 'public_web'
    assert completed.candidates[0].source_metadata['company_name_evidence_urls'] == [
        'https://www.example.com/zhi-lin'
    ]
    assert completed.results[0].mobile == '17665736111'
    assert completed.results[0].address == '深圳市南山区科技园 1 号'
    assert completed.results[0].source_metadata['amap_category'] == '装饰设计'
    assert completed.results[0].source_metadata['amap_coordinates'] == {
        'longitude': 113.93,
        'latitude': 22.54,
    }
    assert completed.checkpoint.current_stage == 'completed'
    assert completed.checkpoint.browser_state == 'ready'


def test_collection_skips_company_names_already_seen_in_another_task() -> None:
    names = FakeCompanyCandidateDiscoveryProvider()
    amap = FakeExactCompanyMapProvider()
    service = CollectionService(
        map_provider=amap,
        candidate_discovery_provider=names,
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    first = service.create_from_text('找深圳软装设计公司，需要电话和地址。')
    first.company_name_candidates.append(
        CompanyNameCandidate(
            company_name='深圳智林装饰软装设计工程有限公司',
            city='深圳市',
            matched_keyword='软装设计公司',
        )
    )
    second = service.create_from_text('找深圳软装设计公司，需要电话和地址。')

    service.start(second.id)

    assert amap.company_calls == []


def test_collection_skips_company_names_already_searched_by_an_earlier_work_unit() -> None:
    names = FakeCompanyCandidateDiscoveryProvider()
    amap = FakeExactCompanyMapProvider()
    service = CollectionService(
        map_provider=amap,
        candidate_discovery_provider=names,
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    task = service.create_from_text('找深圳软装设计公司，需要电话和地址。')
    task.work_units.append(
        task.work_units[0].model_copy(
            update={'id': 'unit-second-keyword', 'keyword': '整装设计公司'},
            deep=True,
        )
    )
    task.summary.total_work_units = len(task.work_units)

    service.start(task.id)

    assert amap.company_calls == [
        ('深圳市', '深圳智林装饰软装设计工程有限公司'),
    ]


def test_collection_does_not_repeat_an_exact_lookup_that_previously_had_no_match() -> None:
    class NoMatchMapProvider(FakeExactCompanyMapProvider):
        def search_company(
            self,
            *,
            company_name: str,
            city: str,
            max_results: int = 5,
        ) -> list[MapPoiCandidate]:
            self.company_calls.append((city, company_name))
            return []

    names = FakeCompanyCandidateDiscoveryProvider()
    amap = NoMatchMapProvider()
    service = CollectionService(
        map_provider=amap,
        candidate_discovery_provider=names,
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    task = service.create_from_text('找深圳软装设计公司，需要电话和地址。')
    task.work_units.append(
        task.work_units[0].model_copy(
            update={'id': 'unit-second-no-match', 'keyword': '整装设计公司'},
            deep=True,
        )
    )
    task.summary.total_work_units = len(task.work_units)

    service.start(task.id)

    assert amap.company_calls == [
        ('深圳市', '深圳智林装饰软装设计工程有限公司'),
    ]


def test_residential_collection_skips_hard_irrelevant_company_names() -> None:
    names = MixedResidentialCompanyCandidateDiscoveryProvider()
    amap = FakeExactCompanyMapProvider()
    service = CollectionService(
        map_provider=amap,
        candidate_discovery_provider=names,
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    task = service.create_from_text(
        '我是做家具的，寻找深圳全案软装公司、设计公司和整装公司，需要手机号。'
    )

    service.start(task.id)

    assert all('婚礼' not in company for _city, company in amap.company_calls)
    assert ('深圳市', '深圳智林装饰软装设计工程有限公司') in amap.company_calls


def test_collection_rechecks_competitor_terms_for_existing_task() -> None:
    service = CollectionService(
        map_provider=FakeExactCompanyMapProvider(),
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    task = service.create_from_text(
        '我是做家具的，寻找深圳全案软装公司、设计公司和整装公司，需要手机号。'
    )
    task.intent.competitor_terms = ['家具']

    assert service._is_competitor(task, '深圳索菲亚良造整装店') is True


def test_residential_collection_prunes_persisted_hard_irrelevant_results() -> None:
    amap = FakeKeywordDiscoveryProvider()
    service = CollectionService(
        map_provider=amap,
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    task = service.create_from_text(
        '我是做家具的，寻找深圳软装和整装公司，需要手机号。'
    )
    task.candidates = [
        MapPoiCandidate(
            candidate_id='valid',
            company_name='深圳住宅软装设计有限公司',
            city='深圳市',
        ),
        MapPoiCandidate(
            candidate_id='wedding',
            company_name='深圳高端婚礼活动策划公司',
            city='深圳市',
        ),
    ]
    task.results = [
        LeadRecord(
            id='lead-valid',
            task_id=task.id,
            company_name='深圳住宅软装设计有限公司',
            city='深圳市',
        ),
        LeadRecord(
            id='lead-wedding',
            task_id=task.id,
            company_name='深圳高端婚礼活动策划公司',
            city='深圳市',
        ),
    ]

    changed = service._prune_hard_irrelevant_residential_results(task)

    assert changed is True
    assert [candidate.candidate_id for candidate in task.candidates] == ['valid']
    assert [lead.id for lead in task.results] == ['lead-valid']


def test_completed_collection_can_extend_keywords_without_replaying_old_units() -> None:
    amap = FakeKeywordDiscoveryProvider()
    service = CollectionService(
        map_provider=amap,
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    task = service.create_from_text('找深圳软装设计公司，需要电话和地址。')
    completed = service.start(task.id)
    original_unit_count = len(completed.work_units)
    original_calls = list(amap.calls)

    extended = service.extend_keywords(
        task.id,
        ['整装公司', completed.work_units[0].keyword],
    )
    resumed = service.start(extended.id)

    assert len(resumed.work_units) == original_unit_count + 1
    assert resumed.intent.keywords[-1] == '整装公司'
    assert amap.calls[:len(original_calls)] == original_calls
    assert amap.calls[len(original_calls):] == [('深圳市', '整装公司')]


def test_empty_public_discovery_uses_amap_names_then_exact_lookup() -> None:
    names = EmptyCompanyCandidateDiscoveryProvider()
    amap = KeywordFallbackExactMapProvider()
    service = CollectionService(
        map_provider=amap,
        candidate_discovery_provider=names,
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    task = service.create_from_text('寻找深圳软装设计公司，需要电话，找 1 条有效信息。')

    completed = service.start(task.id)

    assert amap.keyword_calls == [('深圳市', '软装设计公司')]
    assert amap.company_calls == [('深圳市', '深圳候选软装设计有限公司')]
    assert completed.summary.valid_contact_count == 1
    assert completed.candidates[0].mobile == '17665736111'
    assert completed.candidates[0].source_metadata['discovery_channel'] == 'amap_keyword'


def test_collection_rejects_location_pois_before_exact_company_lookup() -> None:
    amap = PlacePoiKeywordFallbackProvider()
    service = CollectionService(
        map_provider=amap,
        candidate_discovery_provider=EmptyCompanyCandidateDiscoveryProvider(),
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    task = service.create_from_text('寻找深圳软装设计公司，需要手机号，找 1 条有效信息。')

    service.start(task.id)

    assert amap.company_calls == [('深圳市', '深圳目标软装设计有限公司')]
    assert [item.company_name for item in task.company_name_candidates] == [
        '深圳目标软装设计有限公司'
    ]


def test_public_and_amap_company_name_candidates_are_combined_before_exact_lookup() -> None:
    amap = KeywordFallbackExactMapProvider()
    service = CollectionService(
        map_provider=amap,
        candidate_discovery_provider=FakeCompanyCandidateDiscoveryProvider(),
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    task = service.create_from_text('寻找深圳软装设计公司，需要手机号，找 2 条有效信息。')

    completed = service.start(task.id)

    assert amap.company_calls == [
        ('深圳市', '深圳智林装饰软装设计工程有限公司'),
        ('深圳市', '深圳候选软装设计有限公司'),
    ]
    assert completed.summary.candidate_count == 2


def test_exact_capable_amap_provider_never_accepts_broad_result_as_final() -> None:
    amap = KeywordFallbackExactMapProvider()
    service = CollectionService(
        map_provider=amap,
        candidate_discovery_provider=None,
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    task = service.create_from_text('寻找深圳软装设计公司，需要手机号，找 1 条有效信息。')

    completed = service.start(task.id)

    assert amap.keyword_calls == [('深圳市', '软装设计公司')]
    assert amap.company_calls == [('深圳市', '深圳候选软装设计有限公司')]
    assert completed.candidates[0].mobile == '17665736111'


def test_amap_keyword_fallback_keeps_task_city_authoritative() -> None:
    amap = CrossCityKeywordFallbackMapProvider()
    service = CollectionService(
        map_provider=amap,
        candidate_discovery_provider=EmptyCompanyCandidateDiscoveryProvider(),
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    task = service.create_from_text('寻找深圳软装设计公司，需要手机号，找 1 条有效信息。')

    completed = service.start(task.id)

    assert amap.company_calls == [('深圳市', '深圳候选软装设计有限公司')]
    assert completed.results[0].city == '深圳市'


def test_enrichment_mobile_cannot_replace_landline_only_amap_contact() -> None:
    service = CollectionService(
        map_provider=LandlineOnlyExactMapProvider(),
        candidate_discovery_provider=FakeCompanyCandidateDiscoveryProvider(),
        relevance_judges={},
        enrichment_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    task = service.create_from_text('寻找深圳软装设计公司，需要手机号，找 1 条有效信息。')

    completed = service.start(task.id)

    assert completed.summary.valid_contact_count == 0
    assert completed.results[0].mobile is None
    assert completed.results[0].telephone == '0755-82793362'


def test_collection_reports_phone_valid_target_and_source_exhaustion() -> None:
    service = CollectionService(
        map_provider=FakeExactCompanyMapProvider(),
        candidate_discovery_provider=FakeCompanyCandidateDiscoveryProvider(),
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    task = service.create_from_text(
        '我是做家具的，寻找深圳全案软装公司、设计公司和整装公司，需要手机号码，尽量多找。'
    )

    completed = service.start(task.id)

    assert completed.summary.target_valid_contacts == 100
    assert completed.summary.valid_contact_count == 1
    assert completed.summary.no_phone_count == 0
    assert completed.summary.source_exhausted is True
    assert completed.completion_reason == 'source_exhausted'


def test_landline_only_amap_result_does_not_count_or_deliver() -> None:
    service = CollectionService(
        map_provider=LandlineOnlyExactMapProvider(),
        candidate_discovery_provider=FakeCompanyCandidateDiscoveryProvider(),
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    task = service.create_from_text('寻找深圳软装设计公司，需要手机号码，找 1 条有效信息。')

    completed = service.start(task.id)

    assert completed.summary.valid_contact_count == 0
    assert completed.summary.no_phone_count == 1
    assert completed.completion_reason == 'source_exhausted'
    assert completed.results[0].mobile is None
    try:
        service.deliver_results(
            task.id,
            target_url='https://erp.example.test/leads',
            lead_id=completed.results[0].id,
        )
    except ValueError as exc:
        assert 'mobile' in str(exc).lower()
    else:
        raise AssertionError('landline-only Amap result must not be deliverable')


def test_phone_valid_target_stops_later_work_units() -> None:
    names = FakeCompanyCandidateDiscoveryProvider()
    amap = FakeExactCompanyMapProvider()
    service = CollectionService(
        map_provider=amap,
        candidate_discovery_provider=names,
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    task = service.create_from_text(
        '我是做家具的，寻找深圳全案软装公司、设计公司和整装公司，需要电话，找 1 条有效信息。'
    )

    completed = service.start(task.id)

    assert completed.summary.valid_contact_count == 1
    assert completed.completion_reason == 'target_reached'
    assert len(names.calls) == 1
    assert len(amap.company_calls) == 1
    assert all(unit.status == 'skipped_limit' for unit in completed.work_units[1:])


def test_phone_valid_target_completes_even_when_an_earlier_work_unit_failed() -> None:
    service = CollectionService(
        map_provider=FakeExactCompanyMapProvider(),
        candidate_discovery_provider=FirstCompanyCandidateLookupFailsProvider(),
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    task = service.create_from_text(
        '寻找深圳全案软装公司、设计公司和整装公司，需要电话，找 1 条有效信息。'
    )

    completed = service.start(task.id)

    assert any(unit.status == 'failed' for unit in completed.work_units)
    assert completed.summary.valid_contact_count == 1
    assert completed.status == 'completed'
    assert completed.completion_reason == 'target_reached'


def test_phone_valid_target_stops_later_company_lookups_in_same_unit() -> None:
    names = TwoCompanyNameDiscoveryProvider()
    amap = FakeExactCompanyMapProvider()
    service = CollectionService(
        map_provider=amap,
        candidate_discovery_provider=names,
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    task = service.create_from_text('寻找深圳软装设计公司，需要电话，找 1 条有效信息。')

    completed = service.start(task.id)

    assert completed.summary.valid_contact_count == 1
    assert completed.completion_reason == 'target_reached'
    assert amap.company_calls == [
        ('深圳市', '深圳智林装饰软装设计工程有限公司')
    ]


def test_collection_rejects_fuzzy_amap_result_for_a_company_name_candidate() -> None:
    names = FakeCompanyCandidateDiscoveryProvider()
    amap = FuzzyExactCompanyMapProvider()
    service = CollectionService(
        map_provider=amap,
        candidate_discovery_provider=names,
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    task = service.create_from_text('找深圳软装设计公司，需要电话和地址。')

    completed = service.start(task.id)

    assert completed.status == 'completed'
    assert completed.company_name_candidates
    assert completed.candidates == []
    assert completed.results == []
    assert completed.work_units[0].map_match_count == 0


def test_collection_rejects_exact_company_name_from_another_city() -> None:
    service = CollectionService(
        map_provider=CrossCityExactCompanyMapProvider(),
        candidate_discovery_provider=FakeCompanyCandidateDiscoveryProvider(),
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    task = service.create_from_text('找深圳软装设计公司，需要电话和地址。')

    completed = service.start(task.id)

    assert completed.status == 'completed'
    assert completed.candidates == []
    assert completed.results == []
    assert completed.work_units[0].map_match_count == 0


def test_collection_keeps_completed_exact_matches_when_a_later_company_lookup_times_out() -> None:
    names = TwoCompanyNameDiscoveryProvider()
    amap = PartiallyTimingOutMapProvider()
    service = CollectionService(
        map_provider=amap,
        candidate_discovery_provider=names,
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    task = service.create_from_text('找深圳软装设计公司，需要电话和地址。')

    completed = service.start(task.id)

    assert completed.status == 'completed_with_errors'
    assert [candidate.company_name for candidate in completed.candidates] == [
        '深圳智林装饰软装设计工程有限公司'
    ]
    assert completed.results[0].mobile == '17665736111'
    assert completed.work_units[0].status == 'failed'
    assert '深圳市超时软装设计有限公司' in completed.work_units[0].last_error


class FakeRuntime:
    def __init__(self) -> None:
        self.discovery = FakeKeywordDiscoveryProvider()
        self.judge = FakeRelevanceJudge()
        self.service = CollectionService(
            map_provider=self.discovery,
            relevance_judges={'doubao': self.judge},
            enrichment_gateway=FakeDoubaoGateway(),
            evidence_verifier=FakeEvidenceVerifier(),
            erp_adapter=FakeErpAdapter(),
            configured_models={'doubao'},
        )


def test_collection_keeps_map_candidate_and_enriches_relevant_company() -> None:
    runtime = FakeRuntime()
    task = runtime.service.create_from_text('深圳找软装公司，需要手机号，使用豆包')

    assert task.status == 'planned'
    assert task.work_units

    completed = runtime.service.start(task.id)

    assert completed.status == 'completed'
    assert completed.summary.candidate_count == 1
    assert completed.summary.relevant_count == 1
    assert completed.results[0].address == '深圳市南山区示例路 1 号'
    assert completed.results[0].mobile == '13800138000'


def test_map_only_collection_uses_amap_details_without_doubao_judgement_or_login() -> None:
    discovery = MapOnlyKeywordDiscoveryProvider()
    service = CollectionService(
        map_provider=discovery,
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    task = service.create_from_text('找深圳的软装设计公司，需要电话和地址。')

    completed = service.start(task.id)

    assert completed.status == 'completed'
    assert completed.relevance_decisions == {}
    assert completed.summary.candidate_count == 1
    assert completed.summary.relevant_count == 1
    assert completed.results[0].telephone == '0755-12345678'
    assert completed.results[0].address == '深圳市南山区示例路 1 号'
    assert completed.results[0].source_url == 'https://uri.amap.com/marker?pid=map-only-poi'


def test_resume_skips_succeeded_units_after_attention_pause() -> None:
    runtime = FakeRuntime()
    task = runtime.service.create_from_text('深圳和东莞找软装公司，需要手机号，使用豆包')
    second_query = (task.work_units[1].city, task.work_units[1].keyword)
    first_query = (task.work_units[0].city, task.work_units[0].keyword)
    runtime.discovery.pause_on_query = second_query

    paused = runtime.service.start(task.id)

    assert paused.status == 'needs_attention'
    assert paused.checkpoint.completed_work_unit_ids == [task.work_units[0].id]
    assert runtime.discovery.call_counts[first_query] == 1

    runtime.discovery.pause_on_query = None
    resumed = runtime.service.resume(task.id)

    assert resumed.status == 'completed'
    assert runtime.discovery.call_counts[first_query] == 1
    assert resumed.checkpoint.completed_work_unit_ids == [unit.id for unit in task.work_units]


def test_city_limit_skips_later_keywords_after_a_qualified_lead() -> None:
    runtime = FakeRuntime()
    task = runtime.service.create_from_text(
        '深圳找软装公司和设计公司，每城最多 1 家，需要手机号，使用豆包'
    )

    completed = runtime.service.start(task.id)

    assert completed.summary.contact_count == 1
    assert sum(count for (city, _keyword), count in runtime.discovery.call_counts.items() if city == '深圳市') == 1
    assert any(unit.status == 'skipped_limit' for unit in completed.work_units)


def test_city_limit_counts_unique_valid_mobile_numbers() -> None:
    runtime = FakeRuntime()
    task = runtime.service.create_from_text(
        '深圳找软装公司和设计公司，每城最多 2 家，需要手机号，使用豆包'
    )
    task.results = [
        LeadRecord(
            id='lead-first-branch',
            task_id=task.id,
            company_name='深圳佳美域装饰集团',
            city='深圳市',
            mobile='18503095715',
        ),
        LeadRecord(
            id='lead-second-branch',
            task_id=task.id,
            company_name='佳美域品牌装饰(龙岗旗舰店)',
            city='深圳市',
            mobile='18503095715',
        ),
    ]

    assert runtime.service._city_limit_reached(task, task.work_units[0]) is False


def test_city_limit_counts_distinct_mobile_numbers_for_the_same_company() -> None:
    runtime = FakeRuntime()
    task = runtime.service.create_from_text(
        '深圳找软装公司，每城最多 2 家，需要手机号，使用豆包'
    )
    task.results = [
        LeadRecord(
            id='lead-company-mobile-one',
            task_id=task.id,
            company_name='深圳双联系方式软装有限公司',
            city='深圳市',
            mobile='13800138000',
        ),
        LeadRecord(
            id='lead-company-mobile-two',
            task_id=task.id,
            company_name='深圳双联系方式软装有限公司',
            city='深圳市',
            mobile='13900139000',
        ),
    ]

    assert runtime.service._city_limit_reached(task, task.work_units[0]) is True


def test_retry_errors_reopens_city_limit_units_when_unique_limit_is_not_reached() -> None:
    runtime = FakeRuntime()
    task = runtime.service.create_from_text(
        '深圳找软装公司和设计公司，每城最多 2 家，需要手机号，使用豆包'
    )
    task.results = [
        LeadRecord(
            id='lead-first-branch',
            task_id=task.id,
            company_name='深圳佳美域装饰集团',
            city='深圳市',
            mobile='18503095715',
        ),
        LeadRecord(
            id='lead-second-branch',
            task_id=task.id,
            company_name='佳美域品牌装饰(龙岗旗舰店)',
            city='深圳市',
            mobile='18503095715',
        ),
    ]
    retried_unit = task.work_units[0]
    retried_unit.status = 'skipped_limit'
    retried_unit.last_error = 'city_limit_reached'
    for unit in task.work_units[1:]:
        unit.status = 'succeeded'
    task.status = 'completed'

    completed = runtime.service.retry_errors(task.id)

    assert retried_unit.status == 'succeeded'
    assert (retried_unit.city, retried_unit.keyword) in runtime.discovery.calls
    assert completed.summary.valid_contact_count == 2


def test_verified_auto_delivery_runs_only_after_independent_evidence() -> None:
    erp = FakeErpAdapter()
    runtime = FakeRuntime()
    runtime.service = CollectionService(
        map_provider=runtime.discovery,
        relevance_judges={'doubao': runtime.judge},
        enrichment_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(
            EvidenceResult(
                contact_verification_status='verified_public_web',
                field_evidence={
                    'mobile': EvidenceValue(value='13800138000', status='verified')
                },
            )
        ),
        erp_adapter=erp,
        configured_models={'doubao'},
    )
    task = runtime.service.create_from_text(
        '深圳找软装公司，需要手机号，使用豆包',
        verified_auto_deliver=True,
    )

    completed = runtime.service.start(task.id)

    assert len(erp.payloads) == 1
    assert completed.results[0].delivery_status == 'delivered'
    assert completed.results[0].delivery_at is not None


def test_verified_auto_delivery_requires_valid_amap_mobile() -> None:
    class EmailOnlyEnrichmentGateway:
        def enrich_company(self, **_kwargs) -> DoubaoEnrichment:
            return DoubaoEnrichment(email='sales@example.test')

    erp = FakeErpAdapter()
    service = CollectionService(
        map_provider=MapOnlyKeywordDiscoveryProvider(),
        relevance_judges={},
        enrichment_gateway=EmailOnlyEnrichmentGateway(),
        evidence_verifier=FakeEvidenceVerifier(
            EvidenceResult(
                contact_verification_status='verified_public_web',
                field_evidence={'email': EvidenceValue(value='sales@example.test', status='verified')},
            )
        ),
        erp_adapter=erp,
        configured_models=set(),
    )
    task = service.create_from_text(
        '深圳找软装公司，需要邮箱。',
        verified_auto_deliver=True,
    )

    completed = service.start(task.id)

    assert completed.results[0].mobile is None
    assert erp.payloads == []


def test_auto_delivery_requires_field_level_evidence_for_requested_contact() -> None:
    erp = FakeErpAdapter()
    runtime = FakeRuntime()
    runtime.service = CollectionService(
        map_provider=runtime.discovery,
        relevance_judges={'doubao': runtime.judge},
        enrichment_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(
            EvidenceResult(contact_verification_status='verified_public_web')
        ),
        erp_adapter=erp,
        configured_models={'doubao'},
    )
    task = runtime.service.create_from_text(
        '深圳找软装公司，需要手机号，使用豆包',
        verified_auto_deliver=True,
    )

    completed = runtime.service.start(task.id)

    assert erp.payloads == []
    assert completed.results[0].delivery_status == 'display_only'


def test_collection_calls_public_evidence_verifier_before_auto_delivery() -> None:
    erp = FakeErpAdapter()
    public_evidence = FakePublicEvidenceVerifier()
    runtime = FakeRuntime()
    runtime.service = CollectionService(
        map_provider=runtime.discovery,
        relevance_judges={'doubao': runtime.judge},
        enrichment_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        public_evidence_verifier=public_evidence,
        erp_adapter=erp,
        configured_models={'doubao'},
    )
    task = runtime.service.create_from_text(
        '深圳找软装公司，需要手机号，使用豆包',
        verified_auto_deliver=True,
    )

    completed = runtime.service.start(task.id)

    assert public_evidence.calls[0]['mobile'] == '13800138000'
    assert len(erp.payloads) == 1
    assert completed.results[0].field_evidence['mobile'].status == 'verified'


def test_failed_enrichment_is_retryable_without_losing_candidate() -> None:
    enrichment = FlakyEnrichmentGateway()
    discovery = FakeKeywordDiscoveryProvider()
    service = CollectionService(
        map_provider=discovery,
        relevance_judges={'doubao': FakeRelevanceJudge()},
        enrichment_gateway=enrichment,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models={'doubao'},
    )
    task = service.create_from_text('深圳找软装公司，需要手机号，使用豆包')

    failed = service.start(task.id)
    failed_snapshot = failed.model_copy(deep=True)
    retried = service.retry_errors(task.id)

    assert failed_snapshot.status == 'completed_with_errors'
    assert len(failed_snapshot.candidates) == 1
    assert retried.status == 'completed'
    assert enrichment.calls == 2
    assert len(retried.results) == 1


def test_duplicate_company_merges_sources_and_relevance_decisions() -> None:
    discovery = MultiSourceKeywordDiscoveryProvider()
    service = CollectionService(
        map_provider=discovery,
        relevance_judges={'doubao': RelevantJudge()},
        enrichment_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models={'doubao'},
    )
    task = service.create_from_text(
        '深圳找软装公司和设计公司，需要手机号，使用豆包'
    )

    completed = service.start(task.id)

    assert completed.status == 'completed'
    assert len(completed.candidates) == 1
    assert completed.candidates[0].source_urls == [
        'https://amap.example.test/poi/1',
        'https://amap.example.test/poi/2',
    ]
    assert completed.candidates[0].source_metadata['matched_keywords'] == [
        '软装公司',
        '设计公司',
    ]
    decisions = completed.relevance_decisions[completed.candidates[0].candidate_id]
    assert len(decisions) == 2
    assert {decision.keyword for decision in decisions} == {'软装公司', '设计公司'}


def test_collection_delivery_ledger_prevents_duplicate_after_service_reload() -> None:
    from backend.app.db import Base, create_database
    from backend.app.storage.repositories import CollectionRepository

    engine, session_factory = create_database('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    repository = CollectionRepository(session_factory)
    evidence = EvidenceResult(
        company_name_verification_status='verified_map',
        contact_verification_status='verified_public_web',
        field_evidence={
            'mobile': EvidenceValue(value='13800138000', status='verified')
        },
    )

    first_erp = FakeErpAdapter()
    first_service = CollectionService(
        map_provider=FakeKeywordDiscoveryProvider(),
        relevance_judges={'doubao': FakeRelevanceJudge()},
        enrichment_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(evidence),
        erp_adapter=first_erp,
        configured_models={'doubao'},
        repository=repository,
    )
    first = first_service.create_from_text(
        '深圳找软装公司，需要手机号，使用豆包',
        verified_auto_deliver=True,
    )
    first_result = first_service.start(first.id)

    second_erp = FakeErpAdapter()
    second_service = CollectionService(
        map_provider=FakeKeywordDiscoveryProvider(),
        relevance_judges={'doubao': FakeRelevanceJudge()},
        enrichment_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(evidence),
        erp_adapter=second_erp,
        configured_models={'doubao'},
        repository=repository,
    )
    second = second_service.create_from_text(
        '深圳找软装公司，需要手机号，使用豆包',
        verified_auto_deliver=True,
    )
    second_result = second_service.start(second.id)

    assert first_result.results[0].delivery_status == 'delivered'
    assert second_result.results[0].delivery_status == 'duplicate'
    assert second_erp.payloads == []


def test_verified_auto_delivery_blocks_mobile_delivered_with_legacy_fingerprint() -> None:
    erp = FakeErpAdapter()
    service = CollectionService(
        map_provider=FakeKeywordDiscoveryProvider(),
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        erp_adapter=erp,
        configured_models=set(),
    )
    task = service.create_from_text(
        '深圳找软装公司，需要手机号。',
        verified_auto_deliver=True,
    )
    task.results = [
        LeadRecord(
            id='lead-old-store', task_id=task.id, city='深圳市',
            company_name='深圳示例装饰南山店', mobile='13800138000',
            delivery_status='delivered', delivery_fingerprint='legacy-payload-fingerprint',
        )
    ]
    new_lead = LeadRecord(
        id='lead-new-store', task_id=task.id, city='深圳市',
        company_name='深圳示例装饰福田店', mobile='13800138000',
        contact_verification_status='verified',
        source_metadata={
            'detail_verified': True,
            'detail_raw_text': '深圳示例装饰福田店 13800138000',
        },
    )
    task.results.append(new_lead)

    result = service._deliver_with_adapter(task, new_lead, erp, manual=False)

    assert result is not None
    assert result.status == 'duplicate'
    assert new_lead.delivery_status == 'duplicate'
    assert erp.payloads == []


def test_collection_reload_pauses_task_left_running_without_a_worker() -> None:
    from backend.app.db import Base, create_database
    from backend.app.storage.repositories import CollectionRepository

    engine, session_factory = create_database('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    repository = CollectionRepository(session_factory)
    first_service = CollectionService(
        map_provider=FakeKeywordDiscoveryProvider(),
        relevance_judges={'doubao': FakeRelevanceJudge()},
        enrichment_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models={'doubao'},
        repository=repository,
    )
    task = first_service.create_from_text('深圳找软装公司，需要手机号，使用豆包')
    task.status = 'running'
    task.work_units[0].status = 'running'
    task.checkpoint.current_stage = 'running'
    task.checkpoint.current_work_unit_id = task.work_units[0].id
    repository.save(task)

    reloaded_service = CollectionService(
        map_provider=FakeKeywordDiscoveryProvider(),
        relevance_judges={'doubao': FakeRelevanceJudge()},
        enrichment_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models={'doubao'},
        repository=repository,
    )

    restored = reloaded_service.get_task(task.id)

    assert restored.status == 'paused'
    assert restored.work_units[0].status == 'paused'
    assert restored.checkpoint.current_stage == 'paused'
    assert restored.checkpoint.browser_state == 'stopped'


def test_collection_reload_normalizes_stale_running_unit_on_a_paused_task() -> None:
    from backend.app.db import Base, create_database
    from backend.app.storage.repositories import CollectionRepository

    engine, session_factory = create_database('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    repository = CollectionRepository(session_factory)
    first_service = CollectionService(
        map_provider=FakeKeywordDiscoveryProvider(),
        relevance_judges={'doubao': FakeRelevanceJudge()},
        enrichment_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models={'doubao'},
        repository=repository,
    )
    task = first_service.create_from_text('\u6df1\u5733\u5e02\u88c5\u4fee\u516c\u53f8\uff0c\u9700\u8981\u624b\u673a\u53f7\uff0c\u4f7f\u7528\u8c46\u5305')
    task.status = 'paused'
    task.work_units[0].status = 'running'
    repository.save(task)

    reloaded_service = CollectionService(
        map_provider=FakeKeywordDiscoveryProvider(),
        relevance_judges={'doubao': FakeRelevanceJudge()},
        enrichment_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models={'doubao'},
        repository=repository,
    )

    restored = reloaded_service.get_task(task.id)

    assert restored.status == 'paused'
    assert restored.work_units[0].status == 'paused'


def test_collection_reload_corrects_target_reached_task_with_stale_error_status() -> None:
    from backend.app.db import Base, create_database
    from backend.app.storage.repositories import CollectionRepository

    engine, session_factory = create_database('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    repository = CollectionRepository(session_factory)
    first_service = CollectionService(
        map_provider=FakeExactCompanyMapProvider(),
        candidate_discovery_provider=FakeCompanyCandidateDiscoveryProvider(),
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
        repository=repository,
    )
    task = first_service.create_from_text(
        '寻找深圳全案软装公司，需要电话，找 1 条有效信息。'
    )
    completed = first_service.start(task.id)
    completed.status = 'completed_with_errors'
    completed.completion_reason = 'completed_with_errors'
    completed.checkpoint.current_stage = 'completed_with_errors'
    completed.work_units[0].status = 'failed'
    repository.save(completed)

    reloaded_service = CollectionService(
        map_provider=FakeExactCompanyMapProvider(),
        candidate_discovery_provider=FakeCompanyCandidateDiscoveryProvider(),
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
        repository=repository,
    )

    restored = reloaded_service.get_task(task.id)

    assert restored.status == 'completed'
    assert restored.completion_reason == 'target_reached'
    assert restored.checkpoint.current_stage == 'completed'


def test_collection_reload_recomputes_legacy_landline_summary() -> None:
    from backend.app.db import Base, create_database
    from backend.app.storage.repositories import CollectionRepository

    engine, session_factory = create_database('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    repository = CollectionRepository(session_factory)
    first_service = CollectionService(
        map_provider=FakeKeywordDiscoveryProvider(),
        relevance_judges={'doubao': FakeRelevanceJudge()},
        enrichment_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models={'doubao'},
        repository=repository,
    )
    task = first_service.create_from_text('深圳找软装公司，需要手机号，使用豆包')
    task.candidates = [
        MapPoiCandidate(
            candidate_id='legacy-landline',
            company_name='深圳市旧摘要软装有限公司',
            city='深圳市',
            telephone='0755-82793362',
        )
    ]
    task.results = [
        LeadRecord(
            id='lead-legacy-landline',
            task_id=task.id,
            company_name='深圳市旧摘要软装有限公司',
            city='深圳市',
            telephone='0755-82793362',
        )
    ]
    task.summary = CollectionSummary(
        candidate_count=1,
        valid_contact_count=1,
        no_phone_count=0,
    )
    repository.save(task)

    reloaded_service = CollectionService(
        map_provider=FakeKeywordDiscoveryProvider(),
        relevance_judges={'doubao': FakeRelevanceJudge()},
        enrichment_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models={'doubao'},
        repository=repository,
    )

    restored = reloaded_service.get_task(task.id)

    assert restored.summary.valid_contact_count == 0
    assert restored.summary.no_phone_count == 1
    persisted = repository.get(task.id)
    assert persisted is not None
    assert persisted.summary.valid_contact_count == 0
    assert persisted.summary.no_phone_count == 1


def test_collection_reload_moves_legacy_mobile_out_of_telephone() -> None:
    from backend.app.db import Base, create_database
    from backend.app.storage.repositories import CollectionRepository

    engine, session_factory = create_database('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    repository = CollectionRepository(session_factory)
    first_service = CollectionService(
        map_provider=FakeKeywordDiscoveryProvider(),
        relevance_judges={'doubao': FakeRelevanceJudge()},
        enrichment_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models={'doubao'},
        repository=repository,
    )
    task = first_service.create_from_text('深圳找软装公司，需要手机号，使用豆包')
    task.results = [
        LeadRecord(
            id='lead-legacy-mobile',
            task_id=task.id,
            company_name='深圳市旧手机号软装有限公司',
            city='深圳市',
            telephone='13800138000',
        )
    ]
    repository.save(task)

    reloaded_service = CollectionService(
        map_provider=FakeKeywordDiscoveryProvider(),
        relevance_judges={'doubao': FakeRelevanceJudge()},
        enrichment_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models={'doubao'},
        repository=repository,
    )

    restored = reloaded_service.get_task(task.id)

    assert restored.results[0].mobile == '13800138000'
    assert restored.results[0].telephone is None


def test_collection_reload_clears_invalid_legacy_mobile_field() -> None:
    from backend.app.db import Base, create_database
    from backend.app.storage.repositories import CollectionRepository

    engine, session_factory = create_database('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    repository = CollectionRepository(session_factory)
    first_service = CollectionService(
        map_provider=FakeKeywordDiscoveryProvider(),
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
        repository=repository,
    )
    task = first_service.create_from_text('深圳找软装公司，需要手机号')
    task.results = [
        LeadRecord(
            id='lead-invalid-mobile',
            task_id=task.id,
            company_name='深圳市旧数据软装有限公司',
            city='深圳市',
            mobile='0755-82793362',
        )
    ]
    repository.save(task)

    reloaded_service = CollectionService(
        map_provider=FakeKeywordDiscoveryProvider(),
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
        repository=repository,
    )

    restored = reloaded_service.get_task(task.id)

    assert restored.results[0].mobile is None


def test_async_collection_can_pause_between_work_units() -> None:
    discovery = BlockingKeywordDiscoveryProvider()
    service = CollectionService(
        map_provider=discovery,
        relevance_judges={'doubao': FakeRelevanceJudge()},
        enrichment_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        erp_adapter=FakeErpAdapter(),
        configured_models={'doubao'},
    )
    task = service.create_from_text('深圳和东莞找软装公司，需要手机号，使用豆包')

    queued = service.start_async(task.id)
    assert queued.status == 'queued'
    assert discovery.started.wait(timeout=1)

    paused = service.pause(task.id)
    discovery.release.set()
    settled = service.wait(task.id, timeout=2)

    assert paused.status == 'paused'
    assert settled.status == 'paused'
    assert len(discovery.calls) == 1


def test_async_collection_can_be_cancelled_and_cannot_resume() -> None:
    discovery = BlockingKeywordDiscoveryProvider()
    service = CollectionService(
        map_provider=discovery,
        relevance_judges={'doubao': FakeRelevanceJudge()},
        enrichment_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models={'doubao'},
    )
    task = service.create_from_text('深圳找软装公司，需要手机号码。')

    service.start_async(task.id)
    assert discovery.started.wait(timeout=1)
    cancelled = service.cancel(task.id)
    discovery.release.set()
    settled = service.wait(task.id, timeout=2)

    assert cancelled.status == 'cancelled'
    assert settled.status == 'cancelled'
    assert service.resume(task.id).status == 'cancelled'


def test_mobile_is_valid_only_when_captured_from_amap_detail_text() -> None:
    runtime = FakeRuntime()
    task = runtime.service.create_from_text('深圳找软装公司，需要手机号码。')
    task.results = [
        LeadRecord(
            id='lead-public-mobile',
            task_id=task.id,
            company_name='深圳示例软装有限公司',
            city='深圳市',
            mobile='13800138000',
            source_metadata={'detail_verified': False},
        ),
    ]

    assert runtime.service._unique_phone_valid_leads(task) == []


def test_non_continuous_collection_pauses_after_one_work_unit() -> None:
    runtime = FakeRuntime()
    task = runtime.service.create_from_text(
        '深圳和东莞找软装公司，需要手机号，使用豆包',
        continuous_mode=False,
    )

    paused = runtime.service.start(task.id)

    assert paused.status == 'paused'
    assert paused.summary.completed_work_units == 1
    assert len(runtime.discovery.calls) == 1

    completed = runtime.service.resume(task.id)

    assert completed.status == 'completed'
    assert completed.summary.completed_work_units == 2


def test_auto_delivery_keeps_captured_contact_display_only() -> None:
    erp = FakeErpAdapter()
    runtime = FakeRuntime()
    runtime.service = CollectionService(
        map_provider=runtime.discovery,
        relevance_judges={'doubao': runtime.judge},
        enrichment_gateway=FakeDoubaoGateway(),
        evidence_verifier=FakeEvidenceVerifier(),
        erp_adapter=erp,
        configured_models={'doubao'},
    )
    task = runtime.service.create_from_text(
        '深圳找软装公司，需要手机号，使用豆包',
        auto_deliver=True,
    )

    completed = runtime.service.start(task.id)

    assert erp.payloads == []
    assert completed.results[0].delivery_status == 'display_only'


def test_auto_delivery_accepts_mobile_verified_on_amap_detail() -> None:
    erp = FakeErpAdapter()
    runtime = FakeRuntime()
    service = CollectionService(
        map_provider=runtime.discovery,
        relevance_judges={'doubao': runtime.judge},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        erp_adapter=erp,
        configured_models={'doubao'},
    )
    task = service.create_from_text(
        '深圳找软装公司，需要手机号，使用豆包',
        verified_auto_deliver=True,
    )
    lead = LeadRecord(
        id='amap-detail-mobile',
        task_id=task.id,
        company_name='深圳示例软装有限公司',
        city='深圳市',
        mobile='13800138000',
        contact_verification_status='captured',
        source_metadata={
            'provider': 'amap_web',
            'detail_verified': True,
            'detail_raw_text': '深圳示例软装有限公司 电话：13800138000',
        },
        field_evidence={
            'mobile': EvidenceValue(value='13800138000', status='verified'),
        },
    )

    result = service._auto_deliver(task, lead)

    assert result is not None
    assert result.status == 'delivered'
    assert len(erp.payloads) == 1


def test_refresh_amap_details_extracts_mobile_and_delivers_idempotently() -> None:
    erp = FakeErpAdapter()
    provider = RefreshExactMobileMapProvider()
    service = CollectionService(
        map_provider=provider,
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(
            EvidenceResult(
                contact_verification_status='verified_map',
                field_evidence={
                    'mobile': EvidenceValue(value='13800138000', status='verified')
                },
            )
        ),
        erp_adapter=erp,
        manual_delivery_adapter_factory=lambda _url, _token: erp,
        configured_models=set(),
    )
    task = service.create_from_text('深圳找软装公司，需要手机号。')
    task.candidates = [
        MapPoiCandidate(
            candidate_id='old-poi',
            company_name='深圳示例软装公司',
            city='深圳市',
            source_url='https://www.amap.com/place/old-poi',
            source_metadata={'provider': 'amap_web', 'detail_verified': True},
        )
    ]
    task.results = [
        LeadRecord(
            id='lead-old-poi',
            task_id=task.id,
            company_name='深圳示例软装公司',
            city='深圳市',
            source_metadata={'provider': 'amap_web', 'detail_verified': True},
        )
    ]
    service._persist(task)

    first = service.refresh_amap_contacts_and_deliver(
        task.id,
        target_url='https://erp.example.test/leads',
    )
    assert first.results[0].mobile == '13800138000'
    assert first.results[0].telephone is None
    assert first.results[0].delivery_status == 'delivered'
    second = service.refresh_amap_contacts_and_deliver(
        task.id,
        target_url='https://erp.example.test/leads',
    )

    assert second.results[0].delivery_status == 'duplicate'
    assert len(erp.payloads) == 1


def test_refresh_amap_details_never_delivers_landline() -> None:
    erp = FakeErpAdapter()
    service = CollectionService(
        map_provider=RefreshLandlineMapProvider(),
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        erp_adapter=erp,
        manual_delivery_adapter_factory=lambda _url, _token: erp,
        configured_models=set(),
    )
    task = service.create_from_text('深圳找软装公司，需要手机号。')
    task.candidates = [
        MapPoiCandidate(
            candidate_id='old-landline',
            company_name='深圳座机软装公司',
            city='深圳市',
            source_metadata={'provider': 'amap_web', 'detail_verified': True},
        )
    ]
    result = service.refresh_amap_contacts_and_deliver(
        task.id,
        target_url='https://erp.example.test/leads',
    )

    assert result.results[0].mobile is None
    assert result.results[0].telephone == '0755-82793362'
    assert erp.payloads == []


def test_refresh_amap_details_pauses_for_challenge() -> None:
    service = CollectionService(
        map_provider=RefreshPausedMapProvider(),
        relevance_judges={},
        enrichment_gateway=None,
        evidence_verifier=FakeEvidenceVerifier(),
        configured_models=set(),
    )
    task = service.create_from_text('深圳找软装公司，需要手机号。')
    task.candidates = [
        MapPoiCandidate(
            candidate_id='old-paused',
            company_name='深圳待验证软装公司',
            city='深圳市',
            source_metadata={'provider': 'amap_web', 'detail_verified': True},
        )
    ]
    result = service.refresh_amap_contacts_and_deliver(
        task.id,
        target_url='https://erp.example.test/leads',
    )

    assert result.status == 'needs_attention'
    assert result.checkpoint.browser_state == 'waiting_for_challenge'
