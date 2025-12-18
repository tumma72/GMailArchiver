"""WorkflowProgressWidget - Composer for multi-step workflow progress display."""

from dataclasses import dataclass, field
from typing import Any, Self

from rich.console import Group
from rich.text import Text

from gmailarchiver.cli.ui.widgets.log_window import LogLevel, LogWindowWidget
from gmailarchiver.cli.ui.widgets.task import TaskStatus, TaskWidget


@dataclass
class WorkflowProgressWidget:
    """Widget composing TaskWidgets and LogWindowWidget for workflow display.

    Renders:
    - List of workflow tasks (completed/running)
    - Separator line
    - Scrolling log window of individual items

    Example:
        wf = WorkflowProgressWidget(max_logs=5, show_logs=True)

        # Add workflow steps
        task1 = wf.add_task("Scanning messages").start()
        task1.complete("Found 1,000 messages")

        task2 = wf.add_task("Archiving").start()
        task2.set_progress(0, 1000)

        # Log individual items
        wf.log_success("Archived: Email subject")
        task2.advance()

        # Render
        group = wf.render(animation_frame=0)
    """

    show_logs: bool = True
    max_logs: int = 5
    _tasks: list[TaskWidget] = field(default_factory=list)
    _log_window: LogWindowWidget = field(init=False)

    def __post_init__(self) -> None:
        """Initialize log window after dataclass init."""
        self._log_window = LogWindowWidget(max_size=self.max_logs, show_separator=True)

    def add_task(self, description: str) -> TaskWidget:
        """Add a new workflow task.

        Args:
            description: Task description

        Returns:
            TaskWidget for further configuration
        """
        task = TaskWidget(description)
        self._tasks.append(task)
        return task

    def current_task(self) -> TaskWidget | None:
        """Get the currently running task.

        Returns:
            Running task or None if no task is running
        """
        for task in reversed(self._tasks):
            if task.status == TaskStatus.RUNNING:
                return task
        return None

    # Log window delegation methods
    def log(self, message: str, level: LogLevel = LogLevel.INFO) -> Self:
        """Log a message to the log window.

        Args:
            message: Log message
            level: Log level

        Returns:
            Self for fluent chaining
        """
        if self.show_logs:
            self._log_window.log(message, level)
        return self

    def log_success(self, message: str) -> Self:
        """Log a success message.

        Args:
            message: Success message

        Returns:
            Self for fluent chaining
        """
        return self.log(message, LogLevel.SUCCESS)

    def log_warning(self, message: str) -> Self:
        """Log a warning message.

        Args:
            message: Warning message

        Returns:
            Self for fluent chaining
        """
        return self.log(message, LogLevel.WARNING)

    def log_error(self, message: str) -> Self:
        """Log an error message.

        Args:
            message: Error message

        Returns:
            Self for fluent chaining
        """
        return self.log(message, LogLevel.ERROR)

    def log_info(self, message: str) -> Self:
        """Log an info message.

        Args:
            message: Info message

        Returns:
            Self for fluent chaining
        """
        return self.log(message, LogLevel.INFO)

    @property
    def task_count(self) -> int:
        """Number of workflow tasks."""
        return len(self._tasks)

    @property
    def log_count(self) -> int:
        """Total number of log entries."""
        return self._log_window.total_count

    def render(self, animation_frame: int = 0) -> Group:
        """Render the complete workflow progress display.

        Args:
            animation_frame: Current animation frame for spinners (0-9)

        Returns:
            Rich Group containing tasks and log window
        """
        renderables: list[Any] = []

        # Render all tasks
        for task in self._tasks:
            renderables.append(task.render(animation_frame))

        # Render log window if enabled and has entries
        if self.show_logs and self._log_window.has_entries:
            renderables.append(self._log_window.render())

        return Group(*renderables) if renderables else Group(Text(""))

    def to_json(self) -> dict[str, Any]:
        """Return JSON-serializable representation.

        Returns:
            Dictionary with tasks and log entries
        """
        return {
            "type": "workflow_progress",
            "show_logs": self.show_logs,
            "max_logs": self.max_logs,
            "tasks": [t.to_json() for t in self._tasks],
            "logs": self._log_window.to_json() if self.show_logs else None,
        }
