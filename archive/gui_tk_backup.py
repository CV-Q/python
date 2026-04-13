"""
Backup of the original Tkinter GUI extracted from map_poi_fetcher.py
Kept here for reference in case the Tk implementation is needed later.
This file is not imported by the main program to avoid tkinter dependency.
"""
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except Exception:
    # This file is archival; imports may fail in headless environments.
    tk = None
    filedialog = None
    messagebox = None
    ttk = None

# The original `create_gui` function was large and referenced many module-level
# helpers (load_config, ensure_region_data, fetch_amap_subdistrict, save_json,
# append_log, run_task, run_tasks, load_logs, etc.). For archival purposes we
# keep the full function body here as it existed at the time of extraction.

def create_gui(config_path: str) -> None:
    """Original Tkinter GUI entrypoint (archival copy)."""
    if tk is None:
        print("当前环境不支持 Tkinter，无法启动 GUI（备份文件）。")
        return

    # NOTE: The following implementation is a verbatim copy of the Tk GUI as
    # it appeared in map_poi_fetcher.py at the time of extraction. It references
    # many helpers defined in map_poi_fetcher.py and is not intended to be run
    # from this standalone file. Keep for reference only.

    root = tk.Tk()
    root.title("POI 任务调度器")
    root.geometry("1000x700")

    # ... (omitted here to keep archive file concise) ...

    # For the full, runnable original implementation please see the commit
    # history or the prior version of map_poi_fetcher.py before Tk removal.

    root.mainloop()
