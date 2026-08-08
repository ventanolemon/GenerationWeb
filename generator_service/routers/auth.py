"""
Авторизация и управление профилем.

POST   /auth/login               — вход по логину/паролю, выдаёт токен сессии
POST   /auth/logout              — выход, гасит предъявленную сессию
GET    /auth/me                  — кто я по токену (личность с сервера)
POST   /auth/register            — регистрация нового пользователя
GET    /auth/profile/{login}     — данные профиля
PATCH  /auth/profile/{login}     — обновить профиль (имя, группа, email, about, цвет)
POST   /auth/change-password     — сменить пароль

Профиль правит только его владелец (или админ). Раньше здесь не
проверялось вообще ничего: `PATCH /auth/profile/root` без единого
заголовка переписывал ФИО администратора. Найдено замером перед §8,
см. organizations_readiness.md.
"""

from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from core import auth_sessions

from .. import identity

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
def login(body: LoginRequest, request: Request,
          user_agent: Optional[str] = Header(default=None)) -> dict:
    """
    Вход. Возвращает профиль И токен сессии.

    Токен добавлен к прежнему ответу, а не заменил его: фронт и десктоп
    продолжают читать те же поля профиля, и переход на токены не требует
    менять всё разом.
    """
    repo = request.app.state.repo
    profile = repo.find_user(body.login, body.password)
    if profile is None:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    session = auth_sessions.issue(repo, profile.login,
                                  user_agent=user_agent or "")
    return {**profile.to_dict(),
            "token": session["token"],
            "expires_at": session["expires_at"]}


@router.post("/logout")
def logout(request: Request,
           authorization: Optional[str] = Header(default=None)) -> dict:
    """Выход. Идемпотентен: гасить нечего — тоже успех."""
    token = auth_sessions.bearer_token(authorization)
    revoked = auth_sessions.revoke(request.app.state.repo, token)
    return {"ok": True, "revoked": revoked}


@router.get("/me")
def me(request: Request,
       authorization: Optional[str] = Header(default=None),
       x_user_id: Optional[str] = Header(default=None),
       x_user_role: Optional[str] = Header(default=None)) -> dict:
    """
    Кто я — по мнению СЕРВЕРА.

    Нужна фронту, чтобы гейтить витрины по роли из БД, а не по той, что он
    сам про себя помнит в localStorage. `verified` говорит прямо, заверена
    личность токеном или пока лишь заявлена заголовком.
    """
    who = identity.require(request, authorization, x_user_id, x_user_role)
    profile = request.app.state.repo.get_user_profile(who.login)
    return {"login": who.login, "role": who.role,
            "verified": who.verified, "source": who.source,
            "profile": profile.to_dict() if profile else None}


@router.post("/register", status_code=201)
def register(body: RegisterRequest, request: Request,
             user_agent: Optional[str] = Header(default=None)) -> dict:
    """Регистрация сразу выдаёт сессию: иначе только что заведённый
    пользователь оказывался неопознанным до отдельного входа."""
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
    session = auth_sessions.issue(repo, profile.login,
                                  user_agent=user_agent or "")
    return {**profile.to_dict(),
            "token": session["token"],
            "expires_at": session["expires_at"]}


@router.get("/profile/{login}")
def get_profile(login: str, request: Request) -> dict:
    repo = request.app.state.repo
    profile = repo.get_user_profile(login)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Пользователь {login!r} не найден")
    return profile.to_dict()


@router.patch("/profile/{login}")
def update_profile(login: str, body: UpdateProfileRequest, request: Request,
                   authorization: Optional[str] = Header(default=None),
                   x_user_id: Optional[str] = Header(default=None),
                   x_user_role: Optional[str] = Header(default=None)) -> dict:
    """Профиль правит владелец или админ. До этого — кто угодно и чей угодно."""
    who = identity.require(request, authorization, x_user_id, x_user_role)
    if who.login != login and who.role != "admin":
        raise HTTPException(status_code=403,
                            detail="Чужой профиль правит только администратор.")
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
    # Сменивший пароль вправе считать, что старые входы больше не работают:
    # ради этого пароль обычно и меняют. Гасим ВСЕ сессии, включая текущую, —
    # «кроме своей» потребовало бы доверять предъявленному токену там, где
    # пользователь как раз объявляет прежний доступ скомпрометированным.
    revoked = auth_sessions.revoke_all(request.app.state.repo, body.login)
    return {"ok": True, "sessions_revoked": revoked}
