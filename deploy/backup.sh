#!/bin/bash
# Бэкап SQLite-базы бота. Через `sqlite3 .backup`, а не простой cp —
# при включённом WAL-режиме (см. database/database.py) наивное копирование
# файла bot.db может не захватить изменения, ещё не перенесённые из
# bot.db-wal в основной файл. `.backup` делает консистентный снапшот
# правильно, независимо от состояния WAL.
set -e

DB_PATH="${DB_PATH:-/home/botuser/podselenie-bot/bot.db}"
BACKUP_DIR="${BACKUP_DIR:-/home/botuser/backups}"
KEEP_LAST="${KEEP_LAST:-14}"

mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +%F_%H-%M)
sqlite3 "$DB_PATH" ".backup '$BACKUP_DIR/bot-$TIMESTAMP.db'"

# Храним только последние N бэкапов, остальное удаляем
ls -tp "$BACKUP_DIR"/bot-*.db 2>/dev/null | tail -n +$((KEEP_LAST + 1)) | xargs -r rm --
