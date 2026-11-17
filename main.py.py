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
    await m.answer("Mines. Virtual ballar bilan o'yin.", reply_markup=kb)

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
db.executescript("""create table if not exists users(id integer primary key, balance real);
create table if not exists games(uid integer primary key, bet real, mines text, opened text);""")

def auth(init: str) -> int:
    d = dict(parse_qsl(init, keep_blank_values=True))
    h = d.pop("hash", "")
    s = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
    key = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(key, s.encode(), hashlib.sha256).hexdigest(), h):
        raise HTTPException(401, "Auth xato")
    return json.loads(d["user"])["id"]

def mult(n, k):  # n mina, k ochilgan xavfsiz katak
    return round(0.97 * comb(25, k) / comb(25 - n, k), 2)

def bal(uid):
    r = db.execute("select balance from users where id=?", (uid,)).fetchone()
    if not r:
        db.execute("insert into users values(?,?)", (uid, START)); db.commit(); return START
    return r[0]

def setbal(uid, b):
    db.execute("update users set balance=? where id=?", (round(b, 2), uid)); db.commit()

def game(uid):
    r = db.execute("select * from games where uid=?", (uid,)).fetchone()
    return (r["bet"], json.loads(r["mines"]), json.loads(r["opened"])) if r else None

def view(uid, over=None):
    g, out = game(uid), {"balance": bal(uid), "active": False}
    if g:
        bet, m, o = g
        left = 25 - len(m) - len(o)
        out.update(active=True, bet=bet, opened=o, mult=mult(len(m), len(o)),
                   next=mult(len(m), len(o) + 1) if left > 0 else None)
    if over: out.update(over)
    return out

def finish(uid, won):
    bet, m, o = game(uid)
    pay = round(bet * mult(len(m), len(o)), 2) if won else 0
    if won: setbal(uid, bal(uid) + pay)
    db.execute("delete from games where uid=?", (uid,)); db.commit()
    return view(uid, {"mines": m, "opened": o, "won": won, "payout": pay})

class StartReq(BaseModel): bet: float; mines: int
class OpenReq(BaseModel): cell: int

@app.post("/api/state")
def state(x_init_data: str = Header("")):
    uid = auth(x_init_data)
    if bal(uid) < 1 and not game(uid): setbal(uid, START)
    return view(uid)

@app.post("/api/start")
def start_game(r: StartReq, x_init_data: str = Header("")):
    uid = auth(x_init_data)
    if game(uid): raise HTTPException(400, "O'yin davom etmoqda")
    if not 1 <= r.mines <= 24: raise HTTPException(400, "Mina soni 1-24")
    if r.bet < 1 or r.bet > bal(uid): raise HTTPException(400, "Tikish noto'g'ri yoki balans yetmaydi")
    setbal(uid, bal(uid) - r.bet)
    mines = random.sample(range(25), r.mines)
    db.execute("insert into games values(?,?,?,?)", (uid, r.bet, json.dumps(mines), "[]")); db.commit()
    return view(uid)

@app.post("/api/open")
def open_cell(r: OpenReq, x_init_data: str = Header("")):
    uid = auth(x_init_data)
    g = game(uid)
    if not g or not 0 <= r.cell < 25: raise HTTPException(400, "O'yin yo'q")
    bet, m, o = g
    if r.cell in o: raise HTTPException(400, "Katak ochilgan")
    if r.cell in m:
        return finish(uid, False)
    o.append(r.cell)
    db.execute("update games set opened=? where uid=?", (json.dumps(o), uid)); db.commit()
    if len(o) == 25 - len(m): return finish(uid, True)
    return view(uid)

@app.post("/api/cashout")
def cashout(x_init_data: str = Header("")):
    uid = auth(x_init_data)
    g = game(uid)
    if not g or not g[2]: raise HTTPException(400, "Avval kamida bitta katak oching")
    return finish(uid, True)

@app.get("/")
def index(): return FileResponse("index.html")
