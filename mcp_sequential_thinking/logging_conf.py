import logging
import sys
import time
from contextlib import contextmanager
from typing import Iterator


def configure_logging(name: str = "sequential-thinking") -> logging.Logger:
    """Configure and return a logger with standardized settings.

    Args:
        name: The name for the logger

    Returns:
        logging.Logger: Configured logger instance
    """
    # Configure root logger. stderr only — stdout is the stdio transport's
    # protocol channel and must never carry log output (B7 observability).
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stderr)
        ]
    )

    # Get and return the named logger
    return logging.getLogger(name)


@contextmanager
def log_duration(logger: logging.Logger, operation: str) -> Iterator[None]:
    """Log start/end of ``operation`` with elapsed time in milliseconds.

    Used to make handler stalls (B7) visible in the server logs instead of
    silently hanging.
    """
    start = time.monotonic()
    logger.info(f"{operation} started")
    try:
        yield
    except Exception:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.error(f"{operation} failed after {elapsed_ms:.1f}ms")
        raise
    else:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(f"{operation} completed in {elapsed_ms:.1f}ms")
