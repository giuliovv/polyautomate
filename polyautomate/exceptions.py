class PolymarketAPIError(RuntimeError):
    """Raised when the Polymarket API responds with an error status code."""

    def __init__(self, status_code: int, message: str, *, payload=None):
        detail = f"HTTP {status_code}: {message}"
        super().__init__(detail)
        self.status_code = status_code
        self.payload = payload or {}
