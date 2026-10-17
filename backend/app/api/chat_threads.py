"""AI Chat conversation threads: durable history (SQLite, the app's existing database — no new service, nothing paid).

A thread belongs to ONE verified company (organisation number), set on its first answerable message. Its history lives here, in the database, and is read
back from here for every follow-up — the browser never supplies the history, so a thread can neither be tampered with nor mixed with another one.

* Creating a thread and sending a message are idempotent by client-supplied id: a retry (double click, network retry) never creates a second thread
  or a second copy of a message.
* A question that names another company is answered about that company in a NEW thread (the old thread stays as it was, plus a short notice).
* Deleting a thread deletes its messages from the database.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any

from ..core.util import clean_ws, now_iso, truncate
from ..errors import ApiError
from ..identity.employer import org_numbers_in
from ..logging_setup import get_logger
from ..storage.db import Database, dumps, loads
from . import chat
from .chat_intent import capitalised_names

log = get_logger("chat.threads")

ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
MAX_THREADS = 300
MAX_MESSAGES = 400
DEFAULT_TITLE = "New chat"
_FILLER = re.compile(r"^(?:please\s+|hey\s+|hi\s+|can you\s+|could you\s+|would you\s+|tell me\s+|give me\s+|show me\s+|i (?:want|need|would like) (?:to know|you to)\s+)+", re.I)
_LEAD_Q = re.compile(r"^(?:what(?:'s| is| are| was| were)|who(?:'s| is| are)|which|how (?:has|have|did|does|do|is|are|much|many)|when|where|why|is|are|does|did|do|has|have)\s+", re.I)


def make_title(question: str, legal_name: str | None = None) -> str:
    """A short, meaningful title from the first user message (not the raw sentence): filler words dropped, first letter capitalised, bounded length."""
    t = clean_ws(question).strip(" ?!.")
    t = _FILLER.sub("", t)
    t = t[:1].upper() + t[1:] if t else ""
    if len(t) < 3:
        return f"About {legal_name}" if legal_name else DEFAULT_TITLE
    if len(t) > 56:
        t = t[:55].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return t


def valid_id(value: Any) -> str:
    if not isinstance(value, str) or not ID_RE.match(value):
        raise ApiError("invalid", "A conversation id has 8–64 letters, digits, dashes or underscores.", status=400)
    return value


class ChatThreads:
    def __init__(self, services: Any):
        self.s = services
        self.db: Database = services.db
        self._locks: dict[str, asyncio.Lock] = {}

    # ---------------------------------------------------------------- reads --
    def _summary(self, row: Any) -> dict[str, Any]:
        last = self.db.one("SELECT content, role FROM chat_messages WHERE thread_id = ? AND kind IS NOT 'context_notice' ORDER BY seq DESC LIMIT 1", (row["id"],))
        n = self.db.one("SELECT COUNT(*) AS n FROM chat_messages WHERE thread_id = ?", (row["id"],))
        return {"id": row["id"], "title": row["title"], "titleEdited": bool(row["title_edited"]), "createdAt": row["created_at"], "updatedAt": row["updated_at"],
                "company": {"orgNumber": row["org_number"], "legalName": row["legal_name"]} if row["org_number"] else None,
                "messageCount": int(n["n"]) if n else 0, "preview": truncate(clean_ws(last["content"]), 90) if last else ""}

    def list(self) -> list[dict[str, Any]]:
        rows = self.db.all("SELECT * FROM chat_threads ORDER BY updated_at DESC LIMIT ?", (MAX_THREADS,))
        return [self._summary(r) for r in rows]

    def _row(self, thread_id: str) -> Any:
        row = self.db.one("SELECT * FROM chat_threads WHERE id = ?", (valid_id(thread_id),))
        if row is None:
            raise ApiError("not_found", "That conversation does not exist (it may have been deleted).", status=404)
        return row

    @staticmethod
    def _message(row: Any) -> dict[str, Any]:
        payload = loads(row["payload_json"], {}) or {}
        return {"id": row["id"], "role": row["role"], "kind": row["kind"], "content": row["content"], "createdAt": row["created_at"], **({"payload": payload} if payload else {})}

    def get(self, thread_id: str) -> dict[str, Any]:
        row = self._row(thread_id)
        msgs = self.db.all("SELECT * FROM chat_messages WHERE thread_id = ? ORDER BY seq", (row["id"],))
        return {**self._summary(row), "messages": [self._message(m) for m in msgs]}

    def history_for(self, thread_id: str, *, max_messages: int, max_chars: int) -> list[dict[str, str]]:
        """Earlier turns of THIS thread only. A question that moved to another company's thread, and notices, are not part of the conversation's context."""
        rows = self.db.all("SELECT * FROM chat_messages WHERE thread_id = ? ORDER BY seq", (thread_id,))
        out: list[dict[str, Any]] = []
        for r in rows:
            payload = loads(r["payload_json"], {}) or {}
            if r["kind"] == "context_notice" or payload.get("movedTo"):
                continue
            if r["role"] == "assistant" and r["kind"] in ("clarification", "error"):
                continue
            out.append({"role": r["role"], "content": r["content"]})
        return chat.clean_history(out, max_messages=max_messages, max_chars=max_chars)

    # --------------------------------------------------------------- writes --
    def create(self, thread_id: str | None = None, *, org: str | None = None, legal_name: str | None = None, title: str | None = None) -> dict[str, Any]:
        tid = valid_id(thread_id) if thread_id else uuid.uuid4().hex
        existing = self.db.one("SELECT id FROM chat_threads WHERE id = ?", (tid,))
        if existing:  # a retry of the same creation returns the same thread
            return self._summary(self._row(tid))
        count = self.db.one("SELECT COUNT(*) AS n FROM chat_threads")
        if count and int(count["n"]) >= MAX_THREADS:
            oldest = self.db.one("SELECT id FROM chat_threads ORDER BY updated_at ASC LIMIT 1")
            if oldest:
                self.delete(oldest["id"])
        now = now_iso()
        self.db.execute("INSERT OR IGNORE INTO chat_threads(id, title, title_edited, org_number, legal_name, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                        (tid, clean_ws(title or DEFAULT_TITLE)[:80] or DEFAULT_TITLE, 1 if title else 0, org, legal_name, now, now))
        return self._summary(self._row(tid))

    def rename(self, thread_id: str, title: str) -> dict[str, Any]:
        row = self._row(thread_id)
        t = clean_ws(str(title or ""))[:80]
        if not t:
            raise ApiError("invalid", "A conversation needs a title.", status=400)
        self.db.execute("UPDATE chat_threads SET title = ?, title_edited = 1, updated_at = updated_at WHERE id = ?", (t, row["id"]))
        return self._summary(self._row(thread_id))

    def delete(self, thread_id: str) -> bool:
        row = self.db.one("SELECT id FROM chat_threads WHERE id = ?", (valid_id(thread_id),))
        if row is None:
            return False
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM chat_messages WHERE thread_id = ?", (thread_id,))
            conn.execute("DELETE FROM chat_threads WHERE id = ?", (thread_id,))
        self._locks.pop(thread_id, None)
        return True

    def _set_company(self, thread_id: str, org: str, legal: str | None) -> None:
        self.db.execute("UPDATE chat_threads SET org_number = ?, legal_name = ? WHERE id = ?", (org, legal, thread_id))

    def _append(self, thread_id: str, message_id: str, role: str, content: str, *, kind: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """INSERT OR IGNORE by message id: the same message is never stored twice."""
        row = self.db.one("SELECT * FROM chat_messages WHERE id = ?", (message_id,))
        if row is not None:
            return self._message(row)
        count = self.db.one("SELECT COUNT(*) AS n, COALESCE(MAX(seq), 0) AS m FROM chat_messages WHERE thread_id = ?", (thread_id,))
        if count and int(count["n"]) >= MAX_MESSAGES:
            raise ApiError("invalid", "This conversation is very long. Start a new chat to continue.", status=400)
        now = now_iso()
        self.db.execute("INSERT OR IGNORE INTO chat_messages(id, thread_id, seq, role, kind, content, created_at, payload_json) VALUES (?,?,?,?,?,?,?,?)",
                        (message_id, thread_id, int(count["m"]) + 1 if count else 1, role, kind, content[:12000], now, dumps(payload) if payload else None))
        self.db.execute("UPDATE chat_threads SET updated_at = ? WHERE id = ?", (now, thread_id))
        return self._message(self.db.one("SELECT * FROM chat_messages WHERE id = ?", (message_id,)))

    # ------------------------------------------------------------------ ask --
    async def _pick_company(self, question: str, org_hint: str | None) -> tuple[str | None, list[dict[str, Any]], str | None]:
        """Identity for a thread that has no company yet: an explicit organisation number, a number in the text, or exactly one exact register match for a name."""
        s = self.s
        if org_hint:
            return s.clean_org(org_hint), [], None
        nums = sorted(org_numbers_in([question]))  # a set: it has no order and cannot be indexed
        if len(nums) > 1:
            return None, [], "the question contains more than one organisation number"  # never guess which one was meant
        if nums:
            try:
                return s.clean_org(nums[0]), [], None
            except ApiError as exc:
                return None, [], exc.message
        names = [m.group(0) for m in chat.COMPANY_NAME.finditer(question)] + capitalised_names(question, limit=3)
        seen: set[str] = set()
        for name in names:
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            org, cands, problem = await chat._resolve_other(s, name)  # noqa: SLF001
            if org:
                return org, [], None
            if cands and (chat.COMPANY_NAME.search(name) or len(names) == 1):
                return None, cands, None
            if problem:
                return None, [], problem
        return None, [], None

    async def ask(self, thread_id: str, body: dict[str, Any], on_progress: Any = None) -> dict[str, Any]:
        s = self.s
        self._row(thread_id)
        retry_of = valid_id(body["retryOf"]) if body.get("retryOf") else None
        question = clean_ws(str(body.get("question") or ""))
        if not question and not retry_of:
            raise ApiError("invalid", "Ask a question.", status=400)
        mid = retry_of or (valid_id(body["messageId"]) if body.get("messageId") else uuid.uuid4().hex)
        lock = self._locks.setdefault(thread_id, asyncio.Lock())
        async with lock:
            if retry_of:  # the user picked the company for a question that was waiting for one: answer THAT question, do not duplicate it
                prior = self.db.one("SELECT * FROM chat_messages WHERE id = ? AND thread_id = ? AND role = 'user'", (retry_of, thread_id))
                if prior is None:
                    raise ApiError("not_found", "That message is not part of this conversation.", status=404)
                self.db.execute("DELETE FROM chat_messages WHERE thread_id = ? AND seq > ? AND kind = 'clarification'", (thread_id, prior["seq"]))
                question = prior["content"]
                user_msg = self._message(prior)
            else:
                # a retry of a message that was already answered returns the stored answer (no second research, no duplicate rows)
                prior = self.db.one("SELECT seq FROM chat_messages WHERE id = ? AND thread_id = ?", (mid, thread_id))
                if prior is not None:
                    nxt = self.db.one("SELECT * FROM chat_messages WHERE thread_id = ? AND seq > ? ORDER BY seq LIMIT 1", (thread_id, prior["seq"]))
                    if nxt is not None and nxt["role"] == "assistant" and nxt["kind"] == "error":
                        self.db.execute("DELETE FROM chat_messages WHERE id = ?", (nxt["id"],))  # a failed attempt is retried, not replayed
                    elif nxt is not None and nxt["role"] == "assistant":
                        return self._reply(thread_id, self._message(self.db.one("SELECT * FROM chat_messages WHERE id = ?", (mid,))), self._message(nxt))
            row = self._row(thread_id)
            history = self.history_for(thread_id, max_messages=s.settings.chat_max_history_messages, max_chars=1500)
            if not retry_of:
                first = self.db.one("SELECT COUNT(*) AS n FROM chat_messages WHERE thread_id = ? AND role = 'user'", (thread_id,))
                user_msg = self._append(thread_id, mid, "user", question)
                if first and int(first["n"]) == 0 and not row["title_edited"]:
                    self.db.execute("UPDATE chat_threads SET title = ? WHERE id = ?", (make_title(question, row["legal_name"]), thread_id))
            else:  # the unanswered question is the one being asked: it is not its own history
                history = [m for m in history if not (m["role"] == "user" and m["content"] == chat.clean_history([{"role": "user", "content": question}], max_messages=1, max_chars=1500)[0]["content"])]

            org = row["org_number"]
            hint = str(body["orgNumber"]) if body.get("orgNumber") else None
            if org is None:
                picked, candidates, problem = await self._pick_company(question, hint)
                if picked is None:
                    text = ("Which company do you mean? Name it exactly, give its 9-digit organisation number, or pick it below. Answers are always about one verified company."
                            if not candidates else "More than one registered company matches that name. Pick the exact company — COGNIS never guesses.")
                    if problem:
                        text = f"I could not look up that company ({problem}). " + text
                    reply = self._append(thread_id, uuid.uuid4().hex, "assistant", text, kind="clarification",
                                         payload={"kind": "clarification", "answer": text, "candidates": candidates[:6], "citations": [], "sources": [], "coverage": [],
                                                  "search": {"state": "not_used", "note": "No search was made."}, "waitingFor": user_msg["id"]})
                    return self._reply(thread_id, user_msg, reply)
                rec = await s.ensure_record(picked)
                legal = (s.profile_for(rec)["company"] or {}).get("legalName")
                self._set_company(thread_id, picked, legal)
                org = picked
            elif hint and s.clean_org(hint) != org:  # an explicit company change on an existing thread is a new thread, never a rewrite of this one
                return await self._switch_thread(thread_id, user_msg, question, s.clean_org(hint), body, on_progress)
            turn = chat.ChatTurn(org=org, question=question, history=history, fresh=bool(body.get("fresh")))
            try:
                payload = await chat.answer_question(s, turn, on_progress)
            except ApiError as exc:
                self._append(thread_id, uuid.uuid4().hex, "assistant", exc.message, kind="error", payload={"kind": "error", "answer": exc.message, "code": exc.code, "citations": [], "sources": []})
                raise
            if payload.get("contextSwitch"):
                return await self._finish_switch(thread_id, user_msg, question, payload, body)
            payload["followUps"] = chat.follow_ups(payload)
            reply = self._append(thread_id, uuid.uuid4().hex, "assistant", payload["answer"], kind=payload.get("kind"), payload=payload)
            return self._reply(thread_id, user_msg, reply)

    async def _switch_thread(self, old_id: str, user_msg: dict[str, Any], question: str, org: str, body: dict[str, Any], on_progress: Any) -> dict[str, Any]:
        s = self.s
        rec = await s.ensure_record(org)
        legal = (s.profile_for(rec)["company"] or {}).get("legalName")
        new = self.create(None, org=org, legal_name=legal, title=None)
        turn = chat.ChatTurn(org=org, question=question, history=[], fresh=bool(body.get("fresh")), allow_switch=False)
        payload = await chat.answer_question(s, turn, on_progress)
        old = self._row(old_id)
        payload["contextSwitch"] = {"from": {"orgNumber": old["org_number"], "legalName": old["legal_name"]}, "to": {"orgNumber": org, "legalName": legal},
                                    "message": f"Active company changed from {old['legal_name']} to {legal} (organisation number {org}). Everything below was retrieved for {legal}; nothing from {old['legal_name']} was used."}
        return await self._finish_switch(old_id, user_msg, question, payload, body, new_thread=new["id"])

    async def _finish_switch(self, old_id: str, user_msg: dict[str, Any], question: str, payload: dict[str, Any], body: dict[str, Any], new_thread: str | None = None) -> dict[str, Any]:
        """The answer concerns another company: it is stored in a NEW thread for that company; the old thread keeps the question, plus a notice, and stays clean."""
        to = payload["contextSwitch"]["to"]
        if new_thread is None:
            new = self.create(None, org=to["orgNumber"], legal_name=to["legalName"])
            new_thread = new["id"]
        new_user = self._append(new_thread, uuid.uuid4().hex, "user", user_msg["content"])
        self.db.execute("UPDATE chat_threads SET title = ? WHERE id = ? AND title_edited = 0", (make_title(user_msg["content"], to["legalName"]), new_thread))
        payload["followUps"] = chat.follow_ups(payload)
        reply = self._append(new_thread, uuid.uuid4().hex, "assistant", payload["answer"], kind=payload.get("kind"), payload=payload)
        # mark the question in the old thread as moved (so it is not used as context there) and say where it went
        self.db.execute("UPDATE chat_messages SET payload_json = ? WHERE id = ?", (dumps({"movedTo": new_thread}), user_msg["id"]))
        notice = f"Continued in a new chat about {to['legalName']} (organisation number {to['orgNumber']}). This conversation stays about its own company."
        self._append(old_id, uuid.uuid4().hex, "assistant", notice, kind="context_notice", payload={"kind": "context_notice", "answer": notice, "movedTo": new_thread, "citations": [], "sources": []})
        out = self._reply(new_thread, new_user, reply)
        out["switchedFromThreadId"] = old_id
        return out

    def _reply(self, thread_id: str, user_msg: dict[str, Any], reply: dict[str, Any]) -> dict[str, Any]:
        return {"threadId": thread_id, "thread": self._summary(self._row(thread_id)), "userMessage": user_msg, "assistantMessage": reply}
