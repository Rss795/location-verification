"""Small, application-friendly logging setup for the package."""

import logging


def configure_logging(level: str = "INFO") -> None:
    """Configure standard logging using a validated named level."""

    normalized = level.upper()
    numeric_level = getattr(logging, normalized, None)
    if not isinstance(numeric_level, int) or isinstance(numeric_level, bool):
        raise ValueError(f"unsupported logging level: {level}")
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
