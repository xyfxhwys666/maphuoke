from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def load_dotenv_file(path: Path | str) -> None:
    """Load simple local KEY=VALUE settings without overriding the process environment."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv_file(Path(__file__).resolve().parents[2] / '.env')


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    database_url: str = os.getenv('DATABASE_URL', 'sqlite+pysqlite:///./mapsearch.db')
    amap_api_key: str | None = os.getenv('AMAP_API_KEY') or None
    amap_base_url: str = os.getenv('AMAP_BASE_URL', 'https://restapi.amap.com')
    amap_max_pages: int = _int_env('AMAP_MAX_PAGES', 3)
    amap_request_interval_seconds: float = _float_env('AMAP_REQUEST_INTERVAL_SECONDS', 0.3)
    amap_retry_limit: int = _int_env('AMAP_RETRY_LIMIT', 3)
    batch_max_items: int = _int_env('MAPSEARCH_BATCH_MAX_ITEMS', 1000)
    batch_request_interval_seconds: float = _float_env('MAPSEARCH_BATCH_REQUEST_INTERVAL_SECONDS', 0.3)
    amap_cdp_port: int = _int_env('MAPSEARCH_AMAP_CDP_PORT', 9227)
    doubao_cdp_port: int = _int_env('MAPSEARCH_DOUBAO_CDP_PORT', 9228)
    doubao_url: str = os.getenv('DOUBAO_URL', 'https://www.doubao.com/chat/')
    browser_profile_dir: str = os.getenv(
        'MAPSEARCH_BROWSER_PROFILE_DIR'
    ) or str(Path(tempfile.gettempdir()) / 'map-lead-platform' / 'profiles')
    chrome_path: str | None = os.getenv('MAPSEARCH_CHROME_PATH') or None
    erp_url: str | None = os.getenv('ERP_URL') or None
    erp_bearer_token: str | None = os.getenv('ERP_BEARER_TOKEN') or None
    kuai_api_base_url: str | None = os.getenv('KUAI_API_BASE_URL') or None
    kuai_api_key: str | None = os.getenv('KUAI_API_KEY') or None
    kuai_model: str | None = os.getenv('KUAI_MODEL') or None


def load_settings() -> RuntimeSettings:
    return RuntimeSettings()
