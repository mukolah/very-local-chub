import os, json, base64, requests, re, random, argparse, time, threading, datetime
from flask import Flask, render_template, request, send_from_directory, jsonify, Response
from PIL import Image, UnidentifiedImageError

#Does not support after scrolling styling for max card height, text size (set in html), made by, and other styles

app = Flask(__name__)

CARDS_PER_PAGE = 100
CARD_PREVIEW_SIZE = (300, 300)

parser = argparse.ArgumentParser()
parser.add_argument('--autoupdate', type=int, default=300, nargs='?', const=60, help='Auto-update interval in seconds')
parser.add_argument('--synctags', action='store_true', default=False, help='Enable tag synchronization')
parser.add_argument('--backup', action='store_true', default=False, help='Backup old cards to /backup')
parser.add_argument('--min_tags', type=int, default=0, help='Minimum number of tags for card to be saved')
parser.add_argument('--include_tags', type=str, default="", help='Only downloads cards with specified tags (comma-separated)')
parser.add_argument('--exclude_tags', type=str, default="nonenglish", help='Comma-separated list of tags to exclude on download')
sorting_methods = [
    'download_count', 'id', 'rating', 'default', 'rating_count', 
    'last_activity_at', 'trending_downloads', 'n_favorites', 'created_at', 
    'star_count', 'msgs_chat', 'msgs_user', 'chats_user', 'name', 'timeline', 
    'n_tokens', 'random', 'trending', 'newcomer', 'favorite_time', 'ai_rating'
]
parser.add_argument('--sorting', type=str, default='last_activity_at', choices=sorting_methods, help=f'Sorting method (default: last_activity_at). Options: {", ".join(sorting_methods)}')
parser.add_argument('--allow_nsfw', action='store_true', default=True, help='Include NSFW items in the result')
parser.add_argument('--allow_nsfl', action='store_true', default=True, help='Include NSFL items in the result')
parser.add_argument('--min_tokens', type=int, default=250, help='Minimum total token count of the card')
parser.add_argument('--max_tokens', type=int, default=128000, help='Maximum total token count of the card')
parser.add_argument('--include_forks', action='store_true', default=False, help='Download forks as well as root cards')
parser.add_argument('--require_expressions', action='store_true', default=False, help='Require an expression pack')
parser.add_argument('--require_lore_embedded', action='store_true', default=False, help='Require either an embedded lorebook')
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
            requests.get('http://127.0.0.1:1488/sync?c=20')
        except requests.ConnectionError:
            pass
        autoupdEvent.wait(autoupdInterval)


def deleteCard(cardId):
    for ext in ['png', 'json']:
        os.remove(f'static/{cardId}.{ext}')

def getCardMetadata(cardId):
    with open(f'static/{cardId}.json', 'r', encoding='utf-8') as f:
        metadata = json.load(f)
        return metadata

def getPngInfo(cardId):
    with open(f'static/{cardId}.png', 'rb') as f:
        img = Image.open(f)
        return json.loads(base64.b64decode(img.png.im_info['chara']).decode('utf-8'))

def pngCheck(cardId):
    try:
        Image.open(f'static/{cardId}.png').format == 'PNG'
        return True
    except UnidentifiedImageError:
        return False

def createCardEntry(metadata):
    # Remove HTML tags and unwanted characters from the description using regex
    cleaned_description = re.sub(r'<[^>]+>', '', metadata['description'])  # Remove all HTML tags
    cleaned_description = re.sub(r'\s+', ' ', cleaned_description)  # Replace multiple spaces with a single space
    cleaned_description = cleaned_description.strip()  # Strip leading and trailing whitespace

    # Same for tagline (short description)
    cleaned_tagline = re.sub(r'<[^>]+>', '', metadata['tagline'])  # Remove all HTML tags
    cleaned_tagline = re.sub(r'\s+', ' ', cleaned_tagline)  # Replace multiple spaces with a single space
    cleaned_tagline = cleaned_description.strip()  # Strip leading and trailing whitespace

    return {
        'id': metadata['id'],
        'author': metadata['fullPath'].split('/')[0],
        'name': metadata['name'],
        'tagline': cleaned_tagline,
        'description': cleaned_description,  # Use the cleaned description
        'topics': [topic for topic in metadata['topics'] if topic != 'ROOT'],
        'imagePath': f'static/{metadata["id"]}.png',
        'tokenCount': metadata['nTokens'],
        'lastActivityAt': datetime.datetime.strptime(metadata['lastActivityAt'], "%Y-%m-%dT%H:%M:%SZ").strftime("%b %d, %Y %H:%M"),
        'createdAt': datetime.datetime.strptime(metadata['createdAt'], "%Y-%m-%dT%H:%M:%SZ").strftime("%b %d, %Y %H:%M")
    }

def getCardList(page, query=None, searchType='basic', sort_by='createdAt'):
    cards = []
    cardIds = sorted([int(file.split('.')[0]) for file in os.listdir('static') if file.lower().endswith('.png')], reverse=True)
    count = len(cardIds)
    randomTags = set()

    # Apply sorting based on the user's choice
    if sort_by == 'lastActivityAt':
        cardIds.sort(key=lambda x: datetime.datetime.strptime(getCardMetadata(x)['lastActivityAt'], "%Y-%m-%dT%H:%M:%SZ"), reverse=True)
    if sort_by == 'createdAt':
        cardIds.sort(key=lambda x: datetime.datetime.strptime(getCardMetadata(x)['createdAt'], "%Y-%m-%dT%H:%M:%SZ"), reverse=True)
    else:
        cardIds.sort(reverse=True)
    
    if query:
        include_tags = set()
        exclude_tags = set()
        
        for tag in query.lower().split(','):
            tag = tag.strip()
            if tag.startswith('-'):
                exclude_tags.add(tag[1:].strip())  # Remove the '-' and add to exclude list
            else:
                include_tags.add(tag.strip())

        filtered_cards = []
        
        for cardId in cardIds:
            metadata = getCardMetadata(cardId)
            card_tags = set(tag.lower() for tag in metadata['topics'])
            randomTags.update(card_tags)

            # Inclusion logic
            if include_tags and not include_tags.issubset(card_tags):
                continue  # Skip if any included tag is missing
            
            # Exclusion logic
            if exclude_tags and not exclude_tags.isdisjoint(card_tags):
                continue  # Skip if any excluded tag is found
            
            filtered_cards.append(createCardEntry(metadata))

        # Fix: Use full filtered list count, not total dataset count
        filtered_count = len(filtered_cards)

        # Pagination logic for search
        startIndex = (page - 1) * CARDS_PER_PAGE
        endIndex = startIndex + CARDS_PER_PAGE
        paginated_cards = filtered_cards[startIndex:endIndex]

        total_pages = (filtered_count // CARDS_PER_PAGE) + (1 if filtered_count % CARDS_PER_PAGE else 0)

        return paginated_cards, filtered_count, total_pages, randomTags

    else:
        startIndex = (page - 1) * CARDS_PER_PAGE
        endIndex = startIndex + CARDS_PER_PAGE
        for cardId in cardIds[startIndex:endIndex]:
            metadata = getCardMetadata(cardId)
            if metadata:
                randomTags.update(metadata['topics'])
                cards.append(createCardEntry(metadata))

    total_pages = (count // CARDS_PER_PAGE) + (1 if count % CARDS_PER_PAGE else 0)
    return cards, count, total_pages, randomTags


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

@app.route('/static/<path:filename>', methods=['GET'])
def image(filename):
    return send_from_directory('static', filename)

@app.route('/get_png_info/<cardId>', methods=['GET'])
def get_png_info(cardId):
    png_info = getPngInfo(cardId)
    return jsonify(png_info)

@app.route('/', methods=['GET'])
def index():
    page = int(request.args.get('page', 1))
    query = request.args.get('query')
    searchType = request.args.get('type', 'basic')
    sort_by = request.args.get('sort', 'createdAt')

    cards, count, total_pages, randomTags = getCardList(page, query, searchType)

    search_results = cards if query else None  # Only store paginated results

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

@app.route('/sync', methods=['GET'])
def syncCards():
    totalCards, currCard, newCards = int(request.args.get('c', 500)), 0, 0
    cardIds = sorted([int(file.split('.')[0]) for file in os.listdir('static') if file.lower().endswith('.png')], reverse=True)

    def should_skip_card(card):
        for label in card.get("labels", []):
            if label.get("title") == "TOKEN_COUNTS":
                try:
                    description_data = json.loads(label.get("description", "{}"))
                    if description_data.get("total") in [1630, 5872, 3199, 1678, 3199, 2389, 2625]:
                        return True
                except json.JSONDecodeError:
                    pass
        
        name_symbols = [
            # Chinese (HSK 1-2)
            "我", "你", "他", "她", "它", "我们", "你们", "他们", "她们", "这", "那", "是", "不", "了", "在", "有", "没有", "说", "问", "知道", 
            "做", "看", "听", "想", "来", "去", "吃", "喝", "买", "卖", "高", "低", "大", "小", "多", "少", "新", "旧", "长", "短", "快", "慢",
            "高", "低", "重", "轻", "早", "晚", "前", "后", "左", "右", "中", "上", "下", "开", "关", "笑", "哭", "跳", "跑", "走", "打", "玩",
            # Japanese (Jōyō kanji)
            "日", "月", "木", "水", "火", "金", "土", "人", "子", "女", "男", "大", "小", "中", "上", "下", "左", "右", "前", "後", "生", 
            "学", "年", "今", "時", "分", "半", "長", "短", "多", "少", "高", "低", "新", "古", "青", "赤", "白", "黒", "雨", "雪", "風", 
            "道", "駅", "車", "電", "話", "読", "書", "行", "来", "食", "飲", "買", "売", "見", "聞", "思", "考", "知", "愛", "友", "家", 
            # Korean (Hangul syllables)
            "가", "나", "다", "라", "마", "바", "사", "아", "자", "차", "카", "타", "파", "하", "거", "너", "더", "러", "머", "버", "서",
            "어", "저", "처", "커", "터", "퍼", "허", "고", "노", "도", "로", "모", "보", "소", "오", "조", "초", "코", "토", "포", "호",
            "구", "누", "두", "루", "무", "부", "수", "우", "주", "추", "쿠", "투", "푸", "후", "기", "니", "디", "리", "미", "비", "시", 
            "이", "지", "치", "키", "티", "피", "히", "가", "나", "다", "라", "마", "바", "사", "아", "자", "차", "카", "타", "파", "하",
            # Custom dict (collected from various bots)
            "空", "格", "一", "是", "的", "雌", "小", "鬼", "妹", "妹", "縉", "雲", "本", "角", "色", "卡", "免", "费", "发", "布", "于", "类", "脑", "服", "务", "器", "未", "经", "允", "许", "禁", "止", "搬", "运", "或", "用", "于", "盈", "利", "贩", "卖", "将", "在", "此", "处", "更", "新", "后", "续", "版", "本", "在", "性", "爱", "医", "院", "工", "作", "的", "妈", "妈", "地", "牢", "之", "主", "庄", "晓", "飞", "机", "杯", "魅", "魔", "调", "教", "系", "统", "更", "世", "界", "设", "定", "中", "实", "装", "性", "格", "女", "性", "姓", "名", "庄", "园", "详", "细", "注", "意", "加", "载", "世", "界", "书", "开", "局", "示", "例", "生", "成", "一", "个", "强", "势", "性", "格", "身", "材", "高", "挑", "御", "姐", "型", "恶", "魔", "白", "长", "发", "有", "角", "进", "来", "佩", "佩", "约", "书", "娅"
            ]
        if any(symbol in card.get("name", "") for symbol in name_symbols):
            return True

        # description_symbols = ['优', '化', '了', '内', '容', '显', '示']
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
                        if not os.path.exists('backup'): os.mkdir('backup')
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
            'first': totalCards, 
            'page': f'{page}', 
            'sort': sorting, 
            'asc': 'false', 
            'nsfw': allow_nsfw, 
            'nsfl': allow_nsfl, 
            'min_tokens': min_tokens, 
            'max_tokens': max_tokens, 
            'include_forks': include_forks, 
            'min_tags': min_tags, 
            'tags': include_tags, 
            'exclude_tags': exclude_tags, 
            'require_expressions': require_expressions, 
            'require_lore_embedded': require_lore_embedded}, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'}).json()
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

    return jsonify({
        'cards': cards,
        'page': page,
        'total_pages': total_pages
    })

@app.route('/sort', methods=['GET'])
def sort_cards():
    page = int(request.args.get('page', 1))
    query = request.args.get('query')
    searchType = request.args.get('type', 'basic')
    sort_by = request.args.get('sort', 'createdAt')

    cards, count, total_pages, randomTags = getCardList(page, query, searchType, sort_by)

    return jsonify({
        'cards': cards,
        'total_pages': total_pages
    })

if __name__ == '__main__':
    if autoupdMode and not autoupdRunning:
        autoupdRunning = True
        autoupdThread = threading.Thread(target=autoUpdate, daemon=True)
        autoupdThread.start()

    app.run(debug=False, port=1488)
