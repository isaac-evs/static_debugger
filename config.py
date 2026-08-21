from enum import Enum
from pathlib import Path

MAIN_DIR = Path(__file__).parent.resolve()
WORKING_DIR = MAIN_DIR.joinpath('temp')

class ConnectionStatus(Enum):
    Undefined = 0
    Secured = 1
    Established = 2

APP_SETTINGS = {}
DB_STATUS = ConnectionStatus.Undefined
TEST_TIMEOUT = 1
TIMEOUT_SIGNAL_RECEIVED = 0


