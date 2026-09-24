from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status

from tollbooth.api.budget_schemas import (
    BudgetCreate,
    BudgetOut,
    BudgetUpdate,
    Scope,
    apply_update,
    scope_value,
    to_nanousd,
)
from tollbooth.deps import State, require_admin
from tollbooth.domain import Budget, BudgetScope
from tollbooth.security import new_id

router = APIRouter(prefix="/admin/budgets", tags=["budgets"], dependencies=[Depends(require_admin)])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_budget(body: BudgetCreate, state: State) -> BudgetOut:
    await _check_scope(body.scope, state)
    now = datetime.now(UTC)
    budget = Budget(
        id=new_id(),
        name=body.name,
        scope=body.scope.type,
        scope_value=scope_value(body.scope),
        period=body.period,
        limit_nanousd=to_nanousd(body.limit_usd),
        enforcement=body.enforcement,
        thresholds=tuple(body.thresholds),
        enabled=body.enabled,
        created_at=now,
        updated_at=now,
    )
    await state.budgets.create(budget)
    state.budget_tracker.invalidate()
    return BudgetOut.of(await state.budget_tracker.usage(budget))


@router.get("")
async def list_budgets(state: State) -> list[BudgetOut]:
    budgets = await state.budgets.list_all()
    return [BudgetOut.of(await state.budget_tracker.usage(b)) for b in budgets]


@router.get("/{budget_id}")
async def get_budget(budget_id: str, state: State) -> BudgetOut:
    budget = await _existing(budget_id, state)
    return BudgetOut.of(await state.budget_tracker.usage(budget))


@router.patch("/{budget_id}")
async def update_budget(budget_id: str, body: BudgetUpdate, state: State) -> BudgetOut:
    budget = await _existing(budget_id, state)
    if body.scope is not None:
        await _check_scope(body.scope, state)
    updated = apply_update(budget, body, datetime.now(UTC))
    if not await state.budgets.update(updated):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "budget not found")
    state.budget_tracker.invalidate()
    return BudgetOut.of(await state.budget_tracker.usage(updated))


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_budget(budget_id: str, state: State) -> Response:
    if not await state.budgets.delete(budget_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "budget not found")
    state.budget_tracker.invalidate()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _existing(budget_id: str, state: State) -> Budget:
    budget = await state.budgets.get(budget_id)
    if budget is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "budget not found")
    return budget


async def _check_scope(scope: Scope, state: State) -> None:
    if scope.type is BudgetScope.KEY and await state.keys.get(scope_value(scope) or "") is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "virtual key not found")
