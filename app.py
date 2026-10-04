from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
from PIL import Image, ImageOps
import sqlite3, os, uuid, io, json
from datetime import datetime
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='static')
CORS(app)

# Railway는 DATA_DIR 환경변수로 볼륨 경로를 지정, 로컬은 'data' 사용
DATA_DIR  = os.environ.get('DATA_DIR', 'data')
DB_PATH   = os.path.join(DATA_DIR, 'service.db')
PHOTO_DIR = os.path.join(DATA_DIR, 'photos')
THUMB_DIR = os.path.join(DATA_DIR, 'thumbs')
ALLOWED_EXT = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.webp'}

os.makedirs(PHOTO_DIR, exist_ok=True)
os.makedirs(THUMB_DIR, exist_ok=True)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS memos (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sites (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            address TEXT,
            contact_name TEXT,
            contact_phone TEXT,
            memo TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS visits (
            id TEXT PRIMARY KEY,
            site_id TEXT NOT NULL,
            visit_date TEXT NOT NULL,
            work_content TEXT,
            engineer TEXT,
            status TEXT DEFAULT 'completed',
            memo TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS photos (
            id TEXT PRIMARY KEY,
            site_id TEXT,
            visit_id TEXT,
            schedule_id TEXT,
            filename TEXT NOT NULL,
            caption TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE,
            FOREIGN KEY (visit_id) REFERENCES visits(id) ON DELETE SET NULL,
            FOREIGN KEY (schedule_id) REFERENCES schedules(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS schedules (
            id TEXT PRIMARY KEY,
            site_id TEXT,
            title TEXT NOT NULL,
            scheduled_date TEXT NOT NULL,
            scheduled_time TEXT,
            memo TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE SET NULL
        );

        -- 방송팀·찬양팀 소통 (/band)
        CREATE TABLE IF NOT EXISTS band_songs (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            folder TEXT DEFAULT '기본',
            memo TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS band_song_pages (
            id TEXT PRIMARY KEY,
            song_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            page_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (song_id) REFERENCES band_songs(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS band_setlists (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            setlist_date TEXT,
            memo TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS band_setlist_songs (
            id TEXT PRIMARY KEY,
            setlist_id TEXT NOT NULL,
            song_id TEXT NOT NULL,
            position INTEGER DEFAULT 0,
            note TEXT,
            FOREIGN KEY (setlist_id) REFERENCES band_setlists(id) ON DELETE CASCADE,
            FOREIGN KEY (song_id) REFERENCES band_songs(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS band_requests (
            id TEXT PRIMARY KEY,
            sender TEXT,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            done_at TEXT
        );
        CREATE TABLE IF NOT EXISTS band_notes (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- 실시간 인도(따라가기): 인도자가 넘기는 위치를 공유
        CREATE TABLE IF NOT EXISTS band_live (
            id TEXT PRIMARY KEY,
            setlist_id TEXT,
            song_index INTEGER DEFAULT 0,
            page_index INTEGER DEFAULT 0,
            leader TEXT,
            active INTEGER DEFAULT 0,
            updated_at TEXT
        );

        -- 악보 필기/주석 (인도자가 쓴 표시를 공유). 페이지당 1행, data=선(stroke) JSON
        CREATE TABLE IF NOT EXISTS band_annotations (
            page_id TEXT PRIMARY KEY,
            data TEXT,
            updated_at TEXT
        );

        -- 빠른 요청 버튼 프리셋 (팀이 함께 수정)
        CREATE TABLE IF NOT EXISTS band_quick_presets (
            id TEXT PRIMARY KEY,
            emoji TEXT,
            text TEXT NOT NULL,
            position INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            doc_type TEXT NOT NULL,
            doc_no TEXT,
            site_id TEXT,
            title TEXT,
            client_name TEXT,
            doc_date TEXT,
            supply_amount INTEGER DEFAULT 0,
            tax_amount INTEGER DEFAULT 0,
            data TEXT,
            source_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS price_items (
            id TEXT PRIMARY KEY,
            category TEXT,
            model TEXT NOT NULL,
            unit TEXT DEFAULT 'EA',
            cost_price INTEGER,
            price INTEGER,
            memo TEXT,
            source TEXT DEFAULT 'manual'
        );
    ''')
    conn.commit()
    conn.close()


init_db()

# 기존 DB 마이그레이션
def migrate_db():
    conn = get_db()
    photo_cols = [r[1] for r in conn.execute("PRAGMA table_info(photos)").fetchall()]
    if 'schedule_id' not in photo_cols:
        conn.execute("ALTER TABLE photos ADD COLUMN schedule_id TEXT")
    visit_cols = [r[1] for r in conn.execute("PRAGMA table_info(visits)").fetchall()]
    if 'schedule_id' not in visit_cols:
        conn.execute("ALTER TABLE visits ADD COLUMN schedule_id TEXT")
    conn.commit()
    conn.close()

migrate_db()


def make_thumb(src_path, thumb_path, size=(400, 400)):
    try:
        img = Image.open(src_path)
        img = img.convert('RGB')
        img.thumbnail(size, Image.LANCZOS)
        img.save(thumb_path, 'JPEG', quality=75)
    except Exception:
        pass


# ── Sites ─────────────────────────────────────────────────────────────────────

@app.route('/api/sites', methods=['GET'])
def get_sites():
    q = request.args.get('q', '').strip()
    conn = get_db()
    if q:
        rows = conn.execute(
            'SELECT * FROM sites WHERE name LIKE ? OR address LIKE ? ORDER BY name',
            (f'%{q}%', f'%{q}%')
        ).fetchall()
    else:
        rows = conn.execute('SELECT * FROM sites ORDER BY name').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/sites', methods=['POST'])
def create_site():
    d = request.json
    if not d.get('name', '').strip():
        return jsonify({'error': '현장명을 입력하세요'}), 400
    sid = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        'INSERT INTO sites (id,name,address,contact_name,contact_phone,memo) VALUES (?,?,?,?,?,?)',
        (sid, d['name'].strip(), d.get('address'), d.get('contact_name'), d.get('contact_phone'), d.get('memo'))
    )
    conn.commit()
    row = conn.execute('SELECT * FROM sites WHERE id=?', (sid,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201


@app.route('/api/sites/<sid>', methods=['GET'])
def get_site(sid):
    conn = get_db()
    row = conn.execute('SELECT * FROM sites WHERE id=?', (sid,)).fetchone()
    conn.close()
    return jsonify(dict(row)) if row else ('', 404)


@app.route('/api/sites/<sid>', methods=['PUT'])
def update_site(sid):
    d = request.json
    conn = get_db()
    conn.execute(
        'UPDATE sites SET name=?,address=?,contact_name=?,contact_phone=?,memo=? WHERE id=?',
        (d['name'], d.get('address'), d.get('contact_name'), d.get('contact_phone'), d.get('memo'), sid)
    )
    conn.commit()
    row = conn.execute('SELECT * FROM sites WHERE id=?', (sid,)).fetchone()
    conn.close()
    return jsonify(dict(row))


@app.route('/api/sites/<sid>', methods=['DELETE'])
def delete_site(sid):
    conn = get_db()
    conn.execute('DELETE FROM sites WHERE id=?', (sid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


# ── Visits ────────────────────────────────────────────────────────────────────

@app.route('/api/sites/<sid>/visits', methods=['GET'])
def get_visits(sid):
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM visits WHERE site_id=? ORDER BY visit_date DESC', (sid,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/visits', methods=['GET'])
def all_visits():
    conn = get_db()
    rows = conn.execute('''
        SELECT v.*, s.name site_name FROM visits v
        LEFT JOIN sites s ON v.site_id=s.id
        ORDER BY v.visit_date DESC LIMIT 50
    ''').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/sites/<sid>/visits', methods=['POST'])
def create_visit(sid):
    d = request.json
    if not d.get('visit_date', '').strip():
        return jsonify({'error': '날짜를 입력하세요'}), 400
    vid = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        'INSERT INTO visits (id,site_id,visit_date,work_content,engineer,status,memo) VALUES (?,?,?,?,?,?,?)',
        (vid, sid, d['visit_date'], d.get('work_content'), d.get('engineer'), d.get('status', 'completed'), d.get('memo'))
    )
    conn.commit()
    row = conn.execute('SELECT * FROM visits WHERE id=?', (vid,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201


@app.route('/api/visits/<vid>', methods=['PUT'])
def update_visit(vid):
    d = request.json
    conn = get_db()
    conn.execute(
        'UPDATE visits SET visit_date=?,work_content=?,engineer=?,status=?,memo=? WHERE id=?',
        (d['visit_date'], d.get('work_content'), d.get('engineer'), d.get('status', 'completed'), d.get('memo'), vid)
    )
    conn.commit()
    row = conn.execute('SELECT * FROM visits WHERE id=?', (vid,)).fetchone()
    conn.close()
    return jsonify(dict(row))


@app.route('/api/visits/<vid>', methods=['DELETE'])
def delete_visit(vid):
    conn = get_db()
    conn.execute('DELETE FROM visits WHERE id=?', (vid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


# ── Photos ────────────────────────────────────────────────────────────────────

@app.route('/api/sites/<sid>/photos', methods=['GET'])
def get_photos(sid):
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM photos WHERE site_id=? ORDER BY created_at DESC', (sid,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/sites/<sid>/photos', methods=['POST'])
def upload_photo(sid):
    if 'photo' not in request.files:
        return jsonify({'error': 'No file'}), 400
    pid, filename = save_photo_file(request.files['photo'], sid)
    if not pid:
        return jsonify({'error': filename}), 400
    conn = get_db()
    conn.execute(
        'INSERT INTO photos (id,site_id,visit_id,filename,caption) VALUES (?,?,?,?,?)',
        (pid, sid, request.form.get('visit_id'), filename, request.form.get('caption', ''))
    )
    conn.commit()
    row = conn.execute('SELECT * FROM photos WHERE id=?', (pid,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201


def save_photo_file(f, folder_key):
    ext = os.path.splitext(secure_filename(f.filename or 'photo.jpg'))[1].lower() or '.jpg'
    if ext not in ALLOWED_EXT:
        return None, 'Invalid file type'
    pid = str(uuid.uuid4())
    filename = f'{pid}.jpg'
    photo_dir = os.path.join(PHOTO_DIR, folder_key)
    thumb_dir = os.path.join(THUMB_DIR, folder_key)
    os.makedirs(photo_dir, exist_ok=True)
    os.makedirs(thumb_dir, exist_ok=True)
    raw = f.read()
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)  # 아이폰 EXIF 회전 방향 보정
        img = img.convert('RGB')
        img.save(os.path.join(photo_dir, filename), 'JPEG', quality=85)
        img.thumbnail((400, 400), Image.LANCZOS)
        img.save(os.path.join(thumb_dir, filename), 'JPEG', quality=70)
    except Exception:
        with open(os.path.join(photo_dir, filename), 'wb') as fh:
            fh.write(raw)
    return pid, filename


@app.route('/api/photo/<folder>/<filename>')
def serve_photo(folder, filename):
    return send_from_directory(os.path.join(PHOTO_DIR, folder), filename)


@app.route('/api/thumb/<folder>/<filename>')
def serve_thumb(folder, filename):
    thumb_path = os.path.join(THUMB_DIR, folder, filename)
    if os.path.exists(thumb_path):
        return send_from_directory(os.path.join(THUMB_DIR, folder), filename)
    return send_from_directory(os.path.join(PHOTO_DIR, folder), filename)


@app.route('/api/photos/<pid>', methods=['DELETE'])
def delete_photo(pid):
    conn = get_db()
    row = conn.execute('SELECT * FROM photos WHERE id=?', (pid,)).fetchone()
    if row:
        folder = row['site_id'] or row['schedule_id']
        if folder:
            for d in [PHOTO_DIR, THUMB_DIR]:
                p = os.path.join(d, folder, row['filename'])
                if os.path.exists(p):
                    os.remove(p)
        conn.execute('DELETE FROM photos WHERE id=?', (pid,))
        conn.commit()
    conn.close()
    return jsonify({'ok': True})


# ── Schedule Photos ───────────────────────────────────────────────────────────

@app.route('/api/schedules/<scid>/photos', methods=['GET'])
def get_schedule_photos(scid):
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM photos WHERE schedule_id=? ORDER BY created_at DESC', (scid,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/schedules/<scid>/photos', methods=['POST'])
def upload_schedule_photo(scid):
    if 'photo' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f = request.files['photo']
    pid, filename = save_photo_file(f, scid)
    if not pid:
        return jsonify({'error': filename}), 400
    conn = get_db()
    conn.execute(
        'INSERT INTO photos (id,site_id,schedule_id,filename,caption) VALUES (?,?,?,?,?)',
        (pid, None, scid, filename, request.form.get('caption', ''))
    )
    conn.commit()
    row = conn.execute('SELECT * FROM photos WHERE id=?', (pid,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201


# ── Schedules ─────────────────────────────────────────────────────────────────

@app.route('/api/schedules', methods=['GET'])
def get_schedules():
    month = request.args.get('month')
    pending_only = request.args.get('pending') == '1'
    conn = get_db()
    if pending_only:
        # 완료되지 않은 모든 일정 (날짜 무관)
        rows = conn.execute('''
            SELECT sc.*, s.name site_name FROM schedules sc
            LEFT JOIN sites s ON sc.site_id=s.id
            WHERE sc.status != 'completed'
            ORDER BY sc.scheduled_date, sc.scheduled_time
        ''').fetchall()
    elif month:
        rows = conn.execute('''
            SELECT sc.*, s.name site_name FROM schedules sc
            LEFT JOIN sites s ON sc.site_id=s.id
            WHERE sc.scheduled_date LIKE ? OR sc.scheduled_date IS NULL
            ORDER BY sc.scheduled_date, sc.scheduled_time
        ''', (f'{month}%',)).fetchall()
    else:
        rows = conn.execute('''
            SELECT sc.*, s.name site_name FROM schedules sc
            LEFT JOIN sites s ON sc.site_id=s.id
            ORDER BY sc.scheduled_date, sc.scheduled_time
        ''').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/schedules', methods=['POST'])
def create_schedule():
    d = request.json
    if not d.get('title', '').strip():
        return jsonify({'error': '제목을 입력하세요'}), 400
    scid = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        'INSERT INTO schedules (id,site_id,title,scheduled_date,scheduled_time,memo) VALUES (?,?,?,?,?,?)',
        (scid, d.get('site_id'), d['title'], d.get('scheduled_date') or None, d.get('scheduled_time'), d.get('memo'))
    )
    conn.commit()
    row = conn.execute('SELECT sc.*, s.name site_name FROM schedules sc LEFT JOIN sites s ON sc.site_id=s.id WHERE sc.id=?', (scid,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201


@app.route('/api/schedules/<scid>', methods=['PUT'])
def update_schedule(scid):
    d = request.json
    conn = get_db()
    conn.execute(
        'UPDATE schedules SET site_id=?,title=?,scheduled_date=?,scheduled_time=?,memo=?,status=? WHERE id=?',
        (d.get('site_id'), d['title'], d['scheduled_date'], d.get('scheduled_time'), d.get('memo'), d.get('status', 'pending'), scid)
    )
    conn.commit()
    row = conn.execute('SELECT sc.*, s.name site_name FROM schedules sc LEFT JOIN sites s ON sc.site_id=s.id WHERE sc.id=?', (scid,)).fetchone()
    conn.close()
    return jsonify(dict(row))


@app.route('/api/schedules/<scid>', methods=['DELETE'])
def delete_schedule(scid):
    conn = get_db()
    conn.execute('DELETE FROM schedules WHERE id=?', (scid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/schedules/<scid>/complete', methods=['POST'])
def complete_schedule(scid):
    """일정 완료 처리 + 현장이 있으면 방문기록 자동 생성 + 사진 이동"""
    conn = get_db()
    sched = conn.execute('SELECT * FROM schedules WHERE id=?', (scid,)).fetchone()
    if not sched:
        conn.close()
        return jsonify({'error': 'Not found'}), 404

    # 일정 완료 처리
    conn.execute("UPDATE schedules SET status='completed' WHERE id=?", (scid,))

    visit = None
    if sched['site_id']:
        # 이미 이 일정으로 생성된 방문기록이 있으면 재사용 (중복 방지)
        existing = conn.execute(
            'SELECT * FROM visits WHERE schedule_id=?', (scid,)
        ).fetchone()
        if existing:
            conn.commit()
            conn.close()
            return jsonify({'ok': True, 'visit': dict(existing)})

        # 방문기록 자동 생성
        vid = str(uuid.uuid4())
        work = sched['title']
        if sched['memo']:
            work += '\n' + sched['memo']
        conn.execute(
            'INSERT INTO visits (id,site_id,visit_date,work_content,status,schedule_id) VALUES (?,?,?,?,?,?)',
            (vid, sched['site_id'], sched['scheduled_date'], work, 'completed', scid)
        )

        # 일정 사진 → 방문기록으로 이동 (파일도 site 폴더로 이동)
        photos = conn.execute(
            'SELECT * FROM photos WHERE schedule_id=?', (scid,)
        ).fetchall()

        for p in photos:
            old_dir = os.path.join(PHOTO_DIR, scid)
            new_dir = os.path.join(PHOTO_DIR, sched['site_id'])
            old_thumb = os.path.join(THUMB_DIR, scid)
            new_thumb = os.path.join(THUMB_DIR, sched['site_id'])
            os.makedirs(new_dir, exist_ok=True)
            os.makedirs(new_thumb, exist_ok=True)

            old_f = os.path.join(old_dir, p['filename'])
            new_f = os.path.join(new_dir, p['filename'])
            if os.path.exists(old_f):
                import shutil
                shutil.move(old_f, new_f)

            old_t = os.path.join(old_thumb, p['filename'])
            new_t = os.path.join(new_thumb, p['filename'])
            if os.path.exists(old_t):
                import shutil
                shutil.move(old_t, new_t)

            conn.execute(
                'UPDATE photos SET site_id=?, visit_id=? WHERE id=?',
                (sched['site_id'], vid, p['id'])
            )

        conn.commit()
        visit = dict(conn.execute('SELECT * FROM visits WHERE id=?', (vid,)).fetchone())

    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'visit': visit})


# ── Memos ─────────────────────────────────────────────────────────────────────

@app.route('/api/memos', methods=['GET'])
def get_memos():
    conn = get_db()
    rows = conn.execute('SELECT * FROM memos ORDER BY updated_at DESC').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/memos', methods=['POST'])
def create_memo():
    d = request.json
    if not d.get('title', '').strip():
        return jsonify({'error': '제목을 입력하세요'}), 400
    mid = str(uuid.uuid4())
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    conn.execute('INSERT INTO memos (id,title,content,created_at,updated_at) VALUES (?,?,?,?,?)',
        (mid, d['title'].strip(), d.get('content',''), now, now))
    conn.commit()
    row = conn.execute('SELECT * FROM memos WHERE id=?', (mid,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201

@app.route('/api/memos/<mid>', methods=['PUT'])
def update_memo(mid):
    d = request.json
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    conn.execute('UPDATE memos SET title=?,content=?,updated_at=? WHERE id=?',
        (d['title'], d.get('content',''), now, mid))
    conn.commit()
    row = conn.execute('SELECT * FROM memos WHERE id=?', (mid,)).fetchone()
    conn.close()
    return jsonify(dict(row))

@app.route('/api/memos/<mid>', methods=['DELETE'])
def delete_memo(mid):
    conn = get_db()
    conn.execute('DELETE FROM memos WHERE id=?', (mid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


# ── Settings (회사 정보 / 직인) ──────────────────────────────────────────────

DEFAULT_COMPANY = {
    'name': '윌로펌프서비스',
    'biz_no': '780-29-01203',
    'ceo': '강한빛',
    'address': '경기도 양주시 부흥로 2061-8 1층 T3호',
    'tel': '031-821-0613',
    'fax': '031-821-0614',
    'mobile': '010-4389-0613',
    'email': 'wilopumpe@naver.com',
    'biz_type': '도소매',
    'biz_item': '그외기타기계장비외',
    'bank': '',
    'quote_note': '작업 중 타 부품의 이상 발생 시 추가 비용 발생할 수 있음.',
}
ASSET_DIR = os.path.join(DATA_DIR, 'assets')
os.makedirs(ASSET_DIR, exist_ok=True)


def load_company(conn):
    row = conn.execute("SELECT value FROM settings WHERE key='company'").fetchone()
    company = dict(DEFAULT_COMPANY)
    if row:
        company.update(json.loads(row['value']))
    company['has_stamp'] = os.path.exists(os.path.join(ASSET_DIR, 'stamp.png'))
    return company


@app.route('/api/settings/company', methods=['GET'])
def get_company():
    conn = get_db()
    company = load_company(conn)
    conn.close()
    return jsonify(company)


@app.route('/api/settings/company', methods=['PUT'])
def update_company():
    d = request.json or {}
    company = {k: (d.get(k) or '').strip() for k in DEFAULT_COMPANY}
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('company',?)",
                 (json.dumps(company, ensure_ascii=False),))
    conn.commit()
    company = load_company(conn)
    conn.close()
    return jsonify(company)


@app.route('/api/settings/stamp', methods=['POST'])
def upload_stamp():
    if 'photo' not in request.files:
        return jsonify({'error': 'No file'}), 400
    try:
        img = Image.open(request.files['photo'].stream)
        img = ImageOps.exif_transpose(img).convert('RGBA')
        img.thumbnail((400, 400), Image.LANCZOS)
        img.save(os.path.join(ASSET_DIR, 'stamp.png'), 'PNG')
    except Exception:
        return jsonify({'error': '이미지를 읽을 수 없습니다'}), 400
    return jsonify({'ok': True})


@app.route('/api/stamp')
def serve_stamp():
    resp = send_from_directory(ASSET_DIR, 'stamp.png')
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


# ── Documents (견적서 / 거래명세서 / 계약서 / 작업완료확인서) ─────────────────

DOC_PREFIX = {'quote': 'Q', 'statement': 'S', 'contract': 'C', 'completion': 'W'}


def doc_row(r):
    d = dict(r)
    d['data'] = json.loads(d['data'] or '{}')
    return d


def next_doc_no(conn, doc_type, doc_date):
    # 예) Q-2610-003 : 유형-연월-순번
    prefix = f"{DOC_PREFIX[doc_type]}-{(doc_date or '')[2:4]}{(doc_date or '')[5:7]}-"
    row = conn.execute('SELECT doc_no FROM documents WHERE doc_no LIKE ? ORDER BY doc_no DESC LIMIT 1',
                       (prefix + '%',)).fetchone()
    seq = int(row['doc_no'].rsplit('-', 1)[1]) + 1 if row else 1
    return f'{prefix}{seq:03d}'


def doc_fields(d):
    return (d.get('site_id') or None, (d.get('title') or '').strip(), (d.get('client_name') or '').strip(),
            d.get('doc_date') or datetime.now().strftime('%Y-%m-%d'),
            int(d.get('supply_amount') or 0), int(d.get('tax_amount') or 0),
            json.dumps(d.get('data') or {}, ensure_ascii=False))


@app.route('/api/documents', methods=['GET'])
def get_documents():
    sql = '''SELECT d.*, s.name site_name FROM documents d
             LEFT JOIN sites s ON d.site_id=s.id WHERE 1=1'''
    args = []
    if request.args.get('type'):
        sql += ' AND d.doc_type=?'
        args.append(request.args['type'])
    if request.args.get('site_id'):
        sql += ' AND d.site_id=?'
        args.append(request.args['site_id'])
    q = request.args.get('q', '').strip()
    if q:
        sql += ' AND (d.title LIKE ? OR d.client_name LIKE ? OR s.name LIKE ? OR d.doc_no LIKE ?)'
        args += [f'%{q}%'] * 4
    sql += ' ORDER BY d.doc_date DESC, d.created_at DESC LIMIT 300'
    conn = get_db()
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return jsonify([doc_row(r) for r in rows])


@app.route('/api/documents', methods=['POST'])
def create_document():
    d = request.json or {}
    if d.get('doc_type') not in DOC_PREFIX:
        return jsonify({'error': '문서 종류가 올바르지 않습니다'}), 400
    did = str(uuid.uuid4())
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    fields = doc_fields(d)
    conn = get_db()
    doc_no = next_doc_no(conn, d['doc_type'], fields[3])
    conn.execute('''INSERT INTO documents (id,doc_type,doc_no,site_id,title,client_name,doc_date,
                    supply_amount,tax_amount,data,source_id,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                 (did, d['doc_type'], doc_no, *fields, d.get('source_id'), now, now))
    conn.commit()
    row = conn.execute('SELECT * FROM documents WHERE id=?', (did,)).fetchone()
    conn.close()
    return jsonify(doc_row(row)), 201


@app.route('/api/documents/<did>', methods=['GET'])
def get_document(did):
    conn = get_db()
    row = conn.execute('''SELECT d.*, s.name site_name FROM documents d
                          LEFT JOIN sites s ON d.site_id=s.id WHERE d.id=?''', (did,)).fetchone()
    company = load_company(conn)
    conn.close()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    doc = doc_row(row)
    doc['company'] = company
    return jsonify(doc)


@app.route('/api/documents/<did>', methods=['PUT'])
def update_document(did):
    d = request.json or {}
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    conn.execute('''UPDATE documents SET site_id=?,title=?,client_name=?,doc_date=?,
                    supply_amount=?,tax_amount=?,data=?,updated_at=? WHERE id=?''',
                 (*doc_fields(d), now, did))
    conn.commit()
    row = conn.execute('SELECT * FROM documents WHERE id=?', (did,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(doc_row(row))


@app.route('/api/documents/<did>', methods=['DELETE'])
def delete_document(did):
    conn = get_db()
    conn.execute('DELETE FROM documents WHERE id=?', (did,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/documents/<did>/export/<fmt>')
def export_document(did, fmt):
    """엑셀(.xlsx) / 한글(.hwpx) 파일로 내려받기"""
    import exports
    if fmt not in ('xlsx', 'hwpx'):
        return jsonify({'error': '지원하지 않는 형식입니다'}), 400
    conn = get_db()
    row = conn.execute('SELECT * FROM documents WHERE id=?', (did,)).fetchone()
    company = load_company(conn)
    conn.close()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    doc = doc_row(row)
    images = exports.Images(PHOTO_DIR, os.path.join(ASSET_DIR, 'stamp.png'),
                            os.path.join(app.static_folder, 'wilo-partner-logo.png'))
    blocks = exports.build_blocks(doc, company)
    name = exports.TYPE_NAME[doc['doc_type']]
    if fmt == 'xlsx':
        data = exports.render_xlsx(blocks, images, name)
        mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else:
        data = exports.render_hwpx(blocks, images, name, page_border=doc['doc_type'] == 'completion')
        mime = 'application/hwp+zip'
    filename = f"{name}_{doc['client_name'] or ''}_{(doc['doc_date'] or '').replace('-', '')}.{fmt}"
    for ch in '\\/:*?"<>|':
        filename = filename.replace(ch, '')
    return send_file(io.BytesIO(data), mimetype=mime, as_attachment=True, download_name=filename)


@app.route('/api/documents/photos', methods=['POST'])
def upload_document_photo():
    """작업완료확인서에 직접 올리는 사진 (현장 사진과 별도 보관)"""
    if 'photo' not in request.files:
        return jsonify({'error': 'No file'}), 400
    pid, filename = save_photo_file(request.files['photo'], 'docs')
    if not pid:
        return jsonify({'error': filename}), 400
    return jsonify({'folder': 'docs', 'filename': filename}), 201


# ── Price items (단가표) ─────────────────────────────────────────────────────

def to_int(v):
    if isinstance(v, (int, float)):
        return int(v)
    try:
        return int(float(str(v).replace(',', '').strip()))
    except (ValueError, TypeError):
        return None


@app.route('/api/price-items', methods=['GET'])
def get_price_items():
    q = request.args.get('q', '').strip()
    conn = get_db()
    if request.args.get('manual'):
        rows = conn.execute("SELECT * FROM price_items WHERE source='manual' ORDER BY model").fetchall()
    elif q:
        rows = conn.execute('''SELECT * FROM price_items WHERE model LIKE ? OR category LIKE ? OR memo LIKE ?
                               ORDER BY source='import', model LIMIT 30''',
                            (f'%{q}%', f'%{q}%', f'%{q}%')).fetchall()
    else:
        rows = conn.execute("SELECT * FROM price_items ORDER BY source='import', category, model").fetchall()
    total = conn.execute('SELECT COUNT(*) FROM price_items').fetchone()[0]
    conn.close()
    return jsonify({'items': [dict(r) for r in rows], 'total': total})


@app.route('/api/price-items', methods=['POST'])
def create_price_item():
    d = request.json or {}
    if not (d.get('model') or '').strip():
        return jsonify({'error': '품목명을 입력하세요'}), 400
    pid = str(uuid.uuid4())
    conn = get_db()
    conn.execute('INSERT INTO price_items (id,category,model,unit,cost_price,price,memo,source) VALUES (?,?,?,?,?,?,?,?)',
                 (pid, d.get('category', ''), d['model'].strip(), d.get('unit') or 'EA',
                  to_int(d.get('cost_price')), to_int(d.get('price')), d.get('memo', ''), 'manual'))
    conn.commit()
    row = conn.execute('SELECT * FROM price_items WHERE id=?', (pid,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201


@app.route('/api/price-items/<pid>', methods=['PUT'])
def update_price_item(pid):
    d = request.json or {}
    conn = get_db()
    conn.execute('UPDATE price_items SET category=?,model=?,unit=?,cost_price=?,price=?,memo=? WHERE id=?',
                 (d.get('category', ''), (d.get('model') or '').strip(), d.get('unit') or 'EA',
                  to_int(d.get('cost_price')), to_int(d.get('price')), d.get('memo', ''), pid))
    conn.commit()
    row = conn.execute('SELECT * FROM price_items WHERE id=?', (pid,)).fetchone()
    conn.close()
    return jsonify(dict(row) if row else {})


@app.route('/api/price-items/<pid>', methods=['DELETE'])
def delete_price_item(pid):
    conn = get_db()
    conn.execute('DELETE FROM price_items WHERE id=?', (pid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


def parse_price_workbook(f):
    """윌로 가격표/단가표 엑셀에서 (분류, 모델명, 물품대, 소비자가) 추출.
    시트마다 '모델명' 헤더를 찾고, 한 행에 표가 여러 개 나란히 있어도 처리한다."""
    import openpyxl
    wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
    items = []
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        header_idx = None
        for i, r in enumerate(rows[:15]):
            if any(isinstance(c, str) and c.replace(' ', '') == '모델명' for c in r):
                header_idx = i
                break
        if header_idx is None:
            continue
        header = [(c or '').replace('\n', '').replace(' ', '') if isinstance(c, str) else '' for c in rows[header_idx]]
        model_cols = [i for i, h in enumerate(header) if h == '모델명']
        blocks = []
        for n, m in enumerate(model_cols):
            end = model_cols[n + 1] if n + 1 < len(model_cols) else len(header)
            start = model_cols[n - 1] + 1 if n else 0
            cost_cols = [i for i in range(m + 1, end) if '물품대' in header[i]]
            price_col = next((i for i in range(m + 1, end) if '소비자가' in header[i]), None)
            kind_col = next((i for i in range(start, m) if header[i] == '기종'), None)
            blocks.append((m, cost_cols[-1] if cost_cols else None, price_col, kind_col))
        title = ws.title.strip()
        for m, cost_col, price_col, kind_col in blocks:
            kind = ''
            for r in rows[header_idx + 1:]:
                if kind_col is not None and kind_col < len(r) and r[kind_col]:
                    kind = ' '.join(str(r[kind_col]).split())
                model = r[m] if m < len(r) else None
                if not isinstance(model, str) or not model.strip():
                    continue
                price = to_int(r[price_col]) if price_col is not None and price_col < len(r) else None
                cost = to_int(r[cost_col]) if cost_col is not None and cost_col < len(r) else None
                if price is None and cost is None:
                    continue
                items.append((kind or title, model.strip(), cost, price))
    return items


@app.route('/api/price-items/import', methods=['POST'])
def import_price_items():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    try:
        items = parse_price_workbook(request.files['file'])
    except Exception:
        return jsonify({'error': '엑셀 파일을 읽을 수 없습니다 (.xlsx만 가능)'}), 400
    if not items:
        return jsonify({'error': "'모델명' 열을 찾지 못했습니다"}), 400
    conn = get_db()
    # 직접 입력한 품목(인건비 등)은 유지하고, 이전에 불러온 단가표만 교체
    conn.execute("DELETE FROM price_items WHERE source='import'")
    conn.executemany("INSERT INTO price_items (id,category,model,unit,cost_price,price,source) VALUES (?,?,?,'EA',?,?,'import')",
                     [(str(uuid.uuid4()), c, m, cost, p) for c, m, cost, p in items])
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'count': len(items)})


# ── Search ────────────────────────────────────────────────────────────────────

@app.route('/api/search')
def search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'sites': [], 'visits': []})
    conn = get_db()
    sites = conn.execute(
        'SELECT * FROM sites WHERE name LIKE ? OR address LIKE ? ORDER BY name LIMIT 20',
        (f'%{q}%', f'%{q}%')
    ).fetchall()
    visits = conn.execute('''
        SELECT v.*, s.name site_name FROM visits v
        LEFT JOIN sites s ON v.site_id=s.id
        WHERE v.work_content LIKE ? OR s.name LIKE ? OR v.engineer LIKE ?
        ORDER BY v.visit_date DESC LIMIT 20
    ''', (f'%{q}%', f'%{q}%', f'%{q}%')).fetchall()
    conn.close()
    return jsonify({'sites': [dict(r) for r in sites], 'visits': [dict(r) for r in visits]})


# ── Band: 방송팀·찬양팀 소통 ──────────────────────────────────────────────────

def song_folder_key(song_id):
    return f'band_{song_id}'


@app.route('/api/band/folders', methods=['GET'])
def band_folders():
    conn = get_db()
    rows = conn.execute('''
        SELECT COALESCE(folder, '기본') folder, COUNT(*) cnt
        FROM band_songs GROUP BY COALESCE(folder, '기본') ORDER BY folder
    ''').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/band/songs', methods=['GET'])
def band_songs():
    folder = request.args.get('folder', '').strip()
    q = request.args.get('q', '').strip()
    conn = get_db()
    sql = '''
        SELECT s.*, COUNT(p.id) page_count,
               (SELECT filename FROM band_song_pages WHERE song_id=s.id ORDER BY page_order LIMIT 1) cover
        FROM band_songs s LEFT JOIN band_song_pages p ON p.song_id=s.id
    '''
    cond, args = [], []
    if folder:
        cond.append("COALESCE(s.folder,'기본')=?")
        args.append(folder)
    if q:
        cond.append('s.title LIKE ?')
        args.append(f'%{q}%')
    if cond:
        sql += ' WHERE ' + ' AND '.join(cond)
    sql += ' GROUP BY s.id ORDER BY s.title'
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/band/songs', methods=['POST'])
def band_create_song():
    title = (request.form.get('title') or '').strip()
    if not title:
        return jsonify({'error': '곡 제목을 입력하세요'}), 400
    song_id = str(uuid.uuid4())
    folder = (request.form.get('folder') or '').strip() or '기본'
    conn = get_db()
    conn.execute(
        'INSERT INTO band_songs (id,title,folder,memo) VALUES (?,?,?,?)',
        (song_id, title, folder, request.form.get('memo'))
    )
    order = 0
    for f in request.files.getlist('pages'):
        pid, filename = save_photo_file(f, song_folder_key(song_id))
        if pid:
            conn.execute(
                'INSERT INTO band_song_pages (id,song_id,filename,page_order) VALUES (?,?,?,?)',
                (pid, song_id, filename, order)
            )
            order += 1
    conn.commit()
    row = conn.execute('SELECT * FROM band_songs WHERE id=?', (song_id,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201


@app.route('/api/band/songs/<song_id>', methods=['GET'])
def band_get_song(song_id):
    conn = get_db()
    row = conn.execute('SELECT * FROM band_songs WHERE id=?', (song_id,)).fetchone()
    if not row:
        conn.close()
        return ('', 404)
    pages = conn.execute(
        'SELECT * FROM band_song_pages WHERE song_id=? ORDER BY page_order', (song_id,)
    ).fetchall()
    conn.close()
    d = dict(row)
    d['pages'] = [dict(p) for p in pages]
    return jsonify(d)


@app.route('/api/band/songs/<song_id>', methods=['PUT'])
def band_update_song(song_id):
    d = request.json
    conn = get_db()
    conn.execute(
        'UPDATE band_songs SET title=?,folder=?,memo=? WHERE id=?',
        (d['title'], (d.get('folder') or '').strip() or '기본', d.get('memo'), song_id)
    )
    conn.commit()
    row = conn.execute('SELECT * FROM band_songs WHERE id=?', (song_id,)).fetchone()
    conn.close()
    return jsonify(dict(row))


@app.route('/api/band/songs/<song_id>', methods=['DELETE'])
def band_delete_song(song_id):
    conn = get_db()
    pages = conn.execute('SELECT filename FROM band_song_pages WHERE song_id=?', (song_id,)).fetchall()
    for p in pages:
        for d in [PHOTO_DIR, THUMB_DIR]:
            path = os.path.join(d, song_folder_key(song_id), p['filename'])
            if os.path.exists(path):
                os.remove(path)
    page_ids = [p['id'] for p in conn.execute('SELECT id FROM band_song_pages WHERE song_id=?', (song_id,)).fetchall()]
    for pid in page_ids:
        conn.execute('DELETE FROM band_annotations WHERE page_id=?', (pid,))
    conn.execute('DELETE FROM band_song_pages WHERE song_id=?', (song_id,))
    conn.execute('DELETE FROM band_setlist_songs WHERE song_id=?', (song_id,))
    conn.execute('DELETE FROM band_songs WHERE id=?', (song_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/band/songs/<song_id>/pages', methods=['POST'])
def band_add_pages(song_id):
    conn = get_db()
    if not conn.execute('SELECT 1 FROM band_songs WHERE id=?', (song_id,)).fetchone():
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    start = conn.execute(
        'SELECT COALESCE(MAX(page_order)+1,0) FROM band_song_pages WHERE song_id=?', (song_id,)
    ).fetchone()[0]
    added = []
    for i, f in enumerate(request.files.getlist('pages')):
        pid, filename = save_photo_file(f, song_folder_key(song_id))
        if pid:
            conn.execute(
                'INSERT INTO band_song_pages (id,song_id,filename,page_order) VALUES (?,?,?,?)',
                (pid, song_id, filename, start + i)
            )
            added.append(pid)
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'added': len(added)}), 201


@app.route('/api/band/pages/<pid>', methods=['DELETE'])
def band_delete_page(pid):
    conn = get_db()
    row = conn.execute('SELECT * FROM band_song_pages WHERE id=?', (pid,)).fetchone()
    if row:
        for d in [PHOTO_DIR, THUMB_DIR]:
            path = os.path.join(d, song_folder_key(row['song_id']), row['filename'])
            if os.path.exists(path):
                os.remove(path)
        conn.execute('DELETE FROM band_song_pages WHERE id=?', (pid,))
        conn.execute('DELETE FROM band_annotations WHERE page_id=?', (pid,))
        conn.commit()
    conn.close()
    return jsonify({'ok': True})


# 악보 필기/주석 (인도자가 쓴 표시를 팀원이 함께 봄)

@app.route('/api/band/songs/<song_id>/annotations', methods=['GET'])
def band_get_annotations(song_id):
    conn = get_db()
    rows = conn.execute('''
        SELECT a.page_id, a.data FROM band_annotations a
        JOIN band_song_pages p ON p.id = a.page_id
        WHERE p.song_id=?
    ''', (song_id,)).fetchall()
    conn.close()
    out = {}
    for r in rows:
        try:
            out[r['page_id']] = json.loads(r['data'] or '[]')
        except (TypeError, ValueError):
            out[r['page_id']] = []
    return jsonify(out)


@app.route('/api/band/pages/<page_id>/annotation', methods=['PUT'])
def band_save_annotation(page_id):
    strokes = (request.json or {}).get('data', [])
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    conn.execute('''
        INSERT INTO band_annotations (page_id, data, updated_at) VALUES (?,?,?)
        ON CONFLICT(page_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
    ''', (page_id, json.dumps(strokes), now))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/band/pages/<page_id>/annotation', methods=['DELETE'])
def band_clear_annotation(page_id):
    conn = get_db()
    conn.execute('DELETE FROM band_annotations WHERE page_id=?', (page_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


# 콘티 (예배/기도회 곡 순서)

@app.route('/api/band/setlists', methods=['GET'])
def band_setlists():
    conn = get_db()
    rows = conn.execute('''
        SELECT sl.*, COUNT(ss.id) song_count FROM band_setlists sl
        LEFT JOIN band_setlist_songs ss ON ss.setlist_id=sl.id
        GROUP BY sl.id
        ORDER BY sl.setlist_date DESC, sl.created_at DESC
    ''').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/band/setlists', methods=['POST'])
def band_create_setlist():
    d = request.json
    if not d.get('title', '').strip():
        return jsonify({'error': '제목을 입력하세요'}), 400
    slid = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        'INSERT INTO band_setlists (id,title,setlist_date,memo) VALUES (?,?,?,?)',
        (slid, d['title'].strip(), d.get('setlist_date'), d.get('memo'))
    )
    conn.commit()
    row = conn.execute('SELECT * FROM band_setlists WHERE id=?', (slid,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201


@app.route('/api/band/setlists/<slid>', methods=['GET'])
def band_get_setlist(slid):
    conn = get_db()
    row = conn.execute('SELECT * FROM band_setlists WHERE id=?', (slid,)).fetchone()
    if not row:
        conn.close()
        return ('', 404)
    songs = conn.execute('''
        SELECT ss.id item_id, ss.position, ss.note, s.id song_id, s.title, s.folder,
               (SELECT COUNT(*) FROM band_song_pages WHERE song_id=s.id) page_count,
               (SELECT filename FROM band_song_pages WHERE song_id=s.id ORDER BY page_order LIMIT 1) cover
        FROM band_setlist_songs ss JOIN band_songs s ON s.id=ss.song_id
        WHERE ss.setlist_id=? ORDER BY ss.position
    ''', (slid,)).fetchall()
    conn.close()
    d = dict(row)
    d['songs'] = [dict(s) for s in songs]
    return jsonify(d)


@app.route('/api/band/setlists/<slid>', methods=['PUT'])
def band_update_setlist(slid):
    d = request.json
    conn = get_db()
    conn.execute(
        'UPDATE band_setlists SET title=?,setlist_date=?,memo=? WHERE id=?',
        (d['title'], d.get('setlist_date'), d.get('memo'), slid)
    )
    conn.commit()
    row = conn.execute('SELECT * FROM band_setlists WHERE id=?', (slid,)).fetchone()
    conn.close()
    return jsonify(dict(row))


@app.route('/api/band/setlists/<slid>', methods=['DELETE'])
def band_delete_setlist(slid):
    conn = get_db()
    conn.execute('DELETE FROM band_setlist_songs WHERE setlist_id=?', (slid,))
    conn.execute('DELETE FROM band_setlists WHERE id=?', (slid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/band/setlists/<slid>/songs', methods=['POST'])
def band_setlist_add_song(slid):
    d = request.json
    if not d.get('song_id'):
        return jsonify({'error': 'song_id가 필요합니다'}), 400
    conn = get_db()
    pos = conn.execute(
        'SELECT COALESCE(MAX(position)+1,0) FROM band_setlist_songs WHERE setlist_id=?', (slid,)
    ).fetchone()[0]
    item_id = str(uuid.uuid4())
    conn.execute(
        'INSERT INTO band_setlist_songs (id,setlist_id,song_id,position,note) VALUES (?,?,?,?,?)',
        (item_id, slid, d['song_id'], pos, d.get('note'))
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'item_id': item_id}), 201


@app.route('/api/band/setlists/<slid>/songs/<item_id>', methods=['DELETE'])
def band_setlist_remove_song(slid, item_id):
    conn = get_db()
    conn.execute('DELETE FROM band_setlist_songs WHERE id=? AND setlist_id=?', (item_id, slid))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/band/setlists/<slid>/order', methods=['PUT'])
def band_setlist_reorder(slid):
    item_ids = (request.json or {}).get('item_ids', [])
    conn = get_db()
    for i, item_id in enumerate(item_ids):
        conn.execute(
            'UPDATE band_setlist_songs SET position=? WHERE id=? AND setlist_id=?',
            (i, item_id, slid)
        )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


# 빠른 요청 버튼 프리셋 (팀이 함께 추가/수정/삭제)

DEFAULT_QUICK_PRESETS = [
    ('🔊', '모니터 소리 키워주세요'),
    ('🔉', '모니터 소리 줄여주세요'),
    ('🎤', '마이크가 안 들려요'),
    ('⚠️', '하울링(삐- 소리)이 나요'),
]


@app.route('/api/band/quickpresets', methods=['GET'])
def band_quickpresets():
    conn = get_db()
    rows = conn.execute('SELECT * FROM band_quick_presets ORDER BY position, rowid').fetchall()
    if not rows:
        # 처음이면 기본 버튼 채워넣기
        for i, (emoji, text) in enumerate(DEFAULT_QUICK_PRESETS):
            conn.execute('INSERT INTO band_quick_presets (id,emoji,text,position) VALUES (?,?,?,?)',
                         (str(uuid.uuid4()), emoji, text, i))
        conn.commit()
        rows = conn.execute('SELECT * FROM band_quick_presets ORDER BY position, rowid').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/band/quickpresets', methods=['POST'])
def band_create_quickpreset():
    d = request.json or {}
    if not (d.get('text') or '').strip():
        return jsonify({'error': '내용을 입력하세요'}), 400
    conn = get_db()
    pos = conn.execute('SELECT COALESCE(MAX(position)+1,0) FROM band_quick_presets').fetchone()[0]
    pid = str(uuid.uuid4())
    conn.execute('INSERT INTO band_quick_presets (id,emoji,text,position) VALUES (?,?,?,?)',
                 (pid, (d.get('emoji') or '').strip(), d['text'].strip(), pos))
    conn.commit()
    row = conn.execute('SELECT * FROM band_quick_presets WHERE id=?', (pid,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201


@app.route('/api/band/quickpresets/<pid>', methods=['PUT'])
def band_update_quickpreset(pid):
    d = request.json or {}
    if not (d.get('text') or '').strip():
        return jsonify({'error': '내용을 입력하세요'}), 400
    conn = get_db()
    conn.execute('UPDATE band_quick_presets SET emoji=?, text=? WHERE id=?',
                 ((d.get('emoji') or '').strip(), d['text'].strip(), pid))
    conn.commit()
    row = conn.execute('SELECT * FROM band_quick_presets WHERE id=?', (pid,)).fetchone()
    conn.close()
    return jsonify(dict(row)) if row else ('', 404)


@app.route('/api/band/quickpresets/<pid>', methods=['DELETE'])
def band_delete_quickpreset(pid):
    conn = get_db()
    conn.execute('DELETE FROM band_quick_presets WHERE id=?', (pid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


# 방송실 요청 (모니터 볼륨, 마이크 등)

@app.route('/api/band/requests', methods=['GET'])
def band_requests():
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM band_requests ORDER BY created_at DESC LIMIT 50'
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/band/requests', methods=['POST'])
def band_create_request():
    d = request.json
    if not d.get('message', '').strip():
        return jsonify({'error': '요청 내용을 입력하세요'}), 400
    rid = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        'INSERT INTO band_requests (id,sender,message) VALUES (?,?,?)',
        (rid, (d.get('sender') or '').strip() or None, d['message'].strip())
    )
    conn.commit()
    row = conn.execute('SELECT * FROM band_requests WHERE id=?', (rid,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201


@app.route('/api/band/requests/<rid>/done', methods=['POST'])
def band_request_done(rid):
    conn = get_db()
    conn.execute(
        "UPDATE band_requests SET status='done', done_at=CURRENT_TIMESTAMP WHERE id=?", (rid,)
    )
    conn.commit()
    row = conn.execute('SELECT * FROM band_requests WHERE id=?', (rid,)).fetchone()
    conn.close()
    return jsonify(dict(row)) if row else ('', 404)


@app.route('/api/band/requests/<rid>', methods=['DELETE'])
def band_delete_request(rid):
    conn = get_db()
    conn.execute('DELETE FROM band_requests WHERE id=?', (rid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


# 전달사항/주의사항 메모

@app.route('/api/band/notes', methods=['GET'])
def band_notes():
    conn = get_db()
    rows = conn.execute('SELECT * FROM band_notes ORDER BY updated_at DESC').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/band/notes', methods=['POST'])
def band_create_note():
    d = request.json
    if not d.get('title', '').strip():
        return jsonify({'error': '제목을 입력하세요'}), 400
    nid = str(uuid.uuid4())
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    conn.execute(
        'INSERT INTO band_notes (id,title,content,created_at,updated_at) VALUES (?,?,?,?,?)',
        (nid, d['title'].strip(), d.get('content', ''), now, now)
    )
    conn.commit()
    row = conn.execute('SELECT * FROM band_notes WHERE id=?', (nid,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201


@app.route('/api/band/notes/<nid>', methods=['PUT'])
def band_update_note(nid):
    d = request.json
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    conn.execute(
        'UPDATE band_notes SET title=?,content=?,updated_at=? WHERE id=?',
        (d['title'], d.get('content', ''), now, nid)
    )
    conn.commit()
    row = conn.execute('SELECT * FROM band_notes WHERE id=?', (nid,)).fetchone()
    conn.close()
    return jsonify(dict(row))


@app.route('/api/band/notes/<nid>', methods=['DELETE'])
def band_delete_note(nid):
    conn = get_db()
    conn.execute('DELETE FROM band_notes WHERE id=?', (nid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


# 실시간 인도(따라가기): 인도자가 넘기면 팀원 화면이 함께 이동

LIVE_TIMEOUT = 40  # 초. 인도자가 이 시간 넘게 위치를 안 보내면 자동 종료로 간주


@app.route('/api/band/live', methods=['GET'])
def band_live_get():
    conn = get_db()
    row = conn.execute("SELECT * FROM band_live WHERE id='current'").fetchone()
    conn.close()
    if not row or not row['active']:
        return jsonify({'active': 0})
    d = dict(row)
    # 인도자가 오래 위치를 안 보내면 종료된 것으로 처리
    try:
        last = datetime.strptime(d['updated_at'], '%Y-%m-%d %H:%M:%S')
        if (datetime.now() - last).total_seconds() > LIVE_TIMEOUT:
            return jsonify({'active': 0})
    except (TypeError, ValueError):
        pass
    return jsonify(d)


@app.route('/api/band/live', methods=['POST'])
def band_live_set():
    d = request.json or {}
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    conn.execute('''
        INSERT INTO band_live (id,setlist_id,song_index,page_index,leader,active,updated_at)
        VALUES ('current',?,?,?,?,1,?)
        ON CONFLICT(id) DO UPDATE SET
            setlist_id=excluded.setlist_id, song_index=excluded.song_index,
            page_index=excluded.page_index, leader=excluded.leader,
            active=1, updated_at=excluded.updated_at
    ''', (d.get('setlist_id'), d.get('song_index', 0), d.get('page_index', 0), d.get('leader'), now))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/band/live/stop', methods=['POST'])
def band_live_stop():
    conn = get_db()
    conn.execute("UPDATE band_live SET active=0 WHERE id='current'")
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


# ── Static ────────────────────────────────────────────────────────────────────

# 찬양/방송팀 전용 화면(첫 화면부터 /band)을 켜는 두 가지 방법:
#  1) BAND_ONLY=1  : 이 서비스는 무조건 찬양 화면만. (윌로와 별개인 전용 서비스로
#                    같은 코드를 하나 더 띄울 때 사용 — 자체 주소/DB를 가짐)
#  2) BAND_HOST=... : 지정한 도메인으로 접속했을 때만 찬양 화면. (한 서비스에 별도
#                    도메인을 연결해 쓰는 경우. 여러 개면 콤마로 구분)
BAND_ONLY  = os.environ.get('BAND_ONLY', '').strip().lower() in ('1', 'true', 'yes', 'on')
BAND_HOSTS = [h.strip().lower() for h in os.environ.get('BAND_HOST', '').split(',') if h.strip()]


def is_band_host():
    if BAND_ONLY:
        return True
    host = (request.host or '').split(':')[0].lower()
    return any(host == b or b in host for b in BAND_HOSTS)


@app.route('/band')
def band_page():
    return send_from_directory('static', 'band.html')


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    band = is_band_host()
    # 찬양 전용일 때는 관리자 홈(index.html)을 노출하지 않고 찬양 화면으로
    if band and (path == '' or path == 'index.html'):
        return send_from_directory('static', 'band.html')
    if path and os.path.exists(os.path.join('static', path)):
        return send_from_directory('static', path)
    return send_from_directory('static', 'band.html' if band else 'index.html')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))

    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = '127.0.0.1'

    print('\n' + '='*50)
    print('  윌로 서비스 관리 시스템')
    print('='*50)
    print(f'  PC 접속:     http://localhost:{port}')
    print(f'  아이폰 접속: http://{local_ip}:{port}')
    print('  (같은 와이파이에 연결되어 있어야 합니다)')
    print('='*50 + '\n')
    app.run(host='0.0.0.0', port=port, debug=False)
