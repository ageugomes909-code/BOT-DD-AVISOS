import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread
from flask import Flask

import discord
from discord import app_commands
from discord.ext import commands

# ==============================================
# SERVIDOR WEB PARA MANTER O RENDER ONLINE (24/7)
# ==============================================
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Bot Operacional e Online!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def manter_online():
    t = Thread(target=run_flask, daemon=True)
    t.start()

# ==============================================
# CONFIGURAÇÕES DO BOT
# ==============================================
TOKEN = os.getenv("DISCORD_TOKEN")
START_TIME = datetime.now(timezone.utc)

CONFIG_FILE = Path(__file__).parent / "config.json"

URL_REGEX = re.compile(
    r"(https?://\S+)"
    r"|(www\.\S+)"
    r"|(discord\.gg/\S+)"
    r"|(discord\.com/invite/\S+)"
    r"|(\b[a-z0-9-]+\.(com|net|org|gg|io|br|xyz|tv|me|link|site|online)(/\S*)?)",
    re.IGNORECASE,
)


def load_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def get_guild_cfg(guild_id):
    cfg = load_config()
    key = str(guild_id)
    if key not in cfg:
        cfg[key] = {
            "log_channel": None,
            "link_roles": [],
            "authorized_users": [],
            "antilink_enabled": False,
        }
        save_config(cfg)
    return cfg[key], cfg


def set_guild_cfg(guild_id, new_cfg):
    cfg = load_config()
    cfg[str(guild_id)] = new_cfg
    save_config(cfg)


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


def is_authorized(interaction):
    if interaction.guild is None:
        return False
    if interaction.user.id == interaction.guild.owner_id:
        return True
    gcfg, _ = get_guild_cfg(interaction.guild.id)
    return interaction.user.id in gcfg.get("authorized_users", [])


def require_auth():
    async def predicate(interaction):
        if not is_authorized(interaction):
            raise app_commands.CheckFailure("Você não tem permissão para usar este comando.")
        return True
    return app_commands.check(predicate)


@bot.tree.error
async def on_app_command_error(interaction, error):
    msg = str(error)
    if isinstance(error, app_commands.CheckFailure):
        try:
            await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            await interaction.followup.send(msg, ephemeral=True)
    else:
        try:
            await interaction.response.send_message(f"Erro: {msg}", ephemeral=True)
        except Exception:
            await interaction.followup.send(f"Erro: {msg}", ephemeral=True)


@bot.event
async def on_ready():
    print(f"[BOT] Logado como {bot.user}")
    if not bot.intents.message_content:
        print("[AVISO] MESSAGE CONTENT INTENT DESATIVADO — antilink e logs não vão funcionar!")
    else:
        print("[OK] Message Content Intent ativo.")
    try:
        synced = await bot.tree.sync()
        print(f"[BOT] {len(synced)} comandos registrados globalmente.")
    except Exception as e:
        print(f"[ERRO] Sync: {e}")


@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.guild is None:
        return

    gcfg, _ = get_guild_cfg(message.guild.id)
    if not gcfg.get("antilink_enabled"):
        return

    content = message.content or ""
    if not URL_REGEX.search(content):
        return

    link_roles = gcfg.get("link_roles", [])
    has_link_role = any(r.id in link_roles for r in message.author.roles)
    is_owner = message.author.id == message.guild.owner_id
    is_admin = message.author.guild_permissions.manage_messages

    if has_link_role or is_owner or is_admin:
        return

    try:
        await message.delete()
        await message.channel.send(
            f"{message.author.mention} links não são permitidos aqui.",
            delete_after=6,
        )
    except Exception as e:
        print(f"[ERRO ANTILINK] {e}")


@bot.event
async def on_message_delete(message):
    if message.author.bot:
        return
    if message.guild is None:
        return

    gcfg, _ = get_guild_cfg(message.guild.id)
    log_id = gcfg.get("log_channel")
    if not log_id:
        return
    log_channel = bot.get_channel(log_id)
    if not log_channel:
        return

    e = discord.Embed(title="🗑️  Mensagem Apagada", color=0xED4245, timestamp=datetime.now(timezone.utc))
    e.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
    e.add_field(name="Autor", value=f"{message.author.mention} (`{message.author}`)", inline=True)
    e.add_field(name="Canal", value=message.channel.mention, inline=True)
    e.add_field(name="Autor ID", value=f"`{message.author.id}`", inline=True)
    e.add_field(name="Conteúdo", value=(message.content[:1024] if message.content else "*[sem texto]*"), inline=False)
    if message.attachments:
        e.add_field(name="Anexos", value="\n".join(a.url for a in message.attachments[:5])[:1024], inline=False)
    e.set_footer(text=f"ID Mensagem: {message.id}")
    try:
        await log_channel.send(embed=e)
    except Exception as err:
        print(f"[ERRO LOG DELETE] {err}")


@bot.event
async def on_message_edit(before, after):
    if before.author.bot:
        return
    if before.guild is None:
        return
    if before.content == after.content:
        return

    gcfg, _ = get_guild_cfg(before.guild.id)
    log_id = gcfg.get("log_channel")
    if not log_id:
        return
    log_channel = bot.get_channel(log_id)
    if not log_channel:
        return

    e = discord.Embed(title="✏️  Mensagem Editada", color=0xFEE75C, timestamp=datetime.now(timezone.utc))
    e.set_author(name=str(before.author), icon_url=before.author.display_avatar.url)
    e.add_field(name="Autor", value=f"{before.author.mention} (`{before.author}`)", inline=True)
    e.add_field(name="Canal", value=before.channel.mention, inline=True)
    e.add_field(name="Autor ID", value=f"`{before.author.id}`", inline=True)
    e.add_field(name="Antes", value=before.content[:1024] or "*vazio*", inline=False)
    e.add_field(name="Depois", value=after.content[:1024] or "*vazio*", inline=False)
    e.add_field(name="Link", value=f"[ir para mensagem]({after.jump_url})", inline=False)
    e.set_footer(text=f"ID Mensagem: {before.id}")
    try:
        await log_channel.send(embed=e)
    except Exception as err:
        print(f"[ERRO LOG EDIT] {err}")


@bot.tree.command(name="enviar", description="Envia uma mensagem em um canal específico.")
@app_commands.describe(canal="Canal de destino", mensagem="Texto a enviar", embed="Enviar como embed?", titulo="Título do embed", cor="Cor hex do embed")
@require_auth()
async def enviar(interaction, canal: discord.TextChannel, mensagem: str, embed: bool = False, titulo: str = None, cor: str = None):
    if embed:
        color = discord.Color.blurple()
        if cor:
            try:
                color = discord.Color(int(cor.lstrip("#"), 16))
            except ValueError:
                pass
        e = discord.Embed(description=mensagem, color=color)
        if titulo:
            e.title = titulo
        msg = await canal.send(embed=e)
    else:
        msg = await canal.send(content=mensagem)
    await interaction.response.send_message(f"Enviado em {canal.mention} — ID: `{msg.id}`", ephemeral=True)


@bot.tree.command(name="editar", description="Edita uma mensagem enviada pelo bot.")
@app_commands.describe(canal="Canal", id="ID da mensagem", nova_mensagem="Novo conteúdo")
@require_auth()
async def editar(interaction, canal: discord.TextChannel, id: str, nova_mensagem: str):
    try:
        msg = await canal.fetch_message(int(id))
        if msg.author.id != bot.user.id:
            return await interaction.response.send_message("Só edito mensagens minhas.", ephemeral=True)
        await msg.edit(content=nova_mensagem)
        await interaction.response.send_message("Mensagem editada.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Erro: {e}", ephemeral=True)


@bot.tree.command(name="apagar", description="Apaga uma mensagem do bot.")
@app_commands.describe(canal="Canal", id="ID da mensagem")
@require_auth()
async def apagar(interaction, canal: discord.TextChannel, id: str):
    try:
        msg = await canal.fetch_message(int(id))
        if msg.author.id != bot.user.id:
            return await interaction.response.send_message("Só apago mensagens minhas.", ephemeral=True)
        await msg.delete()
        await interaction.response.send_message("Mensagem apagada.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Erro: {e}", ephemeral=True)


@bot.tree.command(name="info", description="Informações do bot.")
async def info(interaction):
    delta = datetime.now(timezone.utc) - START_TIME
    e = discord.Embed(title="Bot Info", color=discord.Color.blurple())
    e.add_field(name="Servidores", value=str(len(bot.guilds)), inline=True)
    e.add_field(name="Ping", value=f"{round(bot.latency * 1000)}ms", inline=True)
    e.add_field(name="Uptime", value=str(delta).split(".")[0], inline=True)
    e.timestamp = datetime.now(timezone.utc)
    await interaction.response.send_message(embed=e)


def _embed_trancado(canal, motivo=None):
    e = discord.Embed(title="🔴  CANAL TRANCADO", description=f"{canal.mention} está **trancado**.\n\nNenhuma mensagem pode ser enviada enquanto o canal estiver neste estado.", color=0xED4245, timestamp=datetime.now(timezone.utc))
    if motivo:
        e.add_field(name="Motivo", value=motivo, inline=False)
    e.set_footer(text="Use /destrancar para liberar o canal")
    return e


def _embed_destrancado(canal, motivo=None):
    e = discord.Embed(title="🟢  CANAL DESTRANCADO", description=f"{canal.mention} foi **destrancado**.\n\nTodos podem enviar mensagens novamente.", color=0x57F287, timestamp=datetime.now(timezone.utc))
    if motivo:
        e.add_field(name="Motivo", value=motivo, inline=False)
    e.set_footer(text="Canal liberado")
    return e


@bot.tree.command(name="trancar", description="Tranca o canal.")
@app_commands.describe(motivo="Motivo (opcional)")
@require_auth()
async def trancar(interaction, motivo: str = None):
    canal = interaction.channel
    everyone = interaction.guild.default_role
    ow = canal.overwrites_for(everyone)
    ow.send_messages = False
    ow.send_messages_in_threads = False
    ow.create_public_threads = False
    ow.create_private_threads = False
    try:
        await canal.set_permissions(everyone, overwrite=ow, reason=f"Trancado — {motivo or 'sem motivo'}")
    except Exception as e:
        return await interaction.response.send_message(f"Erro: {e}", ephemeral=True)
    if isinstance(canal, discord.ForumChannel):
        try:
            ow_f = canal.overwrites_for(everyone)
            ow_f.create_public_threads = False
            ow_f.create_private_threads = False
            await canal.set_permissions(everyone, overwrite=ow_f)
        except Exception:
            pass
    await canal.send(embed=_embed_trancado(canal, motivo))
    await interaction.response.send_message("Canal trancado.", ephemeral=True)


@bot.tree.command(name="destrancar", description="Destranca o canal.")
@app_commands.describe(motivo="Motivo (opcional)")
@require_auth()
async def destrancar(interaction, motivo: str = None):
    canal = interaction.channel
    everyone = interaction.guild.default_role
    ow = canal.overwrites_for(everyone)
    ow.send_messages = None
    ow.send_messages_in_threads = None
    ow.create_public_threads = None
    ow.create_private_threads = None
    try:
        await canal.set_permissions(everyone, overwrite=ow, reason=f"Destrancado — {motivo or 'sem motivo'}")
    except Exception as e:
        return await interaction.response.send_message(f"Erro: {e}", ephemeral=True)
    await canal.send(embed=_embed_destrancado(canal, motivo))
    await interaction.response.send_message("Canal destrancado.", ephemeral=True)


@bot.tree.command(name="setlogs", description="Define o canal de logs.")
@app_commands.describe(canal="Canal de texto onde os logs serão enviados")
@require_auth()
async def setlogs(interaction, canal: discord.TextChannel):
    gcfg, _ = get_guild_cfg(interaction.guild.id)
    gcfg["log_channel"] = canal.id
    set_guild_cfg(interaction.guild.id, gcfg)
    await interaction.response.send_message(f"Canal de logs definido: {canal.mention}", ephemeral=True)


@bot.tree.command(name="setrolelink", description="Define o cargo que pode enviar links.")
@app_commands.describe(cargo="Cargo autorizado a enviar links")
@require_auth()
async def setrolelink(interaction, cargo: discord.Role):
    gcfg, _ = get_guild_cfg(interaction.guild.id)
    roles = gcfg.get("link_roles", [])
    if cargo.id not in roles:
        roles.append(cargo.id)
    gcfg["link_roles"] = roles
    set_guild_cfg(interaction.guild.id, gcfg)
    await interaction.response.send_message(f"Cargo {cargo.mention} autorizado a enviar links.", ephemeral=True)


@bot.tree.command(name="removerolelink", description="Remove cargo da lista de links.")
@app_commands.describe(cargo="Cargo a remover")
@require_auth()
async def removerolelink(interaction, cargo: discord.Role):
    gcfg, _ = get_guild_cfg(interaction.guild.id)
    roles = gcfg.get("link_roles", [])
    if cargo.id in roles:
        roles.remove(cargo.id)
    gcfg["link_roles"] = roles
    set_guild_cfg(interaction.guild.id, gcfg)
    await interaction.response.send_message(f"Cargo {cargo.mention} removido da lista de links.", ephemeral=True)


@bot.tree.command(name="antilink", description="Ativa/desativa o bloqueio de links.")
@app_commands.describe(estado="on / off")
@app_commands.choices(estado=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
@require_auth()
async def antilink(interaction, estado: app_commands.Choice[str]):
    gcfg, _ = get_guild_cfg(interaction.guild.id)
    gcfg["antilink_enabled"] = (estado.value == "on")
    set_guild_cfg(interaction.guild.id, gcfg)
    await interaction.response.send_message(f"Antilink **{estado.value.upper()}**.", ephemeral=True)


@bot.tree.command(name="autorizar", description="Dá permissão pra alguém usar comandos do bot.")
@app_commands.describe(user="Usuário a autorizar")
@require_auth()
async def autorizar(interaction, user: discord.Member):
    gcfg, _ = get_guild_cfg(interaction.guild.id)
    users = gcfg.get("authorized_users", [])
    if user.id not in users:
        users.append(user.id)
    gcfg["authorized_users"] = users
    set_guild_cfg(interaction.guild.id, gcfg)
    await interaction.response.send_message(f"{user.mention} agora pode usar comandos do bot.", ephemeral=True)


@bot.tree.command(name="desautorizar", description="Remove permissão de alguém.")
@app_commands.describe(user="Usuário a remover")
@require_auth()
async def desautorizar(interaction, user: discord.Member):
    gcfg, _ = get_guild_cfg(interaction.guild.id)
    users = gcfg.get("authorized_users", [])
    if user.id in users:
        users.remove(user.id)
    gcfg["authorized_users"] = users
    set_guild_cfg(interaction.guild.id, gcfg)
    await interaction.response.send_message(f"{user.mention} não pode mais usar comandos do bot.", ephemeral=True)


@bot.tree.command(name="autorizados", description="Lista usuários autorizados.")
@require_auth()
async def autorizados(interaction):
    gcfg, _ = get_guild_cfg(interaction.guild.id)
    users = gcfg.get("authorized_users", [])
    if not users:
        return await interaction.response.send_message("Nenhum usuário autorizado ainda (além do dono).", ephemeral=True)
    linhas = "\n".join(f"<@{u}> (`{u}`)" for u in users)
    e = discord.Embed(title="Usuários autorizados", description=linhas, color=discord.Color.blurple())
    await interaction.response.send_message(embed=e, ephemeral=True)


@bot.tree.command(name="entrar", description="Faz o bot entrar num canal de voz.")
@app_commands.describe(canal="Canal de voz")
@require_auth()
async def entrar(interaction, canal: discord.VoiceChannel):
    try:
        perms = canal.permissions_for(interaction.guild.me)
        if not perms.connect:
            return await interaction.response.send_message(
                f"Sem permissão de **Conectar** em {canal.mention}.", ephemeral=True
            )
        vc = interaction.guild.voice_client
        if vc and vc.is_connected():
            await vc.move_to(canal)
        else:
            await canal.connect(timeout=15.0, reconnect=True)
        await interaction.response.send_message(f"Entrei em {canal.mention}.", ephemeral=True)
    except Exception as e:
        err = str(e)
        if "PyNaCl" in err or "nacl" in err.lower():
            msg = "Falta PyNaCl. Roda: `pip install pynacl` e reinicia o bot."
        elif "timed out" in err.lower():
            msg = "Timeout ao conectar. Verifica se o canal existe e o bot tem permissão."
        else:
            msg = f"Erro: {err}"
        try:
            await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            await interaction.followup.send(msg, ephemeral=True)


@bot.tree.command(name="sair", description="Faz o bot sair do canal de voz.")
@require_auth()
async def sair(interaction):
    vc = interaction.guild.voice_client
    if not vc:
        return await interaction.response.send_message("Não estou em call.", ephemeral=True)
    try:
        await vc.disconnect(force=True)
        await interaction.response.send_message("Saí da call.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Erro: {e}", ephemeral=True)


@bot.tree.command(name="config", description="Mostra a configuração atual do servidor.")
@require_auth()
async def config(interaction):
    gcfg, _ = get_guild_cfg(interaction.guild.id)
    log_id = gcfg.get("log_channel")
    log_str = f"<#{log_id}>" if log_id else "não definido"
    roles = gcfg.get("link_roles", [])
    roles_str = ", ".join(f"<@&{r}>" for r in roles) if roles else "nenhum"
    users = gcfg.get("authorized_users", [])
    users_str = ", ".join(f"<@{u}>" for u in users) if users else "nenhum"
    content_status = "ATIVO" if bot.intents.message_content else "DESATIVADO (antilink/logs quebrados)"
    e = discord.Embed(title="Configuração do Servidor", color=discord.Color.blurple())
    e.add_field(name="Message Content Intent", value=content_status, inline=False)
    e.add_field(name="Canal de logs", value=log_str, inline=False)
    e.add_field(name="Antilink", value="ON" if gcfg.get("antilink_enabled") else "OFF", inline=True)
    e.add_field(name="Cargos com link", value=roles_str, inline=False)
    e.add_field(name="Usuários autorizados", value=users_str, inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        print("[ERRO FATAL] A variável de ambiente DISCORD_TOKEN não foi configurada!")
    else:
        manter_online()
        bot.run(TOKEN)
