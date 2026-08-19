import logging

_SENSITIVE_HTTP_LOGGERS = ("httpx", "httpcore")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    for logger_name in _SENSITIVE_HTTP_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
