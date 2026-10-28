"""Keep independent Amap collection tasks running until the requested target is met."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_API = 'http://127.0.0.1:8017/api/v1'
POLL_SECONDS = 20
TERMINAL_STATUSES = {'completed', 'completed_with_errors', 'cancelled'}
PAUSE_MARKERS = ('login', '登录', 'challenge', '验证码', '滑块', '安全验证')
SHENZHEN_AREAS = (
    '白石洲', '桃园', '西丽', '留仙洞', '皇岗', '梅林', '莲花北', '景田',
    '竹子林', '农林', '侨香', '安托山', '红树湾', '碧海湾', '固戍', '翻身',
    '新安', '宝体', '坪洲', '同乐', '石井', '坑梓', '葵涌', '坝光',
    '沙井', '松岗', '福永', '航城', '平湖', '华南城', '南联', '双龙',
    '大运新城', '坂田', '民治', '观澜', '大浪', '石岩', '公明', '马田',
    '福城', '蛇口', '南头', '前海湾', '月亮湾', '赤湾', '海上世界', '车公庙',
    '香蜜湖', '水贝', '田贝', '笋岗', '东湖', '罗芳', '清水河', '黄贝岭',
    '莲塘', '大梅沙', '小梅沙', '盐田港',
)
TARGET_SUFFIXES = (
    '住宅软装顾问', '家装设计工作室', '别墅全案装修', '商业空间设计',
    '住宅室内设计工作室', '整装设计服务', '软装配饰设计', '大宅设计事务所',
    '全案装修设计', '私宅设计工作室', '精装房软装设计', '旧房改造设计',
)


def request_json(url: str, *, method: str = 'GET', payload: dict | None = None) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload else None
    request = Request(url, data=data, method=method)
    if data is not None:
        request.add_header('Content-Type', 'application/json; charset=utf-8')
    with urlopen(request, timeout=90) as response:
        return json.load(response)


def strict_mobile(lead: dict) -> str | None:
    metadata = lead.get('source_metadata') or {}
    mobile = lead.get('mobile')
    raw = metadata.get('detail_raw_text') or ''
    if not mobile or metadata.get('detail_verified') is not True or mobile not in raw:
        return None
    return mobile


def task_strict_mobiles(task: dict) -> set[str]:
    return {mobile for lead in task.get('results', []) if (mobile := strict_mobile(lead))}


def task_used_keywords(task: dict) -> set[str]:
    return {
        str(unit.get('keyword')).strip()
        for unit in task.get('work_units', [])
        if str(unit.get('keyword') or '').strip()
    }


def daily_progress(state: dict, *, current_date: str, strict_valid_count: int) -> dict:
    if state.get('daily_date') != current_date:
        return {
            'daily_date': current_date,
            'daily_start_count': strict_valid_count,
            'daily_valid_count': 0,
        }
    start_count = int(state.get('daily_start_count', strict_valid_count))
    return {
        'daily_date': current_date,
        'daily_start_count': start_count,
        'daily_valid_count': max(0, strict_valid_count - start_count),
    }


def should_stop_for_target(*, strict_valid_count: int, target: int) -> bool:
    return strict_valid_count >= target


def should_resume_daily_pause(state: dict, task: dict) -> bool:
    return bool(
        state.get('daily_paused_task_id')
        and state.get('daily_paused_task_id') == task.get('id')
        and task.get('status') == 'paused'
    )


def browser_needs_reopen(task: dict) -> bool:
    # A running unit owns the browser and the provider handles reconnects. The
    # persisted checkpoint can lag behind the live browser during a unit.
    if any(unit.get('status') == 'running' for unit in task.get('work_units', [])):
        return False
    return (task.get('checkpoint') or {}).get('browser_state') in {'stopped', 'failed'}


EXPANSION_SUFFIXES = (
    '\u5ba4\u5185\u8bbe\u8ba1\u516c\u53f8', '\u88c5\u9970\u8bbe\u8ba1\u516c\u53f8', '\u5bb6\u5c45\u7a7a\u95f4\u8bbe\u8ba1\u516c\u53f8',
    '\u8f6f\u88c5\u9648\u8bbe\u516c\u53f8', '\u5bb6\u5c45\u7f8e\u5b66\u516c\u53f8', '\u5bb6\u5c45\u8bbe\u8ba1\u516c\u53f8',
    '\u5168\u6848\u8bbe\u8ba1\u4e8b\u52a1\u6240', '\u79c1\u5b85\u8bbe\u8ba1\u4e8b\u52a1\u6240', '\u6837\u677f\u623f\u8bbe\u8ba1\u516c\u53f8',
    '\u9152\u5e97\u8bbe\u8ba1\u516c\u53f8', '\u5927\u5b85\u8bbe\u8ba1\u516c\u53f8', '\u5927\u5b85\u8f6f\u88c5\u8bbe\u8ba1',
    '\u5546\u4e1a\u7a7a\u95f4\u8bbe\u8ba1\u516c\u53f8', '\u5546\u4e1a\u7a7a\u95f4\u88c5\u9970\u516c\u53f8', '\u529e\u516c\u7a7a\u95f4\u8bbe\u8ba1\u516c\u53f8',
)
DEEP_EXPANSION_SUFFIXES = (
    '\u88c5\u4fee\u516c\u53f8', '\u5bb6\u5ead\u88c5\u4fee\u516c\u53f8', '\u623f\u5c4b\u88c5\u4fee\u516c\u53f8',
    '\u5ba4\u5185\u88c5\u9970\u516c\u53f8', '\u4f4f\u5b85\u88c5\u4fee\u516c\u53f8', '\u522b\u5885\u88c5\u4fee\u516c\u53f8',
    '\u7cbe\u88c5\u623f\u8bbe\u8ba1\u516c\u53f8', '\u5bb6\u88c5\u5168\u6848\u516c\u53f8', '\u9ad8\u7aef\u4f4f\u5b85\u8bbe\u8ba1',
    '\u65e7\u623f\u7ffb\u65b0\u516c\u53f8', '\u529e\u516c\u5ba4\u88c5\u4fee\u516c\u53f8', '\u5546\u94fa\u88c5\u4fee\u516c\u53f8',
    '\u9910\u996e\u7a7a\u95f4\u8bbe\u8ba1\u516c\u53f8', '\u9152\u5e97\u88c5\u4fee\u8bbe\u8ba1\u516c\u53f8', '\u5c55\u5385\u8bbe\u8ba1\u516c\u53f8',
    '\u552e\u697c\u5904\u8bbe\u8ba1\u516c\u53f8', '\u5efa\u7b51\u88c5\u9970\u8bbe\u8ba1\u516c\u53f8', '\u88c5\u4fee\u8bbe\u8ba1\u5de5\u4f5c\u5ba4',
    '\u8f6f\u88c5\u642d\u914d\u516c\u53f8', '\u5ba4\u5185\u9648\u8bbe\u8bbe\u8ba1',
)
CUSTOMER_SIDE_EXPANSION_SUFFIXES = (
    '\u5168\u6848\u8f6f\u88c5\u8bbe\u8ba1', '\u8f6f\u88c5\u8bbe\u8ba1\u4e8b\u52a1\u6240', '\u8f6f\u88c5\u843d\u5730\u670d\u52a1',
    '\u79c1\u5b85\u5168\u6848\u8bbe\u8ba1', '\u522b\u5885\u5168\u6848\u8bbe\u8ba1', '\u7cbe\u88c5\u623f\u8f6f\u88c5\u8bbe\u8ba1',
    '\u6837\u677f\u95f4\u8f6f\u88c5\u8bbe\u8ba1', '\u4f4f\u5b85\u7a7a\u95f4\u8bbe\u8ba1', '\u5ba4\u5185\u9648\u8bbe\u8bbe\u8ba1',
    '\u5bb6\u5c45\u7a7a\u95f4\u7b56\u5212', '\u5168\u5c4b\u7a7a\u95f4\u8bbe\u8ba1', '\u5bb6\u88c5\u8bbe\u8ba1\u5de5\u4f5c\u5ba4',
    '\u6574\u88c5\u8bbe\u8ba1\u5de5\u4f5c\u5ba4', '\u8bbe\u8ba1\u65bd\u5de5\u4e00\u4f53\u5316', '\u5ba4\u5185\u8bbe\u8ba1\u5de5\u4f5c\u5ba4',
    '\u9ad8\u7aef\u4f4f\u5b85\u6539\u9020', '\u4f4f\u5b85\u6539\u9020\u8bbe\u8ba1', '\u62ce\u5305\u5165\u4f4f\u8bbe\u8ba1',
)
QUALIFIED_QUERY_PREFIXES = (
    '\u4e13\u4e1a', '\u9ad8\u7aef', '\u7cbe\u54c1', '\u672c\u5730', '\u4e00\u7ad9\u5f0f',
    '\u5b9a\u5236', '\u539f\u521b', '\u72ec\u7acb', '\u8d44\u6df1', '\u53e3\u7891',
)
QUALIFIED_QUERY_SUFFIXES = (
    '\u5168\u6848\u8f6f\u88c5\u516c\u53f8', '\u8f6f\u88c5\u8bbe\u8ba1\u516c\u53f8', '\u6574\u88c5\u516c\u53f8',
    '\u5ba4\u5185\u8bbe\u8ba1\u516c\u53f8', '\u88c5\u9970\u8bbe\u8ba1\u516c\u53f8', '\u79c1\u5b85\u8bbe\u8ba1\u516c\u53f8',
    '\u522b\u5885\u8bbe\u8ba1\u516c\u53f8', '\u4f4f\u5b85\u7a7a\u95f4\u8bbe\u8ba1', '\u7cbe\u88c5\u623f\u8f6f\u88c5\u8bbe\u8ba1',
    '\u6837\u677f\u95f4\u8f6f\u88c5\u8bbe\u8ba1', '\u5bb6\u88c5\u8bbe\u8ba1\u5de5\u4f5c\u5ba4', '\u6574\u88c5\u8bbe\u8ba1\u5de5\u4f5c\u5ba4',
)


def next_keywords(used_keywords: set[str], *, limit: int = 120) -> list[str]:
    for suffixes in (
        TARGET_SUFFIXES,
        EXPANSION_SUFFIXES,
        DEEP_EXPANSION_SUFFIXES,
        CUSTOMER_SIDE_EXPANSION_SUFFIXES,
    ):
        keywords = [
            f'{area}{suffix}'
            for area in SHENZHEN_AREAS
            for suffix in suffixes
            if f'{area}{suffix}' not in used_keywords
        ]
        if keywords:
            return keywords[:limit]
    qualified_keywords = [
        f'{area}{qualifier}{suffix}'
        for area in SHENZHEN_AREAS
        for qualifier in QUALIFIED_QUERY_PREFIXES
        for suffix in QUALIFIED_QUERY_SUFFIXES
        if f'{area}{qualifier}{suffix}' not in used_keywords
    ]
    if qualified_keywords:
        return qualified_keywords[:limit]
    return []


def read_state(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


def load_all_tasks(api_url: str) -> list[dict]:
    listing = request_json(f'{api_url}/collection-tasks?limit=100')
    items = listing.get('items', [])
    return [request_json(f"{api_url}/collection-tasks/{item['id']}") for item in items]


def create_next_task(api_url: str, request_text: str, used_keywords: set[str]) -> dict:
    keywords = next_keywords(used_keywords)
    if not keywords:
        raise RuntimeError('no unused Shenzhen query combinations remain')
    task = request_json(
        f'{api_url}/collection-tasks/from-natural-language',
        method='POST',
        payload={
            'request_text': request_text,
            'keywords': keywords,
            'continuous_mode': True,
            'auto_deliver': False,
            'verified_auto_deliver': True,
        },
    )
    return request_json(
        f"{api_url}/collection-tasks/{task['id']}/start",
        method='POST',
    )


def extend_source_exhausted_task(
    api_url: str,
    *,
    task_id: str,
    used_keywords: set[str],
) -> dict:
    keywords = next_keywords(used_keywords)
    if not keywords:
        raise RuntimeError('no unused Shenzhen query combinations remain')
    return request_json(
        f'{api_url}/collection-tasks/{task_id}/extend',
        method='POST',
        payload={'keywords': keywords},
    )


def has_manual_pause(task: dict) -> bool:
    return task.get('status') in {'paused', 'cancelled', 'needs_attention'}


def requires_manual_action(task: dict) -> bool:
    text = ' '.join(str(item) for item in task.get('errors', []))
    return task.get('status') == 'needs_attention' or any(marker in text.lower() for marker in PAUSE_MARKERS)


def run(
    api_url: str,
    state_path: Path,
    request_text: str | None,
    target: int,
    active_task_id: str | None = None,
) -> None:
    state = read_state(state_path)
    if request_text:
        state.setdefault('request_text', request_text)
    if not state.get('request_text'):
        raise ValueError('request text is required in state or command line')
    state.setdefault('target', target)
    state.setdefault('daily_target', 100)
    if active_task_id:
        state.setdefault('active_task_id', active_task_id)
    while True:
        try:
            tasks = load_all_tasks(api_url)
            strict_mobiles = set().union(*(task_strict_mobiles(task) for task in tasks)) if tasks else set()
            state['strict_valid_count'] = len(strict_mobiles)
            progress = daily_progress(
                state,
                current_date=datetime.now().astimezone().date().isoformat(),
                strict_valid_count=len(strict_mobiles),
            )
            state.update(progress)
            state['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
            active_id = state.get('active_task_id')
            active = next((task for task in tasks if task.get('id') == active_id), None)

            if active and should_resume_daily_pause(state, active) and state['daily_valid_count'] < state['daily_target']:
                resumed = request_json(
                    f"{api_url}/collection-tasks/{active['id']}/resume",
                    method='POST',
                )
                state.pop('daily_paused_task_id', None)
                state.pop('last_error', None)
                state.update(active_task_id=resumed['id'], status='running', completion_reason=None)
                write_state(state_path, state)
                time.sleep(POLL_SECONDS)
                continue

            if active and browser_needs_reopen(active):
                request_json(f'{api_url}/collection-browser/amap/open', method='POST')
                resumed = request_json(
                    f"{api_url}/collection-tasks/{active['id']}/resume",
                    method='POST',
                )
                state.pop('last_error', None)
                state.update(active_task_id=resumed['id'], status='running', completion_reason=None)
                write_state(state_path, state)
                time.sleep(POLL_SECONDS)
                continue

            if should_stop_for_target(strict_valid_count=len(strict_mobiles), target=state['target']):
                state.update(status='completed', completion_reason='target_reached')
                write_state(state_path, state)
                return
            if active and requires_manual_action(active):
                state.update(status='needs_attention', completion_reason='manual_amap_action_required')
                write_state(state_path, state)
                return
            if active and has_manual_pause(active):
                state.update(status='paused', completion_reason='manual_task_control')
                write_state(state_path, state)
                return
            if active is None or active.get('status') in TERMINAL_STATUSES:
                used_keywords = set().union(*(task_used_keywords(task) for task in tasks)) if tasks else set()
                if active and active.get('status') == 'completed' and active.get('completion_reason') == 'source_exhausted':
                    next_task = extend_source_exhausted_task(
                        api_url,
                        task_id=active['id'],
                        used_keywords=used_keywords,
                    )
                else:
                    next_task = create_next_task(api_url, state['request_text'], used_keywords)
                state.pop('last_error', None)
                state.update(active_task_id=next_task['id'], status='running', completion_reason=None)
                write_state(state_path, state)
            else:
                state.pop('last_error', None)
                state.update(status='running', completion_reason=None)
                write_state(state_path, state)
            time.sleep(POLL_SECONDS)
        except (HTTPError, URLError, TimeoutError, RuntimeError, OSError) as exc:
            state.update(status='retry_wait', last_error=str(exc), updated_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'))
            write_state(state_path, state)
            time.sleep(POLL_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--api-url', default=DEFAULT_API)
    parser.add_argument('--state-file', type=Path, required=True)
    parser.add_argument('--request-text')
    parser.add_argument('--target', type=int, required=True)
    parser.add_argument('--active-task-id')
    args = parser.parse_args()
    run(
        args.api_url.rstrip('/'),
        args.state_file,
        args.request_text,
        args.target,
        args.active_task_id,
    )


if __name__ == '__main__':
    main()
