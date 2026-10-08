from __future__ import annotations

import json

from polyautomate.runtime import aws_state


def test_local_state_load_save_roundtrip(tmp_path, monkeypatch):
    monkeypatch.delenv("LONGSHOT_STATE_BUCKET", raising=False)
    path = tmp_path / "state" / "longshot-state.json"

    assert aws_state.load_json_state(path, {"traded": {}}) == {"traded": {}}

    aws_state.save_json_state(path, {"open_positions": {"a": {"slug": "a"}}})

    assert json.loads(path.read_text()) == {"open_positions": {"a": {"slug": "a"}}}
    assert aws_state.load_json_state(path, {}) == {"open_positions": {"a": {"slug": "a"}}}


def test_s3_state_load_save_roundtrip(monkeypatch):
    calls = []

    class Body:
        def read(self):
            return b'{"open_positions":{"remote":{"slug":"remote"}}}'

    class FakeNoSuchKey(Exception):
        pass

    class FakeClient:
        class exceptions:
            NoSuchKey = FakeNoSuchKey

        def get_object(self, **kwargs):
            calls.append(("get", kwargs))
            return {"Body": Body()}

        def put_object(self, **kwargs):
            calls.append(("put", kwargs))
            return {}

    monkeypatch.setenv("LONGSHOT_STATE_BUCKET", "bucket")
    monkeypatch.setenv("LONGSHOT_STATE_KEY", "key.json")
    monkeypatch.setattr(aws_state, "_s3_client", lambda: FakeClient())

    assert aws_state.load_json_state(None, {}) == {"open_positions": {"remote": {"slug": "remote"}}}
    aws_state.save_json_state(None, {"closed_positions": []})

    assert calls[0] == ("get", {"Bucket": "bucket", "Key": "key.json"})
    assert calls[1][0] == "put"
    assert calls[1][1]["Bucket"] == "bucket"
    assert calls[1][1]["Key"] == "key.json"
    assert json.loads(calls[1][1]["Body"].decode("utf-8")) == {"closed_positions": []}
