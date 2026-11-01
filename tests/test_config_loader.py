import json

import pytest

from modules.core.config_loader import load_metric_config


def write(tmp_path, data):
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_valid_config(tmp_path):
    path = write(
        tmp_path,
        {"metric_name": "m", "endpoint": "http://x", "payload": {}},
    )
    assert load_metric_config(path)["metric_name"] == "m"


def test_missing_keys(tmp_path):
    path = write(tmp_path, {"metric_name": "m"})
    with pytest.raises(ValueError, match="endpoint"):
        load_metric_config(path)


def test_payload_must_be_object(tmp_path):
    path = write(
        tmp_path,
        {"metric_name": "m", "endpoint": "e", "payload": []},
    )
    with pytest.raises(ValueError):
        load_metric_config(path)


def test_bad_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{oops", encoding="utf-8")
    with pytest.raises(ValueError):
        load_metric_config(path)
