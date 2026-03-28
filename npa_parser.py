import tkinter as tk
from tkinter import filedialog, messagebox
import re
import os
import json
import threading
import urllib.request
import urllib.parse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

def load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()

def clean_header(line):
    line = re.sub(r'\s*\(в ред\..*?\)\s*$', '', line)
    line = re.sub(r'\s*\(в ред\..*$', '', line)
    return line.strip()

def detect_encoding_and_read(filepath):
    encodings_to_try = ['utf-8-sig', 'utf-16', 'utf-8', 'windows-1251', 'cp866']
    for enc in encodings_to_try:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                text = f.read()
                if '\x00' in text and enc not in ['utf-16', 'utf-16-le', 'utf-16-be']:
                    continue
                return text.splitlines()
        except UnicodeDecodeError:
            continue
    try:
        with open(filepath, 'r', encoding='utf-16le') as f:
            return f.read().splitlines()
    except Exception:
        pass
    raise Exception("Не удалось определить кодировку файла или прочитать его.")

def call_gemini(text, prompt_instruction):
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise Exception("API ключ не найден.")
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-pro-preview:generateContent?key={api_key}"
    
    data = {
        "systemInstruction": {
            "parts": [{"text": "Вы - строгий парсер. Выдавайте ТОЛЬКО результат выжимки (ключевые слова), без объяснений, без вводных или заключительных слов, без markdown-разметки (без звездочек) и без каких-либо диалоговых фраз. Ваш ответ должен состоять ИСКЛЮЧИТЕЛЬНО из самой выжимки."}]
        },
        "contents": [{
            "parts": [{"text": prompt_instruction + "\n\nТекст статьи:\n" + text}]
        }],
        "generationConfig": {"temperature": 0.1}
    }
    
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'})
    
    max_retries = 5
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result['candidates'][0]['content']['parts'][0]['text'].strip()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                if attempt < max_retries - 1:
                    # При 429 ошибке ждем дольше с каждой попыткой (экспоненциальная задержка)
                    time.sleep(5 * (attempt + 1))
                    continue
                else:
                    raise Exception("Превышен лимит запросов к API (429).")
            
            error_info = e.read().decode('utf-8')
            if e.code == 404 and "gemini-3.1-pro-preview" in url:
                # На случай если модели 3.1-pro-preview нет, падаем на 1.5-pro
                url_fallback = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={api_key}"
                req_fallback = urllib.request.Request(url_fallback, data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'})
                try:
                    with urllib.request.urlopen(req_fallback) as res2:
                        result2 = json.loads(res2.read().decode('utf-8'))
                        return result2['candidates'][0]['content']['parts'][0]['text'].strip()
                except urllib.error.HTTPError as e2:
                    raise Exception(f"Ошибка API (fallback): {e2.code} - {e2.read().decode('utf-8')}")
                    
            raise Exception(f"Ошибка API: {e.code} - {error_info}")
    
    raise Exception("Неизвестная ошибка вызова API")

def process_file(filepath, use_gemini=False, progress_callback=None):
    load_env()
    
    prompt_instruction = ""
    if use_gemini:
        if not os.environ.get("GEMINI_API_KEY", ""):
            raise Exception("API ключ не найден! Создайте файл .env рядом со скриптом и добавьте туда строку:\nGEMINI_API_KEY=ваш_токен")
            
        prompt_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'prompt.json')
        if not os.path.exists(prompt_file):
            raise Exception("Файл prompt.json не найден в директории скрипта!")
        with open(prompt_file, 'r', encoding='utf-8') as f:
            prompt_data = json.load(f)
            prompt_instruction = prompt_data.get("prompt", "")

    lines = detect_encoding_and_read(filepath)

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
            
        if not title_finished and not stripped.isupper():
            pass

        if stripped.startswith("Раздел ") or stripped.startswith("Глава "):
            finalize_article()
            
            if not title_finished:
                if title_lines:
                    result_elements.append({"type": "text", "content": " ".join(title_lines)})
                title_finished = True
            
            cleaned = clean_header(stripped)
            result_elements.append({"type": "section", "content": cleaned})
            current_element_type = "section"
            continue
            
        elif stripped.startswith("Статья "):
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

    # Обработка статей через Gemini (в многопоточном режиме)
    stats = {"processed": 0, "errors": 0, "total": 0}
    if use_gemini:
        articles_to_process = [elem for elem in result_elements if elem["type"] == "article"]
        stats["total"] = len(articles_to_process)
        processed_count = 0
        
        if progress_callback:
            progress_callback(f"Начинаем обработку {stats['total']} статей через Gemini...")

        def process_single_article(elem):
            full_text = elem["title"] + "\n" + elem["text"]
            try:
                summary = call_gemini(full_text, prompt_instruction)
                elem["summary"] = summary
            except Exception as e:
                elem["summary"] = f"[Ошибка суммаризации: {str(e)}]"
                elem["has_error"] = True
            return elem

        # Для платного API можно поставить 10-20 потоков. Уменьшил до 5 для большей стабильности
        with ThreadPoolExecutor(max_workers=5) as executor:
            # Чтобы избежать резкого спайка (когда все потоки стучатся в первую секунду),
            # добавим небольшую задержку между отправкой заданий в пул
            futures = []
            for elem in articles_to_process:
                futures.append(executor.submit(process_single_article, elem))
                time.sleep(0.5) # полсекунды между стартами потоков
                
            for future in as_completed(futures):
                processed_count += 1
                result_elem = future.result()
                if result_elem.get("has_error"):
                    stats["errors"] += 1
                else:
                    stats["processed"] += 1
                    
                if progress_callback:
                    progress_callback(f"Обработано {processed_count} из {stats['total']} статей (Ошибок: {stats['errors']})...")

    # Сборка финального текста
    result_lines = []
    
    for i, elem in enumerate(result_elements):
        if elem["type"] == "text":
            result_lines.append(elem["content"])
            result_lines.append("")
        elif elem["type"] == "section":
            # Добавляем пустую строку перед разделом, если это не начало
            if result_lines and result_lines[-1] != "":
                result_lines.append("")
            result_lines.append(elem["content"])
        elif elem["type"] == "article":
            # Добавляем пустую строку перед статьей, если перед ней не раздел/глава
            if result_lines and i > 0 and result_elements[i-1]["type"] not in ["section", "text"]:
                if result_lines[-1] != "":
                    result_lines.append("")
            
            result_lines.append(elem["title"])
            if use_gemini:
                result_lines.append(elem.get("summary", ""))
            result_lines.append("")

    base_path, ext = os.path.splitext(filepath)
    counter = 1
    out_filepath = f"{base_path}_{counter}{ext}"
    while os.path.exists(out_filepath):
        counter += 1
        out_filepath = f"{base_path}_{counter}{ext}"

    with open(out_filepath, 'w', encoding='utf-8') as f:
        final_text = "\n".join(result_lines).strip()
        f.write(final_text + "\n")
    
    return out_filepath, stats

class NpaParserApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Парсер структуры НПА")
        self.root.geometry("500x260")
        self.root.eval('tk::PlaceWindow . center')
        self.root.configure(padx=20, pady=20)
        
        title_label = tk.Label(root, text="Извлечение структуры НПА", font=("Arial", 14, "bold"))
        title_label.pack(pady=(0, 10))
        
        desc_label = tk.Label(
            root, 
            text="Выберите .txt файл. Скрипт извлечет\nназвание, разделы, главы и статьи.", 
            font=("Arial", 10), justify=tk.CENTER
        )
        desc_label.pack(pady=(0, 10))
        
        self.use_gemini_var = tk.BooleanVar(value=False)
        self.cb_gemini = tk.Checkbutton(
            root, 
            text="Использовать ИИ (Gemini) для выжимки статей", 
            variable=self.use_gemini_var,
            font=("Arial", 10)
        )
        self.cb_gemini.pack(pady=(0, 10))
        
        self.btn = tk.Button(
            root, text="Выбрать файл", command=self.select_file, 
            font=("Arial", 12), bg="#4CAF50", fg="white",
            padx=20, pady=10, cursor="hand2"
        )
        self.btn.pack()
        
        self.status_label = tk.Label(root, text="", font=("Arial", 9), fg="blue")
        self.status_label.pack(pady=(10, 0))

    def select_file(self):
        initial_dir = os.path.dirname(os.path.abspath(__file__))
        filepath = filedialog.askopenfilename(
            initialdir=initial_dir,
            title="Выберите файл НПА",
            filetypes=(("Текстовые файлы", "*.txt"), ("Все файлы", "*.*"))
        )
        
        if filepath:
            self.btn.config(state=tk.DISABLED)
            self.cb_gemini.config(state=tk.DISABLED)
            self.status_label.config(text="Обработка файла, пожалуйста подождите...")
            
            t = threading.Thread(target=self.process_in_thread, args=(filepath,))
            t.start()

    def update_status(self, text):
        self.status_label.config(text=text)

    def process_in_thread(self, filepath):
        try:
            out_file, stats = process_file(
                filepath, 
                use_gemini=self.use_gemini_var.get(),
                progress_callback=lambda msg: self.root.after(0, self.update_status, msg)
            )
            self.root.after(0, self.finish_success, out_file, stats)
        except Exception as e:
            self.root.after(0, self.finish_error, str(e))

    def finish_success(self, out_file, stats):
        self.btn.config(state=tk.NORMAL)
        self.cb_gemini.config(state=tk.NORMAL)
        self.status_label.config(text="Готово!")
        
        msg = f"Файл успешно обработан!\n\nРезультат сохранен в:\n{os.path.basename(out_file)}"
        if self.use_gemini_var.get():
            msg += f"\n\nОтчет по обработке ИИ:\nВсего статей: {stats['total']}\nУспешно: {stats['processed']}\nОшибок: {stats['errors']}"
            
        messagebox.showinfo("Успех", msg)

    def finish_error(self, err_msg):
        self.btn.config(state=tk.NORMAL)
        self.cb_gemini.config(state=tk.NORMAL)
        self.status_label.config(text="Ошибка!")
        import traceback
        traceback.print_exc()
        messagebox.showerror("Ошибка", f"Произошла ошибка при обработке:\n{err_msg}")

if __name__ == "__main__":
    root = tk.Tk()
    app = NpaParserApp(root)
    root.mainloop()