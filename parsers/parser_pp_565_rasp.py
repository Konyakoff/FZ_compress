import re

def clean_header(line):
    line = re.sub(r'\s*\(в ред\..*?\)\s*$', '', line)
    line = re.sub(r'\s*\(в ред\..*$', '', line)
    return line.strip()

def parse(lines):
    result_elements = []
    
    title_lines = []
    state = "SEARCHING_TITLE"
    
    current_element_type = None
    current_article_title = ""
    current_article_text = []

    def finalize_article():
        nonlocal current_article_title, current_article_text, current_element_type
        if current_article_title and current_element_type == "article":
            result_elements.append({
                "type": "article",
                "title": current_article_title,
                "text": "\n".join(current_article_text)
            })
        current_article_title = ""
        current_article_text = []

    for line in lines:
        stripped = line.strip().lstrip('\ufeff\u200b')
        
        if stripped == "Таблица 1":
            finalize_article()
            break
            
        if state == "SEARCHING_TITLE":
            if stripped == "I. Общие положения":
                result_elements.append({"type": "text", "content": "Приложение N 1 к Положению о военно-врачебной экспертизе"})
                result_elements.append({"type": "section", "content": "I. Общие положения"})
                state = "PART_1"
                continue
            continue
            
        elif state == "PART_1":
            if stripped == "II. Расписание болезней":
                finalize_article()
                result_elements.append({"type": "section", "content": "II. Расписание болезней"})
                state = "PART_2"
                continue
                
            match = re.match(r'^(\d+\.)\s*(.*)', stripped)
            if match:
                finalize_article()
                current_article_title = match.group(1)
                current_element_type = "article"
                if match.group(2):
                    cleaned = clean_header(match.group(2))
                    if cleaned:
                        current_article_text.append(cleaned)
            else:
                if current_element_type == "article" and current_article_title:
                    cleaned = clean_header(stripped)
                    if cleaned:
                        current_article_text.append(cleaned)
            continue
            
        elif state == "PART_2":
            # Skip table headers and empty lines
            if stripped in [
                'Статья расписания болезней',
                'Наименование болезней, степень нарушения функции',
                'Категория годности к военной службе',
                'I графа',
                'II графа',
                'III графа'
            ] or stripped == '':
                continue
            
            # Detect subsection (e.g. "1. Инфекционные и паразитарные болезни")
            if re.match(r'^\d+\.\s+.*', stripped):
                finalize_article()
                cleaned = clean_header(stripped)
                result_elements.append({"type": "section", "content": cleaned})
                current_element_type = "section"
                continue
                
            # Detect article number (e.g. "1", "88")
            if re.match(r'^\d+$', stripped):
                finalize_article()
                current_article_title = "Статья " + stripped + ". "
                current_element_type = "article"
                state = "PART_2_WAIT_TITLE"
                continue
                
            if current_element_type == "article" and current_article_title:
                cleaned = clean_header(stripped)
                if cleaned:
                    current_article_text.append(cleaned)
            continue
            
        elif state == "PART_2_WAIT_TITLE":
            if stripped:
                cleaned = clean_header(stripped)
                current_article_title += cleaned
                current_element_type = "article"
                state = "PART_2"
            continue
            
    finalize_article()

    if state == "SEARCHING_TITLE" and title_lines:
        result_elements.insert(0, {"type": "text", "content": " ".join(title_lines)})

    return result_elements
