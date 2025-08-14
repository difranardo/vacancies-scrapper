from typing import Dict, Optional
from flask_login.mixins import UserMixin

# ─────── Modelo mínimo de usuario ───────
class User(UserMixin):
    def __init__(self, email: str, name: str = "") -> None:
        self.id   = email
        self.name = name or email.split("@", 1)[0]

_USERS: Dict[str, User] = {}

def get_user(uid: str) -> Optional[User]: return _USERS.get(uid)
def set_user(email:str, name:str) -> User: return _USERS.setdefault(email, User(email, name))