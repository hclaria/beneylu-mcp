#!/usr/bin/env python3
"""Script « monitor » d'un cron Hermes : nouveautés Beneylu -> Telegram des parents, avec accusé de réception.

1. whats_new (serveur MCP beneylu-mcp, via stdio) ;
2. envoi direct par l'API du bot Telegram à chaque parent ;
3. ack(cursor) seulement si tous les envois ont réussi. Sinon rien n'est confirmé et les nouveautés
   reviennent au passage suivant, marquées comme rappel ;
4. affiche un historique stable des derniers éléments transmis (+ une ligne d'échec éventuelle).
   Hermes compare cette sortie à celle du passage précédent : identique -> aucun agent ne démarre (0 token) ;
   différente -> l'agent du cron se réveille avec le diff et pose les rappels.
N'utilise jamais get_conversation (ne marque rien comme lu côté école).
"""
import json, os, subprocess, textwrap, urllib.request, urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")

# Configuration (variables d'environnement) :
#   BENEYLU_MCP_CMD      commande qui lance le serveur MCP (ex. "uvx --from /chemin/beneylu-mcp beneylu-mcp")
#   HERMES_ENV           fichier .env de Hermes contenant TELEGRAM_BOT_TOKEN (défaut ~/.hermes/.env)
#   BENEYLU_CHATS        destinataires "Nom:chat_id,Nom:chat_id"
#   BENEYLU_KIDS         prénoms à garder dans les résumés "Prénom1,Prénom2"
#   BENEYLU_SENT_LOG     historique des envois (défaut ~/.hermes/cache/beneylu_sent_log.json)
RUN = os.environ.get("BENEYLU_MCP_CMD", "beneylu-mcp").split()
ENV = os.path.expanduser(os.environ.get("HERMES_ENV", "~/.hermes/.env"))
CHATS = dict(x.split(":", 1) for x in os.environ.get("BENEYLU_CHATS", "").split(",") if ":" in x)
KIDS = {k.strip() for k in os.environ.get("BENEYLU_KIDS", "").split(",") if k.strip()}


class Mcp:
    def __init__(self):
        self.p = subprocess.Popen(RUN, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True)
        self.n = 0
        self._req("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "beneylu-cron", "version": "2"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, msg):
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()

    def _req(self, method, params):
        self.n += 1
        self._send({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})
        for line in self.p.stdout:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("id") == self.n:
                if "error" in d:
                    raise RuntimeError(d["error"].get("message", "erreur MCP"))
                return d["result"]
        raise RuntimeError("le serveur MCP s'est arrêté")

    def tool(self, name, args=None):
        r = self._req("tools/call", {"name": name, "arguments": args or {}})
        text = "".join(c.get("text", "") for c in r.get("content", []))
        if r.get("isError"):
            raise RuntimeError(text[:300])
        return json.loads(text)

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=10)
        except Exception:
            self.p.kill()


def fmt_date(s):
    try:
        return datetime.fromisoformat(s).astimezone(PARIS).strftime("%d/%m à %Hh%M")
    except Exception:
        return s or ""


def render(d):
    out = []
    for p in d.get("posts", []):
        kids = [k for k in p.get("children", []) if not KIDS or k in KIDS] or ["?"]
        tag = "✏️ Mot modifié" if p.get("change") == "updated" else "📒 Nouveau mot"
        if p.get("already_reported_at"):
            tag = f"🔁 Rappel (signalé le {fmt_date(p['already_reported_at'])}, envoi non confirmé) · " + tag
        txt = textwrap.shorten(" ".join((p.get("text") or "").split()), 700, placeholder=" …")
        lines = [f"{tag} : {', '.join(kids)} ({p.get('author', '?')}, {fmt_date(p.get('date'))})", txt]
        pend = [k for k in p.get("pending_signature_for", []) if not KIDS or k in KIDS]
        if pend:
            lines.append(f"✍️ Signature attendue pour {', '.join(pend)}")
        if p.get("attachments"):
            lines.append(f"📎 {p['attachments']} pièce(s) jointe(s)")
        lines.append(p.get("url", ""))
        out.append("\n".join(lines))
    for n in d.get("notifications", []):
        t = n.get("text") or n.get("content") or n.get("title") or json.dumps(n, ensure_ascii=False)[:300]
        prefix = "🔁 Rappel · 🔔" if n.get("already_reported_at") else "🔔"
        out.append(f"{prefix} {textwrap.shorten(' '.join(str(t).split()), 400, placeholder=' …')}")
    if d.get("unread_messages_increased"):
        out.append(f"💬 {d.get('unread_messages')} message(s) non lu(s) dans la messagerie Beneylu")
    return ("🏫 Beneylu : du nouveau\n\n" + "\n\n".join(out)) if out else ""


def chunks(text, size=3900):
    parts, cur = [], ""
    for block in text.split("\n\n"):
        if cur and len(cur) + len(block) + 2 > size:
            parts.append(cur)
            cur = ""
        cur = (cur + "\n\n" + block) if cur else block
    return parts + [cur] if cur else parts


def bot_token():
    for line in open(ENV, encoding="utf-8"):
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("TELEGRAM_BOT_TOKEN introuvable")


def send(token, chat_id, text):
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=30) as r:
        if not json.loads(r.read()).get("ok"):
            raise RuntimeError("Telegram a refusé le message")


LOG = os.path.expanduser(os.environ.get("BENEYLU_SENT_LOG", "~/.hermes/cache/beneylu_sent_log.json"))
LOG_SHOWN = 15


def load_log():
    try:
        with open(LOG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"sent": [], "error": None}


def save_log(log):
    with open(LOG + ".tmp", "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    os.replace(LOG + ".tmp", LOG)


def remember_sent(log, d):
    """Append the delivered posts/notifications (deduplicated on id + text) to the sent log."""
    known = {(e["id"], e["text"]) for e in log["sent"]}
    stamp = datetime.now(PARIS).strftime("%d/%m/%Y %Hh%M")
    for p in d.get("posts", []):
        entry = {"id": p.get("id"), "kind": "mot", "sent_at": stamp, "date": fmt_date(p.get("date")),
                 "children": [k for k in p.get("children", []) if not KIDS or k in KIDS], "author": p.get("author"),
                 "text": " ".join((p.get("text") or "").split()), "url": p.get("url"),
                 "signature_for": [k for k in p.get("pending_signature_for", []) if not KIDS or k in KIDS]}
        if (entry["id"], entry["text"]) not in known:
            log["sent"].append(entry)
    for n in d.get("notifications", []):
        t = n.get("text") or n.get("content") or n.get("title") or ""
        entry = {"id": n.get("id"), "kind": "notification", "sent_at": stamp, "text": " ".join(str(t).split()),
                 "url": n.get("url")}
        if (entry["id"], entry["text"]) not in known:
            log["sent"].append(entry)
    log["sent"] = log["sent"][-200:]


def print_monitor(log):
    """Deterministic output for the Hermes monitor: changes only when something new was delivered
    or when the error state changes, so the agent wakes only then."""
    if log.get("error"):
        print(f"ÉTAT : ÉCHEC, {log['error']}\n")
    print("Derniers éléments Beneylu transmis aux parents (le plus récent en dernier) :")
    for e in log["sent"][-LOG_SHOWN:]:
        print(json.dumps(e, ensure_ascii=False))


def main():
    mcp = None
    log = load_log()
    error = None
    try:
        mcp = Mcp()
        d = mcp.tool("whats_new")
        msg = render(d)
        failed = []
        if msg:
            if not CHATS:
                raise RuntimeError("BENEYLU_CHATS vide : aucun destinataire")
            token = bot_token()
            for who, chat in CHATS.items():
                try:
                    for part in chunks(msg):
                        send(token, chat, part)
                except Exception as e:  # never print the exception: the URL contains the bot token
                    failed.append(f"{who} ({type(e).__name__})")
        if failed:
            error = (f"envoi Telegram échoué pour {', '.join(failed)} ; rien n'a été confirmé, "
                     f"les nouveautés seront renvoyées au prochain passage")
        else:
            if msg:
                remember_sent(log, d)
            mcp.tool("ack", {"cursor": d["cursor"]})
    except Exception as e:
        error = f"vérification impossible ({type(e).__name__}: {str(e)[:200]}) ; rien n'a été confirmé"
    finally:
        if mcp:
            mcp.close()
    log["error"] = error
    save_log(log)
    print_monitor(log)


if __name__ == "__main__":
    main()
