import os
import json
import sqlite3
import threading
import logging
import requests
import nest_asyncio
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)
from flask import Flask

TOKEN = "8046819996:AAFaaJPorHCjNRWmHzyW2CWG69g1cqWnNaM"
ADMIN_ID = 1460561546
DB_PATH = 'jogos.db'

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

nest_asyncio.apply()

cache_resultado = {'data': None, 'resultado': None, 'concurso': None, 'cache_time': None, 'manual': False}
CACHE_TTL = timedelta(minutes=10)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS jogos (id INTEGER PRIMARY KEY AUTOINCREMENT, numeros TEXT NOT NULL)''')
    conn.commit()
    conn.close()

def carregar_jogos():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, numeros FROM jogos ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()
    jogos = []
    for id_, numeros_json in rows:
        try:
            numeros = json.loads(numeros_json)
            jogos.append((id_, numeros))
        except json.JSONDecodeError:
            logger.warning(f"Jogo com id {id_} inválido.")
    return jogos

def salvar_jogo(numeros):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO jogos (numeros) VALUES (?)", (json.dumps(numeros),))
    conn.commit()
    conn.close()

def remover_jogo(id_):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM jogos WHERE id = ?", (id_,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def validar_numeros(texto):
    try:
        numeros = sorted(int(n) for n in texto.strip().split())
        if len(numeros) != 6 or any(n < 1 or n > 60 for n in numeros):
            return None
        return numeros
    except Exception:
        return None

def obter_resultado_megasena(concurso=None):
    now = datetime.now()
    if cache_resultado['cache_time'] and (now - cache_resultado['cache_time']) < CACHE_TTL and concurso is None:
        return { 'numeros': cache_resultado['resultado'], 'concurso': cache_resultado['concurso'], 'data': cache_resultado['data'] }
    url = f'https://loteriascaixa-api.herokuapp.com/api/megasena/{concurso}' if concurso else 'https://loteriascaixa-api.herokuapp.com/api/megasena/latest'
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        resultado = sorted(int(d) for d in data['dezenas'])
        concurso_resp = data['concurso']
        data_resp = data['data']
        if not cache_resultado.get('manual', False):
            cache_resultado.update({'resultado': resultado, 'concurso': concurso_resp, 'data': data_resp, 'cache_time': now, 'manual': False})
        return { 'numeros': resultado, 'concurso': concurso_resp, 'data': data_resp }
    except requests.RequestException as e:
        logger.error(f"Erro API Mega-Sena: {e}")
        raise

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard_inline = [
        [InlineKeyboardButton("➕ Adicionar jogo", callback_data='add'), InlineKeyboardButton("❌ Remover jogo", callback_data='remove')],
        [InlineKeyboardButton("📋 Listar jogos", callback_data='list'), InlineKeyboardButton("🎯 Conferir rápido", callback_data='check')],
        [InlineKeyboardButton("📅 Conferir antigos", callback_data='check_past'), InlineKeyboardButton("🖊 Manual", callback_data='manual_result')],
        [InlineKeyboardButton("💰 Próximo prêmio", callback_data='next_prize')]
    ] if user_id == ADMIN_ID else [
        [InlineKeyboardButton("📋 Listar jogos", callback_data='list'), InlineKeyboardButton("🎯 Conferir", callback_data='check')],
        [InlineKeyboardButton("📅 Conferir antigos", callback_data='check_past')],
        [InlineKeyboardButton("💰 Próximo prêmio", callback_data='next_prize')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard_inline)
    keyboard_reply = ReplyKeyboardMarkup([[KeyboardButton("/start")], [KeyboardButton("/cancel")]], resize_keyboard=True)
    await update.message.reply_text("📲 Escolha uma opção:", reply_markup=reply_markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if query.data == 'add':
        if user_id != ADMIN_ID:
            await query.edit_message_text("🚫 Apenas admin.")
            return
        await query.edit_message_text("✍️ Envie 6 dezenas separadas por espaço.")
        context.user_data.update({'esperando_jogo': True})
    elif query.data == 'manual_result':
        if user_id != ADMIN_ID:
            await query.edit_message_text("🚫 Apenas admin.")
            return
        await query.edit_message_text("🖊 Envie os 6 números sorteados manualmente.")
        context.user_data.update({'esperando_resultado_manual': True})
    elif query.data == 'list':
        jogos = carregar_jogos()
        if not jogos:
            await query.edit_message_text("📭 Nenhum jogo salvo.")
            return
        texto = "\n".join([f"{i+1}: {' '.join(f'{d:02}' for d in jogo[1])}" for i, jogo in enumerate(jogos)])
        await query.edit_message_text(f"📋 Jogos:\n{texto}")
    elif query.data == 'check':
        try:
            dados = obter_resultado_megasena()
        except Exception:
            await query.edit_message_text("⚠️ Erro ao obter resultado.")
            return
        resultado, concurso, data = dados['numeros'], dados['concurso'], dados['data']
        jogos = carregar_jogos()
        if not jogos:
            await query.edit_message_text("📭 Nenhum jogo salvo.")
            return
        texto = f"🎱 Concurso {concurso} - {data}\nResultado: {' '.join(f'{d:02}' for d in resultado)}\n\n"
        for i, jogo in enumerate(jogos):
            acertos = set(jogo[1]) & set(resultado)
            texto += f"Jogo {i+1}: {' '.join(f'✅{d:02}' if d in acertos else f'{d:02}' for d in jogo[1])} → {len(acertos)} acertos\n"
        await query.edit_message_text(texto)
    elif query.data == 'next_prize':
        try:
            response = requests.get('https://loteriascaixa-api.herokuapp.com/api/megasena/latest', timeout=10)
            response.raise_for_status()
            data = response.json()
            estimativa = data.get('valor_estimado_proximo_concurso')
            acumulado = data.get('acumulado', False)

            if estimativa:
                valor = f"R$ {float(estimativa):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                texto = f"💰 *Próximo prêmio estimado*: {valor}"
                if acumulado:
                    texto += "\n🎯 *Acumulado!*"
            else:
                texto = "❌ Não foi possível obter a estimativa do próximo prêmio."

            await query.edit_message_text(texto, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Erro ao buscar próximo prêmio: {e}")
            await query.edit_message_text("⚠️ Erro ao buscar o próximo prêmio.")

async def mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    user_id = update.effective_user.id
    if texto.lower() == '/cancel':
        context.user_data.clear()
        await update.message.reply_text("❌ Cancelado. Use /start.")
        return
    if context.user_data.get('esperando_jogo'):
        if user_id != ADMIN_ID:
            await update.message.reply_text("🚫 Apenas admin.")
            return
        numeros = validar_numeros(texto)
        if not numeros:
            await update.message.reply_text("❌ Envie 6 dezenas válidas.")
            return
        salvar_jogo(numeros)
        context.user_data.clear()
        await update.message.reply_text(f"✅ Jogo adicionado: {' '.join(f'{d:02}' for d in numeros)}")
    elif context.user_data.get('esperando_resultado_manual'):
        if user_id != ADMIN_ID:
            await update.message.reply_text("🚫 Apenas admin.")
            return
        numeros = validar_numeros(texto)
        if not numeros:
            await update.message.reply_text("❌ Envie 6 dezenas válidas.")
            return
        cache_resultado.update({
            'resultado': numeros, 'concurso': "MANUAL",
            'data': datetime.now().strftime("%d/%m/%Y %H:%M"),
            'cache_time': datetime.now(), 'manual': True
        })
        context.user_data.clear()
        await update.message.reply_text(f"✅ Resultado manual atualizado: {' '.join(f'{d:02}' for d in numeros)}")
    else:
        await update.message.reply_text("👋 Use /start para menu.")

flask_app = Flask(__name__)

@flask_app.route('/')
def index(): return "✅ Bot online."

def run_flask(): flask_app.run(host='0.0.0.0', port=5000)

def iniciar_bot():
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", mensagem))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mensagem))
    logger.info("🤖 Bot iniciado")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    iniciar_bot()
