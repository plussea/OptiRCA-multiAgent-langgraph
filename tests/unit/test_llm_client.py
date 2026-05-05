import pytest
from optirc.core.llm_client import LLMClient


def test_llm_client_init():
    client = LLMClient()
    assert client.primary is not None
    assert client.backup is not None
