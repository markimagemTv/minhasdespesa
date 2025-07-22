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
        [KeyboardButton("📂 Conferir com Concurso Passado")],
        [KeyboardButton("📈 Premiação do Último Sorteio")],
        [KeyboardButton("❌ Excluir Jogo")],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

# Validação das dezenas
def validar_dezenas(texto):
    try:
        nums = [int(d) for d in texto.replace(" ", "").split(",")]
        if len(nums) != 6 or any(not (1 <= n <= 60) for n in nums):
            return None
        if len(set(nums)) != 6:
            return None
        return sorted(nums)
    except:
        return None

# API da Caixa para último resultado
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

# Resultado por concurso
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

# Função para exibir premiação do último sorteio
async def exibir_premiacao_ultima():
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
                    return "❌ Erro ao buscar a premiação."
                data = await resp.json(content_type=None)
                
                concurso = data.get("numero")
                data_sorteio = data.get("dataApuracao")
                dezenas = data.get("listaDezenasSorteadasOrdemSorteio") or data.get("listaDezenas")
                acumulado = data.get("acumulado", False)
                valor_acumulado = float(data.get("valorAcumuladoConcursoEspecial", 0.0))
                premiacoes = data.get("listaRateioPremio", [])

                texto = f"🎯 *Mega-Sena #{concurso} - {data_sorteio}*\n"
                texto += f"Dezenas sorteadas: {', '.join(dezenas)}\n"
                texto += f"Acumulou? {'✅ Sim' if acumulado else '❌ Não'}\n"
                if valor_acumulado:
                    texto += f"Valor acumulado p/ próximo concurso: *R$ {valor_acumulado:,.2f}*\n\n"

                texto += "💰 *Premiação:*\n"
                for faixa in premiacoes:
                    texto += f"- {faixa['descricaoFaixa']}: {faixa['numeroDeGanhadores']} ganhadores - R$ {float(faixa['valorPremio']):,.2f}\n"

                return texto
    except Exception as e:
        return f"❌ Erro ao processar a premiação: {str(e)}"

# Função para premiação por concurso
async def premiacao_por_concurso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("❗ Use: /premiacao <número_do_concurso>")
        return

    concurso = context.args[0]
    url = f"https://servicebus2.caixa.gov.br/portaldeloterias/api/megasena/{concurso}"
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
                    await update.message.reply_text("❌ Concurso não encontrado.")
                    return
                data = await resp.json(content_type=None)
                
                dezenas = data.get("listaDezenasSorteadasOrdemSorteio") or data.get("listaDezenas")
                data_sorteio = data.get("dataApuracao")
                acumulado = data.get("acumulado", False)
                valor_acumulado = float(data.get("valorAcumuladoConcursoEspecial", 0.0))
                premiacoes = data.get("listaRateioPremio", [])

                texto = f"🎯 *Mega-Sena #{concurso} - {data_sorteio}*\n"
                texto += f"Dezenas sorteadas: {', '.join(dezenas)}\n"
                texto += f"Acumulou? {'✅ Sim' if acumulado else '❌ Não'}\n"
                if valor_acumulado:
                    texto += f"Valor acumulado p/ próximo concurso: *R$ {valor_acumulado:,.2f}*\n\n"

                texto += "💰 *Premiação:*\n"
                for faixa in premiacoes:
                    texto += f"- {faixa['descricaoFaixa']}: {faixa['numeroDeGanhadores']} ganhadores - R$ {float(faixa['valorPremio']):,.2f}\n"

                await update.message.reply_text(texto, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao buscar dados: {str(e)}")

# Handler principal de mensagens
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
        msg = "📋 *Seus Jogos:*\n\n"
        for idj, dezenas, data_cad in jogos:
            data_fmt = datetime.datetime.fromisoformat(data_cad).strftime("%d/%m/%Y %H:%M")
            msg += f"#{idj}: {dezenas} (cadastrado em {data_fmt})\n"
        await update.message.reply_text(msg, parse_mode="Markdown")

    elif texto == "✅ Conferir Jogos (Último Sorteio)":
        texto_resultado = await conferir_jogos(uid)
        await update.message.reply_text(texto_resultado, parse_mode="Markdown")

    elif texto == "📈 Premiação do Último Sorteio":
        texto_resultado = await exibir_premiacao_ultima()
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
                texto = f"🎯 Resultado #{concurso} - {data_sorteio}\nDezenas: {', '.join(dezenas_sorteadas)}\n\n"
                for jid, dezenas_jogo in jogos:
                    dezenas_jogo_list = dezenas_jogo.split(",")
                    dezenas_formatadas = [f"✅{d}" if d in dezenas_sorteadas else d for d in dezenas_jogo_list]
                    acertos = set(dezenas_jogo_list) & set(dezenas_sorteadas)
                    count_acertos = len(acertos)
                    emoji = " 🏆" if count_acertos == 6 else " 🥳" if count_acertos == 5 else " 🎉" if count_acertos == 4 else ""
                    texto += f"Jogo #{jid}: {', '.join(dezenas_formatadas)} - Acertos: *{count_acertos}*{emoji}\n"
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
    texto = f"🎯 Resultado Mega-Sena #{concurso} - {data_sorteio}\nDezenas: {', '.join(dezenas_sorteadas)}\n\n"
    for jid, dezenas_jogo in jogos:
        dezenas_jogo_list = dezenas_jogo.split(",")
        dezenas_formatadas = [f"✅{d}" if d in dezenas_sorteadas else d for d in dezenas_jogo_list]
        acertos = set(dezenas_jogo_list) & set(dezenas_sorteadas)
        count_acertos = len(acertos)
        emoji = " 🏆" if count_acertos == 6 else " 🥳" if count_acertos == 5 else " 🎉" if count_acertos == 4 else ""
        texto += f"Jogo #{jid}: {', '.join(dezenas_formatadas)} - Acertos: *{count_acertos}*{emoji}\n"
    return texto

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
        app.add_handler(CommandHandler("premiacao", premiacao_por_concurso))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
        app.add_handler(CallbackQueryHandler(button_handler))
        print("✅ Bot rodando...")
        await app.run_polling()

    asyncio.run(main())
