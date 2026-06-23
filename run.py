import os
import sys
import tkinter as tk
from tkinter import messagebox

from logic.data_loader import latest_data_file
from logic.ui import build_window


def main():
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "data")

    try:
        path = latest_data_file(data_dir)
        build_window(path)
    except Exception as exc:
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Error", str(exc))
            root.destroy()
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
