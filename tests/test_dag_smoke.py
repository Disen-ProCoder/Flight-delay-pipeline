"""
tests/test_dag_smoke.py

Smoke test for the Airflow DAG module without requiring a full Airflow install.
It injects a minimal fake Airflow API so the DAG file can be imported and inspected.
"""

import importlib
import sys
from types import ModuleType


def _install_fake_airflow(monkeypatch):
    current = {"dag": None, "groups": []}

    class FakeDAG:
        def __init__(self, *args, **kwargs):
            self.dag_id = kwargs.get("dag_id")
            self.task_ids = []

        def __enter__(self):
            current["dag"] = self
            return self

        def __exit__(self, exc_type, exc, tb):
            current["dag"] = None
            return False

    class FakeOperator:
        def __init__(self, *args, **kwargs):
            task_id = kwargs.get("task_id")
            prefix = ".".join(current["groups"])
            self.task_id = f"{prefix}.{task_id}" if prefix else task_id
            if current["dag"] is not None:
                current["dag"].task_ids.append(self.task_id)

        def __rshift__(self, other):
            return other

    class FakeTaskGroup:
        def __init__(self, group_id):
            self.group_id = group_id

        def __enter__(self):
            current["groups"].append(self.group_id)
            return self

        def __exit__(self, exc_type, exc, tb):
            current["groups"].pop()
            return False

    airflow = ModuleType("airflow")
    airflow.DAG = FakeDAG

    operators_python = ModuleType("airflow.operators.python")
    operators_python.PythonOperator = FakeOperator
    operators_python.BranchPythonOperator = FakeOperator

    operators_empty = ModuleType("airflow.operators.empty")
    operators_empty.EmptyOperator = FakeOperator

    utils_task_group = ModuleType("airflow.utils.task_group")
    utils_task_group.TaskGroup = FakeTaskGroup

    models = ModuleType("airflow.models")
    models.Variable = object()

    monkeypatch.setitem(sys.modules, "airflow", airflow)
    monkeypatch.setitem(sys.modules, "airflow.operators.python", operators_python)
    monkeypatch.setitem(sys.modules, "airflow.operators.empty", operators_empty)
    monkeypatch.setitem(sys.modules, "airflow.utils.task_group", utils_task_group)
    monkeypatch.setitem(sys.modules, "airflow.models", models)


def test_dag_import_exposes_expected_tasks(monkeypatch):
    _install_fake_airflow(monkeypatch)

    sys.modules.pop("dags.flight_delay_dag", None)
    dag_module = importlib.import_module("dags.flight_delay_dag")

    assert dag_module.dag.dag_id == "flight_delay_pipeline"
    assert set(dag_module.dag.task_ids) == {
        "start",
        "end",
        "already_processed",
        "check_already_processed",
        "extract.download_bts_data",
        "transform.clean_data",
        "quality.run_quality_checks",
        "load.load_to_warehouse",
        "load.refresh_materialized_views",
    }
