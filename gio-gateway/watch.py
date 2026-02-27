#!/usr/bin/env python3
"""
watch.py — Monitor de mensajes WhatsApp en tiempo real
Uso: python3 watch.py
     python3 watch.py --all    (muestra todos los logs, no solo mensajes)
"""
import sys
import time
import re
import os
from typing import Optional
from datetime import datetime

# ── Colores ANSI ──────────────────────────────────────────────────────────────
R  = "\033[0m"       # reset
B  = "\033[1m"       # bold
DIM = "\033[2m"      # dim

GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RED    = "\033[91m"
BLUE   = "\033[94m"
PURPLE = "\033[95m"
GRAY   = "\033[90m"

LOG_FILE = os.path.join(os.path.dirname(__file__), "gateway.log")

# ── Patterns ──────────────────────────────────────────────────────────────────
RE_TIMESTAMP = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
RE_INCOMING  = re.compile(r"Mensaje de (.+?) \((.+?)\): (.+)$")
RE_RESPONSE  = re.compile(r"WhatsApp enviado a (\S+) ✓")
RE_DIFY_RESP = re.compile(r"Respuesta Dify: (.+)$")
RE_HANDOFF   = re.compile(r"etapa=(\S+) \| clasificacion=(\S+) \| handoff=(\S+)")
RE_CACHE        = re.compile(r"Tenant cache loaded: (\d+) tenant")
RE_RELOAD       = re.compile(r"Tenant cache recargado")
RE_HUMAN_CTRL   = re.compile(r"Humano tomó control de (\S+)")
RE_HUMAN_PAUSE  = re.compile(r"Humano en control — IA en pausa")
RE_AI_RESUME    = re.compile(r"IA reactivada para (\S+)")
RE_WARN         = re.compile(r"\[WARNING\]|\[WARN\]")
RE_ERROR        = re.compile(r"\[ERROR\]")

SHOW_ALL = "--all" in sys.argv

def format_line(line: str) -> Optional[str]:
    """Returns a formatted line or None if it should be hidden."""
    line = line.rstrip()
    if not line:
        return None

    # Extract timestamp
    ts_match = RE_TIMESTAMP.search(line)
    ts = ts_match.group(1)[11:] if ts_match else ""  # HH:MM:SS only
    ts_str = f"{GRAY}{ts}{R} " if ts else ""

    # ── Incoming WhatsApp message ──────────────────────────────────────────
    m = RE_INCOMING.search(line)
    if m:
        name, phone, text = m.group(1), m.group(2), m.group(3)
        return (
            f"\n{ts_str}{GREEN}{B}📱 ENTRANTE{R}\n"
            f"   {B}De:{R}      {GREEN}{name}{R} ({GRAY}{phone}{R})\n"
            f"   {B}Mensaje:{R} {text}"
        )

    # ── Dify response (raw) ────────────────────────────────────────────────
    m = RE_DIFY_RESP.search(line)
    if m:
        preview = m.group(1)[:120]
        return f"{ts_str}{BLUE}🤖 Dify:{R} {DIM}{preview}...{R}"

    # ── Handoff / metadata ─────────────────────────────────────────────────
    m = RE_HANDOFF.search(line)
    if m:
        etapa, clasif, handoff = m.group(1), m.group(2), m.group(3)
        handoff_str = f"{RED}{B}HANDOFF ✋{R}" if handoff == "True" else f"{GRAY}bot{R}"
        return (
            f"{ts_str}{PURPLE}📊 Clasificación:{R} "
            f"etapa={CYAN}{etapa}{R}  clasif={CYAN}{clasif}{R}  → {handoff_str}"
        )

    # ── WhatsApp sent ──────────────────────────────────────────────────────
    m = RE_RESPONSE.search(line)
    if m:
        phone = m.group(1)
        return f"{ts_str}{CYAN}✅ Respuesta enviada{R} → {phone}"

    # ── Tenant cache loaded ────────────────────────────────────────────────
    m = RE_CACHE.search(line)
    if m:
        n = m.group(1)
        color = GREEN if int(n) > 0 else YELLOW
        return f"{ts_str}{color}🔄 Cache: {n} tenant(s) cargado(s){R}"

    m = RE_RELOAD.search(line)
    if m:
        return f"{ts_str}{YELLOW}🔄 Cache recargado{R}"

    # ── Human control ─────────────────────────────────────────────────────
    m = RE_HUMAN_CTRL.search(line)
    if m:
        phone = m.group(1)
        return f"{ts_str}{YELLOW}{B}👤 HUMANO TOMÓ CONTROL{R} → {phone}"

    if RE_HUMAN_PAUSE.search(line):
        return f"{ts_str}{YELLOW}🤐 IA en pausa (humano activo){R}"

    m = RE_AI_RESUME.search(line)
    if m:
        phone = m.group(1)
        return f"{ts_str}{GREEN}🤖 IA reactivada{R} → {phone}"

    # ── Errors ────────────────────────────────────────────────────────────
    if RE_ERROR.search(line):
        return f"{ts_str}{RED}{B}❌ ERROR:{R} {RED}{line}{R}"

    if RE_WARN.search(line):
        return f"{ts_str}{YELLOW}⚠️  {line}{R}"

    # ── Show everything else only with --all ──────────────────────────────
    if SHOW_ALL:
        return f"{GRAY}{line}{R}"

    return None


def tail(filepath: str):
    """Follow a file like tail -f, yielding new lines."""
    while not os.path.exists(filepath):
        print(f"{YELLOW}Esperando gateway.log...{R}", end="\r", flush=True)
        time.sleep(1)

    with open(filepath, "r") as f:
        # Start from the end of the file
        f.seek(0, 2)
        print(f"{GREEN}{B}Gio Gateway Monitor{R} — {GRAY}Ctrl+C para salir{R}")
        print(f"{GRAY}{'─' * 50}{R}\n")
        while True:
            line = f.readline()
            if line:
                formatted = format_line(line)
                if formatted:
                    print(formatted, flush=True)
            else:
                time.sleep(0.3)


if __name__ == "__main__":
    try:
        tail(LOG_FILE)
    except KeyboardInterrupt:
        print(f"\n{GRAY}Monitor cerrado.{R}")
