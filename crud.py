from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
import models


def get_user(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()


def get_user_by_username(db: Session, username: str):
    return db.query(models.User).filter(models.User.username == username).first()


def get_all_users(db: Session, exclude_id: int):
    return db.query(models.User).filter(models.User.id != exclude_id).all()


def create_user(db: Session, username: str, hashed_password: str):
    user = models.User(username=username, hashed_password=hashed_password)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_chat(db: Session, chat_id: int):
    return db.query(models.Chat).filter(models.Chat.id == chat_id).first()


def get_user_chats(db: Session, user_id: int):
    memberships = db.query(models.ChatMember).filter(models.ChatMember.user_id == user_id).all()
    result = []
    for m in memberships:
        chat = m.chat
        if chat.is_group:
            title = chat.name
        else:
            other = next((mem.user for mem in chat.members if mem.user_id != user_id), None)
            title = other.username if other else "Чат"
        last_msg = chat.messages[-1] if chat.messages else None
        result.append({
            "id": chat.id,
            "title": title,
            "is_group": chat.is_group,
            "last_message": last_msg.text[:40] if last_msg else "",
            "last_at": last_msg.created_at.isoformat() if last_msg else ""
        })
    result.sort(key=lambda x: x["last_at"], reverse=True)
    return result


def get_or_create_private_chat(db: Session, user1_id: int, user2_id: int):
    user1_chats = {m.chat_id for m in db.query(models.ChatMember).filter(
        models.ChatMember.user_id == user1_id).all()}
    user2_chats = {m.chat_id for m in db.query(models.ChatMember).filter(
        models.ChatMember.user_id == user2_id).all()}
    common = user1_chats & user2_chats
    for chat_id in common:
        chat = get_chat(db, chat_id)
        if chat and not chat.is_group and len(chat.members) == 2:
            return chat
    
    chat = models.Chat(is_group=False)
    db.add(chat)
    db.flush()
    db.add(models.ChatMember(chat_id=chat.id, user_id=user1_id))
    db.add(models.ChatMember(chat_id=chat.id, user_id=user2_id))
    db.commit()
    db.refresh(chat)
    return chat


def create_group_chat(db: Session, name: str, creator_id: int, members_ids: list[int]):
    chat = models.Chat(name=name, is_group=True)
    db.add(chat)
    db.flush()
    all_members = list({creator_id} | set(members_ids))
    for uid in all_members:
        db.add(models.ChatMember(chat_id=chat.id, user_id=uid))
    db.commit()
    db.refresh(chat)
    return chat


def is_member(db: Session, chat_id: int, user_id: int) -> bool:
    return db.query(models.ChatMember).filter(
        and_(models.ChatMember.chat_id == chat_id, models.ChatMember.user_id == user_id)
    ).first() is not None


def get_messages(db: Session, chat_id: int, limit: int = 100):
    return db.query(models.Message).filter(
        models.Message.chat_id == chat_id
    ).order_by(models.Message.id.desc()).limit(limit).all()[::-1]


def save_message(db: Session, chat_id: int, sender_id: int, text: str):
    msg = models.Message(chat_id=chat_id, sender_id=sender_id, text=text)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def delete_message(db: Session, message_id: int, user_id: int):
    """Returns chat_id on success, None if message not found or user is not the sender."""
    msg = db.query(models.Message).filter(models.Message.id == message_id).first()
    if not msg or msg.sender_id != user_id:
        return None
    chat_id = msg.chat_id
    db.delete(msg)
    db.commit()
    return chat_id


def delete_chat(db: Session, chat_id: int, user_id: int) -> bool:
    if not is_member(db, chat_id, user_id):
        return False
    db.query(models.Message).filter(models.Message.chat_id == chat_id).delete()
    db.query(models.ChatMember).filter(models.ChatMember.chat_id == chat_id).delete()
    db.query(models.Chat).filter(models.Chat.id == chat_id).delete()
    db.commit()
    return True