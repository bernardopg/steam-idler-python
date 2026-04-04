"""Tests for detailed logger JSON outputs."""

from __future__ import annotations

import json

from steam_idle_bot.config.settings import Settings
from steam_idle_bot.utils.detailed_logger import DetailedLogger


def make_settings() -> Settings:
    return Settings(username="user", password="pass")


def test_log_filtering_process_writes_json(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    logger = DetailedLogger(make_settings())

    logger.log_filtering_process(
        steam_id="123",
        all_games=[1, 2, 3],
        games_with_cards=[1, 2],
        games_with_drops=[1],
        final_games=[1],
        excluded_games=[3],
        scraping_results={1: True},
        drop_filter_source="badge_service",
    )

    files = list((tmp_path / "logs").glob("game_filtering_*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["drop_filter_source"] == "badge_service"
    assert data["details"]["final_games"] == [1]


def test_log_scraping_result_appends_and_recovers_from_invalid_json(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    logger = DetailedLogger(make_settings())
    log_file = tmp_path / "logs" / "scraping_results.json"
    log_file.write_text("not-json", encoding="utf-8")

    logger.log_scraping_result(10, "123", True, "x" * 300)
    logger.log_scraping_result(11, "123", False, "ok")

    data = json.loads(log_file.read_text(encoding="utf-8"))
    assert len(data) == 2
    assert data[0]["app_id"] == 10
    assert data[0]["content_preview"].endswith("...")
    assert data[1]["has_drops"] is False


def test_log_api_results_appends(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    logger = DetailedLogger(make_settings())

    logger.log_api_results("owned_games", [1, 2], {1: "ok"})
    logger.log_api_results("owned_games", [3], {3: "ok"})

    file_path = tmp_path / "logs" / "owned_games_results.json"
    data = json.loads(file_path.read_text(encoding="utf-8"))
    assert len(data) == 2
    assert data[0]["games_count"] == 2
    assert data[1]["games"] == [3]


def test_log_api_results_recovers_from_invalid_json(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    logger = DetailedLogger(make_settings())
    file_path = tmp_path / "logs" / "owned_games_results.json"
    file_path.write_text("invalid", encoding="utf-8")

    logger.log_api_results("owned_games", [1], {1: True})
    data = json.loads(file_path.read_text(encoding="utf-8"))
    assert len(data) == 1
