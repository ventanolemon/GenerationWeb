"""
Авторизация и управление профилем.

POST   /auth/login               — вход по логину/паролю
POST   /auth/register            — регистрация нового пользователя
GET    /auth/profile/{login}     — данные профиля
PATCH  /auth/profile/{login}     — обновить профиль (имя, группа, email, about, цвет)
POST   /auth/change-password     — сменить пароль
"""

from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    login: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class RegisterRequest(BaseModel):
    login: str = Field(..., min_length=2, max_length=64,
                       pattern=r"^[A-Za-z0-9_\-\.]+$")
    password: str = Field(..., min_length=4)
    fio: str = Field(..., min_length=1, max_length=200)
    group: str = Field("", max_length=100)
    email: str = Field("", max_length=200)


class UpdateProfileRequest(BaseModel):
    fio: str = Field(..., min_length=1, max_length=200)
    group: str = Field("", max_length=100)
    email: str = Field("", max_length=200)
    about: str = Field("", max_length=2000)
    avatar_color: str = Field("", max_length=32)


class ChangePasswordRequest(BaseModel):
    login: str = Field(..., min_length=1)
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=4)


@router.post("/login")
def login(body: LoginRequest, request: Request) -> dict:
    repo = request.app.state.repo
    profile = repo.find_user(body.login, body.password)
    if profile is None:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    return profile.to_dict()


@router.post("/register", status_code=201)
def register(body: RegisterRequest, request: Request) -> dict:
    repo = request.app.state.repo
    ok = repo.create_user(
        login=body.login,
        password=body.password,
        fio=body.fio,
        group=body.group,
        email=body.email,
    )
    if not ok:
        raise HTTPException(
            status_code=409,
            detail=f"Пользователь с логином «{body.login}» уже существует"
        )
    profile = repo.get_user_profile(body.login)
    return profile.to_dict()


@router.get("/profile/{login}")
def get_profile(login: str, request: Request) -> dict:
    repo = request.app.state.repo
    profile = repo.get_user_profile(login)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Пользователь {login!r} не найден")
    return profile.to_dict()


@router.patch("/profile/{login}")
def update_profile(login: str, body: UpdateProfileRequest, request: Request) -> dict:
    repo = request.app.state.repo
    ok = repo.update_user_profile(
        login=login,
        fio=body.fio,
        group=body.group,
        email=body.email,
        about=body.about,
        avatar_color=body.avatar_color,
    )
    if not ok:
        raise HTTPException(status_code=404, detail=f"Пользователь {login!r} не найден")
    profile = repo.get_user_profile(login)
    return profile.to_dict()


@router.post("/change-password")
def change_password(body: ChangePasswordRequest, request: Request) -> dict:
    repo = request.app.state.repo
    ok = repo.change_user_password(
        login=body.login,
        current_password=body.current_password,
        new_password=body.new_password,
    )
    if not ok:
        raise HTTPException(status_code=401, detail="Неверный текущий пароль")
    return {"ok": True}
