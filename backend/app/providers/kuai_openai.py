from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen

from backend.app.collection.models import RelevanceDecision
from backend.app.domain.models import MapPoiCandidate
from backend.app.providers.doubao_parser import parse_relevance_response
from backend.app.providers.doubao_prompt import build_relevance_prompt


class KuaiOpenAiRelevanceJudge:
    """OpenAI-compatible model judge used only to classify map candidates."""

    id = 'kuai'

    def __init__(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        model: str | None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.base_url = (base_url or '').rstrip('/')
        self.api_key = api_key or ''
        self.model = model or ''
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def judge(
        self,
        *,
        request_text: str,
        city: str,
        keyword: str,
        candidate: MapPoiCandidate,
    ) -> RelevanceDecision:
        if not self.configured:
            raise RuntimeError('Kuai OpenAI model is not configured')
        prompt = build_relevance_prompt(
            request_text=request_text,
            city=city,
            keyword=keyword,
            candidate={
                'candidate_id': candidate.candidate_id,
                'company_name': candidate.company_name,
                'address': candidate.address,
                'category': candidate.category,
                'telephone': candidate.telephone,
                'source_url': candidate.source_url,
            },
        )
        payload = json.dumps({
            'model': self.model,
            'messages': [
                {
                    'role': 'system',
                    'content': 'You return only the requested JSON object.',
                },
                {'role': 'user', 'content': prompt},
            ],
            'temperature': 0,
        }, ensure_ascii=False).encode('utf-8')
        request = Request(
            f'{self.base_url}/chat/completions',
            data=payload,
            headers={
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
            },
            method='POST',
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body: dict[str, Any] = json.loads(response.read().decode('utf-8'))
            content = body['choices'][0]['message']['content']
        except (KeyError, IndexError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError('Kuai OpenAI response is invalid') from exc
        if not isinstance(content, str):
            raise TypeError('Kuai OpenAI response content is invalid')
        return parse_relevance_response(
            content,
            candidate_id=candidate.candidate_id,
            model_id=self.id,
        )
