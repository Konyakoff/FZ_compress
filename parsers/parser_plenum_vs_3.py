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
    
    max_point_number = -1

    def finalize_article():
        nonlocal current_article_title, current_article_text
        if current_article_title:
            result_elements.append({
                "type": "article",
                "title": current_article_title,
                "text": "\n".join(current_article_text).strip()
            })
        current_article_title = ""
        current_article_text = []

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
                state = "PREAMBLE"
                result_elements.append({"type": "text", "content": " ".join(title_lines)})
                current_article_title = "0"
                current_element_type = "article"
                continue
            
            # If we see a paragraph that doesn't look like a title (not all caps, long)
            # Or if it's the beginning of the preamble
            if stripped and not stripped.isupper() and len(stripped) > 50:
                state = "PREAMBLE"
                result_elements.append({"type": "text", "content": " ".join(title_lines)})
                current_article_title = "0"
                current_element_type = "article"
                current_article_text.append(clean_header(stripped))
                continue

            if stripped:
                title_lines.append(stripped)
            continue
            
        elif state in ["PREAMBLE", "PARSING_CONTENT"]:
            if not stripped:
                continue
                
            point_match = point_regex.match(stripped)
            if point_match:
                point_num_str = point_match.group(1)
                first_num_part = int(point_num_str.split('.')[0])
                
                if first_num_part > max_point_number:
                    finalize_article()
                    state = "PARSING_CONTENT"
                    max_point_number = first_num_part
                    point_number = point_num_str
                    current_article_title = point_number
                    current_element_type = "article"
                    
                    text_after = stripped[point_match.end():].strip()
                    if text_after:
                        cleaned = clean_header(text_after)
                        current_article_text.append(cleaned)
                    continue
                else:
                    if current_element_type == "article" and current_article_title:
                        cleaned = clean_header(stripped)
                        current_article_text.append(cleaned)
                    continue
                
            if current_element_type == "article" and current_article_title:
                cleaned = clean_header(stripped)
                current_article_text.append(cleaned)

    finalize_article()

    if state == "COLLECTING_TITLE":
        result_elements.insert(0, {"type": "text", "content": " ".join(title_lines)})

    return result_elements
