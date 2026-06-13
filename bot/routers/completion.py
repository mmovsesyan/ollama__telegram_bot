from aiogram import F, Router
from aiogram.filters.command import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from pydantic import BaseModel
import asyncio
import json
import os
import tempfile

from bot.bot import bot as aiogram_bot
from bot.keyboards.inline import answer_keyboard
from bot.keyboards.reply import command_keyboard, cancel_keyboard
from bot.ollama import OllamaChat, OllamaChatMessage, generate_chat_completion
from bot.ollama.api import get_installed_models, model_is_installed
from bot.ollama.dto import OllamaErrorChunk
from bot.states import BotStates
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
    last_active: float = 0

chats: dict[int, UserChat] = {}
_typing_last: dict[int, float] = {}
_request_last: dict[int, float] = {}
_generating: set[int] = set()

import time

async def _cleanup_old_chats():
    """Remove chat sessions idle for > 2 hours to prevent memory leak."""
    now = time.time()
    stale = [uid for uid, chat in chats.items() if chat.last_active < now - 7200]
    for uid in stale:
        _delete_chat(uid)
        print(f"[CLEANUP] Removed idle session for user {uid}")

async def _safe_typing(user_id: int):
    import time
    now = time.time()
    if user_id in _typing_last and now - _typing_last[user_id] < 3:
        return
    _typing_last[user_id] = now
    try:
        await aiogram_bot.send_chat_action(chat_id=user_id, action="typing")
    except Exception as e:
        if "Flood control" in str(e) or "Too Many Requests" in str(e):
            pass
        else:
            print(f"[TYPING] Error: {e}")

def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token on average."""
    return max(1, len(text) // 4)

BUTTON_MAP = {
    "🤖 Модели": "/models",
    "🔍 Поиск": "/search",
    "🌤 Погода": "/weather",
    "📰 Новости": "/news",
    "🧠 Память": "/memory",
    "📝 Заметка": "/note",
    "⏰ Напоминание": "/remind",
    "🔍 Мониторы": "/monitors",
    "➕ Монитор": "/monitor_add",
    "📊 Отчёт": "/report",
    "❓ Помощь": "/help",
    "🗑 Очистить": "/clear",
}

async def generate(message: Message, user_id: int, text: str):
    now = time.time()
    if user_id in _request_last and now - _request_last[user_id] < 1:
        await message.answer("Слишком быстро. Подождите секунду.")
        return
    _request_last[user_id] = now

    if user_id in _generating:
        await message.answer("⏳ Подождите, я уже отвечаю...")
        return
    _generating.add(user_id)

    # Map Russian button labels back to commands
    if text in BUTTON_MAP:
        text = BUTTON_MAP[text]

    # Safety net: known commands should never reach the LLM
    KNOWN_COMMANDS = {
        "/models", "/help", "/model", "/clear",
        "/search", "/weather", "/news", "/note",
        "/remind", "/reminders", "/remind_cancel", "/remind_remove",
        "/monitors", "/monitor_add", "/monitor_remove",
        "/report", "/memory", "/memory_add", "/memory_remove",
        "/fetch",
    }
    parts = text.split()
    if parts and parts[0] in KNOWN_COMMANDS:
        cmd = parts[0]
        print(f"[ROUTING WARNING] Command {cmd} reached generate(). Check router order.")
        await message.answer(
            f"⚠️ Команда {cmd} не обработана. Убедитесь, что cron.router подключён ДО completion.router."
        )
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

    chat.last_active = time.time()
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
        async with asyncio.timeout(300):
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
    except asyncio.TimeoutError:
        print(f"[ERROR] Generation timeout for user {user_id}")
        await msg.edit_text("⏳ Генерация заняла слишком много времени. Попробуйте ещё раз.")
        return
    except Exception as e:
        print(f"[ERROR] Generation failed: {e}")
        await msg.edit_text(f"Произошла ошибка при генерации ответа. Попробуйте ещё раз.\n({str(e)[:200]})")
        return
    finally:
        _generating.discard(user_id)

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
    MAX_CONTEXT_TOKENS = 4000
    system_messages = [m for m in chat.ollama_chat.messages if m.role == "system"]
    other_messages = [m for m in chat.ollama_chat.messages if m.role != "system"]

    total_tokens = sum(_estimate_tokens(m.content) for m in system_messages)
    kept: list[OllamaChatMessage] = []
    # Keep newest messages first, then prepend older ones while under token budget
    for m in reversed(other_messages):
        tokens = _estimate_tokens(m.content)
        if total_tokens + tokens > MAX_CONTEXT_TOKENS and kept:
            break
        total_tokens += tokens
        kept.insert(0, m)

    chat.ollama_chat.messages = system_messages + kept


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

@router.message(Command("models"))
@router.message(lambda m: m.text and m.text == "/models")
@router.message(F.text == "🤖 Модели")
async def cmd_models(message: Message):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        print(f"[BLOCKED] Unauthorized user {message.from_user.id}")
        return
    models = await get_installed_models()
    model_list = "\n".join([f"- {m.name}" for m in models]) or "Нет моделей"
    await message.answer(f"Доступные модели:\n{model_list}")


@router.message(Command("help"))
@router.message(lambda m: m.text and m.text == "/help")
@router.message(F.text == "❓ Помощь")
async def cmd_help(message: Message):
    if message.from_user is None:
        return
    if not _is_allowed(message.from_user.id):
        print(f"[BLOCKED] Unauthorized user {message.from_user.id}")
        return
    await message.answer(
        "🤖 Команды бота:\n\n"
        "📋 AI:\n"
        "/models — список моделей\n"
        "/model <name> — сменить модель\n"
        "/clear — очистить историю\n\n"
        "🌐 Поиск в интернете:\n"
        "/search <запрос> — поиск через Ollama Web\n"
        "/fetch <url> — загрузить страницу\n"
        "/weather <город> — погода\n"
        "/news — актуальные новости\n\n"
        "📝 Заметки и память:\n"
        "/note <текст> — сохранить заметку\n"
        "/memory_add [<category>] <текст> — сохранить факт\n"
        "   категории: fact, preference, task, decision\n"
        "/memory — показать все факты\n"
        "/memory_remove <id> — удалить факт\n\n"
        "⏰ Напоминания:\n"
        "/remind <время> <текст> — добавить\n"
        "/reminders — список\n"
        "/remind_cancel <id> — отменить\n"
        "/remind_remove <id> — удалить\n\n"
        "🔍 Мониторинг сайтов:\n"
        "/monitor_add <name> <url> [интервал] — добавить\n"
        "   Интервал: 5m (5 мин), 1h (1 час), или секунды\n"
        "   Пример: /monitor_add Timeweb 37.220.85.240 5m\n"
        "/monitors — список и статус\n"
        "/monitor_remove <id> — удалить\n\n"
        "📊 Другое:\n"
        "/report — ежедневный отчёт\n"
        "/help — эта справка\n\n"
        "Напишите любое сообщение для разговора с AI.",
    )


@router.message(Command("model"))
@router.message(lambda m: m.text and (m.text == "/model" or m.text.startswith("/model ")))
async def cmd_model(message: Message, state: FSMContext):
    if message.from_user is None:
        return
    user_id = message.from_user.id
    if not _is_allowed(user_id):
        print(f"[BLOCKED] Unauthorized user {user_id}")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "Введите название модели:\n"
            "Пример: llama2:13b-chat",
        )
        await state.set_state(BotStates.waiting_model)
        return
    model_to_set = parts[1].strip()
    if not await model_is_installed(model_to_set):
        await message.answer(f"Модель {model_to_set} не найдена!")
        return
    _create_chat(user_id)
    chats[user_id].selected_model = model_to_set
    await message.answer(f"Модель изменена на {model_to_set}")


@router.message(BotStates.waiting_model)
async def process_model_state(message: Message, state: FSMContext):
    if message.from_user is None:
        await state.clear()
        return
    user_id = message.from_user.id
    if not _is_allowed(user_id):
        await state.clear()
        return
    if message.text is None:
        await message.answer("Ожидался текст.", reply_markup=cancel_keyboard)
        await state.clear()
        return
    text = message.text or ""
    if text == "❌ Отмена":
        await state.clear()
        await message.answer("Действие отменено.", reply_markup=ReplyKeyboardRemove())
        return
    if text.startswith("/") or text in BUTTON_MAP:
        await state.clear()
        await message.answer("Текущее действие отменено.", reply_markup=ReplyKeyboardRemove())
        return
    model_to_set = text.strip()
    if not await model_is_installed(model_to_set):
        await message.answer(f"Модель {model_to_set} не найдена!", reply_markup=cancel_keyboard)
        await state.clear()
        return
    _create_chat(user_id)
    chats[user_id].selected_model = model_to_set
    await message.answer(f"Модель изменена на {model_to_set}", reply_markup=cancel_keyboard)
    await state.clear()


@router.message(Command("clear"))
@router.message(lambda m: m.text and m.text == "/clear")
@router.message(F.text == "🗑 Очистить")
async def cmd_clear(message: Message):
    if message.from_user is None:
        return
    user_id = message.from_user.id
    if not _is_allowed(user_id):
        print(f"[BLOCKED] Unauthorized user {user_id}")
        return
    if user_id in chats and chats[user_id].session_id and db:
        db.close_session(chats[user_id].session_id, "User cleared chat")
    _delete_chat(user_id)
    await message.answer("История очищена.")


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

async def _download_document(document):
    file = await aiogram_bot.get_file(document.file_id)
    suffix = os.path.splitext(document.file_name or "")[1] or ".bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = tmp.name
    await aiogram_bot.download_file(file.file_path, tmp_path)
    return tmp_path, document.file_name or "file", suffix.lower()

def _extract_text_from_file(file_path: str, suffix: str) -> str:
    if suffix == ".pdf":
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(file_path)
            parts = []
            for i, page in enumerate(reader.pages):
                parts.append(page.extract_text() or "")
                if i >= 30:
                    parts.append("\n...[truncated at 30 pages]")
                    break
            return "\n".join(parts)
        except ImportError:
            return "[PDF: установите PyPDF2 для извлечения текста]"
        except Exception as e:
            return f"[PDF extraction error: {e}]"
    elif suffix == ".json":
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        try:
            data = json.loads(content)
            return json.dumps(data, ensure_ascii=False, indent=2)
        except:
            return content
    elif suffix in (".csv", ".tsv"):
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    elif suffix in (".txt", ".md", ".py", ".js", ".html", ".css", ".sql", ".log", ".xml", ".yaml", ".yml"):
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    elif suffix == ".docx":
        try:
            import docx
            doc = docx.Document(file_path)
            return "\n".join(para.text for para in doc.paragraphs)
        except ImportError:
            return "[DOCX: установите python-docx для извлечения текста]"
        except Exception as e:
            return f"[DOCX extraction error: {e}]"
    else:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return f"[Unsupported or binary file type: {suffix}]"

@router.message(F.document)
async def handle_document(message: Message, state: FSMContext):
    if message.from_user is None:
        return
    user_id = message.from_user.id
    if not _is_allowed(user_id):
        return
    document = message.document
    if document is None:
        return

    await message.answer(f"📄 Получен файл: {document.file_name or 'unknown'}\nЗагружаю и извлекаю текст...")

    tmp_path = None
    try:
        tmp_path, fname, suffix = await _download_document(document)
        text = _extract_text_from_file(tmp_path, suffix)
    except Exception as e:
        await message.answer(f"❌ Ошибка обработки файла: {str(e)[:200]}")
        return
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    if not text or not text.strip():
        await message.answer("❌ Не удалось извлечь текст из файла.")
        return

    max_chars = 12000
    original_len = len(text)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n...[обрезано с {original_len} символов]"

    prompt = f"[Документ: {fname}]\n\n{text}\n\nПроанализируй содержимое и дай краткий обзор."
    await generate(message, user_id, prompt)

def _detect_intent(text: str) -> tuple[str | None, str | None]:
    """Detect user intent from natural language. Returns (intent, extracted_arg)."""
    import re
    t = text.lower().strip()

    # --- remind ---
    if re.search(r"напомни|напомнить|добавь напоминание|добавить напоминание|напомни мне", t):
        return "remind", text

    # --- weather ---
    m = re.search(r"(?:погода|погоду|weather|температура)(?:\s+(?:в|for|in|для))?\s+([a-zа-яё\-]+)", t)
    if m:
        return "weather", m.group(1).capitalize()
    if re.search(r"^погода$|^погоду$|^weather$", t):
        return "weather", None

    # --- search ---
    m = re.search(r"(?:поищи|найди|загугли|погугли|ищи|search|google)\s+(.+)", t)
    if m:
        return "search", m.group(1).strip()

    # --- news ---
    if re.search(r"новости|последние новости|news", t):
        return "news", None

    # --- memory add ---
    m = re.search(r"(?:запомни|добавь факт|запиши что|запомни что)\s+(.+)", t)
    if m:
        return "memory_add", m.group(1).strip()

    # --- memory show ---
    if re.search(r"моя память|что ты помнишь|покажи память|мои факты|покажи факты", t):
        return "memory_show", None

    # --- note ---
    m = re.search(r"(?:заметка|запиши заметку|сделай заметку)\s+(.+)", t)
    if m:
        return "note", m.group(1).strip()

    # --- monitor add ---
    m = re.search(r"(?:добавь монитор|монитор|следи за)\s+(.+)", t)
    if m:
        return "monitor_add", m.group(1).strip()

    # --- monitor show ---
    if re.search(r"мониторы|покажи мониторы|список мониторов", t):
        return "monitor_show", None

    # --- report ---
    if re.search(r"отч[её]т|report|ежедневный отч[её]т", t):
        return "report", None

    # --- help ---
    if re.search(r"помощь|help|справка|команды", t):
        return "help", None

    # --- models ---
    if re.search(r"модели|список моделей|models", t):
        return "models", None

    # --- model switch ---
    m = re.search(r"(?:смени модель|поменяй модель|выбери модель)\s+(.+)", t)
    if m:
        return "model", m.group(1).strip()

    # --- clear ---
    if re.search(r"очисти|сбрось|clear chat|очистить историю", t):
        return "clear", None

    return None, None


async def answer(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    user_id = message.from_user.id
    if message.text is None:
        await message.answer("Я работаю только с текстом. Напишите сообщение или используйте кнопки.")
        return
    if not _is_allowed(user_id):
        print(f"[BLOCKED] Unauthorized user {user_id}")
        return
    text = message.text

    # Handle cancel button globally
    if text == "❌ Отмена":
        current_state = await state.get_state()
        if current_state is not None:
            await state.clear()
            await message.answer("Действие отменено.")
        else:
            await message.answer("Нет активного действия для отмены.")
        return

    # --- Natural language intent routing ---
    try:
        intent, arg = _detect_intent(text)
        if intent and not text.startswith("/"):
            # Map intent to direct function calls from cron router
            if intent == "weather":
                if arg:
                    from bot.routers.cron import _process_weather
                    await _process_weather(message, arg)
                else:
                    await message.answer("🌤 Какой город?")
                return
            if intent == "search":
                if arg:
                    from bot.routers.cron import _process_search
                    await _process_search(message, arg)
                else:
                    await message.answer("🔍 Что искать?")
                return
            if intent == "news":
                from bot.routers.cron import cmd_news
                await cmd_news(message)
                return
            if intent == "remind":
                from bot.routers.cron import _process_remind
                await _process_remind(user_id, text)
                return
            if intent == "memory_show":
                from bot.routers.cron import cmd_memory
                await cmd_memory(message)
                return
            if intent == "monitor_show":
                from bot.routers.cron import cmd_monitors
                await cmd_monitors(message)
                return
            if intent == "report":
                from bot.routers.cron import cmd_report
                await cmd_report(message)
                return
            if intent == "note":
                if arg and db:
                    db.add_note(user_id, arg)
                    await message.answer("Заметка сохранена.")
                else:
                    await message.answer("📝 Что записать?")
                return
            if intent == "memory_add":
                if arg and db:
                    parts = arg.split(maxsplit=1)
                    cat = parts[0].lower() if len(parts) > 1 else "fact"
                    content = parts[1] if len(parts) > 1 else arg
                    if cat not in ("fact", "preference", "task", "decision"):
                        cat = "fact"
                        content = arg
                    mid = db.add_memory(user_id, cat, content)
                    await message.answer(f"✅ Факт #{mid} сохранён: [{cat}] {content}")
                else:
                    await message.answer("🧠 Что запомнить?")
                return
            if intent == "monitor_add":
                await message.answer(
                    "🔍 Введите данные монитора:\n<имя> <url> [интервал]\nПример: Google google.com 5m",
                )
                return
            if intent == "models":
                await generate(message, user_id, "/models")
                return
            if intent == "model":
                if arg:
                    await generate(message, user_id, f"/model {arg}")
                else:
                    await message.answer("Укажите модель. Пример: смени модель llama3")
                return
            if intent == "clear":
                await generate(message, user_id, "/clear")
                return
            if intent == "help":
                await generate(message, user_id, "/help")
                return

    except Exception as e:
        print(f"[INTENT ERROR] {e}")
    await generate(message, user_id, text)

# Global error handler: prevents bot crash on any unhandled exception
@router.errors()
async def global_error_handler(event):
    update = event.update
    exception = event.exception
    print(f"[GLOBAL ERROR] {exception}")
    if update.message:
        try:
            from bot.keyboards.reply import command_keyboard
            await update.message.answer(
                "⚠️ Произошла ошибка. Попробуйте ещё раз или используйте /help.",
            )
        except Exception as e:
            print(f"[ERROR HANDLER FAIL] {e}")
