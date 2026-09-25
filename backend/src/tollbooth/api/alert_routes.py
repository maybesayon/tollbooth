from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from tollbooth.alerts import new_signing_secret, url_hint
from tollbooth.api.alert_schemas import (
    AlertOut,
    ChannelCreate,
    ChannelCreated,
    ChannelOut,
    ChannelTestResult,
)
from tollbooth.deps import Editor, State, require_viewer
from tollbooth.domain import Channel, ChannelType
from tollbooth.repositories.base import DuplicateNameError
from tollbooth.security import new_id

router = APIRouter(prefix="/admin", tags=["alerts"], dependencies=[Depends(require_viewer)])


@router.post("/channels", status_code=status.HTTP_201_CREATED)
async def create_channel(body: ChannelCreate, state: State, principal: Editor) -> ChannelCreated:
    url = str(body.url)
    channel = Channel(
        id=new_id(),
        name=body.name,
        type=body.type,
        url_hint=url_hint(url),
        created_at=datetime.now(UTC),
    )
    secret = new_signing_secret() if body.type is ChannelType.WEBHOOK else None
    try:
        await state.channels.create(
            channel,
            encrypted_url=state.secret_box.encrypt(url),
            encrypted_secret=state.secret_box.encrypt(secret) if secret else None,
        )
    except DuplicateNameError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, "channel name already exists") from e
    return ChannelCreated(**ChannelOut.of(channel).model_dump(), signing_secret=secret)


@router.get("/channels")
async def list_channels(state: State) -> list[ChannelOut]:
    return [ChannelOut.of(c) for c in await state.channels.list_all()]


@router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(channel_id: str, state: State, principal: Editor) -> Response:
    if not await state.channels.delete(channel_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "channel not found")
    state.budget_tracker.invalidate()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/channels/{channel_id}/test")
async def test_channel(channel_id: str, state: State, principal: Editor) -> ChannelTestResult:
    channel = await state.channels.get(channel_id)
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "channel not found")
    result = await state.alert_manager.send_test(channel)
    return ChannelTestResult(ok=result.ok, status_code=result.status_code, error=result.error)


@router.get("/alerts")
async def list_alerts(
    state: State,
    budget_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AlertOut]:
    return [AlertOut.of(a) for a in await state.alerts.recent(limit, budget_id)]
