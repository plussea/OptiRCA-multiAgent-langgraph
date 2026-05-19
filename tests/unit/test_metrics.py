"""Tests for metrics collection."""

import time
from unittest.mock import patch

import pytest

from optirc.core.metrics import MetricsCollector


class TestMetricsCollector:
    def test_init_without_prometheus(self):
        with patch("optirc.core.metrics.PROMETHEUS_AVAILABLE", False):
            metrics = MetricsCollector()
            assert not metrics._enabled

    def test_pipeline_timer_no_prometheus(self):
        with patch("optirc.core.metrics.PROMETHEUS_AVAILABLE", False):
            metrics = MetricsCollector()
            with metrics.pipeline_timer():
                pass  # Should not raise

    def test_node_timer_no_prometheus(self):
        with patch("optirc.core.metrics.PROMETHEUS_AVAILABLE", False):
            metrics = MetricsCollector()
            with metrics.node_timer("test_node"):
                pass

    def test_llm_timer_no_prometheus(self):
        with patch("optirc.core.metrics.PROMETHEUS_AVAILABLE", False):
            metrics = MetricsCollector()
            with metrics.llm_timer("openrouter", "generate_json"):
                pass

    def test_record_methods_no_prometheus(self):
        with patch("optirc.core.metrics.PROMETHEUS_AVAILABLE", False):
            metrics = MetricsCollector()
            metrics.record_llm_tokens("openrouter", "generate_json", 100)
            metrics.record_circuit_state("test", "closed")
            metrics.record_circuit_failure("test")
            metrics.record_error("llm", "timeout")
            metrics.set_active_pipelines(5)
            metrics.set_pending_pipelines(2)
            metrics.set_db_pool_stats(10, 8)

    def test_get_prometheus_metrics_disabled(self):
        with patch("optirc.core.metrics.PROMETHEUS_AVAILABLE", False):
            metrics = MetricsCollector()
            content, content_type = metrics.get_prometheus_metrics()
            assert b"disabled" in content
            assert content_type == "text/plain"

    def test_pipeline_timer_error_status(self):
        with patch("optirc.core.metrics.PROMETHEUS_AVAILABLE", False):
            metrics = MetricsCollector()
            with pytest.raises(ValueError):
                with metrics.pipeline_timer():
                    raise ValueError("test error")

    def test_node_timer_error_status(self):
        with patch("optirc.core.metrics.PROMETHEUS_AVAILABLE", False):
            metrics = MetricsCollector()
            with pytest.raises(ValueError):
                with metrics.node_timer("test_node"):
                    raise ValueError("test error")

    def test_llm_timer_error_status(self):
        with patch("optirc.core.metrics.PROMETHEUS_AVAILABLE", False):
            metrics = MetricsCollector()
            with pytest.raises(ValueError):
                with metrics.llm_timer("openrouter", "generate_json"):
                    raise ValueError("test error")
