import os
import sqlite3
import datetime
import logging
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

# Configurando logging básico
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Estados e dados temporários (se precisar, aqui está vazio pois simplificado)
user_states = {}
temp_data = {}

# Teclado principal com botão inline para conferir jogos
def teclado_principal():
    buttons = [
        [KeyboardButton("🚀 Iniciar")],
        [KeyboardButton("➕ Adicionar Conta")],
        [KeyboardButton("✅ Marcar Conta como Paga")],
        [KeyboardButton("📊 Relatório Mensal")],
        [KeyboardButton("📅 Relatório por Mês")],
        [KeyboardButton("📝 Atualizar Conta")],
        [KeyboardButton("❌ Remover Conta")]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

# Mensagem inicial com teclado principal + botão inline "Conferir Jogos"
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Mensagem principal com ReplyKeyboard
    await update.message.reply_text(
        "👋 Olá! Bem-vindo ao Gerenciador de Despesas e Mega Sena!",
        reply_markup=teclado_principal()
    )
    # Logo após, enviar botão inline para Conferir Jogos
    await update.message.reply_text(
        "Quer conferir seus jogos no último sorteio? Clique no botão abaixo:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Conferir Jogos (Último Sorteio)", callback_data="conferir_jogos")]
        ])
    )
    user_states.pop(update.message.from_user.id, None)
    temp_data.pop(update.message.from_user.id, None)

# Função dummy para conferir jogos (substitua pela sua lógica real)
async def conferir_jogos(uid: int) -> str:
    logger.info(f"Conferindo jogos para o usuário {uid}...")
    # Aqui você faria requisição à API oficial da loterias caixa, por exemplo
    # Retorno simulado:
    return (
        "🎉 *Resultado da Mega Sena*\n\n"
        "Conferimos seus jogos do último sorteio e...\n"
        "Você ganhou R$ 0,00 😅\n"
        "_(Esta é uma simulação, implemente a lógica real)_"
    )

# Handler para callbacks dos botões inline
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = query.from_user.id

    if data == "conferir_jogos":
        try:
            texto_resultado = await conferir_jogos(uid)
            await query.edit_message_text(texto_resultado, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Erro ao conferir jogos para usuário {uid}: {e}")
            await query.edit_message_text(f"❌ Erro ao conferir jogos: {e}")

# Handler para mensagens de texto (exemplo simples, você pode expandir)
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    texto = update.message.text.strip()
    logger.info(f"Usuário {uid} enviou texto: '{texto}'")

    if texto == "🚀 Iniciar":
        await start(update, context)
    else:
        await update.message.reply_text("Use os botões para navegar pelo bot.")

# Execução principal Railway-safe
if __name__ == "__main__":
    nest_asyncio.apply()

    async def main():
        logger.info("🔄 Inicializando bot...")
        token = os.getenv("BOT_TOKEN")
        if not token:
            logger.error("❌ BOT_TOKEN não encontrado nas variáveis de ambiente.")
            return
        app = ApplicationBuilder().token(token).build()

        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
        app.add_handler(CallbackQueryHandler(button_handler))

        logger.info("✅ Bot iniciado e aguardando mensagens...")
        await app.run_polling()

    asyncio.get_event_loop().run_until_complete(main())
