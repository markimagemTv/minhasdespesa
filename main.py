import os
import asyncio
import logging
import mercadopago
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler
)

# Setup básico de logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# Dicionário para armazenar status de usuários pagos
usuarios_pagantes = set()

# Handler /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id in usuarios_pagantes:
        await update.message.reply_text("✅ Você já tem acesso ao bot!")
    else:
        keyboard = [
            [InlineKeyboardButton("💳 Pagar R$10 via PIX", callback_data="pagar_pix")]
        ]
        await update.message.reply_text(
            "👋 Olá! Para usar este bot, você precisa realizar um pagamento.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

# Callback do botão de pagamento
async def pagar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    # Criação de preferência Mercado Pago
    mp_token = os.getenv("MERCADO_PAGO_TOKEN")
    if not mp_token:
        await query.edit_message_text("❌ Erro: Token do Mercado Pago não configurado.")
        return

    mp_client = mercadopago.SDK(mp_token)

    preference_data = {
        "transaction_amount": 10,
        "description": "Acesso ao Bot Mega Sena",
        "payment_method_id": "pix",
        "payer": {
            "email": f"user{user_id}@email.com"
        }
    }

    try:
        preference = mp_client.payment().create(preference_data)
        qr_code_base64 = preference["response"]["point_of_interaction"]["transaction_data"]["qr_code_base64"]
        qr_code = preference["response"]["point_of_interaction"]["transaction_data"]["qr_code"]
        payment_id = preference["response"]["id"]

        # Envia QR code e instruções
        await query.edit_message_text(
            f"🧾 Escaneie o QR Code com seu app de banco ou copie e cole o código PIX abaixo:\n\n🔢 *Código:* `{qr_code}`\n\n⏳ Aguardando confirmação...",
            parse_mode="Markdown",
        )

        # (Opcional) Pode enviar imagem QR code como arquivo base64 se quiser.

        # Aguarda e simula verificação (60s)
        await asyncio.sleep(60)

        # Verificação fictícia: liberar acesso após tempo
        usuarios_pagantes.add(user_id)
        await context.bot.send_message(
            chat_id=user_id,
            text="✅ Pagamento confirmado! Agora você tem acesso completo ao bot."
        )

    except Exception as e:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"❌ Erro ao gerar pagamento: {e}"
        )

# Handler de mensagens comuns
async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in usuarios_pagantes:
        await update.message.reply_text("🚫 Você precisa pagar para usar o bot. Use /start.")
        return

    await update.message.reply_text("🎉 Você tem acesso! Mande sua aposta da Mega Sena aqui.")

# Função principal do bot
async def main():
    print("🔄 Inicializando bot...")

    bot_token = os.getenv("BOT_TOKEN")
    mp_token = os.getenv("MERCADO_PAGO_TOKEN")

    if not bot_token:
        raise ValueError("❌ BOT_TOKEN não definido no ambiente!")
    if not mp_token or not isinstance(mp_token, str):
        raise ValueError("❌ MERCADO_PAGO_TOKEN inválido ou ausente!")

    app = ApplicationBuilder().token(bot_token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(pagar_callback, pattern="^pagar_pix$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder))

    print("✅ Bot rodando. Aguardando mensagens...")
    await app.run_polling()

# Executa o bot
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"💥 Erro ao iniciar o bot: {e}")
