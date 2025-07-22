
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

user_states = {}
temp_data = {}

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

def teclado_principal():
    buttons = [
        [KeyboardButton("➕ Adicionar Jogo")],
        [KeyboardButton("📋 Listar Jogos")],
        [KeyboardButton("✅ Conferir Jogos (Último Sorteio)")],
        [KeyboardButton("📅 Resultado por Concurso")],
        [KeyboardButton("📂 Conferir com Concurso Passado")],
        [KeyboardButton("❌ Excluir Jogo")],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def validar_dezenas(texto):
    try:
        nums = [int(d) for d in texto.replace(" ", "").split(",")]
        if len(nums) != 6 or any(not (1 <= n <= 60) for n in nums):
            return None
        return sorted(set(nums))
    except:
        return None

async def obter_ultimo_resultado():
    url = "https://servicebus2.caixa.gov.br/portaldeloterias/api/megasena"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Origin": "https://www.loterias.caixa.gov.br",
        "Referer": "https://www.loterias.caixa.gov.br/"
    }
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return None, None, None
                data = await resp.json(content_type=None)
                dezenas = data.get("listaDezenasSorteadasOrdemSorteio") or data.get("listaDezenas")
                concurso = data.get("numero")
                data_sorteio = data.get("dataApuracao")
                return concurso, dezenas, data_sorteio
    except:
        return None, None, None

async def obter_resultado_concurso(concurso_num):
    url = f"https://servicebus2.caixa.gov.br/portaldeloterias/api/megasena/{concurso_num}"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Origin": "https://www.loterias.caixa.gov.br",
        "Referer": "https://www.loterias.caixa.gov.br/"
    }
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return None, None
                data = await resp.json(content_type=None)
                dezenas = data.get("listaDezenasSorteadasOrdemSorteio") or data.get("listaDezenas")
                data_sorteio = data.get("dataApuracao")
                return dezenas, data_sorteio
    except:
        return None, None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎉 Olá! Bem-vindo ao *Bot Mega-Sena*!

Use o menu abaixo para começar.",
        reply_markup=teclado_principal(),
        parse_mode="Markdown"
    )
    user_states.pop(update.message.from_user.id, None)
    temp_data.pop(update.message.from_user.id, None)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    texto = update.message.text.strip()
    estado = user_states.get(uid)

    if texto == "➕ Adicionar Jogo":
        user_states[uid] = "aguardando_dezenas"
        await update.message.reply_text("Digite 6 dezenas separadas por vírgula:")

    elif texto == "📋 Listar Jogos":
        with get_db() as conn:
            jogos = conn.execute("SELECT id, dezenas, data_cadastro FROM jogos WHERE user_id = ?", (uid,)).fetchall()
        if not jogos:
            await update.message.reply_text("Você não tem jogos cadastrados.")
            return
        msg = "📋 *Seus Jogos:*

"
        for idj, dezenas, data_cad in jogos:
            data_fmt = datetime.datetime.fromisoformat(data_cad).strftime("%d/%m/%Y %H:%M")
            msg += f"#{idj}: {dezenas} (cadastrado em {data_fmt})
"
        await update.message.reply_text(msg, parse_mode="Markdown")

    elif texto == "✅ Conferir Jogos (Último Sorteio)":
        texto_resultado = await conferir_jogos(uid)
        await update.message.reply_text(texto_resultado, parse_mode="Markdown")

    elif texto == "📅 Resultado por Concurso":
        user_states[uid] = "aguardando_concurso"
        await update.message.reply_text("Digite o número do concurso:")

    elif texto == "📂 Conferir com Concurso Passado":
        user_states[uid] = "aguardando_conferencia_passada"
        await update.message.reply_text("Digite o número do concurso para conferir seus jogos:")

    elif texto == "❌ Excluir Jogo":
        with get_db() as conn:
            jogos = conn.execute("SELECT id, dezenas FROM jogos WHERE user_id = ?", (uid,)).fetchall()
        if not jogos:
            await update.message.reply_text("Você não tem jogos cadastrados.")
            return
        keyboard = [[InlineKeyboardButton(f"Jogo #{idj}: {dezenas}", callback_data=f"excluir_{idj}")] for idj, dezenas in jogos]
        await update.message.reply_text("Selecione o jogo para excluir:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif estado == "aguardando_dezenas":
        dezenas_validas = validar_dezenas(texto)
        if not dezenas_validas:
            await update.message.reply_text("❌ Dezenas inválidas. Digite 6 números de 1 a 60.")
            return
        dezenas_str = ",".join(f"{d:02d}" for d in dezenas_validas)
        with get_db() as conn:
            conn.execute("INSERT INTO jogos (user_id, dezenas, data_cadastro) VALUES (?, ?, ?)",
                         (uid, dezenas_str, datetime.datetime.now().isoformat()))
        await update.message.reply_text(f"✅ Jogo cadastrado: {dezenas_str}", reply_markup=teclado_principal())
        user_states.pop(uid, None)

    elif estado == "aguardando_concurso":
        try:
            concurso = int(texto)
        except:
            await update.message.reply_text("Número inválido.")
            return
        dezenas, data_sorteio = await obter_resultado_concurso(concurso)
        if dezenas:
            await update.message.reply_text(f"🎯 Resultado #{concurso} ({data_sorteio}): {', '.join(dezenas)}")
        else:
            await update.message.reply_text("Concurso não encontrado.")
        user_states.pop(uid, None)

    elif estado == "aguardando_conferencia_passada":
        try:
            concurso = int(texto)
        except:
            await update.message.reply_text("Número inválido.")
            return
        dezenas_sorteadas, data_sorteio = await obter_resultado_concurso(concurso)
        if not dezenas_sorteadas:
            await update.message.reply_text("Concurso não encontrado ou inválido.")
        else:
            with get_db() as conn:
                jogos = conn.execute("SELECT id, dezenas FROM jogos WHERE user_id = ?", (uid,)).fetchall()
            if not jogos:
                await update.message.reply_text("Você não tem jogos cadastrados.")
            else:
                texto = f"🎯 Resultado #{concurso} - {data_sorteio}
Dezenas: {', '.join(dezenas_sorteadas)}

"
                for jid, dezenas_jogo in jogos:
                    dezenas_jogo_list = dezenas_jogo.split(",")
                    acertos = set(dezenas_jogo_list) & set(dezenas_sorteadas)
                    dezenas_formatadas = [
                        f"{dez} ✅" if dez in acertos else dez for dez in dezenas_jogo_list
                    ]
                    qtd_acertos = len(acertos)

                    if qtd_acertos == 6:
                        emoji_resultado = "🏆🎉"
                    elif qtd_acertos == 5:
                        emoji_resultado = "💰"
                    elif qtd_acertos == 4:
                        emoji_resultado = "🎯"
                    else:
                        emoji_resultado = "✖️"

                    texto += f"Jogo #{jid}: {', '.join(dezenas_formatadas)} - Acertos: *{qtd_acertos}* {emoji_resultado}
"
                await update.message.reply_text(texto, parse_mode="Markdown")
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

async def conferir_jogos(uid):
    concurso, dezenas_sorteadas, data_sorteio = await obter_ultimo_resultado()
    if not dezenas_sorteadas:
        return "❌ Erro ao obter o resultado da Mega-Sena."
    with get_db() as conn:
        jogos = conn.execute("SELECT id, dezenas FROM jogos WHERE user_id = ?", (uid,)).fetchall()
    if not jogos:
        return "Você não tem jogos cadastrados."
    texto = f"🎯 Resultado Mega-Sena #{concurso} - {data_sorteio}
Dezenas: {', '.join(dezenas_sorteadas)}

"
    for jid, dezenas_jogo in jogos:
        dezenas_jogo_list = dezenas_jogo.split(",")
        acertos = set(dezenas_jogo_list) & set(dezenas_sorteadas)
        dezenas_formatadas = [
            f"{dez} ✅" if dez in acertos else dez for dez in dezenas_jogo_list
        ]
        qtd_acertos = len(acertos)

        if qtd_acertos == 6:
            emoji_resultado = "🏆🎉"
        elif qtd_acertos == 5:
            emoji_resultado = "💰"
        elif qtd_acertos == 4:
            emoji_resultado = "🎯"
        else:
            emoji_resultado = "✖️"

        texto += f"Jogo #{jid}: {', '.join(dezenas_formatadas)} - Acertos: *{qtd_acertos}* {emoji_resultado}
"
    return texto

if __name__ == "__main__":
    nest_asyncio.apply()

    async def main():
        print("🔄 Inicializando bot...")
        init_db()
        token = os.getenv("BOT_TOKEN")
        if not token:
            print("❌ BOT_TOKEN não definido.")
            return
        app = ApplicationBuilder().token(token).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
        app.add_handler(CallbackQueryHandler(button_handler))
        print("✅ Bot rodando...")
        await app.run_polling()

    asyncio.run(main())
