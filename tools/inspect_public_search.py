from __future__ import annotations

import json

import httpx

from backend.app.providers.public_web import (
    _clean_company_name,
    _PublicSearchResultParser,
)


def main() -> None:
    query = '深圳市 室内设计 公司 官网 联系方式'
    sources = (
        ('sogou', 'https://www.sogou.com/web', 'query', 'page'),
        ('so', 'https://www.so.com/s', 'q', 'pn'),
        ('bing', 'https://cn.bing.com/search', 'q', 'first'),
        ('baidu', 'https://www.baidu.com/s', 'wd', 'pn'),
    )
    rows: list[dict[str, object]] = []
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        for label, url, query_parameter, page_parameter in sources:
            for page in (1, 2):
                page_value = (
                    (page - 1) * 10 + 1
                    if label == 'bing'
                    else (page - 1) * 10
                    if label == 'baidu'
                    else page
                )
                try:
                    response = client.get(
                        url,
                        params={query_parameter: query, page_parameter: page_value},
                        headers={'User-Agent': 'Mozilla/5.0 (compatible; MapSearch/1.0)'},
                    )
                    response.raise_for_status()
                except Exception as exc:  # noqa: BLE001 - diagnostic output needs the source error
                    rows.append({'source': label, 'page': page, 'error': str(exc)})
                    continue
                parser = _PublicSearchResultParser()
                parser.feed(response.text)
                names = [
                    name
                    for result in parser.results
                    if (name := _clean_company_name(result['title']))
                ]
                rows.append({
                    'source': label,
                    'page': page,
                    'status': response.status_code,
                    'bytes': len(response.content),
                    'parsed_results': len(parser.results),
                    'company_names': list(dict.fromkeys(names)),
                    'result_titles': [result['title'] for result in parser.results[:10]],
                    'title': response.text[:120].replace('\n', ' '),
                })
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
