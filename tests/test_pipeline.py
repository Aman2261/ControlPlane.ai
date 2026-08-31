"""
Basic tests for the ControlPlane.ai pipeline.
"""
import pytest
from pathlib import Path
import sys

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import llm_client, pipeline, audit_log


class TestPipeline:
    """Test suite for the pipeline module."""

    def setup_method(self):
        """Setup test fixtures before each test."""
        audit_log.init_db()

    def test_pipeline_imports(self):
        """Test that core modules can be imported."""
        assert pipeline is not None
        assert llm_client is not None

    def test_scenarios_exist(self):
        """Test that demo scenarios are defined."""
        assert hasattr(llm_client, 'SCENARIOS')
        assert len(llm_client.SCENARIOS) > 0

    def test_run_scenario(self):
        """Test running a single scenario through the pipeline."""
        scenario_id = list(llm_client.SCENARIOS.keys())[0]
        result = pipeline.run_scenario(scenario_id)
        
        # Verify result structure
        assert result is not None
        assert 'decision' in result
        assert 'scenario' in result
        assert 'raw_response' in result
        
        # Verify decision structure
        decision = result['decision']
        assert 'tier' in decision
        assert decision['tier'] in ['ALLOW', 'AUTO_FIX', 'ESCALATE', 'BLOCK']
        assert 'findings' in decision
        assert 'overall_risk' in decision

    def test_all_scenarios_executable(self):
        """Test that all scenarios can be executed without errors."""
        for scenario_id in llm_client.SCENARIOS:
            result = pipeline.run_scenario(scenario_id)
            assert result is not None
            assert 'decision' in result


class TestLLMClient:
    """Test suite for the LLM client module."""

    def test_scenarios_have_required_fields(self):
        """Test that all scenarios have required fields."""
        for scenario_id, scenario in llm_client.SCENARIOS.items():
            assert 'title' in scenario
            assert 'prompt' in scenario
            assert 'use_case' in scenario


class TestAuditLog:
    """Test suite for the audit log module."""

    def setup_method(self):
        """Setup test fixtures before each test."""
        audit_log.init_db()

    def test_audit_log_initialization(self):
        """Test that the audit log can be initialized."""
        # This should not raise an exception
        audit_log.init_db()

    def test_metrics_summary(self):
        """Test that metrics summary can be generated."""
        metrics = audit_log.metrics_summary()
        assert metrics is not None
        assert isinstance(metrics, dict)
