from backend.app.domain.normalization import (
    extract_mobile,
    normalize_company_name,
    normalize_email,
    normalize_mobile,
    normalize_telephone,
    normalize_wechat,
)


def test_phone_normalization_separates_mobile_landline_and_400() -> None:
    assert normalize_mobile('+86 138-0013-8000') == '13800138000'
    assert normalize_mobile('0755-12345678') is None
    assert normalize_mobile('400-800-1234') is None
    assert normalize_telephone(' 0755-12345678 ') == '0755-12345678'
    assert normalize_telephone('400-800-1234') == '400-800-1234'


def test_mobile_extraction_requires_phone_boundaries() -> None:
    assert extract_mobile('座机 0755-82793362 手机 136-8955-0791') == '13689550791'
    assert extract_mobile('40013812345678') is None
    assert extract_mobile('075513812345678') is None
    assert extract_mobile('123456789013812345678') is None


def test_company_name_removes_spacing_and_edge_punctuation() -> None:
    assert normalize_company_name(' 深圳 示例 科技 有限公司 ') == '深圳示例科技有限公司'
    assert normalize_company_name('') is None


def test_email_and_wechat_are_trimmed_and_normalized() -> None:
    assert normalize_email(' Sales@Example.COM ') == 'sales@example.com'
    assert normalize_wechat(' example_sales ') == 'example_sales'
    assert normalize_email('not an email') is None
    assert normalize_wechat(' ') is None
