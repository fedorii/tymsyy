from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import json

from database import get_db, engine
import models
import auth
import crud

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Messenger")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ─── WebSocket connection manager ───────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        # chat_id -> list of (websocket, user_id)
        self.active: dict[int, list[tuple[WebSocket, int]]] = {}

    async def connect(self, websocket: WebSocket, chat_id: int, user_id: int):
        await websocket.accept()
        self.active.setdefault(chat_id, []).append((websocket, user_id))

    def disconnect(self, websocket: WebSocket, chat_id: int):
        if chat_id in self.active:
            self.active[chat_id] = [(ws, uid) for ws, uid in self.active[chat_id] if ws != websocket]

    async def broadcast(self, chat_id: int, message: dict):
        for ws, _ in self.active.get(chat_id, []):
            try:
                await ws.send_text(json.dumps(message, ensure_ascii=False))
            except Exception:
                pass


manager = ConnectionManager()


# ─── Auth pages ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    user = await auth.get_current_user_from_cookie(request)
    if user:
        return RedirectResponse("/chats", status_code=302)
    return RedirectResponse("/login", status_code=302)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = crud.get_user_by_username(db, username)
    if not user or not auth.verify_password(password, user.hashed_password):
        return templates.TemplateResponse(request, "login.html", {"error": "Неверный логин или пароль"})
    token = auth.create_token(user.id)
    response = RedirectResponse("/chats", status_code=302)
    response.set_cookie("token", token, httponly=True, max_age=86400 * 7)
    return response


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html")


@app.post("/register")
async def register(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    if crud.get_user_by_username(db, username):
        return templates.TemplateResponse(request, "register.html", {"error": "Имя занято"})
    if len(username) < 2 or len(password) < 4:
        return templates.TemplateResponse(request, "register.html", {"error": "Логин должен иметь 2 или более символов, а пароль — больше или равно 4 символам"})
    crud.create_user(db, username, auth.hash_password(password))
    return RedirectResponse("/login", status_code=302)


@app.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("token")
    return response


# ─── Main chat UI ────────────────────────────────────────────────────────────

@app.get("/chats", response_class=HTMLResponse)
async def chats_page(request: Request, db: Session = Depends(get_db)):
    user = await auth.get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    chats = crud.get_user_chats(db, user.id)
    users = crud.get_all_users(db, exclude_id=user.id)
    return templates.TemplateResponse(request, "chats.html", {
        "current_user": user,
        "chats": chats,
        "users": users
    })


# ─── API ─────────────────────────────────────────────────────────────────────

@app.post("/api/chats/private/{user_id}")
async def create_private_chat(user_id: int, request: Request, db: Session = Depends(get_db)):
    user = await auth.get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401)
    chat = crud.get_or_create_private_chat(db, user.id, user_id)
    return {"chat_id": chat.id}


@app.post("/api/chats/group")
async def create_group_chat(request: Request, db: Session = Depends(get_db)):
    user = await auth.get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401)
    data = await request.json()
    name = data.get("name", "").strip()
    member_ids = data.get("members", [])
    if not name:
        raise HTTPException(status_code=400, detail="Укажите название")
    chat = crud.create_group_chat(db, name, user.id, member_ids)
    return {"chat_id": chat.id}


@app.get("/api/chats/{chat_id}/messages")
async def get_messages(chat_id: int, request: Request, db: Session = Depends(get_db)):
    user = await auth.get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401)
    if not crud.is_member(db, chat_id, user.id):
        raise HTTPException(status_code=403)
    msgs = crud.get_messages(db, chat_id)
    return [{"id": m.id, "text": m.text, "sender_id": m.sender_id,
             "sender": m.sender.username, "created_at": m.created_at.isoformat()} for m in msgs]


@app.get("/api/chats/{chat_id}/info")
async def get_chat_info(chat_id: int, request: Request, db: Session = Depends(get_db)):
    user = await auth.get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401)
    chat = crud.get_chat(db, chat_id)
    if not chat or not crud.is_member(db, chat_id, user.id):
        raise HTTPException(status_code=403)
    members = [{"id": m.user.id, "username": m.user.username} for m in chat.members]
    title = chat.name if chat.is_group else next(
        (m.user.username for m in chat.members if m.user_id != user.id), "Чат"
    )
    return {"id": chat.id, "title": title, "is_group": chat.is_group, "members": members}


# ─── WebSocket ───────────────────────────────────────────────────────────────

@app.websocket("/ws/{chat_id}/{token}")
async def websocket_endpoint(websocket: WebSocket, chat_id: int, token: str, db: Session = Depends(get_db)):
    user_id = auth.decode_token(token)
    if not user_id or not crud.is_member(db, chat_id, user_id):
        await websocket.close(code=4001)
        return

    user = crud.get_user(db, user_id)
    await manager.connect(websocket, chat_id, user_id)
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            text = payload.get("text", "").strip()
            if not text:
                continue
            msg = crud.save_message(db, chat_id, user_id, text)
            await manager.broadcast(chat_id, {
                "id": msg.id,
                "text": msg.text,
                "sender_id": user_id,
                "sender": user.username,
                "created_at": msg.created_at.isoformat(),
            })
    except WebSocketDisconnect:
        manager.disconnect(websocket, chat_id)
