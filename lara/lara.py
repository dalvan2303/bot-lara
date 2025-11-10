# filepath: /home/joao/Área de trabalho/lara/lara.py
# ...existing code...
import os
import re
import time
import glob
import asyncio
from functools import partial

from neonize.aioze.client import NewAClient
from neonize.aioze.events import MessageEv, ConnectedEv

# Import dinâmico e robusto para PollVoteEv
try:
    from neonize.proto.wa_handler import PollVoteEv
except Exception:
    PollVoteEv = None
    tried = []
    candidates = [
        "neonize.events.PollVoteEv",
        "neonize.events.poll.PollVoteEv",
        "neonize.proto.poll.PollVoteEv",
        "neonize.proto.events.PollVoteEv",
        "neonize.proto.wa_handler.PollVoteEv",
    ]
    for path in candidates:
        try:
            module_name, cls_name = path.rsplit(".", 1)
            mod = __import__(module_name, fromlist=[cls_name])
            PollVoteEv = getattr(mod, cls_name)
            tried.append(path)
            break
        except Exception as e:
            tried.append(f"{path} -> {e.__class__.__name__}")
    if PollVoteEv is None:
        try:
            import pkgutil, inspect, importlib, neonize
            for finder, name, ispkg in pkgutil.walk_packages(neonize.__path__, neonize.__name__ + "."):
                try:
                    m = importlib.import_module(name)
                    for _n, obj in inspect.getmembers(m, inspect.isclass):
                        nlow = _n.lower()
                        if "poll" in nlow or "vote" in nlow:
                            PollVoteEv = obj
                            tried.append(f"found:{name}.{_n}")
                            break
                    if PollVoteEv:
                        break
                except Exception:
                    continue
        except Exception:
            pass
    if PollVoteEv is None:
        print("Aviso: PollVoteEv não encontrado. Enquetes ficarão em modo fallback. Tentativas:", tried)

from neonize.utils import build_jid
from neonize.utils.enum import VoteType

from openai import OpenAI
import yt_dlp

# --- Config ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY não definido. Exporte: export OPENAI_API_KEY='sua_chave_aqui'")
client_openai = OpenAI(api_key=OPENAI_API_KEY)

TEMP_DIR = './temp'
os.makedirs(TEMP_DIR, exist_ok=True)
DOWNLOADS_DIR = os.path.join(TEMP_DIR, 'downloads')
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

TEST_GROUP_JID = None

# --- IA Sync ---
def _sync_responder_como_membro(texto_mensagem):
    prompt_sistema = (
        "Você é uma inteligência artificial chamada Lara. Você é um membro ativo, engraçado e informal "
        "de um grupo de WhatsApp. Responda de forma concisa e amigável."
    )
    try:
        response = client_openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "system", "content": prompt_sistema}, {"role": "user", "content": texto_mensagem}],
            max_tokens=150,
            temperature=0.8
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Erro na API da OpenAI (Chat): {e}")
        return "Ih, deu ruim na minha IA aqui. Tenta de novo!"

def _sync_tts_gerar_audio(texto, chat_id):
    audio_path = os.path.join(TEMP_DIR, f"tts_{chat_id}_{int(time.time())}.mp3")
    try:
        response = client_openai.audio.speech.create(
            model="tts-1",
            voice="nova",
            input=texto,
        )
        response.stream_to_file(audio_path)
        return audio_path
    except Exception as e:
        print(f"Erro na API da OpenAI (TTS): {e}")
        return None

# --- Download sync ---
def _sync_baixar_e_enviar_midia(client: NewAClient, chat_id, url, tipo_midia):
    temp_filename_base = os.path.join(DOWNLOADS_DIR, f"{chat_id}_{int(time.time())}")
    downloaded_file = None

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
        'outtmpl': f'{temp_filename_base}.%(ext)s',
        'noplaylist': True, 'verbose': False, 'quiet': True, 'merge_output_format': 'mp4'
    }

    if tipo_midia == 'musica':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
            'outtmpl': f'{temp_filename_base}.%(ext)s', 'ffmpeg_location': 'ffmpeg',
        })
        expected_extension = 'mp3'
    else:
        expected_extension = 'mp4'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            search_pattern = f"{temp_filename_base}.{expected_extension}"
            files_found = glob.glob(search_pattern)
            if not files_found:
                files_found = glob.glob(f"{temp_filename_base}.*")
            if not files_found:
                raise FileNotFoundError("O yt-dlp não encontrou o arquivo final após o download.")

            downloaded_file = files_found[0]
            if os.path.exists(downloaded_file) and os.path.getsize(downloaded_file) > 0:
                return {
                    'status': 'success', 'tipo': tipo_midia, 'file_path': downloaded_file,
                    'title': info_dict.get('title', tipo_midia),
                }
            else:
                raise FileNotFoundError(f"Arquivo encontrado ({downloaded_file}) mas está vazio ou não é válido.")
    except Exception as e:
        return {'status': 'error', 'message': f"❌ Erro ao baixar a mídia: {e}", 'file_path': downloaded_file}
    finally:
        pass

# --- Group management ---
async def handle_group_management(client: NewAClient, msg, partes, chat_id):
    global TEST_GROUP_JID
    comando = partes[0].lower()
    group_jid = chat_id
    if not group_jid.is_group and comando != '/criargrupo':
        await client.reply_message("Este comando só pode ser usado em grupos. 🤷‍♀️", msg)
        return

    try:
        if comando == '/criargrupo':
            if len(partes) < 3:
                await client.reply_message("Use: */criargrupo [Nome do Grupo] | [Número1,Número2,...]*", msg)
                return
            nome = partes[1].strip()
            numeros = partes[2].split(',')
            participants = [build_jid(num.strip()) for num in numeros if num.strip().isdigit()]
            if not participants:
                await client.reply_message("Nenhum número de participante válido foi fornecido.", msg)
                return
            group_info = await client.create_group(nome, participants)
            TEST_GROUP_JID = group_info.jid
            await client.reply_message(f"🎉 Grupo criado: *{group_info.group_name}* (ID: {TEST_GROUP_JID.user})", msg)
            return
        elif comando == '/info':
            group_info = await client.get_group_info(group_jid)
            participants_count = len(group_info.participants) if group_info.participants else 0
            info_text = (
                f"📋 *Informações do Grupo:* \n"
                f"Nome: {group_info.group_name}\n"
                f"Descrição: {group_info.group_desc if group_info.group_desc else 'Nenhuma'}\n"
                f"Participantes: {participants_count}"
            )
            await client.reply_message(info_text, msg)
            return
        elif comando in ('/add', '/remover'):
            if len(partes) < 2:
                await client.reply_message(f"Use: *{comando} [Número]*", msg)
                return
            user_number = partes[1].strip()
            if not user_number.isdigit():
                await client.reply_message("Por favor, forneça um número de telefone válido.", msg)
                return
            user_jid = [build_jid(user_number)]
            action = "add" if comando == '/add' else "remove"
            await client.update_group_participants(group_jid, user_jid, action)
            await client.reply_message(f"✅ Participante *{user_number}* {action} ao grupo.", msg)
            return
        elif comando == '/mudar_nome':
            if len(partes) < 2:
                await client.reply_message("Use: */mudar_nome [Novo Nome]*", msg)
                return
            novo_nome = partes[1]
            await client.update_group_name(group_jid, novo_nome)
            await client.reply_message(f"✅ Nome do grupo alterado para: *{novo_nome}*", msg)
            return
        elif comando == '/mudar_descricao':
            if len(partes) < 2:
                await client.reply_message("Use: */mudar_descricao [Nova Descrição]*", msg)
                return
            nova_desc = partes[1]
            await client.update_group_description(group_jid, nova_desc)
            await client.reply_message(f"✅ Descrição do grupo alterada.", msg)
            return
    except Exception as e:
        await client.reply_message(f"❌ Erro ao executar o comando de grupo: {e}. Verifique se Lara é *Admin*.", msg)

# --- Main ---
async def main():
    client = NewAClient("lara_bot")

    @client.event
    async def on_connected(client: NewAClient, event: ConnectedEv):
        print("🎉 Lara conectada e pronta para interagir!")

    @client.event
    async def on_poll_vote(client: NewAClient, event):
        try:
            voter_jid = event.info.message_source.sender
            voter_name = voter_jid.user
            poll_update = event.message.poll_update_message
            if not poll_update or not poll_update.vote:
                return
            selected_options = [opt.name for opt in poll_update.vote.selected_options]
            print(f"📊 {voter_name} votou em: {selected_options} na enquete {poll_update.poll_creator.user}")
        except Exception as e:
            print(f"on_poll_vote: evento não compatível: {e}")

    @client.event
    async def on_message(client: NewAClient, event: MessageEv):
        msg = event.message
        if not msg.conversation or msg.info.is_from_me:
            return
        texto_recebido = msg.conversation.strip()
        chat_id = msg.info.chat

        if texto_recebido.lower().startswith('/enquete'):
            if not chat_id.is_group:
                await client.reply_message("Enquetes só podem ser criadas em grupos. 🧐", msg)
                return
            partes = texto_recebido.split('|')
            if len(partes) < 3:
                await client.reply_message("Use: */enquete [Pergunta] | [Opção1] | [Opção2]...*", msg)
                return
            pergunta = partes[0].replace('/enquete', '').strip()
            opcoes = [p.strip() for p in partes[1:] if p.strip()]
            if len(opcoes) < 2:
                await client.reply_message("Você precisa de pelo menos 2 opções para criar uma enquete.", msg)
                return
            try:
                poll_msg = client.build_poll_vote_creation(pergunta, opcoes, VoteType.SINGLE_SELECT)
                await client.send_message(chat_id, message=poll_msg)
                await client.send_message(chat_id, "📊 Enquete criada! Votem! (Apenas uma opção)")
            except Exception as e:
                await client.reply_message(f"❌ Erro ao criar enquete (Versão do neonize): {e}", msg)
                return

        elif texto_recebido.lower().startswith(('/video', '/musica')):
            partes = texto_recebido.split(maxsplit=1)
            if len(partes) < 2 or not re.match(r'https?://', partes[1]):
                await client.reply_message("Comando inválido. Use */video [link]* ou */musica [link]*.", msg)
                return
            await client.reply_message("⏳ Processando download...", msg)
            resultado = await asyncio.to_thread(_sync_baixar_e_enviar_midia, client, chat_id, partes[1], partes[0].lower().replace('/', ''))
            if resultado['status'] == 'success':
                try:
                    if resultado['tipo'] == 'musica':
                        await client.send_audio(chat_id, resultado['file_path'], caption=f"🎵 {resultado['title']}")
                    else:
                        await client.send_video(chat_id, resultado['file_path'], caption=f"🎬 {resultado['title']}")
                    status_message = f"✅ Pronto! '{resultado['title']}' enviado."
                    try:
                        fp = resultado.get('file_path')
                        if fp and os.path.exists(fp):
                            os.remove(fp)
                    except Exception as e:
                        print(f"Aviso: não foi possível remover arquivo temporário: {e}")
                except Exception as e:
                    status_message = f"❌ Erro ao enviar a mídia via WhatsApp: {e}"
            else:
                status_message = resultado['message']
            await client.send_message(chat_id, status_message)

        elif texto_recebido.lower().startswith(('/criargrupo', '/info', '/add', '/remover', '/mudar_nome', '/mudar_descricao')):
            if texto_recebido.lower().startswith('/criargrupo'):
                partes = texto_recebido.split('|', maxsplit=2)
            else:
                partes = texto_recebido.split(maxsplit=2)
            await handle_group_management(client, msg, partes, chat_id)

        elif texto_recebido.lower().startswith("lara") or msg.info.mentioned_jids:
            if texto_recebido.lower().startswith("lara"):
                texto_para_ia = texto_recebido[4:].strip()
            else:
                texto_para_ia = texto_recebido
            if not texto_para_ia:
                await client.reply_message("Diga algo, não sou adivinha! 😉", msg)
                return
            await client.send_chat_state(chat_id, "composing")
            resposta_texto = await asyncio.to_thread(_sync_responder_como_membro, texto_para_ia)
            audio_path = await asyncio.to_thread(_sync_tts_gerar_audio, resposta_texto, chat_id.user)
            if audio_path and os.path.exists(audio_path):
                await client.send_audio(chat_id, audio_path)
                await client.send_message(chat_id, f"*(Lara em Áudio)*:\n{resposta_texto}")
                try:
                    os.remove(audio_path)
                except Exception as e:
                    print(f"Aviso: Falha ao remover arquivo TTS temporário: {e}")
            else:
                await client.reply_message(f"🚨 Falha ao gerar áudio. {resposta_texto}", msg)
            return

        elif texto_recebido.lower() in ("oi", "olá"):
            await client.reply_message("Fala, galera! 👋 Eu sou a Lara!", msg)

    # checagens iniciais
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY não definido.")
    try:
        import subprocess
        subprocess.run(["ffmpeg", "-version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        print("Aviso: ffmpeg não disponível no PATH. O download/merge pode falhar.")

    backoff = 1
    while True:
        try:
            print("Conectando ao Neonize...")
            await client.connect()
            backoff = 1
            while True:
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"Erro na conexão do client: {e}. Tentando reconectar em {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)

if __name__ == "__main__":
    try:
        print("Iniciando Lara, o bot assíncrono...")
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot Lara desligado. Tchau!")
    except Exception as e:
        print(f"Ocorreu um erro fatal: {e}")

web: python3 lara.py
