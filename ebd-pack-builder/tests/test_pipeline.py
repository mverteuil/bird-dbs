"""Tests for pipeline state management."""

from pathlib import Path

import pytest

from ebd_pack_builder.models.state import PipelineState, StepResult, StepStatus
from ebd_pack_builder.pipeline import PipelineManager


class TestPipelineState:
    """Test PipelineState model."""

    def test_create_empty_state(self):
        """Should create empty state with defaults."""
        state = PipelineState(pipeline_id="test")
        assert state.pipeline_id == "test"
        assert state.steps == {}

    def test_get_step_creates_new(self):
        """Should create new step if not exists."""
        state = PipelineState(pipeline_id="test")
        step = state.get_step("convert")
        assert step.status == StepStatus.PENDING
        assert "convert" in state.steps

    def test_mark_started(self):
        """Should mark step as started."""
        state = PipelineState(pipeline_id="test")
        state.mark_started("convert")
        assert state.steps["convert"].status == StepStatus.RUNNING
        assert state.steps["convert"].started_at is not None

    def test_mark_completed(self):
        """Should mark step as completed."""
        state = PipelineState(pipeline_id="test")
        state.mark_started("convert")
        state.mark_completed("convert", "/output/path", {"rows": 1000})

        step = state.steps["convert"]
        assert step.status == StepStatus.COMPLETED
        assert step.output_path == "/output/path"
        assert step.metrics["rows"] == 1000
        assert step.completed_at is not None

    def test_mark_failed(self):
        """Should mark step as failed."""
        state = PipelineState(pipeline_id="test")
        state.mark_started("convert")
        state.mark_failed("convert", "Something went wrong")

        step = state.steps["convert"]
        assert step.status == StepStatus.FAILED
        assert step.error_message == "Something went wrong"

    def test_is_completed(self):
        """Should check if step is completed."""
        state = PipelineState(pipeline_id="test")
        assert not state.is_completed("convert")

        state.mark_completed("convert")
        assert state.is_completed("convert")

    def test_can_skip(self):
        """Should check if step can be skipped."""
        state = PipelineState(pipeline_id="test")

        # Not completed, can't skip
        assert not state.can_skip("convert", force=False)

        # Completed, can skip
        state.mark_completed("convert")
        assert state.can_skip("convert", force=False)

        # Force overrides
        assert not state.can_skip("convert", force=True)


class TestStepResult:
    """Test StepResult model."""

    def test_duration_seconds(self):
        """Should calculate duration."""
        from datetime import datetime, timedelta

        step = StepResult()
        step.started_at = datetime.now()
        step.completed_at = step.started_at + timedelta(seconds=120)

        assert step.duration_seconds == 120

    def test_duration_none_when_not_completed(self):
        """Should return None when not completed."""
        step = StepResult()
        assert step.duration_seconds is None


class TestPipelineManager:
    """Test PipelineManager."""

    def test_load_creates_new_state(self, temp_state_dir: Path):
        """Should create new state if file doesn't exist."""
        manager = PipelineManager(temp_state_dir, "test-pipeline")
        state = manager.state
        assert state.pipeline_id == "test-pipeline"

    def test_save_and_load_state(self, temp_state_dir: Path):
        """Should persist state to disk."""
        manager = PipelineManager(temp_state_dir, "test-pipeline")
        manager.start_step("convert")
        manager.complete_step("convert", "/output", {"rows": 1000})

        # Create new manager, should load saved state
        manager2 = PipelineManager(temp_state_dir, "test-pipeline")
        assert manager2.state.is_completed("convert")
        assert manager2.state.steps["convert"].output_path == "/output"

    def test_get_steps_from_none(self, temp_state_dir: Path):
        """Should return all steps when from_step is None."""
        manager = PipelineManager(temp_state_dir)
        steps = manager.get_steps_from(None)
        assert steps == manager.STEPS

    def test_get_steps_from_middle(self, temp_state_dir: Path):
        """Should return steps from specified step."""
        manager = PipelineManager(temp_state_dir)
        steps = manager.get_steps_from("partition")
        assert steps == ["partition", "density_report", "size_manifest", "build", "verify"]

    def test_get_steps_from_invalid(self, temp_state_dir: Path):
        """Should raise for invalid step name."""
        manager = PipelineManager(temp_state_dir)
        with pytest.raises(ValueError, match="Unknown step"):
            manager.get_steps_from("invalid_step")

    def test_should_skip(self, temp_state_dir: Path):
        """Should check if step should be skipped."""
        manager = PipelineManager(temp_state_dir)

        # Not completed
        assert not manager.should_skip("convert")

        # Mark completed
        manager.complete_step("convert")
        assert manager.should_skip("convert")

        # Force override
        assert not manager.should_skip("convert", force=True)

    def test_get_step_output(self, temp_state_dir: Path):
        """Should return output path from completed step."""
        manager = PipelineManager(temp_state_dir)

        # Not completed
        assert manager.get_step_output("convert") is None

        # Complete with output
        manager.complete_step("convert", "/output/parquet")
        assert manager.get_step_output("convert") == "/output/parquet"
