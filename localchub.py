import os, json, base64, requests, re, random, argparse, time, threading, datetime, sqlite3, functools, secrets
from contextlib import contextmanager
from flask import Flask, render_template, request, send_from_directory, jsonify, Response, session, redirect, flash
from PIL import Image, UnidentifiedImageError
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

CARDS_PER_PAGE = 100
DB_PATH = 'cards.db'

# ── DB context manager ─────────────────────────────────────────────────────────

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()

# ── DB init helpers ────────────────────────────────────────────────────────────

def init_tag_metadata():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tag_metadata (
                tag          TEXT PRIMARY KEY,
                is_favourite INTEGER NOT NULL DEFAULT 0,
                is_banned    INTEGER NOT NULL DEFAULT 0,
                merged_into  TEXT DEFAULT NULL,
                updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_tm_merged_into ON tag_metadata(merged_into);
        """)
        conn.commit()

def init_card_scores():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS card_scores (
                card_id    INTEGER PRIMARY KEY,
                quality    REAL DEFAULT NULL,
                lewdity    REAL DEFAULT NULL,
                story      REAL DEFAULT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()

def init_settings():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key        TEXT PRIMARY KEY,
                value      TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()

# ── Settings helpers ───────────────────────────────────────────────────────────

def get_setting(key):
    try:
        with get_db() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row['value'] if row else None
    except Exception:
        return None

def set_setting(key, value):
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))",
            (key, value)
        )
        conn.commit()

# ── Tag metadata ───────────────────────────────────────────────────────────────

def get_tag_metadata_map():
    try:
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM tag_metadata").fetchall()
        return {
            row['tag']: {
                'is_favourite': bool(row['is_favourite']),
                'is_banned': bool(row['is_banned']),
                'merged_into': row['merged_into']
            }
            for row in rows
        }
    except Exception:
        return {}

# ── Scores helpers ─────────────────────────────────────────────────────────────

def get_all_scores():
    try:
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM card_scores").fetchall()
        return {
            row['card_id']: {
                'quality': row['quality'],
                'lewdity': row['lewdity'],
                'story': row['story']
            }
            for row in rows
        }
    except Exception:
        return {}

def render_score_bar(score, emoji):
    filled = int(score)
    has_half = (score % 1) >= 0.25
    half_html = f'<span class="score-half">{emoji}</span>' if has_half else ''
    return emoji * filled + half_html

# ── API token auth decorator ───────────────────────────────────────────────────

def require_api_token(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return jsonify({'error': 'Unauthorized'}), 401
        stored = get_setting('api_token')
        if not stored or auth[7:] != stored:
            return jsonify({'error': 'Invalid token'}), 401
        return f(*args, **kwargs)
    return decorated

# ── Session auth before_request ────────────────────────────────────────────────

@app.before_request
def check_auth():
    exempt = {'/login', '/setup', '/setup/create', '/setup/skip', '/logout'}
    if request.path.startswith('/static/') or request.path.startswith('/assets/') or request.path in exempt:
        return
    # API v1 routes use bearer token — skip session check
    if request.path.startswith('/api/v1/'):
        return
    try:
        auth_skipped = get_setting('auth_skipped') == 'true'
        first_done = get_setting('first_login_done') == 'true'
    except Exception:
        return
    if not auth_skipped and not first_done:
        return redirect('/setup')
    if not auth_skipped and 'authenticated' not in session:
        return redirect('/login')

# ── Card preview size ──────────────────────────────────────────────────────────

CARD_PREVIEW_SIZE = (300, 300)

# ── CLI args ───────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser()
parser.add_argument('--autoupdate', type=int, default=30000, nargs='?', const=60)
parser.add_argument('--synctags', action='store_true', default=False)
parser.add_argument('--backup', action='store_true', default=False)
parser.add_argument('--min_tags', type=int, default=0)
parser.add_argument('--include_tags', type=str, default="")
parser.add_argument('--exclude_tags', type=str, default="nonenglish")
sorting_methods = [
    'download_count', 'id', 'rating', 'default', 'rating_count',
    'last_activity_at', 'trending_downloads', 'n_favorites', 'created_at',
    'star_count', 'msgs_chat', 'msgs_user', 'chats_user', 'name', 'timeline',
    'n_tokens', 'random', 'trending', 'newcomer', 'favorite_time', 'ai_rating'
]
parser.add_argument('--sorting', type=str, default='last_activity_at', choices=sorting_methods)
parser.add_argument('--allow_nsfw', action='store_true', default=True)
parser.add_argument('--allow_nsfl', action='store_true', default=True)
parser.add_argument('--min_tokens', type=int, default=250)
parser.add_argument('--max_tokens', type=int, default=128000)
parser.add_argument('--include_forks', action='store_true', default=False)
parser.add_argument('--require_expressions', action='store_true', default=False)
parser.add_argument('--require_lore_embedded', action='store_true', default=False)
args = parser.parse_args()
autoupdInterval = args.autoupdate
autoupdMode = args.autoupdate is not None
synctagsMode = args.synctags
backupMode = args.backup
min_tags = args.min_tags
include_tags = args.include_tags
exclude_tags = args.exclude_tags
sorting = args.sorting
allow_nsfw = args.allow_nsfw
allow_nsfl = args.allow_nsfl
min_tokens = args.min_tokens
max_tokens = args.max_tokens
include_forks = args.include_forks
require_expressions = args.require_expressions
require_lore_embedded = args.require_lore_embedded

autoupdThread = None
autoupdRunning = False
autoupdEvent = threading.Event()

def autoUpdate():
    while not autoupdEvent.is_set():
        print(f'[autoupdate/{autoupdInterval}s] Updating cards..')
        try:
            requests.get('http://127.0.0.1:1488/sync?c=50')
        except requests.ConnectionError:
            pass
        autoupdEvent.wait(autoupdInterval)

# ── Card helpers ───────────────────────────────────────────────────────────────

def deleteCard(cardId):
    for ext in ['png', 'json']:
        os.remove(f'static/{cardId}.{ext}')

def getCardMetadata(cardId):
    with open(f'static/{cardId}.json', 'r', encoding='utf-8') as f:
        return json.load(f)

def getPngInfo(cardId):
    try:
        with open(f'static/{cardId}.png', 'rb') as f:
            img = Image.open(f)
            if "chara" in img.png.im_info:
                return json.loads(base64.b64decode(img.png.im_info['chara']).decode('utf-8'))
            else:
                return {}
    except FileNotFoundError:
        return {}
    except UnidentifiedImageError:
        return {}
    except Exception as e:
        print(f'Error retrieving PNG info: {str(e)}')
        return {}

def pngCheck(cardId):
    try:
        Image.open(f'static/{cardId}.png').format == 'PNG'
        return True
    except UnidentifiedImageError:
        return False

def createCardEntry(metadata, score=None):
    cleaned_description = re.sub(r'<[^>]+>', '', metadata['description'])
    cleaned_description = re.sub(r'\s+', ' ', cleaned_description).strip()
    cleaned_tagline = re.sub(r'<[^>]+>', '', metadata['tagline'])
    cleaned_tagline = re.sub(r'\s+', ' ', cleaned_tagline).strip()

    q = score.get('quality') if score else None
    l = score.get('lewdity') if score else None
    s = score.get('story') if score else None

    return {
        'id': metadata['id'],
        'author': metadata['fullPath'].split('/')[0],
        'name': metadata['name'],
        'tagline': cleaned_tagline,
        'description': cleaned_description,
        'topics': [topic for topic in metadata['topics'] if topic != 'ROOT'],
        'imagePath': f'static/{metadata["id"]}.png',
        'tokenCount': metadata['nTokens'],
        'lastActivityAt': datetime.datetime.strptime(metadata['lastActivityAt'], "%Y-%m-%dT%H:%M:%SZ").strftime("%b %d, %Y %H:%M"),
        'createdAt': datetime.datetime.strptime(metadata['createdAt'], "%Y-%m-%dT%H:%M:%SZ").strftime("%b %d, %Y %H:%M"),
        'quality_bar': render_score_bar(q, '⭐') if q is not None else None,
        'lewdity_bar': render_score_bar(l, '🍑') if l is not None else None,
        'story_bar': render_score_bar(s, '📖') if s is not None else None,
        'quality_score': q,
        'lewdity_score': l,
        'story_score': s,
    }

def card_has_effective_tag(card_tags, required, merge_map):
    return required in card_tags or any(merge_map.get(ct) == required for ct in card_tags)

def card_is_banned(card_tags, banned_set, merge_map):
    for ct in card_tags:
        if ct in banned_set or (merge_map.get(ct) in banned_set and merge_map.get(ct) is not None):
            return True
    return False

def getCardList(page, query=None, searchType='basic', sort_by='createdAt'):
    all_scores = get_all_scores()
    json_files = [f for f in os.listdir('static') if f.endswith('.json')]

    json_files.sort(
        key=lambda f: os.path.getmtime(os.path.join('static', f)),
        reverse=True
    )

    card_ids_sorted = [int(os.path.splitext(f)[0]) for f in json_files]

    filtered_cards = []
    randomTags = set()

    tag_meta = get_tag_metadata_map()
    banned = {t for t, v in tag_meta.items() if v['is_banned']}
    merge_map = {t: v['merged_into'] for t, v in tag_meta.items() if v['merged_into']}

    def add_to_random_tags(card_tags):
        for ct in card_tags:
            canonical = merge_map.get(ct, ct)
            if canonical not in banned:
                randomTags.add(canonical)

    if query:
        include_tags_q = set()
        exclude_tags_q = set()

        for tag in query.lower().split(','):
            tag = tag.strip()
            if tag.startswith('-'):
                exclude_tags_q.add(tag[1:])
            else:
                include_tags_q.add(tag)

        for card_id in card_ids_sorted:
            try:
                metadata = getCardMetadata(card_id)
            except Exception:
                continue

            card_tags = set(tag.lower() for tag in metadata.get('topics', []))

            if banned and card_is_banned(card_tags, banned, merge_map):
                continue

            if include_tags_q and not all(card_has_effective_tag(card_tags, req, merge_map) for req in include_tags_q):
                continue
            if exclude_tags_q and not exclude_tags_q.isdisjoint(card_tags):
                continue

            add_to_random_tags(card_tags)
            filtered_cards.append(createCardEntry(metadata, all_scores.get(card_id)))

        total_cards = len(filtered_cards)
        total_pages = (total_cards + CARDS_PER_PAGE - 1) // CARDS_PER_PAGE
        start = (page - 1) * CARDS_PER_PAGE
        end = start + CARDS_PER_PAGE
        return filtered_cards[start:end], total_cards, total_pages, randomTags

    if banned:
        all_valid = []
        for card_id in card_ids_sorted:
            try:
                metadata = getCardMetadata(card_id)
                card_tags = set(t.lower() for t in metadata.get('topics', []))
                if card_is_banned(card_tags, banned, merge_map):
                    continue
                all_valid.append((card_id, metadata))
                add_to_random_tags(card_tags)
            except Exception:
                continue
        total_cards = len(all_valid)
        total_pages = (total_cards + CARDS_PER_PAGE - 1) // CARDS_PER_PAGE
        start = (page - 1) * CARDS_PER_PAGE
        end = start + CARDS_PER_PAGE
        cards = [createCardEntry(m, all_scores.get(cid)) for cid, m in all_valid[start:end]]
        return cards, total_cards, total_pages, randomTags

    # Fast path: no bans
    start = (page - 1) * CARDS_PER_PAGE
    end = start + CARDS_PER_PAGE

    cards = []
    for card_id in card_ids_sorted[start:end]:
        try:
            metadata = getCardMetadata(card_id)
            cards.append(createCardEntry(metadata, all_scores.get(card_id)))
            add_to_random_tags(set(t.lower() for t in metadata.get('topics', [])))
        except Exception:
            continue

    total_cards = len(card_ids_sorted)
    total_pages = (total_cards + CARDS_PER_PAGE - 1) // CARDS_PER_PAGE
    return cards, total_cards, total_pages, randomTags

def blacklistAdd(cardId):
    if not os.path.exists('blacklist.txt'):
        with open('blacklist.txt', 'w') as f:
            f.write('')
    with open('blacklist.txt', 'a') as f:
        f.write(f'{cardId}\n')

def blacklistCheck(cardId):
    if os.path.exists('blacklist.txt'):
        with open('blacklist.txt', 'r') as f:
            return cardId in f.read().split('\n')
    return False

# ── Static / card image routes ─────────────────────────────────────────────────

@app.route('/static/<path:filename>', methods=['GET'])
def image(filename):
    return send_from_directory('static', filename)

@app.route('/assets/<path:filename>', methods=['GET'])
def assets(filename):
    return send_from_directory('templates', filename)

@app.route('/get_png_info/<cardId>', methods=['GET'])
def get_png_info(cardId):
    return jsonify(getPngInfo(cardId))

# ── Main page ──────────────────────────────────────────────────────────────────

@app.route('/', methods=['GET'])
def index():
    page = int(request.args.get('page', 1))
    query = request.args.get('query')
    searchType = request.args.get('type', 'basic')
    sort_by = request.args.get('sort', 'createdAt')

    cards, count, total_pages, randomTags = getCardList(page, query, searchType)
    search_results = cards if query else None

    return render_template(
        'index.html',
        cards=cards,
        page=page,
        total_pages=total_pages,
        card_preview_size=CARD_PREVIEW_SIZE,
        search_results=search_results,
        count=count,
        random_tags=randomTags
    )

# ── Sync ───────────────────────────────────────────────────────────────────────

@app.route('/sync', methods=['GET'])
def syncCards():
    totalCards, currCard, newCards = int(request.args.get('c', 500)), 0, 0
    cardIds = sorted([int(file.split('.')[0]) for file in os.listdir('static') if file.lower().endswith('.png')], reverse=True)

    def should_skip_card(card):
        for label in card.get("labels", []):
            if label.get("title") == "TOKEN_COUNTS":
                try:
                    description_data = json.loads(label.get("description", "{}"))
                    if description_data.get("total") in [1630, 5872, 3199, 1678, 3199, 2389, 2625, 5192]:
                        return True
                except json.JSONDecodeError:
                    pass

        name_symbols = [
            "我", "你", "他", "她", "它", "我们", "你们", "他们", "她们", "这", "那", "是", "不", "了", "在", "有", "没有", "说", "问", "知道",
            "做", "看", "听", "想", "来", "去", "吃", "喝", "买", "卖", "高", "低", "大", "小", "多", "少", "新", "旧", "长", "短", "快", "慢",
            "高", "低", "重", "轻", "早", "晚", "前", "后", "左", "右", "中", "上", "下", "开", "关", "笑", "哭", "跳", "跑", "走", "打", "玩",
            "日", "月", "木", "水", "火", "金", "土", "人", "子", "女", "男", "大", "小", "中", "上", "下", "左", "右", "前", "後", "生",
            "学", "年", "今", "時", "分", "半", "長", "短", "多", "少", "高", "低", "新", "古", "青", "赤", "白", "黒", "雨", "雪", "風",
            "道", "駅", "車", "電", "話", "読", "書", "行", "来", "食", "飲", "買", "売", "見", "聞", "思", "考", "知", "愛", "友", "家",
            "가", "나", "다", "라", "마", "바", "사", "아", "자", "차", "카", "타", "파", "하", "거", "너", "더", "러", "머", "버", "서",
            "어", "저", "처", "커", "터", "퍼", "허", "고", "노", "도", "로", "모", "보", "소", "오", "조", "초", "코", "토", "포", "호",
            "구", "누", "두", "루", "무", "부", "수", "우", "주", "추", "쿠", "투", "푸", "후", "기", "니", "디", "리", "미", "비", "시",
            "이", "지", "치", "키", "티", "피", "히", "가", "나", "다", "라", "마", "바", "사", "아", "자", "차", "카", "타", "파", "하",
            "空", "格", "一", "是", "的", "雌", "小", "鬼", "妹", "妹", "縉", "雲", "本", "角", "色", "卡", "免", "费", "发", "布", "于", "类", "脑", "服", "务", "器", "未", "经", "允", "许", "禁", "止", "搬", "运", "或", "用", "于", "盈", "利", "贩", "卖", "将", "在", "此", "处", "更", "新", "后", "续", "版", "本", "在", "性", "爱", "医", "院", "工", "作", "的", "妈", "妈", "地", "牢", "之", "主", "庄", "晓", "飞", "机", "杯", "魅", "魔", "调", "教", "系", "统", "更", "世", "界", "设", "定", "中", "实", "装", "性", "格", "女", "性", "姓", "名", "庄", "园", "详", "细", "注", "意", "加", "载", "世", "界", "书", "开", "局", "示", "例", "生", "成", "一", "个", "强", "势", "性", "格", "身", "材", "高", "挑", "御", "姐", "型", "恶", "魔", "白", "长", "发", "有", "角", "进", "来", "佩", "佩", "约", "书", "娅", '温', '迪'
        ]
        if any(symbol in card.get("name", "") for symbol in name_symbols):
            return True
        if "description" in card and any(symbol in card["description"] for symbol in name_symbols):
            return True
        return False

    def dlCard(card):
        nonlocal newCards, currCard
        cardId = card['id']
        if should_skip_card(card):
            print(f'Spam-Bot or Non-Eng card detected, skipping {card["name"]} ({cardId})..')
            return False
        pTask = 'Downloading'
        if synctagsMode and os.path.exists(f'static/{cardId}.json') and len(card['topics']) > 0:
            if card['topics'] != getCardMetadata(card['id'])['topics']:
                with open(f'static/{cardId}.json', 'w', encoding='utf-8') as f:
                    f.write(json.dumps(card, indent=4))
                    print(f'Updating tags for {card["name"]} ({cardId})..')
        if card['createdAt'] != card['lastActivityAt'] and os.path.exists(f'static/{cardId}.json'):
            if card['lastActivityAt'] != getCardMetadata(card['id'])['lastActivityAt']:
                try:
                    cardIds.remove(cardId)
                    pTask = 'Updating'
                    if backupMode:
                        if not os.path.exists('backup'):
                            os.mkdir('backup')
                        for ext in ['png', 'json']:
                            os.rename(f'static/{cardId}.{ext}', f'backup/{cardId}_{getCardMetadata(card["id"])["lastActivityAt"].split("T")[0]}.{ext}')
                except Exception as e:
                    print(e, cardId)
        if cardId not in cardIds:
            with open(f'static/{cardId}.json', 'w', encoding='utf-8') as f:
                f.write(json.dumps(card, indent=4))
            with open(f'static/{cardId}.png', 'wb') as f:
                f.write(requests.get(f'https://avatars.charhub.io/avatars/{card["fullPath"]}/chara_card_v2.png').content)
                print(f'{pTask} {card["name"]} ({cardId})..')
            if not pngCheck(cardId):
                deleteCard(cardId)
                blacklistAdd(cardId)
                return False
            newCards += 1
        currCard += 1
        return True

    def genSyncData():
        nonlocal totalCards
        page = 1
        r = requests.get('https://inference.chub.ai/search', params={
            'first': totalCards, 'page': f'{page}', 'sort': sorting, 'asc': 'false',
            'nsfw': allow_nsfw, 'nsfl': allow_nsfl, 'min_tokens': min_tokens,
            'max_tokens': max_tokens, 'include_forks': include_forks, 'min_tags': min_tags,
            'tags': include_tags, 'exclude_tags': exclude_tags,
            'require_expressions': require_expressions, 'require_lore_embedded': require_lore_embedded
        }, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'}).json()

        if 'data' not in r:
            print(f"Unexpected response structure: {r}")
            yield f"data: {json.dumps({'progress': 0, 'currCard': 'Error: No data returned from the API.', 'newCards': 0})}\n\n"
            return

        cards = r['data']['nodes']
        for card in cards:
            yield f"data: {json.dumps({'progress': round((currCard / len(cards)) * 100, 2), 'currCard': card['name'], 'newCards': newCards})}\n\n"
            if not blacklistCheck(str(card['id'])):
                if card['id'] == 88:
                    continue
                if not dlCard(card):
                    continue

        yield f"data: {json.dumps({'progress': 100, 'currCard': 'Sync Completed', 'newCards': newCards})}\n\n"

    return Response(genSyncData(), content_type='text/event-stream')

# ── Card management routes ─────────────────────────────────────────────────────

@app.route('/delete_card/<int:cardId>', methods=['POST', 'DELETE'])
def delete_card(cardId):
    try:
        deleteCard(cardId)
        blacklistAdd(cardId)
        return jsonify({'message': 'Card deleted successfully'}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@app.route('/edit_tags/<int:cardId>', methods=['POST'])
def edit_tags(cardId):
    try:
        newTags = request.form.get('tags')
        metadata = getCardMetadata(cardId)
        metadata['topics'] = [tag.strip() for tag in newTags.split(',') if tag != '']
        with open(f'static/{cardId}.json', 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=4)
        return jsonify({'message': 'Tags updated successfully'}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@app.route('/load_more', methods=['GET'])
def load_more():
    page = int(request.args.get('page', 1))
    query = request.args.get('query')
    searchType = request.args.get('type', 'basic')
    sort_by = request.args.get('sort', 'createdAt')

    cards, count, total_pages, _ = getCardList(page, query, searchType)
    return jsonify({'cards': cards, 'page': page, 'total_pages': total_pages})

@app.route('/sort', methods=['GET'])
def sort_cards():
    page = int(request.args.get('page', 1))
    query = request.args.get('query')
    searchType = request.args.get('type', 'basic')
    sort_by = request.args.get('sort', 'createdAt')

    cards, count, total_pages, randomTags = getCardList(page, query, searchType, sort_by)
    return jsonify({'cards': cards, 'total_pages': total_pages})

@app.route('/get_card_info/<int:cardId>', methods=['GET'])
def get_card_info(cardId):
    try:
        metadata = getCardMetadata(cardId)
        png_info = getPngInfo(cardId)
        card_details = {
            'name': metadata.get('name', 'Unknown'),
            'author': metadata.get('author', 'Unknown'),
            'tagline': metadata.get('tagline', 'No tagline'),
            'description': metadata.get('description', 'No description'),
            'topics': metadata.get('topics', []),
            'imagePath': metadata.get('imagePath', '/static/' + str(cardId) + '.png'),
            'createdAt': metadata.get('createdAt', 'Unknown date'),
            'lastActivityAt': metadata.get('lastActivityAt', 'Unknown date'),
            **png_info
        }
        return render_template('card_details.html', metadata=card_details)
    except FileNotFoundError as e:
        return jsonify({'error': f'Card not found: {str(e)}'}), 404
    except KeyError as e:
        return jsonify({'error': f'Missing field in metadata: {str(e)}'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── Scores route (internal UI) ─────────────────────────────────────────────────

@app.route('/api/scores/<int:cardId>', methods=['POST'])
def api_set_scores(cardId):
    data = request.get_json()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM card_scores WHERE card_id = ?", (cardId,)).fetchone()
        q = row['quality'] if row else None
        l = row['lewdity'] if row else None
        s = row['story'] if row else None
        if 'quality' in data:
            q = float(data['quality']) if data['quality'] is not None else None
        if 'lewdity' in data:
            l = float(data['lewdity']) if data['lewdity'] is not None else None
        if 'story' in data:
            s = float(data['story']) if data['story'] is not None else None
        conn.execute(
            "INSERT OR REPLACE INTO card_scores (card_id, quality, lewdity, story, updated_at) VALUES (?, ?, ?, ?, datetime('now'))",
            (cardId, q, l, s)
        )
        conn.commit()
    return jsonify({
        'quality_bar': render_score_bar(q, '⭐') if q is not None else None,
        'lewdity_bar': render_score_bar(l, '🍑') if l is not None else None,
        'story_bar': render_score_bar(s, '📖') if s is not None else None,
        'quality_score': q,
        'lewdity_score': l,
        'story_score': s,
    })

# ── Tag API routes ─────────────────────────────────────────────────────────────

@app.route('/api/tags', methods=['GET'])
def api_get_tags():
    tag_counts = {}
    for f in os.listdir('static'):
        if f.endswith('.json'):
            try:
                with open(f'static/{f}', 'r', encoding='utf-8') as fp:
                    metadata = json.load(fp)
                for tag in metadata.get('topics', []):
                    t = tag.lower().strip()
                    if t and t != 'root':
                        tag_counts[t] = tag_counts.get(t, 0) + 1
            except Exception:
                continue
    tag_meta = get_tag_metadata_map()
    all_tags = set(tag_counts.keys()) | set(tag_meta.keys())
    tags = []
    for tag in all_tags:
        meta = tag_meta.get(tag, {})
        tags.append({
            'tag': tag,
            'count': tag_counts.get(tag, 0),
            'is_favourite': meta.get('is_favourite', False),
            'is_banned': meta.get('is_banned', False),
            'merged_into': meta.get('merged_into', None),
        })
    tags.sort(key=lambda x: x['count'], reverse=True)
    return jsonify({'tags': tags})

@app.route('/api/tags/metadata', methods=['GET'])
def api_get_tag_metadata():
    tag_meta = get_tag_metadata_map()
    return jsonify({
        'favourites': [t for t, v in tag_meta.items() if v['is_favourite']],
        'banned': [t for t, v in tag_meta.items() if v['is_banned']],
        'merges': [{'source': t, 'target': v['merged_into']} for t, v in tag_meta.items() if v['merged_into']],
    })

@app.route('/api/tags/favourite', methods=['POST'])
def api_toggle_favourite():
    data = request.get_json()
    tag = (data.get('tag') or '').lower().strip()
    if not tag:
        return jsonify({'error': 'Missing tag'}), 400
    with get_db() as conn:
        row = conn.execute('SELECT is_favourite FROM tag_metadata WHERE tag = ?', (tag,)).fetchone()
        if row:
            new_val = 0 if row['is_favourite'] else 1
            conn.execute('UPDATE tag_metadata SET is_favourite = ?, updated_at = datetime("now") WHERE tag = ?', (new_val, tag))
        else:
            new_val = 1
            conn.execute('INSERT INTO tag_metadata (tag, is_favourite) VALUES (?, 1)', (tag,))
        conn.commit()
    return jsonify({'tag': tag, 'is_favourite': bool(new_val)})

@app.route('/api/tags/ban', methods=['POST'])
def api_toggle_ban():
    data = request.get_json()
    tag = (data.get('tag') or '').lower().strip()
    if not tag:
        return jsonify({'error': 'Missing tag'}), 400
    with get_db() as conn:
        row = conn.execute('SELECT is_banned FROM tag_metadata WHERE tag = ?', (tag,)).fetchone()
        if row:
            new_val = 0 if row['is_banned'] else 1
            conn.execute('UPDATE tag_metadata SET is_banned = ?, updated_at = datetime("now") WHERE tag = ?', (new_val, tag))
        else:
            new_val = 1
            conn.execute('INSERT INTO tag_metadata (tag, is_banned) VALUES (?, 1)', (tag,))
        conn.commit()
    return jsonify({'tag': tag, 'is_banned': bool(new_val)})

@app.route('/api/tags/merge', methods=['POST'])
def api_merge_tags():
    data = request.get_json()
    sources = [(s or '').lower().strip() for s in data.get('sources', [])]
    target = (data.get('target') or '').lower().strip()
    if not target or not sources:
        return jsonify({'error': 'Missing sources or target'}), 400
    sources = [s for s in sources if s and s != target]
    if not sources:
        return jsonify({'error': 'No valid source tags (cannot merge a tag into itself)'}), 400
    with get_db() as conn:
        for source in sources:
            row = conn.execute('SELECT tag FROM tag_metadata WHERE tag = ?', (source,)).fetchone()
            if row:
                conn.execute('UPDATE tag_metadata SET merged_into = ?, updated_at = datetime("now") WHERE tag = ?', (target, source))
            else:
                conn.execute('INSERT INTO tag_metadata (tag, merged_into) VALUES (?, ?)', (source, target))
        conn.commit()
    return jsonify({'merged': sources, 'target': target})

@app.route('/api/tags/unmerge', methods=['POST'])
def api_unmerge_tags():
    data = request.get_json()
    tags = [(t or '').lower().strip() for t in data.get('tags', [])]
    if not tags:
        return jsonify({'error': 'Missing tags'}), 400
    with get_db() as conn:
        for tag in tags:
            conn.execute('UPDATE tag_metadata SET merged_into = NULL, updated_at = datetime("now") WHERE tag = ?', (tag,))
        conn.commit()
    return jsonify({'unmerged': tags})

# ── Auth routes ────────────────────────────────────────────────────────────────

@app.route('/setup', methods=['GET'])
def setup_page():
    auth_skipped = get_setting('auth_skipped') == 'true'
    first_done = get_setting('first_login_done') == 'true'
    if auth_skipped or first_done:
        return redirect('/')
    return render_template('setup.html')

@app.route('/setup/create', methods=['POST'])
def setup_create():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    confirm = request.form.get('confirm', '')
    if not username or not password:
        flash('Username and password are required.')
        return redirect('/setup')
    if password != confirm:
        flash('Passwords do not match.')
        return redirect('/setup')
    if len(password) < 4:
        flash('Password must be at least 4 characters.')
        return redirect('/setup')
    set_setting('username', username)
    set_setting('password_hash', generate_password_hash(password))
    set_setting('first_login_done', 'true')
    session['authenticated'] = True
    return redirect('/')

@app.route('/setup/skip', methods=['POST'])
def setup_skip():
    set_setting('auth_skipped', 'true')
    set_setting('first_login_done', 'true')
    return redirect('/')

@app.route('/login', methods=['GET'])
def login_page():
    auth_skipped = get_setting('auth_skipped') == 'true'
    if auth_skipped or 'authenticated' in session:
        return redirect('/')
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login_submit():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    stored_user = get_setting('username')
    stored_hash = get_setting('password_hash')
    if username == stored_user and stored_hash and check_password_hash(stored_hash, password):
        session['authenticated'] = True
        return redirect('/')
    flash('Invalid username or password.')
    return redirect('/login')

@app.route('/logout')
def logout():
    session.pop('authenticated', None)
    return redirect('/login')

# ── API token management ───────────────────────────────────────────────────────

@app.route('/api/token/status', methods=['GET'])
def api_token_status():
    token = get_setting('api_token')
    if token:
        masked = '****' + token[-8:] if len(token) >= 8 else '****'
        return jsonify({'has_token': True, 'masked': masked, 'token': token})
    return jsonify({'has_token': False, 'masked': None, 'token': None})

@app.route('/api/token/generate', methods=['POST'])
def api_token_generate():
    new_token = secrets.token_urlsafe(32)
    set_setting('api_token', new_token)
    return jsonify({'token': new_token})

# ── API docs page ──────────────────────────────────────────────────────────────

@app.route('/api/docs', methods=['GET'])
def api_docs():
    return render_template('api_docs.html')

# ── API v1 routes (bearer auth) ────────────────────────────────────────────────

@app.route('/api/v1/cards', methods=['GET'])
@require_api_token
def api_v1_list_cards():
    page = int(request.args.get('page', 1))
    query = request.args.get('query')
    searchType = request.args.get('type', 'basic')
    sort_by = request.args.get('sort', 'createdAt')
    cards, count, total_pages, _ = getCardList(page, query, searchType, sort_by)
    return jsonify({'cards': cards, 'page': page, 'total_pages': total_pages, 'count': count})

@app.route('/api/v1/cards/<int:cardId>', methods=['GET'])
@require_api_token
def api_v1_get_card(cardId):
    try:
        metadata = getCardMetadata(cardId)
        png_info = getPngInfo(cardId)
        all_scores = get_all_scores()
        entry = createCardEntry(metadata, all_scores.get(cardId))
        entry['raw_data'] = png_info.get('data', {})
        entry['png_info'] = png_info
        return jsonify(entry)
    except FileNotFoundError:
        return jsonify({'error': 'Card not found'}), 404

@app.route('/api/v1/cards/<int:cardId>', methods=['PATCH'])
@require_api_token
def api_v1_update_card(cardId):
    data = request.get_json()
    result = {}

    score_fields = {k: data[k] for k in ('quality', 'lewdity', 'story') if k in data}
    if score_fields:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM card_scores WHERE card_id = ?", (cardId,)).fetchone()
            q = row['quality'] if row else None
            l = row['lewdity'] if row else None
            s = row['story'] if row else None
            if 'quality' in score_fields:
                q = float(score_fields['quality']) if score_fields['quality'] is not None else None
            if 'lewdity' in score_fields:
                l = float(score_fields['lewdity']) if score_fields['lewdity'] is not None else None
            if 'story' in score_fields:
                s = float(score_fields['story']) if score_fields['story'] is not None else None
            conn.execute(
                "INSERT OR REPLACE INTO card_scores (card_id, quality, lewdity, story, updated_at) VALUES (?, ?, ?, ?, datetime('now'))",
                (cardId, q, l, s)
            )
            conn.commit()
        result['scores'] = {
            'quality': q, 'lewdity': l, 'story': s,
            'quality_bar': render_score_bar(q, '⭐') if q is not None else None,
            'lewdity_bar': render_score_bar(l, '🍑') if l is not None else None,
            'story_bar': render_score_bar(s, '📖') if s is not None else None,
        }

    if 'topics' in data:
        try:
            metadata = getCardMetadata(cardId)
            metadata['topics'] = [t.strip() for t in data['topics'] if t.strip()]
            with open(f'static/{cardId}.json', 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=4)
            result['topics'] = metadata['topics']
        except FileNotFoundError:
            return jsonify({'error': 'Card not found'}), 404

    return jsonify(result)

@app.route('/api/v1/cards/<int:cardId>/tags/add', methods=['POST'])
@require_api_token
def api_v1_add_tags(cardId):
    data = request.get_json()
    new_tags = [t.strip() for t in data.get('tags', []) if t.strip()]
    try:
        metadata = getCardMetadata(cardId)
        existing = list(metadata.get('topics', []))
        for t in new_tags:
            if t not in existing:
                existing.append(t)
        metadata['topics'] = existing
        with open(f'static/{cardId}.json', 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=4)
        return jsonify({'topics': metadata['topics']})
    except FileNotFoundError:
        return jsonify({'error': 'Card not found'}), 404

@app.route('/api/v1/cards/<int:cardId>/tags/remove', methods=['POST'])
@require_api_token
def api_v1_remove_tags(cardId):
    data = request.get_json()
    rm_tags = set(t.strip() for t in data.get('tags', []) if t.strip())
    try:
        metadata = getCardMetadata(cardId)
        metadata['topics'] = [t for t in metadata.get('topics', []) if t not in rm_tags]
        with open(f'static/{cardId}.json', 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=4)
        return jsonify({'topics': metadata['topics']})
    except FileNotFoundError:
        return jsonify({'error': 'Card not found'}), 404

# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    # Feature 4: Safe startup checks
    if not os.path.exists('static'):
        os.makedirs('static')
        print('[startup] Created missing static/ folder')

    if not os.path.exists(DB_PATH):
        static_jsons = [f for f in os.listdir('static') if f.endswith('.json')]
        static_pngs = [f for f in os.listdir('static') if f.endswith('.png') and f != 'favicon.ico']
        if static_jsons and static_pngs:
            print('[startup] No DB found but JSON/PNG files present — running migration...')
            from migrate import migrate_from_json
            migrate_from_json('static', verbose=True)
            print('[startup] Migration complete')
        else:
            print('[startup] No DB found — creating empty database')

    init_tag_metadata()
    init_card_scores()
    init_settings()

    # Set Flask session secret key (generated once, stored persistently)
    sk = get_setting('secret_key')
    if not sk:
        sk = secrets.token_hex(32)
        set_setting('secret_key', sk)
    app.secret_key = sk

    if autoupdMode and not autoupdRunning:
        autoupdRunning = True
        autoupdThread = threading.Thread(target=autoUpdate, daemon=True)
        autoupdThread.start()

    app.run(debug=False, port=1488)
