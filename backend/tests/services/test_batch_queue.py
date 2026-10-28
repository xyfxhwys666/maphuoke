from __future__ import annotations

from backend.app.batch.importers import CompanyInput
from backend.app.batch.queue import BatchQueue


def test_batch_queue_isolates_company_failure_and_can_retry_only_failed_items() -> None:
    attempts: dict[str, int] = {}

    def process(item: CompanyInput) -> str:
        attempts[item.company_name] = attempts.get(item.company_name, 0) + 1
        if item.company_name == '失败公司' and attempts[item.company_name] == 1:
            raise RuntimeError('temporary failure')
        return f'done:{item.company_name}'

    queue = BatchQueue(process, request_interval_seconds=0)
    queue.enqueue([
        CompanyInput(company_name='成功公司', city='深圳市', row_number=2),
        CompanyInput(company_name='失败公司', city='广州市', row_number=3),
    ])

    first = queue.run_all()
    retried = queue.retry_errors()

    assert [result.status for result in first] == ['completed', 'failed']
    assert retried[0].status == 'completed'
    assert retried[0].result == 'done:失败公司'
    assert attempts == {'成功公司': 1, '失败公司': 2}


def test_batch_queue_applies_request_pacing_between_items() -> None:
    sleeps: list[float] = []
    queue = BatchQueue(
        lambda item: item.company_name,
        request_interval_seconds=0.3,
        sleep_fn=lambda seconds: sleeps.append(seconds),
    )
    queue.enqueue([
        CompanyInput(company_name='公司A', city='深圳市', row_number=2),
        CompanyInput(company_name='公司B', city='深圳市', row_number=3),
    ])

    queue.run_all()

    assert sleeps and all(seconds == 0.3 for seconds in sleeps)


def test_batch_queue_pause_leaves_unprocessed_items_queued() -> None:
    processed: list[str] = []
    pause = True

    def process(item: CompanyInput) -> str:
        processed.append(item.company_name)
        return item.company_name

    queue = BatchQueue(
        process,
        request_interval_seconds=0,
        should_pause=lambda: pause and len(processed) >= 1,
    )
    queue.enqueue([
        CompanyInput(company_name='公司A', city='深圳市', row_number=2),
        CompanyInput(company_name='公司B', city='深圳市', row_number=3),
    ])

    first = queue.run_all()
    pause = False
    second = queue.run_all()

    assert [result.company_name for result in first] == ['公司A']
    assert [result.status for result in second] == ['completed']
    assert processed == ['公司A', '公司B']
