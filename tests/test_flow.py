import pytest

pytest.importorskip("prefect")

from prefect.testing.utilities import prefect_test_harness  # noqa: E402

from flows import cs_ops_etl as module  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def harness():
    with prefect_test_harness():
        yield


@pytest.fixture()
def calls(monkeypatch):
    """Replace the subprocess runner with a recorder; no retries, no real commands."""
    record: list[str] = []
    fail: set[str] = set()

    def fake_execute(name, command, timeout, env):
        record.append(name)
        if name in fail:
            raise module.StageFailed(f"{name} failed")

    monkeypatch.setattr(module, "execute", fake_execute)
    monkeypatch.setattr(module, "run_stage", module.run_stage.with_options(retries=0, on_failure=[]))
    record_fail = fail
    return record, record_fail


def test_stage_commands_use_the_cli():
    assert module.STAGES["load_postgres"][0][-4:] == ["--module", "database", "--action", "load"]
    assert module.STAGES["archive"][0][1:] == ["main.py", "--module", "archive"]
    assert set(module.STAGES) == {
        "dashboard", "lark", "archive", "load_postgres", "dbt_build", "spark_history", "monitor",
    }


def test_all_stages_run_in_dependency_order(calls):
    record, _ = calls
    module.cs_ops_etl()

    assert sorted(record) == sorted(module.STAGES)
    position = {name: i for i, name in enumerate(record)}
    assert position["archive"] > max(position["dashboard"], position["lark"])
    assert position["load_postgres"] > position["archive"]
    assert position["dbt_build"] > position["load_postgres"]
    assert position["monitor"] > position["dbt_build"]
    assert position["spark_history"] > position["archive"]


def test_failed_download_stops_everything_downstream(calls):
    record, fail = calls
    fail.add("dashboard")

    with pytest.raises(module.StageFailed) as error:
        module.cs_ops_etl()

    assert "dashboard (Failed)" in str(error.value)
    assert "lark" not in str(error.value)
    assert "lark" in record  # independent branch still runs
    for blocked in ("archive", "load_postgres", "dbt_build", "spark_history", "monitor"):
        assert blocked not in record


def test_failed_load_skips_dbt_but_not_spark(calls):
    record, fail = calls
    fail.add("load_postgres")

    with pytest.raises(module.StageFailed) as error:
        module.cs_ops_etl()

    assert "load_postgres (Failed)" in str(error.value)
    assert "spark_history" not in str(error.value)
    assert "spark_history" in record
    assert "dbt_build" not in record and "monitor" not in record


def test_execute_streams_success_failure_and_timeout():
    import sys

    from prefect import flow

    @flow
    def runner(code: str, timeout: int):
        module.execute("t", [sys.executable, "-c", code], timeout, {})

    runner("print('ok')", 30)

    with pytest.raises(module.StageFailed, match="exited with code 3"):
        runner("import sys; sys.exit(3)", 30)

    with pytest.raises(module.StageFailed, match="timed out"):
        runner("import time; time.sleep(30)", 1)
