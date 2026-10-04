"""문서 내보내기 — 엑셀(.xlsx) / 한글(.hwpx)

문서마다 레이아웃을 한 번만 정의하고(블록 목록), 같은 레이아웃을 엑셀과 한글로 각각 그린다.
  블록: ('p', 문단) · ('s', 여백mm) · ('t', 표) · ('br',) 페이지 나눔
  표:   widths=[열 너비 mm...], rows=[(행 높이 mm, [셀...])]  — 셀은 HTML처럼 병합된 칸은 생략
"""
import io, os, zipfile, random
from xml.sax.saxutils import escape
from PIL import Image, ImageOps

PAGE_W = 180  # A4 본문 폭(mm), 좌우 여백 15mm
STAMP = 15    # 직인 크기(mm)

TYPE_NAME = {'quote': '견적서', 'statement': '거래명세서', 'contract': '공사도급표준계약서', 'completion': '작업완료확인서'}
GRAY = '#EFEFEF'
BLUE = '#DFE5EE'


# ── 공통 ──────────────────────────────────────────────────────────────────────

def won(n):
    return f'{int(n or 0):,}'


def kor_num(n):
    """숫자 → 한글 금액 (2420000 → 이백사십이만)"""
    n = int(n or 0)
    if not n:
        return '영'
    D, S, B = '_일이삼사오육칠팔구', ['', '십', '백', '천'], ['', '만', '억', '조']
    out, g = '', 0
    while n > 0:
        part = n % 10000
        if part:
            s = ''
            for i, c in enumerate(f'{part:04d}'):
                v, u = int(c), 3 - i
                if v:
                    s += ('' if v == 1 and u > 0 else D[v]) + S[u]
            if part == 1 and g > 0:
                s = '일'
            out = s + B[g] + out
        n //= 10000
        g += 1
    return out


def sum_items(items):
    supply = tax = 0
    for it in items:
        a = round(float(it.get('qty') or 0) * float(it.get('price') or 0))
        supply += a
        tax += round(a * 0.1)
    return supply, tax


def ymd(d, blank=False):
    if not d:
        return '        년      월      일' if blank else ''
    y, m, dd = d.split('-')
    return f'{y}년 {m}월 {dd}일'


def ymd_short(d):
    if not d:
        return ''
    y, m, dd = d.split('-')
    return f'{y}년 {int(m)}월 {int(dd)}일'


def spaced(s):
    return ' '.join(s or '')


def vertical(s):
    return '\n'.join(c for c in s if c != ' ')


def C(text='', **kw):
    kw['text'] = '' if text is None else str(text)
    return kw


def P(text, **kw):
    kw['text'] = text
    return ('p', kw)


def T(widths, rows, border=True):
    return ('t', {'widths': widths, 'rows': rows, 'border': border})


# ── 문서별 레이아웃 ───────────────────────────────────────────────────────────

def lab(text, **kw):
    return C(text, bg=GRAY, bold=True, align='CENTER', **kw)


def layout_quote(doc, co):
    d, c = doc['data'], doc['data'].get('client') or {}
    items = [it for it in d.get('items') or [] if it.get('name') or it.get('price')]
    supply, tax = sum_items(items)
    total = supply + tax
    tel = ('TEL ' + c['tel'] if c.get('tel') else '') + (' / FAX ' + c['fax'] if c.get('fax') else '')
    co_tel = f"TEL {co['tel']}" + (f" / FAX {co['fax']}" if co.get('fax') else '')
    none = (0, 0, 0, 0)
    rows = [(7.5, [lab('수 신'), C(doc['client_name'], bold=True), C(b=none), lab('상 호'), C(co['name'], b=(1, 0, 1, 1)),
                   C('(인)', align='CENTER', b=(0, 1, 1, 1), stamp=True)]),
            (7.5, [lab('연락처'), C(tel), C(b=none), lab('주 소'), C(co['address'], cs=2)]),
            (7.5, [lab('공사명'), C(doc.get('title')), C(b=none), lab('사업자번호'), C(co['biz_no'], cs=2)]),
            (7.5, [lab('유효기간'), C(d.get('valid_until')), C(b=none), lab('연락처', rs=2), C(f"{co_tel}\nEMAIL  {co['email']}", rs=2, cs=2)]),
            (7.5, [C('1. 귀사의 일익 번창하심을 기원합니다.\n2. 하기와 같이 견적드리오니 검토하기 바랍니다.', cs=2, rs=2), C(b=none)]),
            (7.5, [C(b=none), lab('담당자'), C(f"{co['ceo']}   {co.get('mobile', '')}", cs=2)])]
    item_rows = [(7.6, [lab(h) for h in ['품목명', '규격', '수량', '단가', '공급가액', '부가세']])]
    for i in range(max(14, len(items))):
        it = items[i] if i < len(items) else None
        if not it:
            item_rows.append((7, [C() for _ in range(6)]))
            continue
        a = round(float(it.get('qty') or 0) * float(it.get('price') or 0))
        item_rows.append((7, [C(it.get('name')), C(it.get('spec'), align='CENTER'), C(it.get('qty'), align='CENTER'),
                              C(num=it.get('price') or 0, align='RIGHT'), C(num=a, align='RIGHT'), C(num=round(a * 0.1), align='RIGHT')]))
    return [
        P('견 적 서', size=22, bold=True, underline=True, align='CENTER'),
        ('s', 3),
        T([90, 90], [(8, [C(f"일 자 : {(doc['doc_date'] or '').replace('-', '/')}", valign='BOTTOM'),
                          C(img=('logo', 25, 7), align='RIGHT', valign='BOTTOM')])], border=False),
        T([20, 68, 4, 22, 54, 12], rows),
        ('s', 3),
        T([120, 60], [(9, [C(f'금 액 : {kor_num(total)}원 정', bold=True, size=11.5, b=(1, 0, 1, 1)),
                           C(f'(₩ {won(total)}원)', bold=True, size=11.5, align='RIGHT', b=(0, 1, 1, 1))])]),
        ('s', 3),
        T([69, 16, 15, 26, 30, 24], item_rows),
        ('s', 2),
        T([22, 38, 14, 40, 16, 50], [(9, [lab('공급가액'), C(num=supply, align='RIGHT'), lab('VAT'), C(num=tax, align='RIGHT'),
                                          lab('합계'), C(num=total, align='RIGHT')])]),
        ('s', 2),
        T([15, 165], [(22, [lab('비고'), C(d.get('note'), valign='BOTTOM')])]),
    ]


def layout_statement(doc, co):
    d, c = doc['data'], doc['data'].get('client') or {}
    items = [it for it in d.get('items') or [] if it.get('name') or it.get('price')]
    supply, tax = sum_items(items)
    total = supply + tax
    none = (0, 0, 0, 0)
    vlab = lambda s: C(vertical(s), rs=5, bg=GRAY, bold=True, align='CENTER', size=9.5)
    rows = [(7.5, [vlab('공급받는자'), lab('상호'), C(doc['client_name'], cs=3, bold=True), C(b=none),
                   vlab('공급자'), lab('상호'), C(co['name'], cs=3)]),
            (7.5, [lab('사업자번호', size=9), C(c.get('biz_no'), size=9), lab('성명', size=9), C(c.get('ceo'), size=9), C(b=none),
                   lab('사업자번호', size=9), C(co['biz_no'], size=9), lab('성명', size=9), C(co['ceo'], size=9, stamp=True)]),
            (7.5, [lab('주소'), C(c.get('address'), cs=3, size=9), C(b=none), lab('주소'), C(co['address'], cs=3, size=9)]),
            (7.5, [lab('연락처'), C(c.get('tel'), cs=3), C(b=none), lab('연락처'), C(co['tel'], cs=3)]),
            (7.5, [lab('공사명'), C(doc.get('title'), cs=3, size=9), C(b=none), lab('EMAIL'), C(co['email'], cs=3)])]
    item_rows = [(7.6, [lab(h) for h in ['순번', '품목명', '규격', '수량', '단가', '공급가액', '부가세']])]
    for i in range(max(14, len(items))):
        it = items[i] if i < len(items) else None
        if not it:
            item_rows.append((7, [C() for _ in range(7)]))
            continue
        a = round(float(it.get('qty') or 0) * float(it.get('price') or 0))
        item_rows.append((7, [C(i + 1, align='CENTER'), C(it.get('name')), C(it.get('spec'), align='CENTER'), C(it.get('qty'), align='CENTER'),
                              C(num=it.get('price') or 0, align='RIGHT'), C(num=a, align='RIGHT'), C(num=round(a * 0.1), align='RIGHT')]))
    blocks = [
        P('거 래 명 세 서', size=22, bold=True, underline=True, align='CENTER'),
        ('s', 3),
        T([20, 50, 110], [(7.5, [lab('일 자'), C((doc['doc_date'] or '').replace('-', '/')),
                                 C(img=('logo', 25, 7), align='RIGHT', valign='BOTTOM', b=none)])]),
        T([7, 19, 30, 10, 21, 3, 7, 19, 30, 10, 24], rows),
        ('s', 3),
        T([120, 60], [(6, [C('  다음과 같이 계산합니다.', cs=2, size=9.5, b=(1, 1, 1, 0))]),
                      (8, [C(f'금  액 : {kor_num(total)}원 정', bold=True, size=11.5, b=(1, 0, 0, 1)),
                           C(f'(₩{won(total)})', bold=True, size=11.5, align='RIGHT', b=(0, 1, 0, 1))])]),
        T([11, 62, 15, 13, 25, 29, 25], item_rows),
        ('s', 2),
        T([20, 30, 12, 28, 13, 30, 13, 34], [(9, [lab('공급가액'), C(num=supply, align='RIGHT'), lab('VAT'), C(num=tax, align='RIGHT'),
                                                  lab('합계'), C(num=total, align='RIGHT'), lab('확인'), C('인', align='RIGHT')])]),
        ('s', 2),
        T([20, 160], [(15, [lab('비 고'), C(d.get('note'))])]),
    ]
    if co.get('bank'):
        blocks += [('s', 2), T([20, 160], [(9, [lab('입금계좌'), C(co['bank'], bold=True)])])]
    return blocks


def layout_contract(doc, co):
    d, c = doc['data'], doc['data'].get('client') or {}
    amt = int(doc.get('supply_amount') or 0)
    vat = '부가세포함' if d.get('vat_mode') == 'included' else '부가세별도'
    ctr = lambda s, **kw: C(s, align='CENTER', **kw)
    # 서명란: 왼쪽 "갑"(3칸) · 오른쪽 "을"(3칸, 마지막 칸은 (인) 자리)
    L, R = (1, 1, 0, 0), (1, 1, 0, 0)
    sign = [(9, [C('"갑"', cs=3, b=(1, 1, 1, 0)), C('"을"', cs=3, b=(1, 1, 1, 0))]),
            (8.5, [C(doc['client_name'], cs=3, b=L), C(f'주    소 : {co["address"]}', cs=3, b=R, size=9.5)]),
            (8.5, [C(f'주    소 : {c.get("address", "")}', cs=3, b=L), C(f'상    호 : {co["name"]}', cs=3, b=R)]),
            (8.5, [C(f'대 표 자 : {spaced(c.get("ceo"))} ( 인 )', cs=3, b=L), C(f'대 표 자 : {spaced(co["ceo"])}', cs=2, b=(1, 0, 0, 0)),
                   C('(인)', align='CENTER', b=(0, 1, 0, 0), stamp=True)]),
            (8.5, [C(f'전    화 : {c.get("tel", "")}', cs=3, b=L), C(f'전    화 : {co["tel"]}', cs=3, b=R)]),
            (5, [C(cs=3, b=(1, 1, 0, 1)), C(cs=3, b=(1, 1, 0, 1))])]
    rows = [
        (9.5, [C('공사도급표준계약서', cs=3, rs=2, size=17, bold=True, align='CENTER'), ctr('계약일자', cs=3)]),
        (9.5, [ctr(ymd(doc['doc_date']), cs=3)]),
        (9.5, [ctr('계\n약\n자', rs=4, bold=True), ctr('발주처'), C(f"○ {doc['client_name']}", cs=4)]),
        (9.5, [ctr('계약대상자', rs=3), C(f"○ 상호 또는 법인 명칭 : {co['name']}"), C(f"○ 사업자등록번호 : {co['biz_no']}", cs=3, size=9.5)]),
        (9.5, [C(f"○ 주소 : {co['address']}"), C(f"○ 전화번호 : {co['tel']}", cs=3)]),
        (9.5, [C(f"○ 대표자 : {spaced(co['ceo'])}"), C(cs=3)]),
        (9.5, [ctr('계\n약\n내\n용', rs=8, bold=True), ctr('공 사 명'), C(doc.get('title'), cs=4)]),
        (9.5, [ctr('계 약 금'), C(f'일금 {kor_num(amt)} 원정 ( ₩{won(amt)}원/{vat} )', cs=4)]),
        (9.5, [ctr('계약이행보증금'), C(d.get('perf_bond'), cs=4)]),
        (9.5, [ctr('하자이행보증금'), C(d.get('defect_bond'), cs=4)]),
        (9.5, [ctr('하자담보기간'), C(d.get('warranty'), cs=4)]),
        (9.5, [ctr('지체상금율'), C(d.get('delay_rate'), cs=4)]),
        (9.5, [ctr('착공년월일'), ctr(ymd(d.get('start_date'), True)), ctr('준공년월일'), ctr(ymd(d.get('end_date'), True), cs=2)]),
        (9.5, [ctr('기타사항'), C(d.get('etc_note'), cs=4)]),
        (22, [C('도급인("갑")과 수급인("을")은 상기와 같이 공사계약을 체결하고 신의에 성실히 계약상의 의무를 이행할 것을 확약하며, '
                '이 계약의 증서로서 계약서를 작성하여 당사자 간 기명, 날인 후 각각 1통씩 보관한다.', cs=6)]),
        (9.5, [C(f"붙임서류 : {d.get('attachments') or ''}", cs=3), C(cs=3)]),
        (12, [C(ymd(doc['doc_date']) + '   ', cs=6, align='RIGHT')]),
    ] + sign
    return [T([13, 30, 73, 27, 25, 12], rows)]


def layout_completion(doc, co):
    d = doc['data']
    amt = int(doc.get('supply_amount') or 0)
    vat = '부가세포함' if d.get('vat_mode') == 'included' else '부가세별도'
    none = (0, 0, 0, 0)
    info = lambda k, v: (11, [C(k, bg=BLUE, b=none, size=11), C(v, bg=BLUE, b=none, size=11)])
    blocks = [
        ('s', 22),
        P('작업완료확인서', size=22, align='CENTER'),
        ('s', 10),
        T([30, 150], [info('○ 공   사  명 :', doc.get('title')),
                      info('○ 계약금액 :', f'일 금 {kor_num(amt)} 원 정 (₩{won(amt)}), {vat}' if amt else ''),
                      info('○ 계약일자 :', ymd_short(d.get('contract_date'))),
                      info('○ 착공일자 :', ymd_short(d.get('start_date'))),
                      info('○ 준공일자 :', ymd_short(d.get('end_date')))], border=False),
        ('s', 30),
        P('    ❖    별첨 : 사진자료', size=12),
        ('s', 12),
        P((doc['doc_date'] or '').replace('-', '.'), size=13, align='CENTER'),
        ('s', 32),
        T([96, 32, 12, 40], [(8, [C(), C(f"주  소 : {co['address']}", cs=3, size=10.5)]),
                             (8, [C(), C(f"회사명 : {co['name']}", cs=3, size=10.5)]),
                             (8, [C(), C(f"성  명 : {co['ceo']}", size=10.5), C('(인)', align='CENTER', size=10.5, stamp=True), C()])],
          border=False),
    ]
    if (d.get('photo_layout') or 'rows') == 'grid':
        return blocks + completion_grid(d.get('photos') or [])
    groups = [g for g in d.get('groups') or [] if g.get('photos')]
    for p in range(0, len(groups), 3):
        rows = []
        for g in groups[p:p + 3]:
            photos = (g['photos'] + [None, None, None])[:3]
            rows.append((70, [C(vertical(g.get('title') or ''), rs=2, bold=True, align='CENTER', b=none, size=10.5)] +
                         [C(img=('photo', ph['folder'], ph['filename'], 54, 68), align='CENTER', b=none) if ph else C(b=none) for ph in photos]))
            rows.append((7, [C(ph.get('caption') if ph else '', align='CENTER', b=none) for ph in photos]))
            rows.append((4, [C(b=none, cs=4)]))
        blocks += [('br',), P('작업사진', size=14, bold=True, align='CENTER'), ('s', 5), T([12, 56, 56, 56], rows, border=False)]
    return blocks


def grid_shape(n):
    """사진 수에 따라 (열 수, 사진 폭mm, 사진 높이mm) — 한 페이지 최대 12장"""
    cols = 2 if n <= 4 else 3 if n <= 9 else 4
    rows = -(-n // cols)
    w = 178 / cols - 4
    h = min(w * 1.3, 240 / rows - 9)
    return cols, w, h


def completion_grid(photos):
    """작업사진: 사진만 격자로 모아서 (항목 제목 · 설명 없음)"""
    none = (0, 0, 0, 0)
    blocks = []
    for p in range(0, len(photos), 12):
        page = photos[p:p + 12]
        cols, w, h = grid_shape(len(page))
        rows = []
        for r in range(0, len(page), cols):
            line = page[r:r + cols] + [None] * (cols - len(page[r:r + cols]))
            rows.append((h + 2, [C(img=('photo', ph['folder'], ph['filename'], w, h), align='CENTER', b=none) if ph else C(b=none)
                                 for ph in line]))
            rows.append((4, [C(b=none, cs=cols)]))
        blocks += [('br',), P('작업사진', size=14, bold=True, align='CENTER'), ('s', 5),
                   T([178 / cols] * cols, rows, border=False)]
    return blocks


LAYOUTS = {'quote': layout_quote, 'statement': layout_statement, 'contract': layout_contract, 'completion': layout_completion}


def build_blocks(doc, co):
    return LAYOUTS[doc['doc_type']](doc, co)


# ── 이미지 ───────────────────────────────────────────────────────────────────

class Images:
    """레이아웃의 img 키 → 실제 이미지 바이트 (사진은 칸 비율에 맞게 잘라서 축소)"""

    def __init__(self, photo_dir, stamp_path, logo_path):
        self.photo_dir, self.stamp_path, self.logo_path = photo_dir, stamp_path, logo_path
        self.cache = {}

    def get(self, key):
        """반환: (bytes, ext, px_w, px_h) 또는 None"""
        if key in self.cache:
            return self.cache[key]
        res = None
        try:
            if key[0] == 'stamp':
                res = self._png(self.stamp_path)
            elif key[0] == 'logo':
                res = self._png(self.logo_path)
            elif key[0] == 'photo':
                _, folder, filename, w, h = key
                path = os.path.join(self.photo_dir, os.path.basename(folder), os.path.basename(filename))
                img = ImageOps.exif_transpose(Image.open(path)).convert('RGB')
                img = ImageOps.fit(img, (int(w * 12), int(h * 12)), Image.LANCZOS)  # 약 300dpi
                buf = io.BytesIO()
                img.save(buf, 'JPEG', quality=82)
                res = (buf.getvalue(), 'jpg', img.width, img.height)
        except Exception:
            res = None
        self.cache[key] = res
        return res

    @staticmethod
    def _png(path):
        if not path or not os.path.exists(path):
            return None
        img = Image.open(path)
        buf = io.BytesIO()
        img.save(buf, 'PNG')
        return (buf.getvalue(), 'png', img.width, img.height)


def place_cells(rows):
    """병합 칸을 고려해 각 셀의 (행, 열) 위치 계산"""
    occupied, placed = set(), []
    for r, (_, cells) in enumerate(rows):
        col = 0
        for cell in cells:
            while (r, col) in occupied:
                col += 1
            cs, rs = cell.get('cs', 1), cell.get('rs', 1)
            for dr in range(rs):
                for dc in range(cs):
                    occupied.add((r + dr, col + dc))
            placed.append((r, col, cell))
            col += cs
    return placed


def cell_borders(cell, table_border):
    b = cell.get('b')
    if b is None:
        b = (1, 1, 1, 1) if table_border else (0, 0, 0, 0)
    return tuple(bool(x) for x in b)


def cell_text(cell):
    if 'num' in cell:
        return won(cell['num'])
    return cell.get('text', '')


# ── 엑셀 ─────────────────────────────────────────────────────────────────────

def render_xlsx(blocks, images, title):
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.drawing.spreadsheet_drawing import OneCellAnchor, AnchorMarker
    from openpyxl.drawing.xdr import XDRPositiveSize2D
    from openpyxl.worksheet.pagebreak import Break
    from openpyxl.utils import get_column_letter

    PX = 96 / 25.4   # px per mm
    EMU = 9525       # EMU per px
    FONT = '맑은 고딕'

    # 모든 표의 열 경계를 합쳐 시트 전체의 열 격자를 만든다
    edges = {0.0, float(PAGE_W)}
    for kind, *rest in blocks:
        if kind == 't':
            x = 0.0
            for w in rest[0]['widths']:
                x = round(x + w, 2)
                edges.add(x)
    edges = sorted(edges)
    col_of = {x: i for i, x in enumerate(edges)}  # 경계 x(mm) → 열 번호(0부터)

    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.sheet_view.showGridLines = False
    for i in range(len(edges) - 1):
        px = (edges[i + 1] - edges[i]) * PX
        ws.column_dimensions[get_column_letter(i + 1)].width = max(0.1, (px - 5) / 7)

    thin = Side(style='thin', color='777777')
    row = 1
    last_col = len(edges) - 1

    def add_image(key, w_mm, h_mm, x_mm, row_idx, y_mm):
        im = images.get(key)
        if not im:
            return
        x_mm = max(0.0, min(x_mm, PAGE_W - 0.5))
        c = max(i for i, e in enumerate(edges[:-1]) if e <= x_mm)
        # 칸 위쪽으로 넘치면 윗행 기준으로 위치를 잡는다
        while y_mm < 0 and row_idx > 1:
            row_idx -= 1
            y_mm += (ws.row_dimensions[row_idx].height or 15) * 25.4 / 72
        xl = XLImage(io.BytesIO(im[0]))
        size = XDRPositiveSize2D(int(w_mm * PX * EMU), int(h_mm * PX * EMU))
        xl.anchor = OneCellAnchor(_from=AnchorMarker(col=c, colOff=int((x_mm - edges[c]) * PX * EMU),
                                                     row=row_idx - 1, rowOff=int(max(0, y_mm) * PX * EMU)), ext=size)
        ws.add_image(xl)

    for kind, *rest in blocks:
        if kind == 's':
            ws.row_dimensions[row].height = rest[0] * 72 / 25.4
            row += 1
        elif kind == 'br':
            ws.row_breaks.append(Break(id=row - 1))
        elif kind == 'p':
            p = rest[0]
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=last_col)
            cell = ws.cell(row=row, column=1, value=p['text'])
            cell.font = Font(name=FONT, size=p.get('size', 10), bold=p.get('bold', False),
                             underline='single' if p.get('underline') else None)
            cell.alignment = Alignment(horizontal=p.get('align', 'LEFT').lower(), vertical='center')
            ws.row_dimensions[row].height = p.get('size', 10) * 1.8
            row += 1
        elif kind == 't':
            t = rest[0]
            xs = [0.0]
            for w in t['widths']:
                xs.append(round(xs[-1] + w, 2))
            heights = [h for h, _ in t['rows']]
            for i, h in enumerate(heights):
                ws.row_dimensions[row + i].height = h * 72 / 25.4
            for r, c, cell in place_cells(t['rows']):
                cs, rs = cell.get('cs', 1), cell.get('rs', 1)
                c0, c1 = col_of[xs[c]] + 1, col_of[xs[c + cs]]
                r0, r1 = row + r, row + r + rs - 1
                if c1 > c0 or r1 > r0:
                    ws.merge_cells(start_row=r0, start_column=c0, end_row=r1, end_column=c1)
                xc = ws.cell(row=r0, column=c0)
                if 'num' in cell:
                    xc.value = int(cell['num'])
                    xc.number_format = '#,##0'
                elif cell.get('text'):
                    v = cell['text']
                    xc.value = int(v) if isinstance(v, str) and v.isdigit() and len(v) < 6 else v
                xc.font = Font(name=FONT, size=cell.get('size', 10), bold=cell.get('bold', False))
                xc.alignment = Alignment(horizontal=cell.get('align', 'LEFT').lower(),
                                         vertical={'TOP': 'top', 'BOTTOM': 'bottom'}.get(cell.get('valign'), 'center'),
                                         wrap_text=True, indent=0 if cell.get('align') in ('CENTER', 'RIGHT') else 1)
                fill = PatternFill('solid', fgColor=cell['bg'][1:]) if cell.get('bg') else None
                bl, br_, bt, bb = cell_borders(cell, t['border'])
                for rr in range(r0, r1 + 1):
                    for cc in range(c0, c1 + 1):
                        x = ws.cell(row=rr, column=cc)
                        x.border = Border(left=thin if bl and cc == c0 else None, right=thin if br_ and cc == c1 else None,
                                          top=thin if bt and rr == r0 else None, bottom=thin if bb and rr == r1 else None)
                        if fill:
                            x.fill = fill
                # 셀 안 이미지 (로고 · 사진)
                cell_w = xs[c + cs] - xs[c]
                cell_h = sum(heights[r:r + rs])
                if cell.get('img'):
                    key = cell['img']
                    w, h = key[-2], key[-1]
                    if cell.get('align') == 'RIGHT':
                        x0 = xs[c] + cell_w - w - 1
                    else:
                        x0 = xs[c] + (cell_w - w) / 2
                    y0 = {'BOTTOM': cell_h - h - 0.5, 'TOP': 0.5}.get(cell.get('valign'), (cell_h - h) / 2)
                    add_image(key, w, h, x0, r0, y0)
                # 직인: (인) 칸 정중앙에 겹쳐 찍기
                if cell.get('stamp'):
                    add_image(('stamp',), STAMP, STAMP, xs[c] + cell_w / 2 - STAMP / 2, r0, cell_h / 2 - STAMP / 2)
            row += len(t['rows'])

    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.orientation = 'portrait'
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0 if ws.row_breaks.brk else 1
    ws.page_margins.left = ws.page_margins.right = 0.55
    ws.page_margins.top = 0.5
    ws.page_margins.bottom = 0.4
    ws.page_margins.header = ws.page_margins.footer = 0
    ws.print_options.horizontalCentered = True
    ws.print_area = f'A1:{get_column_letter(last_col)}{row - 1}'
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── 한글(.hwpx) ──────────────────────────────────────────────────────────────

HU = 7200 / 25.4  # HWPUNIT per mm
NS = ('xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
      'xmlns:hp10="http://www.hancom.co.kr/hwpml/2016/paragraph" xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
      'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
      'xmlns:hhs="http://www.hancom.co.kr/hwpml/2011/history" xmlns:hm="http://www.hancom.co.kr/hwpml/2011/master-page" '
      'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf" xmlns:dc="http://purl.org/dc/elements/1.1/" '
      'xmlns:opf="http://www.idpf.org/2007/opf/" xmlns:ooxmlchart="http://www.hancom.co.kr/hwpml/2016/ooxmlchart" '
      'xmlns:hwpunitchar="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar" xmlns:epub="http://www.idpf.org/2007/ops" '
      'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0"')
LANGS = ['HANGUL', 'LATIN', 'HANJA', 'JAPANESE', 'OTHER', 'SYMBOL', 'USER']
XML_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'


def hu(mm):
    return int(round(mm * HU))


class Hwpx:
    def __init__(self, images, page_border=False):
        self.images = images
        self.char_prs = {}    # (size, bold, underline) → id
        self.para_prs = {}    # (align, line%) → id
        self.border_fills = {}  # (l, r, t, b, bg, line) → id  (1·2번은 기본값)
        self.bin_items = {}   # img key → (item id, bytes, ext, px_w, px_h)
        self.uid = random.randint(1000000, 9000000)
        self.page_border = page_border
        self.cpr(10)
        self.ppr('JUSTIFY', 160)

    def next_id(self):
        self.uid += 1
        return self.uid

    def cpr(self, size=10, bold=False, underline=False):
        key = (float(size), bool(bold), bool(underline))
        return self.char_prs.setdefault(key, len(self.char_prs))

    def ppr(self, align='LEFT', line=130):
        key = (align, int(line))
        return self.para_prs.setdefault(key, len(self.para_prs))

    def bfill(self, l, r, t, b, bg=None, line='SOLID', width='0.12 mm'):
        key = (l, r, t, b, bg, line, width)
        return self.border_fills.setdefault(key, len(self.border_fills) + 3)

    def bin_id(self, key):
        if key not in self.bin_items:
            im = self.images.get(key)
            if not im:
                return None
            self.bin_items[key] = (f'image{len(self.bin_items) + 1}',) + im
        return self.bin_items[key][0]

    # ── 본문 요소 ──
    def pic(self, key, w_mm, h_mm, inline=True):
        ref = self.bin_id(key)
        if not ref:
            return ''
        _, _, _, pw, ph = self.bin_items[key]
        W, H = hu(w_mm), hu(h_mm)
        pos = (f'<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
               f'vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>') if inline else (
               # 글 앞으로 띄워서 문단(=칸) 가운데에 놓는다
               '<hp:pos treatAsChar="0" affectLSpacing="0" flowWithText="0" allowOverlap="1" holdAnchorAndSO="0" '
               'vertRelTo="PARA" horzRelTo="PARA" vertAlign="CENTER" horzAlign="CENTER" vertOffset="0" horzOffset="0"/>')
        wrap = 'TOP_AND_BOTTOM' if inline else 'IN_FRONT_OF_TEXT'
        return (f'<hp:pic id="{self.next_id()}" zOrder="{self.next_id() % 1000}" numberingType="PICTURE" textWrap="{wrap}" '
                f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0" instid="{self.next_id()}" reverse="0">'
                f'<hp:offset x="0" y="0"/><hp:orgSz width="{W}" height="{H}"/><hp:curSz width="{W}" height="{H}"/>'
                f'<hp:flip horizontal="0" vertical="0"/><hp:rotationInfo angle="0" centerX="{W // 2}" centerY="{H // 2}" rotateimage="1"/>'
                f'<hp:renderingInfo><hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
                f'<hc:scaMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/><hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/></hp:renderingInfo>'
                f'<hc:img binaryItemIDRef="{ref}" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>'
                f'<hp:imgRect><hc:pt0 x="0" y="0"/><hc:pt1 x="{W}" y="0"/><hc:pt2 x="{W}" y="{H}"/><hc:pt3 x="0" y="{H}"/></hp:imgRect>'
                f'<hp:imgClip left="0" right="{pw * 75}" top="0" bottom="{ph * 75}"/><hp:inMargin left="0" right="0" top="0" bottom="0"/>'
                f'<hp:imgDim dimwidth="{pw * 75}" dimheight="{ph * 75}"/><hp:effects/>'
                f'<hp:sz width="{W}" widthRelTo="ABSOLUTE" height="{H}" heightRelTo="ABSOLUTE" protect="0"/>{pos}'
                f'<hp:outMargin left="0" right="0" top="0" bottom="0"/></hp:pic>')

    def para(self, text, size=10, bold=False, underline=False, align='LEFT', line=130, extra='', page_break=False):
        run = f'<hp:t>{escape(text)}</hp:t>' if text else ''
        return (f'<hp:p id="2147483648" paraPrIDRef="{self.ppr(align, line)}" styleIDRef="0" pageBreak="{1 if page_break else 0}" '
                f'columnBreak="0" merged="0"><hp:run charPrIDRef="{self.cpr(size, bold, underline)}">{run}{extra}</hp:run></hp:p>')

    def table(self, t, page_break=False):
        widths, rows = t['widths'], t['rows']
        xs = [0.0]
        for w in widths:
            xs.append(xs[-1] + w)
        heights = [h for h, _ in rows]
        tcs = {r: [] for r in range(len(rows))}
        for r, c, cell in place_cells(rows):
            cs, rs = cell.get('cs', 1), cell.get('rs', 1)
            cw, ch = xs[c + cs] - xs[c], sum(heights[r:r + rs])
            l, rr, tt, bb = cell_borders(cell, t['border'])
            bf = self.bfill(l, rr, tt, bb, cell.get('bg'))
            size, bold, align = cell.get('size', 10), cell.get('bold', False), cell.get('align', 'LEFT')
            line = int(cell.get('line', 1.3) * 100)
            lines = cell_text(cell).split('\n')
            paras = []
            for i, ln in enumerate(lines):
                extra = self.pic(('stamp',), STAMP, STAMP, inline=False) if cell.get('stamp') and i == 0 else ''
                paras.append(self.para(ln, size, bold, False, align, line, extra))
            if cell.get('img'):
                key = cell['img']
                paras = [self.para('', size, False, False, align, 100, self.pic(key, key[-2], key[-1]))]
            valign = {'TOP': 'TOP', 'BOTTOM': 'BOTTOM'}.get(cell.get('valign'), 'CENTER')
            pad_lr = 0.4 if cell.get('img') else 1.5
            tcs[r].append(
                f'<hp:tc name="" header="0" hasMargin="1" protect="0" editable="0" dirty="0" borderFillIDRef="{bf}">'
                f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="{valign}" linkListIDRef="0" '
                f'linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">{"".join(paras)}</hp:subList>'
                f'<hp:cellAddr colAddr="{c}" rowAddr="{r}"/><hp:cellSpan colSpan="{cs}" rowSpan="{rs}"/>'
                f'<hp:cellSz width="{hu(cw)}" height="{hu(ch)}"/>'
                f'<hp:cellMargin left="{hu(pad_lr)}" right="{hu(pad_lr)}" top="{hu(0.4)}" bottom="{hu(0.4)}"/></hp:tc>')
        trs = ''.join(f'<hp:tr>{"".join(tcs[r])}</hp:tr>' for r in range(len(rows)))
        tbl = (f'<hp:tbl id="{self.next_id()}" zOrder="{self.next_id() % 1000}" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" '
               f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL" repeatHeader="0" rowCnt="{len(rows)}" '
               f'colCnt="{len(widths)}" cellSpacing="0" borderFillIDRef="{self.bfill(0, 0, 0, 0)}" noAdjust="0">'
               f'<hp:sz width="{hu(xs[-1])}" widthRelTo="ABSOLUTE" height="{hu(sum(heights))}" heightRelTo="ABSOLUTE" protect="0"/>'
               f'<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" '
               f'horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
               f'<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
               f'<hp:inMargin left="{hu(1.5)}" right="{hu(1.5)}" top="{hu(0.4)}" bottom="{hu(0.4)}"/>{trs}</hp:tbl>')
        return (f'<hp:p id="2147483648" paraPrIDRef="{self.ppr("LEFT", 100)}" styleIDRef="0" pageBreak="{1 if page_break else 0}" '
                f'columnBreak="0" merged="0"><hp:run charPrIDRef="{self.cpr(1)}">{tbl}<hp:t/></hp:run></hp:p>')

    def body(self, blocks):
        out, brk = [], False
        for kind, *rest in blocks:
            if kind == 'br':
                brk = True
                continue
            if kind == 's':
                # 빈 줄 하나로 여백 (줄 높이 ≈ 글자 크기)
                out.append(self.para('', max(1, rest[0] / 0.3528), line=100, page_break=brk))
            elif kind == 'p':
                p = rest[0]
                out.append(self.para(p['text'], p.get('size', 10), p.get('bold', False), p.get('underline', False),
                                     p.get('align', 'LEFT'), 130, page_break=brk))
            elif kind == 't':
                out.append(self.table(rest[0], page_break=brk))
            brk = False
        return out

    # ── 패키지 ──
    def sec_pr(self):
        pbf = self.bfill(1, 1, 1, 1, None, 'DOUBLE_SLIM', '0.7 mm') if self.page_border else 1
        pbf_xml = ''.join(
            f'<hp:pageBorderFill type="{t}" borderFillIDRef="{pbf}" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER">'
            f'<hp:offset left="{hu(7)}" right="{hu(7)}" top="{hu(7)}" bottom="{hu(7)}"/></hp:pageBorderFill>' for t in ('BOTH', 'EVEN', 'ODD'))
        return ('<hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000" tabStopVal="4000" tabStopUnit="HWPUNIT" '
                'outlineShapeIDRef="1" memoShapeIDRef="0" textVerticalWidthHead="0" masterPageCnt="0">'
                '<hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0"/><hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>'
                '<hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0" border="SHOW_ALL" fill="SHOW_ALL" '
                'hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/>'
                '<hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/>'
                f'<hp:pagePr landscape="WIDELY" width="59528" height="84186" gutterType="LEFT_ONLY">'
                f'<hp:margin header="0" footer="0" gutter="0" left="{hu(15)}" right="{hu(15)}" top="{hu(14)}" bottom="{hu(10)}"/></hp:pagePr>'
                '<hp:footNotePr><hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/>'
                '<hp:noteLine length="-1" type="SOLID" width="0.12 mm" color="#000000"/><hp:noteSpacing betweenNotes="283" belowLine="567" aboveLine="850"/>'
                '<hp:numbering type="CONTINUOUS" newNum="1"/><hp:placement place="EACH_COLUMN" beneathText="0"/></hp:footNotePr>'
                '<hp:endNotePr><hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/>'
                '<hp:noteLine length="14692344" type="SOLID" width="0.12 mm" color="#000000"/><hp:noteSpacing betweenNotes="0" belowLine="567" aboveLine="850"/>'
                '<hp:numbering type="CONTINUOUS" newNum="1"/><hp:placement place="END_OF_DOCUMENT" beneathText="0"/></hp:endNotePr>'
                f'{pbf_xml}</hp:secPr>')

    def header_xml(self):
        font = ('<hh:font id="0" face="함초롬돋움" type="TTF" isEmbedded="0"><hh:typeInfo familyType="FCAT_GOTHIC" weight="6" '
                'proportion="4" contrast="0" strokeVariation="1" armStyle="1" letterform="1" midline="1" xHeight="1"/></hh:font>')
        fontfaces = ''.join(f'<hh:fontface lang="{lg}" fontCnt="1">{font}</hh:fontface>' for lg in LANGS)

        def bf_xml(i, l, r, t, b, bg, line='SOLID', width='0.12 mm'):
            side = lambda on: f'type="{line if on else "NONE"}" width="{width if on else "0.1 mm"}" color="#000000"'
            fill = (f'<hc:fillBrush><hc:winBrush faceColor="{bg}" hatchColor="#999999" alpha="0"/></hc:fillBrush>' if bg else '')
            return (f'<hh:borderFill id="{i}" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">'
                    '<hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
                    f'<hh:leftBorder {side(l)}/><hh:rightBorder {side(r)}/><hh:topBorder {side(t)}/><hh:bottomBorder {side(b)}/>'
                    f'<hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>{fill}</hh:borderFill>')
        fills = [bf_xml(1, 0, 0, 0, 0, None), bf_xml(2, 0, 0, 0, 0, None)]
        fills += [bf_xml(i, *k) for k, i in sorted(self.border_fills.items(), key=lambda x: x[1])]

        attrs7 = lambda v: ' '.join(f'{lg.lower()}="{v}"' for lg in LANGS)
        chars = []
        for (size, bold, underline), i in sorted(self.char_prs.items(), key=lambda x: x[1]):
            chars.append(f'<hh:charPr id="{i}" height="{int(size * 100)}" textColor="#000000" shadeColor="none" useFontSpace="0" '
                         f'useKerning="0" symMark="NONE" borderFillIDRef="2"><hh:fontRef {attrs7(0)}/><hh:ratio {attrs7(100)}/>'
                         f'<hh:spacing {attrs7(0)}/><hh:relSz {attrs7(100)}/><hh:offset {attrs7(0)}/>{"<hh:bold/>" if bold else ""}'
                         f'<hh:underline type="{"BOTTOM" if underline else "NONE"}" shape="SOLID" color="#000000"/>'
                         '<hh:strikeout shape="NONE" color="#000000"/><hh:outline type="NONE"/>'
                         '<hh:shadow type="NONE" color="#C0C0C0" offsetX="10" offsetY="10"/></hh:charPr>')
        margin = ('<hh:margin><hc:intent value="0" unit="HWPUNIT"/><hc:left value="0" unit="HWPUNIT"/><hc:right value="0" unit="HWPUNIT"/>'
                  '<hc:prev value="0" unit="HWPUNIT"/><hc:next value="0" unit="HWPUNIT"/></hh:margin>')
        paras = []
        for (align, line), i in sorted(self.para_prs.items(), key=lambda x: x[1]):
            sp = f'{margin}<hh:lineSpacing type="PERCENT" value="{line}" unit="HWPUNIT"/>'
            paras.append(f'<hh:paraPr id="{i}" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="0" suppressLineNumbers="0" checked="0">'
                         f'<hh:align horizontal="{align}" vertical="BASELINE"/><hh:heading type="NONE" idRef="0" level="0"/>'
                         '<hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD" widowOrphan="0" keepWithNext="0" '
                         'keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/><hh:autoSpacing eAsianEng="0" eAsianNum="0"/>'
                         f'<hp:switch><hp:case hp:required-namespace="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar">{sp}</hp:case>'
                         f'<hp:default>{sp}</hp:default></hp:switch>'
                         '<hh:border borderFillIDRef="2" offsetLeft="0" offsetRight="0" offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/>'
                         '</hh:paraPr>')
        return (f'{XML_HEAD}<hh:head {NS} version="1.4" secCnt="1">'
                '<hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/><hh:refList>'
                f'<hh:fontfaces itemCnt="{len(LANGS)}">{fontfaces}</hh:fontfaces>'
                f'<hh:borderFills itemCnt="{len(fills)}">{"".join(fills)}</hh:borderFills>'
                f'<hh:charProperties itemCnt="{len(chars)}">{"".join(chars)}</hh:charProperties>'
                '<hh:tabProperties itemCnt="1"><hh:tabPr id="0" autoTabLeft="0" autoTabRight="0"/></hh:tabProperties>'
                f'<hh:paraProperties itemCnt="{len(paras)}">{"".join(paras)}</hh:paraProperties>'
                '<hh:styles itemCnt="1"><hh:style id="0" type="PARA" name="바탕글" engName="Normal" paraPrIDRef="0" charPrIDRef="0" '
                'nextStyleIDRef="0" langID="1042" lockForm="0"/></hh:styles>'
                '</hh:refList><hh:compatibleDocument targetProgram="HWP201X"><hh:layoutCompatibility/></hh:compatibleDocument>'
                '<hh:docOption><hh:linkinfo path="" pageInherit="0" footnoteInherit="0"/></hh:docOption>'
                '<hh:trackchageConfig flags="56"/></hh:head>')

    def build(self, blocks, title):
        paras = self.body(blocks)
        # 첫 문단에 구역 설정(용지 · 여백 · 쪽 테두리)을 넣는다
        first = (f'<hp:p id="2147483648" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
                 f'<hp:run charPrIDRef="{self.cpr(1)}">{self.sec_pr()}<hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" '
                 'colCount="1" sameSz="1" sameGap="0"/></hp:ctrl></hp:run></hp:p>')
        section = f'{XML_HEAD}<hs:sec {NS}>{first}{"".join(paras)}</hs:sec>'
        header = self.header_xml()  # 본문을 만든 뒤에 (스타일이 모두 등록된 상태)
        bins = list(self.bin_items.values())
        manifest = ''.join(f'<opf:item id="{b[0]}" href="BinData/{b[0]}.{b[2]}" media-type="image/{"jpeg" if b[2] == "jpg" else "png"}" '
                           'isEmbeded="1"/>' for b in bins)
        hpf = (f'{XML_HEAD}<opf:package {NS} version="" unique-identifier="" id=""><opf:metadata><opf:title>{escape(title)}</opf:title>'
               '<opf:language>ko</opf:language></opf:metadata><opf:manifest>'
               '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
               '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
               f'<opf:item id="settings" href="settings.xml" media-type="application/xml"/>{manifest}</opf:manifest>'
               '<opf:spine><opf:itemref idref="header" linear="yes"/><opf:itemref idref="section0" linear="yes"/></opf:spine></opf:package>')
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr(zipfile.ZipInfo('mimetype'), 'application/hwp+zip', compress_type=zipfile.ZIP_STORED)
            z.writestr('version.xml', f'{XML_HEAD}<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" '
                       'tagetApplication="WORDPROCESSOR" major="5" minor="0" micro="5" buildNumber="0" os="1" xmlVersion="1.4" '
                       'application="Hancom Office Hangul" appVersion="9, 1, 1, 5656 WIN32LEWindows_8"/>')
            z.writestr('META-INF/container.xml', f'{XML_HEAD}<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container" '
                       'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf"><ocf:rootfiles><ocf:rootfile full-path="Contents/content.hpf" '
                       'media-type="application/hwpml-package+xml"/></ocf:rootfiles></ocf:container>')
            z.writestr('META-INF/manifest.xml', f'{XML_HEAD}<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>')
            z.writestr('Contents/content.hpf', hpf)
            z.writestr('Contents/header.xml', header)
            z.writestr('Contents/section0.xml', section)
            z.writestr('settings.xml', f'{XML_HEAD}<ha:HWPApplicationSetting xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
                       'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0"><ha:CaretPosition listIDRef="0" paraIDRef="0" pos="0"/>'
                       '</ha:HWPApplicationSetting>')
            for item_id, data, ext, _, _ in bins:
                z.writestr(f'BinData/{item_id}.{ext}', data)
        return buf.getvalue()


def render_hwpx(blocks, images, title, page_border=False):
    return Hwpx(images, page_border).build(blocks, title)
