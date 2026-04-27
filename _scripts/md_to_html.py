#!/usr/bin/env python3
"""Convert botNotes markdown files to styled HTML (design system: white, Sky Blue accent, Inter)."""

import re
import sys
from pathlib import Path

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

        body {{
            font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            font-size: 16px;
            line-height: 1.6;
            color: #111827;
            background: #FFFFFF;
        }}

        header {{
            background: #FFFFFF;
            border-bottom: 1px solid #E5E7EB;
            padding: 16px 24px;
            position: sticky;
            top: 0;
        }}

        .brand {{
            font-size: 15px;
            font-weight: 600;
            color: #111827;
        }}

        .brand .accent {{ color: #8CE4FF; }}

        main {{
            max-width: 680px;
            margin: 0 auto;
            padding: 48px 24px 96px;
        }}

        h1 {{
            font-size: 32px;
            font-weight: 700;
            line-height: 1.2;
            letter-spacing: -0.01em;
            color: #111827;
            margin-bottom: 12px;
        }}

        h2 {{
            font-size: 20px;
            font-weight: 600;
            line-height: 1.3;
            letter-spacing: -0.01em;
            color: #111827;
            margin-top: 40px;
            margin-bottom: 14px;
            padding-bottom: 10px;
            border-bottom: 2px solid #8CE4FF;
        }}

        h3 {{
            font-size: 16px;
            font-weight: 600;
            line-height: 1.4;
            color: #111827;
            margin-top: 24px;
            margin-bottom: 8px;
        }}

        h4 {{
            font-size: 14px;
            font-weight: 600;
            color: #374151;
            margin-top: 16px;
            margin-bottom: 6px;
        }}

        p {{
            color: #374151;
            margin-bottom: 14px;
        }}

        hr {{
            border: none;
            border-top: 1px solid #E5E7EB;
            margin: 32px 0;
        }}

        ul, ol {{
            padding-left: 20px;
            margin-bottom: 14px;
            color: #374151;
        }}

        li {{
            margin-bottom: 6px;
            line-height: 1.6;
        }}

        a {{
            color: #111827;
            text-decoration-color: #8CE4FF;
            text-underline-offset: 3px;
        }}

        a:hover {{ color: #6B7280; }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 20px;
            font-size: 14px;
            border: 1px solid #E5E7EB;
        }}

        th {{
            background: #F9FAFB;
            text-align: left;
            padding: 10px 14px;
            font-weight: 500;
            font-size: 13px;
            color: #374151;
            border-bottom: 1px solid #E5E7EB;
        }}

        td {{
            padding: 10px 14px;
            border-bottom: 1px solid #E5E7EB;
            color: #374151;
            vertical-align: top;
        }}

        tr:last-child td {{ border-bottom: none; }}

        strong {{ font-weight: 600; color: #111827; }}
        em {{ font-style: italic; color: #6B7280; }}

        blockquote {{
            border-left: 3px solid #E5E7EB;
            padding: 4px 16px;
            color: #6B7280;
            font-style: italic;
            margin: 14px 0;
        }}

        .callout {{
            background: #F9FAFB;
            border-left: 3px solid #8CE4FF;
            padding: 12px 16px;
            font-size: 14px;
            color: #6B7280;
            margin-bottom: 16px;
        }}

        pre {{
            background: #F9FAFB;
            border: 1px solid #E5E7EB;
            border-radius: 8px;
            padding: 16px 20px;
            overflow-x: auto;
            margin-bottom: 20px;
        }}

        pre code {{
            font-family: "JetBrains Mono", "Fira Code", "Cascadia Code", monospace;
            font-size: 13px;
            line-height: 1.6;
            color: #374151;
        }}

        code {{
            font-family: "JetBrains Mono", "Fira Code", "Cascadia Code", monospace;
            font-size: 13px;
            background: #F3F4F6;
            padding: 1px 6px;
            border-radius: 4px;
            color: #111827;
        }}

        footer {{
            text-align: center;
            font-size: 12px;
            color: #9CA3AF;
            padding: 32px 24px;
            border-top: 1px solid #E5E7EB;
            margin-top: 48px;
        }}

        @media (max-width: 640px) {{
            main {{ padding: 32px 16px 64px; }}
            h1 {{ font-size: 24px; }}
            h2 {{ font-size: 18px; }}
        }}
    </style>
</head>
<body>
    <header>
        <span class="brand">&#9889; SECTOR <span class="accent">7G</span></span>
    </header>
    <main>
        {body}
    </main>
    <footer>Sector 7G Automated Intelligence System</footer>
</body>
</html>"""


def inline_fmt(text: str) -> str:
    import html as _html
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)', r'<em>\1</em>', text)
    # inline code: `text`
    def code_repl(m):
        return f'<code>{_html.escape(m.group(1))}</code>'
    text = re.sub(r'`([^`]+)`', code_repl, text)
    return text


def convert_md(md: str) -> tuple:
    lines = md.split('\n')
    out = []
    title = ''
    in_list = False
    list_tag = ''
    in_table = False
    table_head_done = False
    in_code = False
    code_lines = []

    def close_list():
        nonlocal in_list, list_tag
        if in_list:
            out.append(f'</{list_tag}>')
            in_list = False
            list_tag = ''

    def close_table():
        nonlocal in_table, table_head_done
        if in_table:
            out.append('</tbody></table>')
            in_table = False
            table_head_done = False

    def close_code():
        nonlocal in_code, code_lines
        if in_code:
            import html as _html
            body = _html.escape('\n'.join(code_lines))
            out.append(f'<pre><code>{body}</code></pre>')
            in_code = False
            code_lines = []

    for line in lines:
        s = line.strip()

        # Fenced code block toggle
        if s.startswith('```'):
            if in_code:
                close_code()
            else:
                close_list()
                close_table()
                in_code = True
                code_lines = []
            continue

        if in_code:
            code_lines.append(line)
            continue

        if not s:
            close_list()
            close_table()
            continue

        if re.match(r'^-{3,}$', s):
            close_list()
            close_table()
            out.append('<hr>')
            continue

        if s.startswith('# ') and not s.startswith('## '):
            close_list(); close_table()
            t = inline_fmt(s[2:])
            if not title:
                title = s[2:]
            out.append(f'<h1>{t}</h1>')
            continue

        if s.startswith('## ') and not s.startswith('### '):
            close_list(); close_table()
            out.append(f'<h2>{inline_fmt(s[3:])}</h2>')
            continue

        if s.startswith('### ') and not s.startswith('#### '):
            close_list(); close_table()
            out.append(f'<h3>{inline_fmt(s[4:])}</h3>')
            continue

        if s.startswith('#### '):
            close_list(); close_table()
            out.append(f'<h4>{inline_fmt(s[5:])}</h4>')
            continue

        # Table row
        if s.startswith('|') and s.endswith('|'):
            close_list()
            if re.match(r'^\|[\s\-:|]+\|$', s):
                continue  # separator row
            cells = [c.strip() for c in s[1:-1].split('|')]
            if not in_table:
                in_table = True
                table_head_done = False
                out.append('<table><thead><tr>')
                for c in cells:
                    out.append(f'<th>{inline_fmt(c)}</th>')
                out.append('</tr></thead><tbody>')
                table_head_done = True
            else:
                out.append('<tr>')
                for c in cells:
                    out.append(f'<td>{inline_fmt(c)}</td>')
                out.append('</tr>')
            continue

        # Bullet list: - or *<space(s)>
        if re.match(r'^[-*]\s+\S', s):
            close_table()
            if not in_list or list_tag != 'ul':
                close_list()
                out.append('<ul>')
                in_list = True
                list_tag = 'ul'
            text = re.sub(r'^[-*]\s+', '', s)
            out.append(f'<li>{inline_fmt(text)}</li>')
            continue

        # Ordered list
        if re.match(r'^\d+\.\s+', s):
            close_table()
            if not in_list or list_tag != 'ol':
                close_list()
                out.append('<ol>')
                in_list = True
                list_tag = 'ol'
            text = re.sub(r'^\d+\.\s+', '', s)
            out.append(f'<li>{inline_fmt(text)}</li>')
            continue

        # Blockquote
        if s.startswith('> '):
            close_list(); close_table()
            out.append(f'<blockquote><p>{inline_fmt(s[2:])}</p></blockquote>')
            continue

        # Italic callout (standalone *text* — not a bullet)
        if s.startswith('*') and s.endswith('*') and not s.startswith('**') and not re.match(r'^\*\s', s):
            close_list(); close_table()
            out.append(f'<p class="callout">{inline_fmt(s)}</p>')
            continue

        # Regular paragraph
        close_list(); close_table()
        out.append(f'<p>{inline_fmt(s)}</p>')

    close_list()
    close_table()
    close_code()
    return title, '\n'.join(out)


def convert_file(md_path: Path) -> Path:
    md = md_path.read_text(encoding='utf-8')
    title, body = convert_md(md)
    html = HTML_TEMPLATE.format(title=title or md_path.stem, body=body)
    out = md_path.with_suffix('.html')
    out.write_text(html, encoding='utf-8')
    return out


def main():
    args = sys.argv[1:]
    if not args:
        print('Usage: md_to_html.py <file.md> ...')
        print('       md_to_html.py --all')
        sys.exit(1)

    if '--all' in args:
        root = Path(__file__).parent.parent
        dirs = [root / '_reports', root / '_media' / 'podcasts', root / '_media' / 'youtube']
        count = 0
        for d in dirs:
            for f in sorted(d.glob('*.md')):
                if f.name.startswith('.'):
                    continue
                out = convert_file(f)
                print(f'  {out.relative_to(root)}')
                count += 1
        print(f'\n{count} file(s) converted.')
    else:
        for p in args:
            out = convert_file(Path(p))
            print(f'Converted: {out}')


if __name__ == '__main__':
    main()
