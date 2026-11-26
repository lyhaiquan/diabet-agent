# -*- coding: utf-8 -*-
"""Tao reference docx kieu IEEE (mot co chu) tu reference docx cua pandoc.

    python make_ieee_reference.py reference.docx reference_ieee.docx

Quy tac:
  - Mot phong chu (Times New Roman) va mot co chu 12 pt cho moi kieu: than bai, tieu de, bang,
    chu thich, muc luc, tai lieu tham khao. Tieu de phan cap bang dam / nghieng chu khong bang co chu.
  - Ngoai le duy nhat: khoi ma nguon dung Consolas 10 pt (chu co dinh do rong, 12 pt se tran dong).
  - Tieu de tai lieu (kieu Title) 16 pt dam, can giua, chi o trang bia.
  - Mau chu den hoan toan, khong con chu do / xanh.
"""
import sys
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

FONT = "Times New Roman"
BODY = Pt(12)
CODE = Pt(10)
TITLE = Pt(16)

src, dst = sys.argv[1], sys.argv[2]
doc = Document(src)
styles_el = doc.styles.element


def set_fonts(rpr, name):
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.insert(0, rf)
    for a in list(rf.attrib):
        del rf.attrib[a]
    for a in ("ascii", "hAnsi", "cs", "eastAsia"):
        rf.set(qn("w:" + a), name)


def set_size(rpr, pt):
    for tag in ("w:sz", "w:szCs"):
        e = rpr.find(qn(tag))
        if e is None:
            e = OxmlElement(tag)
            rpr.append(e)
        e.set(qn("w:val"), str(int(pt.pt * 2)))


# 1. docDefaults
dd = styles_el.find(qn("w:docDefaults"))
rpr = dd.find(qn("w:rPrDefault")).find(qn("w:rPr"))
set_fonts(rpr, FONT)
set_size(rpr, BODY)
ppr = dd.find(qn("w:pPrDefault")).find(qn("w:pPr"))
sp = ppr.find(qn("w:spacing"))
if sp is None:
    sp = OxmlElement("w:spacing")
    ppr.append(sp)
sp.set(qn("w:after"), "120")
sp.set(qn("w:line"), "312")        # gian dong 1,3
sp.set(qn("w:lineRule"), "auto")

# 2. tung kieu
CODE_STYLES = {"SourceCode", "VerbatimChar"}
for st in doc.styles:
    el = st.element
    sid = el.get(qn("w:styleId")) or ""
    if st.type not in (1, 2):      # 1 = paragraph, 2 = character
        continue
    rpr = el.find(qn("w:rPr"))
    if rpr is None:
        rpr = OxmlElement("w:rPr")
        el.append(rpr)
    is_code = sid in CODE_STYLES or sid.endswith("Tok")
    if is_code:
        set_fonts(rpr, "Consolas")
        set_size(rpr, CODE)
    else:
        set_fonts(rpr, FONT)
        set_size(rpr, TITLE if sid in ("Title",) else BODY)
    # mau chu: den
    for c in rpr.findall(qn("w:color")):
        rpr.remove(c)
    if sid.endswith("Tok") and sid not in ("NormalTok",):
        pass                        # to mau cu phap la ngoai le cua khoi ma (giu mau)
    elif not is_code:
        c = OxmlElement("w:color")
        c.set(qn("w:val"), "000000")
        rpr.append(c)
    # tieu de: dam, khong nghieng tru H3
    if sid.startswith("Heading") and not sid.endswith("Char"):
        for t in ("w:b", "w:bCs", "w:i", "w:iCs"):
            for e in rpr.findall(qn(t)):
                rpr.remove(e)
        rpr.append(OxmlElement("w:b"))
        if sid in ("Heading3", "Heading4", "Heading5"):
            rpr.append(OxmlElement("w:i"))
    if sid == "Title":
        for e in rpr.findall(qn("w:b")):
            rpr.remove(e)
        rpr.append(OxmlElement("w:b"))
    # thu tu phan tu trong rPr phai hop le voi Word: rFonts, b, i, color, sz, szCs ...
    order = ["rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "color", "spacing",
             "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect", "bdr", "shd", "vertAlign", "lang"]
    kids = list(rpr)
    kids.sort(key=lambda k: order.index(k.tag.split("}")[1]) if k.tag.split("}")[1] in order else 99)
    for k in kids:
        rpr.remove(k)
    for k in kids:
        rpr.append(k)

# 3. can le, ngat dong, thut dau dong
def ppr_of(style):
    el = style.element
    p = el.find(qn("w:pPr"))
    if p is None:
        p = OxmlElement("w:pPr")
        # pPr phai dung truoc rPr
        r = el.find(qn("w:rPr"))
        if r is not None:
            r.addprevious(p)
        else:
            el.append(p)
    return p


def set_just(style, val):
    p = ppr_of(style)
    j = p.find(qn("w:jc"))
    if j is None:
        j = OxmlElement("w:jc")
        p.append(j)
    j.set(qn("w:val"), val)


def reorder_ppr(p):
    order = ["pStyle", "keepNext", "keepLines", "pageBreakBefore", "widowControl", "numPr", "pBdr", "shd", "tabs",
             "spacing", "ind", "contextualSpacing", "jc", "outlineLvl"]
    kids = list(p)
    kids.sort(key=lambda k: order.index(k.tag.split("}")[1]) if k.tag.split("}")[1] in order else 99)
    for k in kids:
        p.remove(k)
    for k in kids:
        p.append(k)


names = {s.element.get(qn("w:styleId")): s for s in doc.styles}
for sid in ("BodyText", "FirstParagraph", "Compact", "BlockText"):
    if sid in names:
        set_just(names[sid], "both" if sid != "Compact" else "left")
for sid in ("SourceCode",):          # khối mã: căn trái, không giãn chữ
    if sid in names:
        set_just(names[sid], "left")
for sid in ("Title", "Subtitle", "Author", "Date"):
    if sid in names:
        set_just(names[sid], "center")
for sid in ("ImageCaption", "TableCaption", "Caption"):
    if sid in names:
        set_just(names[sid], "center")
        r = names[sid].element.find(qn("w:rPr"))
        for t in ("w:i", "w:iCs"):
            for e in r.findall(qn(t)):
                r.remove(e)
for sid in ("Heading1", "Heading2", "Heading3"):
    if sid in names:
        set_just(names[sid], "left")
        p = ppr_of(names[sid])
        sp = p.find(qn("w:spacing"))
        if sp is None:
            sp = OxmlElement("w:spacing")
            p.append(sp)
        sp.set(qn("w:before"), "240")
        sp.set(qn("w:after"), "120")
        k = p.find(qn("w:keepNext"))
        if k is None:
            p.append(OxmlElement("w:keepNext"))
# bang va muc luc: khong gian dong 1,3 (de bang gon)
for sid in ("Compact",):
    if sid in names:
        p = ppr_of(names[sid])
        sp = p.find(qn("w:spacing"))
        if sp is None:
            sp = OxmlElement("w:spacing")
            p.append(sp)
        sp.set(qn("w:before"), "20")
        sp.set(qn("w:after"), "20")
        sp.set(qn("w:line"), "252")
        sp.set(qn("w:lineRule"), "auto")

# kieu "Reference": thut le treo, can deu, cho danh muc tai lieu tham khao
from docx.enum.style import WD_STYLE_TYPE
ref = doc.styles.add_style("Reference", WD_STYLE_TYPE.PARAGRAPH)
ref.base_style = doc.styles["Body Text"] if "Body Text" in [s.name for s in doc.styles] else None
ref.font.name = FONT
ref.font.size = BODY
pf = ref.paragraph_format
pf.left_indent = Cm(1.0)
pf.first_line_indent = Cm(-1.0)
pf.space_after = Pt(4)
pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
ref.element.set(qn("w:customStyle"), "1")

# 4. trang A4, le 2,5 cm
for sec in doc.sections:
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2.5)
    sec.top_margin = sec.bottom_margin = Cm(2.5)

for p in doc.styles.element.iter(qn("w:pPr")):
    reorder_ppr(p)
doc.save(dst)
print("ok:", dst)
