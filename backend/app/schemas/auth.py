"""认证相关 schema（契约同源：docs/14 §3 LoginRequest/RefreshRequest/TokenResponse）。"""

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class CurrentUser(BaseModel):
    """解析后的登录主体（api 层不接触 ORM，跨层只传该 DTO）。"""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    email: str
    role: str  # admin | researcher | viewer
