from backend.app.collection.intent import parse_collection_intent


def test_natural_language_defaults_to_tier3_plus_and_expands_residential_keywords():
    intent = parse_collection_intent(
        '我是做家装的，寻找全国三线及以上城市的全案软装公司，需要手机号，尽量多找一些。',
        configured_models={'doubao'},
    )

    assert intent.all_cities is True
    assert intent.cities == []
    assert '软装设计' in intent.keywords
    assert '别墅软装设计公司' in intent.keywords
    assert intent.required_contacts == ['mobile']
    assert intent.contact_match == 'all'
    assert intent.limit_per_city is None


def test_explicit_city_contacts_all_and_quantity_are_parsed():
    intent = parse_collection_intent(
        '找深圳、东莞的别墅设计公司，手机号和邮箱都要，每城最多 12 家。',
        configured_models={'doubao', 'deepseek'},
    )

    assert intent.cities == ['深圳市', '东莞市']
    assert intent.all_cities is False
    assert intent.required_contacts == ['mobile', 'email']
    assert intent.contact_match == 'all'
    assert intent.limit_per_city == 12


def test_unrelated_model_keywords_are_removed_and_models_are_configured_only():
    intent = parse_collection_intent(
        '查询广州软装公司，使用 DeepSeek。',
        configured_models={'doubao'},
        model_keywords=['建材供应商', '全案软装公司'],
    )

    assert '建材供应商' not in intent.keywords
    assert '全案软装公司' in intent.keywords
    assert intent.models == ['doubao']


def test_configured_kuai_model_is_used_when_the_request_does_not_name_a_model():
    intent = parse_collection_intent(
        '查询深圳软装公司，需要手机号。',
        configured_models={'kuai'},
    )

    assert intent.models == ['kuai']


def test_furniture_business_request_expands_customer_types_without_keyword_list_input():
    intent = parse_collection_intent(
        '我是做家具的，寻找全国三线及以上城市的全案软装公司、设计公司和整装公司，需要手机号码，尽量多找。',
        configured_models={'doubao'},
    )

    assert intent.all_cities is True
    assert intent.cities == []
    assert intent.required_contacts == ['mobile']
    assert intent.limit_per_city is None
    assert intent.keywords[:5] == [
        '软装设计',
        '住宅软装',
        '室内软装',
        '私宅软装',
        '豪宅软装',
    ]
    assert {'别墅全案设计公司', '私宅软装公司', '整装设计', '全案落地'} <= set(intent.keywords)
    assert all('建材' not in keyword and '工业' not in keyword for keyword in intent.keywords)


def test_furniture_business_request_extracts_competitor_terms():
    intent = parse_collection_intent(
        '我是做家具的，寻找深圳全案软装公司、设计公司和整装公司，需要手机号码。',
        configured_models=set(),
    )

    assert '家具' in intent.competitor_terms
    assert '家居' in intent.competitor_terms
    assert '全屋定制' in intent.competitor_terms
    assert '索菲亚' in intent.competitor_terms


def test_shenzhen_natural_language_request_builds_the_residential_keyword_matrix():
    intent = parse_collection_intent(
        '我想在深圳找做住宅、私宅、豪宅和别墅项目的全案软装公司、室内设计公司和整装公司，需要手机号。',
        configured_models={'doubao'},
    )

    assert intent.cities == ['深圳市']
    assert intent.all_cities is False
    assert intent.keywords[:5] == [
        '软装设计',
        '住宅软装',
        '室内软装',
        '私宅软装',
        '豪宅软装',
    ]
    assert {'别墅软装设计公司', '高端住宅室内设计公司', '豪宅设计公司', '整装设计'} <= set(intent.keywords)
    assert len(intent.keywords) <= 24


def test_model_keywords_supplement_natural_language_expansion_but_noise_is_removed():
    intent = parse_collection_intent(
        '找深圳做全案软装的客户公司，需要手机号。',
        configured_models={'doubao'},
        model_keywords=['轻奢软装设计公司', '建材供应商', '装修招聘公司'],
    )

    assert '轻奢软装设计公司' in intent.keywords
    assert '建材供应商' not in intent.keywords
    assert '装修招聘公司' not in intent.keywords


def test_shenzhen_as_many_as_possible_sets_100_phone_valid_target() -> None:
    intent = parse_collection_intent(
        '我是做家具的，寻找深圳全案软装公司、设计公司和整装公司，需要手机号码，尽量多找。',
        configured_models=set(),
    )

    assert intent.cities == ['深圳市']
    assert intent.required_contacts == ['mobile']
    assert intent.target_valid_contacts == 100
    assert '南山区软装设计公司' in intent.keywords
    assert '龙岗区整装公司' in intent.keywords
    assert len(intent.keywords) > 24


def test_explicit_record_target_wins_over_as_many_as_possible() -> None:
    intent = parse_collection_intent(
        '寻找深圳整装公司，需要电话，尽量多找，找 25 条有效信息',
        configured_models=set(),
    )

    assert intent.target_valid_contacts == 25


def test_target_only_request_builds_generic_keywords_without_competitor_terms() -> None:
    intent = parse_collection_intent(
        '找广州的口腔诊所和牙科诊所，需要手机号，尽量多找。',
        configured_models=set(),
    )

    assert intent.cities == ['广州市']
    assert {'口腔诊所', '牙科诊所'} <= set(intent.keywords)
    assert intent.competitor_terms == []
