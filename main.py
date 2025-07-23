import os
import sqlite3
import datetime
import aiohttp
import nest_asyncio
import asyncio
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

# Usuários que já pagaram (em memória, pode ser salvo em banco para persistência)
usuarios_pagantes = set()

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
        dezenas_formatadas = [f"{dez}🎯" if dez in acertos else dez for dez in dezenas_jogo_list]
        texto += f"{emojis} Jogo #{jid}: {', '.join(dezenas_formatadas)} - Acertos: *{len(acertos)}*\n"

    return texto

# --- NOVO: Pagamento Mercado Pago ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid in usuarios_pagantes:
        await update.message.reply_text(
            "✅ Você já possui acesso ao bot.\nUse o menu abaixo para continuar.",
            reply_markup=teclado_principal()
        )
        user_states.pop(uid, None)
        temp_data.pop(uid, None)
    else:
        keyboard = [
            [InlineKeyboardButton("💳 Pagar R$5 via PIX", callback_data="pagar_pix")]
        ]
        await update.message.reply_text(
            "👋 Olá! Para acessar o bot, é necessário realizar um pagamento de R$5 via PIX.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        user_states.pop(uid, None)
        temp_data.pop(uid, None)

async def pagar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    mp_token = os.getenv("MERCADO_PAGO_TOKEN")
    if not mp_token:
        await query.edit_message_text("❌ Token Mercado Pago não configurado no ambiente.")
        return

    mp_client = mercadopago.SDK(mp_token)

    payment_data = {
        "transaction_amount": 5.00,
        "description": "Acesso ao Bot Mega-Sena",
        "payment_method_id": "pix",
        "payer": {
            "email": f"user{uid}@example.com"
        }
    }

    try:
        payment_response = mp_client.payment().create(payment_data)
        payment = payment_response["response"]
        qr_code = payment.get("point_of_interaction", {}).get("transaction_data", {}).get("qr_code")
        qr_code_base64 = payment.get("point_of_interaction", {}).get("transaction_data", {}).get("qr_code_base64")

        if not qr_code:
            await query.edit_message_text("❌ Não foi possível gerar o QR Code do pagamento.")
            return

        texto_pix = f"""
📲 Escaneie o QR Code abaixo com seu app bancário para pagar:

🔢 Código PIX:
`{qr_code}`

⏳ Aguardando confirmação do pagamento...
"""
        await query.edit_message_text(texto_pix, parse_mode="Markdown")

        # Aqui você pode implementar a verificação real via webhook ou polling.
        # Para exemplo, aguarda 60 segundos e libera acesso.

        await asyncio.sleep(60)

        # Simular confirmação
        usuarios_pagantes.add(uid)
        await context.bot.send_message(
            chat_id=uid,
            text="✅ Pagamento confirmado! Agora você tem acesso completo ao bot.",
            reply_markup=teclado_principal()
        )

    except Exception as e:
        await context.bot.send_message(chat_id=uid, text=f"❌ Erro ao gerar pagamento: {e}")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text.strip()

    # Controle de acesso
    if uid not in usuarios_pagantes:
        await update.message.reply_text(
            "🚫 Você precisa realizar o pagamento para acessar o bot. Use /start para iniciar o pagamento."
        )
        return

    # Seu código atual de message_handler segue abaixo:

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
            await update.message.reply_text(
                f"📅 Resultado Mega-Sena #{text} - {data_sorteio}\nDezenas: {', '.join(dezenas)}"
            )
        user_states.pop(uid, None)

    elif user_states.get(uid) == "aguardando_concurso_conferencia" and text.isdigit():
        concurso_num = int(text)
        dezenas_sorteadas, data_sorteio = await obter_resultado_concurso(concurso_num)
        if not dezenas_sorteadas:
            await update.message.reply_text("❌ Concurso não encontrado.")
            user_states.pop(uid, None)
            return

        with get_db() as conn:
            jogos = conn.execute("SELECT id, dezenas FROM jogos WHERE user_id = ?", (uid,)).fetchall()
        if not jogos:
            await update.message.reply_text("Você não tem jogos cadastrados.")
            user_states.pop(uid, None)
            return

        texto = f"🎯 Resultado Mega-Sena #{concurso_num} - {data_sorteio}\nDezenas: {', '.join(dezenas_sorteadas)}\n"
        texto += "\n📊 Seus jogos:\n"
        for jid, dezenas_jogo in jogos:
            dezenas_jogo_list = dezenas_jogo.split(",")
            acertos = set(dezenas_jogo_list) & set(dezenas_sorteadas)
            emojis = {4: "🔸", 5: "🔷", 6: "💎"}.get(len(acertos), "➖")
            dezenas_formatadas = [f"{dez}🎯" if dez in acertos else dez for dez in dezenas_jogo_list]
            texto += f"{emojis} Jogo #{jid}: {', '.join(dezenas_formatadas)} - Acertos: *{len(acertos)}*\n"

        await update.message.reply_text(texto, parse_mode="Markdown")
        user_states.pop(uid, None)

    else:
        await update.message.reply_text("Comando não reconhecido. Use o menu abaixo.", reply_markup=teclado_principal())

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

    if data == "pagar_pix":
        await pagar_callback(update, context)
        return

    if data.startswith("del:"):
        jogo_id = int(data.split(":")[1])
        with get_db() as conn:
            conn.execute("DELETE FROM jogos WHERE id = ? AND user_id = ?", (jogo_id, uid))
        await query.edit_message_text(f"🗑️ Jogo #{jogo_id} excluído com sucesso.")

# Inicialização do bot

def main():
    init_db()
    token = os.getenv("BOT_TOKEN")
    if not token:
        print("❌ TELEGRAM_TOKEN não configurado no ambiente.")
        return

    application = ApplicationBuilder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), message_handler))
    application.add_handler(CallbackQueryHandler(callback_handler))

    print("Bot iniciado!")
    application.run_polling()

if __name__ == "__main__":
    nest_asyncio.apply()
    main()
