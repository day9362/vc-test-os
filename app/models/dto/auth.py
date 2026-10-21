from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    tenant: str = Field(min_length=1, max_length=64)
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    token: str


class TenantOut(BaseModel):
    tenant_id: str
    name: str


class MeOut(BaseModel):
    user_id: str
    name: str
    role: str
    tenant_id: str
    tenant_name: str
