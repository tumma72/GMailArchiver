# SessionLogger Quick Start Guide

## Basic Usage

### Simple Usage
```python
from gmailarchiver.output import SessionLogger

# Create logger (uses default XDG path: ~/.config/gmailarchiver/logs)
logger = SessionLogger()

# Write logs
logger.write("Application started", "INFO")
logger.write("Processing 100 messages", "INFO")
logger.write("Warning: Rate limit approaching", "WARNING")
logger.write("Debug: API response time 250ms", "DEBUG")
logger.write("Error: Network timeout", "ERROR")
logger.write("Operation completed", "SUCCESS")

# Close when done
logger.close()
```

### Context Manager (Recommended)
```python
from gmailarchiver.output import SessionLogger

# Automatic cleanup with context manager
with SessionLogger() as logger:
    logger.write("Starting operation", "INFO")
    logger.write("Processing data", "INFO")
    logger.write("Complete", "SUCCESS")
    # File automatically closed on exit
```

### Custom Configuration
```python
from pathlib import Path
from gmailarchiver.output import SessionLogger

# Custom log directory and retention
custom_dir = Path("/var/log/myapp")
logger = SessionLogger(
    log_dir=custom_dir,
    keep_last=20  # Keep last 20 sessions (default: 10)
)

logger.write("Custom configuration active", "INFO")
logger.close()
```

### Disable Cleanup (Keep All Logs)
```python
logger = SessionLogger(keep_last=0)  # Never delete old logs
```

## Integration with LogBuffer

```python
from gmailarchiver.output import SessionLogger, LogBuffer

# Initialize both
buffer = LogBuffer(max_visible=10)  # Shows last 10 in UI
session_logger = SessionLogger()    # Stores all to file

# Send same logs to both
def log(message: str, level: str = "INFO") -> None:
    buffer.add(message, level)
    session_logger.write(message, level)

# Use throughout application
log("Processing started", "INFO")
log("Debug: Cache hit rate 95%", "DEBUG")  # In file, not in UI
log("Found 500 messages", "INFO")
log("Archive complete", "SUCCESS")

session_logger.close()
```

## Log File Format

```
YYYY-MM-DD HH:MM:SS.mmm [LEVEL] message
```

**Example:**
```
2025-01-24 14:30:52.123 [INFO] Application started
2025-01-24 14:30:52.456 [WARNING] Rate limit at 80%
2025-01-24 14:30:53.789 [ERROR] Network timeout
2025-01-24 14:30:54.012 [SUCCESS] Archive complete
```

## Log File Locations

### Default Locations (XDG-Compliant)
- **Linux/macOS**: `~/.config/gmailarchiver/logs/session_*.log`
- **Windows**: `%APPDATA%\gmailarchiver\logs\session_*.log`

### Filename Format
```
session_YYYY-MM-DD_HHMMSS.log
```

**Examples:**
- `session_2025-01-24_143052.log`
- `session_2025-01-24_150000.log`

### Environment Variable Override
```bash
# Linux/macOS: Set custom config directory
export XDG_CONFIG_HOME=/custom/config
# Logs will be in: /custom/config/gmailarchiver/logs/
```

## Severity Levels

| Level | Use Case | Example |
|-------|----------|---------|
| `DEBUG` | Detailed diagnostic info | API timings, cache hits |
| `INFO` | General informational | Operation started, progress |
| `WARNING` | Potential issues | Rate limits, slow responses |
| `ERROR` | Error conditions | Network failures, timeouts |
| `SUCCESS` | Successful completion | Operation finished |

**Default:** If no level specified, uses `INFO`

## Automatic Cleanup

### Default Behavior
- Keeps **last 10 sessions**
- Runs on initialization
- Only deletes `session_*.log` files
- Preserves other files in log directory

### Configuration Options
```python
# Keep last 5 sessions
SessionLogger(keep_last=5)

# Keep last 20 sessions
SessionLogger(keep_last=20)

# Keep all sessions (no cleanup)
SessionLogger(keep_last=0)
```

### Manual Cleanup
```bash
# Find and delete old logs manually
cd ~/.config/gmailarchiver/logs
ls -lt session_*.log | tail -n +11 | awk '{print $9}' | xargs rm
```

## Error Handling

### Common Errors

**Permission Denied:**
```python
try:
    logger = SessionLogger(log_dir=Path("/root/logs"))
except PermissionError:
    print("Cannot create log directory - permission denied")
```

**Disk Full:**
```python
try:
    logger.write("Test message", "INFO")
except OSError as e:
    print(f"Failed to write log: {e}")
```

**Write After Close:**
```python
logger = SessionLogger()
logger.close()

try:
    logger.write("Test", "INFO")
except ValueError:
    print("Cannot write to closed logger")
```

## Performance Considerations

### Immediate Flush
- Each `write()` call flushes to disk immediately
- Ensures logs survive crashes
- Slight performance overhead (~microseconds per write)
- Acceptable for debugging/audit trail use case

### High-Volume Logging
```python
# For applications with 1000+ logs/second, consider:
# 1. Use keep_last=0 initially (faster initialization)
# 2. Batch cleanup separately
# 3. Or use Python's logging module for high-performance needs

logger = SessionLogger(keep_last=0)  # Skip cleanup on init
```

## Testing

### Unit Test Example
```python
import tempfile
from pathlib import Path
from gmailarchiver.output import SessionLogger

def test_session_logger():
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = SessionLogger(log_dir=Path(tmpdir))

        logger.write("Test message", "INFO")
        logger.close()

        content = logger.log_file.read_text()
        assert "INFO" in content
        assert "Test message" in content
```

## Troubleshooting

### Issue: Logs not appearing
```python
# Check that logger is closed or flushed
logger.close()  # Explicit close
# Or use context manager (auto-closes)
```

### Issue: Permission errors
```bash
# Check directory permissions
ls -ld ~/.config/gmailarchiver/logs

# Fix if needed (Linux/macOS)
chmod 755 ~/.config/gmailarchiver/logs
```

### Issue: Disk space
```bash
# Check available space
df -h ~/.config/gmailarchiver

# Clean up old logs manually if needed
rm ~/.config/gmailarchiver/logs/session_2024-*.log
```

## Best Practices

1. **Use context manager**: Ensures proper cleanup
2. **Log all severities**: DEBUG for diagnostics, INFO for operations
3. **Close after use**: Prevent file handle leaks
4. **Configure retention**: Balance disk space vs. history needs
5. **Monitor disk space**: In long-running applications
6. **Include context**: Add operation IDs, user IDs in messages

## Example: Complete Application

```python
from gmailarchiver.output import SessionLogger, LogBuffer
from pathlib import Path

def main():
    # Initialize logging
    buffer = LogBuffer(max_visible=10)

    with SessionLogger(keep_last=15) as logger:
        def log(msg: str, level: str = "INFO"):
            buffer.add(msg, level)
            logger.write(msg, level)

        try:
            log("Application started", "INFO")
            log("Debug: Config loaded from ~/.config/myapp", "DEBUG")

            # Main operation
            log("Processing 1000 items", "INFO")
            for i in range(1000):
                if i % 100 == 0:
                    log(f"Progress: {i}/1000", "INFO")

            log("Operation completed successfully", "SUCCESS")

        except Exception as e:
            log(f"Fatal error: {e}", "ERROR")
            raise

        finally:
            log("Application shutting down", "INFO")

    # Log file automatically closed here
    print(f"Session logs saved to: {logger.log_file}")

if __name__ == "__main__":
    main()
```

## API Reference

### SessionLogger Class

```python
class SessionLogger:
    def __init__(
        self,
        log_dir: Path | None = None,  # None = XDG default
        keep_last: int = 10            # 0 = keep all
    ) -> None

    def write(
        self,
        message: str,
        level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR, SUCCESS
    ) -> None

    def close(self) -> None

    # Context manager support
    def __enter__(self) -> SessionLogger
    def __exit__(...) -> None

    # Properties
    log_dir: Path      # Directory containing log files
    log_file: Path     # Current session log file
```

### Static Methods

```python
@staticmethod
def _get_default_log_dir() -> Path
    """Get XDG-compliant default log directory."""
```

## See Also

- `LogBuffer`: In-memory ring buffer for UI display
- `OutputManager`: Unified output system for commands
- `ARCHITECTURE.md`: System architecture documentation
