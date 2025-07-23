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
        "🎉 Olá! Bem-vindo ao *Bot Mega-Sena*!\n\nUse o menu abaixo para começar.",
        reply_markup=teclado_principal(),
        parse_mode="Markdown"
    )
    user_states.pop(update.message.from_user.id, None)
    temp_data.pop(update.message.from_user.id, None)

async def conferir_jogos(uid):
    concurso, dezenas_sorteadas, data_sorteio = await obter_ultimo_resultado()
    if not dezenas_sorteadas:
        return "❌ Erro ao obter o resultado da Mega-Sena."
    with get_db() as conn:
        jogos = conn.execute("SELECT id, dezenas FROM jogos WHERE user_id = ?", (uid,)).fetchall()
    if not jogos:
        return "Você não tem jogos cadastrados."

    texto = f"🎯 Resultado Mega-Sena #{concurso} - {data_sorteio}\nDezenas: {', '.join(dezenas_sorteadas)}\n\n"
    for jid, dezenas_jogo in jogos:
        dezenas_jogo_list = dezenas_jogo.split(",")
        acertos = set(dezenas_jogo_list) & set(dezenas_sorteadas)
        emojis = ''.join(['✅' if dj in acertos else '🔸' for dj in dezenas_jogo_list])
        bonus = ""
        if len(acertos) == 6:
            bonus = " 🏆🎉"
        elif len(acertos) == 5:
            bonus = " 💰"
        elif len(acertos) == 4:
            bonus = " 🎯"
        texto += f"Jogo #{jid}: {dezenas_jogo} - Acertos: *{len(acertos)}*{bonus} {emojis}\n"

    # Buscar info extra sobre prêmios e acumulado
    url = f"https://servicebus2.caixa.gov.br/portaldeloterias/api/megasena/{concurso}"
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    rateios = data.get("listaRateioPremio", [])
                    acumulado = data.get("valorAcumuladoConcursoProximo", 0)
                    texto += "\n\n🏅 *Prêmios Pagos:*\n"
                    for faixa in rateios:
                        texto += f"- {faixa['descricaoFaixa']}: {faixa['numeroDeGanhadores']} ganhador(es), R$ {float(faixa['valorPremio']):,.2f}\n"
                    texto += f"\n📈 *Acumulado para o próximo concurso:* R$ {float(acumulado):,.2f}"
    except:
        texto += "\n\n⚠️ Não foi possível carregar os prêmios."

    return texto

# Você pode continuar incluindo os outros handlers como message_handler, excluir jogo etc. com base na estrutura acima.

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
