#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import sqlite3
import tempfile
import tkinter as tk
import webbrowser
from datetime import date, datetime
from html import escape as esc
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

DB_PATH = Path(__file__).with_name("apa.db")

LUNI = ["Ianuarie", "Februarie", "Martie", "Aprilie", "Mai", "Iunie",
        "Iulie", "August", "Septembrie", "Octombrie", "Noiembrie", "Decembrie"]

CULOARE_PORTOCALIU = "#f28c28"
CULOARE_VERDE = "#1faa4b"
CULOARE_ROSU = "#e0202a"


# ----------------------------------------------------------------------------
#
# ----------------------------------------------------------------------------
def citeste_numar(text):
    """Citește un număr pozitiv; acceptă și virgula ca separator zecimal."""
    valoare = float(str(text).strip().replace(",", "."))
    if valoare != valoare or valoare < 0 or valoare == float("inf"):
        raise ValueError("număr invalid")
    return valoare


def fmt_num(x):
    """5.0 -> '5', 5.5 -> '5.5', 5.25 -> '5.25'"""
    return f"{x:.2f}".rstrip("0").rstrip(".")


def fmt_lei(x):
    return f"{x:.2f} lei"


def eticheta_luna(luna):
    """'2026-02' -> 'Februarie 2026'"""
    an, luna_nr = luna.split("-")
    return f"{LUNI[int(luna_nr) - 1]} {an}"


# ----------------------------------------------------------------------------
# Baza de date
# ----------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS setari (
    cheie   TEXT PRIMARY KEY,
    valoare TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS utilizatori (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    nume   TEXT NOT NULL,
    cnp    TEXT NOT NULL UNIQUE,
    adresa TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS consumuri (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    utilizator_id INTEGER NOT NULL REFERENCES utilizatori(id) ON DELETE CASCADE,
    luna          TEXT NOT NULL,          -- format AAAA-LL
    index_val     REAL NOT NULL,          -- m³ consumați în luna respectivă
    tarif         REAL NOT NULL,          -- lei/m³ la momentul introducerii
    UNIQUE (utilizator_id, luna)
);
CREATE TABLE IF NOT EXISTS plati (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    utilizator_id INTEGER NOT NULL REFERENCES utilizatori(id) ON DELETE CASCADE,
    luna          TEXT NOT NULL,
    suma          REAL NOT NULL,
    data          TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""


class Baza:
    def __init__(self, cale):
        self.con = sqlite3.connect(str(cale))
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys = ON")
        self.con.executescript(SCHEMA)
        self.con.execute("INSERT OR IGNORE INTO setari VALUES ('pret_m3', '5')")
        self.con.execute("INSERT OR IGNORE INTO setari VALUES ('index_retea', '0')")
        self.con.commit()

    # --- setări -------------------------------------------------------------
    def _get(self, cheie):
        return float(self.con.execute(
            "SELECT valoare FROM setari WHERE cheie = ?", (cheie,)).fetchone()[0])

    def _set(self, cheie, valoare):
        self.con.execute("UPDATE setari SET valoare = ? WHERE cheie = ?",
                         (str(valoare), cheie))
        self.con.commit()

    def pret(self):
        return self._get("pret_m3")

    def set_pret(self, valoare):
        self._set("pret_m3", valoare)

    def index_retea(self):
        return self._get("index_retea")

    def set_index_retea(self, valoare):
        self._set("index_retea", valoare)

    # --- utilizatori --------------------------------------------------------
    def utilizatori(self, filtru=""):
        like = f"%{filtru.strip()}%"
        return self.con.execute(
            """SELECT u.id, u.nume, u.cnp, u.adresa,
                      COALESCE(SUM(c.index_val), 0) AS index_total
               FROM utilizatori u
               LEFT JOIN consumuri c ON c.utilizator_id = u.id
               WHERE u.nume LIKE ? OR u.cnp LIKE ? OR u.adresa LIKE ?
               GROUP BY u.id ORDER BY u.id""", (like, like, like)).fetchall()

    def utilizator(self, uid):
        return self.con.execute(
            "SELECT * FROM utilizatori WHERE id = ?", (uid,)).fetchone()

    def adauga_utilizator(self, nume, cnp, adresa):
        self.con.execute(
            "INSERT INTO utilizatori (nume, cnp, adresa) VALUES (?, ?, ?)",
            (nume, cnp, adresa))
        self.con.commit()

    def modifica_utilizator(self, uid, nume, cnp, adresa):
        self.con.execute(
            "UPDATE utilizatori SET nume = ?, cnp = ?, adresa = ? WHERE id = ?",
            (nume, cnp, adresa, uid))
        self.con.commit()

    def sterge_utilizator(self, uid):
        self.con.execute("DELETE FROM utilizatori WHERE id = ?", (uid,))
        self.con.commit()

    # --- consumuri ----------------------------------------------------------
    def consumuri(self, uid):
        return self.con.execute(
            "SELECT luna, index_val, tarif FROM consumuri "
            "WHERE utilizator_id = ? ORDER BY luna", (uid,)).fetchall()

    def exista_consum(self, uid, luna):
        return self.con.execute(
            "SELECT 1 FROM consumuri WHERE utilizator_id = ? AND luna = ?",
            (uid, luna)).fetchone() is not None

    def salveaza_consum(self, uid, luna, index_val, tarif):
        self.con.execute(
            """INSERT INTO consumuri (utilizator_id, luna, index_val, tarif)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (utilizator_id, luna) DO UPDATE
               SET index_val = excluded.index_val, tarif = excluded.tarif""",
            (uid, luna, index_val, tarif))
        self.con.commit()

    def sterge_consum(self, uid, luna):
        """Șterge consumul lunii și plățile aferente."""
        self.con.execute(
            "DELETE FROM consumuri WHERE utilizator_id = ? AND luna = ?", (uid, luna))
        self.con.execute(
            "DELETE FROM plati WHERE utilizator_id = ? AND luna = ?", (uid, luna))
        self.con.commit()

    # --- plăți --------------------------------------------------------------
    def incasat_pe_luni(self, uid):
        rows = self.con.execute(
            "SELECT luna, SUM(suma) FROM plati WHERE utilizator_id = ? GROUP BY luna",
            (uid,)).fetchall()
        return {r[0]: r[1] for r in rows}

    def adauga_plata(self, uid, luna, suma):
        self.con.execute(
            "INSERT INTO plati (utilizator_id, luna, suma) VALUES (?, ?, ?)",
            (uid, luna, suma))
        self.con.commit()

    def plati_detaliat(self, uid):
        return self.con.execute(
            "SELECT luna, suma, data FROM plati WHERE utilizator_id = ? "
            "ORDER BY data, id", (uid,)).fetchall()

    def anuleaza_plati_luna(self, uid, luna):
        self.con.execute(
            "DELETE FROM plati WHERE utilizator_id = ? AND luna = ?", (uid, luna))
        self.con.commit()

    # --- totaluri pentru panoul principal -----------------------------------
    def totaluri(self):
        total_de_incasat = self.con.execute(
            "SELECT COALESCE(SUM(index_val * tarif), 0) FROM consumuri").fetchone()[0]
        total_incasat = self.con.execute(
            "SELECT COALESCE(SUM(suma), 0) FROM plati").fetchone()[0]
        restanti = len({r["id"] for r in self.restante_detaliat()})
        return total_de_incasat, total_incasat, restanti

    def restante_detaliat(self):
        """Câte un rând pentru fiecare lună neachitată (integral sau parțial)."""
        rows = self.con.execute(
            """SELECT u.id, u.nume, u.cnp, u.adresa, c.luna,
                      c.index_val * c.tarif AS sold,
                      COALESCE((SELECT SUM(p.suma) FROM plati p
                                WHERE p.utilizator_id = c.utilizator_id
                                  AND p.luna = c.luna), 0) AS incasat
               FROM consumuri c
               JOIN utilizatori u ON u.id = c.utilizator_id
               ORDER BY u.nume COLLATE NOCASE, u.id, c.luna""").fetchall()
        return [r for r in rows if r["sold"] - r["incasat"] > 0.005]


# ----------------------------------------------------------------------------
# Tipărirea situației de plată (fișă HTML, se deschide în browser și se tipărește)
# ----------------------------------------------------------------------------
def _data_ro(text):
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y")
    except (ValueError, TypeError):
        return str(text)


def genereaza_situatie_html(db, uid):
    u = db.utilizator(uid)
    incasat_luni = db.incasat_pe_luni(uid)

    randuri_luni = []
    total_sold = total_incasat = 0.0
    for r in db.consumuri(uid):
        sold = r["index_val"] * r["tarif"]
        inc = incasat_luni.get(r["luna"], 0.0)
        total_sold += sold
        total_incasat += inc
        randuri_luni.append(
            f"<tr><td>{esc(eticheta_luna(r['luna']))}</td>"
            f"<td class='n'>{fmt_num(r['index_val'])}</td>"
            f"<td class='n'>{fmt_num(r['tarif'])} lei/m³</td>"
            f"<td class='n'>{fmt_lei(sold)}</td>"
            f"<td class='n'>{fmt_lei(inc)}</td>"
            f"<td class='n{' rest' if sold - inc > 0.005 else ''}'>"
            f"{fmt_lei(max(sold - inc, 0))}</td></tr>")
    rest_total = max(total_sold - total_incasat, 0)

    randuri_plati = "".join(
        f"<tr><td>{esc(_data_ro(p['data']))}</td>"
        f"<td>{esc(eticheta_luna(p['luna']))}</td>"
        f"<td class='n'>{fmt_lei(p['suma'])}</td></tr>"
        for p in db.plati_detaliat(uid))
    if not randuri_plati:
        randuri_plati = "<tr><td colspan='3'><i>Nicio plată înregistrată.</i></td></tr>"

    return f"""<!DOCTYPE html>
<html lang="ro"><head><meta charset="utf-8">
<title>Situație de plată – {esc(u['nume'])}</title>
<style>
  @page {{ size: A4; margin: 16mm; }}
  body {{ font-family: Arial, Helvetica, sans-serif; color: #111; font-size: 12pt; }}
  h1 {{ font-size: 20pt; margin: 0 0 4px; }}
  h2 {{ font-size: 13pt; margin: 22px 0 6px; border-bottom: 2px solid #111; padding-bottom: 3px; }}
  .meta {{ color: #444; margin-bottom: 14px; }}
  .client {{ border: 1px solid #999; padding: 8px 12px; margin: 10px 0; line-height: 1.5; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ border: 1px solid #999; padding: 5px 8px; text-align: left; }}
  th {{ background: #eee; }}
  td.n, th.n {{ text-align: right; white-space: nowrap; }}
  td.rest {{ color: #c00; font-weight: bold; }}
  .totaluri {{ margin-top: 14px; margin-left: auto; width: 320px; }}
  .totaluri td {{ border: none; padding: 3px 0; }}
  .totaluri tr.final td {{ border-top: 2px solid #111; font-weight: bold; font-size: 13pt; padding-top: 6px; }}
  .semnaturi {{ display: flex; justify-content: space-between; margin-top: 60px; color: #444; }}
  .semnaturi div {{ border-top: 1px solid #111; width: 200px; text-align: center; padding-top: 4px; }}
  .no-print {{ margin-bottom: 14px; }}
  @media print {{ .no-print {{ display: none; }} }}
</style></head>
<body>
  <div class="no-print"><button onclick="window.print()">🖨 Tipărește</button></div>
  <h1>Situație de plată – consum apă</h1>
  <div class="meta">Întocmită la data de {date.today().strftime('%d.%m.%Y')}</div>
  <div class="client">
    <b>Nume:</b> {esc(u['nume'])}<br>
    <b>CNP:</b> {esc(u['cnp'])}<br>
    <b>Adresă:</b> {esc(u['adresa'])}
  </div>

  <h2>Consum lunar și plăți pe luni</h2>
  <table>
    <tr><th>Luna</th><th class="n">Index (m³)</th><th class="n">Tarif</th>
        <th class="n">Sold</th><th class="n">Încasat</th><th class="n">Rest de plată</th></tr>
    {''.join(randuri_luni) or "<tr><td colspan='6'><i>Niciun consum înregistrat.</i></td></tr>"}
  </table>

  <h2>Plăți înregistrate</h2>
  <table>
    <tr><th>Data plății</th><th>Pentru luna</th><th class="n">Suma</th></tr>
    {randuri_plati}
  </table>

  <table class="totaluri">
    <tr><td>Total de plată:</td><td class="n">{fmt_lei(total_sold)}</td></tr>
    <tr><td>Total încasat:</td><td class="n">{fmt_lei(total_incasat)}</td></tr>
    <tr class="final"><td>REST DE PLATĂ:</td><td class="n">{fmt_lei(rest_total)}</td></tr>
  </table>

  <div class="semnaturi"><div>Semnătură casier</div><div>Semnătură consumator</div></div>
  <script>window.addEventListener('load', function () {{ setTimeout(window.print, 400); }});</script>
</body></html>"""


def tipareste_situatie(db, uid):
    """Generează fișa într-un fișier temporar și o deschide în browser."""
    u = db.utilizator(uid)
    nume_sigur = re.sub(r"[^\w]+", "_", u["nume"], flags=re.UNICODE).strip("_") or "utilizator"
    cale = Path(tempfile.gettempdir()) / f"situatie_{nume_sigur}_{date.today():%Y%m%d}.html"
    cale.write_text(genereaza_situatie_html(db, uid), encoding="utf-8")
    webbrowser.open(cale.as_uri())
    return cale


# ----------------------------------------------------------------------------
# Formular adăugare / modificare utilizator
# ----------------------------------------------------------------------------
class FormUtilizator(tk.Toplevel):
    def __init__(self, parinte, titlu, date=None):
        super().__init__(parinte)
        self.title(titlu)
        self.resizable(False, False)
        self.transient(parinte)
        self.rezultat = None

        self.var_nume = tk.StringVar(value=date["nume"] if date else "")
        self.var_cnp = tk.StringVar(value=date["cnp"] if date else "")
        self.var_adresa = tk.StringVar(value=date["adresa"] if date else "")

        cadru = ttk.Frame(self, padding=15)
        cadru.pack()
        for i, (text, var, latime) in enumerate([
                ("Nume:", self.var_nume, 40),
                ("CNP:", self.var_cnp, 40),
                ("Adresă:", self.var_adresa, 40)]):
            ttk.Label(cadru, text=text).grid(row=i, column=0, sticky="w", pady=5)
            ttk.Entry(cadru, textvariable=var, width=latime).grid(
                row=i, column=1, pady=5, padx=(10, 0))

        butoane = ttk.Frame(cadru)
        butoane.grid(row=3, column=0, columnspan=2, pady=(12, 0), sticky="e")
        ttk.Button(butoane, text="Salvează", command=self.salveaza).pack(side="left", padx=5)
        ttk.Button(butoane, text="Anulează", command=self.destroy).pack(side="left")

        self.bind("<Return>", lambda e: self.salveaza())
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        self.focus_set()

    def salveaza(self):
        nume = self.var_nume.get().strip()
        cnp = self.var_cnp.get().strip()
        adresa = self.var_adresa.get().strip()
        if not nume:
            messagebox.showerror("Date incomplete", "Introdu numele.", parent=self)
            return
        if not re.fullmatch(r"\d{13}", cnp):
            messagebox.showerror("CNP invalid",
                                 "CNP-ul trebuie să aibă exact 13 cifre.", parent=self)
            return
        if not adresa:
            messagebox.showerror("Date incomplete", "Introdu adresa.", parent=self)
            return
        self.rezultat = (nume, cnp, adresa)
        self.destroy()


# ----------------------------------------------------------------------------
# Fereastra 2: Registrul utilizatorilor
# ----------------------------------------------------------------------------
class FereastraRegistru(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.db = app.db
        self.title("Registrul utilizatorilor")
        self.geometry("1000x560")
        self.minsize(800, 420)
        self.protocol("WM_DELETE_WINDOW", self.inchide)

        # --- rândul de sus: preț + căutare ---
        sus = ttk.Frame(self, padding=(12, 12, 12, 4))
        sus.pack(fill="x")
        ttk.Label(sus, text="Preț m³ apă =").pack(side="left")
        self.var_pret = tk.StringVar(value=fmt_num(self.db.pret()))
        ttk.Entry(sus, textvariable=self.var_pret, width=8, justify="right").pack(
            side="left", padx=(6, 2))
        ttk.Label(sus, text="lei").pack(side="left")
        ttk.Button(sus, text="Salvează preț", command=self.salveaza_pret).pack(
            side="left", padx=10)

        self.var_cauta = tk.StringVar()
        self.var_cauta.trace_add("write", lambda *a: self.incarca())
        ttk.Entry(sus, textvariable=self.var_cauta, width=28).pack(side="right")
        ttk.Label(sus, text="Caută:").pack(side="right", padx=(0, 6))

        ttk.Label(
            self, foreground="#666666", padding=(12, 0, 12, 6),
            text="Prețul nou se aplică doar consumurilor introduse de acum înainte; "
                 "lunile deja introduse își păstrează tariful."
        ).pack(fill="x")

        # --- titlu + butoane ---
        bara = ttk.Frame(self, padding=(12, 4))
        bara.pack(fill="x")
        ttk.Label(bara, text="👤  Registrul Utilizatorilor",
                  font=("TkDefaultFont", 14, "bold")).pack(side="left")
        ttk.Button(bara, text="Șterge", command=self.sterge).pack(side="right", padx=3)
        ttk.Button(bara, text="Modifică", command=self.modifica).pack(side="right", padx=3)
        ttk.Button(bara, text="Adaugă", command=self.adauga).pack(side="right", padx=3)
        ttk.Button(bara, text="Deschide evidența", command=self.deschide).pack(
            side="right", padx=(3, 20))

        # --- tabel ---
        zona = ttk.Frame(self, padding=(12, 4, 12, 4))
        zona.pack(fill="both", expand=True)
        coloane = ("id", "nume", "cnp", "adresa", "index")
        self.tabel = ttk.Treeview(zona, columns=coloane, show="headings",
                                  selectmode="browse")
        for col, text, lat, ancora in [
                ("id", "ID", 50, "center"), ("nume", "Nume", 190, "w"),
                ("cnp", "CNP", 140, "center"), ("adresa", "Adresă", 380, "w"),
                ("index", "Index total (m³)", 110, "e")]:
            self.tabel.heading(col, text=text)
            self.tabel.column(col, width=lat, anchor=ancora,
                              stretch=(col == "adresa"))
        bara_scroll = ttk.Scrollbar(zona, orient="vertical", command=self.tabel.yview)
        self.tabel.configure(yscrollcommand=bara_scroll.set)
        self.tabel.pack(side="left", fill="both", expand=True)
        bara_scroll.pack(side="right", fill="y")

        self.tabel.bind("<Double-1>", lambda e: self.deschide_la_click(e))
        self.tabel.bind("<Return>", lambda e: self.deschide())
        self.tabel.bind("<Delete>", lambda e: self.sterge())

        self.lbl_info = ttk.Label(self, foreground="#666666", padding=(12, 2, 12, 10))
        self.lbl_info.pack(fill="x")
        self.incarca()

    # --- date ---
    def incarca(self):
        selectat = self.tabel.selection()
        self.tabel.delete(*self.tabel.get_children())
        randuri = self.db.utilizatori(self.var_cauta.get())
        for r in randuri:
            self.tabel.insert("", "end", iid=str(r["id"]), values=(
                f"{r['id']:02d}", r["nume"], r["cnp"], r["adresa"],
                fmt_num(r["index_total"])))
        if selectat and self.tabel.exists(selectat[0]):
            self.tabel.selection_set(selectat[0])
        self.lbl_info.config(
            text=f"{len(randuri)} utilizatori. Dublu-clic pe un utilizator "
                 f"deschide evidența lui lunară.")

    def utilizator_selectat(self):
        sel = self.tabel.selection()
        if not sel:
            messagebox.showinfo("Selectează un utilizator",
                                "Alege mai întâi un utilizator din tabel.", parent=self)
            return None
        return int(sel[0])

    # --- acțiuni ---
    def salveaza_pret(self):
        try:
            pret = citeste_numar(self.var_pret.get())
            if pret <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Preț invalid",
                                 "Introdu un număr pozitiv, de exemplu 5,00.", parent=self)
            return
        self.db.set_pret(pret)
        self.var_pret.set(fmt_num(pret))
        self.app.actualizeaza_tot()
        messagebox.showinfo("Salvat", f"Prețul pe m³ este acum {pret:.2f} lei.",
                            parent=self)

    def adauga(self):
        form = FormUtilizator(self, "Adaugă utilizator")
        self.wait_window(form)
        if form.rezultat:
            try:
                self.db.adauga_utilizator(*form.rezultat)
            except sqlite3.IntegrityError:
                messagebox.showerror("CNP existent",
                                     "Există deja un utilizator cu acest CNP.", parent=self)
                return
            self.app.actualizeaza_tot()

    def modifica(self):
        uid = self.utilizator_selectat()
        if uid is None:
            return
        form = FormUtilizator(self, "Modifică utilizator", self.db.utilizator(uid))
        self.wait_window(form)
        if form.rezultat:
            try:
                self.db.modifica_utilizator(uid, *form.rezultat)
            except sqlite3.IntegrityError:
                messagebox.showerror("CNP existent",
                                     "Există deja un utilizator cu acest CNP.", parent=self)
                return
            self.app.actualizeaza_tot()

    def sterge(self):
        uid = self.utilizator_selectat()
        if uid is None:
            return
        u = self.db.utilizator(uid)
        if messagebox.askyesno(
                "Confirmă ștergerea",
                f"Ștergi utilizatorul „{u['nume']}”?\n\n"
                "Se vor șterge și toate consumurile și plățile lui.",
                icon="warning", parent=self):
            self.db.sterge_utilizator(uid)
            self.app.actualizeaza_tot()

    def deschide_la_click(self, event):
        if self.tabel.identify_row(event.y):
            self.deschide()

    def deschide(self):
        uid = self.utilizator_selectat()
        if uid is not None:
            FereastraEvidenta(self.app, uid)

    def inchide(self):
        self.app.registru = None
        self.destroy()


# ----------------------------------------------------------------------------
# Fereastra 3: Evidența lunară + înregistrarea plăților
# ----------------------------------------------------------------------------
class FereastraEvidenta(tk.Toplevel):
    def __init__(self, app, uid):
        super().__init__(app)
        self.app = app
        self.db = app.db
        self.uid = uid
        u = self.db.utilizator(uid)
        self.title(f"Evidența lunară – {u['nume']}")
        self.geometry("900x720")
        self.minsize(780, 600)

        # --- antet ---
        antet = ttk.Frame(self, padding=(14, 12, 14, 4))
        antet.pack(fill="x")
        ttk.Label(antet, text="💧", font=("TkDefaultFont", 28)).pack(side="left", padx=(0, 12))
        text = ttk.Frame(antet)
        text.pack(side="left")
        ttk.Label(text, text="Evidența Lunară",
                  font=("TkDefaultFont", 16, "bold")).pack(anchor="w")
        ttk.Label(text, text=f"{u['nume']}, CNP {u['cnp']}, {u['adresa']}").pack(anchor="w")

        # --- adaugă consum ---
        adauga = ttk.LabelFrame(self, text=" Adaugă consum ", padding=10)
        adauga.pack(fill="x", padx=14, pady=8)
        acum = _acum()
        self.var_luna = tk.StringVar(value=LUNI[acum[1] - 1])
        self.var_an = tk.StringVar(value=str(acum[0]))
        self.var_index = tk.StringVar()
        ttk.Label(adauga, text="Luna:").pack(side="left")
        ttk.Combobox(adauga, textvariable=self.var_luna, values=LUNI,
                     state="readonly", width=12).pack(side="left", padx=(6, 4))
        ttk.Spinbox(adauga, textvariable=self.var_an, from_=2000, to=2100,
                    width=6).pack(side="left", padx=(0, 16))
        ttk.Label(adauga, text="Index (m³):").pack(side="left")
        camp_index = ttk.Entry(adauga, textvariable=self.var_index, width=10)
        camp_index.pack(side="left", padx=(6, 12))
        camp_index.bind("<Return>", lambda e: self.adauga_consum())
        ttk.Button(adauga, text="Adaugă consum", command=self.adauga_consum).pack(side="left")
        ttk.Button(adauga, text="Șterge luna selectată",
                   command=self.sterge_consum).pack(side="right")

        # --- tabel consumuri ---
        self.tabel_consum = ttk.Treeview(
            self, columns=("luna", "index", "tarif", "sold"), show="headings",
            height=6, selectmode="browse")
        for col, text, lat, ancora in [
                ("luna", "Luna", 200, "w"), ("index", "Index (m³)", 120, "e"),
                ("tarif", "Tarif", 160, "e"), ("sold", "Sold", 140, "e")]:
            self.tabel_consum.heading(col, text=text)
            self.tabel_consum.column(col, width=lat, anchor=ancora)
        self.tabel_consum.pack(fill="x", padx=14)
        self.lbl_total = ttk.Label(self, font=("TkDefaultFont", 11, "bold"))
        self.lbl_total.pack(anchor="e", padx=18, pady=(4, 8))

        ttk.Separator(self).pack(fill="x", padx=14, pady=4)

        # --- înregistrarea plăților ---
        plati_antet = ttk.Frame(self, padding=(14, 6, 14, 4))
        plati_antet.pack(fill="x")
        ttk.Label(plati_antet, text="💰", font=("TkDefaultFont", 24)).pack(side="left", padx=(0, 12))
        ttk.Label(plati_antet, text="Înregistrarea plăților",
                  font=("TkDefaultFont", 14, "bold")).pack(side="left")
        ttk.Button(plati_antet, text="🖨  Tipărește situația",
                   command=self.tipareste).pack(side="right")

        self.tabel_plati = ttk.Treeview(
            self, columns=("luna", "sold", "incasat", "rest"), show="headings",
            height=6, selectmode="browse")
        for col, text, lat, ancora in [
                ("luna", "Luna", 200, "w"), ("sold", "Sold", 140, "e"),
                ("incasat", "Încasat", 140, "e"), ("rest", "Rest de plată", 160, "e")]:
            self.tabel_plati.heading(col, text=text)
            self.tabel_plati.column(col, width=lat, anchor=ancora)
        self.tabel_plati.pack(fill="x", padx=14)
        self.tabel_plati.bind("<<TreeviewSelect>>", lambda e: self._actualizeaza_eticheta_plata())

        plata = ttk.Frame(self, padding=(14, 8))
        plata.pack(fill="x")
        self.lbl_luna_plata = ttk.Label(plata, text="Selectează o lună din tabel")
        self.lbl_luna_plata.pack(side="left")
        ttk.Button(plata, text="Anulează plățile lunii",
                   command=self.anuleaza_plati).pack(side="right")
        ttk.Button(plata, text="Înregistrează plata",
                   command=self.inregistreaza_plata).pack(side="right", padx=8)
        self.var_suma = tk.StringVar()
        camp_suma = ttk.Entry(plata, textvariable=self.var_suma, width=10, justify="right")
        camp_suma.pack(side="right")
        camp_suma.bind("<Return>", lambda e: self.inregistreaza_plata())
        ttk.Label(plata, text="Încasat (lei):").pack(side="right", padx=(0, 6))

        self.lbl_rest = ttk.Label(self, font=("TkDefaultFont", 12, "bold"))
        self.lbl_rest.pack(anchor="w", padx=18, pady=(2, 10))

        self.incarca()
        camp_index.focus_set()

    # --- date ---
    def incarca(self, luna_selectata=None):
        if luna_selectata is None:
            sel = self.tabel_plati.selection()
            luna_selectata = sel[0] if sel else None

        self.tabel_consum.delete(*self.tabel_consum.get_children())
        self.tabel_plati.delete(*self.tabel_plati.get_children())
        incasat = self.db.incasat_pe_luni(self.uid)
        total_sold = 0.0
        total_incasat = 0.0
        for r in self.db.consumuri(self.uid):
            sold = r["index_val"] * r["tarif"]
            inc = incasat.get(r["luna"], 0.0)
            total_sold += sold
            total_incasat += inc
            self.tabel_consum.insert("", "end", iid=r["luna"], values=(
                eticheta_luna(r["luna"]), fmt_num(r["index_val"]),
                f"{fmt_num(r['tarif'])} lei/m³", fmt_lei(sold)))
            self.tabel_plati.insert("", "end", iid=r["luna"], values=(
                eticheta_luna(r["luna"]), fmt_lei(sold), fmt_lei(inc),
                fmt_lei(max(sold - inc, 0))))
        rest = total_sold - total_incasat
        self.lbl_total.config(text=f"Total: {fmt_lei(total_sold)}")
        self.lbl_rest.config(
            text=f"Rest de plată: {fmt_lei(max(rest, 0))}",
            foreground=CULOARE_ROSU if rest > 0.005 else CULOARE_VERDE)
        if luna_selectata and self.tabel_plati.exists(luna_selectata):
            self.tabel_plati.selection_set(luna_selectata)
        self._actualizeaza_eticheta_plata()

    def _actualizeaza_eticheta_plata(self):
        sel = self.tabel_plati.selection()
        if sel:
            self.lbl_luna_plata.config(text=f"Plată pentru: {eticheta_luna(sel[0])}")
        else:
            self.lbl_luna_plata.config(text="Selectează o lună din tabel")

    def tipareste(self):
        if not self.db.consumuri(self.uid):
            messagebox.showinfo("Nimic de tipărit",
                                "Utilizatorul nu are încă niciun consum înregistrat.",
                                parent=self)
            return
        try:
            tipareste_situatie(self.db, self.uid)
        except OSError as e:
            messagebox.showerror("Eroare la tipărire",
                                 f"Nu am putut genera fișa:\n{e}", parent=self)

    def _dupa_modificare(self, luna=None):
        self.incarca(luna)
        self.app.actualizeaza_tot()

    # --- acțiuni consum ---
    def adauga_consum(self):
        try:
            index_val = citeste_numar(self.var_index.get())
        except ValueError:
            messagebox.showerror("Index invalid",
                                 "Introdu un număr pozitiv pentru index.", parent=self)
            return
        try:
            an = int(self.var_an.get())
            if not 2000 <= an <= 2100:
                raise ValueError
        except ValueError:
            messagebox.showerror("An invalid", "Introdu un an între 2000 și 2100.",
                                 parent=self)
            return
        luna = f"{an:04d}-{LUNI.index(self.var_luna.get()) + 1:02d}"
        if self.db.exista_consum(self.uid, luna):
            if not messagebox.askyesno(
                    "Lună existentă",
                    f"Pentru {eticheta_luna(luna)} există deja un consum.\nÎl înlocuiesc?",
                    parent=self):
                return
        self.db.salveaza_consum(self.uid, luna, index_val, self.db.pret())
        self.var_index.set("")
        self._dupa_modificare(luna)

    def sterge_consum(self):
        sel = self.tabel_consum.selection()
        if not sel:
            messagebox.showinfo("Selectează o lună",
                                "Alege luna din tabelul de consumuri.", parent=self)
            return
        luna = sel[0]
        if messagebox.askyesno(
                "Confirmă ștergerea",
                f"Ștergi consumul pentru {eticheta_luna(luna)}?\n"
                "Se șterg și plățile înregistrate pentru luna respectivă.",
                icon="warning", parent=self):
            self.db.sterge_consum(self.uid, luna)
            self._dupa_modificare()

    # --- acțiuni plăți ---
    def _luna_plata(self):
        sel = self.tabel_plati.selection()
        if not sel:
            messagebox.showinfo("Selectează o lună",
                                "Alege luna din tabelul de plăți.", parent=self)
            return None
        return sel[0]

    def inregistreaza_plata(self):
        luna = self._luna_plata()
        if luna is None:
            return
        try:
            suma = citeste_numar(self.var_suma.get())
            if suma <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Sumă invalidă",
                                 "Introdu o sumă pozitivă, de exemplu 25 sau 12,50.",
                                 parent=self)
            return
        consum = next(r for r in self.db.consumuri(self.uid) if r["luna"] == luna)
        rest = consum["index_val"] * consum["tarif"] - self.db.incasat_pe_luni(self.uid).get(luna, 0.0)
        if suma > rest + 0.005:
            if not messagebox.askyesno(
                    "Suma depășește restul",
                    f"Restul de plată pentru {eticheta_luna(luna)} este {fmt_lei(max(rest, 0))}, "
                    f"iar tu încasezi {fmt_lei(suma)}.\nContinui?", parent=self):
                return
        self.db.adauga_plata(self.uid, luna, suma)
        self.var_suma.set("")
        self._dupa_modificare(luna)

    def anuleaza_plati(self):
        luna = self._luna_plata()
        if luna is None:
            return
        if messagebox.askyesno(
                "Confirmă",
                f"Ștergi toate plățile înregistrate pentru {eticheta_luna(luna)}?",
                icon="warning", parent=self):
            self.db.anuleaza_plati_luna(self.uid, luna)
            self._dupa_modificare(luna)


def _acum():
    from datetime import date
    azi = date.today()
    return azi.year, azi.month


# ----------------------------------------------------------------------------
# Fereastra: Restanțieri (cine nu a plătit și în ce lună)
# ----------------------------------------------------------------------------
class FereastraRestanti(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.db = app.db
        self.title("Restanțieri")
        self.geometry("960x520")
        self.minsize(760, 380)
        self.protocol("WM_DELETE_WINDOW", self.inchide)

        antet = ttk.Frame(self, padding=(14, 12, 14, 6))
        antet.pack(fill="x")
        ttk.Label(antet, text="⚠  Restanțieri",
                  font=("TkDefaultFont", 16, "bold")).pack(side="left")
        ttk.Button(antet, text="Deschide evidența",
                   command=self.deschide).pack(side="right")

        zona = ttk.Frame(self, padding=(14, 4, 14, 4))
        zona.pack(fill="both", expand=True)
        self.tabel = ttk.Treeview(
            zona, columns=("nume", "adresa", "luna", "sold", "incasat", "rest"),
            show="headings", selectmode="browse")
        for col, text, lat, ancora, stretch in [
                ("nume", "Nume", 170, "w", False),
                ("adresa", "Adresă", 280, "w", True),
                ("luna", "Luna neplătită", 140, "w", False),
                ("sold", "Sold", 90, "e", False),
                ("incasat", "Încasat", 90, "e", False),
                ("rest", "Rest de plată", 110, "e", False)]:
            self.tabel.heading(col, text=text)
            self.tabel.column(col, width=lat, anchor=ancora, stretch=stretch)
        self.tabel.tag_configure("rest", foreground=CULOARE_ROSU)
        scroll = ttk.Scrollbar(zona, orient="vertical", command=self.tabel.yview)
        self.tabel.configure(yscrollcommand=scroll.set)
        self.tabel.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tabel.bind("<Double-1>", self._la_dublu_clic)
        self.tabel.bind("<Return>", lambda e: self.deschide())

        self.lbl_info = ttk.Label(self, font=("TkDefaultFont", 11, "bold"),
                                  padding=(14, 6, 14, 12))
        self.lbl_info.pack(fill="x")
        self.incarca()

    def incarca(self):
        selectat = self.tabel.selection()
        self.tabel.delete(*self.tabel.get_children())
        randuri = self.db.restante_detaliat()
        total = 0.0
        for r in randuri:
            rest = r["sold"] - r["incasat"]
            total += rest
            self.tabel.insert(
                "", "end", iid=f"{r['id']}|{r['luna']}", tags=("rest",),
                values=(r["nume"], r["adresa"], eticheta_luna(r["luna"]),
                        fmt_lei(r["sold"]), fmt_lei(r["incasat"]), fmt_lei(rest)))
        if selectat and self.tabel.exists(selectat[0]):
            self.tabel.selection_set(selectat[0])
        nr = len({r["id"] for r in randuri})
        if randuri:
            self.lbl_info.config(
                text=f"{nr} utilizatori restanți, {len(randuri)} luni neplătite, "
                     f"total de recuperat: {fmt_lei(total)}   "
                     f"(dublu-clic deschide evidența utilizatorului)")
        else:
            self.lbl_info.config(text="Nu există restanțieri. 🎉")

    def _la_dublu_clic(self, event):
        if self.tabel.identify_row(event.y):
            self.deschide()

    def deschide(self):
        sel = self.tabel.selection()
        if not sel:
            messagebox.showinfo("Selectează un rând",
                                "Alege un utilizator din tabel.", parent=self)
            return
        FereastraEvidenta(self.app, int(sel[0].split("|")[0]))

    def inchide(self):
        self.app.restanti = None
        self.destroy()


# ----------------------------------------------------------------------------
# Fereastra 1: Panoul principal
# ----------------------------------------------------------------------------
class Panou(tk.Tk):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.registru = None
        self.restanti = None
        self.title("Evidența consumatorilor de apă")
        self.geometry("900x620")
        self.minsize(780, 560)

        self.v_de_incasat = tk.StringVar()
        self.v_incasat = tk.StringVar()
        self.v_restanti = tk.StringVar()
        self.v_index_retea = tk.StringVar()
        self.v_total_plata = tk.StringVar()
        self.v_total_incasari = tk.StringVar()
        self.v_rest = tk.StringVar()

        cadru = ttk.Frame(self, padding=20)
        cadru.pack(fill="both", expand=True)
        cadru.columnconfigure((0, 1), weight=1, uniform="col")

        ttk.Label(cadru, text="PANOU PRINCIPAL",
                  font=("TkDefaultFont", 18)).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(cadru, text="Situația generală a încasărilor",
                  font=("TkDefaultFont", 12)).grid(row=1, column=0, columnspan=2,
                                                   sticky="w", pady=(0, 14))

        self._card(cadru, 2, 0, "Total de încasat:", self.v_de_incasat, CULOARE_PORTOCALIU)
        self._card(cadru, 2, 1, "Total încasat:", self.v_incasat, CULOARE_VERDE)
        self._card(cadru, 3, 0, "RESTANȚI:", self.v_restanti, "black",
                   comanda=self.deschide_restanti)

        buton_registru = self._cadru_cu_bordura(cadru, 3, 1)
        ttk.Button(buton_registru, text="👤  Registrul utilizatorilor",
                   command=self.deschide_registru).pack(expand=True, fill="both",
                                                        padx=20, pady=30)

        # --- caseta de jos: rețeaua de alimentare ---
        jos = self._cadru_cu_bordura(cadru, 4, 0, columnspan=2, pady=(24, 8))
        jos.columnconfigure(1, weight=1)
        font_mare = ("TkDefaultFont", 12)

        rand = ttk.Frame(jos)
        rand.pack(fill="x", padx=16, pady=(14, 4))
        ttk.Label(rand, text="Index total de la rețeaua de alimentare cu apă:",
                  font=font_mare).pack(side="left")
        ttk.Label(rand, textvariable=self.v_index_retea, font=("TkDefaultFont", 12, "bold")
                  ).pack(side="left", padx=6)
        ttk.Button(rand, text="Adaugă index rețea",
                   command=self.adauga_index_retea).pack(side="right")

        self._linie(jos, "Total de plată:", self.v_total_plata, CULOARE_PORTOCALIU,
                    "(index rețea × preț pe m³)")
        self._linie(jos, "Total încasări:", self.v_total_incasari, CULOARE_VERDE,
                    "(suma încasată automat de la utilizatori)")
        self.lbl_rest = self._linie(jos, "Rămas de plată:", self.v_rest, CULOARE_ROSU,
                                    "(total de plată − total încasări)")
        ttk.Frame(jos, height=10).pack()

        self.actualizeaza()

    # --- elemente de interfață ---
    def _cadru_cu_bordura(self, parinte, rand, coloana, columnspan=1, pady=8):
        c = tk.Frame(parinte, highlightthickness=2, highlightbackground="black",
                     highlightcolor="black", bd=0)
        c.grid(row=rand, column=coloana, columnspan=columnspan, sticky="nsew",
               padx=8, pady=pady)
        return c

    def _card(self, parinte, rand, coloana, titlu, variabila, culoare, comanda=None):
        c = self._cadru_cu_bordura(parinte, rand, coloana)
        t = tk.Label(c, text=titlu, font=("TkDefaultFont", 16), anchor="w")
        t.pack(fill="x", padx=24, pady=(22, 0))
        lbl = tk.Label(c, textvariable=variabila, font=("TkDefaultFont", 22),
                       fg=culoare, anchor="w")
        lbl.pack(fill="x", padx=24, pady=(4, 22 if comanda is None else 0))
        if comanda is not None:
            sub = tk.Label(c, text="Click pentru detalii ›", fg="#666666", anchor="w")
            sub.pack(fill="x", padx=24, pady=(0, 14))
            for w in (c, t, lbl, sub):
                w.bind("<Button-1>", lambda e: comanda())
                w.config(cursor="hand2")
        return lbl

    def _linie(self, parinte, titlu, variabila, culoare, nota):
        rand = ttk.Frame(parinte)
        rand.pack(fill="x", padx=16, pady=3)
        ttk.Label(rand, text=titlu, font=("TkDefaultFont", 12), width=16).pack(side="left")
        lbl = tk.Label(rand, textvariable=variabila, fg=culoare,
                       font=("TkDefaultFont", 12, "bold"), width=14, anchor="w")
        lbl.pack(side="left")
        ttk.Label(rand, text=nota, foreground="#666666").pack(side="left", padx=6)
        return lbl

    # --- date ---
    def actualizeaza(self):
        de_incasat, incasat, restanti = self.db.totaluri()
        self.v_de_incasat.set(fmt_lei(de_incasat))
        self.v_incasat.set(fmt_lei(incasat))
        self.v_restanti.set(str(restanti))

        index_retea = self.db.index_retea()
        total_plata = index_retea * self.db.pret()
        rest = total_plata - incasat
        self.v_index_retea.set(f"{fmt_num(index_retea)} m³")
        self.v_total_plata.set(fmt_lei(total_plata))
        self.v_total_incasari.set(fmt_lei(incasat))
        self.v_rest.set(fmt_lei(rest))
        self.lbl_rest.config(fg=CULOARE_ROSU if rest > 0.005 else CULOARE_VERDE)

    def actualizeaza_tot(self):
        """Apelată de ferestrele copil după orice modificare."""
        self.actualizeaza()
        if self.registru is not None:
            self.registru.incarca()
        if self.restanti is not None:
            self.restanti.incarca()

    # --- acțiuni ---
    def deschide_restanti(self):
        if self.restanti is not None:
            self.restanti.deiconify()
            self.restanti.lift()
            return
        self.restanti = FereastraRestanti(self)

    def deschide_registru(self):
        if self.registru is not None:
            self.registru.deiconify()
            self.registru.lift()
            return
        self.registru = FereastraRegistru(self)

    def adauga_index_retea(self):
        text = simpledialog.askstring(
            "Index rețea",
            "Introdu indexul total de la rețeaua de alimentare cu apă (m³):",
            initialvalue=fmt_num(self.db.index_retea()), parent=self)
        if text is None:
            return
        try:
            valoare = citeste_numar(text)
        except ValueError:
            messagebox.showerror("Index invalid", "Introdu un număr pozitiv.", parent=self)
            return
        self.db.set_index_retea(valoare)
        self.actualizeaza()


def main():
    db = Baza(DB_PATH)
    Panou(db).mainloop()


if __name__ == "__main__":
    main()
