#!/usr/bin/env python3
"""Generate the installed-skill catalog from the shared manifest and SKILL.md frontmatter."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'skill-guide' / 'references' / 'skill-catalog.md'

def frontmatter(path):
    lines = path.read_text(encoding='utf-8').splitlines()
    try:
        start = lines.index('---')
        end = lines.index('---', start + 1)
    except ValueError:
        return path.parent.name, '설명 확인 필요'
    fm = lines[start + 1:end]
    name = path.parent.name
    desc = ''
    for i, line in enumerate(fm):
        if line.startswith('name:'):
            name = line.split(':', 1)[1].strip().strip('"\'')
        if line.startswith('description:'):
            value = line.split(':', 1)[1].strip()
            if value in {'|', '>'}:
                collected = []
                for continuation in fm[i + 1:]:
                    if continuation.startswith('  ') or continuation.startswith('\t'):
                        collected.append(continuation.strip())
                    else:
                        break
                desc = ' '.join(collected)
            else:
                desc = value.strip('"\'')
            break
    desc = re.sub(r'\s+', ' ', desc).strip()
    return name, desc or '설명 확인 필요'

def main():
    data = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    lines = ['# 설치 스킬 자동 카탈로그', '', '> 이 파일은 `generate_skill_guide.py`가 manifest.json과 각 SKILL.md에서 생성한다.', '']
    for name in sorted(data['skills']):
        skill_name, description = frontmatter(ROOT / name / 'SKILL.md')
        meta = data['skills'][name]
        lines.append(f'- `{skill_name}` — {description}')
        lines.append(f'  - Codex: {meta["codex"]} / Claude: {meta["claude"]} / 의존성: {", ".join(meta["dependencies"]) or "없음"}')
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'GENERATED {OUT}')

if __name__ == '__main__':
    main()
