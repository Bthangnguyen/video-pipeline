class DouyinSearchError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def to_payload(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }


INVALID_KEYWORD = "INVALID_KEYWORD"
MISSING_COOKIE_FILE = "MISSING_COOKIE_FILE"
COOKIE_EXPIRED = "COOKIE_EXPIRED"
LOGIN_REQUIRED = "LOGIN_REQUIRED"
CHALLENGE_REQUIRED = "CHALLENGE_REQUIRED"
NO_RESULTS = "NO_RESULTS"
DIRECT_API_FAILED = "DIRECT_API_FAILED"
BROWSER_SEARCH_FAILED = "BROWSER_SEARCH_FAILED"
RESULT_EXPIRED = "RESULT_EXPIRED"
STREAM_RESOLVE_FAILED = "STREAM_RESOLVE_FAILED"
NETWORK_ERROR = "NETWORK_ERROR"
UNKNOWN_ERROR = "UNKNOWN_ERROR"

