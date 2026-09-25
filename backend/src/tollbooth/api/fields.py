from typing import Annotated

from pydantic import AfterValidator, Field


def _no_nul(value: str) -> str:
    # Postgres text cannot hold NUL; reject it here instead of failing in the database.
    if "\x00" in value:
        raise ValueError("must not contain NUL characters")
    return value


Name = Annotated[str, Field(min_length=1, max_length=200, pattern=r"\S"), AfterValidator(_no_nul)]
Text = Annotated[str, Field(max_length=200), AfterValidator(_no_nul)]
