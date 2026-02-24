"""Pipeline state management and orchestration."""

import json
from pathlib import Path

from ebd_pack_builder.models.state import PipelineState, StepStatus


class PipelineManager:
    """Manages pipeline state for resumability and progress tracking."""

    STATE_FILENAME = "pipeline_state.json"

    # Ordered list of pipeline steps
    STEPS = [
        "convert",
        "sort",
        "partition",
        "density_report",
        "plan",
        "build",
        "verify",
    ]

    def __init__(self, state_dir: Path, pipeline_id: str = "ebd-pipeline"):
        """Initialize pipeline manager.

        Args:
            state_dir: Directory to store state files
            pipeline_id: Unique identifier for this pipeline run
        """
        self.state_dir = Path(state_dir)
        self.pipeline_id = pipeline_id
        self._state: PipelineState | None = None

    @property
    def state_file(self) -> Path:
        """Path to the state JSON file."""
        return self.state_dir / self.STATE_FILENAME

    @property
    def state(self) -> PipelineState:
        """Get or load the current pipeline state."""
        if self._state is None:
            self._state = self.load_state()
        return self._state

    def load_state(self) -> PipelineState:
        """Load state from disk or create new state."""
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    data = json.load(f)
                return PipelineState.model_validate(data)
            except (json.JSONDecodeError, ValueError) as e:
                print(f"Warning: Could not load state file, creating new: {e}")

        return PipelineState(pipeline_id=self.pipeline_id)

    def save_state(self) -> None:
        """Save current state to disk."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w") as f:
            json.dump(self.state.model_dump(mode="json"), f, indent=2, default=str)

    def start_step(self, step_name: str) -> None:
        """Mark a step as started."""
        self.state.mark_started(step_name)
        self.save_state()

    def complete_step(
        self,
        step_name: str,
        output_path: str | Path | None = None,
        metrics: dict | None = None,
    ) -> None:
        """Mark a step as completed."""
        self.state.mark_completed(step_name, output_path, metrics)
        self.save_state()

    def fail_step(self, step_name: str, error: str) -> None:
        """Mark a step as failed."""
        self.state.mark_failed(step_name, error)
        self.save_state()

    def should_skip(self, step_name: str, force: bool = False) -> bool:
        """Check if a step should be skipped.

        Args:
            step_name: Name of the step
            force: If True, never skip

        Returns:
            True if step should be skipped
        """
        return self.state.can_skip(step_name, force)

    def get_step_output(self, step_name: str) -> str | None:
        """Get the output path from a completed step."""
        step = self.state.get_step(step_name)
        if step.status == StepStatus.COMPLETED:
            return step.output_path
        return None

    def get_steps_from(self, from_step: str | None) -> list[str]:
        """Get list of steps starting from a specific step.

        Args:
            from_step: Step name to start from, or None for all steps

        Returns:
            List of step names in order
        """
        if from_step is None:
            return self.STEPS.copy()

        try:
            idx = self.STEPS.index(from_step)
            return self.STEPS[idx:]
        except ValueError:
            raise ValueError(f"Unknown step: {from_step}. Valid steps: {self.STEPS}") from None

    def print_status(self) -> None:
        """Print current pipeline status."""
        print("=" * 60)
        print(f"Pipeline Status: {self.state.pipeline_id}")
        print("=" * 60)
        print(f"Created: {self.state.created_at}")
        print(f"Updated: {self.state.updated_at}")
        print()

        for step_name in self.STEPS:
            step = self.state.get_step(step_name)
            status_icon = {
                StepStatus.PENDING: " ",
                StepStatus.RUNNING: "...",
                StepStatus.COMPLETED: "OK",
                StepStatus.FAILED: "X",
                StepStatus.SKIPPED: "-",
            }.get(step.status, "?")

            line = f"[{status_icon:>3}] {step_name:<20}"

            if step.status == StepStatus.COMPLETED:
                duration = step.duration_seconds
                if duration:
                    from ebd_pack_builder.utils.formatting import format_duration

                    line += f" ({format_duration(duration)})"
                if step.output_path:
                    line += f" -> {step.output_path}"

            elif step.status == StepStatus.FAILED:
                if step.error_message:
                    line += f" ERROR: {step.error_message[:50]}"

            print(line)

        print()
