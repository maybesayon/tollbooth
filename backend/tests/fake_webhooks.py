"""In-process receiver for alert webhooks, used as the notification transport."""

import json
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class Received:
    url: str
    headers: httpx.Headers
    body: bytes

    @property
    def json(self) -> Any:
        return json.loads(self.body)


class WebhookReceiver:
    def __init__(self) -> None:
        self.received: list[Received] = []
        self.failures_left: dict[str, int] = {}
        self.unreachable: set[str] = set()

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def to(self, host: str) -> list[Received]:
        return [r for r in self.received if httpx.URL(r.url).host == host]

    async def handle(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host in self.unreachable:
            raise httpx.ConnectError(f"cannot reach {request.url}", request=request)
        self.received.append(Received(str(request.url), request.headers, await request.aread()))
        if self.failures_left.get(host, 0) > 0:
            self.failures_left[host] -= 1
            return httpx.Response(500, text="receiver error")
        return httpx.Response(200, text="ok")
