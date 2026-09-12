"""Protect the performance report from averaging worker percentiles/RPS."""
import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "runtime_load", Path(__file__).resolve().parents[2] / "experiments/runtime-nodes/load.py")
load = importlib.util.module_from_spec(spec)
spec.loader.exec_module(load)


def test_aggregate_pools_requests_and_uses_the_shared_elapsed_interval():
    common = {"pool_size": 20, "pools": 1, "loop_lag": [1], "cpu_seconds": 1}
    result = load.aggregate([
        {**common, "started": 10, "finished": 20,
         "timings": [(10, True)] * 99, "statuses": {"201": 99}, "uncertain_keys": []},
        {**common, "started": 11, "finished": 21,
         "timings": [(10000, False)], "statuses": {"ReadTimeout": 1}, "uncertain_keys": ["unknown"]},
    ])
    assert result["p95_ms"] == 10  # Averaging the two workers would give 5005 ms.
    assert result["requests"] == 100 and result["success"] == 99
    assert result["duration_seconds"] == 11
    assert result["success_rps"] == 9
    assert result["failure_rate"] == .01
    assert result["uncertain_keys"] == ["unknown"]
    assert result["client_start_spread_ms"] == 1000
