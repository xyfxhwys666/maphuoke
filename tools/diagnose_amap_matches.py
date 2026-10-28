from __future__ import annotations

import argparse
import json
from typing import Any
from urllib.request import Request, urlopen


def request_json(url: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
    request = Request(
        url,
        data=data,
        headers={'Content-Type': 'application/json'} if data is not None else {},
        method='POST' if data is not None else 'GET',
    )
    with urlopen(request, timeout=45) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('collection_task_id')
    parser.add_argument('--limit', type=int, default=8)
    parser.add_argument('--base-url', default='http://127.0.0.1:8017/api/v1')
    parser.add_argument('--company', action='append', default=[])
    args = parser.parse_args()

    collection = request_json(f'{args.base_url}/collection-tasks/{args.collection_task_id}')
    names = args.company or [
        candidate['company_name']
        for candidate in collection['company_name_candidates'][: max(args.limit, 1)]
    ]
    results: list[dict[str, Any]] = []
    for company_name in names:
        created = request_json(
            f'{args.base_url}/company-search-tasks',
            payload={
                'company_name': company_name,
                'city': '深圳市',
                'discovery_provider': 'amap_web',
                'enrichment_provider': 'fake_doubao',
                'required_contacts': ['mobile'],
                'auto_deliver': False,
                'allow_map_only_verification': False,
            },
        )
        started = request_json(
            f"{args.base_url}/company-search-tasks/{created['id']}/start",
            payload={},
        )
        results.append({
            'query': company_name,
            'status': started['status'],
            'errors': started.get('errors', []),
            'results': [
                {
                    'name': candidate['company_name'],
                    'city': candidate['city'],
                    'phone': candidate.get('telephone') or candidate.get('mobile'),
                    'poi': candidate.get('poi_id'),
                }
                for candidate in started['candidates']
            ],
        })
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
