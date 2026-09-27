"""Offline unit tests for the dynamically generated Click CLI (__main__.py).

The KarakeepAPI constructor and the API methods are monkeypatched at class
level, so no live Karakeep server is needed.
"""

import json

import pytest
from click.testing import CliRunner
from loguru import logger
from pydantic import BaseModel

from karakeep_python_api import APIError, datatypes
from karakeep_python_api import __main__ as cli_main
from karakeep_python_api.__main__ import serialize_output


@pytest.fixture(autouse=True)
def _quiet_logger():
    yield
    logger.remove()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        "KARAKEEP_PYTHON_API_KEY",
        "KARAKEEP_PYTHON_API_ENDPOINT",
        "KARAKEEP_PYTHON_API_VERIFY_SSL",
        "KARAKEEP_PYTHON_API_VERBOSE",
        "KARAKEEP_PYTHON_API_DISABLE_RESPONSE_VALIDATION",
        "KARAKEEP_PYTHON_API_ENSURE_ASCII",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def offline_cli(monkeypatch):
    """Neutralize the real KarakeepAPI constructor so commands run offline."""
    monkeypatch.setattr(
        cli_main.KarakeepAPI, "__init__", lambda self, **kwargs: None, raising=True
    )
    return CliRunner()


BASE_ARGS = ["--api-endpoint", "https://karakeep.test/api/v1/", "--api-key", "dummy"]


def invoke(runner, args, **kwargs):
    return runner.invoke(cli_main.cli, args, **kwargs)


# --- serialize_output ---


def test_serialize_output_handles_models_lists_dicts_and_scalars():
    model = datatypes.CheckUrlResponse(bookmarkId="bm1")
    assert serialize_output(model) == {"bookmarkId": "bm1"}
    assert serialize_output([model, 1]) == [{"bookmarkId": "bm1"}, 1]
    assert serialize_output({"key": model}) == {"key": {"bookmarkId": "bm1"}}
    assert serialize_output("plain") == "plain"
    assert serialize_output(None) is None


# --- Group-level behaviour ---


def test_dump_openapi_specification():
    result = CliRunner().invoke(cli_main.cli, ["--dump-openapi-specification"])
    assert result.exit_code == 0
    spec = json.loads(result.stdout)
    assert "openapi" in spec


def test_cli_requires_api_key():
    result = CliRunner().invoke(
        cli_main.cli,
        ["--api-endpoint", "https://karakeep.test/api/v1/", "get-all-tags"],
    )
    assert result.exit_code != 0
    assert "API Key is required" in result.output


def test_cli_requires_api_endpoint():
    result = CliRunner().invoke(cli_main.cli, ["--api-key", "dummy", "get-all-tags"])
    assert result.exit_code != 0
    assert "API endpoint is required" in result.output


def test_cli_help_lists_generated_commands():
    result = CliRunner().invoke(cli_main.cli, ["--help"])
    assert result.exit_code == 0
    assert "get-all-bookmarks" in result.output
    assert "create-a-new-bookmark" in result.output


def test_cli_rejects_invalid_literal_choice(offline_cli):
    result = invoke(
        offline_cli,
        BASE_ARGS + ["create-a-new-bookmark", "--type", "bogus"],
    )
    assert result.exit_code == 2
    assert "Invalid value" in result.output


# --- Command execution and output rendering ---


def test_cli_command_prints_model_as_json(offline_cli, monkeypatch):
    tag = datatypes.Tag(
        id="tag1",
        name="python",
        numBookmarks=3,
        numBookmarksByAttachedType=datatypes.NumBookmarksByAttachedType(human=3),
    )
    monkeypatch.setattr(
        cli_main.KarakeepAPI,
        "get_a_single_tag",
        lambda self, **kwargs: tag,
        raising=True,
    )
    result = invoke(offline_cli, BASE_ARGS + ["get-a-single-tag", "--tag-id", "tag1"])
    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["id"] == "tag1"
    assert output["numBookmarks"] == 3


def test_cli_none_result_prints_nothing(offline_cli, monkeypatch):
    monkeypatch.setattr(
        cli_main.KarakeepAPI,
        "delete_a_tag",
        lambda self, **kwargs: None,
        raising=True,
    )
    result = invoke(offline_cli, BASE_ARGS + ["delete-a-tag", "--tag-id", "tag1"])
    assert result.exit_code == 0
    assert result.stdout == ""


def test_cli_ascii_flag_escapes_unicode(offline_cli, monkeypatch):
    monkeypatch.setattr(
        cli_main.KarakeepAPI,
        "get_current_user_info",
        lambda self, **kwargs: {"name": "héllo"},
        raising=True,
    )
    result = invoke(offline_cli, BASE_ARGS + ["--ascii", "get-current-user-info"])
    assert result.exit_code == 0
    assert "\\u00e9" in result.stdout

    result = invoke(offline_cli, BASE_ARGS + ["get-current-user-info"])
    assert result.exit_code == 0
    assert "héllo" in result.stdout


def test_cli_parses_json_dict_parameter(offline_cli, monkeypatch):
    received = {}

    def fake_update(self, **kwargs):
        received.update(kwargs)
        return {"id": kwargs.get("bookmark_id")}

    monkeypatch.setattr(
        cli_main.KarakeepAPI, "update_a_bookmark", fake_update, raising=True
    )
    result = invoke(
        offline_cli,
        BASE_ARGS
        + [
            "update-a-bookmark",
            "--bookmark-id",
            "bm1",
            "--update-data",
            '{"title": "new title"}',
        ],
    )
    assert result.exit_code == 0
    assert received["update_data"] == {"title": "new title"}


def test_cli_invalid_json_parameter_fails(offline_cli):
    result = invoke(
        offline_cli,
        BASE_ARGS
        + ["update-a-bookmark", "--bookmark-id", "bm1", "--update-data", "{not json"],
    )
    assert result.exit_code == 1
    assert "Invalid JSON" in result.output


def test_cli_api_error_exits_nonzero(offline_cli, monkeypatch):
    def fail(self, **kwargs):
        raise APIError("server exploded", status_code=500)

    monkeypatch.setattr(cli_main.KarakeepAPI, "get_all_tags", fail, raising=True)
    result = invoke(offline_cli, BASE_ARGS + ["get-all-tags"])
    assert result.exit_code == 1


def test_cli_unexpected_error_exits_nonzero(offline_cli, monkeypatch):
    def fail(self, **kwargs):
        raise RuntimeError("totally unexpected")

    monkeypatch.setattr(cli_main.KarakeepAPI, "get_all_tags", fail, raising=True)
    result = invoke(offline_cli, BASE_ARGS + ["get-all-tags"])
    assert result.exit_code == 1


# --- get-all-bookmarks / get-all-highlights CLI pagination ---


def _bookmark(bm_id):
    return {**{"id": bm_id}, **{k: v for k, v in {
        "createdAt": "2026-01-01T00:00:00.000Z",
        "modifiedAt": None,
        "archived": False,
        "favourited": False,
        "taggingStatus": None,
        "summarizationStatus": None,
        "embeddingStatus": None,
        "userId": "u1",
        "tags": [],
        "content": {"type": "link", "url": "https://example.com"},
        "assets": [],
    }.items()}}


def test_cli_get_all_bookmarks_paginates_until_cursor_exhausted(
    offline_cli, monkeypatch
):
    pages = [
        {"bookmarks": [_bookmark("bm1"), _bookmark("bm2")], "nextCursor": "cursor2"},
        {"bookmarks": [_bookmark("bm3")], "nextCursor": None},
    ]
    calls = []

    def fake_get_all(self, **kwargs):
        calls.append(kwargs)
        return pages[len(calls) - 1]

    monkeypatch.setattr(
        cli_main.KarakeepAPI, "get_all_bookmarks", fake_get_all, raising=True
    )
    result = invoke(offline_cli, BASE_ARGS + ["get-all-bookmarks"])
    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert [bm["id"] for bm in output] == ["bm1", "bm2", "bm3"]
    assert len(calls) == 2
    assert calls[1]["cursor"] == "cursor2"


def test_cli_get_all_bookmarks_respects_total_limit(offline_cli, monkeypatch):
    calls = []

    def fake_get_all(self, **kwargs):
        calls.append(kwargs)
        return datatypes.PaginatedBookmarks.model_validate(
            {"bookmarks": [_bookmark("bm1"), _bookmark("bm2")], "nextCursor": "more"}
        )

    monkeypatch.setattr(
        cli_main.KarakeepAPI, "get_all_bookmarks", fake_get_all, raising=True
    )
    result = invoke(offline_cli, BASE_ARGS + ["get-all-bookmarks", "--limit", "2"])
    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert len(output) == 2
    # A single API page of size 2 satisfies the CLI total limit.
    assert len(calls) == 1
    assert calls[0]["limit"] == 2


def test_cli_get_all_bookmarks_stops_on_empty_page(offline_cli, monkeypatch):
    def fake_get_all(self, **kwargs):
        return {"bookmarks": [], "nextCursor": "always-more"}

    monkeypatch.setattr(
        cli_main.KarakeepAPI, "get_all_bookmarks", fake_get_all, raising=True
    )
    result = invoke(offline_cli, BASE_ARGS + ["get-all-bookmarks"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == []


def test_cli_get_all_highlights_paginates(offline_cli, monkeypatch):
    highlight = {
        "bookmarkId": "bm1",
        "startOffset": 0,
        "endOffset": 5,
        "color": "yellow",
        "text": "hello",
        "note": None,
        "id": "hl1",
        "userId": "u1",
        "createdAt": "2026-01-01T00:00:00.000Z",
    }
    pages = [
        {"highlights": [highlight, {**highlight, "id": "hl2"}], "nextCursor": "c2"},
        {"highlights": [{**highlight, "id": "hl3"}], "nextCursor": None},
    ]
    calls = []

    def fake_get_all(self, **kwargs):
        calls.append(kwargs)
        return pages[len(calls) - 1]

    monkeypatch.setattr(
        cli_main.KarakeepAPI, "get_all_highlights", fake_get_all, raising=True
    )
    result = invoke(offline_cli, BASE_ARGS + ["get-all-highlights"])
    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert [h["id"] for h in output] == ["hl1", "hl2", "hl3"]
    assert calls[1]["cursor"] == "c2"


def test_cli_get_all_highlights_respects_total_limit(offline_cli, monkeypatch):
    highlight = {
        "bookmarkId": "bm1",
        "startOffset": 0,
        "endOffset": 5,
        "color": "yellow",
        "text": "hello",
        "note": None,
        "id": "hl1",
        "userId": "u1",
        "createdAt": "2026-01-01T00:00:00.000Z",
    }

    def fake_get_all(self, **kwargs):
        return {"highlights": [highlight], "nextCursor": "more"}

    monkeypatch.setattr(
        cli_main.KarakeepAPI, "get_all_highlights", fake_get_all, raising=True
    )
    result = invoke(offline_cli, BASE_ARGS + ["get-all-highlights", "--limit", "1"])
    assert result.exit_code == 0
    assert len(json.loads(result.stdout)) == 1


def test_cli_constructor_failure_exits_nonzero(monkeypatch):
    def bad_init(self, **kwargs):
        raise APIError("cannot connect")

    monkeypatch.setattr(cli_main.KarakeepAPI, "__init__", bad_init, raising=True)
    result = CliRunner().invoke(cli_main.cli, BASE_ARGS + ["get-all-tags"])
    assert result.exit_code == 1


def test_dump_openapi_specification_missing_file(monkeypatch):
    monkeypatch.setattr(cli_main.os.path, "exists", lambda p: False)
    result = CliRunner().invoke(cli_main.cli, ["--dump-openapi-specification"])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_cli_value_error_from_method_exits_nonzero(offline_cli, monkeypatch):
    def fail(self, **kwargs):
        raise ValueError("bad arguments")

    monkeypatch.setattr(cli_main.KarakeepAPI, "get_all_tags", fail, raising=True)
    result = invoke(offline_cli, BASE_ARGS + ["get-all-tags"])
    assert result.exit_code == 1


def test_cli_type_error_from_method_exits_nonzero(offline_cli, monkeypatch):
    def fail(self, **kwargs):
        raise TypeError("unexpected keyword")

    monkeypatch.setattr(cli_main.KarakeepAPI, "get_all_tags", fail, raising=True)
    result = invoke(offline_cli, BASE_ARGS + ["-v", "get-all-tags"])
    assert result.exit_code == 1


def test_cli_paginated_type_error_exits_nonzero(offline_cli, monkeypatch):
    def fail(self, **kwargs):
        raise TypeError("unexpected keyword")

    monkeypatch.setattr(cli_main.KarakeepAPI, "get_all_bookmarks", fail, raising=True)
    result = invoke(offline_cli, BASE_ARGS + ["-v", "get-all-bookmarks"])
    assert result.exit_code == 1


def test_cli_get_all_bookmarks_tolerates_weird_page_result(offline_cli, monkeypatch):
    monkeypatch.setattr(
        cli_main.KarakeepAPI,
        "get_all_bookmarks",
        lambda self, **kwargs: "not a page at all",
        raising=True,
    )
    result = invoke(offline_cli, BASE_ARGS + ["get-all-bookmarks"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == []


def test_cli_get_all_bookmarks_stops_when_bookmarks_not_a_list(
    offline_cli, monkeypatch
):
    monkeypatch.setattr(
        cli_main.KarakeepAPI,
        "get_all_bookmarks",
        lambda self, **kwargs: {"bookmarks": "not-a-list", "nextCursor": "more"},
        raising=True,
    )
    result = invoke(offline_cli, BASE_ARGS + ["get-all-bookmarks"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == []


def test_cli_get_all_highlights_stops_on_empty_page(offline_cli, monkeypatch):
    monkeypatch.setattr(
        cli_main.KarakeepAPI,
        "get_all_highlights",
        lambda self, **kwargs: {"highlights": [], "nextCursor": "always-more"},
        raising=True,
    )
    result = invoke(offline_cli, BASE_ARGS + ["get-all-highlights"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == []


def test_cli_verbose_unexpected_error_logs_traceback(offline_cli, monkeypatch):
    def fail(self, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli_main.KarakeepAPI, "get_all_tags", fail, raising=True)
    result = invoke(offline_cli, BASE_ARGS + ["-v", "get-all-tags"])
    assert result.exit_code == 1


def test_cli_get_all_bookmarks_limit_zero_fetches_nothing(offline_cli, monkeypatch):
    monkeypatch.setattr(
        cli_main.KarakeepAPI,
        "get_all_bookmarks",
        lambda self, **kwargs: pytest.fail("API should not be called with --limit 0"),
        raising=True,
    )
    result = invoke(offline_cli, BASE_ARGS + ["get-all-bookmarks", "--limit", "0"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == []


def test_cli_get_all_highlights_limit_zero_fetches_nothing(offline_cli, monkeypatch):
    monkeypatch.setattr(
        cli_main.KarakeepAPI,
        "get_all_highlights",
        lambda self, **kwargs: pytest.fail("API should not be called with --limit 0"),
        raising=True,
    )
    result = invoke(offline_cli, BASE_ARGS + ["get-all-highlights", "--limit", "0"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == []


def test_cli_get_all_highlights_paginated_type_error(offline_cli, monkeypatch):
    def fail(self, **kwargs):
        raise TypeError("unexpected keyword")

    monkeypatch.setattr(cli_main.KarakeepAPI, "get_all_highlights", fail, raising=True)
    result = invoke(offline_cli, BASE_ARGS + ["-v", "get-all-highlights"])
    assert result.exit_code == 1


def test_cli_get_all_highlights_tolerates_weird_page_result(offline_cli, monkeypatch):
    monkeypatch.setattr(
        cli_main.KarakeepAPI,
        "get_all_highlights",
        lambda self, **kwargs: "not a page at all",
        raising=True,
    )
    result = invoke(offline_cli, BASE_ARGS + ["get-all-highlights"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == []


def test_cli_get_all_highlights_stops_when_highlights_not_a_list(
    offline_cli, monkeypatch
):
    monkeypatch.setattr(
        cli_main.KarakeepAPI,
        "get_all_highlights",
        lambda self, **kwargs: {"highlights": "not-a-list", "nextCursor": "more"},
        raising=True,
    )
    result = invoke(offline_cli, BASE_ARGS + ["get-all-highlights"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == []


def test_cli_unserializable_result_exits_nonzero(offline_cli, monkeypatch):
    # A result json.dumps cannot encode triggers the outer TypeError handler.
    monkeypatch.setattr(
        cli_main.KarakeepAPI,
        "get_current_user_info",
        lambda self, **kwargs: {"bad": {1, 2}},
        raising=True,
    )
    result = invoke(offline_cli, BASE_ARGS + ["-v", "get-current-user-info"])
    assert result.exit_code == 1
