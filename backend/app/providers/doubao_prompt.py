from __future__ import annotations

import json
from typing import Any


def build_contact_prompt(
    *,
    company_name: str,
    city: str,
    requested_contacts: list[str],
    known_fields: dict[str, Any] | None = None,
) -> str:
    company_query = company_name.strip()
    city_value = city.strip()
    if city_value and not company_query.startswith(city_value):
        company_query = f'{city_value}{company_query}'
    context = {
        key: value
        for key, value in (known_fields or {}).items()
        if value is not None and str(value).strip()
    }
    contact_text = '、'.join(item.strip() for item in requested_contacts if item.strip()) or 'mobile'
    return (
        f'请联网只查询这1家公司：{company_query}。\n'
        f'查找公开的{contact_text}，手机号必须是中国大陆11位号码，不要座机或400号码。\n'
        f'地图已知上下文（只能用于确认目标，不代表联系人）：{json.dumps(context, ensure_ascii=False)}\n'
        '可使用公司官网、企业信息页面、行业目录、地图页面或搜索结果摘要等公开来源。\n'
        '只填写联网结果中实际出现的内容，不得根据手机号、公司名称或常识推测、补全联系人和联系方式。\n'
        '如果字段明确标记为猜测、推断或无法由原文支持，返回null。联系人姓名和职务只有公开原文明确出现时才填写。\n'
        'source_urls和evidence_quotes必须逐字支持返回的公司和联系方式；没有独立来源时可以返回字段，但系统会将其标为未核验。\n'
        '只输出JSON，不要输出说明、Markdown或代码围栏。字段为：'
        'company_name、mobile、telephone、contact_person_name、contact_person_role、email、wechat、'
        'address、service_intro、source_urls、evidence_quotes。没有公开可对应的手机号时mobile返回null。'
    )


def build_relevance_prompt(
    *,
    request_text: str,
    city: str,
    keyword: str,
    candidate: dict[str, Any],
) -> str:
    context = {
        key: value
        for key, value in candidate.items()
        if value is not None and str(value).strip()
    }
    return (
        '请判断下面的高德地图候选公司是否符合用户的获客需求。\n'
        f'用户需求：{request_text.strip()}\n'
        f'搜索城市：{city.strip()}\n'
        f'搜索关键词：{keyword.strip()}\n'
        f'地图候选：{json.dumps(context, ensure_ascii=False)}\n'
        '只能根据用户需求和候选的地图字段判断，不要猜测联系人或联系方式。\n'
        'status只能是relevant、not_relevant或review；无法确定时使用review。\n'
        '只输出JSON：{"status":"relevant|not_relevant|review",'
        '"reason":"简短理由","confidence":0到1之间的数字}。'
    )


def build_intent_keyword_prompt(*, request_text: str) -> str:
    return (
        f'用户的获客需求：{request_text.strip()}\n'
        '提取高德地图搜索用的客户类型关键词。针对住宅、别墅、豪宅、私宅、软装、陈设、全案、室内、整装等需求，'
        '可以补充相近的住宅客户类型；不要扩展到工业、产品、平面、品牌、广告、景观、建材、供应商、招聘或培训。\n'
        '不要返回城市、公司名称、联系方式或解释。只输出 JSON：'
        '{"keywords":["全案软装公司","别墅室内设计公司","整装设计"]}'
    )
