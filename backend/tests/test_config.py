from backend.app.config import load_dotenv_file


def test_load_dotenv_file_sets_missing_erp_url(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / '.env'
    env_file.write_text('ERP_URL=https://erp.example.test/receive\n', encoding='utf-8')
    monkeypatch.delenv('ERP_URL', raising=False)

    load_dotenv_file(env_file)

    assert __import__('os').environ['ERP_URL'] == 'https://erp.example.test/receive'


def test_load_dotenv_file_keeps_existing_environment_value(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / '.env'
    env_file.write_text('ERP_URL=https://erp.example.test/receive\n', encoding='utf-8')
    monkeypatch.setenv('ERP_URL', 'https://runtime.example.test/receive')

    load_dotenv_file(env_file)

    assert __import__('os').environ['ERP_URL'] == 'https://runtime.example.test/receive'
