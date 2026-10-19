import keyring


class Vault:
    service = 'TelegramGroupSender'

    def get(self, name):
        return keyring.get_password(self.service, name)

    def set(self, name, value):
        keyring.set_password(self.service, name, value)
