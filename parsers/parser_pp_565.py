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
        nonlocal current_article_title, current_article_text
        if current_article_title:
            result_elements.append({
                "type": "article",
                "title": current_article_title,
                "text": "\n".join(current_article_text)
            })
        current_article_title = ""
        current_article_text = []

    roman_regex = re.compile(r'^(I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII|XIII|XIV|XV)\.\s+')
    point_regex = re.compile(r'^(\d+(?:\.\d+)*)\.(?:\s|$)')

    for line in lines:
        stripped = line.strip().lstrip('\ufeff\u200b')
        
        if state == "SEARCHING_TITLE":
            if stripped == "ПОСТАНОВЛЕНИЕ":
                state = "COLLECTING_TITLE"
                title_lines.append(stripped)
            continue
            
        elif state == "COLLECTING_TITLE":
            if stripped.startswith("(в ред.") or stripped.startswith("В соответствии со"):
                state = "WAITING_FOR_SECTION"
                result_elements.append({"type": "text", "content": " ".join(title_lines)})
                continue
            if stripped:
                title_lines.append(stripped)
            continue
            
        elif state == "WAITING_FOR_SECTION":
            if not stripped:
                continue
            roman_match = roman_regex.match(stripped)
            if roman_match:
                state = "PARSING_CONTENT"
                cleaned = clean_header(stripped)
                result_elements.append({"type": "section", "content": cleaned})
                current_element_type = "section"
            continue
            
        elif state == "PARSING_CONTENT":
            roman_match = roman_regex.match(stripped)
            if roman_match:
                finalize_article()
                cleaned = clean_header(stripped)
                result_elements.append({"type": "section", "content": cleaned})
                current_element_type = "section"
                continue
                
            point_match = point_regex.match(stripped)
            if point_match:
                finalize_article()
                point_number = point_match.group(1) + "."
                current_article_title = point_number
                current_element_type = "article"
                
                text_after = stripped[point_match.end():].strip()
                if text_after:
                    cleaned = clean_header(text_after)
                    current_article_text.append(cleaned)
                continue
                
            if current_element_type == "article" and current_article_title:
                cleaned = clean_header(stripped)
                current_article_text.append(cleaned)

    finalize_article()

    if state == "COLLECTING_TITLE":
        result_elements.insert(0, {"type": "text", "content": " ".join(title_lines)})

    return result_elements
