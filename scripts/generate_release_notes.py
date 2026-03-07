#!/usr/bin/env python3
"""
Скрипт для автоматического создания описания релиза на русском языке
на основе коммитов, следующих конвенции Conventional Commits.
"""

import re
import subprocess
import sys
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Tuple

# Маппинг типов коммитов на русские названия
TYPE_MAPPING = {
    'feat': '✨ Новые функции',
    'fix': '🐛 Исправления',
    'docs': '📚 Документация',
    'style': '💄 Стиль кода',
    'refactor': '♻️ Рефакторинг',
    'perf': '⚡ Производительность',
    'test': '🧪 Тесты',
    'build': '🔨 Сборка',
    'ci': '👷 CI/CD',
    'chore': '🔧 Обслуживание'
}

# Маппинг областей на русские названия
SCOPE_MAPPING = {
    'ui': 'интерфейс',
    'localization': 'локализация',
    'build': 'сборка',
    'installer': 'установщик',
    'linux': 'Linux',
    'windows': 'Windows',
    'macos': 'macOS'
}

LOG_FIELD_SEPARATOR = "\x1f"
LOG_RECORD_SEPARATOR = "\x1e"
SKIP_RELEASE_NOTES_MARKERS = (
    "[skip-release-notes]",
    "[no-release-notes]",
)
SKIP_RELEASE_NOTES_TRAILER = re.compile(
    r"^\s*Release-Notes:\s*skip\s*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class CommitEntry:
    """Данные одного коммита из git log."""

    commit_hash: str
    subject: str
    body: str

def is_release_mode() -> bool:
    """Определяет, запущен ли скрипт в режиме выпуска релиза по наличию тега на текущем коммите."""
    try:
        result = subprocess.run(
            ['git', 'describe', '--exact-match', '--tags', 'HEAD'],
            capture_output=True, text=True, check=True
        )
        return True
    except subprocess.CalledProcessError:
        return False

def get_current_tag() -> str:
    """Получает текущий тег, если HEAD помечен тегом."""
    if is_release_mode():
        try:
            result = subprocess.run(
                ['git', 'describe', '--exact-match', '--tags', 'HEAD'],
                capture_output=True, text=True, check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return None
    return None

def get_version_from_tag(tag: str) -> str:
    """Извлекает версию из тега, убирая префикс 'v' если есть."""
    if tag.startswith('v'):
        return tag[1:]  # Убираем префикс 'v'
    return tag

def get_target_version() -> str:
    """
    Определяет целевую версию для релиз ноутс.
    
    Returns:
        Версия для которой создается релиз
    """
    if is_release_mode():
        # В режиме выпуска релиза берем версию из текущего тега
        current_tag = get_current_tag()
        if current_tag:
            return get_version_from_tag(current_tag)
        else:
            print("Ошибка: не удалось определить версию из текущего тега")
            sys.exit(1)
    else:
        # В режиме предварительного просмотра определяем следующую версию
        try:
            result = subprocess.run(
                ['git', 'tag', '--sort=-version:refname'],
                capture_output=True, text=True, check=True
            )
            tags = result.stdout.strip().split('\n') if result.stdout.strip() else []
            
            if not tags:
                return "1.0.0"  # Первый релиз
            
            # Берем последний тег и увеличиваем patch версию
            last_tag = tags[0]
            last_version = get_version_from_tag(last_tag)
            
            # Простое увеличение patch версии (можно улучшить логику)
            if '.' in last_version:
                parts = last_version.split('.')
                if len(parts) >= 3:
                    patch = int(parts[2]) + 1
                    parts[2] = str(patch)
                    return '.'.join(parts)
                else:
                    return f"{last_version}.1"
            else:
                return f"{last_version}.1"
                
        except (subprocess.CalledProcessError, ValueError, IndexError):
            return "1.0.0"  # Fallback


def parse_git_log_output(output: str) -> List[CommitEntry]:
    """Преобразует вывод git log в список структурированных коммитов."""
    commits = []
    for raw_record in output.split(LOG_RECORD_SEPARATOR):
        record = raw_record.strip()
        if not record:
            continue
        parts = record.split(LOG_FIELD_SEPARATOR, 2)
        if len(parts) != 3:
            continue
        commit_hash, subject, body = parts
        commits.append(CommitEntry(
            commit_hash=commit_hash.strip(),
            subject=subject.strip(),
            body=body.strip(),
        ))
    return commits


def get_git_log_entries(*log_args: str) -> List[CommitEntry]:
    """Возвращает структурированные коммиты из git log."""
    result = subprocess.run(
        ['git', 'log', *log_args, '--format=%H%x1f%s%x1f%B%x1e', '--no-merges'],
        capture_output=True, text=True, check=True
    )
    return parse_git_log_output(result.stdout)


def should_skip_release_notes(commit: CommitEntry) -> bool:
    """Определяет, нужно ли скрыть коммит из релиз ноутс."""
    full_message = f"{commit.subject}\n{commit.body}".lower()
    if any(marker in full_message for marker in SKIP_RELEASE_NOTES_MARKERS):
        return True
    return bool(SKIP_RELEASE_NOTES_TRAILER.search(f"{commit.subject}\n{commit.body}"))


def get_commits_since_last_release(preview_mode: bool = False) -> List[CommitEntry]:
    """
    Получает коммиты в зависимости от режима работы.
    
    Args:
        preview_mode: True для режима предварительного просмотра, False для режима выпуска релиза
    
    Returns:
        Список коммитов
    """
    try:
        result = subprocess.run(
            ['git', 'tag', '--sort=-version:refname'],
            capture_output=True, text=True, check=True
        )
        tags = result.stdout.strip().split('\n') if result.stdout.strip() else []
        
        if preview_mode:
            # Режим предварительного просмотра: от последнего тега до HEAD
            if not tags:
                return filter_service_commits(get_git_log_entries())
            last_tag = tags[0]
            return filter_service_commits(get_git_log_entries(f'{last_tag}..HEAD'))
        else:
            # Режим выпуска релиза: от предыдущего тега до текущего тега
            current_tag = get_current_tag()
            if not current_tag:
                print("Ошибка: HEAD не помечен тегом. Запустите в режиме выпуска релиза или используйте --preview")
                return []
            if len(tags) < 2:
                return filter_service_commits(get_git_log_entries(current_tag, '-1'))
            previous_tag = tags[1] if tags[0] == current_tag else tags[0]
            return filter_service_commits(get_git_log_entries(f'{previous_tag}..{current_tag}'))
    except subprocess.CalledProcessError as e:
        print(f"Ошибка при получении коммитов: {e}")
        return []


def filter_service_commits(commits: List[CommitEntry]) -> List[CommitEntry]:
    """Фильтрует служебные коммиты инициализации."""
    filtered_commits = []
    for commit in commits:
        if should_skip_release_notes(commit):
            continue
        # Исключаем коммиты инициализации и служебные коммиты
        if any(keyword in commit.subject.lower() for keyword in [
            'init:', 'initial', 'новый git-репозиторий', 'reset', 'squash'
        ]):
            continue
        filtered_commits.append(commit)
    return filtered_commits

def parse_commit(commit_line: str) -> Tuple[str, str, str, str]:
    """
    Парсит строку коммита и возвращает (тип, область, описание, хеш).
    
    Args:
        commit_line: Строка коммита в формате "hash message"
    
    Returns:
        Tuple с (тип, область, описание, хеш)
    """
    if not commit_line:
        return None, None, None, None
    
    parts = commit_line.split(' ', 1)
    if len(parts) != 2:
        return None, None, None, parts[0] if parts else None
    
    commit_hash, message = parts
    
    # Паттерн для Conventional Commits
    pattern = r'^([a-z]+)(?:\(([a-z-]+)\))?:\s*(.+)$'
    match = re.match(pattern, message)
    
    if not match:
        return None, None, message, commit_hash
    
    commit_type, scope, description = match.groups()
    return commit_type, scope, description, commit_hash

def format_commit_description(description: str, scope: str = None) -> str:
    """Форматирует описание коммита."""
    if scope and scope in SCOPE_MAPPING:
        return f"{description} ({SCOPE_MAPPING[scope]})"
    return description

def generate_release_notes(preview_mode: bool = False) -> str:
    """
    Генерирует описание релиза на русском языке.
    
    Args:
        preview_mode: True для режима предварительного просмотра, False для режима выпуска релиза
    """
    version = get_target_version()
    commits = get_commits_since_last_release(preview_mode)
    grouped_commits = defaultdict(list)
    other_commits = []
    for commit in commits:
        commit_type, scope, description, commit_hash = parse_commit(
            f"{commit.commit_hash} {commit.subject}"
        )
        if commit_type and commit_type in TYPE_MAPPING:
            formatted_desc = format_commit_description(description, scope)
            grouped_commits[commit_type].append(formatted_desc)
        else:
            other_commits.append(description if description else commit.subject)
    lines = ["## Изменения"]
    for commit_type in ['feat', 'fix', 'refactor', 'perf', 'build', 'ci', 'docs', 'style', 'test', 'chore']:
        if commit_type in grouped_commits:
            lines.append(f"### {TYPE_MAPPING[commit_type]}")
            for description in grouped_commits[commit_type]:
                lines.append(f"- {description}")
            lines.append("")
    if other_commits:
        lines.append("### 🔄 Прочие изменения")
        for description in other_commits:
            lines.append(f"- {description}")
        lines.append("")
    lines.append("## Загрузки")
    lines.append("")
    lines.append("Выберите подходящий файл для вашей операционной системы из списка ниже.")
    lines.append("")
    lines.append("Для подробных инструкций по установке и использованию см. [README](https://github.com/IngvarConsulting/efd_unpacker#readme).")
    return "\n".join(lines)

def main():
    """Основная функция."""
    if len(sys.argv) > 1:
        if sys.argv[1] == '--preview':
            preview_mode = True
        elif sys.argv[1] == '--release':
            preview_mode = False
        elif sys.argv[1] in ['-h', '--help']:
            print("Использование:")
            print("  python generate_release_notes.py [--preview]")
            print("  python generate_release_notes.py [--release]")
            print("")
            print("Опции:")
            print("  --preview  Режим предварительного просмотра: от последнего тега до HEAD")
            print("  --release  Режим выпуска релиза: от предыдущего тега до текущего тега")
            print("")
            print("Чтобы скрыть служебный коммит из релиз ноутс, добавьте в его текст")
            print("маркер [skip-release-notes] или trailer 'Release-Notes: skip'.")
            print("")
            print("Если опция не указана, автоматически определяется по наличию тега:")
            print("- Если текущий коммит помечен тегом - используется --release")
            print("- Если текущий коммит не помечен тегом - используется --preview")
            print("")
            print("Версия определяется автоматически из тегов.")
            sys.exit(0)
        else:
            print(f"Неизвестная опция: {sys.argv[1]}")
            print("Используйте --help для справки")
            sys.exit(1)
    else:
        preview_mode = not is_release_mode()
    
    version = get_target_version()
    print(f"Режим: {'предварительного просмотра' if preview_mode else 'выпуска релиза'}")
    print(f"Версия: {version}")
    release_notes = generate_release_notes(preview_mode)
    print(release_notes)

if __name__ == "__main__":
    main() 
