"""
This module checks the `ConnectionStatus`
of a given database's settings.
"""
import sqlite3
import json
import config as DebugController
from config import ConnectionStatus
import logger as AbinLogging


def test_db_connection(db_path: str = 'patterns.db', 
                        dbcollection: str = 'BugPatterns',
                        retry_times:int = 3) -> ConnectionStatus:
    """ This function tests the connection status given
    the connection paramaters.
        
    :param db_path: The database that will be tested for conectivity.
    :type  db_path: str
    :param dbcollection: The collection that will be tested for conectivity.
    :type  dbcollection: str
    :param retry_times: The number of retries to connect to the DB.
    :type  retry_times: int
    :rtype: ConnectionStatus
    """
    AbinLogging.dbConnection_logger.info(
        f"<pre>Testing connection on {db_path}...\n\n</pre>"
    )
    for _ in range(retry_times):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
        except Exception as e:
            AbinLogging.dbConnection_logger.info(
                f"<pre>Unable to establish a connection. {e}</pre>"
            )
        else:
            break
    else:
        AbinLogging.dbConnection_logger.info(f"""
            <pre> <span style='color:#f33; font-weight: bold;'>
            Unable to connect to database instance {db_path} after {retry_times} retries.
            </span> </pre>
            """
        )
        return ConnectionStatus.Undefined
    
    AbinLogging.dbConnection_logger.info(
        "<pre>Querying for one pattern...\n\n</pre>"
    )
    try:
        cursor.execute(f"SELECT data FROM {dbcollection} LIMIT 1")
        test_pattern_row = cursor.fetchone()
    except sqlite3.OperationalError:
        test_pattern_row = None
        
    if test_pattern_row is None:
        AbinLogging.dbConnection_logger.info(f"""
            <pre> <span style='color:#ffa500; font-weight: bold;'>
            Unable to retrive data from {db_path}.{dbcollection}\n\n
            </span></pre>
            """
        )
        return ConnectionStatus.Established
    
    test_pattern = json.loads(test_pattern_row[0])
    dump_data = json.dumps(test_pattern, indent=4)
    AbinLogging.dbConnection_logger.info(f"<pre id='json'>{dump_data}\n\n</pre>")
    AbinLogging.dbConnection_logger.info(f"""
        <pre> <span style='color:#008000; font-weight: bold;'>
        Successful conection to {db_path}
        </span> </pre>
        """
    )
    return ConnectionStatus.Secured


if __name__ == "__main__":
    test_db_connection()