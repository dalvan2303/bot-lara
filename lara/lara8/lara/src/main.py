# main.py

from bot import Bot
import config

def main():
    # Inicializa o bot com as configurações necessárias
    bot = Bot(config.API_KEY, config.OTHER_CONFIG)
    
    # Inicia o loop de eventos do bot
    bot.run()

if __name__ == "__main__":
    main()