#!/usr/bin/env python3
"""
Version 1.0 – Stand: 10.04.2026
Prereq.: Python >3.8, requests, reportlab.

Erstellt ein PDF-Dateiverzeichnis aus einem öffentlichen OwnCloud-Link.
Benötigt wird die URL eines öffentlichen Shares, z.B. https://cloud.example.com/s/TOKEN
Das Skript lädt die Verzeichnisstruktur über WebDAV, extrahiert Informationen zu Dateien und Ordnern 
und erstellt daraus ein übersichtliches PDF mit Logo, Titel, Statistik und Tabelle.
Die PDF-Generierung erfolgt mit ReportLab, die WebDAV-Abfrage mit Requests. 
Es werden verschiedene Authentifizierungsvarianten ausprobiert, um mit unterschiedlichen 
OwnCloud-Versionen kompatibel zu sein. Bei mir lokal Version 1-3, bei ngbau nur Variante 5.
Das Logo wird aus einer Datei im selben Ordner wie das Skript geladen (z.B. NG_Logo_2021_Bau_4c.jpg). 

"""

import sys
import os
import re
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import urlparse, urljoin, quote
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, HRFlowable
)
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER


# ──────────────────────────────────────────────
# OwnCloud WebDAV-Abfrage
# ──────────────────────────────────────────────

def parse_share_id(url: str) -> tuple[str, str]:
    """Extrahiert Base-URL und Share-Token aus einem öffentlichen OwnCloud-Link."""
    # Typisches Format: https://cloud.example.com/s/TOKEN
    #                   https://cloud.example.com/index.php/s/TOKEN
    # bei uns ist es z.B. https://cloud.nesseler.de/index.php/s/TOKEN
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    match = re.search(r'/s/([^/?#]+)', parsed.path)
    if not match:
        raise ValueError(
            f"Kein Share-Token im Link gefunden: {url}\n"
            "Erwartet wird ein Link der Form: https://cloud.example.com/s/TOKEN"
        )
    token = match.group(1)
    return base, token


def webdav_propfind(base_url: str, token: str, path: str = "/", depth: int = 1) -> str:
    """Sendet einen WebDAV PROPFIND-Request an den öffentlichen Share.
    Versucht verschiedene Auth-Methoden, die unterschiedliche OwnCloud-Versionen benötigen.
    Standard WEBDAV funktioniert bei ng wegen CORS- und Auth-Problemen nicht
    """
    webdav_url = f"{base_url}/public.php/webdav{path}"
    body = """<?xml version="1.0" encoding="UTF-8"?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:displayname/>
    <d:getcontentlength/>
    <d:getlastmodified/>
    <d:resourcetype/>
    <d:getcontenttype/>
  </d:prop>
</d:propfind>"""

    # Verschiedene Auth-Varianten, die OwnCloud je nach Version erwartet
    auth_variants = [
        # Variante 1: Token als Username, leeres Passwort (Standard)
        {"auth": (token, ""), "headers": {}},
        # Variante 2: Token als Username, "null" als Passwort
        {"auth": (token, "null"), "headers": {}},
        # Variante 3: public als Username, Token als Passwort
        {"auth": ("public", token), "headers": {}},
        # Variante 4: Token im Header (manche OwnCloud-Versionen)
        {"auth": None, "headers": {"X-OC-Token": token}},
        # Variante 5: Token als Username mit explizitem Header ->> funktioniert bei ng
        {"auth": (token, ""), "headers": {"X-Requested-With": "XMLHttpRequest"}},
    ]

    last_error = None
    for variant in auth_variants:
        headers = {
            "Depth": str(depth),
            "Content-Type": "application/xml",
            **variant["headers"],
        }
        try:
            resp = requests.request(
                "PROPFIND",
                webdav_url,
                headers=headers,
                data=body,
                auth=variant["auth"],
                timeout=30,
                allow_redirects=True,
            )
            if resp.status_code in (207, 200):
                return resp.text
            last_error = f"WebDAV-Fehler {resp.status_code}: {resp.text[:300]}"
        except requests.RequestException as e:
            last_error = str(e)

    raise ConnectionError(last_error)


def parse_propfind(xml_text: str) -> list[dict]:
    """Parst die WebDAV-Antwort und gibt eine Liste von Einträgen zurück."""
    NS = {
        "d": "DAV:",
        "oc": "http://owncloud.org/ns",
        "nc": "http://nextcloud.org/ns",
    }
    root = ET.fromstring(xml_text)
    entries = []
    for response in root.findall("d:response", NS):
        href = response.findtext("d:href", "", NS)
        props = response.find("d:propstat/d:prop", NS)
        if props is None:
            continue

        resourcetype = props.find("d:resourcetype", NS)
        is_dir = resourcetype is not None and resourcetype.find("d:collection", NS) is not None

        name = props.findtext("d:displayname", "", NS)
        if not name:
            # Aus href ableiten
            name = href.rstrip("/").split("/")[-1]
            try:
                from urllib.parse import unquote
                name = unquote(name)
            except Exception:
                pass

        size_str = props.findtext("d:getcontentlength", "0", NS)
        try:
            size = int(size_str)
        except ValueError:
            size = 0

        modified = props.findtext("d:getlastmodified", "", NS)
        content_type = props.findtext("d:getcontenttype", "", NS)

        entries.append({
            "href": href,
            "name": name,
            "is_dir": is_dir,
            "size": size,
            "modified": modified,
            "content_type": content_type,
        })
    return entries


def fetch_recursive(base_url: str, token: str, path: str = "/", _depth: int = 0) -> list[dict]:
    """Lädt rekursiv alle Dateien und Ordner."""
    xml = webdav_propfind(base_url, token, path, depth=1)
    entries = parse_propfind(xml)
    print(f"{'  ' * _depth}Lade: {path} ({len(entries)} Einträge)")
    result = []
    for e in entries:
        # Eigenen Ordner-Eintrag überspringen (erster Eintrag = aktueller Pfad)
        if e["href"].rstrip("/") == f"/public.php/webdav{path}".rstrip("/"):
            continue
        e["depth"] = _depth
        result.append(e)
        if e["is_dir"]:
            # Unterordner: relativen Pfad extrahieren
            subpath = e["href"].replace("/public.php/webdav", "")
            if not subpath.endswith("/"):
                subpath += "/"
            try:
                children = fetch_recursive(base_url, token, subpath, _depth + 1)
                result.extend(children)
            except Exception as ex:
                print(f"  Warnung: Unterordner {subpath} konnte nicht gelesen werden: {ex}")

    return result


# ──────────────────────────────────────────────
# Hilfsfunktionen
# ──────────────────────────────────────────────

def format_size(size: int) -> str:
    """Gibt Dateigröße lesbar formatiert zurück."""
    if size == 0:
        return "–"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def format_date(date_str: str) -> str:
    """Parst HTTP-Datum und gibt deutsches Format zurück."""
    if not date_str:
        return "–"
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str)
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return date_str[:16] if len(date_str) >= 16 else date_str


def get_icon(entry: dict) -> str:
    """Gibt ein passendes Emoji/Symbol zurück."""
    if entry["is_dir"]:
        return "📁"
    name = entry["name"].lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    icons = {
        "pdf": "📄", "doc": "📝", "docx": "📝", "xls": "📊", "xlsx": "📊",
        "ppt": "📋", "pptx": "📋", "jpg": "🖼", "jpeg": "🖼", "png": "🖼",
        "gif": "🖼", "svg": "🖼", "mp4": "🎬", "avi": "🎬", "mov": "🎬",
        "mp3": "🎵", "wav": "🎵", "zip": "🗜", "rar": "🗜", "7z": "🗜",
        "txt": "📄", "csv": "📊", "dwg": "📐", "dxf": "📐", "ifc": "🏗",
    }
    return icons.get(ext, "📄")


# ──────────────────────────────────────────────
# PDF-Erstellung
# ──────────────────────────────────────────────

NESSELER_GREEN = colors.HexColor("#43B02A") #43B02A oder 45ab33
NESSELER_BLUE = colors.HexColor("#2D4B9B") #2D4B9B oder 0a4596
DARK_GRAY = colors.HexColor("#333333")
MID_GRAY = colors.HexColor("#666666")
LIGHT_GRAY = colors.HexColor("#F2F2F2")
TABLE_HEADER_BG = colors.HexColor("#1A1A2E")


def build_pdf(entries: list[dict], projekt: str, owncloud_url: str, logo_path: str, output_path: str):
    """Erstellt das PDF-Dokument."""
    now = datetime.now()
    stand = now.strftime("%d.%m.%Y  %H:%M Uhr")

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=f"Dateiverzeichnis – {projekt}",
        author="nesseler bau gmbh - Christian Hürtgen",
    )

    styles = getSampleStyleSheet()

    style_title = ParagraphStyle(
        "CustomTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        textColor=DARK_GRAY,
        spaceAfter=4,
        leading=22,
    )
    style_subtitle = ParagraphStyle(
        "CustomSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        textColor=MID_GRAY,
        spaceAfter=2,
    )
    style_url = ParagraphStyle(
        "URL",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=8,
        textColor=MID_GRAY,
        spaceAfter=0,
    )
    style_cell = ParagraphStyle(
        "Cell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        textColor=DARK_GRAY,
        leading=11,
    )
    style_dir = ParagraphStyle(
        "DirCell",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        textColor=NESSELER_BLUE,
        leading=11,
    )
    style_footer = ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7,
        textColor=MID_GRAY,
        alignment=TA_CENTER,
    )

    story = []

    # ── Header: Logo + Titel nebeneinander ──
    logo_img = Image(logo_path, width=3 * cm, height=3 * cm)
    logo_img.hAlign = "RIGHT"

    title_block = [
        Paragraph(f"Dateiverzeichnis", style_title),
        Paragraph(f"Projekt: <b>{projekt}</b>", style_subtitle),
        Paragraph(f"Stand: {stand}", style_subtitle),
        Paragraph(f"Quelle: {owncloud_url}", style_url),
    ]

    header_table = Table(
        [[title_block, logo_img]],
        colWidths=[13 * cm, 3.5 * cm],
    )
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.3 * cm))
    story.append(HRFlowable(width="100%", thickness=2, color=NESSELER_GREEN, spaceAfter=0.4 * cm))

    # ── Statistik ──
    total_files = sum(1 for e in entries if not e["is_dir"])
    total_dirs = sum(1 for e in entries if e["is_dir"])
    total_size = sum(e["size"] for e in entries if not e["is_dir"])

    stat_text = (
        f"Gesamt: <b>{total_files}</b> Dateien in <b>{total_dirs}</b> Ordnern "
        f"| Gesamtgröße: <b>{format_size(total_size)}</b>"
    )
    story.append(Paragraph(stat_text, style_subtitle))
    story.append(Spacer(1, 0.4 * cm))

    # ── Tabelle ──
    col_widths = [1.0 * cm, 8.0 * cm, 3.0 * cm, 3.0 * cm, 1.5 * cm]

    # Header-Zeile
    header_row = [
        Paragraph("<font color='white'>#</font>", ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=8, textColor=colors.white)),
        Paragraph("<font color='white'>Name</font>", ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=8, textColor=colors.white)),
        Paragraph("<font color='white'>Geändert</font>", ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=8, textColor=colors.white)),
        Paragraph("<font color='white'>Größe</font>", ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=8, textColor=colors.white)),
        Paragraph("<font color='white'>Typ</font>", ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=8, textColor=colors.white)),
    ]

    rows = [header_row]
    file_counter = 0

    for e in entries:
        indent = "  " * e.get("depth", 0)
        icon = get_icon(e)
        name_text = f"{indent}{icon} {e['name']}"

        if e["is_dir"]:
            name_para = Paragraph(name_text, style_dir)
            size_text = "–"
            type_text = "Ordner"
        else:
            file_counter += 1
            name_para = Paragraph(name_text, style_cell)
            size_text = format_size(e["size"])
            ext = e["name"].rsplit(".", 1)[-1].upper() if "." in e["name"] else "–"
            type_text = ext

        row = [
            Paragraph(str(file_counter) if not e["is_dir"] else "", style_cell),
            name_para,
            Paragraph(format_date(e["modified"]), style_cell),
            Paragraph(size_text, style_cell),
            Paragraph(type_text, style_cell),
        ]
        rows.append(row)

    table = Table(rows, colWidths=col_widths, repeatRows=1)

    table_style = TableStyle([
        # Header
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        # Zeilen abwechselnd einfärben
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
        ("TOPPADDING", (0, 1), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
        # Rahmen
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, NESSELER_GREEN),
        ("LINEBEFORE", (0, 0), (0, -1), 0.5, colors.HexColor("#DDDDDD")),
        ("LINEAFTER", (-1, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E0E0E0")),
    ])
    table.setStyle(table_style)
    story.append(table)

    # ── Footer über onLaterPages / canvas ──
    def add_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MID_GRAY)
        w, h = A4
        footer_text = f"Dateiverzeichnis | Projekt: {projekt} | Stand: {stand} | Seite {doc.page}"
        canvas.drawCentredString(w / 2, 1.2 * cm, footer_text)
        canvas.setLineWidth(0.5)
        canvas.setStrokeColor(NESSELER_GREEN)
        canvas.line(2 * cm, 1.6 * cm, w - 2 * cm, 1.6 * cm)
        canvas.restoreState()

    doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
    print(f"\n✅ PDF erstellt: {output_path}")


# ──────────────────────────────────────────────
# Hauptprogramm
# ──────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  OwnCloud Dateiverzeichnis – PDF-Generator")
    print("=" * 55)

    # Logo-Pfad: neben dem Script suchen
    script_dir = os.path.dirname(os.path.abspath(__file__))
    logo_candidates = [
        os.path.join(script_dir, "NG_Logo_2021_Bau_4c.jpg"),
        os.path.join(script_dir, "logo.jpg"),
        os.path.join(script_dir, "logo.png"),
    ]
    logo_path = None
    for lp in logo_candidates:
        if os.path.exists(lp):
            logo_path = lp
            break
    if not logo_path:
        print("⚠️  Logo nicht gefunden. Erwartet: NG_Logo_2021_Bau_4c.jpg im selben Ordner wie das Script.")
        print("   Das PDF wird ohne Logo erstellt.")

    # Eingaben
    owncloud_url = input("\nOwnCloud Share-Link (z.B. https://cloud.example.com/s/TOKEN): ").strip()
    if not owncloud_url:
        print("Fehler: Kein Link eingegeben.")
        sys.exit(1)

    projekt = input("Projektbezeichnung: ").strip()
    if not projekt:
        projekt = "Unbekanntes Projekt"

    output_name = input("Ausgabedatei (Enter für 'dateiverzeichnis.pdf'): ").strip()
    if not output_name:
        output_name = "dateiverzeichnis.pdf"
    if not output_name.endswith(".pdf"):
        output_name += ".pdf"

    print(f"\n🔍 Verbinde mit OwnCloud: {owncloud_url}")

    try:
        base_url, token = parse_share_id(owncloud_url)
        print(f"   Base-URL: {base_url}")
        print(f"   Token:    {token}")
        print("   Lade Verzeichnisstruktur (rekursiv) ...")
        entries = fetch_recursive(base_url, token)
        print(f"   {len(entries)} Einträge gefunden.")
    except Exception as e:
        print(f"\n❌ Fehler beim Laden: {e}")
        sys.exit(1)

    if not entries:
        print("⚠️  Keine Dateien gefunden – PDF wird trotzdem erstellt.")

    print("\n📄 Erstelle PDF ...")
    try:
        build_pdf(entries, projekt, owncloud_url, logo_path, output_name)
    except Exception as e:
        print(f"\n❌ Fehler bei PDF-Erstellung: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
