"""Shared pytest setup for all bench tests."""


def pytest_configure(config):
    config.addinivalue_line("markers", "bench_ha: real-time Home Assistant test against the fake camera")
