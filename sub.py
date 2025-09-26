import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import os
import json
import time

# subliminal imports
try:
    from subliminal import Video, download_best_subtitles, save_subtitles, region
    from babelfish import Language
    region.configure('dogpile.cache.memory')
    SUBLIMINAL_AVAILABLE = True
except Exception as e:
    SUBLIMINAL_AVAILABLE = False
    SUBLIMINAL_ERROR = str(e)

CONFIG_PATH = os.path.join(os.path.expanduser("~"), "subtitle_downloader_config.json")


class SubtitleDownloaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Auto Subtitle Downloader (with job status)")
        self.root.geometry("840x420")
        self.root.resizable(False, False)

        self.load_config()
        self.queue = []  # list of dicts: {'query': str, 'item': tree_item_id}
        self.queue_lock = threading.Lock()
        self.processing = False
        self.stop_flag = False

        self.setup_gui()

        if not SUBLIMINAL_AVAILABLE:
            self.status_var.set("Missing subliminal library. See startup notice.")
            messagebox.showwarning(
                "Missing dependency",
                "The 'subliminal' library is required.\n\nInstall with:\n\npip install subliminal babelfish requests\n\nImport error:\n" + SUBLIMINAL_ERROR
            )

    def load_config(self):
        self.last_dir = os.path.expanduser("~")
        self.default_download_dir = os.path.join(os.path.expanduser("~"), "Desktop")
        self.default_language = "eng"
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    self.last_dir = cfg.get("last_dir", self.last_dir)
                    self.default_download_dir = cfg.get("default_download_dir", self.default_download_dir)
                    self.default_language = cfg.get("default_language", self.default_language)
        except Exception:
            pass

    def save_config(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "last_dir": self.last_dir,
                    "default_download_dir": self.default_download_dir,
                    "default_language": self.default_language
                }, f, indent=2)
        except Exception:
            pass

    def setup_gui(self):
        pad = 10
        main = ttk.Frame(self.root, padding=pad)
        main.pack(fill='both', expand=True)

        header = ttk.Label(main, text="Auto Subtitle Downloader", font=("Segoe UI", 14, "bold"))
        header.pack(pady=(0, 8))

        # Query area
        qframe = ttk.Frame(main)
        qframe.pack(fill='x', pady=(4, 6))
        ttk.Label(qframe, text="Search query (e.g. 'Attack on Titan season 3 episode 2')").pack(anchor='w')
        self.query_var = tk.StringVar()
        ttk.Entry(qframe, textvariable=self.query_var, width=90).pack(fill='x', pady=(4, 4))

        # Controls
        cframe = ttk.Frame(main)
        cframe.pack(fill='x', pady=(2, 6))

        ttk.Button(cframe, text="Add & Start", command=self.add_query_and_start).pack(side='left')
        ttk.Button(cframe, text="Choose Default Download Folder", command=self.choose_folder).pack(side='left', padx=6)
        ttk.Button(cframe, text="Clear Queue", command=self.clear_queue).pack(side='left', padx=6)
        ttk.Button(cframe, text="Stop After Current", command=self.stop_after_current).pack(side='left', padx=6)

        # Language field
        lang_frame = ttk.Frame(main)
        lang_frame.pack(fill='x', pady=(4, 6))
        ttk.Label(lang_frame, text="Subtitle language (ISO 639-2 code, default: eng)").pack(anchor='w')
        self.lang_var = tk.StringVar(value=self.default_language)
        ttk.Entry(lang_frame, textvariable=self.lang_var, width=10).pack(anchor='w', pady=(4, 0))

        # Treeview showing queue + status
        ttk.Label(main, text="Queue / Job Status:").pack(anchor='w', pady=(6, 0))
        columns = ("query", "status", "message", "saved_file")
        self.tree = ttk.Treeview(main, columns=columns, show="headings", height=8)
        self.tree.heading("query", text="Query")
        self.tree.heading("status", text="Status")
        self.tree.heading("message", text="Message")
        self.tree.heading("saved_file", text="Saved File")
        self.tree.column("query", width=300)
        self.tree.column("status", width=120)
        self.tree.column("message", width=240)
        self.tree.column("saved_file", width=180)
        self.tree.pack(fill='x', pady=(6, 10))

        # Status line and downloads list
        status_frame = ttk.Frame(main)
        status_frame.pack(fill='x', pady=(4, 0))
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(status_frame, textvariable=self.status_var, foreground="blue").pack(anchor='w')

        ttk.Label(main, text=f"Default download folder: {self.default_download_dir}", foreground="gray").pack(anchor='w', pady=(6, 0))
        self.downloads_listbox = tk.Listbox(main, height=4, width=120)
        self.downloads_listbox.pack(fill='x', pady=(6, 0))

    def choose_folder(self):
        folder = filedialog.askdirectory(initialdir=self.default_download_dir)
        if folder:
            self.default_download_dir = folder
            self.save_config()
            self.status_var.set(f"Default download folder set to: {folder}")

    def add_query_and_start(self):
        q = self.query_var.get().strip()
        if not q:
            messagebox.showinfo("Empty query", "Please enter a search query.")
            return
        # Insert into tree and queue
        item = self.tree.insert("", tk.END, values=(q, "Queued", "", ""))
        with self.queue_lock:
            self.queue.append({'query': q, 'item': item})
        self.query_var.set("")
        self.status_var.set("Job added to queue")
        # Auto-start
        if not self.processing:
            self.start_worker_thread()

    def clear_queue(self):
        with self.queue_lock:
            self.queue.clear()
        # Remove only those items whose status is still "Queued" or "Searching"
        for iid in self.tree.get_children():
            vals = self.tree.item(iid, 'values')
            status = vals[1] if len(vals) > 1 else ""
            if status in ("Queued", "Searching"):
                self.tree.delete(iid)
        self.status_var.set("Queue cleared")

    def stop_after_current(self):
        if self.processing:
            self.stop_flag = True
            self.status_var.set("Will stop after the current job finishes")
        else:
            self.status_var.set("Not currently processing")

    def start_worker_thread(self):
        t = threading.Thread(target=self.worker, daemon=True)
        t.start()

    def update_tree_item(self, item_id, status=None, message=None, saved_file=None):
        """Safely update tree row (must be called from main thread via after)"""
        def _update():
            try:
                vals = list(self.tree.item(item_id, 'values'))
                while len(vals) < 4:
                    vals.append("")
                if status is not None:
                    vals[1] = status
                if message is not None:
                    vals[2] = message
                if saved_file is not None:
                    vals[3] = saved_file
                self.tree.item(item_id, values=vals)
            except Exception:
                pass
        self.root.after(1, _update)

    def _list_subs(self, folder):
        """All subtitle files in folder with mtime."""
        out = []
        try:
            for name in os.listdir(folder):
                if name.lower().endswith((".srt", ".ass", ".ssa")):
                    full = os.path.join(folder, name)
                    out.append((os.path.getmtime(full), full))
        except Exception:
            pass
        out.sort(reverse=True)
        return out

    def _snapshot_set(self, folder):
        """Set of existing subtitle file paths at a moment in time."""
        return {p for _, p in self._list_subs(folder)}

    def _recent_after_save(self, before_set, folder, seconds_window=120):
        """
        Return plausible newly-saved files.
        If diff is empty (e.g. overwrite), fallback to 'recent by mtime within window'.
        """
        after_list = self._list_subs(folder)
        after_set = {p for _, p in after_list}
        diff = sorted(after_set - before_set, key=lambda p: os.path.getmtime(p), reverse=True)
        if diff:
            return diff
        # Fallback: take newest files within time window
        now = time.time()
        recent = [p for m, p in after_list if now - m <= seconds_window]
        return recent[:6]

    def _convert_to_srt_if_needed(self, paths):
        """Convert any .ass/.ssa in paths to .srt (deletes originals). Returns list of resulting .srt paths (or original path with note on failure)."""
        srt_paths = []
        try:
            import pysubs2
        except Exception:
            messagebox.showwarning(
                "Missing dependency",
                "To convert ASS/SSA to SRT, please install pysubs2:\n\npip install pysubs2"
            )
            return srt_paths

        for p in paths:
            base, ext = os.path.splitext(p)
            ext_lower = ext.lower()
            if ext_lower == ".srt":
                srt_paths.append(p)
                continue
            if ext_lower in (".ass", ".ssa"):
                try:
                    subs = pysubs2.load(p, encoding="utf-8")
                    srt_out = base + ".srt"
                    subs.save(srt_out, format_="srt")
                    try:
                        os.remove(p)
                    except Exception:
                        pass
                    srt_paths.append(srt_out)
                except Exception as e:
                    srt_paths.append(p + f" (conversion failed: {e})")
        return srt_paths

    def worker(self):
        if not SUBLIMINAL_AVAILABLE:
            self.status_var.set("subliminal not available; cannot search/download subtitles.")
            return

        self.processing = True
        self.stop_flag = False

        while True:
            with self.queue_lock:
                if not self.queue:
                    break
                job = self.queue.pop(0)
            query = job['query']
            item = job['item']

            # Update UI -> Searching
            self.update_tree_item(item, status="Searching", message="")
            self.status_var.set(f"Searching for: {query}")

            # Build a video name to help the parser
            fake_filename = query + " .mkv"
            try:
                video = Video.fromname(fake_filename)
            except Exception:
                try:
                    video = Video.fromname(query + ".mkv")
                except Exception:
                    video = None

            languages = {Language(self.lang_var.get().strip() or self.default_language)}
            download_dir = self.default_download_dir
            os.makedirs(download_dir, exist_ok=True)

            try:
                self.update_tree_item(item, status="Searching", message="Querying providers (SRT preferred)...")
                results = download_best_subtitles([video] if video is not None else [query],
                                                  languages, providers=None, hearing_impaired=False)

                # Filter to SRT / SubRip
                results_srt = {}
                for v, subs in results.items():
                    srt_subs = [s for s in subs if getattr(s, "format", "").lower() in ("srt", "subrip")]
                    if srt_subs:
                        results_srt[v] = set(srt_subs)  # subliminal expects a set

                if results_srt:
                    before = self._snapshot_set(download_dir)
                    self.update_tree_item(item, status="Downloading", message="Saving SRT subtitle(s)...")
                    # Save the first video’s SRTs
                    v0 = next(iter(results_srt.keys()))
                    save_subtitles(v0, results_srt[v0], directory=download_dir)
                    # give filesystem a tick just in case
                    time.sleep(0.2)
                    new_files = self._recent_after_save(before, download_dir)

                    if new_files:
                        saved_display = new_files[0]
                        self.update_tree_item(item, status="Downloaded", message="Downloaded SRT", saved_file=saved_display)
                        self.downloads_listbox.insert(tk.END, saved_display)
                        self.status_var.set(f"Downloaded SRT subtitle for: {query}")
                    else:
                        # Fallback to a broader scan so we don't mislead the user
                        recent = [p for _, p in self._list_subs(download_dir)][:1]
                        if recent:
                            saved_display = recent[0]
                            self.update_tree_item(item, status="Downloaded", message="Downloaded (detected by fallback)", saved_file=saved_display)
                            self.downloads_listbox.insert(tk.END, saved_display)
                            self.status_var.set(f"Downloaded SRT (fallback detect) for: {query}")
                        else:
                            self.update_tree_item(item, status="Error", message="Saved, but could not detect file", saved_file="")
                            self.status_var.set(f"Saved but could not detect file for: {query}")

                else:
                    # No SRT available -> show message, then download best available and convert
                    self.update_tree_item(item, status="Searching", message="SRT not found. Downloading best available...")
                    self.status_var.set(f"SRT not found for: {query}. Downloading best available...")

                    # If results was empty, re-query once (sometimes providers need a second try)
                    if not any(results.values()):
                        results = download_best_subtitles([video] if video is not None else [query],
                                                          languages, providers=None, hearing_impaired=False)

                    # Save what we have
                    saved_any = False
                    before = self._snapshot_set(download_dir)
                    for v, subs in results.items():
                        if subs:
                            self.update_tree_item(item, status="Downloading", message="Saving subtitle(s)...")
                            save_subtitles(v, set(subs), directory=download_dir)
                            saved_any = True
                            break

                    if not saved_any:
                        self.update_tree_item(item, status="Not Found", message="No matching subtitles found", saved_file="")
                        self.status_var.set(f"No subtitles found for: {query}")
                    else:
                        time.sleep(0.2)
                        new_files = self._recent_after_save(before, download_dir)
                        if not new_files:
                            # last-chance fallback
                            new_files = [p for _, p in self._list_subs(download_dir)][:3]

                        if not new_files:
                            self.update_tree_item(item, status="Error", message="Saved, but files not detected", saved_file="")
                            self.status_var.set(f"Saved but files not detected for: {query}")
                        else:
                            # Convert any ASS/SSA to SRT and delete originals
                            self.update_tree_item(item, status="Converting", message="Converting to SRT...")
                            converted = self._convert_to_srt_if_needed(new_files)
                            # Prefer newest SRT
                            srt_candidates = [p for p in converted if isinstance(p, str) and p.lower().endswith(".srt")]
                            saved_display = srt_candidates[0] if srt_candidates else (converted[0] if converted else "")

                            if saved_display:
                                if saved_display.lower().endswith(".srt"):
                                    self.update_tree_item(item, status="Downloaded", message="SRT not found; converted from other format", saved_file=saved_display)
                                    self.downloads_listbox.insert(tk.END, saved_display)
                                    self.status_var.set(f"Downloaded and converted to SRT for: {query}")
                                else:
                                    self.update_tree_item(item, status="Partial", message="Conversion failed; original kept", saved_file=saved_display)
                                    self.downloads_listbox.insert(tk.END, saved_display)
                                    self.status_var.set(f"Downloaded but conversion failed for: {query}")
                            else:
                                self.update_tree_item(item, status="Error", message="Conversion failed; no file", saved_file="")
                                self.status_var.set(f"Conversion failed for: {query}")

            except Exception as ex:
                short_err = str(ex)
                if len(short_err) > 200:
                    short_err = short_err[:197] + "..."
                self.update_tree_item(item, status="Error", message=short_err, saved_file="")
                self.status_var.set(f"Error searching/downloading for: {query}")

            if self.stop_flag:
                break

        self.processing = False
        self.stop_flag = False
        self.status_var.set("Idle - queue finished")

    # (kept for compatibility if you use it elsewhere)
    def _find_recent_subs(self, folder, ext_list=(".srt", ".ass", ".ssa")):
        try:
            files = []
            for name in os.listdir(folder):
                if name.lower().endswith(ext_list):
                    full = os.path.join(folder, name)
                    files.append((os.path.getmtime(full), full))
            files.sort(reverse=True)
            return [f for _, f in files[:6]]
        except Exception:
            return []


def main():
    root = tk.Tk()
    app = SubtitleDownloaderApp(root)
    # center window
    w = 840; h = 420
    x = (root.winfo_screenwidth() // 2) - (w // 2)
    y = (root.winfo_screenheight() // 2) - (h // 2)
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.mainloop()


if __name__ == "__main__":
    main()
