# Деплой на сервер (чтобы бот работал 24/7, а не только когда открыт терминал)

Этот гайд я не мог протестировать на живом сервере (у меня его нет) —
команды проверены по синтаксису и логике, но при реальном деплое
что-то может отличаться в зависимости от твоего провайдера. Если
что-то не сработает как описано — пришли текст ошибки, разберёмся.

## Что нужно

- Любой VPS с Ubuntu 22.04 или 24.04. Самый дешёвый тариф с запасом
  хватит — бот лёгкий (SQLite, один процесс на Python, никакого
  постоянного высокого потребления CPU/RAM).
- **Важный плюс**: бот работает через long polling (сам ходит к
  Telegram, а не наоборот), поэтому **не нужен домен, SSL-сертификат
  или открытый входящий порт** — только исходящий доступ в интернет,
  который есть у любого VPS по умолчанию.

## 1. Первоначальная настройка сервера

Подключись по SSH (провайдер даст IP и root-пароль или SSH-ключ при
создании сервера):

```bash
ssh root@<IP-сервера>
```

Создай отдельного пользователя для бота — не работать от root:

```bash
adduser botuser
usermod -aG sudo botuser   # чтобы мог себе ставить пакеты через sudo
su - botuser
```

Установи Python 3.12+ (на свежем Ubuntu 24.04 он уже системный) и
инструменты:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip sqlite3
```

## 2. Перенос проекта на сервер

Проще всего — заархивировать проект у себя и скопировать через `scp`
(с твоего Mac, не с сервера):

```bash
# на твоём Mac, в папке, где лежит project/
zip -r podselenie-bot.zip project \
  -x "*.pyc" -x "*__pycache__*" -x "project/.env" -x "project/bot.db*"
scp podselenie-bot.zip botuser@<IP-сервера>:~/
```

(`.env` и `bot.db` специально исключены — это твои локальные тестовые
файлы, на сервере им взяться неоткуда и не надо: `.env` заведёшь заново
с реальными продовыми значениями, `bot.db` создастся сам с нуля.)

На сервере:

```bash
cd ~
unzip podselenie-bot.zip
mv project podselenie-bot
cd podselenie-bot
```

## 3. Установка зависимостей

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
deactivate
```

## 4. Настройка `.env`

```bash
cp .env.example .env
nano .env
```

Впиши реальные `BOT_TOKEN` и `ADMIN_ID`, как раньше. `DB_PATH` можно
оставить `bot.db` — файл создастся в рабочей папке бота.

Ограничь права на файл — там токен бота:

```bash
chmod 600 .env
```

## 5. Systemd-служба — автозапуск и перезапуск при сбое

```bash
sudo cp ~/podselenie-bot/deploy/podselenie-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now podselenie-bot
```

Проверь, что запустился:

```bash
sudo systemctl status podselenie-bot
```

Должно быть `active (running)`. Если нет — смотри логи:

```bash
journalctl -u podselenie-bot -f
```

(`-f` — следить за логами в реальном времени, `Ctrl+C` чтобы выйти)

### Полезные команды на будущее

```bash
sudo systemctl restart podselenie-bot   # перезапустить (например, после обновления кода)
sudo systemctl stop podselenie-bot      # остановить
journalctl -u podselenie-bot -n 100     # последние 100 строк лога
```

Файл службы уже настроен на `Restart=on-failure` — если бот упадёт с
ошибкой, systemd поднимет его заново сам через 10 секунд. Если упадёт
сервер целиком — служба запустится автоматически при загрузке
(`enable` уже это делает).

## 6. Бэкапы базы данных

**Важно**: с недавних пор БД работает в WAL-режиме (см.
`database/database.py`) — это значит, что часть свежих данных может
физически лежать не в `bot.db`, а во временном `bot.db-wal`, пока не
"слилось" с основным файлом. Простое копирование `cp bot.db backup.db`
может потерять эти данные. Поэтому в архиве есть `deploy/backup.sh` —
он использует `sqlite3 .backup`, который делает консистентный снапшот
правильно независимо от состояния WAL (проверено: сам протестировал
именно этот сценарий — данные из ещё не слитого WAL корректно попадают
в бэкап).

Настрой автоматический ежедневный бэкап через cron:

```bash
crontab -e
```

Добавь строку (бэкап каждый день в 4:00 утра):

```
0 4 * * * DB_PATH=/home/botuser/podselenie-bot/bot.db BACKUP_DIR=/home/botuser/backups bash /home/botuser/podselenie-bot/deploy/backup.sh
```

Скрипт сам хранит только последние 14 бэкапов, старые удаляет.

## 7. Обновление кода в будущем

Когда пришлю новую версию проекта — обрати внимание, архив всегда
распаковывается в папку `project/` (так называется у меня на диске),
а на сервере бот лежит в `podselenie-bot/` — нужно скопировать файлы,
а не просто `unzip -o` поверх (иначе создастся ещё одна папка рядом,
а не обновится нужная):

```bash
# на Mac — собираешь новый zip, как в шаге 2 (тем же способом, с исключениями)
scp podselenie-bot.zip botuser@<IP-сервера>:~/

# на сервере
sudo systemctl stop podselenie-bot
cd ~
rm -rf update_tmp && unzip -q podselenie-bot.zip -d update_tmp

# копируем новый код поверх старого, не трогая .env и bot.db* —
# их и так нет в архиве (см. шаг 2), но rsync --exclude на всякий случай
rsync -a --exclude='.env' --exclude='bot.db*' update_tmp/project/ podselenie-bot/
rm -rf update_tmp

cd podselenie-bot
source .venv/bin/activate && pip install -r requirements.txt && deactivate
sudo systemctl start podselenie-bot
```

Если `rsync` не установлен: `sudo apt install -y rsync`.

