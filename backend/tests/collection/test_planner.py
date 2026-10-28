from dataclasses import replace

from backend.app.collection.intent import parse_collection_intent
from backend.app.collection.planner import build_work_units, contact_requirement_satisfied
from backend.app.domain.models import LeadRecord


def test_plan_is_city_keyword_matrix_with_stable_deduplicated_ids():
    intent = parse_collection_intent(
        '深圳和东莞找软装公司，每城最多 2 家。',
        configured_models={'doubao'},
    )

    units = build_work_units(intent, provider_id='amap_web')
    second_units = build_work_units(intent, provider_id='amap_web')

    assert len(units) == len({unit.id for unit in units})
    assert [unit.id for unit in units] == [unit.id for unit in second_units]
    assert {(unit.city, unit.keyword) for unit in units} == {
        ('深圳市', '软装公司'),
        ('东莞市', '软装公司'),
    }
    assert all(unit.status == 'planned' for unit in units)
    assert all(unit.limit_per_city == 2 for unit in units)


def test_nationwide_intent_expands_to_all_configured_cities():
    intent = parse_collection_intent(
        '全国找软装公司。',
        configured_models={'doubao'},
    )

    units = build_work_units(intent)

    assert len(units) > 100
    assert {unit.city for unit in units}
    assert all(unit.keyword == '软装公司' for unit in units)


def test_contact_requirement_supports_any_and_all():
    intent = parse_collection_intent(
        '深圳找软装公司。',
        configured_models={'doubao'},
    )
    lead = LeadRecord(
        id='lead-1',
        task_id='task-1',
        city='深圳市',
        company_name='深圳示例公司',
        mobile='13800138000',
    )
    any_intent = replace(intent, contact_match='any')
    all_intent = replace(
        intent,
        required_contacts=['mobile', 'email'],
        contact_match='all',
    )

    assert contact_requirement_satisfied(lead, any_intent) is True
    assert contact_requirement_satisfied(lead, all_intent) is False
