"""Pipeline state models for tracking progress and resumability."""

from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class StepStatus(str, Enum):
    """Status of a pipeline step."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StepResult(BaseModel):
    """Result of a completed pipeline step."""

    status: StepStatus = Field(default=StepStatus.PENDING)
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    output_path: str | None = Field(default=None, description="Primary output path for this step")
    error_message: str | None = Field(default=None)
    metrics: dict = Field(default_factory=dict, description="Step-specific metrics")

    model_config = {"extra": "forbid"}

    @property
    def duration_seconds(self) -> float | None:
        """Calculate step duration in seconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None


class PipelineState(BaseModel):
    """State of the entire pipeline for tracking and resumability."""

    pipeline_id: str = Field(description="Unique identifier for this pipeline run")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # Step results
    steps: dict[str, StepResult] = Field(
        default_factory=dict, description="Results for each pipeline step"
    )

    model_config = {"extra": "forbid"}

    def get_step(self, step_name: str) -> StepResult:
        """Get or create a step result."""
        if step_name not in self.steps:
            self.steps[step_name] = StepResult()
        return self.steps[step_name]

    def mark_started(self, step_name: str) -> None:
        """Mark a step as started."""
        step = self.get_step(step_name)
        step.status = StepStatus.RUNNING
        step.started_at = datetime.now()
        self.updated_at = datetime.now()

    def mark_completed(
        self,
        step_name: str,
        output_path: str | Path | None = None,
        metrics: dict | None = None,
    ) -> None:
        """Mark a step as completed."""
        step = self.get_step(step_name)
        step.status = StepStatus.COMPLETED
        step.completed_at = datetime.now()
        if output_path:
            step.output_path = str(output_path)
        if metrics:
            step.metrics = metrics
        self.updated_at = datetime.now()

    def mark_failed(self, step_name: str, error: str) -> None:
        """Mark a step as failed."""
        step = self.get_step(step_name)
        step.status = StepStatus.FAILED
        step.completed_at = datetime.now()
        step.error_message = error
        self.updated_at = datetime.now()

    def is_completed(self, step_name: str) -> bool:
        """Check if a step is completed."""
        if step_name not in self.steps:
            return False
        return self.steps[step_name].status == StepStatus.COMPLETED

    def can_skip(self, step_name: str, force: bool = False) -> bool:
        """Check if a step can be skipped (already completed and not forced)."""
        return self.is_completed(step_name) and not force
