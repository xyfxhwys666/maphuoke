from backend.app.domain.models import MapPoiCandidate
from backend.app.providers.map_evidence import MapEvidenceVerifier, attach_map_snapshot, capture_map_snapshot
from backend.app.providers.public_web import PublicEvidenceVerifier


def candidate_with_snapshot(text: str) -> MapPoiCandidate:
    return MapPoiCandidate(
        candidate_id='poi-1',
        company_name='深圳示例科技有限公司',
        city='深圳市',
        address='广东省深圳市南山区示例路 1 号',
        source_url='https://uri.amap.com/marker?pid=poi-1',
        poi_id='poi-1',
        raw_text=text,
        source_metadata={'provider': 'amap_web'},
    )


def test_map_snapshot_preserves_visible_text_and_identity_metadata() -> None:
    snapshot = capture_map_snapshot(candidate_with_snapshot('深圳示例科技有限公司\n地址：示例路 1 号'))

    assert snapshot.provider == 'amap_web'
    assert snapshot.poi_id == 'poi-1'
    assert snapshot.source_url == 'https://uri.amap.com/marker?pid=poi-1'
    assert snapshot.visible_text == '深圳示例科技有限公司\n地址：示例路 1 号'
    assert snapshot.snapshot_id


def test_attach_map_snapshot_links_snapshot_id_to_candidate_metadata() -> None:
    candidate = candidate_with_snapshot('深圳示例科技有限公司')

    linked = attach_map_snapshot(candidate)

    assert linked.evidence_snapshot_id
    assert linked.source_metadata['evidence_snapshot_id'] == linked.evidence_snapshot_id


def test_map_verifier_requires_company_and_contact_in_same_visible_evidence() -> None:
    verifier = MapEvidenceVerifier()
    candidate = candidate_with_snapshot('深圳示例科技有限公司\n电话：13800138000')

    result = verifier.verify(
        candidate,
        expected_company_name='深圳示例科技有限公司',
        expected_contact='13800138000',
    )

    assert result.company_name_verification_status == 'verified_map'
    assert result.contact_verification_status == 'verified_map'
    assert result.source_urls == [candidate.source_url]


def test_marker_url_alone_cannot_verify_mobile_and_name_mismatch_is_rejected() -> None:
    verifier = MapEvidenceVerifier()
    candidate = candidate_with_snapshot('深圳示例科技有限公司\n地址：示例路 1 号')

    result = verifier.verify(
        candidate,
        expected_company_name='深圳示例科技有限公司',
        expected_contact='13800138000',
    )
    mismatch = verifier.verify(
        candidate,
        expected_company_name='另一家科技有限公司',
        expected_contact=None,
    )

    assert result.contact_verification_status == 'captured'
    assert mismatch.company_name_verification_status == 'rejected'
    assert mismatch.contact_verification_status == 'rejected_mismatch'


def test_public_evidence_requires_company_and_contact_in_fetched_page() -> None:
    class Response:
        url = 'https://example.com/company'
        text = '<html><body>深圳示例科技有限公司 联系电话：13800138000</body></html>'

        def raise_for_status(self) -> None:
            return None

    class Client:
        def get(self, *_args, **_kwargs):
            return Response()

    verifier = PublicEvidenceVerifier(client=Client())

    result = verifier.verify_contact(
        company_name='深圳示例科技有限公司',
        mobile='13800138000',
        source_urls=['https://example.com/company'],
    )

    assert result.contact_verification_status == 'verified_public_web'
    assert result.source_urls == ['https://example.com/company']
    assert '13800138000' in result.quotes[0]


def test_public_evidence_discovers_independent_contact_page_when_source_lacks_contact() -> None:
    class Response:
        def __init__(self, url: str, text: str) -> None:
            self.url = url
            self.text = text

        def raise_for_status(self) -> None:
            return None

    class Client:
        def get(self, url, *, params=None, **_kwargs):
            if url == 'https://amap.example/poi':
                return Response(url, '<html><body>深圳示例科技有限公司</body></html>')
            if url == 'https://search.example/':
                assert params == {'q': '深圳示例科技有限公司 联系方式'}
                return Response(url, '''
                    <li class="b_algo"><h2><a href="https://company.example/contact">联系我们</a></h2>
                    <div>深圳示例科技有限公司联系方式</div></li>
                ''')
            if url == 'https://company.example/contact':
                return Response(url, '<html><body>深圳示例科技有限公司 电话：13800138000</body></html>')
            raise AssertionError(f'unexpected URL: {url}')

    verifier = PublicEvidenceVerifier(
        client=Client(),
        search_endpoints=(('https://search.example/', 'q'),),
    )

    result = verifier.verify_contact(
        company_name='深圳示例科技有限公司',
        mobile='13800138000',
        source_urls=['https://amap.example/poi'],
    )

    assert result.contact_verification_status == 'verified_public_web'
    assert result.source_urls == ['https://company.example/contact']


def test_public_evidence_discovery_rejects_private_candidate_urls() -> None:
    class Response:
        url = 'https://search.example/'
        text = '''
            <li class="b_algo"><h2><a href="http://127.0.0.1/private">内部页面</a></h2></li>
            <li class="b_algo"><h2><a href="https://company.example/contact">公开页面</a></h2></li>
        '''

        def raise_for_status(self) -> None:
            return None

    class Client:
        def get(self, *_args, **_kwargs):
            return Response()

    verifier = PublicEvidenceVerifier(
        client=Client(),
        search_endpoints=(('https://search.example/', 'q'),),
    )

    assert verifier._discover_evidence_urls('深圳示例科技有限公司') == [
        'https://company.example/contact',
    ]
