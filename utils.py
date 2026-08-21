import config
import logger as AbinLogging

def test_timeout_handler(signum: int, frame) -> None:
    """ The timeout handler.
    
    This function triggers the change of the control variable
    <TIMEOUT_SIGNAL_RECEIVED> in order to raise a timeout exception
    in the AbinCollector class.
    """
    config.TIMEOUT_SIGNAL_RECEIVED = 1
    AbinLogging.debugging_logger.info("Current test timeout reached!")
    AbinLogging.debugging_logger.debug(f"""
        Debug Signal changed to: {config.TIMEOUT_SIGNAL_RECEIVED}.
        Signal handler called with signal {signum}.
        """
    )
