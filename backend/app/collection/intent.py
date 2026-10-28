import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Literal

from backend.app.collection.cities import tier3_plus_city_names

ContactField = Literal['mobile', 'email', 'wechat']
ContactMatch = Literal['any', 'all']

KEYWORD_PATTERN = re.compile(
    r'全案软装公司|全案设计公司|软装设计公司|软装公司|整案公司|整装公司|设计公司'
)
_TARGET_CLAUSE_PATTERN = re.compile(
    r'(?:寻找|查找|想找|要找|找)(?:[\u4e00-\u9fff]{0,12}?(?:的|做))?'
    r'(?P<targets>[\u4e00-\u9fff、和与及]{2,80})(?:，|,|。|；|;|，?需要|，?要|$)'
)
_TARGET_SUFFIX_PATTERN = re.compile(
    r'[\u4e00-\u9fff]{2,24}?(?:公司|企业|门店|商家|机构|诊所|医院|工厂|工作室|中心|店)'
)
_RESIDENTIAL_SCOPE_PATTERN = re.compile(
    r'别墅|豪宅|大宅|私宅|高端住宅|住宅|家装|居住|全案软装|全案设计|整装|整案'
)
_IRRELEVANT_KEYWORD_PATTERN = re.compile(
    r'工业|产品|平面|品牌|广告|视觉|包装|景观|园林|建材|材料|招聘|培训|供应商'
)
_RESIDENTIAL_KEYWORD_EXPANSIONS = (
    '软装设计',
    '住宅软装',
    '室内软装',
    '私宅软装',
    '豪宅软装',
    '别墅软装设计公司',
    '别墅全案设计公司',
    '别墅室内设计公司',
    '别墅装修设计公司',
    '别墅整装公司',
    '高端住宅软装公司',
    '高端住宅设计公司',
    '高端住宅室内设计公司',
    '豪宅软装公司',
    '豪宅设计公司',
    '私宅软装公司',
    '全案设计公司',
    '室内设计',
    '大宅设计',
    '空间设计',
    '软装陈设',
    '整装设计',
    '全案落地',
)
_SHENZHEN_DISTRICTS = (
    '南山区',
    '福田区',
    '罗湖区',
    '宝安区',
    '龙岗区',
    '龙华区',
    '光明区',
    '坪山区',
    '盐田区',
    '大鹏新区',
)
_DISTRICT_KEYWORD_SUFFIXES = (
    '软装设计公司',
    '室内设计公司',
    '整装公司',
    '装修设计公司',
)
CONTACT_TERMS: tuple[tuple[ContactField, tuple[str, ...]], ...] = (
    ('mobile', ('手机号码', '手机号', '手机', '电话号码', '电话')),
    ('email', ('邮箱号码', '邮箱', '邮件', 'email')),
    ('wechat', ('微信号码', '微信号', '微信', 'wechat')),
)
_BUSINESS_PATTERN = re.compile(r'我(?:是|们是)做(?P<business>[\u4e00-\u9fff、和与及]{1,16})(?:的|，|,|。)')
_FURNITURE_COMPETITOR_TERMS = (
    '家具', '家居', '全屋定制', '定制家具', '橱柜', '衣柜', '床垫', '沙发', '家具店', '家居店',
    '索菲亚', '欧派', '尚品宅配', '志邦', '金牌厨柜', '好莱客', '顾家家居', '全友家居',
)
_COMPETITOR_EXPANSIONS: dict[str, tuple[str, ...]] = {
    '家具': _FURNITURE_COMPETITOR_TERMS,
    '家居': _FURNITURE_COMPETITOR_TERMS,
    '软装': ('软装', '家居软装', '软装家居', '窗帘', '家具'),
}
ALL_MATCH_TERMS = ('都要', '全部具备', '全部都要', '缺一不可', '同时具备', '全都要')


@dataclass(slots=True)
class ParsedCollectionIntent:
    request_text: str
    cities: list[str]
    all_cities: bool
    city_scope_label: str
    keywords: list[str]
    models: list[str]
    required_contacts: list[ContactField]
    contact_match: ContactMatch
    limit_per_city: int | None
    target_valid_contacts: int | None = None
    competitor_terms: list[str] = dataclass_field(default_factory=list)


def _extract_cities(text: str) -> list[str]:
    matches: list[tuple[int, str]] = []
    for city in tier3_plus_city_names():
        alias = city.removesuffix('市')
        positions = [position for position in (text.find(city), text.find(alias)) if position >= 0]
        if positions:
            matches.append((min(positions), city))
    return [city for _, city in sorted(matches)]


def _extract_keywords(text: str) -> list[str]:
    keywords = list(dict.fromkeys(KEYWORD_PATTERN.findall(text)))
    if keywords:
        return keywords
    target_clause = _TARGET_CLAUSE_PATTERN.search(text)
    if target_clause:
        targets = target_clause.group('targets')
        generic_targets = [
            value.lstrip('、和与及')
            for value in _TARGET_SUFFIX_PATTERN.findall(targets)
        ]
        if generic_targets:
            return list(dict.fromkeys(generic_targets))
    return ['软装公司']


def _expand_keywords(text: str, keywords: list[str], model_keywords: list[str]) -> list[str]:
    residential_scope = bool(_RESIDENTIAL_SCOPE_PATTERN.search(text))
    # A natural-language brief describes the customer segment, rather than an
    # exact query list. For residential work we start with the proven Amap
    # search matrix and only use model suggestions as additional variants.
    combined = (
        [*_RESIDENTIAL_KEYWORD_EXPANSIONS, *model_keywords]
        if residential_scope
        else [*keywords, *model_keywords]
    )
    high_volume_shenzhen = '深圳' in text and (
        any(term in text for term in ('尽量多找', '越多越好', '多找一些'))
        or bool(re.search(r'100\s*(?:条|家|个)', text))
    )
    if high_volume_shenzhen:
        combined.extend(
            f'{district}{suffix}'
            for district in _SHENZHEN_DISTRICTS
            for suffix in _DISTRICT_KEYWORD_SUFFIXES
        )
    filtered: list[str] = []
    for keyword in combined:
        cleaned = str(keyword).strip()
        if not cleaned or _IRRELEVANT_KEYWORD_PATTERN.search(cleaned):
            continue
        if cleaned not in filtered:
            filtered.append(cleaned)
    return filtered[:80]


def _extract_models(text: str, configured_models: set[str]) -> list[str]:
    lowered = text.lower()
    requested: list[str] = []
    if 'deepseek' in lowered or 'deep seek' in lowered or '深度求索' in text:
        requested.append('deepseek')
    if '豆包' in text or 'doubao' in lowered:
        requested.append('doubao')
    available = [model_id for model_id in requested if model_id in configured_models]
    if available:
        return list(dict.fromkeys(available))
    for fallback in ('doubao', 'deepseek'):
        if fallback in configured_models:
            return [fallback]
    return [min(configured_models)] if configured_models else []


def _extract_contacts(text: str) -> list[ContactField]:
    lowered = text.lower()
    contacts = [
        field
        for field, terms in CONTACT_TERMS
        if any(term in lowered for term in terms)
    ]
    return contacts or ['mobile']


def _extract_limit(text: str) -> int | None:
    match = re.search(
        r'(?:只要|最多|限定|限制|查|找|得到|获得)?\s*(\d{1,4})\s*'
        r'(?:家|条(?:有效)?(?:客户)?(?:信息|线索)?|个(?:有效)?(?:客户|公司|线索)?)',
        text,
    )
    if not match:
        return None
    return max(1, min(1000, int(match.group(1))))


def _extract_target_valid_contacts(text: str, explicit_limit: int | None) -> int | None:
    if explicit_limit is not None:
        return explicit_limit
    if any(term in text for term in ('尽量多找', '越多越好', '多找一些')):
        return 100
    return None


def _extract_competitor_terms(text: str) -> list[str]:
    match = _BUSINESS_PATTERN.search(text)
    if not match:
        return []
    business = match.group('business')
    terms: list[str] = []
    for key, expansions in _COMPETITOR_EXPANSIONS.items():
        if key in business:
            terms.extend(expansions)
    if not terms:
        terms.append(business)
    return list(dict.fromkeys(terms))


def parse_collection_intent(
    request_text: str,
    *,
    configured_models: set[str],
    model_keywords: list[str] | None = None,
) -> ParsedCollectionIntent:
    text = request_text.strip()
    if not text:
        raise ValueError('request_text cannot be empty')
    cities = _extract_cities(text)
    contacts = _extract_contacts(text)
    keywords = _expand_keywords(text, _extract_keywords(text), model_keywords or [])
    contact_match: ContactMatch = (
        'all' if len(contacts) == 1 or any(term in text for term in ALL_MATCH_TERMS) else 'any'
    )
    all_cities = not cities
    city_scope_label = '全国三线及以上城市' if all_cities else '、'.join(cities)
    limit = _extract_limit(text)
    return ParsedCollectionIntent(
        request_text=text,
        cities=cities,
        all_cities=all_cities,
        city_scope_label=city_scope_label,
        keywords=keywords,
        models=_extract_models(text, configured_models),
        required_contacts=contacts,
        contact_match=contact_match,
        limit_per_city=limit,
        target_valid_contacts=_extract_target_valid_contacts(text, limit),
        competitor_terms=_extract_competitor_terms(text),
    )
