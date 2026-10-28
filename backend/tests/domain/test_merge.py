from backend.app.domain import merge as merge_module
from backend.app.domain.merge import merge_candidate_with_enrichment
from backend.app.domain.models import DoubaoEnrichment, MapPoiCandidate


def test_empty_enrichment_preserves_map_fields() -> None:
    candidate = MapPoiCandidate(
        candidate_id='poi-1',
        company_name='深圳示例科技有限公司',
        city='深圳市',
        address='广东省深圳市南山区示例路 1 号',
        telephone='0755-12345678',
        source_url='https://uri.amap.com/marker?id=poi-1',
        discovery_channel='amap_web',
    )

    lead = merge_candidate_with_enrichment(
        candidate,
        DoubaoEnrichment(),
        task_id='task-1',
    )

    assert lead.address == '广东省深圳市南山区示例路 1 号'
    assert lead.telephone == '0755-12345678'
    assert lead.source_urls == ['https://uri.amap.com/marker?id=poi-1']


def test_non_empty_enrichment_adds_contacts_without_replacing_map_identity() -> None:
    candidate = MapPoiCandidate(
        candidate_id='poi-2',
        company_name='深圳示例科技有限公司',
        city='深圳市',
        address='地图地址',
        source_url='https://uri.amap.com/marker?id=poi-2',
        discovery_channel='amap_web',
    )
    enrichment = DoubaoEnrichment(
        company_name='豆包返回的别名',
        mobile='13800138000',
        email='sales@example.com',
        wechat='example_sales',
        contact_person_name='张三',
        source_urls=['https://example.com/company'],
        evidence_quotes=['联系电话：13800138000'],
    )

    lead = merge_candidate_with_enrichment(candidate, enrichment, task_id='task-1')

    assert lead.company_name == '深圳示例科技有限公司'
    assert lead.address == '地图地址'
    assert lead.mobile == '13800138000'
    assert lead.source_urls == [
        'https://uri.amap.com/marker?id=poi-2',
        'https://example.com/company',
    ]
    assert lead.field_evidence['email'].status == 'source_backed'
    assert lead.field_evidence['wechat'].status == 'source_backed'
    assert lead.field_evidence['contact_person_name'].status == 'source_backed'


def test_merge_map_candidate_keeps_stronger_fields_and_accumulates_sources() -> None:
    current = MapPoiCandidate(
        candidate_id='poi-1',
        company_name='深圳示例科技有限公司',
        city='深圳市',
        address='地图地址',
        source_url='https://amap.example/one',
        source_urls=['https://amap.example/one'],
        source_metadata={'matched_keywords': ['软装公司']},
    )
    incoming = MapPoiCandidate(
        candidate_id='poi-2',
        company_name='深圳示例科技有限公司',
        city='深圳市',
        telephone='0755-12345678',
        source_url='https://amap.example/two',
        source_urls=['https://amap.example/two'],
        source_metadata={'matched_keywords': ['全案软装公司']},
    )

    merged = merge_module.merge_map_candidate(current, incoming)

    assert merged is current
    assert current.address == '地图地址'
    assert current.telephone == '0755-12345678'
    assert current.source_urls == ['https://amap.example/one', 'https://amap.example/two']
    assert current.source_metadata['matched_keywords'] == ['软装公司', '全案软装公司']
