import sqlite3
import datetime
import asyncio
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.update import Update

TOKEN = "7215000074:AAHbJ1V0vJsdLzCfeK4dMK-1el5qF-cPTQ"
user_states = {}
temp_data = {}

def init_db():
    conn = sqlite3.connect("despesas.db")
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS contas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT,
            valor REAL,
            vencimento TEXT,
            status TEXT,
            tipo TEXT,
            parcelas_restantes INTEGER
        )
    ''')
    conn.commit()
    conn.close()

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Olá! Bem-vindo ao Gerenciador de Despesas.",
        reply_markup=teclado_principal()
    )
    user_states.pop(update.message.from_user.id, None)
    temp_data.pop(update.message.from_user.id, None)

async def relatorio_mensal(update: Update):
    hoje = datetime.date.today()
    await relatorio_por_mes(update, hoje.month, hoje.year)

async def relatorio_por_mes(update: Update, mes: int, ano: int):
    mes_str = f"{mes:02d}"
    ano_str = str(ano)
    conn = sqlite3.connect("despesas.db")
    c = conn.cursor()
    c.execute("SELECT descricao, valor, vencimento, status FROM contas WHERE strftime('%m', vencimento) = ? AND strftime('%Y', vencimento) = ? ORDER BY vencimento", (mes_str, ano_str))
    contas = c.fetchall()
    conn.close()

    if not contas:
        await update.message.reply_text(f"📊 Nenhuma conta encontrada para {mes_str}/{ano_str}.")
        return

    texto = f"📊 Contas de {mes_str}/{ano_str}:\n\n"
    total_pagas = 0
    total_pendentes = 0
    for desc, val, venc, status in contas:
        emoji = "✅" if status == "paga" else "⏳"
        texto += f"{emoji} {desc} - R$ {val:.2f} - Vencimento: {venc}\n-----------\n"
        if status == "paga":
            total_pagas += val
        else:
            total_pendentes += val

    texto += f"\n💰 Total pago: R$ {total_pagas:.2f}\n⌛ Total pendente: R$ {total_pendentes:.2f}"
    await update.message.reply_text(texto)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    texto = update.message.text

    if texto == "🚀 Iniciar":
        await start(update, context)
        return

    if texto == "➕ Adicionar Conta":
        user_states[uid] = "descricao"
        temp_data[uid] = {}
        await update.message.reply_text("Digite a descrição da conta:")
        return

    if texto == "✅ Marcar Conta como Paga":
        conn = sqlite3.connect("despesas.db")
        c = conn.cursor()
        c.execute("SELECT id, descricao FROM contas WHERE status = 'pendente'")
        contas = c.fetchall()
        conn.close()
        if not contas:
            await update.message.reply_text("Nenhuma conta pendente encontrada.")
            return
        keyboard = [[InlineKeyboardButton(desc, callback_data=f"pagar_{idc}")] for idc, desc in contas]
        await update.message.reply_text("Selecione a conta paga:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if texto == "📊 Relatório Mensal":
        await relatorio_mensal(update)
        return

    if texto == "📅 Relatório por Mês":
        user_states[uid] = "relatorio_mes"
        await update.message.reply_text("Digite o mês e o ano (mm/aaaa):")
        return

    if texto == "❌ Remover Conta":
        conn = sqlite3.connect("despesas.db")
        c = conn.cursor()
        c.execute("SELECT id, descricao FROM contas")
        contas = c.fetchall()
        conn.close()
        if not contas:
            await update.message.reply_text("Nenhuma conta encontrada.")
            return
        keyboard = [[InlineKeyboardButton(desc, callback_data=f"remover_{idc}")] for idc, desc in contas]
        await update.message.reply_text("Selecione a conta a remover:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if texto == "📝 Atualizar Conta":
        conn = sqlite3.connect("despesas.db")
        c = conn.cursor()
        c.execute("SELECT id, descricao FROM contas")
        contas = c.fetchall()
        conn.close()
        if not contas:
            await update.message.reply_text("Nenhuma conta encontrada.")
            return
        keyboard = [[InlineKeyboardButton(desc, callback_data=f"atualizar_{idc}")] for idc, desc in contas]
        await update.message.reply_text("Selecione a conta a atualizar:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    estado = user_states.get(uid)

    if estado == "relatorio_mes":
        try:
            mes, ano = map(int, texto.split("/"))
            await relatorio_por_mes(update, mes, ano)
        except:
            await update.message.reply_text("Formato inválido. Use mm/aaaa.")
        user_states.pop(uid, None)
        return

    elif estado == "descricao":
        temp_data[uid]["descricao"] = texto
        user_states[uid] = "valor"
        await update.message.reply_text("Digite o valor (ex: 1234,56):")
        return

    elif estado == "valor":
        try:
            valor = float(texto.replace(",", "."))
            temp_data[uid]["valor"] = valor
            user_states[uid] = "vencimento"
            await update.message.reply_text("Digite o vencimento (dd/mm/aaaa):")
        except:
            await update.message.reply_text("Valor inválido. Use o formato 1234,56.")
        return

    elif estado == "vencimento":
        try:
            data = datetime.datetime.strptime(texto, "%d/%m/%Y").date()
            temp_data[uid]["vencimento"] = data.isoformat()
            user_states[uid] = "tipo_conta"
            await update.message.reply_text("Essa conta é:", reply_markup=ReplyKeyboardMarkup([["Simples", "Parcelada", "Repetir Semanal", "Repetir Mensal"]], resize_keyboard=True))
        except:
            await update.message.reply_text("Data inválida. Use o formato dd/mm/aaaa.")
        return

    elif estado == "tipo_conta":
        tipo = texto.lower()
        if tipo == "parcelada":
            user_states[uid] = "parcelas"
            temp_data[uid]["tipo"] = "parcelada"
            await update.message.reply_text("Quantas parcelas?")
        elif tipo == "repetir semanal":
            temp_data[uid]["tipo"] = "semanal"
            temp_data[uid]["parcelas"] = 52
            await salvar_contas_repetidas(uid, update)
        elif tipo == "repetir mensal":
            temp_data[uid]["tipo"] = "mensal"
            temp_data[uid]["parcelas"] = 12
            await salvar_contas_repetidas(uid, update)
        else:
            temp_data[uid]["tipo"] = "simples"
            conn = sqlite3.connect("despesas.db")
            c = conn.cursor()
            c.execute("INSERT INTO contas (descricao, valor, vencimento, status, tipo, parcelas_restantes) VALUES (?, ?, ?, 'pendente', ?, NULL)",
                      (temp_data[uid]["descricao"], temp_data[uid]["valor"], temp_data[uid]["vencimento"], temp_data[uid]["tipo"]))
            conn.commit()
            conn.close()
            await update.message.reply_text("💾 Conta adicionada com sucesso!", reply_markup=teclado_principal())
            user_states.pop(uid, None)
            temp_data.pop(uid, None)
        return

    elif estado == "parcelas":
        try:
            parcelas = int(texto)
            temp_data[uid]["parcelas"] = parcelas
            temp_data[uid]["tipo"] = "parcelada"
            await salvar_contas_repetidas(uid, update)
        except:
            await update.message.reply_text("Número inválido de parcelas.")
        return

async def salvar_contas_repetidas(uid, update):
    tipo = temp_data[uid]["tipo"]
    parcelas = temp_data[uid]["parcelas"]
    data = datetime.datetime.fromisoformat(temp_data[uid]["vencimento"])
    conn = sqlite3.connect("despesas.db")
    c = conn.cursor()
    for i in range(parcelas):
        venc = data + datetime.timedelta(weeks=i) if tipo == "semanal" else data + datetime.timedelta(days=30*i)
        c.execute("INSERT INTO contas (descricao, valor, vencimento, status, tipo, parcelas_restantes) VALUES (?, ?, ?, 'pendente', ?, ?)",
                  (temp_data[uid]["descricao"], temp_data[uid]["valor"], venc.date().isoformat(), tipo, parcelas - i))
    conn.commit()
    conn.close()
    await update.message.reply_text("💾 Conta adicionada com sucesso!", reply_markup=teclado_principal())
    user_states.pop(uid, None)
    temp_data.pop(uid, None)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

    if data.startswith("remover_"):
        idc = int(data.split("_")[1])
        conn = sqlite3.connect("despesas.db")
        c = conn.cursor()
        c.execute("DELETE FROM contas WHERE id = ?", (idc,))
        conn.commit()
        conn.close()
        await query.edit_message_text("🗑️ Conta removida com sucesso!")

    elif data.startswith("atualizar_"):
        idc = int(data.split("_")[1])
        temp_data[uid] = {"id": idc}
        user_states[uid] = "update_valor"
        await query.edit_message_text("Digite o novo valor da conta:")

    elif data.startswith("pagar_"):
        idc = int(data.split("_")[1])
        conn = sqlite3.connect("despesas.db")
        c = conn.cursor()
        c.execute("UPDATE contas SET status = 'paga' WHERE id = ?", (idc,))
        conn.commit()
        conn.close()
        await query.edit_message_text("✅ Conta marcada como paga!")

async def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Bot rodando...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
