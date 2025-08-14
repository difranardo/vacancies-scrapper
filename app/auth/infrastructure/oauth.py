from __future__ import annotations
from typing import Tuple
from authlib.integrations.flask_client import OAuth
from flask import Flask

from app.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET

# ─────── Cliente OAuth (Authlib) ───────
oauth = OAuth()
oauth.register(
    name               = "google",
    client_id          = GOOGLE_CLIENT_ID,
    client_secret      = GOOGLE_CLIENT_SECRET,
    server_metadata_url= "https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs      = {"scope": "openid email profile"},
)

def authorize_redirect(redirect_uri:str,nonce:str):
  return oauth.google.authorize_redirect(
        redirect_uri = redirect_uri,
        prompt       = "select_account",
        nonce        = nonce,
  )

def get_user_email(nonce:str)->Tuple[str, str]:
  token  = oauth.google.authorize_access_token(verify=False)
  info   = oauth.google.parse_id_token(token, nonce)
  return info.get("email","").lower(), info.get("name","")

def init_oauth(app:Flask):
  oauth.init_app(app)