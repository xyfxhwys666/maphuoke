import json
from io import BytesIO

from backend.app.domain.models import MapPoiCandidate
from backend.app.providers.kuai_openai import KuaiOpenAiRelevanceJudge


class _Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_kuai_judge_posts_openai_compatible_request_and_parses_decision(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout):
        captured['url'] = request.full_url
        captured['authorization'] = request.get_header('Authorization')
        captured['body'] = json.loads(request.data.decode('utf-8'))
        captured['timeout'] = timeout
        return _Response(json.dumps({
            'choices': [{
                'message': {'content': json.dumps({
                    'status': 'relevant',
                    'reason': '业务范围匹配',
                    'confidence': 0.92,
                }, ensure_ascii=False)},
            }],
        }, ensure_ascii=False).encode('utf-8'))

    monkeypatch.setattr('backend.app.providers.kuai_openai.urlopen', fake_urlopen)
    judge = KuaiOpenAiRelevanceJudge(
        base_url='https://api.kuai.host/v1/',
        api_key='test-key',
        model='gpt-5.6-terra',
    )

    decision = judge.judge(
        request_text='查询深圳软装公司',
        city='深圳市',
        keyword='软装设计公司',
        candidate=MapPoiCandidate(
            candidate_id='candidate-1',
            company_name='深圳示例软装设计有限公司',
            city='深圳市',
        ),
    )

    assert captured['url'] == 'https://api.kuai.host/v1/chat/completions'
    assert captured['authorization'] == 'Bearer test-key'
    assert captured['body']['model'] == 'gpt-5.6-terra'
    assert decision.status == 'relevant'
    assert decision.candidate_id == 'candidate-1'
    assert decision.model_id == 'kuai'
