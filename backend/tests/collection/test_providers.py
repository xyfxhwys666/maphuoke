from backend.app.domain.models import MapPoiCandidate
from backend.app.providers.fake import FakeRelevanceJudge


def test_fake_relevance_judge_returns_structured_decision():
    decision = FakeRelevanceJudge().judge(
        request_text='找家装设计公司',
        city='深圳市',
        keyword='设计公司',
        candidate=MapPoiCandidate(
            candidate_id='candidate-1',
            company_name='深圳示例设计有限公司',
            city='深圳市',
            address='示例路 1 号',
        ),
    )

    assert decision.model_id == 'fake'
    assert decision.status == 'relevant'
    assert decision.reason
