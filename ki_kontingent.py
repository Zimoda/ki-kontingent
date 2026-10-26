"""
KI-Kontingent-Widget fuer Windows und macOS  -  HUD-Edition
Zeigt Nutzungslimits von Claude und ChatGPT (Codex) inkl. Reset-Zeitpunkt
sowie das API-Guthaben von DeepSeek (ueber /user/balance).
Keine Zusatzpakete noetig (nur Python-Standardbibliothek).

Linke Maustaste ziehen = verschieben | Doppelklick = aktualisieren
Rechtsklick = Menue | Start mit --demo zeigt Beispieldaten
"""
import datetime as dt
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request

__version__ = "1.2.0"
HOME = os.path.expanduser("~")
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"


def _app_dir():
    # Als fertige .exe/.app: Einstellungen im Benutzerprofil ablegen
    if getattr(sys, "frozen", False):
        if IS_WIN:
            base = os.environ.get("APPDATA") or HOME
        elif IS_MAC:
            base = os.path.join(HOME, "Library", "Application Support")
        else:
            base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")
        d = os.path.join(base, "KI-Kontingent")
        os.makedirs(d, exist_ok=True)
        return d
    return os.path.dirname(os.path.abspath(sys.argv[0]))


APP_DIR = _app_dir()
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
DEMO = "--demo" in sys.argv

DEFAULT_CONFIG = {
    "interval_minutes": 5,
    "debug": False,
    "position": None,
    "opacity": 0.94,
    "claude": {"enabled": True, "credentials_path": "", "session_key": ""},
    "chatgpt": {"enabled": True, "auth_path": ""},
    "deepseek": {"enabled": True, "api_key": "", "currency": "USD", "budget": 0,
                 "hide_without_key": True},
}

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

# ---- Farben / Schrift (HUD)
BG = "#07090d"
PANEL = "#0c1118"
BORDER = "#123844"
CYAN = "#00e5ff"
TEXT = "#d8f6ff"
DIM = "#5d7a86"
SEG_OFF = "#16212b"
AMBER = "#ffb020"
RED = "#ff3d5a"
MONO = "Consolas" if IS_WIN else "Menlo" if IS_MAC else "DejaVu Sans Mono"
W = 252          # Inhaltsbreite
SEGMENTS = 32
WEEKDAYS = ["MO", "DI", "MI", "DO", "FR", "SA", "SO"]


# ---------------------------------------------------------------- Helfer
def load_config():
    """Liest config.json, ergaenzt fehlende Bloecke (z. B. deepseek) und schreibt sie zurueck."""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(CONFIG_PATH, "rb") as f:
            raw = f.read().decode("utf-8-sig")     # BOM von Notepad & Co. tolerieren
    except FileNotFoundError:
        save_config(cfg)
        return cfg
    except Exception:
        return cfg          # gesperrt oder nicht lesbar - Datei nicht anfassen

    user = None
    try:
        user = json.loads(raw)
    except Exception:
        try:
            user = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))   # Komma vor } / ]
        except Exception:
            user = None
    if not isinstance(user, dict):
        # Defekte Datei aufheben, damit nichts verloren geht, und mit Standardwerten starten
        try:
            os.replace(CONFIG_PATH, CONFIG_PATH + ".defekt")
        except Exception:
            pass
        save_config(cfg)
        return cfg

    for k, v in user.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    if cfg != user:
        save_config(cfg)
    return cfg


def save_config(cfg):
    """Atomar schreiben - nie eine halbe config.json hinterlassen."""
    if DEMO:
        return
    tmp = CONFIG_PATH + ".kik-tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(tmp, CONFIG_PATH)
    except Exception:
        pass


def log_crash(text):
    path = os.path.join(APP_DIR, "ki_kontingent_crash.log")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"--- {dt.datetime.now():%Y-%m-%d %H:%M:%S}  v{__version__}\n{text}\n")
    except Exception:
        pass
    return path


def http_json(url, headers, timeout=15):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def parse_time(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        if v > 1e12:
            v /= 1000
        return dt.datetime.fromtimestamp(v).astimezone()
    try:
        return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def window_label(secs):
    if not secs:
        return "LIMIT"
    secs = int(secs)
    if secs == 18000:
        return "5 STD"
    if secs == 604800:
        return "WOCHE"
    if secs % 86400 == 0:
        return f"{secs // 86400} TAGE"
    return f"{round(secs / 3600)} STD"


def debug_dump(cfg, name, data):
    if cfg.get("debug"):
        try:
            with open(os.path.join(APP_DIR, f"debug_{name}.json"), "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass


def mix(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def virtual_screen():
    """Gesamter Desktop inkl. zweiter Monitore (Windows: negative Koordinaten moeglich)."""
    try:
        import ctypes
        u = ctypes.windll.user32
        x, y = u.GetSystemMetrics(76), u.GetSystemMetrics(77)   # SM_X/YVIRTUALSCREEN
        w, h = u.GetSystemMetrics(78), u.GetSystemMetrics(79)   # SM_CX/CYVIRTUALSCREEN
        if w > 0 and h > 0:
            return x, y, w, h
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- Anbieter
CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CLAUDE_TOKEN_URLS = ["https://platform.claude.com/v1/oauth/token",
                     "https://console.anthropic.com/v1/oauth/token"]
CLAUDE_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
CLAUDE_KEYCHAIN = "Claude Code-credentials"
CODEX_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
CODEX_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEEPSEEK_BALANCE_URL = "https://api.deepseek.com/user/balance"
DS_ACCENT = "#4d6bfe"
DS_SYMBOL = {"CNY": "Â¥", "USD": "$"}
DS_HISTORY_PATH = os.path.join(APP_DIR, "deepseek_history.json")


class LoginExpired(Exception):
    """Login abgelaufen und nicht automatisch erneuerbar."""

    def __init__(self, provider):
        super().__init__(provider)
        self.provider = provider


def http_post_json(url, body, headers=None, timeout=20):
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json_atomic(path, data):
    """Schreibt erst eine Temp-Datei und tauscht sie dann aus - nie halbe Dateien."""
    tmp = path + ".kik-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    try:
        os.chmod(tmp, os.stat(path).st_mode & 0o777)
    except OSError:
        pass
    os.replace(tmp, path)


def is_writable(path):
    return os.access(path, os.W_OK) and os.access(os.path.dirname(path) or ".", os.W_OK)


class ClaudeCredentials:
    """Claude-Code-Login: Windows/Linux als Datei, macOS im Schluesselbund."""

    def __init__(self, custom_path=""):
        base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(HOME, ".claude")
        self.path = custom_path or os.path.join(base, ".credentials.json")
        self.source = None
        self.account = None
        self.data = None

    def load(self):
        if os.path.exists(self.path):
            self.data, self.source = read_json(self.path), "file"
            return self.data
        if IS_MAC:
            out = subprocess.run(["security", "find-generic-password", "-s", CLAUDE_KEYCHAIN, "-w"],
                                 capture_output=True, text=True, timeout=10)
            if out.returncode == 0 and out.stdout.strip():
                self.data, self.source = json.loads(out.stdout.strip()), "keychain"
                meta = subprocess.run(["security", "find-generic-password", "-s", CLAUDE_KEYCHAIN],
                                      capture_output=True, text=True, timeout=10)
                import re
                m = re.search(r'"acct"<blob>="([^"]*)"', meta.stdout + meta.stderr)
                self.account = m.group(1) if m else None
                return self.data
        raise FileNotFoundError(self.path)

    @property
    def oauth(self):
        return self.data["claudeAiOauth"]

    def can_save(self):
        if self.source == "file":
            return is_writable(self.path)
        return self.source == "keychain" and bool(self.account)

    def save(self):
        if self.source == "file":
            write_json_atomic(self.path, self.data)
        elif self.source == "keychain" and self.account:
            out = subprocess.run(["security", "add-generic-password", "-U", "-s", CLAUDE_KEYCHAIN,
                                  "-a", self.account, "-w", json.dumps(self.data)],
                                 capture_output=True, text=True, timeout=10)
            if out.returncode != 0:
                raise OSError("Schluesselbund: " + (out.stderr.strip() or "Schreiben fehlgeschlagen"))
        else:
            raise OSError("Login kann nicht gespeichert werden")


def refresh_claude(store):
    """Erneuert den Claude-Code-Zugang und speichert ihn zurueck,
    damit Claude Code selbst angemeldet bleibt."""
    store.load()  # frisch lesen - evtl. hat Claude Code gerade selbst erneuert
    oauth = store.oauth
    rt = oauth.get("refreshToken")
    if not rt or not store.can_save():
        raise LoginExpired("claude")
    body = {"grant_type": "refresh_token", "refresh_token": rt, "client_id": CLAUDE_CLIENT_ID}
    tok, last_err = None, None
    for url in CLAUDE_TOKEN_URLS:
        try:
            tok = http_post_json(url, body, {"User-Agent": "claude-code/2.0"})
            break
        except urllib.error.HTTPError as e:
            if e.code in (400, 401):
                raise LoginExpired("claude")
            last_err = e
        except urllib.error.URLError as e:
            last_err = e
    if tok is None:
        raise last_err
    oauth["accessToken"] = tok["access_token"]
    if tok.get("refresh_token"):
        oauth["refreshToken"] = tok["refresh_token"]
    if tok.get("expires_in"):
        oauth["expiresAt"] = int((time.time() + float(tok["expires_in"])) * 1000)
    store.save()
    return oauth


def claude_usage(token):
    h = {"Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20",
         "User-Agent": "claude-code/2.0", "Accept": "application/json"}
    return http_json(CLAUDE_USAGE_URL, h)


def fetch_claude(cfg):
    c = cfg["claude"]
    sk = (c.get("session_key") or "").strip()
    if sk:
        # Variante B: Browser-Cookie "sessionKey" von claude.ai
        h = {"Cookie": f"sessionKey={sk}", "User-Agent": BROWSER_UA,
             "Accept": "application/json"}
        orgs = http_json("https://claude.ai/api/organizations", h)
        org = next((o for o in orgs if "chat" in (o.get("capabilities") or [])), orgs[0])
        data = http_json(f"https://claude.ai/api/organizations/{org['uuid']}/usage", h)
    else:
        # Variante A: Anmeldung von Claude Code
        store = ClaudeCredentials(c.get("credentials_path"))
        store.load()
        oauth = store.oauth
        expires = (oauth.get("expiresAt") or 0) / 1000
        if expires and expires < time.time() + 120:
            oauth = refresh_claude(store)
        try:
            data = claude_usage(oauth["accessToken"])
        except urllib.error.HTTPError as e:
            if e.code != 401:
                raise
            data = claude_usage(refresh_claude(store)["accessToken"])

    debug_dump(cfg, "claude", data)
    rows = []
    for key, label in (("five_hour", "5 STD"), ("seven_day", "WOCHE"),
                       ("seven_day_opus", "WOCHE OPUS")):
        w = data.get(key)
        if isinstance(w, dict) and w.get("utilization") is not None:
            rows.append((label, float(w["utilization"]), parse_time(w.get("resets_at"))))
    if not rows:
        raise ValueError("Unbekanntes Antwortformat (debug aktivieren)")
    return rows


def codex_auth_path(cfg):
    base = os.environ.get("CODEX_HOME") or os.path.join(HOME, ".codex")
    return cfg["chatgpt"].get("auth_path") or os.path.join(base, "auth.json")


def refresh_codex(path):
    """Erneuert den Codex-Zugang und speichert ihn zurueck in auth.json."""
    auth = read_json(path)
    t = auth.get("tokens") or {}
    rt = t.get("refresh_token")
    if not rt or not is_writable(path):
        raise LoginExpired("chatgpt")
    try:
        tok = http_post_json(CODEX_TOKEN_URL, {
            "client_id": CODEX_CLIENT_ID, "grant_type": "refresh_token",
            "refresh_token": rt, "scope": "openid profile email"})
    except urllib.error.HTTPError as e:
        if e.code in (400, 401):
            raise LoginExpired("chatgpt")
        raise
    for src, dst in (("access_token", "access_token"), ("refresh_token", "refresh_token"),
                     ("id_token", "id_token")):
        if tok.get(src):
            t[dst] = tok[src]
    auth["tokens"] = t
    auth["last_refresh"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    write_json_atomic(path, auth)
    return t


def codex_usage(t):
    token = t.get("access_token")
    if not token:
        raise ValueError("Kein ChatGPT-Login in auth.json")
    h = {"Authorization": f"Bearer {token}", "User-Agent": "codex_cli_rs",
         "Accept": "application/json"}
    if t.get("account_id"):
        h["ChatGPT-Account-Id"] = t["account_id"]
    return http_json(CODEX_USAGE_URL, h)


def fetch_chatgpt(cfg):
    # Anmeldung der Codex-App/CLI (%USERPROFILE%\.codex\auth.json)
    path = codex_auth_path(cfg)
    t = read_json(path).get("tokens") or {}
    try:
        data = codex_usage(t)
    except urllib.error.HTTPError as e:
        if e.code != 401:
            raise
        fresh = read_json(path).get("tokens") or {}
        if fresh.get("access_token") and fresh.get("access_token") != t.get("access_token"):
            data = codex_usage(fresh)          # Codex hat inzwischen selbst erneuert
        else:
            data = codex_usage(refresh_codex(path))

    debug_dump(cfg, "chatgpt", data)
    rl = data.get("rate_limit") or data
    rows = []
    for key in ("primary_window", "secondary_window"):
        w = rl.get(key)
        if not isinstance(w, dict):
            continue
        reset = parse_time(w.get("reset_at"))
        if reset is None and w.get("reset_after_seconds") is not None:
            reset = dt.datetime.now().astimezone() + dt.timedelta(seconds=w["reset_after_seconds"])
        rows.append((window_label(w.get("limit_window_seconds")),
                     float(w.get("used_percent", 0)), reset))
    if not rows:
        raise ValueError("Unbekanntes Antwortformat (debug aktivieren)")
    return rows


# ---- DeepSeek: die API kennt kein Zeitfenster-Limit, nur ein Guthaben.
def ds_money(v, sym):
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{sym}{s}" if sym else s


def ds_num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def ds_history_add(total, currency, now):
    """Messpunkte mitschreiben, damit sich Verbrauch pro Tag schaetzen laesst."""
    try:
        hist = read_json(DS_HISTORY_PATH)
        if not isinstance(hist, list):
            hist = []
    except Exception:
        hist = []
    stamp = int(now.timestamp())
    hist = [h for h in hist if len(h) > 2 and h[2] == currency]   # Waehrungen nie mischen
    if hist and stamp - int(hist[-1][0]) < 600:      # hoechstens alle 10 Minuten
        hist[-1] = [stamp, total, currency]
    else:
        hist.append([stamp, total, currency])
    hist = [h for h in hist if stamp - int(h[0]) <= 30 * 86400][-500:]
    try:
        with open(DS_HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(hist, f)
    except Exception:
        pass
    return hist


def ds_days_left(hist, total, now):
    """Wie lange reicht das Guthaben noch? Basis: Verbrauch der letzten 7 Tage."""
    if len(hist) < 2 or total <= 0:
        return None
    cutoff = now.timestamp() - 7 * 86400
    pts = [(int(h[0]), ds_num(h[1])) for h in hist if int(h[0]) >= cutoff]
    if len(pts) < 2:
        return None
    days = (pts[-1][0] - pts[0][0]) / 86400
    spent = pts[0][1] - pts[-1][1]
    if days < 0.25 or spent <= 0:
        return None
    return total / (spent / days)


def fetch_deepseek(cfg):
    c = cfg["deepseek"]
    key = (c.get("api_key") or "").strip() or os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise LoginExpired("deepseek")
    data = http_json(DEEPSEEK_BALANCE_URL,
                     {"Authorization": f"Bearer {key}", "Accept": "application/json"})
    debug_dump(cfg, "deepseek", data)

    infos = [i for i in (data.get("balance_infos") or []) if isinstance(i, dict)]
    if not infos:
        raise ValueError("Keine Guthaben-Daten (debug aktivieren)")
    want = (c.get("currency") or "").upper()
    info = next((i for i in infos if (i.get("currency") or "").upper() == want), infos[0])
    cur = (info.get("currency") or "").upper()
    sym = DS_SYMBOL.get(cur, "")
    total = ds_num(info.get("total_balance"))
    granted = ds_num(info.get("granted_balance"))
    topped = ds_num(info.get("topped_up_balance"))

    now = dt.datetime.now().astimezone()
    hist = ds_history_add(total, cur, now)
    peak = max([total] + [ds_num(h[1]) for h in hist])
    cfg_budget = ds_num(c.get("budget"))
    budget = cfg_budget or peak
    used = 0.0 if budget <= 0 else max(0.0, min(100.0, 100.0 * (1 - total / budget)))
    ref = "BUDGET" if cfg_budget > 0 else "MAX"

    # Zeile 1: aufgeladenes Guthaben, Zeile 2: Balken-Bezug + Reichweite
    line1 = f"AUFGELADEN {ds_money(topped, sym)}"
    if granted > 0:
        line1 += f"  //  GRANT {ds_money(granted, sym)}"
    days = ds_days_left(hist, total, now)
    line2 = f"{ref} {ds_money(budget, sym)}"
    if days is not None:
        left = f"~{days:.0f} TAGE" if days >= 1 else "< 1 TAG"
        line2 += f"  //  NOCH {left}"
    if not data.get("is_available", True):
        line1, line2 = "GUTHABEN AUFGEBRAUCHT  //  BITTE AUFLADEN", ""
    return [("GUTHABEN", used, None, ds_money(total, sym), line1, line2)]


def demo_fetch(key):
    import random
    now = dt.datetime.now().astimezone()
    if key == "claude":
        return [("5 STD", random.uniform(20, 45), now + dt.timedelta(hours=3, minutes=31)),
                ("WOCHE", random.uniform(60, 70), now + dt.timedelta(days=5, hours=20))]
    if key == "deepseek":
        return [("GUTHABEN", 62.0, None, "$7,60",
                 "AUFGELADEN $5,60  //  GRANT $2,00",
                 "MAX $20,00  //  NOCH ~9 TAGE")]
    return [("5 STD", random.uniform(80, 92), now + dt.timedelta(minutes=47)),
            ("WOCHE", random.uniform(30, 40), now + dt.timedelta(days=2, hours=6))]


PROVIDERS = [("claude", "CLAUDE", "#ff8a5c", fetch_claude),
             ("chatgpt", "CHATGPT", "#19e6a7", fetch_chatgpt),
             ("deepseek", "DEEPSEEK API", DS_ACCENT, fetch_deepseek)]


def friendly_error(e, provider=""):
    if isinstance(e, LoginExpired) and e.provider == "deepseek":
        return "KEIN API-KEY  -  config.json: deepseek.api_key"
    if isinstance(e, LoginExpired):
        if e.provider == "claude":
            return "LOGIN ABGELAUFEN  -  Claude Code einmal starten und anmelden"
        return "LOGIN ABGELAUFEN  -  Codex einmal starten und anmelden"
    if isinstance(e, FileNotFoundError):
        return "NICHT ANGEMELDET  -  Login-Datei fehlt"
    if isinstance(e, urllib.error.HTTPError):
        if provider == "deepseek" and e.code == 402:
            return "GUTHABEN AUFGEBRAUCHT  -  BITTE AUFLADEN"
        if e.code in (401, 403):
            if provider == "deepseek":
                return f"API-KEY UNGUELTIG ({e.code})"
            return f"ZUGRIFF VERWEIGERT ({e.code})"
        if e.code == 429:
            return "ZU VIELE ANFRAGEN  -  versuche es gleich erneut"
        return f"SERVERFEHLER {e.code}"
    if isinstance(e, urllib.error.URLError):
        return "KEINE VERBINDUNG"
    return str(e)[:60]


def log_error(cfg, provider, err):
    if not cfg.get("debug"):
        return
    import traceback
    try:
        with open(os.path.join(APP_DIR, "ki_kontingent.log"), "a", encoding="utf-8") as f:
            f.write(f"--- {dt.datetime.now():%Y-%m-%d %H:%M:%S} {provider} v{__version__}\n")
            f.write("".join(traceback.format_exception(type(err), err, err.__traceback__)))
    except Exception:
        pass


# ---------------------------------------------------------------- Bausteine
class SegmentBar:
    """Segmentierter Balken, wird nur umgefaerbt - nie neu gezeichnet."""

    def __init__(self, parent):
        self.c = tk.Canvas(parent, width=W, height=9, bg=PANEL, highlightthickness=0, bd=0)
        gap = 2
        seg = (W - gap * (SEGMENTS - 1)) / SEGMENTS
        self.items = []
        for i in range(SEGMENTS):
            x = i * (seg + gap)
            self.items.append(self.c.create_rectangle(x, 0, x + seg, 9, fill=SEG_OFF, width=0))
        self.state = [None] * SEGMENTS

    def set(self, frac, color):
        lit = frac * SEGMENTS
        full = int(lit)
        for i, item in enumerate(self.items):
            if i < full:
                # leichter Verlauf: hintere Segmente etwas dunkler
                col = mix(color, PANEL, 0.35 * (1 - i / max(1, full)))
            elif i == full and lit - full > 0.05:
                col = mix(SEG_OFF, color, lit - full)
            else:
                col = SEG_OFF
            if self.state[i] != col:
                self.c.itemconfig(item, fill=col)
                self.state[i] = col


class Row:
    def __init__(self, parent, label, accent):
        self.accent = accent
        self.shown = None      # aktuell angezeigter (animierter) Wert, 0..100 frei
        self.target = 0.0
        self.reset = None
        self.value_text = None  # statt "62%" z. B. "Â¥7,60"
        self.sub_text = None    # feste Unterzeile statt Reset-Countdown
        self.frame = tk.Frame(parent, bg=PANEL)
        top = tk.Frame(self.frame, bg=PANEL)
        top.pack(fill="x")
        self.lbl = tk.Label(top, text=label, bg=PANEL, fg=DIM, font=(MONO, 8, "bold"))
        self.lbl.pack(side="left", anchor="s", pady=(0, 2))
        self.pct = tk.Label(top, text="--%", bg=PANEL, fg=accent, font=(MONO, 15, "bold"))
        self.pct.pack(side="right")
        self.bar = SegmentBar(self.frame)
        self.bar.c.pack(anchor="w")
        self.sub = tk.Label(self.frame, text="", bg=PANEL, fg=DIM, font=(MONO, 8))
        self.sub.pack(anchor="w", pady=(2, 0))
        self.sub2 = tk.Label(self.frame, text="", bg=PANEL, fg=mix(DIM, PANEL, 0.25),
                             font=(MONO, 8))

    def update(self, label, used, reset, value_text=None, sub_text=None, sub2_text=None):
        self.lbl.config(text=label)
        self.target = 100.0 - max(0.0, min(100.0, used))
        self.reset = reset
        self.value_text = value_text
        self.sub_text = sub_text
        self.sub2_text = sub2_text
        if sub2_text:
            if not self.sub2.winfo_ismapped():
                self.sub2.pack(anchor="w", pady=(1, 0))
            self.sub2.config(text=sub2_text)
        else:
            self.sub2.pack_forget()
        if self.shown is None:
            self.shown = 0.0   # beim ersten Mal hochfahren lassen

    def color(self, free):
        if free >= 40:
            return self.accent
        if free >= 15:
            return AMBER
        return RED

    def animate(self):
        if self.shown is None:
            return
        diff = self.target - self.shown
        if abs(diff) < 0.05:
            if self.shown == self.target:
                return
            self.shown = self.target
        else:
            self.shown += diff * 0.12
        col = self.color(self.shown)
        self.bar.set(self.shown / 100, col)
        txt = self.value_text if self.value_text is not None else f"{self.shown:.0f}%"
        if self.pct.cget("text") != txt or self.pct.cget("fg") != col:
            self.pct.config(text=txt, fg=col)

    def tick_countdown(self, now):
        t = self.reset
        if self.sub_text is not None:
            txt = self.sub_text
        elif not t:
            txt = f"{100 - self.target:.0f}% GENUTZT"
        else:
            when = t.strftime("%H:%M") if t.date() == now.date() else \
                f"{WEEKDAYS[t.weekday()]} {t.strftime('%d.%m. %H:%M')}"
            secs = max(0, int((t - now).total_seconds()))
            d, rem = divmod(secs, 86400)
            h, rem = divmod(rem, 3600)
            m = rem // 60
            left = f"{d}T {h:02d}H" if d else f"{h:02d}:{m:02d}"
            txt = f"RESET {when}  //  T-{left}"
        if self.sub.cget("text") != txt:
            self.sub.config(text=txt)


class Section:
    def __init__(self, parent, name, accent):
        self.accent = accent
        self.frame = tk.Frame(parent, bg=PANEL, padx=10, pady=8,
                              highlightthickness=1, highlightbackground=mix(accent, BG, 0.75))
        head = tk.Frame(self.frame, bg=PANEL)
        head.pack(fill="x", pady=(0, 4))
        mark = tk.Canvas(head, width=4, height=12, bg=accent, highlightthickness=0)
        mark.pack(side="left", padx=(0, 6))
        tk.Label(head, text=name, bg=PANEL, fg=accent, font=(MONO, 10, "bold")).pack(side="left")
        self.state_lbl = tk.Label(head, text="", bg=PANEL, fg=DIM, font=(MONO, 7))
        self.state_lbl.pack(side="right")
        self.body = tk.Frame(self.frame, bg=PANEL)
        self.body.pack(fill="x")
        self.rows = []
        self.err = None
        self.wait = tk.Label(self.body, text="VERBINDE ...", bg=PANEL, fg=DIM, font=(MONO, 8))
        self.wait.pack(anchor="w")

    def apply(self, rows, err):
        """Gibt True zurueck, wenn sich die Struktur geaendert hat (neue Widgets)."""
        changed = False
        if self.wait is not None:
            self.wait.destroy()
            self.wait = None
            changed = True
        if err:
            for r in self.rows:
                r.frame.pack_forget()
            if self.err is None:
                self.err = tk.Label(self.body, bg=PANEL, fg=RED, font=(MONO, 8),
                                    wraplength=W, justify="left")
                changed = True
            self.err.config(text=f"! {err}")
            self.err.pack(anchor="w")
            self.state_lbl.config(text="OFFLINE", fg=RED)
            return changed
        if self.err is not None:
            self.err.pack_forget()
        while len(self.rows) < len(rows):
            self.rows.append(Row(self.body, rows[len(self.rows)][0], self.accent))
            changed = True
        for i, r in enumerate(self.rows):
            if i < len(rows):
                r.update(*rows[i])
                r.frame.pack(fill="x", pady=(0 if i == 0 else 6, 0))
            else:
                r.frame.pack_forget()
        self.state_lbl.config(text="ONLINE", fg=mix(self.accent, BG, 0.3))
        return changed


# ---------------------------------------------------------------- Fenster
class Widget:
    def __init__(self):
        self.cfg = load_config()
        self.pending = None
        self.busy = False
        self.last_fetch = None
        self.phase = 0.0
        self.needs_fit = False

        r = self.root = tk.Tk()
        r.title("KI-Kontingent")
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        try:
            alpha = min(1.0, max(0.3, float(self.cfg.get("opacity", 0.94))))
        except (TypeError, ValueError):
            alpha = 0.94
        r.attributes("-alpha", alpha)
        r.configure(bg=BORDER)
        r.report_callback_exception = self._tk_error
        pos = self.cfg.get("position")
        if pos:
            # Position kann von einem nicht mehr vorhandenen Monitor stammen -> auf den Schirm holen
            try:
                px, py = int(pos[0]), int(pos[1])
            except (TypeError, ValueError, IndexError):
                px = py = 0
            vs = virtual_screen()
            if vs:
                vx, vy, vw, vh = vs
            else:
                vx, vy, vw, vh = 0, 0, r.winfo_screenwidth(), r.winfo_screenheight()
            px = min(max(px, vx - 40), max(vx, vx + vw - 120))
            py = min(max(py, vy), max(vy, vy + vh - 80))
            r.geometry(f"+{px}+{py}")
        else:
            r.geometry(f"+{r.winfo_screenwidth() - 310}+{r.winfo_screenheight() - 620}")

        outer = tk.Frame(r, bg=BG, padx=10, pady=8)
        outer.pack(padx=1, pady=1)

        # Kopfzeile
        head = tk.Frame(outer, bg=BG)
        head.pack(fill="x")
        tri = tk.Canvas(head, width=10, height=10, bg=BG, highlightthickness=0)
        tri.create_polygon(0, 10, 10, 10, 10, 0, fill=CYAN, width=0)
        tri.pack(side="left", padx=(0, 6))
        tk.Label(head, text="KI//KONTINGENT", bg=BG, fg=CYAN,
                 font=(MONO, 9, "bold")).pack(side="left")
        self.dot = tk.Canvas(head, width=8, height=8, bg=BG, highlightthickness=0)
        self.dot_item = self.dot.create_oval(0, 0, 8, 8, fill=DIM, width=0)
        self.dot.pack(side="right", pady=(2, 0))
        self.live = tk.Label(head, text="INIT", bg=BG, fg=DIM, font=(MONO, 7))
        self.live.pack(side="right", padx=(0, 5))

        # Scanline unter dem Kopf
        self.scan = tk.Canvas(outer, width=W + 22, height=2, bg=BG, highlightthickness=0)
        self.scan.pack(pady=(5, 8))
        self.scan.create_rectangle(0, 0, W + 22, 2, fill="#0d2a33", width=0)
        self.scan_item = self.scan.create_rectangle(0, 0, 60, 2, fill=CYAN, width=0)

        self.outer = outer
        self.sections = {}
        for key, name, accent, _ in PROVIDERS:
            if self.section_wanted(key):
                self.add_section(key)

        self.foot = tk.Label(outer, text="", bg=BG, fg=DIM, font=(MONO, 7))
        self.foot.pack(anchor="w", pady=(2, 0))

        self.menu = tk.Menu(r, tearoff=0, bg=PANEL, fg=TEXT, activebackground=BORDER,
                            activeforeground=CYAN, bd=0)
        self.menu.add_command(label=f"KI-Kontingent v{__version__}", state="disabled")
        self.menu.add_separator()
        self.menu.add_command(label="Jetzt aktualisieren", command=self.refresh)
        self.topmost = tk.BooleanVar(value=True)
        self.menu.add_checkbutton(label="Immer im Vordergrund", variable=self.topmost,
                                  command=lambda: r.attributes("-topmost", self.topmost.get()))
        self.ds_var = tk.BooleanVar(value="deepseek" in self.sections)
        self.menu.add_checkbutton(label="DeepSeek-Karte anzeigen", variable=self.ds_var,
                                  command=self.toggle_deepseek)
        self.menu.add_command(label="Konfiguration oeffnen", command=self.open_config)
        self.menu.add_separator()
        self.menu.add_command(label="Beenden", command=r.destroy)

        self._drag = (0, 0)
        self.bind_tree(r)
        self.refresh()
        self.root.after(16, self.animate)
        self.root.after(250, self.tick)

    def section_wanted(self, key):
        """Karte anzeigen? DeepSeek ohne Key standardmaessig ausblenden."""
        conf = self.cfg.get(key) or {}
        if not conf.get("enabled", True):
            return False
        if key == "deepseek" and conf.get("hide_without_key", True):
            if not (str(conf.get("api_key") or "").strip()
                    or os.environ.get("DEEPSEEK_API_KEY", "").strip()):
                return False
        return True

    def add_section(self, key):
        info = next(p for p in PROVIDERS if p[0] == key)
        s = Section(self.outer, info[1], info[2])
        s.frame.pack(fill="x", pady=(0, 6))
        self.sections[key] = s
        self.bind_tree(s.frame)
        self.needs_fit = True

    def toggle_deepseek(self):
        show = bool(self.ds_var.get())
        conf = self.cfg.setdefault("deepseek", {})
        conf["enabled"] = show
        if show:
            conf["hide_without_key"] = False   # bewusst eingeblendet -> bleibt sichtbar
        save_config(self.cfg)
        if show and "deepseek" not in self.sections:
            self.add_section("deepseek")
            self.refresh()
        elif not show and "deepseek" in self.sections:
            self.sections.pop("deepseek").frame.destroy()

    def open_config(self):
        try:
            if not os.path.exists(CONFIG_PATH):
                save_config(self.cfg)
            if IS_WIN:
                os.startfile(CONFIG_PATH)
            elif IS_MAC:
                subprocess.Popen(["open", "-t", CONFIG_PATH])
            else:
                subprocess.Popen(["xdg-open", CONFIG_PATH])
        except Exception as e:
            self.show_error(f"Konfiguration konnte nicht geoeffnet werden:\n{e}\n\nDatei: {CONFIG_PATH}")

    def show_error(self, text):
        try:
            from tkinter import messagebox
            messagebox.showerror("KI-Kontingent", text)
        except Exception:
            pass

    def _tk_error(self, exc, val, tb):
        import traceback
        path = log_crash("".join(traceback.format_exception(exc, val, tb)))
        self.show_error(f"Interner Fehler:\n{val}\n\nDetails stehen in:\n{path}")

    # -- Maus
    def bind_tree(self, w):
        w.bind("<ButtonPress-1>", self.start_drag, add="+")
        w.bind("<B1-Motion>", self.do_drag, add="+")
        w.bind("<ButtonRelease-1>", self.end_drag, add="+")
        popup = lambda e: self.menu.tk_popup(e.x_root, e.y_root)
        w.bind("<Button-3>", popup, add="+")
        if IS_MAC:  # Rechtsklick/Ctrl-Klick auf dem Mac
            w.bind("<Button-2>", popup, add="+")
            w.bind("<Control-Button-1>", popup, add="+")
        w.bind("<Double-Button-1>", lambda e: self.refresh(), add="+")
        for c in w.winfo_children():
            if not isinstance(c, tk.Menu):
                self.bind_tree(c)

    def start_drag(self, e):
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def do_drag(self, e):
        self.root.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def end_drag(self, e):
        self.cfg["position"] = [self.root.winfo_x(), self.root.winfo_y()]
        save_config(self.cfg)

    def fit_to_screen(self):
        """Nach dem ersten Befuellen passend in die Ecke setzen (nicht ausserhalb)."""
        r = self.root
        r.update_idletasks()
        w, h = r.winfo_width(), r.winfo_height()
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        r.geometry(f"+{max(0, sw - w - 24)}+{max(0, sh - h - 48)}")

    # -- Daten
    def refresh(self):
        if self.busy:
            return
        self.busy = True
        threading.Thread(target=self._fetch_all, daemon=True).start()

    def _fetch_all(self):
        res = {}
        for key, _, _, fn in PROVIDERS:
            if key not in self.sections:
                continue
            try:
                res[key] = (demo_fetch(key) if DEMO else fn(self.cfg), None)
            except Exception as e:
                log_error(self.cfg, key, e)
                res[key] = (None, friendly_error(e, key))
        self.pending = res

    def tick(self):
        now = dt.datetime.now().astimezone()
        if self.pending is not None:
            res, self.pending = self.pending, None
            self.busy = False
            self.last_fetch = now
            for key, (rows, err) in res.items():
                if self.sections[key].apply(rows, err):
                    self.bind_tree(self.sections[key].frame)
                    self.needs_fit = True
            if self.needs_fit and not self.cfg.get("position"):
                self.fit_to_screen()
                self.needs_fit = False
        elif self.last_fetch and not self.busy:
            interval = max(1, int(self.cfg.get("interval_minutes", 5)))
            age = (now - self.last_fetch).total_seconds()
            reset_passed = any(r.reset and r.reset <= now and r.shown is not None
                               for s in self.sections.values() for r in s.rows)
            if age >= interval * 60 or (reset_passed and age > 60):
                self.refresh()

        for s in self.sections.values():
            for r in s.rows:
                r.tick_countdown(now)

        if self.busy:
            self.live.config(text="SYNC", fg=CYAN)
            txt = "SYNCHRONISIERE ..."
        else:
            self.live.config(text="LIVE", fg=mix(CYAN, BG, 0.3))
            if self.last_fetch:
                interval = max(1, int(self.cfg.get("interval_minutes", 5))) * 60
                nxt = max(0, int(interval - (now - self.last_fetch).total_seconds()))
                txt = f"STAND {self.last_fetch:%H:%M}  //  NEXT {nxt // 60}:{nxt % 60:02d}"
            else:
                txt = ""
        if DEMO:
            txt += "  [DEMO]"
        if self.foot.cget("text") != txt:
            self.foot.config(text=txt)
        self.root.after(250, self.tick)

    # -- Animation (Balken, Statuspunkt, Scanline)
    def animate(self):
        for s in self.sections.values():
            for r in s.rows:
                r.animate()
        self.phase += 0.06 if self.busy else 0.025
        glow = (math.sin(self.phase * 3) + 1) / 2
        dot = mix(CYAN, BG, 0.1 + 0.6 * glow) if self.busy else mix("#2bff88", BG, 0.25 + 0.35 * glow)
        self.dot.itemconfig(self.dot_item, fill=dot)
        span = W + 22 + 60
        x = (self.phase * (260 if self.busy else 90)) % span - 60
        self.scan.coords(self.scan_item, x, 0, x + 60, 2)
        self.root.after(16 if self.busy else 33, self.animate)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    try:
        Widget().run()
    except Exception:
        import traceback
        crash_path = log_crash(traceback.format_exc())
        try:
            import tkinter.messagebox as mb
            mb.showerror("KI-Kontingent",
                         f"Start fehlgeschlagen.\n\nDetails stehen in:\n{crash_path}")
        except Exception:
            pass
