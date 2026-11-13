"""Telegram setup helper: chat-id detection and .env editing."""
from tools.telegram_setup import latest_chat_id, upsert_env


def test_latest_chat_id_takes_the_newest_message():
    updates = {"result": [
        {"message": {"chat": {"id": 111}}},
        {"my_chat_member": {}},
        {"message": {"chat": {"id": 222}}}]}
    assert latest_chat_id(updates) == 222
    assert latest_chat_id({"result": []}) is None


def test_upsert_env_updates_and_keeps_other_lines(tmp_path):
    p = tmp_path / ".env"
    p.write_text("IG_DEMO=true\nTELEGRAM_BOT_TOKEN=\n# note\n")
    upsert_env(str(p), {"TELEGRAM_BOT_TOKEN": "abc", "TELEGRAM_CHAT_ID": 42})
    text = p.read_text()
    assert "IG_DEMO=true" in text and "# note" in text
    assert "TELEGRAM_BOT_TOKEN=abc" in text and "TELEGRAM_CHAT_ID=42" in text
    assert text.count("TELEGRAM_BOT_TOKEN") == 1


def test_upsert_env_creates_missing_file(tmp_path):
    p = tmp_path / ".env"
    upsert_env(str(p), {"TELEGRAM_CHAT_ID": 7})
    assert p.read_text() == "TELEGRAM_CHAT_ID=7\n"
