import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import date

from tksheet import Sheet

from logic.data_loader import (
    EXCLUDED_STATUSES,
    detail,
    load_data,
    load_full,
    df_to_rows,
)

HEADERS = ["LP No.", "Status", "Created", "Days in System"]


def show_detail(parent: tk.Tk, original_idx: int):
    if not detail["ready"]:
        messagebox.showinfo(
            "Loading", "Full detail data is still loading — please try again in a moment.",
            parent=parent,
        )
        return

    if original_idx >= len(detail["rows"]):
        return

    row = detail["rows"][original_idx]

    top = tk.Toplevel(parent)
    top.title("Package Detail")
    top.geometry("680x520")
    top.resizable(True, True)

    hdr = tk.Frame(top, bg="#2b2d42", pady=8)
    hdr.pack(fill="x")
    lp_val = next(
        (v for k, v in row.items() if k == "LP No." or "lp no" in k.lower()),
        str(original_idx),
    )
    tk.Label(hdr, text=f"Package Detail — {lp_val}",
             font=("Segoe UI", 13, "bold"), bg="#2b2d42", fg="white").pack(side="left", padx=16)
    tk.Button(hdr, text="Close", font=("Segoe UI", 9, "bold"),
              bg="#c0392b", fg="white", relief="flat", padx=10,
              command=top.destroy).pack(side="right", padx=12)

    frame = tk.Frame(top)
    frame.pack(fill="both", expand=True, padx=10, pady=10)

    vsb = ttk.Scrollbar(frame, orient="vertical")
    hsb = ttk.Scrollbar(frame, orient="horizontal")

    tree = ttk.Treeview(frame, columns=("field", "value"), show="headings",
                        yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    tree.heading("field", text="Field")
    tree.heading("value", text="Value")
    tree.column("field", width=240, stretch=True)
    tree.column("value", width=380, stretch=True)

    vsb.config(command=tree.yview)
    hsb.config(command=tree.xview)
    vsb.pack(side="right",  fill="y")
    hsb.pack(side="bottom", fill="x")
    tree.pack(fill="both", expand=True)

    for k, v in row.items():
        display = "—" if v in ("nan", "NaT", "<NA>", "") else v
        tree.insert("", "end", values=(k, display))

    top.grab_set()


def build_window(source_file: str):
    root = tk.Tk()
    root.title("Package Days in System")
    root.geometry("900x620")
    root.resizable(True, True)

    _df:         list = []
    _current_df: list = []

    # ── header ────────────────────────────────────────────────────────────────
    hdr = tk.Frame(root, bg="#2b2d42", pady=8)
    hdr.pack(fill="x")

    tk.Label(hdr, text="Package Days in System",
             font=("Segoe UI", 16, "bold"), bg="#2b2d42", fg="white").pack(side="left", padx=16)

    tk.Button(hdr, text="Exit", font=("Segoe UI", 10, "bold"),
              bg="#c0392b", fg="white", relief="flat", padx=12, pady=2,
              cursor="hand2", command=root.destroy).pack(side="right", padx=16)

    tk.Label(hdr, text=f"Source: {os.path.basename(source_file)}",
             font=("Segoe UI", 9), bg="#2b2d42", fg="#adb5bd").pack(side="right", padx=4)

    # ── summary bar ───────────────────────────────────────────────────────────
    summary_frame = tk.Frame(root, bg="#edf2fb", pady=6)
    summary_frame.pack(fill="x")

    summary_vars = {}
    for key, label in [("In transit", "In transit"), ("Avg days", "Avg days"), ("Max days", "Max days")]:
        box = tk.Frame(summary_frame, bg="#edf2fb", padx=16)
        box.pack(side="left")
        var = tk.StringVar(value="…")
        summary_vars[key] = var
        tk.Label(box, textvariable=var, font=("Segoe UI", 13, "bold"),
                 bg="#edf2fb", fg="#2b2d42").pack()
        tk.Label(box, text=label, font=("Segoe UI", 8),
                 bg="#edf2fb", fg="#6c757d").pack()

    # ── search bar ────────────────────────────────────────────────────────────
    search_frame = tk.Frame(root, pady=6, padx=10)
    search_frame.pack(fill="x")

    tk.Label(search_frame, text="Search LP No. or status:").pack(side="left")
    search_var   = tk.StringVar()
    search_entry = tk.Entry(search_frame, textvariable=search_var, width=40, state="disabled")
    search_entry.pack(side="left", padx=6)

    tk.Label(search_frame, text="Days in system:", font=("Segoe UI", 9)).pack(side="left", padx=(16, 4))
    _sort_order: list = ["desc"]   # mutable cell so closures can write to it

    def _sort_btn_style(btn, active: bool):
        btn.config(relief="sunken" if active else "raised",
                   bg="#2b2d42" if active else "#e0e0e0",
                   fg="white"   if active else "#333")

    btn_desc = tk.Button(search_frame, text="↓ Desc", font=("Segoe UI", 9),
                         padx=6, cursor="hand2")
    btn_asc  = tk.Button(search_frame, text="↑ Asc",  font=("Segoe UI", 9),
                         padx=6, cursor="hand2")
    btn_desc.pack(side="left", padx=2)
    btn_asc.pack(side="left",  padx=2)

    def _apply_sort(order: str):
        _sort_order[0] = order
        _sort_btn_style(btn_desc, order == "desc")
        _sort_btn_style(btn_asc,  order == "asc")
        if _df:
            populate(current_subset())

    btn_desc.config(command=lambda: _apply_sort("desc"))
    btn_asc.config( command=lambda: _apply_sort("asc"))
    _sort_btn_style(btn_desc, True)
    _sort_btn_style(btn_asc,  False)

    tk.Label(search_frame, text="  Double-click a row for full details",
             font=("Segoe UI", 8), fg="#6c757d").pack(side="left", padx=(12, 0))

    # ── tksheet table ─────────────────────────────────────────────────────────
    table_frame = tk.Frame(root)
    table_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    sheet = Sheet(
        table_frame,
        headers=HEADERS,
        data=[],
        header_font=("Segoe UI", 10, "bold"),
        font=("Segoe UI", 10, "normal"),
        row_height=24,
        show_row_index=False,
    )
    sheet.enable_bindings(
        "single_select", "column_select", "row_select",
        "column_width_resize", "column_move",
        "arrowkeys", "right_click_popup_menu",
        "rc_select", "copy",
    )
    sheet.pack(fill="both", expand=True)

    # ── column auto-stretch ───────────────────────────────────────────────────
    def _stretch_cols(event=None):
        w = table_frame.winfo_width() - 4
        if w > 100:
            sheet.set_all_column_widths(max(80, w // len(HEADERS)))

    table_frame.bind("<Configure>", _stretch_cols)

    # ── loading overlay ───────────────────────────────────────────────────────
    overlay = tk.Frame(table_frame, bg="#f0f0f0")
    overlay.place(relx=0, rely=0, relwidth=1, relheight=1)

    tk.Label(overlay, text="Loading data…",
             font=("Segoe UI", 13), bg="#f0f0f0", fg="#555").place(
        relx=0.5, rely=0.45, anchor="center")

    dots_var = tk.StringVar(value="")
    tk.Label(overlay, textvariable=dots_var,
             font=("Segoe UI", 10), bg="#f0f0f0", fg="#aaa").place(
        relx=0.5, rely=0.53, anchor="center")

    def animate_dots(n=0):
        if overlay.winfo_exists() and overlay.winfo_ismapped():
            dots_var.set("● " * (n % 4))
            root.after(400, animate_dots, n + 1)

    animate_dots()

    # ── status bar ────────────────────────────────────────────────────────────
    status_var = tk.StringVar(value=f"As of {date.today()}  •  Red = ≥ 7 days in system")
    tk.Label(root, textvariable=status_var, font=("Segoe UI", 8),
             fg="#6c757d", anchor="w").pack(fill="x", padx=10, pady=(0, 4))

    # ── populate & highlight ──────────────────────────────────────────────────
    def populate(df):
        if _current_df:
            _current_df[0] = df
        else:
            _current_df.append(df)
        rows = df_to_rows(df)
        high = [i for i, r in enumerate(rows) if r[3] >= 7]
        sheet.set_sheet_data(rows, reset_col_positions=False)
        sheet.dehighlight_all(redraw=False)
        if high:
            sheet.highlight_rows(high, bg="#ffe0e0", fg="#000000", redraw=False)
        sheet.redraw()
        _stretch_cols()

    # ── search ────────────────────────────────────────────────────────────────
    def current_subset():
        df = _df[0]
        q  = search_var.get().strip().lower()
        if q:
            mask = (
                df["lp"].astype(str).str.lower().str.contains(q, na=False) |
                df["status"].astype(str).str.lower().str.contains(q, na=False)
            )
            df = df[mask]
        return df.sort_values("days_in_system", ascending=(_sort_order[0] == "asc"))

    def on_search(*_):
        if _df:
            populate(current_subset())

    search_var.trace_add("write", on_search)

    # ── double-click → detail popup ───────────────────────────────────────────
    def on_double_click(event):
        if not _current_df:
            return
        sel = sheet.get_currently_selected()
        if not sel:
            return
        row_pos      = sel.row
        displayed_df = _current_df[0]
        if row_pos >= len(displayed_df):
            return
        original_idx = int(displayed_df.index[row_pos])
        show_detail(root, original_idx)

    sheet.bind("<Double-Button-1>", on_double_click)

    # ── background loader ─────────────────────────────────────────────────────
    result_q: queue.Queue = queue.Queue()

    def worker():
        try:
            result_q.put(("ok", load_data(source_file)))
        except Exception as exc:
            result_q.put(("err", exc))

    def poll_result():
        try:
            result = result_q.get_nowait()
        except queue.Empty:
            root.after(100, poll_result)
            return

        if result[0] == "err":
            overlay.place_forget()
            messagebox.showerror("Error loading data", str(result[1]))
            return

        _, df = result[0], result[1]
        _df.append(df)

        summary_vars["In transit"].set(f"{len(df):,}")
        summary_vars["Avg days"].set(f"{df['days_in_system'].mean():.1f}")
        summary_vars["Max days"].set(str(int(df["days_in_system"].max())))
        status_var.set(
            f"{len(df):,} packages in transit  •  As of {date.today()}  •  Red = ≥ 7 days in system"
        )

        search_entry.config(state="normal")
        overlay.place_forget()
        _current_df.append(df)
        populate(current_subset())

    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=load_full, args=(source_file,), daemon=True).start()
    root.after(100, poll_result)

    root.mainloop()
