"""券商即時API封裝(永豐Shioaji / 富邦新一代API)，處理即時tick/K線訂閱與訂閱數上限 — 待實作。"""


class BrokerClient:
    def subscribe(self, tickers: list[str]) -> None:
        raise NotImplementedError

    def unsubscribe(self, tickers: list[str]) -> None:
        raise NotImplementedError
