import csv
import io
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from tollbooth.api.ledger_schemas import (
    LedgerQuery,
    RequestOut,
    RequestPage,
    RequestsQuery,
    SpendQuery,
    SpendReport,
    TimeseriesQuery,
    TimeseriesReport,
)
from tollbooth.deps import State, require_viewer
from tollbooth.repositories.base import LedgerCursor, LedgerFilter, LedgerRepository

EXPORT_BATCH = 1000

router = APIRouter(prefix="/admin", tags=["ledger"], dependencies=[Depends(require_viewer)])


@router.get("/spend")
async def spend(query: Annotated[SpendQuery, Query()], state: State) -> SpendReport:
    rows = await state.ledger.spend(query.group_by, query.to_filter())
    return SpendReport.of(query, rows)


@router.get("/spend/timeseries")
async def spend_timeseries(
    query: Annotated[TimeseriesQuery, Query()], state: State
) -> TimeseriesReport:
    points = await state.ledger.timeseries(query.interval, query.group_by, query.to_filter())
    return TimeseriesReport.of(query, points)


@router.get("/requests")
async def requests(query: Annotated[RequestsQuery, Query()], state: State) -> RequestPage:
    entries = await state.ledger.page(
        query.to_filter(), limit=query.limit + 1, after=query.decoded_cursor()
    )
    return RequestPage.of(entries, query.limit)


@router.get("/requests.csv", response_class=StreamingResponse)
async def requests_csv(query: Annotated[LedgerQuery, Query()], state: State) -> StreamingResponse:
    """Every matching ledger entry, newest first, with the same fields as `/requests`."""
    return StreamingResponse(
        _csv_chunks(state.ledger, query.to_filter()),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="tollbooth-requests.csv"'},
    )


async def _csv_chunks(ledger: LedgerRepository, ledger_filter: LedgerFilter) -> AsyncIterator[str]:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(RequestOut.model_fields))
    writer.writeheader()
    after = None
    while True:
        entries = await ledger.page(ledger_filter, limit=EXPORT_BATCH, after=after)
        for entry in entries:
            row = RequestOut.of(entry).model_dump(mode="json")
            writer.writerow({key: _cell(value) for key, value in row.items()})
        yield buffer.getvalue()
        if len(entries) < EXPORT_BATCH:
            return
        buffer.seek(0)
        buffer.truncate()
        after = LedgerCursor(entries[-1].created_at, entries[-1].id)


def _cell(value: object) -> object:
    # Spreadsheets run text starting with these as a formula; model names come from clients.
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value
