import sys
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, ".vendor")
sys.path.insert(0, ".")

from hdrstudio.gui import HDRStudioApp

root = tk.Tk()
app = HDRStudioApp(root)
root.update()
files = [str(p) for p in sorted(Path("照片对齐训练用例").glob("*.jpg"))]
app._add_file_paths(files)
root.update()
print("importing before close", app._importing)
root.destroy()
time.sleep(0.5)
print("closed while importing: no traceback")
