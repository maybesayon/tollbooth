from collections.abc import Iterable

HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
_REQUEST_DROP = HOP_BY_HOP | {
    "host",
    "content-length",
    "accept-encoding",
    "authorization",
    "x-api-key",
    "cookie",
    "forwarded",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-real-ip",
}
_RESPONSE_DROP = HOP_BY_HOP | {"content-length", "content-encoding", "set-cookie"}


def upstream_request_headers(
    incoming: Iterable[tuple[str, str]], auth: dict[str, str]
) -> dict[str, str]:
    """Client headers minus credentials and transport headers, plus the real provider auth.

    Accept-Encoding is dropped so httpx negotiates compression itself and hands us decoded bytes.
    """
    headers = {k.lower(): v for k, v in incoming if k.lower() not in _REQUEST_DROP}
    return headers | auth


def client_response_headers(upstream: Iterable[tuple[str, str]]) -> dict[str, str]:
    return {k: v for k, v in upstream if k.lower() not in _RESPONSE_DROP}
