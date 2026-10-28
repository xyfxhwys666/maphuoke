import re

_EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_MOBILE_PATTERN = re.compile(r"1[3-9]\d{9}")
_MOBILE_EXTRACT_PATTERN = re.compile(
    r"(?<!\d)(?:\+?86[\s-]*)?(1[3-9]\d(?:[\s-]?\d){8})(?!\d)"
)


def normalize_mobile(value: object) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) == 13 and digits.startswith("86"):
        digits = digits[2:]
    return digits if _MOBILE_PATTERN.fullmatch(digits) else None


def extract_mobile(value: object) -> str | None:
    """Extract the first valid mainland mobile from mixed phone text."""
    if value is None:
        return None
    match = _MOBILE_EXTRACT_PATTERN.search(str(value))
    return normalize_mobile(match.group(1)) if match else None


def normalize_telephone(value: object) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    return normalized or None


def normalize_email(value: object) -> str | None:
    if value is None:
        return None
    match = _EMAIL_PATTERN.search(str(value))
    return match.group(0).lower() if match else None


def normalize_wechat(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def normalize_company_name(value: object) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\s+", "", str(value)).strip("-_|·,，。;；:：")
    return normalized or None
