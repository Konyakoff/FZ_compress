import re

def clean_header(line):
    line = re.sub(r'\s*\(в ред\..*?\)\s*$', '', line)
    line = re.sub(r'\s*\(в ред\..*$', '', line)
    return line.strip()

def parse(lines):
    result_elements = []
    title_lines = []
    title_finished = False
    current_element_type = None
    current_article_title = ""
    current_article_text = []

    def finalize_article():
        nonlocal current_article_title, current_article_text
        if current_article_title:
            result_elements.append({
                "type": "article",
                "title": current_article_title,
                "text": "\n".join(current_article_text)
            })
        current_article_title = ""
        current_article_text = []

    for line in lines:
        stripped = line.strip().lstrip('\ufeff\u200b')
        if not stripped:
            continue
            
        if not title_finished and stripped.isupper() and stripped != "РОССИЙСКАЯ ФЕДЕРАЦИЯ":
            title_lines.append(stripped)
            continue
        elif not title_finished and len(title_lines) > 0 and not stripped.isupper():
            title_finished = True
            result_elements.append({"type": "text", "content": " ".join(title_lines)})
            
        if stripped.startswith("Статья "):
            finalize_article()
            if not title_finished:
                if title_lines:
                    result_elements.append({"type": "text", "content": " ".join(title_lines)})
                title_finished = True
            cleaned = clean_header(stripped)
            current_article_title = cleaned
            current_element_type = "article"
            continue
            
        if current_element_type == "article" and current_article_title:
            current_article_text.append(stripped)

    finalize_article()
    if not title_finished and title_lines:
        result_elements.insert(0, {"type": "text", "content": " ".join(title_lines)})

    return result_elements
