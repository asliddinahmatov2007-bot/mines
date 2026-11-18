import os, hmac, hashlib, json, random, sqlite3, asyncio
from math import comb
from contextlib import asynccontextmanager
from urllib.parse import parse_qsl
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

TOKEN = os.environ["BOT_TOKEN"]
WEBAPP_URL = os.environ["WEBAPP_URL"]
START = 1000  # boshlang'ich virtual ball

bot, dp = Bot(TOKEN), Dispatcher()

@dp.message(CommandStart())
async def start(m: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="O'ynash", web_app=WebAppInfo(url=WEBAPP_URL))]])
    await m.answer("Ochko 21. Virtual ballar bilan o'yin.", reply_markup=kb)

@dp.message(Command("add"))
async def add(m: Message):
    try:
        n = float(m.text.split()[1])
    except Exception:
        return await m.answer("Misol: /add 5000")
    setbal(m.from_user.id, bal(m.from_user.id) + n)
    await m.answer(f"Balans: {bal(m.from_user.id)} ball")

@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(dp.start_polling(bot))
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)
db = sqlite3.connect("mines.db", check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript("create table if not exists users(id integer primary key, balance real);")

def auth(init: str) -> int:
    d = dict(parse_qsl(init, keep_blank_values=True))
    h = d.pop("hash", "")
    s = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
    key = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(key, s.encode(), hashlib.sha256).hexdigest(), h):
        raise HTTPException(401, "Auth xato")
    return json.loads(d["user"])["id"]

def bal(uid):
    r = db.execute("select balance from users where id=?", (uid,)).fetchone()
    if not r:
        db.execute("insert into users values(?,?)", (uid, START)); db.commit(); return START
    return r[0]

def setbal(uid, b):
    db.execute("update users set balance=? where id=?", (round(b, 2), uid)); db.commit()

# ---------------- BLACKJACK ----------------
db.executescript("create table if not exists bj(uid integer primary key, bet real, deck text, p text, d text);")
RANKS = ["2","3","4","5","6","7","8","9","10","J","Q","K","A"]
SUITS = ["♠","♥","♦","♣"]

def hv(h):
    t = a = 0
    for r, _ in h:
        if r == "A": t += 11; a += 1
        elif r in ("J","Q","K","10"): t += 10
        else: t += int(r)
    while t > 21 and a: t -= 10; a -= 1
    return t

def bj_get(uid):
    r = db.execute("select * from bj where uid=?", (uid,)).fetchone()
    return (r["bet"], json.loads(r["deck"]), json.loads(r["p"]), json.loads(r["d"])) if r else None

def bj_save(uid, bet, deck, p, d):
    db.execute("insert or replace into bj values(?,?,?,?,?)",
               (uid, bet, json.dumps(deck), json.dumps(p), json.dumps(d))); db.commit()

def bj_view(uid, over=None):
    g, out = bj_get(uid), {"balance": bal(uid), "active": False}
    if g:
        bet, deck, p, d = g
        out.update(active=True, bet=bet, player=p, dealer=d[:1], pv=hv(p))
    if over: out.update(over)
    return out

def bj_settle(uid):
    bet, deck, p, d = bj_get(uid)
    pv = hv(p)
    if pv <= 21:
        while hv(d) < 17: d.append(deck.pop())
    dv = hv(d); nat = len(p) == 2 and pv == 21; dnat = len(d) == 2 and dv == 21
    if pv > 21: res, pay = "lose", 0
    elif nat and not dnat: res, pay = "blackjack", bet * 2.5
    elif dnat and not nat: res, pay = "lose", 0
    elif dv > 21 or pv > dv: res, pay = "win", bet * 2
    elif pv == dv: res, pay = "push", bet
    else: res, pay = "lose", 0
    pay = round(pay, 2)
    if pay: setbal(uid, bal(uid) + pay)
    db.execute("delete from bj where uid=?", (uid,)); db.commit()
    return bj_view(uid, {"dealer": d, "player": p, "pv": pv, "dv": dv,
                         "result": res, "payout": pay, "bet": bet})

class BjStart(BaseModel): bet: float

@app.post("/api/bj/state")
def bj_state(x_init_data: str = Header("")):
    uid = auth(x_init_data)
    if bal(uid) < 1 and not bj_get(uid): setbal(uid, START)
    return bj_view(uid)

@app.post("/api/bj/start")
def bj_start(r: BjStart, x_init_data: str = Header("")):
    uid = auth(x_init_data)
    if bj_get(uid): raise HTTPException(400, "O'yin davom etmoqda")
    if r.bet < 1 or r.bet > bal(uid): raise HTTPException(400, "Tikish noto'g'ri yoki balans yetmaydi")
    setbal(uid, bal(uid) - r.bet)
    deck = [[x, y] for x in RANKS for y in SUITS]
    random.shuffle(deck)
    p, d = [deck.pop(), deck.pop()], [deck.pop(), deck.pop()]
    bj_save(uid, r.bet, deck, p, d)
    return bj_settle(uid) if hv(p) == 21 else bj_view(uid)

@app.post("/api/bj/hit")
def bj_hit(x_init_data: str = Header("")):
    uid = auth(x_init_data)
    g = bj_get(uid)
    if not g: raise HTTPException(400, "O'yin yo'q")
    bet, deck, p, d = g
    p.append(deck.pop()); bj_save(uid, bet, deck, p, d)
    return bj_settle(uid) if hv(p) >= 21 else bj_view(uid)

@app.post("/api/bj/stand")
def bj_stand(x_init_data: str = Header("")):
    uid = auth(x_init_data)
    if not bj_get(uid): raise HTTPException(400, "O'yin yo'q")
    return bj_settle(uid)

@app.get("/")
def index(): return FileResponse("index.html")
