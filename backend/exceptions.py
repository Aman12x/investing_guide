class EarningsLensError(Exception):
    pass


class TranscriptNotFoundError(EarningsLensError):
    def __init__(self, ticker: str):
        self.ticker = ticker
        super().__init__(f"No transcript found for {ticker}")


class ClaudeError(EarningsLensError):
    pass


class RedditError(EarningsLensError):
    pass


class NewsError(EarningsLensError):
    pass


class AnalystError(EarningsLensError):
    pass
