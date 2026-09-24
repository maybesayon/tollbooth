from fastapi import APIRouter, Request, Response

from tollbooth.deps import State
from tollbooth.providers import ANTHROPIC, OPENAI
from tollbooth.proxy.handler import proxy

router = APIRouter(tags=["proxy"])


@router.post(OPENAI.path)
async def openai_chat_completions(request: Request, state: State) -> Response:
    return await proxy(request, OPENAI, state)


@router.post(ANTHROPIC.path)
async def anthropic_messages(request: Request, state: State) -> Response:
    return await proxy(request, ANTHROPIC, state)
