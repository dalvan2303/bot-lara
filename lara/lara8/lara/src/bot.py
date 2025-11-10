class Bot:
    def __init__(self):
        self.api_keys = self.load_config()
        self.initialize()

    def load_config(self):
        # Carregar configurações do arquivo de configuração
        from config import Config
        return Config().get_api_keys()

    def initialize(self):
        # Inicializar o bot e configurar o loop de eventos
        print("Bot inicializado com as seguintes chaves de API:", self.api_keys)

    def run(self):
        # Lógica principal do bot
        print("Bot está rodando...")

if __name__ == "__main__":
    bot = Bot()
    bot.run()