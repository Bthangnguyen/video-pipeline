class PinterestSearchError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def to_payload(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


INVALID_KEYWORD = "INVALID_KEYWORD"
MISSING_COOKIE_FILE = "MISSING_COOKIE_FILE"
LOGIN_REQUIRED = "LOGIN_REQUIRED"
CHALLENGE_REQUIRED = "CHALLENGE_REQUIRED"
NO_RESULTS = "NO_RESULTS"
BROWSER_SEARCH_FAILED = "BROWSER_SEARCH_FAILED"
RESULT_EXPIRED = "RESULT_EXPIRED"
NETWORK_ERROR = "NETWORK_ERROR"
