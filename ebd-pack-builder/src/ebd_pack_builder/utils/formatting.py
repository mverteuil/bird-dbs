"""Formatting utilities for human-readable output."""


def format_size(bytes_size: int | float) -> str:
    """Format bytes as human-readable size string.

    Args:
        bytes_size: Size in bytes

    Returns:
        Human-readable string like "1.23 GB"
    """
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_size < 1024:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.2f} TB"


def format_duration(seconds: float) -> str:
    """Format seconds as human-readable duration.

    Args:
        seconds: Duration in seconds

    Returns:
        Human-readable string like "2h 30m 15s"
    """
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
