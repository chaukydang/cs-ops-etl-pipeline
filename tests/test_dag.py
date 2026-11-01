import pytest

pytest.importorskip("airflow")


def test_dag_structure(monkeypatch):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "dags" / "cs_ops_etl.py"
    spec = importlib.util.spec_from_file_location("cs_ops_etl", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    dag = module.dag
    assert set(dag.task_ids) == {"dashboard", "lark", "archive", "load_postgres", "dbt_build"}
    assert dag.get_task("archive").upstream_task_ids == {"dashboard", "lark"}
    assert dag.get_task("load_postgres").upstream_task_ids == {"archive"}
    assert dag.get_task("dbt_build").upstream_task_ids == {"load_postgres"}
