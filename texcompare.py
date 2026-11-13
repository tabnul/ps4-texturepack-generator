"""Compare original and upscaled textures of a pack build, and mark them.

    texcompare.py <game folder> <pack work folder>      (e.g. ...\\tlg\\v2.work)

Left: the texture list (filter box, mark filter). Right: original and upscaled at the same
zoom and position. Mouse wheel zooms, drag pans, Space shows one big view and flips original/upscaled,
S goes back to side by side, F fits, Up/Down moves through the list.
Marks: 1 = good, 2 = wrong (looks broken), 3 = keep original (do not touch), 0 = clear.
Marks and notes are saved at once to marks.csv in the work folder.
"""
import csv
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from PIL import Image, ImageTk

from pack_build import decode
from pack_scan import Archive

MARKS = {'1': 'good', '2': 'wrong', '3': 'keep original', '0': ''}
COLOURS = {'good': '#3a7d44', 'wrong': '#b03030', 'keep original': '#b08020', '': ''}


def checker(size, cell=16):
    w, h = size
    tile = Image.new('RGB', (cell * 2, cell * 2), (90, 90, 90))
    tile.paste((60, 60, 60), (0, 0, cell, cell))
    tile.paste((60, 60, 60), (cell, cell, cell * 2, cell * 2))
    bg = Image.new('RGB', (w, h))
    for y in range(0, h, cell * 2):
        for x in range(0, w, cell * 2):
            bg.paste(tile, (x, y))
    return bg


class App:
    def __init__(self, root, game, work):
        self.root, self.game, self.work = root, Path(game), Path(work)
        self.marks_file = self.work / 'marks.csv'
        self.marks = {}
        if self.marks_file.exists():
            for r in csv.DictReader(open(self.marks_file, encoding='utf-8')):
                self.marks[r['path']] = (r['mark'], r['note'])
        png = self.work / 'png'
        self.rows = []
        for r in csv.DictReader(open(self.work / 'manifest.csv', encoding='utf-8')):
            if r['decision'] == 'pack' and (png / (r['path'][:-4] + '.png')).exists():
                self.rows.append(r)
        self.archives, self.cache = {}, {}
        self.cur = None
        self.zoom, self.cx, self.cy = 1.0, 0.5, 0.5   # zoom in original pixels, view centre (0..1)
        self.single = None                             # None = side by side, 'o' / 'u' = one view
        self.alpha = tk.BooleanVar(value=True)
        self.smooth = tk.BooleanVar(value=False)
        self.build_ui()
        self.refill()

    # ---------- UI ----------
    def build_ui(self):
        r = self.root
        r.title('Texture compare')
        r.geometry('1700x950')
        left = ttk.Frame(r)
        left.pack(side='left', fill='y')
        self.filter = tk.StringVar()
        self.filter.trace_add('write', lambda *a: self.refill())
        ttk.Entry(left, textvariable=self.filter, width=50).pack(fill='x', padx=4, pady=4)
        self.show = tk.StringVar(value='all')
        f = ttk.Frame(left)
        f.pack(fill='x')
        for v in ('all', 'unmarked', 'good', 'wrong', 'keep original'):
            ttk.Radiobutton(f, text=v, value=v, variable=self.show, command=self.refill).pack(side='left')
        self.count = ttk.Label(left)
        self.count.pack(fill='x', padx=4)
        self.list = tk.Listbox(left, width=60, activestyle='none', exportselection=False)
        sb = ttk.Scrollbar(left, command=self.list.yview)
        self.list.config(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        self.list.pack(fill='both', expand=True)
        self.list.bind('<<ListboxSelect>>', lambda e: self.select())

        right = ttk.Frame(r)
        right.pack(side='left', fill='both', expand=True)
        bar = ttk.Frame(right)
        bar.pack(fill='x')
        self.info = ttk.Label(bar, font=('Segoe UI', 10, 'bold'))
        self.info.pack(side='left', padx=6)
        ttk.Checkbutton(bar, text='alpha (checker)', variable=self.alpha, command=self.draw).pack(side='right')
        ttk.Checkbutton(bar, text='smooth original', variable=self.smooth, command=self.draw).pack(side='right')
        mb = ttk.Frame(right)
        mb.pack(fill='x')
        for k, m in MARKS.items():
            ttk.Button(mb, text=f'{k}: {m or "clear"}', command=lambda k=k: self.mark(k)).pack(side='left', padx=2)
        ttk.Label(mb, text='  note:').pack(side='left')
        self.note = tk.StringVar()
        e = ttk.Entry(mb, textvariable=self.note, width=60)
        e.pack(side='left')
        e.bind('<Return>', lambda ev: (self.save_note(), self.root.focus()))
        ttk.Label(mb, text='  wheel zoom, drag pan, Space flip one view, S side by side, Up/Down next, F fit').pack(side='left')
        self.canvas = tk.Canvas(right, bg='#202024', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', lambda e: self.draw())
        self.canvas.bind('<MouseWheel>', self.wheel)
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<B1-Motion>', self.drag)
        for k in MARKS:
            r.bind(k, lambda e, k=k: None if self.typing(e) else self.mark(k))
        r.bind('<space>', lambda e: None if self.typing(e) else self.flip())
        r.bind('f', lambda e: None if self.typing(e) else self.fit())
        r.bind('s', lambda e: None if self.typing(e) else self.side_by_side())
        r.bind('<Down>', lambda e: self.step(1))
        r.bind('<Up>', lambda e: self.step(-1))

    def typing(self, e):
        return isinstance(e.widget, (tk.Entry, ttk.Entry))

    def refill(self):
        text, show = self.filter.get().lower(), self.show.get()
        self.shown = []
        for r in self.rows:
            m = self.marks.get(r['path'], ('', ''))[0]
            if text and text not in r['path'].lower():
                continue
            if show == 'unmarked' and m or show not in ('all', 'unmarked') and m != show:
                continue
            self.shown.append(r)
        self.list.delete(0, 'end')
        for i, r in enumerate(self.shown):
            m = self.marks.get(r['path'], ('', ''))[0]
            self.list.insert('end', f"{r['path'][14:] if r['path'].startswith('game/textures/') else r['path']}"
                                    f"   {r['width']}x{r['height']} {r['format']}" + (f'   [{m}]' if m else ''))
            if m:
                self.list.itemconfig(i, fg=COLOURS[m])
        done = sum(1 for r in self.rows if self.marks.get(r['path'], ('',))[0])
        self.count.config(text=f'{len(self.shown)} shown, {len(self.rows)} textures, {done} marked')

    def step(self, d):
        if not self.shown:
            return
        sel = self.list.curselection()
        i = max(0, min(len(self.shown) - 1, (sel[0] + d) if sel else 0))
        self.list.selection_clear(0, 'end')
        self.list.selection_set(i)
        self.list.see(i)
        self.select()

    # ---------- images ----------
    def load(self, r):
        p = r['path']
        if p not in self.cache:
            a = self.archives.get(r['archive'])
            if a is None:
                a = self.archives[r['archive']] = Archive(self.game / f"{r['archive']}.psarc")
            orig = decode(a.read(a.index[p])).convert('RGBA')
            up = Image.open(self.work / 'png' / (p[:-4] + '.png')).convert('RGBA')
            if len(self.cache) > 6:
                self.cache.pop(next(iter(self.cache)))
            self.cache[p] = (orig, up)
        return self.cache[p]

    def select(self):
        sel = self.list.curselection()
        if not sel:
            return
        self.save_note()
        self.cur = self.shown[sel[0]]
        self.note.set(self.marks.get(self.cur['path'], ('', ''))[1])
        self.root.config(cursor='watch')
        self.root.update_idletasks()
        try:
            self.load(self.cur)
        except Exception as e:
            self.info.config(text=f"{self.cur['path']}: cannot read ({e})")
            self.cur = None
            return
        finally:
            self.root.config(cursor='')
        self.fit()

    def fit(self):
        if not self.cur:
            return
        orig, _ = self.cache[self.cur['path']]
        w, h = self.view_size()
        self.zoom = min(w / orig.width, h / orig.height)
        self.cx = self.cy = 0.5
        self.draw()

    def view_size(self):
        W, H = max(self.canvas.winfo_width(), 50), max(self.canvas.winfo_height(), 50)
        return (W, H) if self.single else ((W - 10) // 2, H)

    def render(self, img, base_w, base_h, w, h, smooth):
        """The part of `img` in view, scaled to w x h. Coordinates are in original pixels."""
        sx, sy = img.width / base_w, img.height / base_h
        vw, vh = w / self.zoom, h / self.zoom
        x0, y0 = self.cx * base_w - vw / 2, self.cy * base_h - vh / 2
        # visible part of the texture (original pixels), and where it lands on screen
        ax0, ay0 = max(0.0, x0), max(0.0, y0)
        ax1, ay1 = min(float(base_w), x0 + vw), min(float(base_h), y0 + vh)
        bg = checker((w, h)) if self.alpha.get() else Image.new('RGB', (w, h), (0, 0, 0))
        dx0, dy0 = round((ax0 - x0) * self.zoom), round((ay0 - y0) * self.zoom)
        dw, dh = round((ax1 - ax0) * self.zoom), round((ay1 - ay0) * self.zoom)
        if dw < 1 or dh < 1:
            return bg
        if self.alpha.get():
            canvas_bg = bg
        else:
            canvas_bg = Image.new('RGB', (w, h), (32, 32, 36))
        out = img.resize((dw, dh), Image.LANCZOS if smooth else Image.NEAREST,
                         box=(ax0 * sx, ay0 * sy, ax1 * sx, ay1 * sy))
        if self.alpha.get():
            canvas_bg.paste(out, (dx0, dy0), out)
        else:
            canvas_bg.paste(out.convert('RGB'), (dx0, dy0))
        return canvas_bg

    def draw(self):
        c = self.canvas
        c.delete('all')
        if not self.cur:
            return
        orig, up = self.cache[self.cur['path']]
        w, h = self.view_size()
        m = self.marks.get(self.cur['path'], ('', ''))[0]
        self.info.config(text=f"{self.cur['path']}   original {orig.width}x{orig.height} -> upscaled "
                              f"{up.width}x{up.height}   zoom {self.zoom:.2f}x" + (f'   [{m}]' if m else ''),
                         foreground=COLOURS[m] or 'black')
        smooth_o = self.smooth.get() or self.zoom < 1
        parts = []
        if self.single in (None, 'o'):
            parts.append(('ORIGINAL', self.render(orig, orig.width, orig.height, w, h, smooth_o)))
        if self.single in (None, 'u'):
            parts.append(('UPSCALED', self.render(up, orig.width, orig.height, w, h, True)))
        self.photos = []
        for i, (label, im) in enumerate(parts):
            ph = ImageTk.PhotoImage(im)
            self.photos.append(ph)
            x = i * (w + 10)
            c.create_image(x, 0, image=ph, anchor='nw')
            c.create_rectangle(x, 0, x + 110, 22, fill='#000000', outline='')
            c.create_text(x + 6, 4, text=label, fill='white', anchor='nw', font=('Segoe UI', 10, 'bold'))

    # ---------- input ----------
    def wheel(self, e):
        if not self.cur:
            return
        f = 1.25 if e.delta > 0 else 0.8
        self.zoom = max(0.01, min(64, self.zoom * f))
        self.draw()

    def press(self, e):
        self.last = (e.x, e.y)

    def drag(self, e):
        if not self.cur:
            return
        orig, _ = self.cache[self.cur['path']]
        dx, dy = e.x - self.last[0], e.y - self.last[1]
        self.last = (e.x, e.y)
        self.cx -= dx / self.zoom / orig.width
        self.cy -= dy / self.zoom / orig.height
        self.draw()

    def flip(self):
        self.single = 'u' if self.single == 'o' else 'o'
        self.draw()

    def side_by_side(self):
        self.single = None
        self.draw()

    # ---------- marks ----------
    def mark(self, k):
        if not self.cur:
            return
        self.marks[self.cur['path']] = (MARKS[k], self.note.get().strip())
        self.save()
        self.refill_keep()

    def save_note(self):
        if self.cur:
            m, n = self.marks.get(self.cur['path'], ('', ''))
            if n != self.note.get().strip():
                self.marks[self.cur['path']] = (m, self.note.get().strip())
                self.save()

    def save(self):
        tmp = self.marks_file.with_suffix('.tmp')
        with open(tmp, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['path', 'mark', 'note'])
            for p, (m, n) in sorted(self.marks.items()):
                if m or n:
                    w.writerow([p, m, n])
        tmp.replace(self.marks_file)

    def refill_keep(self):
        sel = self.list.curselection()
        top = self.list.yview()[0]
        self.refill()
        if sel and sel[0] < len(self.shown):
            self.list.selection_set(sel[0])
        self.list.yview_moveto(top)
        self.draw()


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    root = tk.Tk()
    App(root, sys.argv[1], sys.argv[2])
    root.mainloop()


if __name__ == '__main__':
    main()
