"""Shared test utilities (mirrors dlt-hub/verified-sources tests/utils.py conventions)."""

from dlt.common.pipeline import LoadInfo


def assert_load_info(load_info: LoadInfo, expected_load_packages: int = 1) -> None:
    """Assert that a pipeline load completed fully with no failed jobs."""
    assert len(load_info.loads_ids) == expected_load_packages
    load_info.raise_on_failed_jobs()
