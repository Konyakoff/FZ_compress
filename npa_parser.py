import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import json
import threading
import urllib.request
import urllib.parse
import time
import importlib
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

def call_gemini(text, prompt_instruction, model_name="gemini-3.0-pro"):
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise Exception("API ключ не найден.")
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    
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
    
    max_retries = 10 # Увеличили количество попыток для стабильности
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result['candidates'][0]['content']['parts'][0]['text'].strip()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                if attempt < max_retries - 1:
                    # При 429 ошибке делаем очень большую задержку, так как лимиты восстанавливаются раз в минуту
                    time.sleep(20 * (attempt + 1))
                    continue
                else:
                    raise Exception("Превышен лимит запросов к API (429) даже после всех попыток.")
            
            error_info = e.read().decode('utf-8')
            if e.code == 404:
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

PARSERS_MAP = {
    "1.St_1-35.5.FZ_53 (Разделы, Статьи)": {
        "module": "parsers.parser_fz_53",
        "prompt_key": "FZ_53"
    },
    "6.FZ_127_O_Vnesenii_Izmeneniy (Только Статьи)": {
        "module": "parsers.parser_fz_127",
        "prompt_key": "FZ_127"
    },
    "7.FZ_113_AGS (Главы, Статьи)": {
        "module": "parsers.parser_fz_113",
        "prompt_key": "FZ_113"
    },
    "2.PP_565_bezRaspBol (Положение о ВВЭ)": {
        "module": "parsers.parser_pp_565",
        "prompt_key": "PP_565"
    },
    "4.PP_663_Pologenie_o_Prizyve (Положение о призыве)": {
        "module": "parsers.parser_pp_663",
        "prompt_key": "PP_663"
    }
}

def process_file(filepath, parser_choice, use_gemini=False, model_name="gemini-3.0-pro", progress_callback=None):
    load_env()
    
    parser_config = PARSERS_MAP[parser_choice]
    parser_module = importlib.import_module(parser_config["module"])
    prompt_key = parser_config["prompt_key"]
    
    prompt_instruction = ""
    if use_gemini:
        if not os.environ.get("GEMINI_API_KEY", ""):
            raise Exception("API ключ не найден! Создайте файл .env рядом со скриптом и добавьте туда строку:\nGEMINI_API_KEY=ваш_токен")
            
        prompt_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'prompt.json')
        if not os.path.exists(prompt_file):
            raise Exception("Файл prompt.json не найден в директории скрипта!")
        with open(prompt_file, 'r', encoding='utf-8') as f:
            prompt_data = json.load(f)
            prompt_instruction = prompt_data.get(prompt_key, "")
            if not prompt_instruction:
                raise Exception(f"В prompt.json не найден промпт с ключом '{prompt_key}'!")

    lines = detect_encoding_and_read(filepath)

    # Используем выбранный модуль для парсинга структуры
    result_elements = parser_module.parse(lines)

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
                summary = call_gemini(full_text, prompt_instruction, model_name)
                elem["summary"] = summary
            except Exception as e:
                elem["summary"] = f"[Ошибка суммаризации: {str(e)}]"
                elem["has_error"] = True
            return elem

        with ThreadPoolExecutor(max_workers=1) as executor:
            futures = []
            for elem in articles_to_process:
                futures.append(executor.submit(process_single_article, elem))
                time.sleep(2) # Гарантированная задержка между отправками для защиты TPM (Tokens Per Minute)
                
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
            if result_lines and result_lines[-1] != "":
                result_lines.append("")
            result_lines.append(elem["content"])
        elif elem["type"] == "article":
            if result_lines and i > 0 and result_elements[i-1]["type"] not in ["section", "text"]:
                if result_lines[-1] != "":
                    result_lines.append("")
            
            if use_gemini:
                if "PP_" in prompt_key:
                    # Для пунктов постановления пишем выжимку на той же строке
                    result_lines.append(f"{elem['title']} {elem.get('summary', '')}")
                else:
                    # Для статей пишем выжимку с новой строки
                    result_lines.append(elem["title"])
                    result_lines.append(elem.get("summary", ""))
            else:
                result_lines.append(elem["title"])

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
        self.root.geometry("550x400")
        self.root.eval('tk::PlaceWindow . center')
        self.root.configure(padx=20, pady=20)
        
        # Загрузка моделей
        self.models_map = {}
        models_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models.json')
        if os.path.exists(models_file):
            try:
                with open(models_file, 'r', encoding='utf-8') as f:
                    self.models_map = json.load(f)
            except:
                self.models_map = {"Gemini 3.0 Pro": "gemini-3.0-pro"}
        else:
            self.models_map = {"Gemini 3.0 Pro": "gemini-3.0-pro"}
            
        title_label = tk.Label(root, text="Извлечение структуры НПА", font=("Arial", 14, "bold"))
        title_label.pack(pady=(0, 10))
        
        desc_label = tk.Label(
            root, 
            text="Выберите тип документа и .txt файл.\nСкрипт извлечет нужную структуру.", 
            font=("Arial", 10), justify=tk.CENTER
        )
        desc_label.pack(pady=(0, 10))
        
        # Выпадающий список
        self.parser_var = tk.StringVar()
        self.parser_combo = ttk.Combobox(
            root, 
            textvariable=self.parser_var,
            values=list(PARSERS_MAP.keys()),
            state="readonly",
            width=50,
            font=("Arial", 10)
        )
        self.parser_combo.current(0)
        self.parser_combo.pack(pady=(0, 15))
        
        self.use_gemini_var = tk.BooleanVar(value=False)
        self.cb_gemini = tk.Checkbutton(
            root, 
            text="Использовать ИИ (Gemini) для выжимки статей", 
            variable=self.use_gemini_var,
            command=self.toggle_model_combo,
            font=("Arial", 10)
        )
        self.cb_gemini.pack(pady=(0, 10))
        
        # Выпадающий список моделей
        model_frame = tk.Frame(root)
        model_frame.pack(pady=(0, 15))
        
        tk.Label(model_frame, text="Модель ИИ:", font=("Arial", 10)).pack(side=tk.LEFT, padx=(0, 5))
        
        self.model_var = tk.StringVar()
        self.model_combo = ttk.Combobox(
            model_frame, 
            textvariable=self.model_var,
            values=list(self.models_map.keys()),
            state="disabled",
            width=30,
            font=("Arial", 10)
        )
        # Устанавливаем по умолчанию Gemini 3.0 Pro, если есть
        if "Gemini 3.0 Pro" in self.models_map:
            self.model_combo.set("Gemini 3.0 Pro")
        elif self.models_map:
            self.model_combo.current(0)
        self.model_combo.pack(side=tk.LEFT)
        
        self.btn = tk.Button(
            root, text="Выбрать файл и обработать", command=self.select_file, 
            font=("Arial", 12), bg="#4CAF50", fg="white",
            padx=20, pady=10, cursor="hand2"
        )
        self.btn.pack()
        
        self.status_label = tk.Label(root, text="", font=("Arial", 9), fg="blue")
        self.status_label.pack(pady=(10, 0))

    def toggle_model_combo(self):
        if self.use_gemini_var.get():
            self.model_combo.config(state="readonly")
        else:
            self.model_combo.config(state="disabled")

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
            self.parser_combo.config(state=tk.DISABLED)
            self.model_combo.config(state=tk.DISABLED)
            self.status_label.config(text="Обработка файла, пожалуйста подождите...")
            
            parser_choice = self.parser_var.get()
            model_key = self.model_var.get()
            model_id = self.models_map.get(model_key, "gemini-3.0-pro")
            
            t = threading.Thread(target=self.process_in_thread, args=(filepath, parser_choice, model_id))
            t.start()

    def update_status(self, text):
        self.status_label.config(text=text)

    def process_in_thread(self, filepath, parser_choice, model_id):
        try:
            out_file, stats = process_file(
                filepath,
                parser_choice,
                use_gemini=self.use_gemini_var.get(),
                model_name=model_id,
                progress_callback=lambda msg: self.root.after(0, self.update_status, msg)
            )
            self.root.after(0, self.finish_success, out_file, stats)
        except Exception as e:
            self.root.after(0, self.finish_error, str(e))

    def finish_success(self, out_file, stats):
        self.btn.config(state=tk.NORMAL)
        self.cb_gemini.config(state=tk.NORMAL)
        self.parser_combo.config(state="readonly")
        if self.use_gemini_var.get():
            self.model_combo.config(state="readonly")
        else:
            self.model_combo.config(state="disabled")
        self.status_label.config(text="Готово!")
        
        msg = f"Файл успешно обработан!\n\nРезультат сохранен в:\n{os.path.basename(out_file)}"
        if self.use_gemini_var.get():
            msg += f"\n\nОтчет по обработке ИИ:\nВсего: {stats['total']}\nУспешно: {stats['processed']}\nОшибок: {stats['errors']}"
            
        messagebox.showinfo("Успех", msg)

    def finish_error(self, err_msg):
        self.btn.config(state=tk.NORMAL)
        self.cb_gemini.config(state=tk.NORMAL)
        self.parser_combo.config(state="readonly")
        if self.use_gemini_var.get():
            self.model_combo.config(state="readonly")
        else:
            self.model_combo.config(state="disabled")
        self.status_label.config(text="Ошибка!")
        import traceback
        traceback.print_exc()
        messagebox.showerror("Ошибка", f"Произошла ошибка при обработке:\n{err_msg}")

if __name__ == "__main__":
    root = tk.Tk()
    app = NpaParserApp(root)
    root.mainloop()
