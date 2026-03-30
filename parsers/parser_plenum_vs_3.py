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
                "text": "\n".join(current_article_text).strip()
            })
        current_article_title = ""
        current_article_text = []

    # Matches numbers like "1.", "9.-19.", "1.1.", etc.
    point_regex = re.compile(r'^([\d.-]+)\.(?:\s|$)')

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
                # extract base number, e.g. "9" from "9.-19" or "9.1"
                base_num = re.sub(r'[^\d].*', '', point_num_str)
                
                # If we are already building this exact point, append to it
                if current_article_title == base_num:
                    cleaned = clean_header(stripped)
                    current_article_text.append(cleaned)
                    continue
                
                finalize_article()
                state = "PARSING_CONTENT"
                current_article_title = base_num
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
