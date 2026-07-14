from __future__ import annotations

import logging
import os
import sys


RESET = "\033[0m"
COLORS = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[35;1m",
}
STAGE_COLORS = {
    "HTTP": "\033[36;1m",
    "PIPE": "\033[35;1m",
    "CACHE": "\033[34;1m",
    "DB": "\033[32;1m",
    "MS": "\033[33;1m",
    "AI": "\033[31;1m",
    "TG": "\033[36;1m",
    "WS": "\033[35m",
}


class RailwayColorFormatter(logging.Formatter):
    def __init__(self, *, use_color: bool) -> None:
        super().__init__(
            "%(asctime)s %(levelname)-8s %(name)s %(message)s",
            datefmt="%H:%M:%S",
        )
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        original_levelname = record.levelname
        original_msg = record.msg
        if self.use_color:
            level_color = COLORS.get(record.levelname, "")
            record.levelname = f"{level_color}{record.levelname}{RESET}"
            stage = getattr(record, "stage", "")
            if stage:
                stage_color = STAGE_COLORS.get(str(stage), "\033[37;1m")
                record.msg = f"{stage_color}[{stage}]{RESET} {record.msg}"
        try:
            return super().format(record)
        finally:
            record.levelname = original_levelname
            record.msg = original_msg


def configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    use_color = os.getenv("LOG_COLOR", "1").lower() not in {"0", "false", "no"}

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(RailwayColorFormatter(use_color=use_color))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        logging.getLogger(name).setLevel(level)


def pipeline_log(stage: str, message: str, *args: object, level: int = logging.INFO) -> None:
    logging.getLogger("pipeline").log(level, message, *args, extra={"stage": stage})
