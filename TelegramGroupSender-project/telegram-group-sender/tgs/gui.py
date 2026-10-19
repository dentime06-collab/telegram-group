import asyncio
import os
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QPlainTextEdit, QTableWidget, QTableWidgetItem,
    QMessageBox, QInputDialog, QFileDialog, QProgressBar, QSplitter)
from telethon import errors
from .core import Ledger, parse_links
from .service import Service, Worker
from .storage import Vault


class Bridge(QObject):
    done = Signal(object, object, object)


class Window(QMainWindow):
    def __init__(self, data_dir):
        super().__init__()
        self.setWindowTitle('Telegram Group Sender')
        self.resize(1100, 900)
        self.vault = Vault()
        self.service = Service(self.vault)
        self.worker = Worker()
        self.ledger = Ledger(data_dir / 'history.sqlite3')
        self.bridge = Bridge()
        self.bridge.done.connect(self.completed)
        self.busy = False
        self.authorized = False
        self.groups = []
        self.queue = []
        self.paused = True
        self.scanning = False
        self.closing = False
        self.run_text = ''
        root = QWidget()
        layout = QVBoxLayout(root)
        self.setCentralWidget(root)
        layout.addWidget(QLabel('TELEGRAM GROUP SENDER  •  Публикации с вашим подтверждением'))
        row = QHBoxLayout()
        self.api_id = QLineEdit(); self.api_id.setPlaceholderText('API ID')
        self.api_hash = QLineEdit(); self.api_hash.setPlaceholderText('API Hash'); self.api_hash.setEchoMode(QLineEdit.Password)
        self.phone = QLineEdit(); self.phone.setPlaceholderText('+373…')
        for w in (self.api_id, self.api_hash, self.phone): row.addWidget(w)
        self.connect_btn = QPushButton('Подключиться'); self.connect_btn.clicked.connect(self.connect_account); row.addWidget(self.connect_btn)
        self.code_btn = QPushButton('Получить код'); self.code_btn.clicked.connect(self.request_code); row.addWidget(self.code_btn)
        layout.addLayout(row)
        self.auth = QLabel('Не подключено. API ID и API Hash: my.telegram.org → API development tools.')
        layout.addWidget(self.auth)
        split = QSplitter()
        self.links = QPlainTextEdit(); self.links.setPlaceholderText('Ссылки на группы — по одной на строку\nhttps://t.me/group\nhttps://t.me/+invite')
        self.message = QPlainTextEdit(); self.message.setPlaceholderText('Текст сообщения. Unicode, эмодзи и переносы строк. Без разметки.')
        split.addWidget(self.links); split.addWidget(self.message); layout.addWidget(split)
        row = QHBoxLayout()
        self.check_btn = QPushButton('Проверить группы'); self.check_btn.clicked.connect(self.check_groups); row.addWidget(self.check_btn)
        self.join_btn = QPushButton('Вступить в выделенную группу'); self.join_btn.clicked.connect(self.join_group); row.addWidget(self.join_btn)
        preview = QPushButton('Предпросмотр'); preview.clicked.connect(self.preview); row.addWidget(preview)
        layout.addLayout(row)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Выбор', 'Группа', 'Участие', 'Статус'])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(1, 360)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        for label, callback in [('Начать', self.start), ('Остановить', self.stop), ('Продолжить', self.resume), ('Экспорт CSV', self.export)]:
            button = QPushButton(label); button.clicked.connect(callback); row.addWidget(button)
        layout.addLayout(row)
        self.progress = QProgressBar(); layout.addWidget(self.progress)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(2000); layout.addWidget(self.log)
        self.status = QLabel('Готово'); layout.addWidget(self.status)
        try:
            self.api_id.setText(self.vault.get('api_id') or '')
            self.api_hash.setText(self.vault.get('api_hash') or '')
        except Exception:
            self.log.appendPlainText('Keychain недоступен. Подключение потребует исправления доступа к хранилищу.')

    def notice(self, text):
        QMessageBox.information(self, 'Telegram Group Sender', text)

    def confirm(self, title, text):
        box = QMessageBox(self)
        box.setWindowTitle(title); box.setTextFormat(Qt.PlainText); box.setText(text)
        yes = box.addButton('Подтвердить', QMessageBox.AcceptRole)
        box.addButton('Отмена', QMessageBox.RejectRole)
        box.setDefaultButton(yes)
        box.exec()
        return box.clickedButton() == yes

    def launch(self, coroutine, callback):
        if self.busy:
            coroutine.close()
            return False
        self.busy = True
        self.status.setText('Выполняется запрос…')
        future = self.worker.submit(coroutine)
        def done(f):
            try: result, error = f.result(), None
            except Exception as exc: result, error = None, exc
            self.bridge.done.emit(callback, result, error)
        future.add_done_callback(done)
        return True

    def error_text(self, error):
        if isinstance(error, errors.FloodWaitError):
            self.service.flood(error.seconds)
            return f'Ограничение Telegram: ждать {error.seconds} с. Автоповтора нет.'
        if isinstance(error, errors.InviteRequestSentError):
            return 'Заявка на вступление отправлена. Дождитесь одобрения и проверьте группу снова.'
        if isinstance(error, ValueError): return str(error)
        names = {'PhoneCodeInvalidError': 'Неверный код входа.', 'PhoneCodeExpiredError': 'Код истёк. Запросите новый.',
                 'PasswordHashInvalidError': 'Неверный пароль 2FA.', 'SessionPasswordNeededError': 'Требуется пароль 2FA.',
                 'ChatWriteForbiddenError': 'Публикация запрещена.', 'PeerFloodError': 'Telegram ограничил аккаунт. Отправка остановлена.',
                 'SlowModeWaitError': 'В группе действует медленный режим. Повторите позже с новым подтверждением.',
                 'InviteHashExpiredError': 'Приглашение истекло.', 'InviteHashInvalidError': 'Приглашение недействительно.'}
        return names.get(type(error).__name__, f'Ошибка: {type(error).__name__}. Проверьте подключение и состояние аккаунта.')

    def completed(self, callback, result, error):
        self.busy = False
        self.status.setText('Готово')
        if self.closing:
            self.begin_shutdown(); return
        callback(result, error)

    def connect_account(self):
        if self.busy or self.queue or self.scanning: return
        try:
            api_id = int(self.api_id.text())
            api_hash = self.api_hash.text().strip()
            if api_id <= 0 or len(api_hash) != 32 or any(c not in '0123456789abcdefABCDEF' for c in api_hash):
                raise ValueError('Проверьте API ID и API Hash.')
            self.vault.set('api_id', str(api_id)); self.vault.set('api_hash', api_hash)
        except Exception:
            self.notice('Проверьте API ID / API Hash и доступ к Keychain.'); return
        self.authorized = False
        def done(result, error):
            if error: self.notice(self.error_text(error)); return
            self.authorized = result
            self.auth.setText('Вход выполнен. Сессия сохранена в Keychain.' if result else 'Подключено. Укажите телефон и получите код.')
        self.launch(self.service.connect(api_id, api_hash), done)

    def request_code(self):
        if not self.service.client or self.busy or self.queue or self.scanning or self.authorized: return
        def done(result, error):
            if error: self.notice(self.error_text(error)); return
            code, ok = QInputDialog.getText(self, 'Авторизация', 'Код из Telegram или SMS:')
            if ok and code.strip(): self.launch(self.service.login(code=code.strip()), logged)
        def logged(result, error):
            if isinstance(error, errors.SessionPasswordNeededError):
                password, ok = QInputDialog.getText(self, 'Двухфакторная защита', 'Пароль 2FA:', QLineEdit.Password)
                if ok: self.launch(self.service.login(password=password), logged)
                return
            if error: self.notice(self.error_text(error)); return
            self.authorized = True; self.auth.setText('Вход выполнен. Сессия сохранена в Keychain.')
        self.launch(self.service.request_code(self.phone.text().strip()), done)

    def check_groups(self):
        if not self.authorized or self.busy or self.queue or self.scanning: return
        try: self.pending_links = parse_links(self.links.toPlainText())
        except ValueError as exc: self.notice(str(exc)); return
        self.groups = []; self.table.setRowCount(0); self.scanning = True
        self.next_check()

    def next_check(self):
        if not self.pending_links or not self.scanning:
            self.scanning = False; return
        link = self.pending_links.pop(0)
        def done(group, error):
            if error:
                group = dict(link=link, title=link[0], member=False, allowed=False, error=self.error_text(error))
                if isinstance(error, (errors.FloodWaitError, errors.PeerFloodError)): self.scanning = False
            if not group.get('error') and any(g.get('peer') == group.get('peer') for g in self.groups if g.get('peer')):
                self.next_check(); return
            self.groups.append(group); self.render(); self.next_check()
        self.launch(self.service.inspect(link), done)

    def render(self):
        self.table.setRowCount(len(self.groups))
        for i, g in enumerate(self.groups):
            choice = QTableWidgetItem()
            choice.setFlags(Qt.ItemIsEnabled | (Qt.ItemIsUserCheckable if g['allowed'] else Qt.NoItemFlags))
            choice.setCheckState(Qt.Unchecked); self.table.setItem(i, 0, choice)
            values = [g['title'], 'Да' if g['member'] else 'Нет', g.get('error') or ('Можно публиковать' if g['allowed'] else 'Нет участия / права')]
            for column, value in enumerate(values, 1):
                item = QTableWidgetItem(value); item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable); self.table.setItem(i, column, item)

    def join_group(self):
        i = self.table.currentRow()
        if i < 0 or self.busy or self.queue or self.scanning: return
        group = self.groups[i]
        if group['member']: return
        if not self.confirm('Вступление', f"Вступить в группу «{group['title']}»? Для закрытой группы может быть отправлена заявка."): return
        def done(result, error):
            if error: self.notice(self.error_text(error)); return
            self.groups[i] = result; self.render()
        self.launch(self.service.inspect(group['link'], join=True), done)

    def preview(self):
        box = QMessageBox(self); box.setWindowTitle('Предпросмотр • обычный текст')
        box.setTextFormat(Qt.PlainText); box.setText(self.message.toPlainText() or 'Сообщение пустое'); box.exec()

    def start(self):
        if not self.authorized or self.busy or self.scanning or self.queue: return
        text = self.message.toPlainText()
        if not text.strip() or len(text.encode('utf-16-le')) // 2 > 4096:
            self.notice('Введите сообщение длиной до 4096 единиц UTF-16.'); return
        self.queue = [g for i, g in enumerate(self.groups) if g['allowed'] and self.table.item(i, 0).checkState() == Qt.Checked]
        if not self.queue: self.notice('Выберите группы, где публикация разрешена правилами группы.'); return
        self.run_text = text
        self.progress.setRange(0, len(self.queue)); self.progress.setValue(0)
        self.paused = False; self.next_send()

    def stop(self):
        self.paused = True; self.scanning = False
        self.status.setText('Остановлено. Уже начатый запрос может завершиться.')

    def resume(self):
        if self.busy or not self.queue: return
        self.paused = False; self.next_send()

    def next_send(self):
        if self.paused or not self.queue: return
        group = self.queue[0]; text = self.run_text
        previous = self.ledger.previous(group['peer'], text)
        warning = '\nВ истории уже есть попытка с таким текстом. Проверьте чат во избежание дубликата.\n' if previous else '\n'
        if not self.confirm('Подтверждение каждой отправки', f"Группа: {group['title']}\n{warning}\n{text}\n\nПодтверждаю, что сообщение разрешено правилами этой группы. Отправить?"):
            self.paused = True; return
        # Commit before network I/O: a crash is an ambiguous attempt, never an automatic retry.
        self.ledger.record(group['peer'], text, 'начато', 'Проверьте чат, если результат неизвестен')
        def done(result, error):
            status = 'ошибка / результат может быть неизвестен' if error else 'отправлено'
            detail = self.error_text(error) if error else f'ID сообщения: {result}'
            self.ledger.record(group['peer'], text, status, detail)
            self.log.appendPlainText(f"{group['title']}: {status}. {detail}")
            self.queue.pop(0); self.progress.setValue(self.progress.value() + 1)
            if error: self.paused = True
            QTimer.singleShot(0, self.next_send)
        self.launch(self.service.send(group, text), done)

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Экспорт отчёта', 'telegram-report.csv', 'CSV (*.csv)')
        if path:
            try: self.ledger.export(path)
            except OSError: self.notice('Не удалось сохранить CSV.')

    def begin_shutdown(self):
        async def shutdown():
            if self.service.client: await self.service.client.disconnect()
        self.closing = False
        self.launch(shutdown(), lambda *_: QApplication.instance().quit())

    def closeEvent(self, event):
        event.ignore(); self.paused = True; self.scanning = False; self.hide()
        if self.busy: self.closing = True
        else: self.begin_shutdown()


def main(smoke=False):
    os.umask(0o077)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyle('Fusion')
    app.setStyleSheet('''QWidget { background: #151b26; color: #e7edf7; font-size: 13px; }
        QLineEdit,QPlainTextEdit,QTableWidget {background:#202938; border:1px solid #35445b; border-radius:6px; padding:7px;}
        QPushButton {background:#287bb5; border:0; border-radius:6px; padding:10px;}
        QPushButton:hover {background:#3597d6;} QHeaderView::section {background:#27364b; padding:7px;}
        QProgressBar {border:1px solid #35445b; text-align:center;} QProgressBar::chunk {background:#287bb5;}''')
    data = Path.home() / 'Library' / 'Application Support' / 'TelegramGroupSender'
    if smoke:
        import tempfile
        data = Path(tempfile.mkdtemp(prefix='tgs-smoke-'))
    data.mkdir(parents=True, exist_ok=True); data.chmod(0o700)
    window = Window(data); window.show()
    if smoke: QTimer.singleShot(600, app.quit)
    return app.exec()
