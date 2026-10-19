"""Validation and durable delivery ledger. No credentials or message bodies in logs."""
import csv
import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlparse


def parse_links(text):
    result, seen = [], set()
    for line in text.splitlines():
        value = line.strip()
        if not value:
            continue
        if value.startswith('@'):
            value = 'https://t.me/' + value[1:]
        if value.startswith(('t.me/', 'telegram.me/')):
            value = 'https://' + value
        url = urlparse(value)
        if url.scheme != 'https' or url.netloc.lower() not in ('t.me', 'telegram.me'):
            raise ValueError('Допустимы только ссылки https://t.me/… или @имя.')
        path = url.path.strip('/')
        private = path.startswith(('+', 'joinchat/'))
        token = path.removeprefix('+').removeprefix('joinchat/') if private else path
        if not re.fullmatch(r'[A-Za-z0-9_-]+' if private else r'[A-Za-z][A-Za-z0-9_]{3,31}', token):
            raise ValueError('Некорректная ссылка на группу.')
        key = ('invite:' + token) if private else ('public:' + token.lower())
        if key not in seen:
            result.append((key, token, private))
            seen.add(key)
    return result


def fingerprint(peer, message):
    return hashlib.sha256(f'{peer}\0{message}'.encode()).hexdigest()


class Ledger:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS events (time TEXT, peer TEXT, digest TEXT, status TEXT, detail TEXT)')
        self.db.commit()

    def record(self, peer, message, status, detail=''):
        self.db.execute('INSERT INTO events VALUES (?,?,?,?,?)',
                        (datetime.now(timezone.utc).isoformat(), str(peer), fingerprint(peer, message), status, detail))
        self.db.commit()

    def previous(self, peer, message):
        return self.db.execute('SELECT status FROM events WHERE digest=? ORDER BY rowid DESC LIMIT 1',
                               (fingerprint(peer, message),)).fetchone()

    def export(self, path):
        with open(path, 'w', encoding='utf-8-sig', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(['Время UTC', 'ID группы', 'Хеш сообщения', 'Статус', 'Детали'])
            for row in self.db.execute('SELECT * FROM events ORDER BY rowid'):
                writer.writerow(["'" + v if str(v).startswith(('=', '+', '-', '@')) else v for v in row])
