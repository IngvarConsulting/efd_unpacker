#!/usr/bin/env python3
"""
Скрипт для автоматического создания описания релиза на русском языке
на основе коммитов, следующих конвенции Conventional Commits.
"""

import re
import subprocess
import sys
from collections import defaultdict
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

def get_commits_since_last_release() -> List[str]:
    """Получает коммиты от предыдущего тега до текущего тега включительно."""
    try:
        # Получаем все теги, отсортированные по версии
        result = subprocess.run(
            ['git', 'tag', '--sort=-version:refname'],
            capture_output=True, text=True, check=True
        )
        tags = result.stdout.strip().split('\n') if result.stdout.strip() else []
        
        if len(tags) < 2:
            # Если тегов меньше 2, получаем все коммиты
            result = subprocess.run(
                ['git', 'log', '--oneline', '--no-merges'],
                capture_output=True, text=True, check=True
            )
            return result.stdout.strip().split('\n') if result.stdout.strip() else []
        
        # Текущий тег (первый в списке)
        current_tag = tags[0]
        # Предыдущий тег (второй в списке)
        previous_tag = tags[1]
        
        # Получаем коммиты от предыдущего тега до текущего тега включительно
        # Используем ^previous_tag чтобы исключить коммит предыдущего тега
        result = subprocess.run(
            ['git', 'log', f'{previous_tag}..{current_tag}', '--oneline', '--no-merges'],
            capture_output=True, text=True, check=True
        )
        commits = result.stdout.strip().split('\n') if result.stdout.strip() else []
        
        # Добавляем коммит текущего тега, если он не включен
        result = subprocess.run(
            ['git', 'log', current_tag, '-1', '--oneline', '--no-merges'],
            capture_output=True, text=True, check=True
        )
        current_tag_commit = result.stdout.strip()
        if current_tag_commit and current_tag_commit not in commits:
            commits.insert(0, current_tag_commit)
        
        return commits
        
    except subprocess.CalledProcessError:
        # Если нет тегов, получаем все коммиты
        result = subprocess.run(
            ['git', 'log', '--oneline', '--no-merges'],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip().split('\n') if result.stdout.strip() else []

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

def generate_release_notes(version: str) -> str:
    """Генерирует описание релиза на русском языке."""
    commits = get_commits_since_last_release()
    
    if not commits:
        return f"""# EFD Unpacker {version}

Релиз без изменений в коде.

## Загрузки

Выберите подходящий файл для вашей операционной системы из списка ниже.

Для подробных инструкций по установке и использованию см. [README](https://github.com/IngvarConsulting/efd_unpacker#readme)."""

    # Группируем коммиты по типам
    grouped_commits = defaultdict(list)
    other_commits = []
    
    for commit in commits:
        commit_type, scope, description, commit_hash = parse_commit(commit)
        
        if commit_type and commit_type in TYPE_MAPPING:
            formatted_desc = format_commit_description(description, scope)
            grouped_commits[commit_type].append(formatted_desc)
        else:
            other_commits.append(description if description else commit)
    
    # Формируем описание релиза
    lines = [f"# EFD Unpacker {version}"]
    lines.append("")
    lines.append("## Изменения")
    lines.append("")
    
    # Добавляем сгруппированные коммиты
    for commit_type in ['feat', 'fix', 'refactor', 'perf', 'build', 'ci', 'docs', 'style', 'test', 'chore']:
        if commit_type in grouped_commits:
            lines.append(f"### {TYPE_MAPPING[commit_type]}")
            for description in grouped_commits[commit_type]:
                lines.append(f"- {description}")
            lines.append("")
    
    # Добавляем остальные коммиты
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
    if len(sys.argv) != 2:
        print("Использование: python generate_release_notes.py <version>")
        sys.exit(1)
    
    version = sys.argv[1]
    release_notes = generate_release_notes(version)
    print(release_notes)

if __name__ == "__main__":
    main() 