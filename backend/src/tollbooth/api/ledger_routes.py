from typing import Annotated

from fastapi import APIRouter, Depends, Query

from tollbooth.api.ledger_schemas import (
    RequestPage,
    RequestsQuery,
    SpendQuery,
    SpendReport,
    TimeseriesQuery,
    TimeseriesReport,
)
from tollbooth.deps import State, require_admin

router = APIRouter(prefix="/admin", tags=["ledger"], dependencies=[Depends(require_admin)])


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
