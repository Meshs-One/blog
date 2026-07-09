"""
深度清理修复：从英文原文获取正确标签，替换翻译文件中的LLM推理残留
"""
import re
import os
import yaml

BASE = "E:/21、蓝天老师--老板AI思维--打造你的AI创始团队/一堂课程：启动会--商业突破大航海/blog-source"
LANGS = ["de", "fr", "ja", "ko", "zh"]

def read_front_matter(path):
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return None, None, raw
    return parts[1], parts[2], raw

def parse_yaml(fm_text):
    try:
        return yaml.safe_load(fm_text)
    except:
        return None

def is_llm_garbage(text):
    """Check if text contains LLM reasoning"""
    patterns = [
        r'I need to', r'I think', r'I believe', r'Let me', 
        r'Note:', r'The source', r'Key points', r'Also note',
        r'We need', r'We should', r'The instruction says',
        r'Consider style', r'Use katakana', r'Use \w+体',
        r'Translation of', r'Translate this',
        r'Output ONLY', r'output should be',
        r'Consider German', r'Consistency',
        r'Style reference', r'following the given',
        r'We must output', r'Given localization',
        r'We must use', r'Korean tech', r'Japanese tech',
    ]
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            return True
    return False

def write_yaml_list(lines, key, items, indent=0):
    lines.append(f"{'  '*indent}{key}:")
    for item in items:
        if item:
            safe = str(item).replace('"', '\\"')
            lines.append(f"{'  '*(indent+1)}- \"{safe}\"")

def parse_inline_array(text):
    text = text.strip()
    if (text.startswith('"') and text.endswith('"')) or \
       (text.startswith("'") and text.endswith("'")):
        text = text[1:-1]
    if text.startswith('[') and text.endswith(']'):
        text = text[1:-1]
    items = []
    for part in re.split(r',\s*', text):
        part = part.strip().strip('"').strip("'").strip()
        if part:
            items.append(part)
    return items

def clean_llm_text(text):
    """Try to extract meaningful content from LLM garbage text"""
    text = re.sub(r'^We need to translate.*?The (source|text|terms|list).*?is:?\s*', '', text, flags=re.DOTALL | re.IGNORECASE | re.MULTILINE)
    text = re.sub(r'^Translate.*?:\s*', '', text, flags=re.DOTALL | re.IGNORECASE | re.MULTILINE)
    text = re.sub(r'^I need to translate.*?:\s*', '', text, flags=re.DOTALL | re.IGNORECASE | re.MULTILINE)
    text = re.sub(r'^The English (title|text|phrase).*?(is|are):?\s*', '', text, flags=re.DOTALL | re.IGNORECASE | re.MULTILINE)
    text = re.sub(r'\n.*(We must|I need|Let me|Consider|Also note|Note:|Key points|The style).*', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = text.strip().strip('"').strip("'").strip()
    if len(text) > 200 and is_llm_garbage(text):
        parts = re.split(r'[.。!！\n]', text)
        for p in parts:
            p = p.strip()
            if p and not is_llm_garbage(p) and len(p) > 10:
                return p
        return None
    if is_llm_garbage(text) or len(text) < 5:
        return None
    return text.strip()


def fix_file(fpath, en_data, slug):
    fm_text, body, raw = read_front_matter(fpath)
    if fm_text is None:
        return False
    
    data = parse_yaml(fm_text)
    if data and isinstance(data, dict) and not any(is_llm_garbage(str(v)) for v in data.values()):
        return False
    
    en_tags = en_data.get("tags", [])
    if isinstance(en_tags, str): en_tags = [en_tags]
    en_cats = en_data.get("categories", [])
    if isinstance(en_cats, str): en_cats = [en_cats]
    en_series = en_data.get("series", [])
    if isinstance(en_series, str): en_series = [en_series]

    lines = fm_text.split("\n")
    new_lines = []
    i = 0
    in_block = False
    block_key = None
    block_lines_collect = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        
        # Ending a block
        if in_block:
            # A block continues as long as line is indented or empty
            if stripped == '' or (len(line) - len(line.lstrip())) > 0:
                block_lines_collect.append(line)
                i += 1
                continue
            else:
                in_block = False
                full_text = "\n".join(block_lines_collect).strip()
                if block_key in ("tags", "categories", "series"):
                    items_map = {"tags": en_tags, "categories": en_cats, "series": en_series}
                    write_yaml_list(new_lines, block_key, items_map.get(block_key, []))
                elif block_key in ("title", "description"):
                    cleaned = clean_llm_text(full_text)
                    if cleaned:
                        safe = cleaned.replace('"', '\\"')
                        new_lines.append(f'{block_key}: "{safe}"')
                    else:
                        safe = full_text.replace('"', '\\"').replace('\n', ' ')
                        new_lines.append(f'{block_key}: "{safe}"')
                else:
                    safe = full_text.replace('"', '\\"').replace('\n', ' ')
                    new_lines.append(f'{block_key}: "{safe}"')
                block_key = None
                block_lines_collect = []
                continue
        
        # Block scalar start: key: |
        m = re.match(r'^(\w[\w]*):\s*\|\d*$', stripped)
        if m:
            in_block = True
            block_key = m.group(1)
            i += 1
            continue
        
        # Inline tags/categories/series: tags: "[\"...\"]"
        m = re.match(r'^(tags|categories|series):\s*"(\[.*?\])"\s*$', stripped)
        if m:
            key_name = m.group(1)
            items = parse_inline_array(m.group(2))
            if all(is_llm_garbage(it) for it in items):
                repl = {"tags": en_tags, "categories": en_cats, "series": en_series}[key_name]
                write_yaml_list(new_lines, key_name, repl)
            else:
                write_yaml_list(new_lines, key_name, items)
            i += 1
            continue
        
        # Inline array: tags: [a, b, c] or tags: ["a", "b"]
        m = re.match(r'^(tags|categories|series):\s*\[(.+?)\]\s*$', stripped)
        if m:
            key_name = m.group(1)
            inner = m.group(2)
            items = [x.strip().strip('"').strip("'").strip() for x in inner.split(",")]
            items = [x for x in items if x]
            if all(is_llm_garbage(it) for it in items):
                repl = {"tags": en_tags, "categories": en_cats, "series": en_series}[key_name]
                write_yaml_list(new_lines, key_name, repl)
            else:
                write_yaml_list(new_lines, key_name, items)
            i += 1
            continue
        
        # Fix boolean strings
        line2 = re.sub(r'^(ShowToc|TocOpen|draft):\s*"(true|false)"\s*$', r'\1: \2', line.rstrip())
        if line2 != line.rstrip():
            new_lines.append(line2)
            i += 1
            continue
        
        new_lines.append(line.rstrip())
        i += 1
    
    # Handle trailing block
    if in_block and block_key:
        full_text = "\n".join(block_lines_collect).strip()
        if block_key in ("tags", "categories", "series"):
            items_map = {"tags": en_tags, "categories": en_cats, "series": en_series}
            write_yaml_list(new_lines, block_key, items_map.get(block_key, []))
        elif block_key in ("title", "description"):
            cleaned = clean_llm_text(full_text)
            if cleaned:
                safe = cleaned.replace('"', '\\"')
                new_lines.append(f'{block_key}: "{safe}"')
            else:
                safe = full_text.replace('"', '\\"').replace('\n', ' ')
                new_lines.append(f'{block_key}: "{safe}"')
        else:
            safe = full_text.replace('"', '\\"').replace('\n', ' ')
            new_lines.append(f'{block_key}: "{safe}"')
    
    new_fm = "\n".join(new_lines)
    
    try:
        data2 = yaml.safe_load(new_fm)
        if not isinstance(data2, dict):
            print(f"  FAIL not dict: {os.path.basename(fpath)}")
            print(f"    {new_fm[:200]}")
            return False
    except yaml.YAMLError as e:
        print(f"  FAIL YAML: {os.path.basename(fpath)}: {e}")
        print(f"    {new_fm[:300]}")
        return False
    
    new_content = "---\n" + new_fm + "\n---" + body
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"  ✅ FIXED: {os.path.basename(fpath)}")
    return True


def main():
    # Pre-load all English data
    en_data_by_slug = {}
    en_dir = os.path.join(BASE, "content", "posts")
    if os.path.isdir(en_dir):
        for fname in os.listdir(en_dir):
            if not fname.endswith(".md"):
                continue
            fm_text, _, _ = read_front_matter(os.path.join(en_dir, fname))
            if fm_text:
                data = parse_yaml(fm_text)
                if data and isinstance(data, dict):
                    slug = data.get("slug", fname.replace(".md", ""))
                    en_data_by_slug[slug] = data
    print(f"Loaded {len(en_data_by_slug)} English reference files")
    
    fixed_count = 0
    error_count = 0
    total_count = 0
    
    for lang in LANGS:
        dirpath = os.path.join(BASE, "content", lang, "posts")
        if not os.path.isdir(dirpath):
            continue
        for fname in sorted(os.listdir(dirpath)):
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(dirpath, fname)
            total_count += 1
            
            slug = fname.replace(".md", "")
            en_data = en_data_by_slug.get(slug)
            
            if not en_data:
                fm_text, _, _ = read_front_matter(fpath)
                if fm_text:
                    data = parse_yaml(fm_text)
                    if data and isinstance(data, dict):
                        tkey = data.get("translationKey", "")
                        slug_from_fm = data.get("slug", "")
                        if slug_from_fm and slug_from_fm in en_data_by_slug:
                            en_data = en_data_by_slug[slug_from_fm]
                        elif tkey:
                            for eslug, ed in en_data_by_slug.items():
                                if tkey == ed.get("translationKey", ""):
                                    en_data = ed
                                    break
            
            if not en_data:
                en_data = next(iter(en_data_by_slug.values())) if en_data_by_slug else None
            
            try:
                if fix_file(fpath, en_data, slug):
                    fixed_count += 1
            except Exception as e:
                print(f"  ERROR: {fname}: {e}")
                import traceback
                traceback.print_exc()
                error_count += 1
    
    print(f"\nTotal: {total_count}, Fixed: {fixed_count}, Errors: {error_count}")


if __name__ == "__main__":
    main()
