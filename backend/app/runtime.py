from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.app.browser.lifecycle import DedicatedBrowser
from backend.app.collection.service import CollectionService
from backend.app.config import RuntimeSettings
from backend.app.providers.amap_api import AmapApiProvider
from backend.app.providers.amap_web import AmapWebProvider
from backend.app.providers.doubao_web import DoubaoWebGateway
from backend.app.providers.erp import ErpHttpAdapter
from backend.app.providers.fake import (
    FakeDoubaoGateway,
    FakeMapDiscoveryProvider,
)
from backend.app.providers.kuai_openai import KuaiOpenAiRelevanceJudge
from backend.app.providers.map_evidence import MapEvidenceVerifier
from backend.app.providers.public_web import (
    PublicCompanyNameDiscoveryProvider,
    PublicEvidenceVerifier,
)
from backend.app.services.search_task import CompanySearchService


@dataclass
class RuntimeComponents:
    service: CompanySearchService
    collection_service: CollectionService
    browsers: list[DedicatedBrowser]

    def close(self) -> None:
        for browser in self.browsers:
            browser.close()


def build_runtime_components(
    settings: RuntimeSettings,
    *,
    repository=None,
    collection_repository=None,
) -> RuntimeComponents:
    profile_root = Path(settings.browser_profile_dir)
    map_browser = DedicatedBrowser(
        port=settings.amap_cdp_port,
        user_data_dir=profile_root / 'amap',
        chrome_path=settings.chrome_path,
    )
    doubao_browser = DedicatedBrowser(
        port=settings.doubao_cdp_port,
        user_data_dir=profile_root / 'doubao',
        chrome_path=settings.chrome_path,
    )
    map_providers = {
        'fake_map': FakeMapDiscoveryProvider(),
        'amap_web': AmapWebProvider(browser=map_browser),
        'amap_api': AmapApiProvider(
            api_key=settings.amap_api_key,
            base_url=settings.amap_base_url,
            max_pages=settings.amap_max_pages,
            request_interval_seconds=settings.amap_request_interval_seconds,
            retry_limit=settings.amap_retry_limit,
        ),
    }
    doubao_gateways = {
        'fake_doubao': FakeDoubaoGateway(),
        'doubao_web': DoubaoWebGateway(browser=doubao_browser, chat_url=settings.doubao_url),
    }
    erp_adapter = ErpHttpAdapter(target_url=settings.erp_url, bearer_token=settings.erp_bearer_token)
    kuai_judge = KuaiOpenAiRelevanceJudge(
        base_url=settings.kuai_api_base_url,
        api_key=settings.kuai_api_key,
        model=settings.kuai_model,
    )
    service = CompanySearchService(
        map_provider=map_providers['amap_web'],
        map_providers=map_providers,
        doubao_gateway=doubao_gateways['doubao_web'],
        doubao_gateways=doubao_gateways,
        evidence_verifier=MapEvidenceVerifier(),
        public_evidence_verifier=PublicEvidenceVerifier(),
        erp_adapter=erp_adapter,
        repository=repository,
    )
    collection_service = CollectionService(
        map_provider=map_providers['amap_web'],
        candidate_discovery_provider=PublicCompanyNameDiscoveryProvider(max_search_pages=5),
        relevance_judges={kuai_judge.id: kuai_judge} if kuai_judge.configured else {},
        enrichment_gateway=None,
        evidence_verifier=MapEvidenceVerifier(),
        public_evidence_verifier=PublicEvidenceVerifier(),
        erp_adapter=erp_adapter,
        configured_models={kuai_judge.id} if kuai_judge.configured else set(),
        repository=collection_repository,
    )
    return RuntimeComponents(
        service=service,
        collection_service=collection_service,
        browsers=[map_browser, doubao_browser],
    )
