"""
Sign in with ChatGPT — a student's ChatGPT Plus/Pro plan as MrSOLIS's online brain (2026-11-11).

OpenAI's "Sign in with ChatGPT" with ChatGPT plan usage (developers.openai.com/siwc, the open-source / self-serve
flow): OAuth 2.0 with PKCE in the student's own browser and a loopback redirect to this computer
(http://127.0.0.1:<port>/auth/callback), then inference on the public Responses API (POST /v1/responses) with the
student's access token. The usage comes out of the student's ChatGPT plan; no API key, no MrSOLIS server.

NOT OFFERED YET. A paid app may offer ChatGPT plan usage only after OpenAI accepts it (the user sent OpenAI's interest
form on 2026-11-11). Until then ENABLED stays False and the installed app shows nothing of this; a dev run can try it
with MRSOLIS_CHATGPT_PLAN=1. When OpenAI accepts MrSOLIS: set ENABLED (and PARTNER_CLIENT_ID if OpenAI issues one),
use OpenAI's own "Continue with ChatGPT" button assets, and update TERMS-OF-USE.md 6.6 and the website — see CLAUDE.md.

OpenAI's rules followed here: store=false and stream=true on every request; no temperature / max_output_tokens /
top_p / metadata / user / previous_response_id; system prompts go in `instructions` (system-role items are rejected);
success only on response.completed; plan permission only when the token response grants chatgpt.tokens.use.direct;
refresh tokens rotate (the newest is saved at once, refreshes one at a time); credentials are kept through network
trouble and cleared only on a terminal refresh error; "Using ChatGPT plan" + "Manage usage" (chatgpt.com/settings/usage).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, quote, urlencode, urlparse

import httpx

try:
    from backend import cloud
except ImportError:                          # the frozen app's flat layout
    import cloud

ENABLED = False                              # True once OpenAI accepts MrSOLIS for ChatGPT plan usage
PARTNER_CLIENT_ID = ""                       # an "oaiapp_…" client ID, if OpenAI issues one; "" = self-registration

AUTH = "https://auth.openai.com"
AUTHORIZE = AUTH + "/api/accounts/authorize"
TOKEN = AUTH + "/api/accounts/oauth/token"
JWKS = AUTH + "/.well-known/jwks.json"
DISCOVERY = AUTH + "/.well-known/openid-configuration"
API = "https://api.openai.com/v1"                # where requests go
RESOURCE = "https://api.openai.com/v1"           # what the tokens are for (OAuth resource): always this
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
USAGE_URL = "https://chatgpt.com/settings/usage"
APP_NAME = "MrSOLIS"
DYNAMIC = "dynamic_agent_client"
_TERMINAL = {"invalid_grant", "invalid_refresh_token", "token_expired", "refresh_token_expired",
             "refresh_token_invalidated", "refresh_token_reused"}

FLOW = {"state": "idle", "error": "", "started": 0.0}      # the sign-in in progress (never the secrets)
_PENDING: dict = {}                                        # state, nonce, verifier, redirect, client_id
_SERVER = {"httpd": None}
_LOCK = threading.Lock()
_REFRESH = {"lock": None}


def enabled() -> bool:
    if ENABLED:
        return True
    return not getattr(sys, "frozen", False) and os.environ.get("MRSOLIS_CHATGPT_PLAN") == "1"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64url(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ══════════════════════════════════════════════════════════════════════
#   what is kept (online-brain.json → providers.chatgpt; the tokens sealed with DPAPI like an API key)
# ══════════════════════════════════════════════════════════════════════
def _prov() -> dict:
    return cloud._prov("chatgpt")


def session() -> dict | None:
    sealed = _prov().get("session")
    if not sealed:
        return None
    try:
        return json.loads(cloud._unseal(sealed) or "null")
    except ValueError:
        return None


def _save_session(sess: dict | None):
    p = _prov()
    if sess:
        p["session"] = cloud._seal(json.dumps(sess))
        p["email"] = sess.get("email", "")
        p["plan"] = PLAN_SCOPE in sess.get("scopes", [])
        p["client_id"] = sess.get("client_id", p.get("client_id", ""))
    else:
        p.pop("session", None)
        p["plan"] = False
    cloud._write()


def _host_id() -> str:
    """Opaque and stable for this computer (OpenAI: one per host, urn:uuid form), never anything about the student."""
    p = _prov()
    if not p.get("host_id"):
        p["host_id"] = "urn:uuid:" + str(uuid.uuid4())
        cloud._write()
    return p["host_id"]


def signed_in() -> bool:
    s = session()
    return bool(s and s.get("access_token"))


def plan_ok() -> bool:
    s = session()
    return bool(s and s.get("access_token") and PLAN_SCOPE in s.get("scopes", []))


def state() -> dict:
    p = _prov()
    return {"signed_in": signed_in(), "plan": plan_ok(), "email": p.get("email", "") if signed_in() else "",
            "flow": dict(FLOW), "welcomed": bool(p.get("welcomed")), "usage_url": USAGE_URL}


def mark_welcomed():
    _prov()["welcomed"] = True
    cloud._write()


# ══════════════════════════════════════════════════════════════════════
#   signing in: PKCE in the browser, the redirect back to 127.0.0.1
# ══════════════════════════════════════════════════════════════════════
_DONE_PAGE = """<!doctype html><meta charset="utf-8"><title>MrSOLIS</title>
<body style="margin:0;display:grid;place-items:center;height:100vh;background:#000;color:#fff;font:16px system-ui,sans-serif">
<div style="max-width:420px;text-align:center;line-height:1.5"><h1 style="font-size:22px">{title}</h1><p>{body}</p></div></body>"""


class _Callback(BaseHTTPRequestHandler):
    def log_message(self, *args):            # no request lines (they carry the code) in any log
        pass

    def do_GET(self):
        u = urlparse(self.path)
        if u.path != "/auth/callback":
            self.send_response(404)
            self.end_headers()
            return
        title, body = _finish(parse_qs(u.query))
        page = _DONE_PAGE.format(title=html.escape(title), body=html.escape(body)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)
        if FLOW["state"] in ("done", "declined", "error"):
            threading.Thread(target=stop_signin, daemon=True).start()


def start_signin(consent: bool = False) -> str:
    """Opens the one-time listener on 127.0.0.1 and returns the page to open in the student's browser.
    `consent`: ask again for plan usage (the student had said no to it)."""
    if not enabled():
        raise cloud.CloudError("ChatGPT plans aren't available in MrSOLIS yet.")
    stop_signin()
    sess = session()
    p = _prov()
    client_id = PARTNER_CLIENT_ID or (sess or {}).get("client_id") or p.get("client_id") or DYNAMIC
    verifier = _b64url(secrets.token_bytes(48))                       # 64 characters
    pending = {"state": _b64url(secrets.token_bytes(24)), "nonce": _b64url(secrets.token_bytes(24)),
               "verifier": verifier, "client_id": client_id}
    httpd = HTTPServer(("127.0.0.1", 0), _Callback)
    pending["redirect"] = f"http://127.0.0.1:{httpd.server_address[1]}/auth/callback"
    params = {"client_id": client_id, "response_type": "code", "redirect_uri": pending["redirect"], "scope": SCOPES,
              "resource": RESOURCE, "state": pending["state"], "nonce": pending["nonce"], "code_challenge_method": "S256",
              "code_challenge": _b64url(hashlib.sha256(verifier.encode("ascii")).digest()),
              "ext_agent_host_id": _host_id()}
    if client_id == DYNAMIC:
        params["agent_name_hint"] = APP_NAME
    elif sess and sess.get("id_token"):
        params["id_token_hint"] = sess["id_token"]
        if sess.get("email"):
            params["login_hint"] = sess["email"]
    if consent:
        params["prompt"] = "consent"
    with _LOCK:
        _PENDING.clear()
        _PENDING.update(pending)
        FLOW.update(state="waiting", error="", started=time.time())
        _SERVER["httpd"] = httpd
    threading.Thread(target=httpd.serve_forever, daemon=True, name="chatgpt-signin").start()

    def too_long(attempt=pending["state"]):              # only this attempt, never a newer one
        if FLOW["state"] == "waiting" and _PENDING.get("state") == attempt:
            stop_signin("The sign-in took too long — start again.")
    timer = threading.Timer(600, too_long)
    timer.daemon = True
    timer.start()
    return AUTHORIZE + "?" + urlencode(params, quote_via=quote)


def stop_signin(error: str = ""):
    with _LOCK:
        httpd, _SERVER["httpd"] = _SERVER["httpd"], None
        if error and FLOW["state"] == "waiting":
            FLOW.update(state="error", error=error)
        elif FLOW["state"] == "waiting":
            FLOW.update(state="idle", error="")
        _PENDING.clear()
    if httpd:
        try:
            httpd.shutdown()
            httpd.server_close()
        except Exception:
            pass


def _finish(q: dict) -> tuple:
    """The browser came back: check it, swap the code for tokens, keep them. Returns the page's title and text."""
    one = lambda k: (q.get(k) or [""])[0]
    with _LOCK:
        pending = dict(_PENDING)
    if not pending or not hmac.compare_digest(one("state"), pending.get("state", "")):
        return "This sign-in link has expired", "Go back to MrSOLIS and press Continue with ChatGPT again."
    if one("error"):
        FLOW.update(state="declined", error="You didn't allow MrSOLIS to use ChatGPT.")
        return "MrSOLIS wasn't allowed", "You can close this tab. MrSOLIS keeps using its own brain."
    issued = one("client_id")
    expected = pending["client_id"]
    if expected == DYNAMIC:
        if not issued or issued == DYNAMIC:
            FLOW.update(state="error", error="ChatGPT didn't finish registering MrSOLIS. Try again.")
            return "Sign-in incomplete", "Go back to MrSOLIS and try again."
    elif issued and issued != expected:
        FLOW.update(state="error", error="ChatGPT answered for a different app registration. Try again.")
        return "Sign-in refused", "Go back to MrSOLIS and try again."
    client_id = issued or expected
    try:
        r = httpx.post(TOKEN, data={"grant_type": "authorization_code", "client_id": client_id, "code": one("code"),
                                    "code_verifier": pending["verifier"], "redirect_uri": pending["redirect"],
                                    "resource": RESOURCE},
                       headers={"Accept": "application/json"}, timeout=30)
        tok = r.json() if r.content else {}
        if r.status_code != 200 or not tok.get("access_token"):
            raise ValueError(tok.get("error_description") or tok.get("error") or f"status {r.status_code}")
        claims = _check_id_token(tok.get("id_token", ""), client_id, pending["nonce"])
    except (httpx.HTTPError, ValueError) as e:
        FLOW.update(state="error", error=f"ChatGPT sign-in failed: {e}"[:200])
        return "Sign-in failed", "Go back to MrSOLIS and try again."
    scopes = (tok.get("scope") or "").split()
    _save_session({"client_id": client_id, "issuer": AUTH, "sub": claims["sub"], "email": claims.get("email", ""),
                   "id_token": tok.get("id_token", ""), "access_token": tok["access_token"],
                   "refresh_token": tok.get("refresh_token", ""), "expires_at": time.time() + int(tok.get("expires_in") or 3600),
                   "scopes": scopes, "saved_at": time.time()})
    if PLAN_SCOPE not in scopes:                 # signed in, but plan use not allowed: no inference on this path
        FLOW.update(state="done", error="")
        return "Signed in", "You didn't turn on ChatGPT plan use, so MrSOLIS keeps its own brain. You can close this tab."
    FLOW.update(state="done", error="")
    return "You're signed in", "MrSOLIS can now use your ChatGPT plan. You can close this tab and go back to MrSOLIS."


def _check_id_token(token: str, client_id: str, nonce: str) -> dict:
    """OpenAI's ID token checks: issuer, audience (the issued client ID), expiry, nonce, subject, and the RS256
    signature against OpenAI's keys. (It comes straight from the token endpoint over TLS, which OIDC also accepts.)"""
    try:
        h64, c64, s64 = token.split(".")
        header, claims, sig = json.loads(_unb64url(h64)), json.loads(_unb64url(c64)), _unb64url(s64)
    except (ValueError, AttributeError):
        raise ValueError("no valid ID token")
    aud = claims.get("aud")
    if claims.get("iss") != AUTH:
        raise ValueError("ID token from the wrong issuer")
    if not (aud == client_id or (isinstance(aud, list) and client_id in aud)):
        raise ValueError("ID token for another app")
    if float(claims.get("exp", 0)) < time.time() - 5:
        raise ValueError("ID token expired")
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise ValueError("ID token nonce mismatch")
    if not claims.get("sub"):
        raise ValueError("ID token without a subject")
    if header.get("alg") == "RS256":
        keys = httpx.get(JWKS, timeout=20).json().get("keys", [])
        key = next((k for k in keys if k.get("kid") == header.get("kid")), None) or \
            (keys[0] if len(keys) == 1 else None)
        if not key or not _rs256_ok(f"{h64}.{c64}".encode("ascii"), sig, key):
            raise ValueError("ID token signature doesn't check out")
    return claims


def _rs256_ok(signing_input: bytes, sig: bytes, jwk: dict) -> bool:
    """RSASSA-PKCS1-v1_5 with SHA-256 (RFC 8017), on Python's own integers."""
    n = int.from_bytes(_unb64url(jwk["n"]), "big")
    e = int.from_bytes(_unb64url(jwk["e"]), "big")
    k = (n.bit_length() + 7) // 8
    if len(sig) != k:
        return False
    em = pow(int.from_bytes(sig, "big"), e, n).to_bytes(k, "big")
    info = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(signing_input).digest()
    return hmac.compare_digest(em, b"\x00\x01" + b"\xff" * (k - len(info) - 3) + b"\x00" + info)


async def sign_out() -> dict:
    """Revoke the refresh token at OpenAI, then forget the tokens (the app's registration and host ID stay)."""
    sess = session()
    revoked = False
    if sess and sess.get("refresh_token"):
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                rev = (await c.get(DISCOVERY)).json().get("revocation_endpoint")
                if rev:
                    r = await c.post(rev, data={"token": sess["refresh_token"], "token_type_hint": "refresh_token",
                                                "client_id": sess["client_id"]})
                    revoked = r.status_code == 200
        except (httpx.HTTPError, ValueError):
            revoked = False
    _save_session(None)
    _prov().pop("email", None)
    _prov()["welcomed"] = False
    cloud._write()
    return {"revoked": revoked}


# ══════════════════════════════════════════════════════════════════════
#   the access token (an hour long; refreshed with the rotating refresh token)
# ══════════════════════════════════════════════════════════════════════
async def access_token(force: bool = False) -> str:
    sess = session()
    if not sess or not sess.get("access_token"):
        raise cloud.CloudError("Sign in with ChatGPT in Settings → Brain.")
    if PLAN_SCOPE not in sess.get("scopes", []):
        raise cloud.CloudError("ChatGPT plan use isn't turned on for MrSOLIS — turn it on in Settings → Brain.")
    if not force and sess["expires_at"] - 90 > time.time():
        return sess["access_token"]
    if _REFRESH["lock"] is None:
        _REFRESH["lock"] = asyncio.Lock()
    async with _REFRESH["lock"]:                           # one refresh at a time: the refresh token rotates
        fresh = session()
        if fresh and fresh.get("access_token") != sess.get("access_token") and fresh["expires_at"] - 90 > time.time():
            return fresh["access_token"]
        sess = fresh or sess
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(TOKEN, data={"grant_type": "refresh_token", "client_id": sess["client_id"],
                                              "refresh_token": sess.get("refresh_token", ""), "resource": RESOURCE},
                                 headers={"Accept": "application/json"})
        except httpx.HTTPError as e:
            if sess["expires_at"] > time.time() and not force:
                return sess["access_token"]
            raise cloud.CloudError("MrSOLIS couldn't reach ChatGPT — check the internet connection.", local_ok=True) from e
        try:
            tok = r.json()
        except ValueError:
            tok = {}
        code = tok.get("error") if isinstance(tok.get("error"), str) else (tok.get("error") or {}).get("code", "")
        if r.status_code == 200 and tok.get("access_token"):
            sess.update(access_token=tok["access_token"], expires_at=time.time() + int(tok.get("expires_in") or 3600),
                        saved_at=time.time())
            if tok.get("refresh_token"):
                sess["refresh_token"] = tok["refresh_token"]
            if tok.get("id_token"):
                sess["id_token"] = tok["id_token"]
            if tok.get("scope"):
                sess["scopes"] = tok["scope"].split()
            _save_session(sess)
            return sess["access_token"]
        if code in _TERMINAL:                               # the sign-in has ended (or ChatGPT disconnected MrSOLIS)
            sess.update(access_token="", refresh_token="")
            _save_session(sess)
            raise cloud.CloudError("Your ChatGPT sign-in has ended — sign in again in Settings → Brain.")
        if code == "invalid_client":
            raise cloud.CloudError("ChatGPT doesn't recognise MrSOLIS's registration any more — sign in again in Settings → Brain.")
        raise cloud.CloudError(f"ChatGPT couldn't renew the sign-in ({r.status_code}) — try again shortly.", local_ok=True)


# ══════════════════════════════════════════════════════════════════════
#   models and answers (Responses API, on the student's plan)
# ══════════════════════════════════════════════════════════════════════
async def models() -> list:
    for attempt in range(2):
        token = await access_token(force=attempt > 0)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=12.0)) as c:
                r = await c.get(API + "/models", headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as e:
            raise cloud.CloudError("MrSOLIS couldn't reach ChatGPT — check the internet connection.", local_ok=True) from e
        if r.status_code == 401 and attempt == 0:
            continue
        if r.status_code >= 400:
            raise _plan_error(r.status_code, *_error_of(r.text))
        out = []
        for m in (r.json().get("models") or []):
            if isinstance(m, dict) and m.get("visibility") == "list" and m.get("slug"):
                out.append({"id": m["slug"], "name": m.get("display_name") or m["slug"]})
        return out
    raise cloud.CloudError("ChatGPT didn't accept the sign-in — sign in again in Settings → Brain.")


def to_responses(messages: list) -> tuple:
    """OpenAI-style chat messages → (instructions, Responses input items). No system-role items (refused here)."""
    instructions, items = [], []
    for m in messages:
        role, c = m.get("role"), m.get("content")
        if role == "system":
            t = cloud._text_of(c).strip()
            if t:
                instructions.append(t)
            continue
        if role == "assistant":
            t = cloud._text_of(c).strip()
            if t:
                items.append({"role": "assistant", "content": t})
            continue
        if isinstance(c, list):
            parts = []
            for p in c:
                if not isinstance(p, dict):
                    continue
                if p.get("type") == "text" and (p.get("text") or "").strip():
                    parts.append({"type": "input_text", "text": p["text"]})
                elif p.get("type") == "image_url":
                    url = (p.get("image_url") or {}).get("url", "")
                    if url.startswith("data:image/") or url.startswith("https://"):
                        parts.append({"type": "input_image", "image_url": url})
            if parts:
                items.append({"role": "user", "content": parts})
        elif (c or "").strip():
            items.append({"role": "user", "content": c})
    if items and items[-1]["role"] == "assistant":
        items.append({"role": "user", "content": "Continue from exactly where you left off. Do not repeat anything."})
    return "\n\n".join(instructions), items


def _error_of(raw: str) -> tuple:
    """(code, param, message) from a Responses error body — or OpenAI's admission errors, {"detail": "…"}."""
    try:
        obj = json.loads(raw)
    except ValueError:
        return "", "", raw[:200]
    if isinstance(obj, dict) and isinstance(obj.get("error"), dict):
        e = obj["error"]
        return e.get("code") or "", e.get("param") or "", e.get("message") or ""
    if isinstance(obj, dict) and obj.get("detail"):
        return "", "", str(obj["detail"])[:200]
    return "", "", raw[:200]


def _plan_error(status: int, code: str, param: str, msg: str) -> "cloud.CloudError":
    cloud.LAST["code"] = code or ""
    if code == "subscription_sharing_usage_limit_exceeded":
        return cloud.CloudError("Your ChatGPT plan has reached its limit for MrSOLIS for now. Manage usage in your "
                                "ChatGPT settings (chatgpt.com/settings/usage).", local_ok=True)
    if code in ("subscription_sharing_usage_unavailable", "subscription_sharing_user_unavailable") or status == 503:
        return cloud.CloudError("ChatGPT couldn't check your plan's usage just now — try again shortly.", local_ok=True)
    if code == "subscription_sharing_user_not_eligible":
        return cloud.CloudError("This ChatGPT account's plan can't be used in apps like MrSOLIS.", local_ok=True)
    if code == "subscription_sharing_invalid_user" or status == 401:
        return cloud.CloudError("ChatGPT didn't accept the sign-in. If it keeps happening, sign out and in again in "
                                "Settings → Brain.")
    if code == "subscription_sharing_unsupported_capability":
        if param.startswith("input"):
            return cloud.CloudError("This ChatGPT model can't take that (pictures?). Untick “It can see pictures” or "
                                    "pick another model in Settings → Brain.")
        return cloud.CloudError(f"This ChatGPT model can't do that ({param or 'unsupported'}). Pick another model.")
    if status == 403:
        return cloud.CloudError(f"ChatGPT refused MrSOLIS's request{f' ({code})' if code else ''}: {msg}"[:300],
                                local_ok=True)
    if status >= 500:
        return cloud.CloudError(f"ChatGPT is having trouble right now ({status}).", local_ok=True)
    return cloud.CloudError(f"ChatGPT turned the request down: {msg or code or status}"[:300])


async def stream(model_id: str, messages: list, info, json_mode: bool, schema):
    instructions, items = to_responses(messages)
    quirks = cloud._QUIRKS.setdefault(("chatgpt", model_id), set())
    refreshed = force = False
    for _ in range(6):
        token = await access_token(force=force)
        force = False
        body = {"model": model_id, "input": items, "store": False, "stream": True}
        if instructions:
            if "noinstr" in quirks:
                body["input"] = [{"role": "developer", "content": instructions}] + items
            else:
                body["instructions"] = instructions
        if "noeffort" not in quirks:                      # a tutor's answers: quick; Think: more thought
            body["reasoning"] = {"effort": "medium" if cloud.THINK.get() else "low"}
        if schema and "noschema" not in quirks:
            body["text"] = {"format": {"type": "json_schema", "name": "reply", "schema": schema, "strict": False}}
        elif schema or json_mode:
            _, hinted = to_responses(cloud._json_hint(messages, schema))
            body["input"] = ([{"role": "developer", "content": instructions}] if "noinstr" in quirks and instructions else []) + hinted
        produced = False
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=12.0)) as c:
                async with c.stream("POST", API + "/responses", json=body,
                                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                             "Accept": "text/event-stream"}) as r:
                    if r.status_code >= 400:
                        code, param, msg = _error_of((await r.aread()).decode("utf-8", "ignore"))
                        if r.status_code == 401 and not refreshed and code != "subscription_sharing_invalid_user":
                            refreshed = force = True          # the hour ran out early: renew once
                            continue
                        if code == "subscription_sharing_unsupported_capability":
                            if param.startswith("reasoning") and "noeffort" not in quirks:
                                quirks.add("noeffort")
                                continue
                            if param.startswith("text") and schema and "noschema" not in quirks:
                                quirks.add("noschema")
                                continue
                            if param.startswith("instructions") and "noinstr" not in quirks:
                                quirks.add("noinstr")
                                continue
                        raise _plan_error(r.status_code, code, param, msg)
                    async for line in r.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        try:
                            ev = json.loads(line[5:].strip())
                        except ValueError:
                            continue
                        kind = ev.get("type", "")
                        if kind == "response.output_text.delta":
                            piece = ev.get("delta") or ""
                            if piece:
                                produced = True
                                yield piece
                        elif kind == "response.completed":
                            if info is not None:
                                info["finish"] = "stop"
                            cloud.LAST["code"] = ""
                            return
                        elif kind == "response.incomplete":
                            if info is not None:
                                info["finish"] = "length"
                            return
                        elif kind in ("response.failed", "error"):
                            err = (ev.get("response") or {}).get("error") or ev.get("error") or ev
                            e = _plan_error(500 if not err.get("code") else 400, err.get("code") or "",
                                            err.get("param") or "", err.get("message") or "")
                            e.local_ok = e.local_ok and not produced
                            raise e
            raise cloud.CloudError("ChatGPT's answer was cut off — ask again.", local_ok=not produced)
        except httpx.HTTPError as e:
            raise cloud.CloudError("MrSOLIS couldn't reach ChatGPT — check the internet connection.",
                                   local_ok=not produced) from e
    raise cloud.CloudError("ChatGPT kept turning the request down.")
