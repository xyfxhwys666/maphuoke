import json
from pathlib import Path

_CITY_DATA_PATH = Path(__file__).parent / 'data' / 'tier3_plus_cities.json'


def tier3_plus_city_names() -> list[str]:
    values = json.loads(_CITY_DATA_PATH.read_text(encoding='utf-8'))
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
