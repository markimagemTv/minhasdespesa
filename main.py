import os
import sqlite3
import datetime
import aiohttp
import nest_asyncio
import asyncio
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

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

# Teclado principal

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

# Validação de dezenas

def validar_dezenas(texto):
    try:
        nums = sorted(set(int(d) for d in texto.replace(" ", "").split(",")))
        if len(nums) != 6 or any(not (1 <= n <= 60) for n in nums):
            return None
        return nums
    except:
        return None

# Obter último resultado com prêmios e acumulado

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
                    return None, None, None, None, None
                data = await resp.json(content_type=None)
                dezenas = data.get("listaDezenasSorteadasOrdemSorteio") or data.get("listaDezenas")
                concurso = data.get("numero")
                data_sorteio = data.get("dataApuracao")
                premiacoes = data.get("listaRateioPremio")
                acumulado = data.get("valorAcumuladoProximoConcurso")
                return concurso, dezenas, data_sorteio, premiacoes, acumulado
    except:
        return None, None, None, None, None

# Obter resultado por concurso

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

# Conferência de jogos

async def conferir_jogos(uid):
    concurso, dezenas_sorteadas, data_sorteio, premiacoes, acumulado = await obter_ultimo_resultado()
    if not dezenas_sorteadas:
        return "❌ Erro ao obter o resultado da Mega-Sena."
    with get_db() as conn:
        jogos = conn.execute("SELECT id, dezenas FROM jogos WHERE user_id = ?", (uid,)).fetchall()
    if not jogos:
        return "Você não tem jogos cadastrados."

    texto = f"🎯 Resultado Mega-Sena #{concurso} - {data_sorteio}\nDezenas: {', '.join(dezenas_sorteadas)}\n"

    # Prêmios
    if premiacoes:
        texto += "\n🏆 Premiação:\n"
        for p in premiacoes:
            faixa = p.get("descricaoFaixa")
            ganhadores = p.get("numeroDeGanhadores")
            valor = p.get("valorPremio")
            texto += f"➡️ {faixa}: {ganhadores} ganhador(es) - R$ {float(valor):,.2f}\n"

    if acumulado:
        texto += f"\n📈 Acumulado próximo concurso: R$ {float(acumulado):,.2f}\n"

    texto += "\n📊 Seus jogos:\n"
    for jid, dezenas_jogo in jogos:
        dezenas_jogo_list = dezenas_jogo.split(",")
        acertos = set(dezenas_jogo_list) & set(dezenas_sorteadas)
        emojis = {4: "🔸", 5: "🔷", 6: "💎"}.get(len(acertos), "➖")
        texto += f"{emojis} Jogo #{jid}: {dezenas_jogo} - Acertos: *{len(acertos)}*\n"

    return texto

# Bot Handlers (Start, Mensagens, Botões)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎉 Olá! Bem-vindo ao *Bot Mega-Sena*!\n\nUse o menu abaixo para começar.",
        reply_markup=teclado_principal(),
        parse_mode="Markdown"
    )
    user_states.pop(update.message.from_user.id, None)
    temp_data.pop(update.message.from_user.id, None)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text.strip()

    # Estados pendentes
    if user_states.get(uid) == "aguardando_dezenas":
        dezenas = validar_dezenas(text)
        if not dezenas:
            await update.message.reply_text("❌ Entrada inválida. Envie 6 números de 1 a 60 separados por vírgula.")
            return
        with get_db() as conn:
            conn.execute("INSERT INTO jogos (user_id, dezenas, data_cadastro) VALUES (?, ?, ?)",
                         (uid, ",".join(map(str, dezenas)), datetime.datetime.now().isoformat()))
        await update.message.reply_text("✅ Jogo cadastrado com sucesso!", reply_markup=teclado_principal())
        user_states.pop(uid, None)
        return

    if text == "➕ Adicionar Jogo":
        user_states[uid] = "aguardando_dezenas"
        await update.message.reply_text("✍️ Envie suas 6 dezenas separadas por vírgula (ex: 5,12,23,34,45,56)")

    elif text == "📋 Listar Jogos":
        with get_db() as conn:
            jogos = conn.execute("SELECT id, dezenas FROM jogos WHERE user_id = ?", (uid,)).fetchall()
        if not jogos:
            await update.message.reply_text("📭 Você ainda não cadastrou nenhum jogo.")
        else:
            resposta = "📋 Seus jogos cadastrados:\n"
            for jid, d in jogos:
                resposta += f"🔹 Jogo #{jid}: {d}\n"
            await update.message.reply_text(resposta)

    elif text == "✅ Conferir Jogos (Último Sorteio)":
        resposta = await conferir_jogos(uid)
        await update.message.reply_text(resposta, parse_mode="Markdown")

    elif text == "❌ Excluir Jogo":
        with get_db() as conn:
            jogos = conn.execute("SELECT id, dezenas FROM jogos WHERE user_id = ?", (uid,)).fetchall()
        if not jogos:
            await update.message.reply_text("Você não tem jogos para excluir.")
            return
        botoes = [[InlineKeyboardButton(f"Jogo #{jid}: {d}", callback_data=f"del:{jid}")]
                  for jid, d in jogos]
        markup = InlineKeyboardMarkup(botoes)
        await update.message.reply_text("🗑️ Escolha o jogo que deseja excluir:", reply_markup=markup)

    elif text == "📅 Resultado por Concurso":
        user_states[uid] = "aguardando_concurso_resultado"
        await update.message.reply_text("📩 Envie o número do concurso que deseja consultar.")

    elif text == "📂 Conferir com Concurso Passado":
        user_states[uid] = "aguardando_concurso_conferencia"
        await update.message.reply_text("📩 Envie o número do concurso com o qual deseja conferir seus jogos.")

    elif user_states.get(uid) == "aguardando_concurso_resultado" and text.isdigit():
        dezenas, data_sorteio = await obter_resultado_concurso(text)
        if not dezenas:
            await update.message.reply_text("❌ Concurso não encontrado.")
        else:
            await update.message.reply_text(f"📅 Concurso #{text} ({data_sorteio})\n🔢 Dezenas: {', '.join(dezenas)}")
        user_states.pop(uid, None)

    elif user_states.get(uid) == "aguardando_concurso_conferencia" and text.isdigit():
        dezenas, data_sorteio = await obter_resultado_concurso(text)
        if not dezenas:
            await update.message.reply_text("❌ Concurso não encontrado.")
        else:
            with get_db() as conn:
                jogos = conn.execute("SELECT id, dezenas FROM jogos WHERE user_id = ?", (uid,)).fetchall()
            if not jogos:
                await update.message.reply_text("Você não tem jogos cadastrados.")
            else:
                resposta = f"📅 Concurso #{text} ({data_sorteio})\n🔢 Dezenas sorteadas: {', '.join(dezenas)}\n\n"
                for jid, d in jogos:
                    dezenas_jogo = d.split(",")
                    acertos = set(dezenas_jogo) & set(dezenas)
                    emojis = {4: "🔸", 5: "🔷", 6: "💎"}.get(len(acertos), "➖")
                    resposta += f"{emojis} Jogo #{jid}: {d} - Acertos: *{len(acertos)}*\n"
                await update.message.reply_text(resposta, parse_mode="Markdown")
        user_states.pop(uid, None)

    else:
        await update.message.reply_text("❓ Comando não reconhecido. Use o menu abaixo.", reply_markup=teclado_principal())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("del:"):
        jid = int(query.data.split(":")[1])
        with get_db() as conn:
            conn.execute("DELETE FROM jogos WHERE id = ?", (jid,))
        await query.edit_message_text("✅ Jogo excluído com sucesso.")

# Main

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
