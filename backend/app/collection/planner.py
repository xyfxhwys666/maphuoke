import hashlib

from backend.app.collection.cities import tier3_plus_city_names
from backend.app.collection.intent import ParsedCollectionIntent
from backend.app.collection.models import CollectionWorkUnit
from backend.app.domain.models import LeadRecord


def build_work_units(
    intent: ParsedCollectionIntent,
    *,
    provider_id: str = 'amap_web',
    task_seed: str | None = None,
) -> list[CollectionWorkUnit]:
    cities = intent.cities or tier3_plus_city_names()
    keywords = list(dict.fromkeys(keyword for keyword in intent.keywords if keyword.strip()))
    seed = task_seed or intent.request_text
    units: list[CollectionWorkUnit] = []
    seen: set[tuple[str, str]] = set()
    for city in cities:
        for keyword in keywords:
            identity = (city, keyword)
            if identity in seen:
                continue
            seen.add(identity)
            digest = hashlib.sha256(
                f'{seed}\x00{city}\x00{keyword}\x00{provider_id}'.encode()
            ).hexdigest()
            units.append(
                CollectionWorkUnit(
                    id=f'unit-{digest[:24]}',
                    city=city,
                    keyword=keyword,
                    provider_id=provider_id,
                    models=list(intent.models),
                    required_contacts=list(intent.required_contacts),
                    contact_match=intent.contact_match,
                    limit_per_city=intent.limit_per_city,
                )
            )
    return units


def contact_requirement_satisfied(
    lead: LeadRecord,
    intent: ParsedCollectionIntent,
) -> bool:
    present = [
        bool((getattr(lead, field, None) or '').strip())
        for field in intent.required_contacts
    ]
    if not present:
        return False
    return all(present) if intent.contact_match == 'all' else any(present)
