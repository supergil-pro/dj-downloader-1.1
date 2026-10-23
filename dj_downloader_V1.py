import os
import io
import threading
import re
import subprocess
import requests
import webbrowser

import customtkinter as ctk
import yt_dlp

from PIL import Image, ImageOps
from tkinter import messagebox, filedialog


# הגדרות עיצוב
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")
# גופן עם תמיכה בעברית לכל הרכיבים (הגופן ברירת המחדל הופך סדר מילים בעברית)
ctk.ThemeManager.theme["CTkFont"]["family"] = "Segoe UI"

THUMB_SIZE = (112, 63)
FONT = "Segoe UI"

# פלטת צבעים
C = {
    "bg": "#0a0e17",
    "panel": "#111827",
    "card": "#172033",
    "card_hover": "#1c2740",
    "border": "#243049",
    "input": "#0d1424",
    "cyan": "#22d3ee",
    "cyan_dark": "#0891b2",
    "pink": "#e879f9",
    "text": "#e5e7eb",
    "muted": "#94a3b8",
    "ok": "#4ade80",
    "err": "#f87171",
}


def make_logo(size: int):
    """מצייר את הלוגו (תקליט ויניל עם חץ הורדה) — בלי קבצים חיצוניים."""
    from PIL import ImageDraw
    k = 4
    n = size * k
    c = n / 2
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # טבעת חיצונית בגרדיאנט טורקיז ← ורוד
    steps = 60
    for i in range(steps):
        t = i / (steps - 1)
        col = (int(0x22 + (0xe8 - 0x22) * t), int(0xd3 + (0x79 - 0xd3) * t), int(0xee + (0xf9 - 0xee) * t), 255)
        d.pieslice((0, 0, n, n), 135 + i * 6, 135 + (i + 1) * 6 + 1, fill=col)
    # גוף התקליט
    rr = n * 0.43
    d.ellipse((c - rr, c - rr, c + rr, c + rr), fill=(12, 16, 28, 255))
    for gr in (0.38, 0.33, 0.28):
        q = n * gr
        d.ellipse((c - q, c - q, c + q, c + q), outline=(44, 58, 88, 255), width=max(1, n // 100))
    # תווית מרכזית
    q = n * 0.21
    d.ellipse((c - q, c - q, c + q, c + q), fill=(34, 211, 238, 255))
    # חץ הורדה
    w = n * 0.07
    d.rectangle((c - w / 2, n * 0.36, c + w / 2, n * 0.53), fill=(10, 14, 23, 255))
    d.polygon([(n * 0.39, n * 0.51), (n * 0.61, n * 0.51), (c, n * 0.64)], fill=(10, 14, 23, 255))
    return img.resize((size, size), Image.LANCZOS)


# ---------- כרטיס הורדה (שורה לכל קובץ) ----------

class DownloadItem:
    """כרטיס ברשימת ההורדות: תמונה, שם, סטטוס, התקדמות וכפתור תיקייה. כל המתודות רצות ב־UI thread."""

    def __init__(self, parent, title: str):
        self.file_path = None
        self.thumb_image = None

        self.frame = ctk.CTkFrame(parent, corner_radius=14, fg_color=C["card"],
                                  border_width=1, border_color=C["border"])
        self.frame.pack(fill="x", padx=6, pady=5)
        self.frame.grid_columnconfigure(1, weight=1)

        self.thumb_label = ctk.CTkLabel(
            self.frame, text="♫", width=THUMB_SIZE[0], height=THUMB_SIZE[1],
            fg_color=C["input"], corner_radius=10, font=(FONT, 26), text_color=C["cyan"]
        )
        self.thumb_label.grid(row=0, column=0, rowspan=3, padx=(10, 14), pady=10)

        self.title_label = ctk.CTkLabel(
            self.frame, text=title, font=(FONT, 14, "bold"), text_color=C["text"],
            anchor="w", justify="left", wraplength=560
        )
        self.title_label.grid(row=0, column=1, sticky="ew", pady=(10, 0))

        self.status_label = ctk.CTkLabel(
            self.frame, text="ממתין בתור...", font=(FONT, 12),
            anchor="w", text_color=C["muted"]
        )
        self.status_label.grid(row=1, column=1, sticky="ew")

        self.progress = ctk.CTkProgressBar(self.frame, height=6, corner_radius=3,
                                           fg_color=C["input"], progress_color=C["cyan"])
        self.progress.grid(row=2, column=1, sticky="ew", pady=(2, 12))
        self.progress.set(0)

        self.folder_btn = ctk.CTkButton(
            self.frame, text="📂", width=52, height=52, corner_radius=12, font=(FONT, 22),
            fg_color=C["input"], hover_color=C["cyan_dark"], border_width=1,
            border_color=C["border"], state="disabled", command=self.reveal_in_folder
        )
        self.folder_btn.grid(row=0, column=2, rowspan=3, padx=(12, 12))

    def set_title(self, title: str):
        self.title_label.configure(text=title)

    def set_status(self, text: str, color: str = None):
        self.status_label.configure(text=text, text_color=color or C["muted"])

    def set_progress(self, value: float):
        self.frame.configure(border_color=C["cyan"])
        self.progress.set(value)

    def set_thumbnail(self, pil_image):
        self.thumb_image = ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=THUMB_SIZE)
        self.thumb_label.configure(image=self.thumb_image, text="", fg_color="transparent")

    def set_done(self, path: str, text: str = "✔ הורד בהצלחה"):
        self.file_path = path
        self.progress.configure(progress_color=C["ok"])
        self.progress.set(1.0)
        self.frame.configure(border_color=C["ok"])
        self.set_status(f"{text} • {os.path.basename(path)}", C["ok"])
        self.folder_btn.configure(state="normal", border_color=C["cyan"])

    def set_error(self, text: str):
        self.progress.set(0)
        self.frame.configure(border_color=C["err"])
        self.set_status(f"❌ {text}", C["err"])

    def reveal_in_folder(self):
        # פותח את תיקיית ההורדה עם הקובץ מסומן (realpath — Explorer לא מסמן נתיב מקוצר כמו PRESEN~1)
        if self.file_path and os.path.exists(self.file_path):
            subprocess.Popen(f'explorer /select,"{os.path.realpath(self.file_path)}"')
        elif self.file_path:
            webbrowser.open(os.path.dirname(self.file_path))


class DJDownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # חלון ראשי
        self.title("DJ Offline Playlist Downloader • GilOS")
        h = min(760, self.winfo_screenheight() - 90)
        self.geometry(f"1000x{h}+{max(0, (self.winfo_screenwidth() - 1000) // 2)}+10")
        self.minsize(900, 600)
        self.configure(fg_color=C["bg"])
        self.set_window_icon()

        # תיקיית ברירת מחדל
        self.download_dir = os.path.join(os.getcwd(), "DJ_Downloads")
        os.makedirs(self.download_dir, exist_ok=True)

        # משתנה: לדלג על קבצים קיימים
        self.skip_existing_var = ctk.BooleanVar(value=True)

        # תור הורדות
        self.download_queue = []
        self.queue_lock = threading.Lock()
        self.queue_running = False

        # זיכרון קליפבורד
        self.last_clipboard = ""

        # מבנה גריד
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # פאנל ראשי
        self.main_frame = ctk.CTkFrame(self, corner_radius=22, fg_color=C["panel"],
                                       border_width=1, border_color=C["border"])
        self.main_frame.grid(row=0, column=0, padx=16, pady=16, sticky="nsew")

        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(4, weight=1)

        # ---- כותרת עם לוגו ----
        header = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        header.grid(row=0, column=0, padx=24, pady=(18, 6), sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        logo = make_logo(112)
        self.logo_image = ctk.CTkImage(light_image=logo, dark_image=logo, size=(56, 56))
        ctk.CTkLabel(header, image=self.logo_image, text="").grid(row=0, column=0, rowspan=2, padx=(0, 14))

        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(title_row, text="DJ", font=(FONT, 28, "bold"), text_color=C["cyan"]).pack(side="left")
        ctk.CTkLabel(title_row, text=" Playlist Downloader", font=(FONT, 28, "bold"),
                     text_color=C["text"]).pack(side="left")
        ctk.CTkLabel(title_row, text="  1.1", font=(FONT, 13, "bold"), text_color=C["pink"]).pack(side="left", pady=(10, 0))

        self.label_sub = ctk.CTkLabel(
            header,
            text="YouTube • SoundCloud • Spotify  →  MP3 / WAV / FLAC / MP4   •   פלייליסטים ותמונות עטיפה",
            font=(FONT, 13), text_color=C["muted"]
        )
        self.label_sub.grid(row=1, column=1, sticky="w")

        self.btn_open_folder = ctk.CTkButton(
            header, text="📂  תיקיית הורדות", width=150, height=38, corner_radius=12,
            font=(FONT, 13, "bold"), fg_color=C["card"], hover_color=C["card_hover"],
            border_width=1, border_color=C["border"], text_color=C["text"],
            command=self.open_download_folder
        )
        self.btn_open_folder.grid(row=0, column=2, rowspan=2, padx=(10, 0))

        # ---- שורת קלט + כפתור הורדה ----
        input_row = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        input_row.grid(row=1, column=0, padx=24, pady=(10, 6), sticky="ew")
        input_row.grid_columnconfigure(0, weight=1)

        self.entry_url = ctk.CTkEntry(
            input_row, height=48, corner_radius=14, font=(FONT, 14),
            fg_color=C["input"], border_color=C["border"], border_width=2, text_color=C["text"],
            placeholder_text="הדבק כאן לינק מיוטיוב / פלייליסט / ספוטיפיי / סאונדקלאוד / או שם שיר..."
        )
        self.entry_url.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.entry_url.bind("<FocusIn>", lambda e: self.entry_url.configure(border_color=C["cyan"]))
        self.entry_url.bind("<FocusOut>", lambda e: self.entry_url.configure(border_color=C["border"]))

        self.btn_download = ctk.CTkButton(
            input_row, text="⬇  הורד", width=140, height=48, corner_radius=14,
            font=(FONT, 16, "bold"), fg_color=C["cyan"], hover_color=C["cyan_dark"],
            text_color=C["bg"], command=self.start_download_thread
        )
        self.btn_download.grid(row=0, column=1)

        # ---- שורת אפשרויות ----
        self.options_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.options_frame.grid(row=2, column=0, padx=24, pady=(4, 4), sticky="ew")
        self.options_frame.grid_columnconfigure(5, weight=1)

        # סוג מדיה: אודיו / וידאו
        self.media_type_var = ctk.StringVar(value="audio")
        self.format_var = ctk.StringVar(value="mp3")

        seg_style = dict(font=(FONT, 13, "bold"), height=34, corner_radius=10, fg_color=C["input"],
                         selected_color=C["cyan_dark"], selected_hover_color=C["cyan"],
                         unselected_color=C["input"], unselected_hover_color=C["card_hover"])

        ctk.CTkLabel(self.options_frame, text="סוג", font=(FONT, 13), text_color=C["muted"]).grid(row=0, column=0, padx=(0, 6))
        self.media_type_combo = ctk.CTkSegmentedButton(
            self.options_frame, values=["audio", "video"], variable=self.media_type_var, **seg_style
        )
        self.media_type_combo.grid(row=0, column=1, padx=(0, 18))

        ctk.CTkLabel(self.options_frame, text="פורמט", font=(FONT, 13), text_color=C["muted"]).grid(row=0, column=2, padx=(0, 6))
        self.format_combo = ctk.CTkSegmentedButton(
            self.options_frame, values=["mp3", "wav", "flac", "mp4"], variable=self.format_var, **seg_style
        )
        self.format_combo.grid(row=0, column=3, padx=(0, 18))

        cb_style = dict(font=(FONT, 13), fg_color=C["cyan_dark"], hover_color=C["cyan"],
                        border_color=C["border"], checkbox_width=22, checkbox_height=22)
        checks = ctk.CTkFrame(self.options_frame, fg_color="transparent")
        checks.grid(row=1, column=0, columnspan=8, sticky="w", pady=(8, 0))
        self.skip_existing_cb = ctk.CTkCheckBox(
            checks, text="דלג על קבצים שכבר קיימים", variable=self.skip_existing_var, **cb_style
        )
        self.skip_existing_cb.pack(side="left", padx=(0, 24))

        # מצב איכות מקסימלית: משווה מקורות (יוטיוב / סאונדקלאוד) ומוריד מהאיכותי ביותר
        self.best_quality_var = ctk.BooleanVar(value=False)
        self.best_quality_cb = ctk.CTkCheckBox(
            checks, text="🏆 השווה איכות בין אתרים והורד מהטוב ביותר (איטי יותר)",
            variable=self.best_quality_var, **cb_style
        )
        self.best_quality_cb.pack(side="left")

        small_btn = dict(height=34, corner_radius=10, font=(FONT, 12), fg_color=C["card"],
                         hover_color=C["card_hover"], border_width=1, border_color=C["border"],
                         text_color=C["text"])
        self.btn_choose_folder = ctk.CTkButton(self.options_frame, text="📁 בחר תיקייה", width=110,
                                               command=self.choose_download_folder, **small_btn)
        self.btn_choose_folder.grid(row=0, column=6, padx=(6, 0))
        self.btn_clear = ctk.CTkButton(self.options_frame, text="🧹 נקה", width=80,
                                       command=self.clear_log, **small_btn)
        self.btn_clear.grid(row=0, column=7, padx=(6, 0))

        # ---- התקדמות כללית ----
        prog_row = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        prog_row.grid(row=3, column=0, padx=24, pady=(8, 2), sticky="ew")
        prog_row.grid_columnconfigure(0, weight=1)
        self.progress = ctk.CTkProgressBar(prog_row, height=8, corner_radius=4,
                                           fg_color=C["input"], progress_color=C["pink"])
        self.progress.grid(row=0, column=0, sticky="ew")
        self.progress.set(0)
        self.overall_label = ctk.CTkLabel(prog_row, text="", width=120, font=(FONT, 12, "bold"),
                                          text_color=C["pink"], anchor="e")
        self.overall_label.grid(row=0, column=1, padx=(10, 0))

        # ---- רשימת הורדות — כרטיס לכל קובץ ----
        self.items_frame = ctk.CTkScrollableFrame(
            self.main_frame, fg_color=C["bg"], corner_radius=16,
            label_text="  הורדות", label_font=(FONT, 14, "bold"),
            label_fg_color=C["bg"], label_text_color=C["text"], label_anchor="e",
            scrollbar_button_color=C["border"], scrollbar_button_hover_color=C["cyan_dark"]
        )
        self.items_frame.grid(row=4, column=0, padx=24, pady=(8, 6), sticky="nsew")
        self.empty_label = None
        self.show_empty_state()

        # ---- תיבת לוג ----
        self.status_box = ctk.CTkTextbox(
            self.main_frame, height=72, corner_radius=12, font=(FONT, 11),
            fg_color=C["input"], text_color=C["muted"], border_width=0
        )
        self.status_box.grid(row=5, column=0, padx=24, pady=(4, 4), sticky="ew")
        self.status_box.bind("<Key>", lambda e: "break")

        # חתימה
        self.footer_label = ctk.CTkLabel(
            self.main_frame,
            text="Made by GilOS",
            font=(FONT, 11, "italic"),
            text_color=C["cyan"]
        )
        self.footer_label.grid(row=6, column=0, padx=24, pady=(0, 10), sticky="e")

        self.log_message("המערכת מוכנה. הדבק לינק ולחץ על ⬇ הורד.")
        self.log_message("תומך ביוטיוב, פלייליסטים, ספוטיפיי (דרך חיפוש), סאונדקלאוד, ועוד אתרים ש־yt-dlp מכיר.")
        self.log_message("זיהוי אוטומטי של קישור מהקליפבורד מופעל.")
        self.log_message("אם הורדה נכשלת — המערכת מחפשת אוטומטית את השיר באתרים אחרים.")

        # Hotkeys
        self.bind("<Return>", lambda e: self.start_download_thread())
        self.bind("<Control-v>", lambda e: self.paste_clipboard())
        self.bind("<Control-l>", lambda e: self.clear_log())

        # Providers
        self.providers = [
            YouTubeProvider(),
            SpotifyProvider(),
            SoundCloudProvider(),
            GenericMusicProvider(),
            FallbackSearchProvider()
        ]

        # Clipboard watcher
        self.after(1000, self.clipboard_watcher)

    # ---------- לוגים ו־UI ----------

    def log_message(self, message: str):
        self.status_box.insert("end", message + "\n")
        self.status_box.see("end")

    def safe_log(self, message: str):
        self.after(0, lambda: self.log_message(message))

    def ui(self, fn):
        # מריץ פעולה על ה־UI מתוך תהליכון רקע
        self.after(0, fn)

    def run_on_ui(self, fn):
        # מריץ פעולה על ה־UI ומחכה לתוצאה
        result = {}
        done = threading.Event()

        def wrapper():
            try:
                result["value"] = fn()
            finally:
                done.set()

        self.after(0, wrapper)
        done.wait()
        return result.get("value")

    def set_window_icon(self):
        # אייקון לחלון ולשורת המשימות, נוצר מהלוגו
        try:
            import tempfile
            path = os.path.join(tempfile.gettempdir(), "dj_downloader_icon.ico")
            make_logo(256).save(path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])
            self.iconbitmap(path)
        except Exception:
            pass

    def show_empty_state(self):
        self.empty_label = ctk.CTkLabel(
            self.items_frame, text="♫\nעדיין אין הורדות\nהדבק לינק לשיר או לפלייליסט ולחץ ⬇ הורד",
            font=(FONT, 15), text_color=C["muted"], justify="center"
        )
        self.empty_label.pack(pady=60)

    def new_item(self, title: str):
        if self.empty_label is not None:
            self.empty_label.destroy()
            self.empty_label = None
        return DownloadItem(self.items_frame, title)

    def set_overall(self, value: float, text: str = ""):
        self.progress.set(value)
        self.overall_label.configure(text=text)

    def clear_log(self):
        self.status_box.delete("1.0", "end")
        for child in self.items_frame.winfo_children():
            child.destroy()
        self.show_empty_state()
        self.set_overall(0)

    def paste_clipboard(self):
        try:
            text = self.clipboard_get()
            self.entry_url.delete(0, "end")
            self.entry_url.insert(0, text)
        except Exception:
            pass

    def open_download_folder(self):
        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir, exist_ok=True)
        webbrowser.open(self.download_dir)

    def choose_download_folder(self):
        folder = filedialog.askdirectory(initialdir=self.download_dir)
        if folder:
            self.download_dir = folder
            self.safe_log(f"תיקיית הורדה עודכנה ל: {self.download_dir}")

    # ---------- Clipboard watcher ----------

    def clipboard_watcher(self):
        try:
            text = self.clipboard_get()
            if text != self.last_clipboard:
                self.last_clipboard = text
                if text.startswith("http") and any(
                    k in text for k in ["youtube.com", "youtu.be", "spotify.com", "soundcloud.com"]
                ):
                    self.safe_log(f"זוהה קישור חדש בלוח: {text}")
                    self.entry_url.delete(0, "end")
                    self.entry_url.insert(0, text)
        except Exception:
            pass

        self.after(1000, self.clipboard_watcher)

    # ---------- Threading + Queue ----------

    def enqueue_download(self, url: str):
        with self.queue_lock:
            self.download_queue.append(url)
        self.safe_log(f"נוסף לתור: {url}")

    def start_download_thread(self):
        url = self.entry_url.get().strip()
        if not url:
            self.safe_log("שגיאה: נא להזין קישור או שם שיר.")
            return

        self.enqueue_download(url)
        with self.queue_lock:
            if self.queue_running:
                return
            self.queue_running = True
        threading.Thread(target=self.process_queue, daemon=True).start()

    def process_queue(self):
        while True:
            with self.queue_lock:
                if not self.download_queue:
                    self.queue_running = False
                    break
                url = self.download_queue.pop(0)

            self.safe_log(f"🎵 מתחיל הורדה מהתור: {url}")
            self.download_process(url)
            self.safe_log("✅ סיום משימה מהתור.")

    # ---------- Spotify helpers (ללא API) ----------

    def extract_spotify_name(self, url: str):
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            html = requests.get(url, headers=headers, timeout=10).text
            title_match = re.search(r'<meta property="og:title" content="(.*?)"', html)
            if title_match:
                return title_match.group(1)
        except Exception:
            return None
        return None

    # ---------- YouTube search ----------

    def search_youtube(self, query: str):
        try:
            opts = {
                "quiet": True,
                "skip_download": True,
                "default_search": "ytsearch1",
                "extract_flat": "in_playlist",
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(query, download=False)
                if "entries" in info and info["entries"]:
                    e = info["entries"][0]
                    return e.get("webpage_url") or e.get("url")
        except Exception:
            return None
        return None

    # ---------- בחירה סלקטיבית מתוך פלייליסט ----------

    @staticmethod
    def entry_title(e, idx):
        # שם לתצוגה; בסאונדקלאוד אין שם ברשימה — לוקחים אותו מהלינק
        if e.get("title"):
            return e["title"]
        url = (e.get("url") or "").split("?")[0].rstrip("/")
        if "soundcloud.com/" in url:
            parts = url.split("soundcloud.com/")[1].split("/")
            if len(parts) >= 2:
                return f"{parts[0].replace('-', ' ')} - {parts[-1].replace('-', ' ')}"
        return f"Track {idx + 1}"

    @staticmethod
    def entry_unavailable(e):
        # שירים פרטיים/מחוקים ביוטיוב — לא מסומנים כברירת מחדל
        title = e.get("title") or ""
        if title in ("[Private video]", "[Deleted video]"):
            return True
        return not title and e.get("ie_key") == "Youtube"

    def open_playlist_selector(self, entries, result_container, event_done):
        win = ctk.CTkToplevel(self, fg_color=C["panel"])
        win.title("בחירת שירים מהפלייליסט")
        win.geometry(f"640x560+{self.winfo_rootx() + 180}+{self.winfo_rooty() + 60}")
        win.resizable(False, False)
        # להביא את החלון לקדמת המסך (CTkToplevel נפתח לפעמים מאחורי החלון הראשי)
        win.transient(self)
        win.lift()
        win.attributes("-topmost", True)
        win.after(300, lambda: (win.lift(), win.focus_force(), win.grab_set()))
        win.after(1000, lambda: win.attributes("-topmost", False))
        win.after(250, lambda: win.iconbitmap(os.path.join(__import__("tempfile").gettempdir(), "dj_downloader_icon.ico")))

        frame = ctk.CTkFrame(win, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=16, pady=14)

        ctk.CTkLabel(frame, text="בחר אילו שירים להוריד", font=(FONT, 18, "bold"),
                     text_color=C["text"]).pack(pady=(0, 2))
        count_label = ctk.CTkLabel(frame, text="", font=(FONT, 12), text_color=C["muted"])
        count_label.pack(pady=(0, 8))

        scroll = ctk.CTkScrollableFrame(frame, fg_color=C["bg"], corner_radius=14,
                                        scrollbar_button_color=C["border"],
                                        scrollbar_button_hover_color=C["cyan_dark"])
        scroll.pack(pady=(0, 10), fill="both", expand=True)

        check_vars = []

        def update_count(*_):
            n = sum(1 for var, _, _ in check_vars if var.get())
            count_label.configure(text=f"{n} מתוך {len(check_vars)} מסומנים")

        for idx, e in enumerate(entries):
            title = self.entry_title(e, idx)
            unavailable = self.entry_unavailable(e)
            var = ctk.BooleanVar(value=not unavailable)
            var.trace_add("write", update_count)
            cb = ctk.CTkCheckBox(scroll, text=f"{idx + 1:>3}.  {title}", variable=var, font=(FONT, 13),
                                 fg_color=C["cyan_dark"], hover_color=C["cyan"], border_color=C["border"],
                                 text_color=C["muted"] if unavailable else C["text"],
                                 checkbox_width=20, checkbox_height=20)
            cb.pack(anchor="w", padx=10, pady=3)
            check_vars.append((var, e, cb))
        update_count()

        # שמות חסרים (למשל בסאונדקלאוד) — נשלפים ברקע ומתעדכנים בחלון
        missing = [(i, e, cb) for i, (_, e, cb) in enumerate(check_vars) if not e.get("title") and e.get("url")]

        def fetch_titles():
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
                for i, e, cb in missing:
                    if not win.winfo_exists():
                        return
                    try:
                        t = ydl.extract_info(e["url"], download=False, process=False).get("title")
                    except Exception:
                        t = None
                    if t:
                        e["title"] = t
                        self.ui(lambda cb=cb, t=t, i=i: cb.winfo_exists() and cb.configure(text=f"{i + 1:>3}.  {t}"))

        if missing:
            threading.Thread(target=fetch_titles, daemon=True).start()

        buttons_frame = ctk.CTkFrame(frame, fg_color="transparent")
        buttons_frame.pack(pady=(2, 0))

        def select_all():
            for var, _, _ in check_vars:
                var.set(True)

        def clear_all():
            for var, _, _ in check_vars:
                var.set(False)

        def finish(selected):
            result_container["entries"] = selected
            event_done.set()
            win.destroy()

        def confirm():
            finish([e for var, e, _ in check_vars if var.get()])

        def cancel():
            finish([])

        win.protocol("WM_DELETE_WINDOW", cancel)

        sec = dict(height=38, corner_radius=12, font=(FONT, 13), fg_color=C["card"],
                   hover_color=C["card_hover"], border_width=1, border_color=C["border"], text_color=C["text"])
        ctk.CTkButton(buttons_frame, text="בחר הכול", width=100, command=select_all, **sec).grid(row=0, column=0, padx=5)
        ctk.CTkButton(buttons_frame, text="נקה הכול", width=100, command=clear_all, **sec).grid(row=0, column=1, padx=5)
        ctk.CTkButton(buttons_frame, text="ביטול", width=100, command=cancel, **sec).grid(row=0, column=2, padx=5)
        ctk.CTkButton(buttons_frame, text="⬇  הורד מסומנים", width=170, height=38, corner_radius=12,
                      font=(FONT, 14, "bold"), fg_color=C["cyan"], hover_color=C["cyan_dark"],
                      text_color=C["bg"], command=confirm).grid(row=0, column=3, padx=5)

    # ---------- תמונות ----------

    def load_thumbnail(self, item: DownloadItem, url: str):
        # מוריד את תמונת השיר ברקע ומציג אותה בכרטיס
        def worker():
            try:
                data = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10).content
                img = Image.open(io.BytesIO(data)).convert("RGB")
                img = ImageOps.fit(img, (THUMB_SIZE[0] * 2, THUMB_SIZE[1] * 2))
                self.ui(lambda: item.set_thumbnail(img))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    # ---------- הורדה (אודיו/וידאו) ----------

    def target_extension(self):
        media_type = self.media_type_var.get()
        fmt = self.format_var.get()
        if media_type == "video":
            return "mp4"
        return "m4a" if fmt == "mp4" else fmt

    @staticmethod
    def short_error(e):
        msg = str(e).replace("ERROR: ", "")
        if "Private video" in msg:
            return "סרטון פרטי — לא ניתן להוריד"
        if "Video unavailable" in msg or "not available" in msg:
            return "הסרטון לא זמין"
        if "Sign in to confirm your age" in msg:
            return "סרטון עם הגבלת גיל — לא ניתן להוריד"
        msg = re.sub(r"^\[[^\]]+\] [\w-]+: ", "", msg)
        return msg.split(". ")[0][:150]

    def build_download_opts(self, outtmpl, hooks, pp_hooks):
        media_type = self.media_type_var.get()
        ext = self.target_extension()

        postprocessors = []
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "outtmpl": outtmpl,
            "progress_hooks": hooks,
            "postprocessor_hooks": pp_hooks,
        }

        if media_type == "audio":
            opts["format"] = "bestaudio/best"
            extract = {"key": "FFmpegExtractAudio", "preferredcodec": ext}
            if ext == "mp3":
                extract["preferredquality"] = "320"
            postprocessors.append(extract)
        else:
            opts["format"] = "bestvideo+bestaudio/best"
            opts["merge_output_format"] = "mp4"

        # תמונת עטיפה ותגיות בתוך הקובץ (WAV לא תומך בעטיפה)
        if ext in ("mp3", "flac", "m4a", "mp4"):
            opts["writethumbnail"] = True
            postprocessors.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"})
            postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})
            postprocessors.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})

        opts["postprocessors"] = postprocessors
        return opts

    # ---------- חיפוש מקור חלופי והשוואת איכות ----------

    CODEC_WEIGHT = {"flac": 3.0, "alac": 3.0, "pcm": 3.0, "wav": 3.0, "opus": 1.35,
                    "vorbis": 1.25, "mp4a": 1.15, "aac": 1.15, "mp3": 1.0}

    def audio_quality(self, info):
        """ציון איכות לפי הקול הטוב ביותר במקור: קצב סיביות × יעילות הקודק (opus ב־160 עדיף על mp3 ב־160)."""
        best, desc = 0.0, ""
        fmts = info.get("formats") or [info]
        # רק פורמטים של קול בלבד (בפורמט משולב ה־tbr כולל את הווידאו)
        audio_only = [f for f in fmts if f.get("vcodec") in ("none", None) and f.get("acodec") not in ("none", None, "")]
        for f in audio_only or fmts:
            acodec = (f.get("acodec") or "").split(".")[0].lower()
            if acodec in ("", "none"):
                continue
            abr = f.get("abr") or (f.get("tbr") if audio_only else 0) or 0
            score = abr * self.CODEC_WEIGHT.get(acodec, 1.0)
            if score > best:
                best, desc = score, f"{int(abr)}kbps {acodec}"
        return best, desc

    @staticmethod
    def site_name(info_or_url):
        if isinstance(info_or_url, dict):
            return info_or_url.get("extractor_key") or info_or_url.get("extractor") or "?"
        return "SoundCloud" if "soundcloud" in info_or_url else "YouTube" if "youtu" in info_or_url else "web"

    @staticmethod
    def title_match(query: str, title: str) -> bool:
        stop = {"official", "video", "audio", "lyrics", "hd", "hq", "music", "remastered", "the", "ft", "feat"}
        q = {w for w in re.findall(r"\w+", query.lower()) if w not in stop and len(w) > 1}
        t = set(re.findall(r"\w+", title.lower()))
        # גרסאות אחרות של השיר לא נחשבות התאמה, אלא אם ביקשו אותן
        variants = {"karaoke", "cover", "instrumental", "remix", "sped", "slowed", "nightcore", "reverb", "8d", "acapella"}
        if (t & variants) - set(re.findall(r"\w+", query.lower())):
            return False
        return bool(q) and len(q & t) / len(q) >= 0.6

    def search_sources(self, query: str, duration=None, exclude_url=None, item=None):
        """מחפש את השיר ביוטיוב ובסאונדקלאוד ומחזיר מועמדים ממוינים מהאיכותי ביותר."""
        candidates = []
        opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
        for prefix, site in (("ytsearch3", "YouTube"), ("scsearch3", "SoundCloud")):
            if item:
                self.ui(lambda site=site: item.set_status(f"🔎 מחפש ב־{site}...", C["pink"]))
            try:
                with yt_dlp.YoutubeDL({**opts, "extract_flat": "in_playlist"}) as ydl:
                    found = ydl.extract_info(f"{prefix}:{query}", download=False).get("entries") or []
            except Exception:
                continue
            checked = 0
            for e in found:
                url = e.get("webpage_url") or e.get("url")
                if not url or url == exclude_url or checked >= 2:
                    continue
                if e.get("title") and not self.title_match(query, e["title"]):
                    continue
                checked += 1
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        full = ydl.extract_info(url, download=False)
                except Exception:
                    continue
                if not self.title_match(query, full.get("title") or ""):
                    continue
                if duration and full.get("duration") and abs(full["duration"] - duration) > 20:
                    continue
                score, desc = self.audio_quality(full)
                if score > 0:
                    candidates.append({"score": score, "desc": desc, "url": full.get("webpage_url") or url,
                                       "info": full, "site": site})
        candidates.sort(key=lambda c: c["score"], reverse=True)
        for c in candidates:
            self.safe_log(f"   • {c['site']}: {c['info'].get('title')} — {c['desc']}")
        return candidates

    def download_single(self, url: str, title_hint: str = None):
        """הורדת קובץ בודד עם כרטיס משלו. אם נכשל — מחפש מקור חלופי. מחזיר True אם הצליח."""
        item = self.run_on_ui(lambda: self.new_item(title_hint or url))
        self.ui(lambda: item.set_status("שולף מידע..."))

        outtmpl = os.path.join(self.download_dir, "%(title)s.%(ext)s")
        tried = set()
        query = None if (title_hint or "").startswith(("Track ", "http")) else title_hint
        duration = None
        error = None

        # שליפת מידע מהמקור המקורי
        info = None
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True,
                                   "skip_download": True}) as ydl:
                info = ydl.extract_info(url, download=False)
            query = info.get("title") or query
            duration = info.get("duration")
        except Exception as e:
            error = self.short_error(e)
            self.safe_log(f"❌ {title_hint or url}: {error}")

        candidates = []
        if info:
            score, desc = self.audio_quality(info)
            candidates.append({"score": score, "desc": desc, "url": url, "info": info, "site": self.site_name(info)})
            if self.best_quality_var.get() and query and self.media_type_var.get() == "audio":
                self.safe_log(f"🏆 משווה איכות עבור: {query}")
                candidates += self.search_sources(query, duration, url, item)
                candidates.sort(key=lambda c: c["score"], reverse=True)

        # מנסה מקורות לפי הסדר; אם כולם נכשלו — מחפש באתרים אחרים
        searched = bool(len(candidates) > 1)
        while True:
            if not candidates and not searched and query:
                searched = True
                self.safe_log(f"🔁 מחפש מקור חלופי עבור: {query}")
                candidates = [c for c in self.search_sources(query, duration, url, item) if c["url"] not in tried]
            if not candidates:
                break
            c = candidates.pop(0)
            if c["url"] in tried:
                continue
            tried.add(c["url"])
            path, err = self.download_from(c, item, outtmpl, alt=c["url"] != url)
            if path:
                return True
            error = err

        if not query and not info:
            error = (error or "שגיאה") + " • אין שם שיר לחיפוש חלופי"
        elif searched:
            error = (error or "שגיאה") + " • לא נמצא מקור חלופי"
        self.ui(lambda: item.set_error(error))
        return False

    def download_from(self, cand, item, outtmpl, alt=False):
        """מוריד ממקור אחד. מחזיר (נתיב, None) בהצלחה או (None, שגיאה)."""
        info = cand["info"]
        url = cand["url"]
        title = info.get("title") or url
        self.ui(lambda: (item.set_title(title), item.set_status("מתחיל הורדה...")))
        if info.get("thumbnail"):
            self.load_thumbnail(item, info["thumbnail"])

        with yt_dlp.YoutubeDL({"quiet": True, "outtmpl": outtmpl}) as ydl:
            root, _ = os.path.splitext(ydl.prepare_filename(info))
        final_path = root + "." + self.target_extension()
        source = f"{cand['site']} • {cand['desc']}" if cand.get("desc") else cand["site"]
        if alt:
            source = "מקור חלופי: " + source

        if os.path.exists(final_path) and self.skip_existing_var.get():
            self.ui(lambda: item.set_done(final_path, "כבר קיים — דולג"))
            self.safe_log(f"קובץ כבר קיים, מדלג: {os.path.basename(final_path)}")
            return final_path, None

        def ytdl_hook(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                if total:
                    val = d.get("downloaded_bytes", 0) / total
                    speed = d.get("speed")
                    speed_txt = f"{speed / 1024 / 1024:.1f} MB/s" if speed else ""
                    self.ui(lambda: (item.set_progress(val * 0.9),
                                     item.set_status(f"מוריד {val * 100:.0f}%  {speed_txt}  •  {source}")))
            elif d["status"] == "finished":
                self.ui(lambda: item.set_status("ההורדה הסתיימה, מעבד..."))

        def pp_hook(d):
            if d["status"] == "started":
                name = d.get("postprocessor", "")
                label = {"ExtractAudio": "ממיר פורמט...", "EmbedThumbnail": "מוסיף תמונת עטיפה...",
                         "Metadata": "מוסיף תגיות..."}.get(name)
                if label:
                    self.ui(lambda: item.set_status(label))

        try:
            with yt_dlp.YoutubeDL(self.build_download_opts(outtmpl, [ytdl_hook], [pp_hook])) as ydl:
                result = ydl.extract_info(url, download=True)
            downloads = (result or {}).get("requested_downloads") or []
            path = downloads[0].get("filepath") if downloads else None
            if not path or not os.path.exists(path):
                path = final_path
            if not os.path.exists(path):
                raise RuntimeError("הקובץ לא נוצר")
        except Exception as e:
            msg = self.short_error(e)
            self.safe_log(f"❌ הורדה מ־{cand['site']} נכשלה: {msg}")
            self.ui(lambda: item.set_status(f"❌ {msg} — מנסה מקור אחר...", C["err"]))
            return None, msg

        self.ui(lambda: item.set_done(path, f"✔ הורד • {source}"))
        self.safe_log(f"✔ הורד: {os.path.basename(path)}  ({source})")
        return path, None

    def download_playlist(self, info):
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            self.safe_log("שגיאה: לא נמצאו שירים בפלייליסט.")
            return

        self.safe_log(f"נמצא פלייליסט: {info.get('title', 'Playlist')} ({len(entries)} שירים).")
        self.safe_log("פותח חלון לבחירה סלקטיבית של שירים...")

        result_container = {}
        event_done = threading.Event()
        self.ui(lambda: self.open_playlist_selector(entries, result_container, event_done))
        event_done.wait()

        selected_entries = result_container.get("entries", [])
        if not selected_entries:
            self.safe_log("לא נבחרו שירים להורדה.")
            return

        total = len(selected_entries)
        self.safe_log(f"נבחרו {total} שירים להורדה.")
        self.ui(lambda: self.set_overall(0, f"0 / {total}"))

        ok = 0
        for idx, e in enumerate(selected_entries, start=1):
            url = e.get("webpage_url") or e.get("url")
            title = self.entry_title(e, idx - 1)
            if url and not url.startswith("http"):
                url = f"https://www.youtube.com/watch?v={url}"
            if not url:
                self.safe_log(f"מדלג על שיר ללא URL: {title}")
                continue

            self.safe_log(f"[{idx}/{total}] {title}")
            if self.download_single(url, title):
                ok += 1
            self.ui(lambda v=idx / total, t=f"{idx} / {total}": self.set_overall(v, t))

        self.safe_log(f"✔ פלייליסט הסתיים: {ok} מתוך {total} הורדו בהצלחה.")
        self.safe_log(f"קבצים נשמרו בתיקייה: {self.download_dir}")

    def download_url(self, url: str):
        """מזהה אם הקישור הוא שיר בודד או פלייליסט ומוריד בהתאם."""
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True,
                                   "extract_flat": "in_playlist"}) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            raise RuntimeError(self.short_error(e))

        if info.get("_type") == "playlist" or "entries" in info:
            self.download_playlist(info)
        else:
            self.ui(lambda: self.set_overall(0, "0 / 1"))
            self.download_single(info.get("webpage_url") or url, info.get("title"))
            self.ui(lambda: self.set_overall(1.0, "1 / 1"))

    # ---------- תהליך ראשי ----------

    def download_process(self, url: str):
        try:
            if not url.startswith("http"):
                self.safe_log(f"זוהה שם שיר בלבד, מחפש ביוטיוב: {url}")
                yt_url = self.search_youtube(url)
                if not yt_url:
                    self.safe_log("שגיאה: לא נמצא שיר מתאים ביוטיוב.")
                    return
                self.safe_log(f"נמצא ביוטיוב: {yt_url}")
                url = yt_url

            self.safe_log("🔎 בודק ספק מתאים...")

            for provider in self.providers:
                if provider.can_handle(url):
                    self.safe_log(f"➡ מנסה ספק: {provider.name}")
                    try:
                        provider.download(self, url)
                        return
                    except Exception as e:
                        self.safe_log(f"❌ ספק {provider.name} נכשל: {str(e)}")
                        continue

            self.safe_log("❌ אף ספק לא הצליח לטפל בקישור.")

        except Exception as e:
            self.safe_log(f"שגיאה בתהליך: {str(e)}")


# ---------- Providers ----------

class BaseProvider:
    name = "Base"

    def can_handle(self, url: str) -> bool:
        return False

    def download(self, app: DJDownloaderApp, url: str):
        raise NotImplementedError


class YouTubeProvider(BaseProvider):
    name = "YouTube"

    def can_handle(self, url: str) -> bool:
        return "youtube.com" in url or "youtu.be" in url

    def download(self, app: DJDownloaderApp, url: str):
        app.download_url(url)


class SpotifyProvider(BaseProvider):
    name = "Spotify"

    def can_handle(self, url: str) -> bool:
        return "spotify.com" in url

    def download(self, app: DJDownloaderApp, url: str):
        app.safe_log("🎧 ספק: Spotify → YouTube")
        name = app.extract_spotify_name(url)
        if not name:
            raise RuntimeError("לא ניתן לחלץ שם מספוטיפיי")
        yt_url = app.search_youtube(name)
        if not yt_url:
            raise RuntimeError("לא נמצא שיר מתאים ביוטיוב עבור ספוטיפיי")
        app.download_single(yt_url, name)


class SoundCloudProvider(BaseProvider):
    name = "SoundCloud"

    def can_handle(self, url: str) -> bool:
        return "soundcloud.com" in url

    def download(self, app: DJDownloaderApp, url: str):
        app.download_url(url)


class GenericMusicProvider(BaseProvider):
    name = "Generic Music (yt-dlp)"

    def can_handle(self, url: str) -> bool:
        return url.startswith("http")

    def download(self, app: DJDownloaderApp, url: str):
        app.download_url(url)


class FallbackSearchProvider(BaseProvider):
    name = "Fallback Search"

    def can_handle(self, url: str) -> bool:
        return True

    def download(self, app: DJDownloaderApp, url: str):
        app.safe_log("🔍 ספק: חיפוש fallback ביוטיוב")
        yt_url = app.search_youtube(url)
        if not yt_url:
            raise RuntimeError("גם fallback לא הצליח למצוא תוצאה")
        app.download_url(yt_url)


if __name__ == "__main__":
    app = DJDownloaderApp()
    app.mainloop()
