from dataclasses import dataclass


@dataclass
class UserEntity:
    user_id: str
    username: str
    name: str
    role: str
    password_hash: str
    tenant_id: str = "line-a"
    tenant_name: str = ""
