from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from pydantic import BaseModel
import asyncio

from bot.bot import bot as aiogram_bot
from bot.keyboards.inline import answer_keyboard
from bot.keyboards.reply import base_keyboard
from bot.ollama import OllamaChat, OllamaChatMessage, generate_chat_completion
from bot.ollama.api import get_installed_models, model_is_installed
from bot.ollama.dto import OllamaErrorChunk
from bot.settings import (
    ALLOWED_CHAT_IDS,
    COMPACTION_EVERY_N,
    MAX_CONTEXT_MESSAGES,
    OLLAMA_MODEL,
    OLLAMA_MODEL_TEMPERATURE,
    START_USER_MESSAGE,
    SUMMARY_PROMPT,
    SYSTEM_MESSAGE,
)

router = Router()

db = None  # injected in __init__

def _is_allowed(user_id: int) -> bool:
    if not ALLOWED_CHAT_IDS:
        return True
    allowed = {int(x.strip()) for x in ALLOWED_CHAT_IDS.split(",") if x.strip().isdigit()}
    return user_id in allowed

def _escape_markdown(text: str) -> str:
    chars = r"_[]()~`>#+-=|{}.!"
    for ch in chars:
        text = text.replace(ch, "\\" + ch)
    return text

def wrap(s: str, w: int) -> list[str]:
    return [s[i : i + w] for i in range(0, len(s), w)]

class UserChat(BaseModel):
    ollama_chat: OllamaChat
    selected_model: str = OLLAMA_MODEL
    linked_last_messages: int | None = None
    previous_prompt: str | None = None
    session_id: int | None = None

chats: dict[int, UserChat] = {}
_typing_last: dict[int, float] = {}

async def _safe_typing(user_id: int):
    import time
    now = time.time()
    if user_id in _typing_last and now - _typing_last[user_id] < 3:
        return
    _typing_last[user_id] = now
    try:
        await _safe_typing(user_id)
    except Exception as e:
        if "Flood control" in str(e) or "Too Many Requests" in str(e):
            pass
        else:
            print(f"[TYPING] Error: {e}")

async def generate(message: Message, user_id: int, text: str):
    if text == "New chat":
        await message.answer("Новый чат создан!", reply_markup=base_keyboard)
        return _delete_chat(user_id)

    if text == "/models":
        models = await get_installed_models()
        model_list = "\n".join([f"- {m.name}" for m in models]) or "Нет моделей"
        await message.answer(f"Доступные модели:\n{model_list}")
        return

    if text == "/help":
        await message.answer(
            "🤖 Команды бота:\n\n"
            "📋 AI:\n"
            "/models — список моделей\n"
            "/model <name> — сменить модель\n"
            "/clear — очистить историю\n\n"
            "📝 Заметки и память:\n"
            "/note <текст> — сохранить заметку\n"
            "/memory_add [<category>] <текст> — сохранить факт\n"
            "   категории: fact, preference, task, decision\n"
            "/memory — показать все факты\n"
            "/memory_remove <id> — удалить факт\n\n"
            "⏰ Напоминания:\n"
            "/remind <время> <текст> — добавить\n"
            "/reminders — список\n"
            "/remind_cancel <id> — отменить\n\n"
            "🔍 Мониторинг:\n"
            "/monitor_add <name> <url> [<interval>] — добавить\n"
            "/monitors — список\n"
            "/monitor_remove <id> — удалить\n\n"
            "📊 Другое:\n"
            "/report — ежедневный отчёт\n"
            "/help — эта справка\n\n"
            "Напишите любое сообщение для разговора с AI."
        )
        return

    if text.startswith("/model"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Использование: /model <model_name>")
            return
        model_to_set = parts[1].strip()
        if not await model_is_installed(model_to_set):
            await message.answer(f"Модель {model_to_set} не найдена!")
            return
        _create_chat(user_id)
        chats[user_id].selected_model = model_to_set
        await message.answer(f"Модель изменена на {model_to_set}")
        return

    if text.startswith("/clear"):
        if user_id in chats and chats[user_id].session_id and db:
            db.close_session(chats[user_id].session_id, "User cleared chat")
        _delete_chat(user_id)
        await message.answer("История очищена.")
        return

    is_command = text.startswith("/")
    created = _create_chat(user_id)
    if created and not is_command:
        await message.answer(f"Чат создан. Модель: {chats[user_id].selected_model}")

    chat = chats[user_id]

    try:
        if chat.linked_last_messages:
            await aiogram_bot.edit_message_reply_markup(
                chat_id=user_id,
                message_id=chat.linked_last_messages,
                reply_markup=None,
            )
    except Exception:
        pass

    chat.linked_last_messages = None

    await aiogram_bot.send_chat_action(chat_id=user_id, action="typing")

    prompt = text
    chat.previous_prompt = prompt
    chat.ollama_chat.messages.append(OllamaChatMessage(role="user", content=prompt))
    _trim_context(chat)

    print(f"[{user_id}]: {prompt}")

    if db and chat.session_id:
        db.save_message(user_id, chat.session_id, "user", prompt, chat.selected_model)

    msg = await message.answer("Думаю...")

    assistant_content = ""
    try:
        async for is_done, chunk in generate_chat_completion(
            chat.ollama_chat.messages,
            chat.selected_model,
            temperature=OLLAMA_MODEL_TEMPERATURE,
        ):
            if is_done:
                wrapped_response = wrap(assistant_content, 4096)
                if not wrapped_response:
                    await msg.edit_text("(пустой ответ)", reply_markup=None)
                else:
                    initial_content = wrapped_response.pop(0)
                    safe_text = _escape_markdown(initial_content)
                    try:
                        await msg.edit_text(
                            safe_text,
                            parse_mode="MarkdownV2",
                            reply_markup=None if wrapped_response else answer_keyboard,
                        )
                    except Exception as e:
                        print(f"Markdown error: {e}")
                        await msg.edit_text(
                            initial_content,
                            parse_mode=None,
                            reply_markup=None if wrapped_response else answer_keyboard,
                        )

                    for extra_text in wrapped_response:
                        extra_msg = await msg.answer(extra_text)
                        if wrapped_response.index(extra_text) == len(wrapped_response) - 1:
                            await extra_msg.edit_reply_markup(reply_markup=answer_keyboard)
                print(f"[{user_id}]: Finished!")
            else:
                if isinstance(chunk, OllamaErrorChunk):
                    await msg.edit_text(f"Ошибка Ollama: {chunk.error}")
                    break
                assistant_content += chunk.message.content
                if len(assistant_content) % 100 == 0:
                    await _safe_typing(user_id)
    except Exception as e:
        print(f"[ERROR] Generation failed: {e}")
        await msg.edit_text(f"Произошла ошибка при генерации ответа. Попробуйте ещё раз.\n({str(e)[:200]})")
        return

    chat.linked_last_messages = msg.message_id
    chat.ollama_chat.messages.append(
        OllamaChatMessage(role="assistant", content=assistant_content)
    )
    _trim_context(chat)

    if db and chat.session_id:
        db.save_message(user_id, chat.session_id, "assistant", assistant_content, chat.selected_model)

    # Async compaction after response is sent
    if db and chat.session_id:
        asyncio.create_task(_maybe_compact(user_id, chat))

def _trim_context(chat: UserChat) -> None:
    system_messages = [m for m in chat.ollama_chat.messages if m.role == "system"]
    other_messages = [m for m in chat.ollama_chat.messages if m.role != "system"]
    if len(other_messages) > MAX_CONTEXT_MESSAGES:
        other_messages = other_messages[-MAX_CONTEXT_MESSAGES:]
    chat.ollama_chat.messages = system_messages + other_messages


async def _maybe_compact(user_id: int, chat: UserChat):
    if not db or not chat.session_id:
        return

    # Count only user+assistant messages (excluding system and summaries)
    non_system = [m for m in chat.ollama_chat.messages if m.role in ("user", "assistant")]
    total_count = len(non_system)

    if total_count < COMPACTION_EVERY_N:
        return

    # Check if we already compacted at this count or higher
    latest_summary = db.get_latest_summary(chat.session_id)
    if latest_summary and latest_summary.get("message_count", 0) >= total_count:
        return

    print(f"[COMPACT] Triggered for user {user_id} at {total_count} messages")

    # Build conversation text for summarization
    conversation_lines = []
    for m in non_system:
        role_label = "Пользователь" if m.role == "user" else "Ассистент"
        conversation_lines.append(f"{role_label}: {m.content}")
    conversation_text = "\n\n".join(conversation_lines)

    summary_prompt = (
        f"{SUMMARY_PROMPT}\n\n"
        f"ДИАЛОГ:\n{conversation_text}\n\n"
        f"ВЫЖИМКА:"
    )

    try:
        summary_messages = [
            OllamaChatMessage(role="system", content=SYSTEM_MESSAGE),
            OllamaChatMessage(role="user", content=summary_prompt),
        ]
        summary_content = ""
        async for is_done, chunk in generate_chat_completion(
            summary_messages,
            chat.selected_model,
            temperature=0.3,
        ):
            if is_done:
                break
            else:
                if isinstance(chunk, OllamaErrorChunk):
                    print(f"[COMPACT] Summary error: {chunk.error}")
                    return
                summary_content += chunk.message.content

        if not summary_content.strip():
            print("[COMPACT] Empty summary, skipping")
            return

        db.add_summary(chat.session_id, total_count, summary_content)
        print(f"[COMPACT] Saved summary for session {chat.session_id} at {total_count} messages")

        # --- Auto memory extraction (OpenClaude-style) ---
        memory_prompt = (
            "Проанализируй диалог и извлеки ВАЖНЫЕ факты о пользователе.\n"
            "Для каждого факта укажи категорию: fact (факт), preference (предпочтение), task (задача), decision (решение).\n"
            "Ответь ТОЛЬКО в формате (один факт на строку):\n"
            "[category] content\n"
            "Если нет важных фактов — напиши \"НЕТ\".\n\n"
            f"ДИАЛОГ:\n{conversation_text}\n\n"
            "ФАКТЫ:"
        )
        try:
            memory_messages = [
                OllamaChatMessage(role="system", content=SYSTEM_MESSAGE),
                OllamaChatMessage(role="user", content=memory_prompt),
            ]
            memory_raw = ""
            async for is_done, chunk in generate_chat_completion(
                memory_messages,
                chat.selected_model,
                temperature=0.2,
            ):
                if is_done:
                    break
                else:
                    if isinstance(chunk, OllamaErrorChunk):
                        break
                    memory_raw += chunk.message.content

            if memory_raw.strip() and memory_raw.strip().upper() != "НЕТ":
                for line in memory_raw.strip().split("\n"):
                    line = line.strip()
                    if not line or line.upper() == "НЕТ":
                        continue
                    # Parse [category] content
                    if line.startswith("[") and "]" in line:
                        close_idx = line.index("]")
                        category = line[1:close_idx].lower().strip()
                        content = line[close_idx+1:].strip()
                        if category in ("fact", "preference", "task", "decision") and content:
                            # Check for duplicates
                            existing = db.get_memories(user_id, category)
                            dup = any(m.get('content','').lower() == content.lower() for m in existing)
                            if not dup:
                                db.add_memory(user_id, category, content)
                                print(f"[MEMORY] Auto-saved: [{category}] {content}")
        except Exception as mem_err:
            print(f"[MEMORY] Extraction failed: {mem_err}")

        # Rebuild chat context: system + summary + last 2 pairs
        system_msgs = [m for m in chat.ollama_chat.messages if m.role == "system"]
        summary_msg = OllamaChatMessage(
            role="system",
            content=f"[Контекст предыдущего диалога]: {summary_content}"
        )
        last_pairs = non_system[-4:]  # keep last 2 user + 2 assistant (or less)

        chat.ollama_chat.messages = system_msgs + [summary_msg] + [
            OllamaChatMessage(role=m.role, content=m.content) for m in last_pairs
        ]
        print(f"[COMPACT] Context rebuilt: {len(chat.ollama_chat.messages)} messages")
    except Exception as e:
        print(f"[COMPACT] Failed: {e}")


def _delete_chat(user_id: int) -> None:
    if user_id not in chats:
        return
    del chats[user_id]

def _create_chat(user_id: int) -> bool:
    if user_id in chats:
        return False

    session_id = None
    if db:
        session_id = db.get_or_create_active_session(user_id, OLLAMA_MODEL)

    history = []
    if db:
        history = db.get_session_messages(user_id, limit=MAX_CONTEXT_MESSAGES)

    chats[user_id] = UserChat(
        selected_model=OLLAMA_MODEL,
        ollama_chat=OllamaChat(messages=[]),
        session_id=session_id,
    )

    system_content = SYSTEM_MESSAGE
    if db:
        notes = db.get_notes(user_id)
        if notes:
            system_content += f"\n\nКонтекст о пользователе:\n{notes}"

        # Load structured memories
        memories = db.get_memories(user_id)
        if memories:
            memory_lines = []
            for m in memories:
                cat = m.get('category', 'fact')
                content = m.get('content', '')
                memory_lines.append(f"- [{cat}] {content}")
            system_content += "\n\nВажные факты и предпочтения:\n" + "\n".join(memory_lines)

    if system_content:
        chats[user_id].ollama_chat.messages.append(
            OllamaChatMessage(role="system", content=system_content)
        )

    # Load latest summary as additional context
    if db and session_id:
        latest_summary = db.get_latest_summary(session_id)
        if latest_summary and latest_summary.get("summary"):
            chats[user_id].ollama_chat.messages.append(
                OllamaChatMessage(
                    role="system",
                    content=f"[Контекст предыдущего диалога]: {latest_summary['summary']}"
                )
            )

    for h in history:
        chats[user_id].ollama_chat.messages.append(
            OllamaChatMessage(role=h["role"], content=h["content"])
        )

    if START_USER_MESSAGE:
        chats[user_id].ollama_chat.messages.append(
            OllamaChatMessage(role="user", content=START_USER_MESSAGE)
        )
    return True

@router.callback_query(F.data == "like")
async def like(callback: CallbackQuery):
    if not callback.from_user:
        return print("[ERROR]: Invalid message")

    user_id = callback.from_user.id
    if user_id not in chats:
        return

    chat = chats[user_id]
    if chat.linked_last_messages:
        try:
            await aiogram_bot.edit_message_reply_markup(
                chat_id=user_id,
                message_id=chat.linked_last_messages,
                reply_markup=None,
            )
        except Exception:
            pass
    chat.linked_last_messages = None
    await callback.answer("👍")

@router.callback_query(F.data == "dislike")
async def dislike(callback: CallbackQuery):
    if not callback.from_user:
        return print("[ERROR]: Invalid message")

    user_id = callback.from_user.id
    if user_id not in chats:
        return

    chat = chats[user_id]
    if not chat.linked_last_messages:
        return
    try:
        await aiogram_bot.delete_message(
            user_id,
            message_id=chat.linked_last_messages,
        )
    except Exception:
        pass
    if not chat.previous_prompt:
        return
    if not isinstance(callback.message, Message):
        raise Exception

    await generate(callback.message, user_id, chat.previous_prompt)
    await callback.answer("Перегенерация...")

@router.message()
async def answer(message: Message) -> None:
    if message.from_user is None or message.text is None:
        return
    user_id = message.from_user.id
    if not _is_allowed(user_id):
        print(f"[BLOCKED] Unauthorized user {user_id}")
        return
    await generate(message, user_id, message.text)
