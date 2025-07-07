import os
import sqlite3
import datetime
import aiohttp
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import nest_asyncio
import asyncio

# Estados e dados temporários por usuário
user_states = {}
temp_data = {}

# Banco de dados
def get_db():
    return sqlite3.connect("megasena.db")

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS jogos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                dezenas TEXT,
                data_cadastro TEXT
            )
        ''')

# Teclados principais
def teclado_principal():
    buttons = [
        [KeyboardButton("➕ Adicionar Jogo")],
        [KeyboardButton("📋 Listar Jogos")],
        [KeyboardButton("✅ Conferir Jogos (Último Sorteio)")],
        [KeyboardButton("📅 Resultado por Concurso")],
        [KeyboardButton("❌ Excluir Jogo")],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

# Validação das dezenas
def validar_dezenas(texto):
    try:
        nums = [int(d) for d in texto.replace(" ", "").split(",")]
        if len(nums) != 6 or any(not (1 <= n <= 60) for n in nums):
            return None
        return sorted(set(nums))
    except:
        return None

# API da Caixa para último resultado
async def obter_ultimo_resultado():
    url = "https://servicebus2.caixa.gov.br/portaldeloterias/api/megasena"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                dezenas = data["listaDezenasSorteadasOrdemSorteio"]
                concurso = data["numero"]
                data_sorteio = data["dataApuracao"]
                return concurso, dezenas, data_sorteio
    return None, None, None

# API Caixa para resultado por concurso
async def obter_resultado_concurso(concurso_num):
    url = f"https://servicebus2.caixa.gov.br/portaldeloterias/api/megasena/{concurso_num}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                dezenas = data.get("listaDezenasSorteadasOrdemSorteio")
                data_sorteio = data.get("dataApuracao")
                return dezenas, data_sorteio
    return None, None

# Handlers do bot

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎉 Olá! Bem-vindo ao *Bot Mega-Sena*!\n\n"
        "Use o menu abaixo para começar.",
        reply_markup=teclado_principal(),
        parse_mode="Markdown"
    )
    user_states.pop(update.message.from_user.id, None)
    temp_data.pop(update.message.from_user.id, None)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    texto = update.message.text.strip()
    estado = user_states.get(uid)

    # Comandos pelo menu principal
    if texto == "➕ Adicionar Jogo":
        user_states[uid] = "aguardando_dezenas"
        await update.message.reply_text(
            "Digite as 6 dezenas do seu jogo separadas por vírgula (ex: 04,15,23,33,40,56):"
        )
        temp_data[uid] = {}

    elif texto == "📋 Listar Jogos":
        with get_db() as conn:
            jogos = conn.execute("SELECT id, dezenas, data_cadastro FROM jogos WHERE user_id = ?", (uid,)).fetchall()
        if not jogos:
            await update.message.reply_text("Você não tem jogos cadastrados.")
            return
        msg = "📋 *Seus Jogos:*\n\n"
        for idj, dezenas, data_cad in jogos:
            data_fmt = datetime.datetime.fromisoformat(data_cad).strftime("%d/%m/%Y %H:%M")
            msg += f"#{idj}: {dezenas} (cadastrado em {data_fmt})\n"
        await update.message.reply_text(msg, parse_mode="Markdown")

    elif texto == "✅ Conferir Jogos (Último Sorteio)":
        texto_resultado = await conferir_jogos(uid)
        await update.message.reply_text(texto_resultado, parse_mode="Markdown")

    elif texto == "📅 Resultado por Concurso":
        user_states[uid] = "aguardando_concurso"
        await update.message.reply_text("Digite o número do concurso que deseja consultar:")

    elif texto == "❌ Excluir Jogo":
        with get_db() as conn:
            jogos = conn.execute("SELECT id, dezenas FROM jogos WHERE user_id = ?", (uid,)).fetchall()
        if not jogos:
            await update.message.reply_text("Você não tem jogos cadastrados.")
            return
        keyboard = [[InlineKeyboardButton(f"Jogo #{idj}: {dezenas}", callback_data=f"excluir_{idj}")] for idj, dezenas in jogos]
        await update.message.reply_text("Selecione o jogo para excluir:", reply_markup=InlineKeyboardMarkup(keyboard))

    # Estados guiados

    elif estado == "aguardando_dezenas":
        dezenas_validas = validar_dezenas(texto)
        if not dezenas_validas:
            await update.message.reply_text("❌ Formato inválido. Digite 6 números entre 1 e 60 separados por vírgula.")
            return
        dezenas_str = ",".join(f"{d:02d}" for d in dezenas_validas)
        with get_db() as conn:
            conn.execute(
                "INSERT INTO jogos (user_id, dezenas, data_cadastro) VALUES (?, ?, ?)",
                (uid, dezenas_str, datetime.datetime.now().isoformat())
            )
        await update.message.reply_text(f"✅ Jogo cadastrado: {dezenas_str}", reply_markup=teclado_principal())
        user_states.pop(uid, None)
        temp_data.pop(uid, None)

    elif estado == "aguardando_concurso":
        try:
            concurso_num = int(texto)
        except:
            await update.message.reply_text("❌ Número de concurso inválido. Tente novamente.")
            return

        dezenas, data_sorteio = await obter_resultado_concurso(concurso_num)
        if dezenas is None:
            await update.message.reply_text("❌ Concurso não encontrado ou ainda não realizado.")
        else:
            dezenas_fmt = ", ".join(dezenas)
            await update.message.reply_text(
                f"🎯 Resultado Concurso #{concurso_num} - {data_sorteio}\n"
                f"Dezenas sorteadas: {dezenas_fmt}"
            )
        user_states.pop(uid, None)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

    if data.startswith("excluir_"):
        idj = int(data.split("_")[1])
        with get_db() as conn:
            conn.execute("DELETE FROM jogos WHERE id = ? AND user_id = ?", (idj, uid))
        await query.edit_message_text("🗑️ Jogo removido com sucesso!")

# Conferir jogos do usuário com o último resultado
async def conferir_jogos(uid):
    concurso, dezenas_sorteadas, data_sorteio = await obter_ultimo_resultado()
    if not dezenas_sorteadas:
        return "❌ Não foi possível obter o resultado da Mega-Sena."

    with get_db() as conn:
        jogos = conn.execute("SELECT id, dezenas FROM jogos WHERE user_id = ?", (uid,)).fetchall()

    if not jogos:
        return "Você não tem jogos cadastrados."

    texto = f"🎯 *Resultado Mega-Sena Concurso #{concurso}* - {data_sorteio}\n"
    texto += f"Dezenas sorteadas: {', '.join(dezenas_sorteadas)}\n\n"

    for jid, dezenas_jogo in jogos:
        dezenas_jogo_list = dezenas_jogo.split(",")
        acertos = set(dezenas_jogo_list) & set(dezenas_sorteadas)
        texto += f"Jogo #{jid}: {dezenas_jogo} - Acertos: *{len(acertos)}*\n"

    return texto

# Main runner Railway-safe
if __name__ == "__main__":
    nest_asyncio.apply()

    async def main():
        print("🔄 Inicializando...")
        init_db()
        token = os.getenv("BOT_TOKEN")
        if not token:
            print("❌ BOT_TOKEN não encontrado.")
            return

        app = ApplicationBuilder().token(token).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
        app.add_handler(CallbackQueryHandler(button_handler))
        print("✅ Bot Mega-Sena rodando no Railway...")
        await app.run_polling()

    asyncio.get_event_loop().run_until_complete(main())
