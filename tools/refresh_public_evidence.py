from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.collection.evidence_backfill import refresh_task_public_evidence
from backend.app.config import load_settings
from backend.app.db import create_database
from backend.app.runtime import build_runtime_components
from backend.app.storage.repositories import CollectionRepository


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Re-verify stored public contact evidence without ERP delivery.',
    )
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--max-leads', type=int, default=1)
    args = parser.parse_args()

    settings = load_settings()
    _, session_factory = create_database(settings.database_url)
    repository = CollectionRepository(session_factory)
    task = repository.get(args.task_id)
    if task is None:
        raise SystemExit(f'collection task not found: {args.task_id}')

    runtime = build_runtime_components(
        settings,
        collection_repository=repository,
    )
    try:
        summary = refresh_task_public_evidence(
            runtime.collection_service,
            task,
            max_leads=max(args.max_leads, 0),
        )
    finally:
        runtime.close()
    print(json.dumps({
        'task_id': task.id,
        'checked_count': summary.checked_count,
        'verified_count': summary.verified_count,
        'error_count': summary.error_count,
    }, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
