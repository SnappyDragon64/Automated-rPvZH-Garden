import time
from datetime import datetime
import pytz


class TimeHelper:
    """A static helper class for standardized time and date operations."""
    EST = pytz.timezone('US/Eastern')

    @staticmethod
    def get_est_date() -> str:
        return datetime.now(TimeHelper.EST).strftime('%Y-%m-%d')

    @staticmethod
    def get_current_timestamp() -> int:
        """Returns the current Unix timestamp as an integer."""
        return int(time.time())