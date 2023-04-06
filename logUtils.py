import logging

grey = "\x1b[38;20m"
yellow = "\x1b[33;20m"
red = "\x1b[31;20m"
bold_red = "\x1b[31;1m"
reset = "\x1b[0m"
green = "\x1b[32;20m"
blue = "\x1b[34;20m"
orange = "\x1b[38;5;208m"



logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

LOG_ERRORS = True

def info(message):
    logger.info(f"{grey}{message}{reset}")

def warn(message):
    logger.warning(f"{yellow}{message}{reset}")

def error(message):
    if LOG_ERRORS:
        logger.error(f"{red}{message}{reset}")