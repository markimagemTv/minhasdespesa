import os
import sqlite3
import datetime
import aiohttp
import nest_asyncio
import asyncio
import base64
import mercadopago
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
        conn.execute('''
            CREATE TABLE IF NOT EXISTS acessos (
                user_id INTEGER PRIMARY KEY,
                liberado BOOLEAN DEFAULT 0,
                data_pagamento TEXT
            )
        ''')

# Mercado Pago
mp_client = mercadopago.SDK(os.getenv("MERCADO_PAGO_TOKEN"))

def gerar_qr_code_pix(user_id):
    payment_data = {
        "transaction_amount": 5.00,
        "description": f"Pagamento Bot Mega-Sena - UID {user_id}",
        "payment_method_id": "pix",
        "payer": {"email": f"user{user_id}@example.com"}
    }
    payment_response = mp_client.payment().create(payment_data)
    payment = payment_response["response"]
    qr_code = payment["point_of_interaction"]["transaction_data"]["qr_code"]
    qr_base64 = payment["point_of_interaction"]["transaction_data"]["qr_code_base64"]
    payment_id = payment["id"]
    return payment_id, qr_code, qr_base64

def verificar_pagamento(payment_id):
    try:
        payment = mp_client.payment().get(payment_id)["response"]
        return payment["status"] == "approved"
    except:
        return False

def liberar_acesso(user_id):
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO acessos (user_id, liberado, data_pagamento)
            VALUES (?, 1, ?)
        """, (user_id, datetime.datetime.now().isoformat()))

def acesso_liberado(user_id):
    with get_db() as conn:
        r = conn.execute("SELECT liberado FROM acessos WHERE user_id = ?", (user_id,)).fetchone()
        return r and r[0] == 1

# Teclado principal

def teclado_principal():
    buttons = [
        [KeyboardButton("\u2795 Adicionar Jogo")],
        [KeyboardButton("\ud83d\udccb Listar Jogos")],
        [KeyboardButton("\u2705 Conferir Jogos (\u00daltimo Sorteio)")],
        [KeyboardButton("\ud83d\uddd5 Resultado por Concurso")],
        [KeyboardButton("\ud83d\udcc2 Conferir com Concurso Passado")],
        [KeyboardButton("\u274c Excluir Jogo")],
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

# Obter último resultado

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
        return "\u274c Erro ao obter o resultado da Mega-Sena."
    with get_db() as conn:
        jogos = conn.execute("SELECT id, dezenas FROM jogos WHERE user_id = ?", (uid,)).fetchall()
    if not jogos:
        return "Voc\u00ea n\u00e3o tem jogos cadastrados."

    texto = f"\ud83c\udfaf Resultado Mega-Sena #{concurso} - {data_sorteio}\nDezenas: {', '.join(dezenas_sorteadas)}\n"

    if premiacoes:
        texto += "\n\ud83c\udfc6 Premia\u00e7\u00e3o:\n"
        for p in premiacoes:
            faixa = p.get("descricaoFaixa")
            ganhadores = p.get("numeroDeGanhadores")
            valor = p.get("valorPremio")
            texto += f"\u27a1\ufe0f {faixa}: {ganhadores} ganhador(es) - R$ {float(valor):,.2f}\n"

    if acumulado:
        texto += f"\n\ud83d\udcc8 Acumulado pr\u00f3ximo concurso: R$ {float(acumulado):,.2f}\n"

    texto += "\n\ud83d\udcca Seus jogos:\n"
    for jid, dezenas_jogo in jogos:
        dezenas_jogo_list = dezenas_jogo.split(",")
        acertos = set(dezenas_jogo_list) & set(dezenas_sorteadas)
        emojis = {4: "\ud83d\udd38", 5: "\ud83d\udd37", 6: "\ud83d\udc8e"}.get(len(acertos), "\u2796")
        dezenas_formatadas = [f"{dez}\ud83c\udfaf" if dez in acertos else dez for dez in dezenas_jogo_list]
        texto += f"{emojis} Jogo #{jid}: {', '.join(dezenas_formatadas)} - Acertos: *{len(acertos)}*\n"

    return texto

# Bot Handlers

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "\ud83c\udf89 Ol\u00e1! Bem-vindo ao *Bot Mega-Sena*!\n\nUse o menu abaixo para come\u00e7ar.",
        reply_markup=teclado_principal(),
        parse_mode="Markdown"
    )
    user_states.pop(update.message.from_user.id, None)
    temp_data.pop(update.message.from_user.id, None)

async def comprar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id

    if acesso_liberado(uid):
        await update.message.reply_text("\u2705 Voc\u00ea j\u00e1 tem acesso liberado ao bot.")
        return

    payment_id, pix_code, qr_base64 = gerar_qr_code_pix(uid)
    temp_data[uid] = {"payment_id": payment_id}

    await update.message.reply_photo(
        photo=f"data:image/png;base64,{qr_base64}",
        caption="\ud83d\udcb5 Escaneie o QR Code PIX para pagar R$5,00.\n\nAguardando confirma\u00e7\u00e3o por 60 segundos...",
    )

    await asyncio.sleep(60)
    if verificar_pagamento(payment_id):
        liberar_acesso(uid)
        await update.message.reply_text("\u2705 Pagamento confirmado! Acesso liberado com sucesso.")
    else:
        await update.message.reply_text("\u274c Pagamento n\u00e3o confirmado. Tente novamente com /comprar.")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text.strip()

    # Bloqueio de funcionalidades até pagamento
    if text not in ["/start", "/comprar"] and not acesso_liberado(uid):
        await update.message.reply_text("\ud83d\udd12 Esta funcionalidade est\u00e1 dispon\u00edvel apenas ap\u00f3s o pagamento. Use /comprar.")
        return

    # Aqui seguem os handlers do seu código (Adicionar Jogo, Listar, etc.)
    await update.message.reply_text("\u2753 Comando n\u00e3o reconhecido. Use o menu abaixo.", reply_markup=teclado_principal())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("del:"):
        jid = int(query.data.split(":")[1])
        with get_db() as conn:
            conn.execute("DELETE FROM jogos WHERE id = ?", (jid,))
        await query.edit_message_text("\u2705 Jogo exclu\u00eddo com sucesso.")

# Main

if __name__ == "__main__":
    nest_asyncio.apply()
    async def main():
        print("\ud83d\udd04 Inicializando bot...")
        init_db()
        token = os.getenv("BOT_TOKEN")
        if not token:
            print("\u274c BOT_TOKEN n\u00e3o definido.")
            return
        app = ApplicationBuilder().token(token).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("comprar", comprar))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
        app.add_handler(CallbackQueryHandler(button_handler))
        print("\u2705 Bot rodando...")
        await app.run_polling()
    asyncio.run(main())
