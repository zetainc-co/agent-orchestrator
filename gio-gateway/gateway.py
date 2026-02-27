#!/usr/bin/env python3
"""
Gio Gateway — Meta WhatsApp ↔ Dify (Multi-Tenant)
Flujo: WhatsApp → Meta webhook → [este gateway] → Dify → Meta API → WhatsApp
       (Chatwoot se usa como panel CRM — log via Channel::Api inbox)

v3 — Multi-tenant: routing via phone_number_id → TenantConfig in-memory cache
"""

import hashlib
import hmac
import json
import os
import asyncio
import logging
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("gio-gateway")

# ── Config global (infrastructure, not per-tenant) ────────────────────────────
CHATWOOT_URL             = os.getenv("CHATWOOT_URL", "https://chat.agencianella.com/api/v1")
CHATWOOT_TOKEN           = os.environ["CHATWOOT_TOKEN"]
META_API_VERSION         = os.getenv("META_API_VERSION", "v19.0")
DIFY_API_URL             = os.getenv("DIFY_API_URL", "http://localhost/v1")
DATABASE_URL             = os.environ["DATABASE_URL"]
ENCRYPTION_SECRET        = os.environ["ENCRYPTION_SECRET"]
HUMAN_CONTROL_TIMEOUT_H  = int(os.getenv("HUMAN_CONTROL_TIMEOUT_HOURS", "4"))
NELLA_BACKEND_URL        = os.getenv("NELLA_BACKEND_URL", "http://localhost:3000")

# ── Chatwoot webhook deduplication ────────────────────────────────────────────
# Chatwoot fires the SAME message_created event twice: once via the inbox
# webhook_url (Channel::Api) and once via the account-level webhook.
# We deduplicate by Chatwoot message ID with a 30-second TTL.
_cw_seen: OrderedDict[str, float] = OrderedDict()
_CW_DEDUP_TTL = 30  # seconds


def _cw_is_duplicate(msg_id: str) -> bool:
    """Return True if this Chatwoot message ID was already processed recently."""
    now = time.monotonic()
    # Evict expired entries to prevent unbounded growth
    cutoff = now - _CW_DEDUP_TTL
    while _cw_seen and next(iter(_cw_seen.values())) < cutoff:
        _cw_seen.popitem(last=False)
    if msg_id in _cw_seen:
        return True
    _cw_seen[msg_id] = now
    return False


# ── Per-tenant config ─────────────────────────────────────────────────────────
@dataclass
class TenantConfig:
    tenant_id:           str
    schema_name:         str
    phone_number_id:     str
    dify_app_key:        str
    meta_token:          str
    app_secret:          str
    verify_token:        str
    chatwoot_account_id: int
    chatwoot_inbox_id:   Optional[int]
    chatwoot_token:      str  # per-tenant API token from chatwoot_config

# In-memory cache: phone_number_id -> TenantConfig
tenant_cache: dict[str, TenantConfig] = {}

# ── PostgreSQL pool ───────────────────────────────────────────────────────────
pg_pool: asyncpg.Pool = None  # type: ignore[assignment]


# ── Tenant cache loader ───────────────────────────────────────────────────────
async def load_tenant_cache():
    """Load all active tenant configs into memory from the DB."""
    global tenant_cache
    from crypto_util import decrypt as _decrypt

    async with pg_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                wc.phone_number_id,
                wc.meta_token,
                wc.app_secret,
                wc.verify_token,
                wc.chatwoot_inbox_id,
                t.id                   AS tenant_id,
                t.schema_name,
                dc.dify_app_key,
                COALESCE(cc.chatwoot_account_id, t.chatwoot_account_id) AS chatwoot_account_id,
                cc.chatwoot_api_key    AS chatwoot_token
            FROM public.whatsapp_config wc
            JOIN public.tenants t       ON t.id = wc.tenant_id
            JOIN public.dify_config dc  ON dc.tenant_id = wc.tenant_id
                                       AND dc.is_active = true
            LEFT JOIN public.chatwoot_config cc ON cc.tenant_id = wc.tenant_id
            WHERE wc.is_active = true
              AND t.status = 'active'
        """)

    new_cache: dict[str, TenantConfig] = {}
    for row in rows:
        phone_id = row["phone_number_id"]
        try:
            new_cache[phone_id] = TenantConfig(
                tenant_id           = str(row["tenant_id"]),
                schema_name         = row["schema_name"],
                phone_number_id     = phone_id,
                dify_app_key        = row["dify_app_key"],
                meta_token          = _decrypt(row["meta_token"], ENCRYPTION_SECRET),
                app_secret          = _decrypt(row["app_secret"], ENCRYPTION_SECRET),
                verify_token        = row["verify_token"] or "nella-gateway-2024",
                chatwoot_account_id = row["chatwoot_account_id"],
                chatwoot_inbox_id   = row["chatwoot_inbox_id"],
                chatwoot_token      = row["chatwoot_token"] or CHATWOOT_TOKEN,
            )
        except Exception as e:
            log.error(f"Error loading config for phone_number_id={phone_id}: {e}")
            continue

    tenant_cache = new_cache
    log.info(f"Tenant cache loaded: {len(tenant_cache)} tenant(s) active")
    for pid, cfg in tenant_cache.items():
        log.info(f"  {pid} -> schema={cfg.schema_name}, dify={cfg.dify_app_key[:12]}...")


async def init_pg():
    """Initialize PostgreSQL connection pool and load tenant cache."""
    global pg_pool
    pg_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    await load_tenant_cache()


# ── FastAPI lifespan ──────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pg()
    log.info("Gio Gateway arrancado (multi-tenant) ✓")
    log.info(f"  Dify     : {DIFY_API_URL}")
    log.info(f"  Chatwoot : {CHATWOOT_URL}")
    log.info(f"  Tenants  : {len(tenant_cache)}")
    yield
    if pg_pool:
        await pg_pool.close()


app = FastAPI(title="Gio Gateway", lifespan=lifespan)


# ── Cache reload (called by NestJS after connect/disconnect) ──────────────────
@app.post("/reload-cache")
async def reload_cache():
    """Reload tenant cache from database."""
    await load_tenant_cache()
    return {
        "status":         "ok",
        "tenants_loaded": len(tenant_cache),
        "phone_ids":      list(tenant_cache.keys()),
    }


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status":         "ok",
        "tenants_loaded": len(tenant_cache),
        "phone_ids":      list(tenant_cache.keys()),
        "dify_url":       DIFY_API_URL,
        "chatwoot_url":   CHATWOOT_URL,
    }


# ── Meta webhook: verification ────────────────────────────────────────────────
@app.get("/meta-webhook")
async def meta_verify(request: Request):
    params    = request.query_params
    mode      = params.get("hub.mode")
    token     = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe":
        valid = any(cfg.verify_token == token for cfg in tenant_cache.values())
        if valid:
            log.info(f"Meta webhook verificado (token match)")
            return PlainTextResponse(challenge)

    log.warning(f"Meta webhook verificacion fallida: mode={mode} token={token!r}")
    raise HTTPException(status_code=403, detail="Forbidden")


# ── Meta webhook: inbound messages ───────────────────────────────────────────
@app.post("/meta-webhook")
async def meta_webhook(request: Request):
    body_bytes = await request.body()
    body       = json.loads(body_bytes)

    try:
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                # Multi-tenant routing via phone_number_id
                phone_number_id = value.get("metadata", {}).get("phone_number_id", "")
                config          = tenant_cache.get(phone_number_id)
                if not config:
                    log.warning(f"No tenant config for phone_number_id={phone_number_id}")
                    continue

                # Verify webhook signature with tenant-specific app_secret
                sig_header = request.headers.get("x-hub-signature-256", "")
                if sig_header:
                    mac      = hmac.new(config.app_secret.encode(), body_bytes, hashlib.sha256)
                    expected = "sha256=" + mac.hexdigest()
                    if not hmac.compare_digest(sig_header, expected):
                        log.warning(f"Invalid signature for phone_number_id={phone_number_id}")
                        continue

                messages = value.get("messages", [])
                contacts = value.get("contacts", [])
                name_map = {c["wa_id"]: c.get("profile", {}).get("name", "") for c in contacts}

                for msg in messages:
                    if msg.get("type") != "text":
                        log.info(f"[{config.schema_name}] Tipo {msg.get('type')!r} ignorado")
                        continue

                    meta_msg_id = msg.get("id", "")
                    if await is_processed(meta_msg_id, config.schema_name):
                        log.info(f"[{config.schema_name}] Duplicado: {meta_msg_id}")
                        continue

                    phone   = msg["from"]
                    content = msg["text"]["body"].strip()
                    name    = name_map.get(phone, phone)

                    await mark_processed(meta_msg_id, phone, content, config.schema_name)
                    log.info(f"[{config.schema_name}] Mensaje de {phone} ({name}): {content[:60]!r}")
                    task = asyncio.create_task(process(phone, name, content, config))
                    task.add_done_callback(
                        lambda t: log.error(f"[{config.schema_name}] Error en proceso: {t.exception()}")
                        if not t.cancelled() and t.exception() else None
                    )

    except Exception as e:
        log.error(f"Error procesando webhook Meta: {e}")

    return {"status": "ok"}


# ── Chatwoot Human Bridge ─────────────────────────────────────────────────────
@app.post("/chatwoot-webhook")
async def chatwoot_webhook(request: Request):
    """
    Human Bridge: when a human agent sends a message in Chatwoot,
    forward it to the customer on WhatsApp via Meta API.
    """
    body = await request.json()

    event        = body.get("event", "")
    message_type = body.get("message_type", "")
    is_private   = body.get("private", True)
    content      = body.get("content", "")

    if event != "message_created":
        return {"status": "ignored"}

    # ── Private note: check for AI-resume command before any other filter ────
    # Chatwoot blocks "/" commands in the reply box (opens canned responses menu).
    # Agents use a PRIVATE NOTE with "!ai" to resume AI control — it never reaches WhatsApp.
    AI_RESUME_KEYWORDS = {"!ai", "!bot", "!robot", "activar ia", "resume ia"}
    if is_private and content.strip().lower() in AI_RESUME_KEYWORDS:
        conversation  = body.get("conversation", {})
        inbox_id      = conversation.get("inbox_id")
        contact       = conversation.get("contact", {}) or {}
        phone         = (
            contact.get("phone_number")
            or conversation.get("meta", {}).get("sender", {}).get("phone_number")
            or ""
        )
        config: Optional[TenantConfig] = None
        for cfg in tenant_cache.values():
            if cfg.chatwoot_inbox_id == inbox_id:
                config = cfg
                break
        if config and phone:
            normalized_phone = normalize_phone(phone)
            await set_human_control(normalized_phone, False, config.schema_name)
            log.info(f"[{config.schema_name}] IA reactivada para {normalized_phone} via nota privada")
            chatwoot_conv_id = str(conversation.get("id", ""))
            if chatwoot_conv_id:
                await chatwoot_log_message(
                    chatwoot_conv_id,
                    "🤖 IA reactivada. El agente virtual retoma la conversación.",
                    "outgoing",
                    str(config.chatwoot_account_id),
                    config.chatwoot_token,
                    private=True,
                )
        return {"status": "ai_resumed"}

    # Only process outgoing, non-private, human messages for the Human Bridge
    if message_type != "outgoing" or is_private:
        return {"status": "ignored"}

    # Deduplicate: Chatwoot fires this event twice (inbox webhook_url + account webhook)
    msg_id = str(body.get("id", ""))
    if msg_id and _cw_is_duplicate(msg_id):
        log.debug(f"Chatwoot webhook duplicado ignorado: msg_id={msg_id}")
        return {"status": "ignored", "reason": "duplicate"}

    # Skip bot messages (private notes logged by this gateway)
    if content.startswith("🤖"):
        return {"status": "ignored", "reason": "bot_message"}

    conversation = body.get("conversation", {})
    inbox_id     = conversation.get("inbox_id")

    # Phone number can be in multiple places depending on Chatwoot version
    contact = conversation.get("contact", {}) or {}
    phone   = (
        contact.get("phone_number")
        or conversation.get("meta", {}).get("sender", {}).get("phone_number")
        or body.get("sender", {}).get("phone_number")
        or ""
    )

    if not phone or not inbox_id:
        log.warning(f"Human Bridge: phone_or_inbox_missing inbox={inbox_id} phone={phone!r} keys={list(conversation.keys())}")
        return {"status": "ignored", "reason": "missing_phone_or_inbox"}

    # Find tenant by chatwoot_inbox_id
    config: Optional[TenantConfig] = None
    for cfg in tenant_cache.values():
        if cfg.chatwoot_inbox_id == inbox_id:
            config = cfg
            break

    if not config:
        log.warning(f"Chatwoot webhook: no tenant for inbox_id={inbox_id}")
        return {"status": "ignored", "reason": "no_tenant_for_inbox"}

    normalized_phone = normalize_phone(phone)

    # Human message → pause AI for this conversation
    await set_human_control(normalized_phone, True, config.schema_name)
    log.info(f"[{config.schema_name}] Humano tomó control de {normalized_phone} (timeout: {HUMAN_CONTROL_TIMEOUT_H}h)")

    to_phone = phone.lstrip("+")
    log.info(f"[{config.schema_name}] Human Bridge: → {to_phone}: {content[:60]!r}")
    await meta_send(to_phone, content, config)

    return {"status": "sent"}


# ── Human control helpers ─────────────────────────────────────────────────────
def is_human_in_control(conv_data: dict) -> bool:
    """Return True if a human agent has recently responded and timeout hasn't expired."""
    if not conv_data.get("human_control"):
        return False
    last_human_at_str = conv_data.get("last_human_at")
    if not last_human_at_str:
        return True  # Marked but no timestamp → treat as controlled
    try:
        last_human_at = datetime.fromisoformat(last_human_at_str)
        # Make timezone-aware if naive
        if last_human_at.tzinfo is None:
            last_human_at = last_human_at.replace(tzinfo=timezone.utc)
        elapsed = datetime.now(timezone.utc) - last_human_at
        if elapsed > timedelta(hours=HUMAN_CONTROL_TIMEOUT_H):
            return False  # Timeout expired — AI resumes
    except Exception:
        return True
    return True


async def set_human_control(phone: str, enabled: bool, schema: str):
    """Toggle human control flag on the latest conversation for a phone number.

    Also syncs nella_contacts.handoff_active so both fields stay consistent:
    - enabled=True  → human in control   (handoff_active=True)
    - enabled=False → AI resumes control (handoff_active=False)
    """
    normalized = normalize_phone(phone)
    patch = {"human_control": enabled}
    if enabled:
        patch["last_human_at"] = datetime.now(timezone.utc).isoformat()
    else:
        patch["last_human_at"] = None  # Clear timestamp when AI is restored

    async with pg_pool.acquire() as conn:
        await conn.execute(
            f"""UPDATE "{schema}".nella_conversations
                SET metadata   = metadata || $1::jsonb,
                    updated_at = NOW()
                WHERE id = (
                    SELECT nc.id
                    FROM "{schema}".nella_conversations nc
                    JOIN "{schema}".nella_contacts cnt ON cnt.id = nc.contact_id
                    WHERE cnt.phone = $2
                    ORDER BY nc.created_at DESC
                    LIMIT 1
                )""",
            json.dumps(patch),
            normalized,
        )
        # Keep nella_contacts.handoff_active in sync
        await conn.execute(
            f"""UPDATE "{schema}".nella_contacts
                SET handoff_active = $1,
                    updated_at     = NOW()
                WHERE phone = $2""",
            enabled,
            normalized,
        )


# ── Main processing pipeline ──────────────────────────────────────────────────
async def process(phone: str, name: str, text: str, config: TenantConfig):
    first_name       = name.split()[0] if name else phone
    conv_data        = await get_conv(phone, config.schema_name)
    dify_conv_id     = conv_data.get("dify_conv_id")
    chatwoot_conv_id = conv_data.get("chatwoot_conv_id")

    # 0. Human control check — skip AI if a human agent is active
    if is_human_in_control(conv_data):
        log.info(f"[{config.schema_name}] {phone} | Humano en control — IA en pausa")
        # Still log incoming message to Chatwoot so the agent sees it
        try:
            chatwoot_acct  = str(config.chatwoot_account_id)
            chatwoot_token = config.chatwoot_token
            inbox_id       = config.chatwoot_inbox_id
            if not chatwoot_conv_id and inbox_id:
                chatwoot_conv_id = await chatwoot_get_or_create_conversation(
                    phone, name, chatwoot_acct, inbox_id, chatwoot_token,
                )
            if chatwoot_conv_id:
                try:
                    await chatwoot_log_message(
                        chatwoot_conv_id, text, "incoming", chatwoot_acct, chatwoot_token,
                    )
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 404 and inbox_id:
                        log.warning(
                            f"[{config.schema_name}] chatwoot_conv_id={chatwoot_conv_id} stale (404) "
                            f"en modo humano, recreando conversación"
                        )
                        chatwoot_conv_id = await chatwoot_get_or_create_conversation(
                            phone, name, chatwoot_acct, inbox_id, chatwoot_token,
                        )
                        if chatwoot_conv_id:
                            await chatwoot_log_message(
                                chatwoot_conv_id, text, "incoming", chatwoot_acct, chatwoot_token,
                            )
                    else:
                        raise

            # Persist new conv_id — this path returns early so save_conv won't run
            if chatwoot_conv_id and chatwoot_conv_id != conv_data.get("chatwoot_conv_id") and conv_data.get("conv_id"):
                await _update_chatwoot_conv_id(
                    conv_data["conv_id"], chatwoot_conv_id, config.schema_name,
                )
        except Exception as e:
            log.warning(f"[{config.schema_name}] Chatwoot log (human mode) error: {e}")
        return

    # 1. Call Dify
    dify_payload = {
        "inputs":        {"contact_name": first_name},
        "query":         text,
        "user":          phone,
        "response_mode": "streaming",
    }
    if dify_conv_id:
        dify_payload["conversation_id"] = dify_conv_id

    new_dify_conv_id = dify_conv_id
    raw_answer       = ""

    async def _call_dify(payload: dict) -> str:
        answer = ""
        nonlocal new_dify_conv_id
        async with httpx.AsyncClient(timeout=90.0) as client:
            async with client.stream(
                "POST",
                f"{DIFY_API_URL}/chat-messages",
                headers={"Authorization": f"Bearer {config.dify_app_key}"},
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        event = chunk.get("event", "")
                        if event in ("agent_message", "message"):
                            answer += chunk.get("answer", "")
                        if event in ("message_end", "message"):
                            new_dify_conv_id = chunk.get("conversation_id", new_dify_conv_id)
                    except json.JSONDecodeError:
                        continue
        return answer

    try:
        raw_answer = await _call_dify(dify_payload)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if status == 404 and dify_conv_id:
            # Stale conversation_id (e.g. agent was replaced) — retry as new conversation
            log.warning(f"[{config.schema_name}] Conversation {dify_conv_id} no encontrada en Dify, iniciando nueva")
            dify_payload.pop("conversation_id", None)
            new_dify_conv_id = None
            try:
                raw_answer = await _call_dify(dify_payload)
            except Exception as e2:
                log.error(f"[{config.schema_name}] Error llamando a Dify (retry): {e2}")
                return
        elif status in (401, 403):
            # App key invalid or Dify agent deleted — evict tenant from cache so it
            # stops responding immediately (self-healing, no manual reload needed)
            log.warning(
                f"[{config.schema_name}] Dify devolvió {status} — agente eliminado o key inválida. "
                f"Removiendo tenant {config.phone_number_id!r} del caché."
            )
            tenant_cache.pop(config.phone_number_id, None)
            return
        else:
            log.error(f"[{config.schema_name}] Error llamando a Dify: {e}")
            return
    except Exception as e:
        log.error(f"[{config.schema_name}] Error llamando a Dify: {e}")
        return

    log.info(f"[{config.schema_name}] Respuesta Dify: {raw_answer[:200]}")

    # 2. Parse JSON from agent
    ai = {}
    try:
        start = raw_answer.find("{")
        end   = raw_answer.rfind("}") + 1
        if start >= 0 and end > start:
            ai = json.loads(raw_answer[start:end])
    except json.JSONDecodeError:
        log.warning(f"[{config.schema_name}] JSON malformado de Dify, usando respuesta cruda")

    response_message = ai.get("response_message") or raw_answer
    handoff          = ai.get("handoff", False)
    ai_clasificacion = ai.get("ai_clasificacion", "")
    ai_etapa         = ai.get("ai_etapa", "")

    log.info(
        f"[{config.schema_name}] {phone} | "
        f"etapa={ai_etapa} | clasificacion={ai_clasificacion} | handoff={handoff}"
    )

    # 3. Update contact in PostgreSQL with AI fields
    try:
        await upsert_contact(
            phone, name,
            ai_clasificacion=ai.get("ai_clasificacion", ""),
            ai_etapa=ai.get("ai_etapa", ""),
            ai_analisis=ai.get("ai_analisis", ""),
            handoff=bool(handoff),
            schema=config.schema_name,
            contact_name=ai.get("contact_name") or None,
            contact_email=ai.get("contact_email") or None,
        )
        asyncio.create_task(notify_contacts_updated())
    except Exception as e:
        log.warning(f"[{config.schema_name}] upsert_contact error (non-critical): {e}")

    # 4. Send response via Meta
    await meta_send(phone, response_message, config)

    # 5. Log to Chatwoot
    try:
        chatwoot_acct  = str(config.chatwoot_account_id)
        chatwoot_token = config.chatwoot_token
        inbox_id       = config.chatwoot_inbox_id

        if not chatwoot_conv_id and inbox_id:
            chatwoot_conv_id = await chatwoot_get_or_create_conversation(
                phone, name, chatwoot_acct, inbox_id, chatwoot_token,
            )
        if chatwoot_conv_id:
            # User message as incoming (shows on left side)
            try:
                await chatwoot_log_message(chatwoot_conv_id, text, "incoming", chatwoot_acct, chatwoot_token)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404 and inbox_id:
                    # Stale conversation (inbox deleted/recreated) — get a fresh one
                    log.warning(
                        f"[{config.schema_name}] chatwoot_conv_id={chatwoot_conv_id} stale (404), "
                        f"recreando conversación en inbox {inbox_id}"
                    )
                    chatwoot_conv_id = await chatwoot_get_or_create_conversation(
                        phone, name, chatwoot_acct, inbox_id, chatwoot_token,
                    )
                    if chatwoot_conv_id:
                        await chatwoot_log_message(chatwoot_conv_id, text, "incoming", chatwoot_acct, chatwoot_token)
                else:
                    raise
            # AI response as private note (lock icon — agents know it was the bot)
            if chatwoot_conv_id:
                await chatwoot_log_message(chatwoot_conv_id, f"🤖 {response_message}", "outgoing", chatwoot_acct, chatwoot_token, private=True)
    except Exception as e:
        log.warning(f"[{config.schema_name}] Chatwoot log error (no critico): {e}")

    # 5. Persist to PostgreSQL
    await save_conv(phone, new_dify_conv_id, chatwoot_conv_id, name, conv_data, config.schema_name)
    await log_messages(conv_data, text, response_message, config.schema_name)

    # 6. Handoff
    if handoff and chatwoot_conv_id:
        await chatwoot_handoff(
            chatwoot_conv_id, ai_clasificacion, ai_etapa, str(config.chatwoot_account_id), config.chatwoot_token,
        )


# ── Meta: send message ────────────────────────────────────────────────────────
async def meta_send(to_phone: str, message: str, config: TenantConfig):
    url     = f"https://graph.facebook.com/{META_API_VERSION}/{config.phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                to_phone,
        "type":              "text",
        "text":              {"preview_url": False, "body": message},
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                url,
                headers={"Authorization": f"Bearer {config.meta_token}"},
                json=payload,
            )
            r.raise_for_status()
            log.info(f"[{config.schema_name}] WhatsApp enviado a {to_phone} ✓")
    except Exception as e:
        log.error(f"[{config.schema_name}] Error enviando WhatsApp a {to_phone}: {e}")


# ── DB: deduplication via nella_inbox_queue ───────────────────────────────────
async def is_processed(meta_msg_id: str, schema: str) -> bool:
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""SELECT 1 FROM "{schema}".nella_inbox_queue
                WHERE raw_payload->>'meta_message_id' = $1""",
            meta_msg_id,
        )
    return row is not None


async def mark_processed(meta_msg_id: str, phone: str, content: str, schema: str):
    async with pg_pool.acquire() as conn:
        await conn.execute(
            f"""INSERT INTO "{schema}".nella_inbox_queue (raw_payload, status)
                VALUES ($1::jsonb, 'PROCESSING')""",
            json.dumps({"meta_message_id": meta_msg_id, "phone": phone, "content": content}),
        )


# ── DB: contacts and conversations ────────────────────────────────────────────
async def get_conv(phone: str, schema: str) -> dict:
    """Fetch the latest conversation state for a phone number."""
    normalized = normalize_phone(phone)
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""SELECT
                    nc.id                                        AS conv_id,
                    nc.chatwoot_conversation_id                  AS chatwoot_conv_id,
                    nc.metadata->>'dify_conversation_id'         AS dify_conv_id,
                    nc.metadata->>'human_control'                AS human_control,
                    nc.metadata->>'last_human_at'                AS last_human_at,
                    cnt.id                                       AS contact_id
                FROM "{schema}".nella_conversations nc
                JOIN "{schema}".nella_contacts cnt ON cnt.id = nc.contact_id
                WHERE cnt.phone = $1
                ORDER BY nc.created_at DESC
                LIMIT 1""",
            normalized,
        )
    if row:
        return {
            "conv_id":          str(row["conv_id"]),
            "dify_conv_id":     row["dify_conv_id"],
            "chatwoot_conv_id": str(row["chatwoot_conv_id"]) if row["chatwoot_conv_id"] else None,
            "contact_id":       row["contact_id"],
            "human_control":    row["human_control"] == "true",
            "last_human_at":    row["last_human_at"],
        }
    return {}


async def save_conv(
    phone: str,
    dify_conv_id: str,
    chatwoot_conv_id: Optional[str],
    name: str,
    existing: dict,
    schema: str,
):
    """Upsert contact and conversation with updated state."""
    normalized = normalize_phone(phone)
    cw_int     = int(chatwoot_conv_id) if chatwoot_conv_id else None

    async with pg_pool.acquire() as conn:
        contact_id = await conn.fetchval(
            f"""INSERT INTO "{schema}".nella_contacts
                    (phone, name, last_interaction_at, created_at, updated_at)
                VALUES ($1, $2, NOW(), NOW(), NOW())
                ON CONFLICT (phone) DO UPDATE SET
                    name                = EXCLUDED.name,
                    last_interaction_at = NOW(),
                    updated_at          = NOW()
                RETURNING id""",
            normalized, name,
        )

        metadata = json.dumps({"dify_conversation_id": dify_conv_id})

        if existing.get("conv_id"):
            await conn.execute(
                f"""UPDATE "{schema}".nella_conversations
                    SET metadata                 = $1::jsonb,
                        chatwoot_conversation_id = COALESCE($2, chatwoot_conversation_id),
                        updated_at               = NOW()
                    WHERE id = $3""",
                metadata, cw_int, existing["conv_id"],
            )
        else:
            await conn.execute(
                f"""INSERT INTO "{schema}".nella_conversations
                        (contact_id, contact_phone, chatwoot_conversation_id, metadata, status)
                    VALUES ($1, $2, $3, $4::jsonb, 'active')""",
                contact_id, normalized, cw_int, metadata,
            )


async def upsert_contact(
    phone: str,
    name: str,
    ai_clasificacion: str,
    ai_etapa: str,
    ai_analisis: str,
    handoff: bool,
    schema: str,
    contact_name: Optional[str] = None,
    contact_email: Optional[str] = None,
):
    """Create or update the contact record with AI-extracted fields.
    contact_name / contact_email come from the agent JSON when captured during conversation.
    """
    normalized = normalize_phone(phone)
    # Prefer agent-captured name over WhatsApp profile name (which may be just the number)
    resolved_name = contact_name or name
    async with pg_pool.acquire() as conn:
        await conn.execute(
            f"""INSERT INTO "{schema}".nella_contacts
                    (phone, name, email, lead_status, status, ai_summary, handoff_active, last_interaction_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                ON CONFLICT (phone) DO UPDATE SET
                    name                = COALESCE(NULLIF($2, ''), nella_contacts.name),
                    email               = COALESCE(NULLIF($3, ''), nella_contacts.email),
                    lead_status         = COALESCE(NULLIF($4, ''), nella_contacts.lead_status),
                    status              = COALESCE(NULLIF($5, ''), nella_contacts.status),
                    ai_summary          = COALESCE(NULLIF($6, ''), nella_contacts.ai_summary),
                    handoff_active      = $7,
                    last_interaction_at = NOW(),
                    updated_at          = NOW()""",
            normalized,
            resolved_name or None,
            contact_email or None,
            ai_clasificacion or None,
            ai_etapa or None,
            ai_analisis or None,
            handoff,
        )


async def log_messages(existing: dict, user_text: str, ai_text: str, schema: str):
    conv_id = existing.get("conv_id")
    if not conv_id:
        return
    async with pg_pool.acquire() as conn:
        await conn.execute(
            f"""INSERT INTO "{schema}".nella_messages
                    (conversation_id, body, from_customer, is_ai_response)
                VALUES ($1, $2, true, false),
                       ($1, $3, false, true)""",
            conv_id, user_text, ai_text,
        )


def normalize_phone(phone: str) -> str:
    """Normalize to +{phone} format (Meta sends without +)."""
    phone = phone.strip()
    return f"+{phone}" if not phone.startswith("+") else phone


async def notify_contacts_updated():
    """Fire-and-forget POST to NestJS so it emits contact:updated via WebSocket."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{NELLA_BACKEND_URL}/contacts/notify")
    except Exception as e:
        log.debug(f"notify_contacts_updated error (non-critical): {e}")


async def _update_chatwoot_conv_id(conv_id: str, chatwoot_conv_id: str, schema: str):
    """Overwrite a stale chatwoot_conversation_id in the DB."""
    async with pg_pool.acquire() as conn:
        await conn.execute(
            f"""UPDATE "{schema}".nella_conversations
                SET chatwoot_conversation_id = $1,
                    updated_at               = NOW()
                WHERE id = $2""",
            int(chatwoot_conv_id),
            conv_id,
        )


# ── Chatwoot: get or create conversation ─────────────────────────────────────
async def chatwoot_get_or_create_conversation(
    phone: str,
    name: str,
    chatwoot_account: str,
    inbox_id: int,
    token: str,
) -> Optional[str]:
    normalized = normalize_phone(phone)
    headers    = {"api_access_token": token}
    base       = f"{CHATWOOT_URL}/accounts/{chatwoot_account}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            f"{base}/contacts/search",
            headers=headers,
            params={"q": normalized, "include_contacts": "true"},
        )
        payload_list = r.json().get("payload", [])
        contact_id   = None
        for c in payload_list:
            if c.get("phone_number", "").replace("+", "").replace(" ", "") in phone:
                contact_id = c["id"]
                break

        if not contact_id:
            r = await client.post(
                f"{base}/contacts",
                headers=headers,
                json={"name": name, "phone_number": normalized},
            )
            if r.status_code in (200, 201):
                resp = r.json()
                # Chatwoot wraps response: {"payload": {"contact": {"id": ...}}}
                contact_id = (
                    resp.get("id")
                    or resp.get("payload", {}).get("contact", {}).get("id")
                )
            else:
                log.warning(f"No se pudo crear contacto en Chatwoot: {r.text[:100]}")
                return None

        r = await client.post(
            f"{base}/conversations",
            headers=headers,
            json={"inbox_id": inbox_id, "contact_id": contact_id},
        )
        if r.status_code in (200, 201):
            conv_id = str(r.json().get("id", ""))
            log.info(f"Conversacion Chatwoot creada: {conv_id} para {phone}")
            return conv_id
        else:
            log.warning(f"No se pudo crear conversacion Chatwoot: {r.text[:100]}")
            return None


# ── Chatwoot: log message ─────────────────────────────────────────────────────
async def chatwoot_log_message(
    conv_id: str,
    content: str,
    message_type: str,
    chatwoot_account: str,
    token: str,
    private: bool = False,
):
    """Post a message to a Chatwoot conversation.

    Raises httpx.HTTPStatusError on 404 (stale conversation) so callers can
    detect and recover. All other errors are logged and swallowed.
    """
    url = f"{CHATWOOT_URL}/accounts/{chatwoot_account}/conversations/{conv_id}/messages"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                url,
                headers={"api_access_token": token},
                json={"content": content, "message_type": message_type, "private": private},
            )
            r.raise_for_status()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise  # Propagate so callers can recreate stale conversations
        log.warning(f"chatwoot_log_message error: {e}")
    except Exception as e:
        log.warning(f"chatwoot_log_message error: {e}")


# ── Chatwoot: handoff ─────────────────────────────────────────────────────────
async def chatwoot_handoff(
    conv_id: str,
    clasificacion: str,
    etapa: str,
    chatwoot_account: str,
    token: str,
):
    base    = f"{CHATWOOT_URL}/accounts/{chatwoot_account}/conversations/{conv_id}"
    headers = {"api_access_token": token}

    async with httpx.AsyncClient(timeout=15.0) as client:
        await client.post(
            f"{base}/labels",
            headers=headers,
            json={"labels": ["requiere_atencion"]},
        )
        await client.post(
            f"{base}/messages",
            headers=headers,
            json={
                "content": (
                    f"🤖 *Handoff requerido*\n"
                    f"Clasificacion: {clasificacion}\n"
                    f"Etapa: {etapa}\n"
                    f"El agente paso esta conversacion al equipo humano."
                ),
                "message_type": "outgoing",
                "private":      True,
            },
        )
    log.info(f"Handoff registrado en Chatwoot conv {conv_id} ✓")
