import logging
import os
from textwrap import dedent

from dotenv import load_dotenv

load_dotenv()

class ConsoleLogHandler(logging.Handler):
    def emit(self, logRecord: logging.LogRecord):
        message = dedent(str(logRecord.getMessage()))
        print(message)

DISABLE_LOGGING = os.getenv("DISABLE_LOGGING", "false").lower() == "true"
LOGGER_LEVEL = logging.CRITICAL + 1 if DISABLE_LOGGING else getattr(
    logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO
)

CONSOLE_HANDLER = ConsoleLogHandler()
debugging_logger = logging.getLogger('DebuggingLogger')
debugging_logger.setLevel(LOGGER_LEVEL)
debugging_logger.addHandler(CONSOLE_HANDLER)

TEST_DB_HANDLER = ConsoleLogHandler()
dbConnection_logger = logging.getLogger('DBConnLogger')
dbConnection_logger.setLevel(LOGGER_LEVEL)
dbConnection_logger.addHandler(TEST_DB_HANDLER)

MINING_HANDLER = ConsoleLogHandler()
mining_logger = logging.getLogger('MiningLogger')
mining_logger.setLevel(LOGGER_LEVEL)
mining_logger.addHandler(MINING_HANDLER)
