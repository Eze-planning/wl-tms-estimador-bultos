"""
auth.py
=======
Autenticación JWT y gestión de usuarios para TMS Wild Lama.
Usuarios almacenados en users.json con contraseñas hasheadas con bcrypt.
"""
import os
import json
import uuid
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext

SECRET_KEY  = os.getenv("JWT_SECRET", "wl-tms-secret-change-in-production")
ALGORITHM   = "HS256"
TOKEN_HOURS = 24 * 7   # 7 días

USERS_PATH  = Path(__file__).parent / "users.json"

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# Matriz de permisos por rol
# ---------------------------------------------------------------------------
ROLES: dict[str, dict] = {
    "admin":       {"tabs": ["estimador", "despachos", "prog", "admin"], "edit": True,  "costos": True},
    "logistica":   {"tabs": ["estimador", "despachos", "prog"],          "edit": True,  "costos": True},
    "readonly":    {"tabs": ["estimador", "despachos", "prog"],          "edit": False, "costos": True},
    "bodega":      {"tabs": ["prog"],                                    "edit": False, "costos": False},
    "transportes": {"tabs": ["prog"],                                    "edit": False, "costos": False},
}

# ---------------------------------------------------------------------------
# Persistencia de usuarios
# ---------------------------------------------------------------------------
def _load_users() -> dict:
    if not USERS_PATH.exists():
        default = {"users": [{
            "id":       str(uuid.uuid4())[:8],
            "username": "admin",
            "password": pwd_ctx.hash("admin123"),
            "role":     "admin",
            "nombre":   "Administrador",
            "activo":   True,
        }]}
        _save_users(default)
        return default
    with open(USERS_PATH, encoding="utf-8") as f:
        return json.load(f)

def _save_users(data: dict):
    with open(USERS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _safe(user: dict) -> dict:
    return {k: v for k, v in user.items() if k != "password"}

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate_user(username: str, password: str) -> Optional[dict]:
    users = _load_users()["users"]
    user  = next((u for u in users
                  if u["username"] == username and u.get("activo", True)), None)
    if not user or not pwd_ctx.verify(password, user["password"]):
        return None
    return user

def create_token(user: dict) -> str:
    payload = {
        "sub":    user["id"],
        "usr":    user["username"],
        "role":   user["role"],
        "nombre": user.get("nombre", user["username"]),
        "exp":    datetime.utcnow() + timedelta(hours=TOKEN_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------
def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    if not creds:
        raise HTTPException(status_code=401, detail="No autenticado")
    try:
        return jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")

def require_edit(user: dict = Depends(get_current_user)) -> dict:
    if not ROLES.get(user.get("role"), {}).get("edit"):
        raise HTTPException(status_code=403, detail="Sin permiso de edición")
    return user

def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    return user

# ---------------------------------------------------------------------------
# CRUD de usuarios
# ---------------------------------------------------------------------------
def get_all_users() -> list:
    return [_safe(u) for u in _load_users()["users"]]

def create_user(username: str, password: str, role: str, nombre: str) -> dict:
    if role not in ROLES:
        raise ValueError(f"Rol inválido: {role}")
    data = _load_users()
    if any(u["username"] == username for u in data["users"]):
        raise ValueError(f"Usuario '{username}' ya existe")
    new_user = {
        "id":       str(uuid.uuid4())[:8],
        "username": username,
        "password": pwd_ctx.hash(password),
        "role":     role,
        "nombre":   nombre,
        "activo":   True,
    }
    data["users"].append(new_user)
    _save_users(data)
    return _safe(new_user)

def update_user(user_id: str, cambios: dict) -> dict:
    data = _load_users()
    user = next((u for u in data["users"] if u["id"] == user_id), None)
    if not user:
        raise ValueError("Usuario no encontrado")
    if "role" in cambios and cambios["role"] not in ROLES:
        raise ValueError(f"Rol inválido: {cambios['role']}")
    if cambios.get("password"):
        cambios["password"] = pwd_ctx.hash(cambios["password"])
    else:
        cambios.pop("password", None)
    user.update(cambios)
    _save_users(data)
    return _safe(user)

def delete_user(user_id: str, requesting_id: str):
    if user_id == requesting_id:
        raise ValueError("No podés eliminar tu propio usuario")
    data = _load_users()
    original = len(data["users"])
    data["users"] = [u for u in data["users"] if u["id"] != user_id]
    if len(data["users"]) == original:
        raise ValueError("Usuario no encontrado")
    _save_users(data)
