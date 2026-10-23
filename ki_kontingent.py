"""
KI-Kontingent-Widget fuer Windows und macOS  -  HUD-Edition
Zeigt Nutzungslimits von Claude und ChatGPT (Codex) inkl. Reset-Zeitpunkt.
Keine Zusatzpakete noetig (nur Python-Standardbibliothek).

Linke Maustaste ziehen = verschieben | Doppelklick = aktualisieren
Rechtsklick = Menue | Start mit --demo zeigt Beispieldaten
"""
import datetime as dt
import json
import math
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request

__version__ = "1.1.0"
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
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            user = json.load(f)
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    except FileNotFoundError:
        save_config(cfg)
    except Exception:
        pass
    return cfg


def save_config(cfg):
    if DEMO:
        return
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


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


# ---------------------------------------------------------------- Anbieter
CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CLAUDE_TOKEN_URLS = ["https://platform.claude.com/v1/oauth/token",
                     "https://console.anthropic.com/v1/oauth/token"]
CLAUDE_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
CLAUDE_KEYCHAIN = "Claude Code-credentials"
CODEX_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
CODEX_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"


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


def demo_fetch(key):
    import random
    now = dt.datetime.now().astimezone()
    if key == "claude":
        return [("5 STD", random.uniform(20, 45), now + dt.timedelta(hours=3, minutes=31)),
                ("WOCHE", random.uniform(60, 70), now + dt.timedelta(days=5, hours=20))]
    return [("5 STD", random.uniform(80, 92), now + dt.timedelta(minutes=47)),
            ("WOCHE", random.uniform(30, 40), now + dt.timedelta(days=2, hours=6))]


PROVIDERS = [("claude", "CLAUDE", "#ff8a5c", fetch_claude),
             ("chatgpt", "CHATGPT", "#19e6a7", fetch_chatgpt)]


def friendly_error(e):
    if isinstance(e, LoginExpired):
        if e.provider == "claude":
            return "LOGIN ABGELAUFEN  -  Claude Code einmal starten und anmelden"
        return "LOGIN ABGELAUFEN  -  Codex einmal starten und anmelden"
    if isinstance(e, FileNotFoundError):
        return "NICHT ANGEMELDET  -  Login-Datei fehlt"
    if isinstance(e, urllib.error.HTTPError):
        if e.code in (401, 403):
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

    def update(self, label, used, reset):
        self.lbl.config(text=label)
        self.target = 100.0 - max(0.0, min(100.0, used))
        self.reset = reset
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
        txt = f"{self.shown:.0f}%"
        if self.pct.cget("text") != txt or self.pct.cget("fg") != col:
            self.pct.config(text=txt, fg=col)

    def tick_countdown(self, now):
        t = self.reset
        if not t:
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

        r = self.root = tk.Tk()
        r.title("KI-Kontingent")
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        r.attributes("-alpha", float(self.cfg.get("opacity", 0.94)))
        r.configure(bg=BORDER)
        pos = self.cfg.get("position")
        if pos:
            r.geometry(f"+{pos[0]}+{pos[1]}")
        else:
            r.geometry(f"+{r.winfo_screenwidth() - 310}+{r.winfo_screenheight() - 380}")

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

        self.sections = {}
        for key, name, accent, _ in PROVIDERS:
            if self.cfg.get(key, {}).get("enabled", True):
                s = Section(outer, name, accent)
                s.frame.pack(fill="x", pady=(0, 6))
                self.sections[key] = s

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
        self.menu.add_command(label="Konfiguration oeffnen", command=self.open_config)
        self.menu.add_separator()
        self.menu.add_command(label="Beenden", command=r.destroy)

        self._drag = (0, 0)
        self.bind_tree(r)
        self.refresh()
        self.root.after(16, self.animate)
        self.root.after(250, self.tick)

    def open_config(self):
        try:
            if IS_WIN:
                os.startfile(CONFIG_PATH)
            elif IS_MAC:
                subprocess.Popen(["open", "-t", CONFIG_PATH])
            else:
                subprocess.Popen(["xdg-open", CONFIG_PATH])
        except Exception:
            pass

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
                res[key] = (None, friendly_error(e))
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
    Widget().run()
