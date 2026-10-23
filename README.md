# KI-Kontingent

Kleines Desktop-Widget für **Windows und macOS**, das deine Nutzungslimits von **Claude** und **ChatGPT** anzeigt – mit verbleibenden Prozent, Reset-Zeitpunkt und Countdown. Aktualisiert sich automatisch.

> Inoffizielles Projekt, nicht verbunden mit Anthropic oder OpenAI. Es nutzt nicht dokumentierte Schnittstellen, die sich jederzeit ändern können.

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

Ein Anbieter ohne Login zeigt einfach „Nicht angemeldet“. In der Konfiguration kannst du ihn mit `"enabled": false` ausblenden.

**Datenschutz:** Die Zugangsdaten verlassen deinen Rechner nur in Richtung des jeweiligen Anbieters (Anthropic bzw. OpenAI). Es gibt keinen eigenen Server, keine Telemetrie.

## Bedienung
- Ziehen mit linker Maustaste · Doppelklick = aktualisieren
- Rechtsklick (Mac: auch Ctrl-Klick) = Menü: Aktualisieren, Vordergrund an/aus, Konfiguration, Beenden
- Konfiguration: Windows `%APPDATA%\KI-Kontingent\config.json`, macOS `~/Library/Application Support/KI-Kontingent/config.json`

| Einstellung | Bedeutung |
|---|---|
| `interval_minutes` | Abfrage-Intervall (Standard 5) |
| `opacity` | Transparenz 0.5–1.0 |
| `debug` | schreibt die Rohantworten als `debug_*.json` neben die Konfiguration |

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

Neue Version veröffentlichen: auf GitHub unter *Releases → Draft a new release* einen neuen Tag (z. B. `v1.1.0`) anlegen – GitHub baut beide Versionen und hängt sie automatisch an.

## Lizenz
MIT – siehe [LICENSE](LICENSE).
