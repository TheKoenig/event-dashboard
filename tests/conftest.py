"""Shared pytest fixtures."""

import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_ics() -> bytes:
    """Return the sample ICS calendar."""
    return (FIXTURES / "sample.ics").read_bytes()
