# KI-Kontingent

Kleines Desktop-Widget für **Windows und macOS**, das deine Nutzungslimits von **Claude** und **ChatGPT**, dein **Gemini**-Kontingent sowie dein **DeepSeek-API-Guthaben** anzeigt – mit verbleibenden Prozent, Reset-Zeitpunkt und Countdown. Aktualisiert sich automatisch.

> Inoffizielles Projekt, nicht verbunden mit Anthropic, OpenAI oder DeepSeek. Es nutzt nicht dokumentierte Schnittstellen, die sich jederzeit ändern können.

## Download
Unter **Releases** die passende Datei laden:
- `KI-Kontingent-Windows.zip` → entpacken → `KI-Kontingent.exe` starten
- `KI-Kontingent-macOS.zip` → entpacken → `KI-Kontingent.app` in „Programme“ ziehen

Kein Python nötig.

**Erster Start – Sicherheitswarnung:** Die App ist (noch) nicht signiert.
- Windows: „Der Computer wurde durch Windows geschützt“ → *Weitere Informationen* → *Trotzdem ausführen*
- macOS: Rechtsklick auf die App → *Öffnen* → *Öffnen* (nur beim ersten Mal). Beim ersten Abruf fragt macOS, ob die App auf den Schlüsselbund-Eintrag „Claude Code-credentials“ zugreifen darf → *Erlauben*.

## Voraussetzungen
Das Widget liest die Anmeldung, die schon auf deinem Rechner liegt:

| Anbieter | Benötigt | Angezeigt |
|---|---|---|
| Claude | [Claude Code](https://claude.com/claude-code) einmal angemeldet | 5-Stunden- und Wochenlimit deines Abos |
| ChatGPT | [Codex](https://openai.com/codex) (App oder CLI) einmal mit ChatGPT angemeldet | Codex-Limits (5 Std. + Woche) deines Abos |
| DeepSeek | API-Key von [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys) | Guthaben in USD (kein Zeitfenster-Limit) |
| Gemini | [Gemini CLI](https://github.com/google-gemini/gemini-cli) einmal mit Google angemeldet | Kontingent pro Modell (Code Assist) |

Ein Anbieter ohne Login zeigt einfach „Nicht angemeldet“. In der Konfiguration kannst du ihn mit `"enabled": false` ausblenden. Die DeepSeek-Karte erscheint erst, wenn ein API-Key hinterlegt ist – ohne Key wird sie automatisch weggelassen (`"hide_without_key": true`); die Gemini-Karte ebenso ohne CLI-Login (`"hide_without_login": true`).

**Datenschutz:** Die Zugangsdaten verlassen deinen Rechner nur in Richtung des jeweiligen Anbieters (Anthropic, OpenAI, Google bzw. DeepSeek). Es gibt keinen eigenen Server, keine Telemetrie.

Läuft der Login ab, erneuert das Widget ihn automatisch und speichert ihn zurück – Claude Code, Codex und die Gemini CLI bleiben dabei angemeldet. Nur wenn das nicht klappt (z. B. nach Abmelden), erscheint „Login abgelaufen“: dann die jeweilige CLI einmal starten und anmelden.

## DeepSeek-Guthaben
Die DeepSeek-API kennt keine 5-Stunden- oder Wochenfenster. Abrufbar ist nur das Guthaben (`GET https://api.deepseek.com/user/balance`), deshalb zeigt die Karte:

| Anzeige | Bedeutung |
|---|---|
| `$7,60` | aktuelles Gesamtguthaben (`total_balance`) |
| Balken | Guthaben im Verhältnis zu `MAX` bzw. `BUDGET` |
| `AUFGELADEN $5,60` | selbst aufgeladenes Guthaben (`topped_up_balance`) |
| `-$0,35/TAG` | Verbrauch pro Tag (Aufladungen zählen nicht mit) |
| `GRANT $2,00` | gewährtes Guthaben, falls vorhanden |
| `MAX $20,00` | höchster Stand, den das Widget je gesehen hat |
| `NOCH ~9 TAGE` | Prognose: Guthaben ÷ Verbrauch pro Tag |

Die Messpunkte dafür liegen in `deepseek_history.json` neben der `config.json` (jeder Abruf ein Messpunkt, 30 Tage Aufbewahrung, pro Währung getrennt). Die Prognose erscheint, sobald zwei Messpunkte über mindestens eine halbe Stunde vorliegen – also nach etwa einer Stunde Laufzeit.

## Gemini-Kontingent
Die Gemini-Karte nutzt den Login der **Gemini CLI** (`~/.gemini/oauth_creds.json`) und fragt
die Code-Assist-API (`retrieveUserQuota`) nach dem Kontingent pro Modell. Angezeigt werden
verbleibender Anteil und Reset-Zeitpunkt – wie bei Claude.

```powershell
npm.cmd install -g @google/gemini-cli
gemini        # beim ersten Start "Login with Google"
```

Free, AI Pro und AI Ultra funktionieren mit demselben Google-Konto; je nach Tarif erscheinen
mehr Modelle. Ohne Login wird die Karte weggelassen (`"hide_without_login": true`).

```json
"gemini": {
  "enabled": true,
  "creds_path": "",
  "models": [],
  "hide_without_login": true
}
```

`models` filtert optional per Teilstring (z. B. `["2.5-pro"]`), leer = alle Modelle (max. vier
Zeilen). Ein AI-Studio-API-Key liefert kein Kontingent – Google veröffentlicht dafür keine
Schnittstelle.

## Bedienung
- Ziehen mit linker Maustaste · Doppelklick = aktualisieren
- Rechtsklick (Mac: auch Ctrl-Klick) = Menü: Aktualisieren, Vordergrund an/aus, DeepSeek-Karte an/aus, Konfiguration, Beenden
- Konfiguration: Windows `%APPDATA%\KI-Kontingent\config.json`, macOS `~/Library/Application Support/KI-Kontingent/config.json`

| Einstellung | Bedeutung |
|---|---|
| `interval_minutes` | Abfrage-Intervall (Standard 5) |
| `opacity` | Transparenz 0.5–1.0 |
| `debug` | schreibt die Rohantworten als `debug_*.json` und Fehler in `ki_kontingent.log` neben die Konfiguration |

DeepSeek-Block in der `config.json`:

```json
"deepseek": {
  "enabled": true,
  "api_key": "sk-...",
  "currency": "USD",
  "budget": 0,
  "hide_without_key": true
}
```

| Feld | Bedeutung |
|---|---|
| `api_key` | DeepSeek-API-Key; leer = `DEEPSEEK_API_KEY` aus der Umgebung |
| `currency` | `"USD"` (Standard) oder `"CNY"` |
| `budget` | Referenzbetrag für den Balken; `0` = automatisch (höchster Stand) |
| `hide_without_key` | Karte ohne API-Key komplett ausblenden |

Fehlermeldungen: `KEIN API-KEY` (kein Key hinterlegt), `API-KEY UNGUELTIG (401)`, `GUTHABEN AUFGEBRAUCHT` (HTTP 402).

## Autostart
- Windows: `Win + R` → `shell:startup` → Verknüpfung zur `.exe` hineinlegen
- macOS: Systemeinstellungen → Allgemein → Anmeldeobjekte → `+` → KI-Kontingent

## Selbst bauen
```
pip install pyinstaller
pyinstaller --onefile --noconsole --name KI-Kontingent ki_kontingent.py    # Windows
pyinstaller --windowed --name KI-Kontingent ki_kontingent.py               # macOS
```
Oder ohne Build: `python ki_kontingent.py` (Vorschau mit Beispieldaten: `--demo`).

Neue Version veröffentlichen: auf GitHub unter *Releases → Draft a new release* einen neuen Tag (z. B. v1.2.0) anlegen – GitHub baut beide Versionen und hängt sie automatisch an.

## Lizenz
MIT – siehe [LICENSE](LICENSE).
