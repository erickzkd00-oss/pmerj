import os
import json
import sqlite3
import asyncio
import shutil
import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone

TOKEN = os.getenv("TOKEN")

CANAL_ANALISE_ID = 1509987335301763143
CANAL_LOGS_ID = 1509989451625922671
CANAL_BACKUP_ID = 1509989572803821658

CATEGORIA_OUVIDORIA_ID = 1511074752112885770

# BATE PONTO
CANAL_PAINEL_ID = 1501711518746808441
CANAL_ANTIBURLA_ID = 1501729022932029553
CANAL_PONTO_LOGS_ID = 1501740594857381968
CATEGORIA_PONTO_ID = 1501720358317850704
CATEGORIA_CALLS_ID = 1501740879965192192

ID_CARGO_PM = 1499094987017683045
ID_CARGO_META_INCOMPLETA = 1501712422719717476
ID_CARGO_AUSENCIA = 1501712362678521966
ID_CARGO_META_REDUZIDA = 1502035606346399744

META_MINUTOS = 480
MAX_PONTO_HORAS = 8
AVISO_ANTIBURLA_MINUTOS = 15

IMG_BATEPONTO = "https://media.discordapp.net/attachments/1016489520876752907/1501711374034927776/45dc5029-5539-4620-9d6e-957c5e764372.png?ex=69fd1134&is=69fbbfb4&hm=9c6d9ef9f4e7c7963750367b1e5697250f0a69e41faa0415aa159f09cc549c9a&=&format=webp&quality=lossless&width=972&height=238"

ID_CARGO_POLICIA_MILITAR = 1499094987017683045
ID_CARGO_CPO = 1511076659200135282
ID_CARGO_2_SOLDADO = 1499094987017683045
ID_CARGO_22BPM = 1509990614689906830

IMG_REGISTRO = "https://media.discordapp.net/attachments/1016489520876752907/1500688190036508813/0250a150-0046-4657-8b9e-1cac6011e545.png?ex=69f95849&is=69f806c9&hm=b5b404c8a841fdad9d658c6ec805717c9d259c520d6ba3edbfd25852877891e0&=&format=webp&quality=lossless&width=972&height=239"
IMG_OUVIDORIA = "https://cdn.discordapp.com/attachments/1016489520876752907/1500703408431042691/e0a848fb-c307-4ca5-b45c-90e28fa46406.png?ex=69f96676&is=69f814f6&hm=072bd2e04567f1a7df6c0c0768f5d053235dc42f33dbbbf08769ab82c7c57124&"

ARQUIVO_CONFIG = "config_principal.json"
DB_FILE = "dados.db"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix=";", intents=intents)


# ================= SQLITE =================

conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS ponto_totais (
    user_id INTEGER PRIMARY KEY,
    total_seconds INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS pontos_abertos (
    owner_id INTEGER PRIMARY KEY,
    channel_id INTEGER,
    start_ts INTEGER,
    voice_channel_id INTEGER,
    closed INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS ponto_membros (
    owner_id INTEGER,
    user_id INTEGER,
    valid_seconds INTEGER DEFAULT 0,
    in_voice_since INTEGER,
    out_since INTEGER,
    warned INTEGER DEFAULT 0,
    PRIMARY KEY(owner_id, user_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS ponto_relatorios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER,
    members TEXT,
    start_ts INTEGER,
    end_ts INTEGER,
    total_seconds INTEGER,
    relatorio TEXT
)
""")

conn.commit()


def db_commit():
    conn.commit()


def agora_ts():
    return int(datetime.now(timezone.utc).timestamp())


def formatar_tempo(segundos):
    segundos = max(0, int(segundos))
    horas = segundos // 3600
    minutos = (segundos % 3600) // 60
    return f"{horas}h {minutos}min"


def total_user(user_id):
    cursor.execute("SELECT total_seconds FROM ponto_totais WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else 0


def add_horas(user_id, segundos):
    atual = total_user(user_id)
    novo = atual + int(segundos)
    cursor.execute(
        "INSERT OR REPLACE INTO ponto_totais (user_id, total_seconds) VALUES (?, ?)",
        (user_id, novo)
    )
    db_commit()


def usuario_tem_ponto(user_id):
    cursor.execute("SELECT owner_id FROM ponto_membros WHERE user_id = ?", (user_id,))
    return cursor.fetchone() is not None


def buscar_ponto_por_canal(channel_id):
    cursor.execute(
        "SELECT owner_id, channel_id, start_ts, voice_channel_id, closed FROM pontos_abertos WHERE channel_id = ?",
        (channel_id,)
    )
    return cursor.fetchone()


def buscar_ponto_por_owner(owner_id):
    cursor.execute(
        "SELECT owner_id, channel_id, start_ts, voice_channel_id, closed FROM pontos_abertos WHERE owner_id = ?",
        (owner_id,)
    )
    return cursor.fetchone()


def membros_do_ponto(owner_id):
    cursor.execute("SELECT user_id FROM ponto_membros WHERE owner_id = ?", (owner_id,))
    return [r[0] for r in cursor.fetchall()]


def membros_estado_do_ponto(owner_id):
    cursor.execute("""
        SELECT user_id, valid_seconds, in_voice_since, out_since, warned
        FROM ponto_membros WHERE owner_id = ?
    """, (owner_id,))
    return cursor.fetchall()


def remover_ponto(owner_id):
    cursor.execute("DELETE FROM pontos_abertos WHERE owner_id = ?", (owner_id,))
    cursor.execute("DELETE FROM ponto_membros WHERE owner_id = ?", (owner_id,))
    db_commit()


def segundos_validos_atuais(user_id, agora=None):
    if agora is None:
        agora = agora_ts()

    cursor.execute("""
        SELECT valid_seconds, in_voice_since
        FROM ponto_membros WHERE user_id = ?
    """, (user_id,))
    row = cursor.fetchone()
    if not row:
        return 0

    valid_seconds, in_voice_since = row
    total = valid_seconds or 0
    if in_voice_since:
        total += max(0, agora - in_voice_since)
    return total
# ================= CONFIG JSON =================

def carregar_config():
    if not os.path.exists(ARQUIVO_CONFIG):
        dados = {
            "registros_abertos": True,
            "registros_pendentes": [],
            "cargos_analise": [],
            "cargos_moderacao": [],
            "ouvidoria_abertos": {}
        }
        salvar_config(dados)
        return dados

    with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as f:
        dados = json.load(f)

    dados.setdefault("registros_abertos", True)
    dados.setdefault("registros_pendentes", [])
    dados.setdefault("cargos_analise", [])
    dados.setdefault("cargos_moderacao", [])
    dados.setdefault("ouvidoria_abertos", {})

    salvar_config(dados)
    return dados


def salvar_config(dados):
    with open(ARQUIVO_CONFIG, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=4)


config = carregar_config()


# ================= FUNÇÕES GERAIS =================

def rodape(embed):
    embed.set_footer(text="© Polícia Militar do Estado do Rio de Janeiro • PMERJ")


def imagem(embed, link):
    if link and link.startswith("http"):
        embed.set_image(url=link)


async def apagar(ctx):
    try:
        await ctx.message.delete()
    except:
        pass


def somente_admin():
    async def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)


def tem_cargo(membro, lista):
    if membro.guild_permissions.administrator:
        return True
    return any(cargo.id in lista for cargo in membro.roles)


def pode_analisar(membro):
    return tem_cargo(membro, config["cargos_analise"])


def pode_moderar(membro):
    return tem_cargo(membro, config["cargos_moderacao"])


def tem_cargo_pm(membro):
    cargo = membro.guild.get_role(ID_CARGO_PM)
    return cargo and cargo in membro.roles


def meta_minima_do_membro(membro):
    cargo_reduzido = membro.guild.get_role(ID_CARGO_META_REDUZIDA)
    if cargo_reduzido and cargo_reduzido in membro.roles:
        return (META_MINUTOS * 60) // 2
    return META_MINUTOS * 60


def texto_meta_do_membro(membro):
    return formatar_tempo(meta_minima_do_membro(membro))


def call_autorizada(voice_channel):
    if not voice_channel:
        return False
    return bool(voice_channel.category and voice_channel.category.id == CATEGORIA_CALLS_ID)


async def enviar_log_ponto(guild, embed=None, texto=None):
    try:
        canal = guild.get_channel(CANAL_PONTO_LOGS_ID) or guild.get_channel(CANAL_LOGS_ID)
        if canal:
            if embed:
                await canal.send(content=texto if texto else None, embed=embed)
            elif texto:
                await canal.send(texto)
    except:
        pass


async def logar(guild, texto):
    try:
        canal = guild.get_channel(CANAL_LOGS_ID)
        if canal:
            await canal.send(texto)
    except:
        pass


async def avisar_antiburla(guild, texto):
    try:
        canal = guild.get_channel(CANAL_ANTIBURLA_ID)
        if canal:
            await canal.send(texto)
    except:
        pass



# ================= BACKUP AUTOMÁTICO =================

async def gerar_backup(guild, canal_destino=None, origem="automatico"):
    try:
        conn.commit()

        if not os.path.exists(DB_FILE):
            await logar(guild, "Backup não realizado: banco de dados não encontrado.")
            return False

        nome_backup = f"backup_{origem}_{datetime.now().strftime('%d-%m-%Y_%H-%M-%S')}.db"
        shutil.copy(DB_FILE, nome_backup)

        embed = discord.Embed(
            title="BACKUP DO SISTEMA",
            description=(
                "Backup do banco de dados operacional realizado com sucesso.\n\n"
                "O arquivo contém os registros salvos do sistema, incluindo pontos operacionais, "
                "relatórios, controle de horas e demais informações internas."
            ),
            color=0x000000
        )

        rodape(embed)

        canal = canal_destino or guild.get_channel(CANAL_BACKUP_ID) or guild.get_channel(CANAL_LOGS_ID)

        if canal:
            await canal.send(embed=embed, file=discord.File(nome_backup))

        try:
            os.remove(nome_backup)
        except:
            pass

        return True

    except Exception as erro:
        await logar(guild, f"Erro ao gerar backup: `{erro}`")
        return False


@tasks.loop(hours=12)
async def backup_automatico():
    await bot.wait_until_ready()

    guild = bot.guilds[0] if bot.guilds else None
    if not guild:
        return

    canal_backup = guild.get_channel(CANAL_BACKUP_ID)
    await gerar_backup(guild, canal_backup, "automatico")


@bot.command()
@somente_admin()
@commands.cooldown(1, 30, commands.BucketType.user)
async def backup(ctx):
    await apagar(ctx)

    sucesso = await gerar_backup(ctx.guild, ctx.channel, "manual")

    if not sucesso:
        await ctx.send("Não foi possível realizar o backup neste momento.", delete_after=8)


# ================= EVENTOS =================

@bot.event
async def on_ready():
    bot.add_view(PainelRegistroPolicial())
    bot.add_view(PainelEmbed())
    bot.add_view(PainelOuvidoria())
    bot.add_view(PainelPonto())
    bot.add_view(PontoAbertoView())

    if not monitorar_pontos.is_running():
        monitorar_pontos.start()

    if not backup_automatico.is_running():
        backup_automatico.start()

    print(f"Bot online como {bot.user}")


@bot.event
async def on_command(ctx):
    await logar(
        ctx.guild,
        f"Comando usado por {ctx.author.mention} em {ctx.channel.mention}: `{ctx.message.content}`"
    )


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        return await ctx.send(f"Aguarde {error.retry_after:.1f}s para usar este comando novamente.", delete_after=5)

    if isinstance(error, commands.CheckFailure):
        return await ctx.send("Você não possui permissão para usar este comando.", delete_after=5)

    if isinstance(error, commands.MissingRequiredArgument):
        return await ctx.send("Está faltando alguma informação no comando.", delete_after=6)

    await ctx.send(f"Erro: `{error}`", delete_after=8)
    print(error)




@bot.event
async def on_guild_channel_delete(channel):
    try:
        ponto = buscar_ponto_por_canal(channel.id)
        if ponto:
            remover_ponto(ponto[0])
    except:
        pass

# ================= BATE PONTO =================

MAX_POLICIAIS_ADICIONADOS = 3
TEMPO_FORA_AVISO = 15 * 60
TEMPO_FORA_FECHAR = 45 * 60


def membro_esta_na_call_registrada(guild, user_id, voice_channel_id):
    membro = guild.get_member(user_id)
    if not membro:
        return False
    return bool(membro.voice and membro.voice.channel and membro.voice.channel.id == voice_channel_id)


async def atualizar_membros_do_ponto(guild, owner_id, voice_channel_id):
    agora = agora_ts()
    alterou = False

    for user_id, valid_seconds, in_voice_since, out_since, warned in membros_estado_do_ponto(owner_id):
        em_call = membro_esta_na_call_registrada(guild, user_id, voice_channel_id)

        if em_call:
            if not in_voice_since:
                cursor.execute("""
                    UPDATE ponto_membros
                    SET in_voice_since = ?, out_since = NULL, warned = 0
                    WHERE owner_id = ? AND user_id = ?
                """, (agora, owner_id, user_id))
                alterou = True
        else:
            if in_voice_since:
                acumulado = (valid_seconds or 0) + max(0, agora - in_voice_since)
                cursor.execute("""
                    UPDATE ponto_membros
                    SET valid_seconds = ?, in_voice_since = NULL, out_since = ?, warned = 0
                    WHERE owner_id = ? AND user_id = ?
                """, (acumulado, agora, owner_id, user_id))
                alterou = True
            elif not out_since:
                cursor.execute("""
                    UPDATE ponto_membros
                    SET out_since = ?
                    WHERE owner_id = ? AND user_id = ?
                """, (agora, owner_id, user_id))
                alterou = True

    if alterou:
        db_commit()


class PainelPonto(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Abrir Ponto",
        style=discord.ButtonStyle.green,
        custom_id="abrir_ponto_pmerj"
    )
    async def abrir_ponto(self, interaction: discord.Interaction, button: discord.ui.Button):
        membro = interaction.user

        if not isinstance(membro, discord.Member):
            return await interaction.response.send_message("Erro ao identificar membro.", ephemeral=True)

        if not tem_cargo_pm(membro):
            return await interaction.response.send_message(
                "Apenas integrantes da Polícia Militar podem abrir ponto.",
                ephemeral=True
            )

        if usuario_tem_ponto(membro.id):
            return await interaction.response.send_message(
                "Você já está vinculado a um ponto aberto.",
                ephemeral=True
            )

        if not membro.voice or not membro.voice.channel:
            return await interaction.response.send_message(
                "Você precisa estar em uma call operacional para abrir o ponto.",
                ephemeral=True
            )

        if not call_autorizada(membro.voice.channel):
            return await interaction.response.send_message(
                "O ponto só pode ser iniciado em uma call da categoria operacional autorizada.",
                ephemeral=True
            )

        categoria = interaction.guild.get_channel(CATEGORIA_PONTO_ID)

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            membro: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)
        }

        canal = await interaction.guild.create_text_channel(
            name=f"ponto-{membro.name}",
            overwrites=overwrites,
            category=categoria if categoria else None
        )

        inicio = agora_ts()
        voice_id = membro.voice.channel.id

        cursor.execute(
            "INSERT OR REPLACE INTO pontos_abertos (owner_id, channel_id, start_ts, voice_channel_id, closed) VALUES (?, ?, ?, ?, ?)",
            (membro.id, canal.id, inicio, voice_id, 0)
        )
        cursor.execute(
            "INSERT OR REPLACE INTO ponto_membros (owner_id, user_id, valid_seconds, in_voice_since, out_since, warned) VALUES (?, ?, ?, ?, ?, ?)",
            (membro.id, membro.id, 0, inicio, None, 0)
        )
        db_commit()

        embed = discord.Embed(
            title="BATE-PONTO OPERACIONAL",
            description=(
                "Ponto operacional iniciado.\n\n"
                "O policial deverá permanecer na call registrada durante o serviço. O tempo válido será contabilizado somente enquanto o integrante estiver presente na call operacional.\n\n"
                "Para incluir outros policiais no mesmo serviço, utilize o comando `;add @policial` dentro deste canal. O limite é de até 3 policiais adicionados, além do responsável pelo ponto.\n\n"
                "Ao encerrar, será obrigatório apresentar relatório operacional das atividades realizadas."
            ),
            color=0x000000
        )

        embed.set_author(name=membro.display_name, icon_url=membro.display_avatar.url)
        embed.add_field(name="Responsável", value=membro.mention, inline=False)
        embed.add_field(name="Call registrada", value=membro.voice.channel.mention, inline=False)
        embed.add_field(name="Status", value="Em serviço", inline=False)
        imagem(embed, IMG_BATEPONTO)
        rodape(embed)

        await canal.send(embed=embed, view=PontoAbertoView())

        await interaction.response.send_message(
            f"Seu ponto foi aberto: {canal.mention}",
            ephemeral=True
        )

        await logar(interaction.guild, f"Ponto operacional aberto por {membro.mention} em {canal.mention}.")


class ModalFecharPonto(discord.ui.Modal, title="Fechar Ponto"):
    relatorio = discord.ui.TextInput(
        label="Relatório operacional",
        placeholder="Descreva patrulhamento, ocorrências, abordagens e observações.",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=2000
    )

    async def on_submit(self, interaction: discord.Interaction):
        ponto = buscar_ponto_por_canal(interaction.channel.id)

        if not ponto:
            return await interaction.response.send_message(
                "Este canal não possui ponto aberto.",
                ephemeral=True
            )

        owner_id, channel_id, start_ts, voice_channel_id, closed = ponto

        if interaction.user.id != owner_id and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Apenas o responsável pelo ponto ou administradores podem fechar este ponto.",
                ephemeral=True
            )

        await atualizar_membros_do_ponto(interaction.guild, owner_id, voice_channel_id)

        fim = agora_ts()
        membros = membros_do_ponto(owner_id)
        total_por_membro = {}

        max_segundos = MAX_PONTO_HORAS * 3600

        for user_id in membros:
            total = min(segundos_validos_atuais(user_id, fim), max_segundos)
            total_por_membro[user_id] = total
            add_horas(user_id, total)

        maior_total = max(total_por_membro.values()) if total_por_membro else 0

        cursor.execute(
            "INSERT INTO ponto_relatorios (owner_id, members, start_ts, end_ts, total_seconds, relatorio) VALUES (?, ?, ?, ?, ?, ?)",
            (owner_id, json.dumps(membros), start_ts, fim, maior_total, self.relatorio.value)
        )
        db_commit()

        embed = discord.Embed(
            title="PONTO FECHADO",
            description="O ponto operacional foi encerrado com relatório.",
            color=0x008000
        )

        linhas = []
        for user_id in membros:
            membro = interaction.guild.get_member(user_id)
            nome = membro.mention if membro else f"`{user_id}`"
            linhas.append(f"{nome} — {formatar_tempo(total_por_membro.get(user_id, 0))}")

        embed.add_field(name="Policiais no ponto", value="\n".join(linhas) if linhas else "Nenhum", inline=False)
        embed.add_field(name="Relatório", value=self.relatorio.value[:1000], inline=False)
        imagem(embed, IMG_BATEPONTO)
        rodape(embed)

        await enviar_log_ponto(interaction.guild, embed=embed)

        remover_ponto(owner_id)

        await interaction.response.send_message("Ponto fechado com sucesso.", ephemeral=True)

        await asyncio.sleep(2)

        try:
            await interaction.channel.delete()
        except:
            pass


class PontoAbertoView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Fechar Ponto",
        style=discord.ButtonStyle.danger,
        custom_id="ponto_fechar"
    )
    async def fechar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ModalFecharPonto())


@bot.command()
@commands.cooldown(1, 5, commands.BucketType.user)
async def add(ctx, policial: discord.Member):
    await apagar(ctx)

    ponto = buscar_ponto_por_canal(ctx.channel.id)

    if not ponto:
        return await ctx.send("Este comando só pode ser usado dentro de um canal de ponto aberto.", delete_after=8)

    owner_id, channel_id, start_ts, voice_channel_id, closed = ponto

    if ctx.author.id != owner_id and not ctx.author.guild_permissions.administrator:
        return await ctx.send("Apenas o responsável pelo ponto ou administradores podem adicionar policiais.", delete_after=8)

    if not tem_cargo_pm(policial):
        return await ctx.send(f"{policial.mention} não possui cargo da Polícia Militar.", delete_after=8)

    if usuario_tem_ponto(policial.id):
        return await ctx.send(f"{policial.mention} já está vinculado a um ponto aberto.", delete_after=8)

    if not policial.voice or not policial.voice.channel or policial.voice.channel.id != voice_channel_id:
        return await ctx.send(f"{policial.mention} precisa estar na mesma call operacional registrada no ponto.", delete_after=8)

    if not call_autorizada(policial.voice.channel):
        return await ctx.send(f"{policial.mention} precisa estar em uma call da categoria operacional autorizada.", delete_after=8)

    membros = membros_do_ponto(owner_id)

    if len(membros) >= 4:
        return await ctx.send("O limite deste ponto já foi atingido: responsável + 3 policiais.", delete_after=8)

    agora = agora_ts()

    try:
        await ctx.channel.set_permissions(
            policial,
            view_channel=True,
            send_messages=True,
            read_message_history=True
        )
    except:
        pass

    cursor.execute(
        "INSERT OR REPLACE INTO ponto_membros (owner_id, user_id, valid_seconds, in_voice_since, out_since, warned) VALUES (?, ?, ?, ?, ?, ?)",
        (owner_id, policial.id, 0, agora, None, 0)
    )
    db_commit()

    await ctx.send(f"{policial.mention} foi adicionado ao ponto operacional.")
    await logar(ctx.guild, f"{policial.mention} foi adicionado ao ponto de <@{owner_id}> por {ctx.author.mention}.")


@tasks.loop(minutes=5)
async def monitorar_pontos():
    await bot.wait_until_ready()

    cursor.execute("SELECT owner_id, channel_id, start_ts, voice_channel_id, closed FROM pontos_abertos")
    pontos = cursor.fetchall()

    guild = bot.guilds[0] if bot.guilds else None
    if not guild:
        return

    agora = agora_ts()

    for ponto in pontos:
        owner_id, channel_id, start_ts, voice_channel_id, closed = ponto

        canal = guild.get_channel(channel_id)
        if not canal:
            remover_ponto(owner_id)
            continue

        if agora - start_ts >= MAX_PONTO_HORAS * 3600:
            await fechar_ponto_automatico(guild, ponto, "Tempo máximo de ponto operacional atingido.")
            continue

        await atualizar_membros_do_ponto(guild, owner_id, voice_channel_id)

        for user_id, valid_seconds, in_voice_since, out_since, warned in membros_estado_do_ponto(owner_id):
            if out_since:
                tempo_fora = agora - out_since
                membro = guild.get_member(user_id)

                if tempo_fora >= TEMPO_FORA_AVISO and warned == 0:
                    cursor.execute(
                        "UPDATE ponto_membros SET warned = 1 WHERE owner_id = ? AND user_id = ?",
                        (owner_id, user_id)
                    )
                    db_commit()

                    texto = (
                        f"{membro.mention if membro else f'`{user_id}`'} está fora da call operacional do ponto {canal.mention} "
                        f"há {formatar_tempo(tempo_fora)}. O tempo fora da call não será contabilizado."
                    )

                    try:
                        await canal.send(texto)
                    except:
                        pass

                    await avisar_antiburla(guild, texto)

                if tempo_fora >= TEMPO_FORA_FECHAR:
                    await fechar_ponto_automatico(
                        guild,
                        ponto,
                        f"Policial fora da call operacional por {formatar_tempo(tempo_fora)}."
                    )
                    break


async def fechar_ponto_automatico(guild, ponto, motivo):
    owner_id, channel_id, start_ts, voice_channel_id, closed = ponto
    canal = guild.get_channel(channel_id)

    await atualizar_membros_do_ponto(guild, owner_id, voice_channel_id)

    membros = membros_do_ponto(owner_id)
    fim = agora_ts()
    total_por_membro = {}

    for user_id in membros:
        total = min(segundos_validos_atuais(user_id, fim), MAX_PONTO_HORAS * 3600)
        total_por_membro[user_id] = total
        add_horas(user_id, total)

    embed = discord.Embed(
        title="PONTO ENCERRADO PELO CONTROLE OPERACIONAL",
        description=(
            "O ponto foi encerrado automaticamente.\n\n"
            "Foram computados apenas os períodos válidos em que os policiais permaneceram na call operacional registrada."
        ),
        color=0x800000
    )

    linhas = []
    for user_id in membros:
        membro = guild.get_member(user_id)
        nome = membro.mention if membro else f"`{user_id}`"
        linhas.append(f"{nome} — {formatar_tempo(total_por_membro.get(user_id, 0))}")

    embed.add_field(name="Policiais", value="\n".join(linhas) if linhas else "Nenhum", inline=False)
    embed.add_field(name="Motivo", value=motivo, inline=False)
    imagem(embed, IMG_BATEPONTO)
    rodape(embed)

    await enviar_log_ponto(guild, embed=embed)

    await avisar_antiburla(guild, f"Ponto encerrado automaticamente: {motivo}")

    remover_ponto(owner_id)

    if canal:
        try:
            await canal.send("Ponto encerrado automaticamente pelo controle operacional.")
            await asyncio.sleep(3)
            await canal.delete()
        except:
            pass
# ================= REGISTRO POLICIAL =================

class FormularioRegistro(discord.ui.Modal, title="Registro Policial"):
    nome_rg = discord.ui.TextInput(
        label="Nome e RG",
        placeholder="Exemplo: Erick Walker - 1234",
        required=True,
        max_length=60
    )

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id

        if not config["registros_abertos"]:
            return await interaction.response.send_message(
                "Os registros policiais encontram-se encerrados no momento.",
                ephemeral=True
            )

        if user_id in config["registros_pendentes"]:
            return await interaction.response.send_message(
                "Você já possui um registro policial em análise.",
                ephemeral=True
            )

        cargo_2_soldado = interaction.guild.get_role(ID_CARGO_2_SOLDADO)

        if cargo_2_soldado and cargo_2_soldado in interaction.user.roles:
            return await interaction.response.send_message(
                "Você já possui registro policial ativo como Recruta.",
                ephemeral=True
            )

        canal = interaction.guild.get_channel(CANAL_ANALISE_ID)

        if canal is None:
            return await interaction.response.send_message(
                "Canal de análise não encontrado.",
                ephemeral=True
            )

        config["registros_pendentes"].append(user_id)
        salvar_config(config)

        embed = discord.Embed(
            title="NOVO REGISTRO POLICIAL",
            description=(
                "Um novo registro policial foi encaminhado para análise administrativa.\n\n"
                "Este procedimento é destinado aos aprovados oriundos do processo seletivo da PMERJ, "
                "após conclusão da entrevista."
            ),
            color=0x000000
        )

        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="Solicitante", value=interaction.user.mention, inline=False)
        embed.add_field(name="Identificação", value=self.nome_rg.value, inline=False)
        embed.add_field(name="Cargo solicitado", value="Recruta", inline=False)
        embed.add_field(name="Status", value="Aguardando análise", inline=False)

        imagem(embed, IMG_REGISTRO)
        rodape(embed)

        await canal.send(
            embed=embed,
            view=AnaliseRegistroView(user_id, self.nome_rg.value)
        )

        await interaction.response.send_message(
            "Seu registro policial foi enviado para análise.",
            ephemeral=True
        )


class PainelRegistroPolicial(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Realizar Registro Policial",
        style=discord.ButtonStyle.primary,
        custom_id="realizar_registro_policial_pmerj"
    )
    async def realizar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(FormularioRegistro())


class ModalMotivoRecusa(discord.ui.Modal, title="Motivo da Recusa"):
    motivo = discord.ui.TextInput(
        label="Motivo da recusa",
        placeholder="Informe o motivo da recusa.",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500
    )

    def __init__(self, data):
        super().__init__()
        self.data = data

    async def on_submit(self, interaction: discord.Interaction):
        membro = interaction.guild.get_member(self.data["usuario_id"])

        embed = discord.Embed(
            title="REGISTRO POLICIAL RECUSADO",
            description="A solicitação de registro policial foi recusada pela análise administrativa.",
            color=0x800000
        )

        if membro:
            embed.set_author(name=membro.display_name, icon_url=membro.display_avatar.url)
            discord_info = f"{membro.mention} | {membro.id}"
        else:
            discord_info = f"Usuário ID: {self.data['usuario_id']}"

        embed.add_field(name="Identificação", value=self.data["identificacao"], inline=False)
        embed.add_field(name="Cargo solicitado", value="2° Soldado", inline=False)
        embed.add_field(name="Discord", value=discord_info, inline=False)
        embed.add_field(name="Motivo", value=self.motivo.value, inline=False)
        embed.add_field(name="Responsável pela análise", value=interaction.user.mention, inline=False)

        imagem(embed, IMG_REGISTRO)
        rodape(embed)

        canal_logs = interaction.guild.get_channel(CANAL_LOGS_ID)
        if canal_logs:
            await canal_logs.send(embed=embed)

        if self.data["usuario_id"] in config["registros_pendentes"]:
            config["registros_pendentes"].remove(self.data["usuario_id"])
            salvar_config(config)

        if membro:
            try:
                await membro.send(
                    "Seu registro policial foi **recusado**.\n\n"
                    "Não foram encontrados registros válidos de seu recrutamento "
                    "ou as informações apresentadas não atenderam aos critérios administrativos.\n\n"
                    f"Motivo: {self.motivo.value}"
                )
            except:
                pass

        await interaction.response.edit_message(content="Registro policial recusado.", view=None)


class AnaliseRegistroView(discord.ui.View):
    def __init__(self, usuario_id, identificacao):
        super().__init__(timeout=None)
        self.data = {
            "usuario_id": usuario_id,
            "identificacao": identificacao
        }

    @discord.ui.button(label="Aceitar", style=discord.ButtonStyle.green)
    async def aceitar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not pode_analisar(interaction.user):
            return await interaction.response.send_message(
                "Você não possui permissão para analisar registros policiais.",
                ephemeral=True
            )

        membro = interaction.guild.get_member(self.data["usuario_id"])

        cargo_pm = interaction.guild.get_role(ID_CARGO_POLICIA_MILITAR)
        cargo_cpo = interaction.guild.get_role(ID_CARGO_CPO)
        cargo_2_soldado = interaction.guild.get_role(ID_CARGO_2_SOLDADO)
        cargo_22bpm = interaction.guild.get_role(ID_CARGO_22BPM)

        if not membro:
            return await interaction.response.send_message("Usuário não encontrado.", ephemeral=True)

        if not cargo_pm or not cargo_cpo or not cargo_2_soldado or not cargo_22bpm:
            return await interaction.response.send_message(
                "Um ou mais cargos não foram encontrados. Verifique os IDs configurados.",
                ephemeral=True
            )

        novo_nome = f"Recruta {self.data['identificacao']}"

        try:
            await membro.add_roles(cargo_pm, cargo_cpo, cargo_2_soldado, cargo_22bpm)
            await membro.edit(nick=novo_nome)
        except discord.Forbidden:
            return await interaction.response.send_message(
                "Não consegui aplicar cargos ou alterar o apelido. Verifique se meu cargo está acima dos cargos que devo setar.",
                ephemeral=True
            )

        embed = discord.Embed(
            title="REGISTRO POLICIAL APROVADO",
            description=(
                "O registro policial foi aprovado com sucesso.\n\n"
                "O militar foi devidamente integrado aos quadros da Polícia Militar e recebeu os cargos correspondentes."
            ),
            color=0x008000
        )

        embed.set_author(name=membro.display_name, icon_url=membro.display_avatar.url)
        embed.add_field(name="Identificação", value=self.data["identificacao"], inline=False)
        embed.add_field(name="Cargo aplicado", value=cargo_2_soldado.mention, inline=False)
        embed.add_field(name="Cargos adicionais", value=f"{cargo_pm.mention}\n{cargo_cpo.mention}\n{cargo_22bpm.mention}", inline=False)
        embed.add_field(name="Discord", value=f"{membro.mention} | {membro.id}", inline=False)
        embed.add_field(name="Responsável pela análise", value=interaction.user.mention, inline=False)

        imagem(embed, IMG_REGISTRO)
        rodape(embed)

        canal_logs = interaction.guild.get_channel(CANAL_LOGS_ID)
        if canal_logs:
            await canal_logs.send(embed=embed)

        if self.data["usuario_id"] in config["registros_pendentes"]:
            config["registros_pendentes"].remove(self.data["usuario_id"])
            salvar_config(config)

        try:
            await membro.send(
                "Seu registro policial foi **aprovado**.\n\n"
                "Seja bem-vindo à Polícia Militar. Seu cargo e identificação foram atualizados com sucesso."
            )
        except:
            pass

        await interaction.response.edit_message(content="Registro policial aprovado.", view=None)

    @discord.ui.button(label="Recusar", style=discord.ButtonStyle.red)
    async def recusar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not pode_analisar(interaction.user):
            return await interaction.response.send_message(
                "Você não possui permissão para analisar registros policiais.",
                ephemeral=True
            )

        await interaction.response.send_modal(ModalMotivoRecusa(self.data))


# ================= EMBED FORMULÁRIO =================

class ModalCriarEmbed(discord.ui.Modal, title="Criar Embed"):
    canal_id = discord.ui.TextInput(
        label="ID do canal",
        placeholder="Cole o ID do canal onde a embed será enviada",
        required=True,
        max_length=25
    )

    titulo = discord.ui.TextInput(
        label="Título",
        placeholder="Digite o título da embed",
        required=True,
        max_length=100
    )

    texto = discord.ui.TextInput(
        label="Texto",
        placeholder="Digite o texto da embed",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=3000
    )

    link = discord.ui.TextInput(
        label="Link da imagem",
        placeholder="Opcional",
        required=False,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Apenas administradores podem criar embeds.", ephemeral=True)

        try:
            canal = interaction.guild.get_channel(int(self.canal_id.value))
        except:
            canal = None

        if canal is None:
            return await interaction.response.send_message("Canal não encontrado. Verifique o ID informado.", ephemeral=True)

        embed = discord.Embed(
            title=self.titulo.value,
            description=self.texto.value,
            color=0x000000
        )

        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        imagem(embed, self.link.value)
        rodape(embed)

        await canal.send(embed=embed)
        await interaction.response.send_message(f"Embed enviada em {canal.mention}.", ephemeral=True)

        await logar(interaction.guild, f"Embed criada por {interaction.user.mention} e enviada em {canal.mention}.")


class PainelEmbed(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Criar Embed",
        style=discord.ButtonStyle.secondary,
        custom_id="criar_embed_pmerj"
    )
    async def criar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Apenas administradores podem usar este painel.", ephemeral=True)

        await interaction.response.send_modal(ModalCriarEmbed())


# ================= OUVIDORIA =================

class ModalOuvidoria(discord.ui.Modal, title="Ouvidoria PMERJ"):
    motivo = discord.ui.TextInput(
        label="Descreva sua solicitação",
        style=discord.TextStyle.paragraph,
        placeholder="Explique detalhadamente o ocorrido...",
        required=True,
        max_length=700
    )

    def __init__(self, tipo):
        super().__init__()
        self.tipo = tipo

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)

        if user_id in config["ouvidoria_abertos"]:
            return await interaction.response.send_message(
                "Você já possui um atendimento da Ouvidoria em andamento.",
                ephemeral=True
            )

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True
            ),
            interaction.guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True
            )
        }

        categoria = None
        if CATEGORIA_OUVIDORIA_ID:
            categoria = interaction.guild.get_channel(CATEGORIA_OUVIDORIA_ID)

        canal = await interaction.guild.create_text_channel(
            name=f"ouvidoria-{interaction.user.name}",
            overwrites=overwrites,
            category=categoria
        )

        config["ouvidoria_abertos"][user_id] = canal.id
        salvar_config(config)

        embed = discord.Embed(
            title="OUVIDORIA DA POLÍCIA MILITAR",
            description=(
                "Este atendimento foi aberto junto à Ouvidoria da Polícia Militar.\n\n"
                "A Ouvidoria é destinada ao recebimento de denúncias, reclamações, solicitações de revisão "
                "e demais situações relacionadas à conduta de policiais militares ou atos administrativos.\n\n"
                "Todas as informações apresentadas serão analisadas com responsabilidade, discrição e imparcialidade."
            ),
            color=0x000000
        )

        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="Tipo de atendimento", value=self.tipo, inline=False)
        embed.add_field(name="Solicitante", value=interaction.user.mention, inline=False)
        embed.add_field(name="Relato inicial", value=self.motivo.value, inline=False)
        rodape(embed)

        await canal.send(embed=embed, view=FecharOuvidoriaView(interaction.user.id))
        await interaction.response.send_message(f"Seu atendimento foi aberto: {canal.mention}", ephemeral=True)


class PainelOuvidoria(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(
        placeholder="Selecione o tipo de atendimento",
        custom_id="select_ouvidoria_pmerj",
        options=[
            discord.SelectOption(label="Denúncia", description="Denunciar má conduta policial"),
            discord.SelectOption(label="Revisão", description="Solicitar revisão de situação ou decisão"),
            discord.SelectOption(label="Reclamação", description="Registrar reclamação administrativa"),
            discord.SelectOption(label="Outros", description="Outro assunto relacionado à Ouvidoria")
        ]
    )
    async def selecionar(self, interaction: discord.Interaction, select: discord.ui.Select):
        await interaction.response.send_modal(ModalOuvidoria(select.values[0]))


class FecharOuvidoriaView(discord.ui.View):
    def __init__(self, dono_id):
        super().__init__(timeout=None)
        self.dono_id = dono_id

    @discord.ui.button(label="Encerrar Atendimento", style=discord.ButtonStyle.danger)
    async def fechar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Apenas administradores podem encerrar atendimentos da Ouvidoria.",
                ephemeral=True
            )

        await interaction.response.send_message("Encerrando atendimento e gerando transcript...", ephemeral=True)

        membro = interaction.guild.get_member(self.dono_id)

        try:
            mensagens = []

            async for msg in interaction.channel.history(limit=300, oldest_first=True):
                conteudo = msg.content if msg.content else "[sem texto]"
                mensagens.append(f"{msg.created_at} | {msg.author}: {conteudo}")

            transcript = "\n".join(mensagens) or "Sem mensagens registradas."

            arquivo_pv = discord.File(
                fp=bytes(transcript, "utf-8"),
                filename=f"transcript-{interaction.channel.name}.txt"
            )

            if membro:
                try:
                    await membro.send(
                        "Segue o transcript do seu atendimento na Ouvidoria da Polícia Militar.",
                        file=arquivo_pv
                    )
                except:
                    pass

        except Exception as erro:
            print(f"Erro ao gerar transcript da Ouvidoria: {erro}")

        user_id = str(self.dono_id)

        if user_id in config["ouvidoria_abertos"]:
            del config["ouvidoria_abertos"][user_id]
            salvar_config(config)

        try:
            await interaction.channel.delete()
        except:
            pass


# ================= COMANDOS =================

@bot.command()
@somente_admin()
@commands.cooldown(1, 10, commands.BucketType.user)
async def painelponto(ctx):
    await apagar(ctx)

    embed = discord.Embed(
        title="BATE-PONTO OPERACIONAL",
        description=(
            "Este painel é destinado ao controle de carga horária dos integrantes da Polícia Militar.\n\n"
            "Para iniciar o serviço, o policial deverá estar em uma call operacional autorizada e clicar em **Abrir Ponto**.\n\n"
            "O sistema registra o horário de início, permite adicionar integrantes ao ponto, exige relatório ao fechamento. Integrantes com escala reduzida terão a meta semanal contabilizada pela metade."
        ),
        color=0x000000
    )

    imagem(embed, IMG_BATEPONTO)
    rodape(embed)

    await ctx.send(embed=embed, view=PainelPonto())


@bot.command()
@somente_admin()
@commands.cooldown(1, 10, commands.BucketType.user)
async def relatoriohoras(ctx):
    await apagar(ctx)

    cargo_pm = ctx.guild.get_role(ID_CARGO_PM)
    if not cargo_pm:
        return await ctx.send("Cargo PM não encontrado.")

    linhas = []

    for membro in cargo_pm.members:
        total = total_user(membro.id)
        meta = texto_meta_do_membro(membro)
        if total > 0:
            linhas.append(f"{membro.mention} — {formatar_tempo(total)} / meta {meta}")
        else:
            linhas.append(f"{membro.mention} — NÃO BATEU PONTO / meta {meta}")

    embed = discord.Embed(
        title="RELATÓRIO DE CARGA HORÁRIA",
        description="\n".join(linhas)[:4000] if linhas else "Nenhum policial encontrado.",
        color=0x000000
    )

    rodape(embed)
    await ctx.send(embed=embed)


@bot.command()
@somente_admin()
@commands.cooldown(1, 20, commands.BucketType.user)
async def resetarhoras(ctx):
    await apagar(ctx)

    cargo_pm = ctx.guild.get_role(ID_CARGO_PM)
    cargo_meta = ctx.guild.get_role(ID_CARGO_META_INCOMPLETA)
    cargo_ausencia = ctx.guild.get_role(ID_CARGO_AUSENCIA)

    if not cargo_pm or not cargo_meta:
        return await ctx.send("Cargo PM ou cargo de carga horária incompleta não encontrado.")

    atingiram = []
    nao_atingiram = []
    isentos = []

    for membro in cargo_pm.members:
        total = total_user(membro.id)
        meta_segundos = meta_minima_do_membro(membro)

        if cargo_ausencia and cargo_ausencia in membro.roles:
            isentos.append(f"{membro.mention} — {formatar_tempo(total)} / meta {formatar_tempo(meta_segundos)}")
            continue

        if total >= meta_segundos:
            atingiram.append(f"{membro.mention} — {formatar_tempo(total)} / meta {formatar_tempo(meta_segundos)}")
            try:
                if cargo_meta in membro.roles:
                    await membro.remove_roles(cargo_meta)
            except:
                pass
        else:
            nao_atingiram.append(f"{membro.mention} — {formatar_tempo(total)} / meta {formatar_tempo(meta_segundos)}")
            try:
                await membro.add_roles(cargo_meta)
            except:
                pass

    embed = discord.Embed(
        title="RESET DE CARGA HORÁRIA",
        description="As horas foram resetadas e as tags foram aplicadas conforme a meta definida.",
        color=0x000000
    )

    embed.add_field(name="Atingiram a meta", value="\n".join(atingiram)[:1000] if atingiram else "Nenhum", inline=False)
    embed.add_field(name="Carga horária incompleta", value="\n".join(nao_atingiram)[:1000] if nao_atingiram else "Nenhum", inline=False)
    embed.add_field(name="Isentos por ausência", value="\n".join(isentos)[:1000] if isentos else "Nenhum", inline=False)

    rodape(embed)
    await ctx.send(embed=embed)

    canal_backup = ctx.guild.get_channel(CANAL_BACKUP_ID)
    await gerar_backup(ctx.guild, canal_backup, "antes_reset_horas")

    cursor.execute("DELETE FROM ponto_totais")
    cursor.execute("DELETE FROM ponto_relatorios")
    db_commit()


@bot.command()
@somente_admin()
async def pontosativos(ctx):
    await apagar(ctx)

    cursor.execute("SELECT owner_id, channel_id, start_ts FROM pontos_abertos")
    pontos = cursor.fetchall()

    if not pontos:
        return await ctx.send("Não há pontos ativos no momento.", delete_after=8)

    linhas = []

    for owner_id, channel_id, start_ts in pontos:
        membro = ctx.guild.get_member(owner_id)
        canal = ctx.guild.get_channel(channel_id)
        tempo = agora_ts() - start_ts
        linhas.append(f"{membro.mention if membro else owner_id} — {formatar_tempo(tempo)} — {canal.mention if canal else 'canal não encontrado'}")

    embed = discord.Embed(
        title="PONTOS ATIVOS",
        description="\n".join(linhas)[:4000],
        color=0x000000
    )

    rodape(embed)
    await ctx.send(embed=embed)




@bot.command()
@somente_admin()
@commands.cooldown(1, 10, commands.BucketType.user)
async def forcarfecharponto(ctx):
    await apagar(ctx)

    ponto = buscar_ponto_por_canal(ctx.channel.id)

    if ponto:
        remover_ponto(ponto[0])

    await ctx.send("Canal de ponto encerrado manualmente.", delete_after=5)

    await asyncio.sleep(2)

    try:
        await ctx.channel.delete()
    except:
        pass

@bot.command()
@somente_admin()
async def horas(ctx, membro: discord.Member):
    await apagar(ctx)

    embed = discord.Embed(
        title="HORAS DO POLICIAL",
        description=f"{membro.mention} possui **{formatar_tempo(total_user(membro.id))}** registradas.",
        color=0x000000
    )

    rodape(embed)
    await ctx.send(embed=embed)


@bot.command()
@somente_admin()
@commands.cooldown(1, 10, commands.BucketType.user)
async def painelregistro(ctx):
    await apagar(ctx)

    embed = discord.Embed(
        title="REGISTRO POLICIAL PMERJ",
        description=(
            "Esta área é destinada aos aprovados após a realização da entrevista juntamente a equipe de instrução.\n\n"
            "O registro policial tem como objetivo oficializar a entrada do aprovado no quadro da Polícia Militar, padronizando sua identificação, seus cargos e sua situação administrativa dentro da corporação."
        ),
        color=0x000000
    )

    imagem(embed, IMG_REGISTRO)
    rodape(embed)

    await ctx.send(embed=embed, view=PainelRegistroPolicial())


@bot.command()
@somente_admin()
@commands.cooldown(1, 10, commands.BucketType.user)
async def painelouvidoria(ctx):
    await apagar(ctx)

    embed = discord.Embed(
        title="OUVIDORIA DA POLÍCIA MILITAR",
        description=(
            "Este setor é destinado ao recebimento de denúncias, reclamações e solicitações de revisão administrativa.\n\n"
            "Cada cidadão poderá manter somente um atendimento aberto por vez."
        ),
        color=0x000000
    )

    imagem(embed, IMG_OUVIDORIA)
    rodape(embed)

    await ctx.send(embed=embed, view=PainelOuvidoria())



@bot.command()
@somente_admin()
@commands.cooldown(1, 5, commands.BucketType.user)
async def embed(ctx, *, conteudo):
    await apagar(ctx)

    try:
        partes = conteudo.split("|")

        if len(partes) < 2:
            return await ctx.send(
                "Formato incorreto. Use: `;embed titulo | texto | imagem(opcional)`",
                delete_after=10
            )

        titulo = partes[0].strip()
        texto = partes[1].strip()
        link_imagem = partes[2].strip() if len(partes) >= 3 else ""

        nova_embed = discord.Embed(
            title=titulo,
            description=texto,
            color=0x000000
        )

        nova_embed.set_author(
            name=ctx.author.display_name,
            icon_url=ctx.author.display_avatar.url
        )

        if link_imagem and link_imagem.startswith("http"):
            nova_embed.set_image(url=link_imagem)

        rodape(nova_embed)

        await ctx.send(embed=nova_embed)

        await logar(
            ctx.guild,
            f"Embed criada por {ctx.author.mention} em {ctx.channel.mention}."
        )

    except Exception as erro:
        await ctx.send(
            "Formato incorreto. Use: `;embed titulo | texto | imagem(opcional)`",
            delete_after=10
        )
        print(erro)

@bot.command()
@somente_admin()
async def painelembed(ctx):
    await apagar(ctx)

    embed = discord.Embed(
        title="PAINEL DE EMBEDS",
        description="Clique no botão abaixo para criar uma embed personalizada.",
        color=0x000000
    )

    rodape(embed)
    await ctx.send(embed=embed, view=PainelEmbed())


@bot.command()
@somente_admin()
async def addanalise(ctx, cargo: discord.Role):
    await apagar(ctx)
    if cargo.id not in config["cargos_analise"]:
        config["cargos_analise"].append(cargo.id)
        salvar_config(config)
    await ctx.send(f"{cargo.mention} agora pode analisar registros.", delete_after=8)


@bot.command()
@somente_admin()
async def addmod(ctx, cargo: discord.Role):
    await apagar(ctx)
    if cargo.id not in config["cargos_moderacao"]:
        config["cargos_moderacao"].append(cargo.id)
        salvar_config(config)
    await ctx.send(f"{cargo.mention} agora pode usar moderação.", delete_after=8)


@bot.command()
@commands.cooldown(1, 5, commands.BucketType.user)
async def banir(ctx, membro: discord.Member, *, motivo="Não informado"):
    await apagar(ctx)
    if not pode_moderar(ctx.author):
        return await ctx.send("Você não possui permissão.", delete_after=6)
    await membro.ban(reason=motivo)
    await ctx.send(f"{membro.mention} foi banido. Motivo: `{motivo}`")


@bot.command()
@commands.cooldown(1, 5, commands.BucketType.user)
async def expulsar(ctx, membro: discord.Member, *, motivo="Não informado"):
    await apagar(ctx)
    if not pode_moderar(ctx.author):
        return await ctx.send("Você não possui permissão.", delete_after=6)
    await membro.kick(reason=motivo)
    await ctx.send(f"{membro.mention} foi expulso. Motivo: `{motivo}`")


@bot.command()
@commands.cooldown(1, 5, commands.BucketType.user)
async def mutar(ctx, membro: discord.Member, minutos: int = 10, *, motivo="Não informado"):
    await apagar(ctx)
    if not pode_moderar(ctx.author):
        return await ctx.send("Você não possui permissão.", delete_after=6)
    await membro.timeout(timedelta(minutes=minutos), reason=motivo)
    await ctx.send(f"{membro.mention} foi mutado por `{minutos}` minutos. Motivo: `{motivo}`")


@bot.command()
@commands.cooldown(1, 5, commands.BucketType.user)
async def desmutar(ctx, membro: discord.Member):
    await apagar(ctx)
    if not pode_moderar(ctx.author):
        return await ctx.send("Você não possui permissão.", delete_after=6)
    await membro.timeout(None)
    await ctx.send(f"{membro.mention} foi desmutado.")


if TOKEN is None:
    print("ERRO: TOKEN não encontrado nas Variables do Railway.")
else:
    bot.run(TOKEN)
