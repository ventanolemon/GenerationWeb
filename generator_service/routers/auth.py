"""
POST /auth/login — проверка логина/пароля из таблицы users.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    login: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


@router.post("/login")
def login(body: LoginRequest, request: Request) -> dict:
    repo = request.app.state.repo
    user = repo.find_user(body.login, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    return {"login": user[0], "fio": user[1], "group": user[2]}
