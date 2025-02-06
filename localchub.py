import os, json, base64, requests, re, random, argparse, time, threading, datetime
from flask import Flask, render_template, request, send_from_directory, jsonify, Response
from PIL import Image, UnidentifiedImageError

app = Flask(__name__)

CARDS_PER_PAGE = 100
CARD_PREVIEW_SIZE = (300, 300)

parser = argparse.ArgumentParser()
parser.add_argument('--autoupdate', type=int, default=300, nargs='?', const=60, help='Auto-update interval in seconds')
parser.add_argument('--synctags', action='store_true', default=False, help='Enable tag synchronization')
parser.add_argument('--backup', action='store_true', default=False, help='Backup old cards to /backup')
args = parser.parse_args()
autoupdInterval = args.autoupdate
autoupdMode = args.autoupdate is not None
synctagsMode = args.synctags
backupMode = args.backup
autoupdThread = None

def autoUpdate():
    while True:
        print(f'[autoupdate/{autoupdInterval}s] Updating cards..')
        try:
            requests.get('http://127.0.0.1:1488/sync?c=20')
        except requests.ConnectionError:
            pass
        time.sleep(autoupdInterval)

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
    return {
        'id': metadata['id'],
        'author': metadata['fullPath'].split('/')[0],
        'name': metadata['name'],
        'tagline': metadata['tagline'],
        'description': metadata['description'].replace('Creator\'s notes go here.', '\n'),
        'topics': [topic for topic in metadata['topics'] if topic != 'ROOT'],
        'imagePath': f'static/{metadata["id"]}.png',
        'tokenCount': metadata['nTokens'],
        'lastActivityAt': datetime.datetime.strptime(metadata['lastActivityAt'], "%Y-%m-%dT%H:%M:%SZ").strftime("%B %d, %Y %H:%M")
    }

def getCardList(page, query=None, searchType='basic'):
    cards = []
    cardIds = sorted([int(file.split('.')[0]) for file in os.listdir('static') if file.lower().endswith('.png')], reverse=True)
    count = len(cardIds)
    randomTags = set()
    
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

    def dlCard(card):
        nonlocal newCards, currCard
        cardId = card['id']
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
        r = requests.get('https://api.chub.ai/search', params={'first': totalCards, 'page': f'{page}', 'sort': 'last_activity_at', 'venus': 'false', 'asc': 'false', 'nsfw': 'true', 'min_tokens': '500', 'include_forks': 'false'}, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'}).json()
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

    cards, count, total_pages, _ = getCardList(page, query, searchType)

    return jsonify({
        'cards': cards,
        'page': page,
        'total_pages': total_pages
    })


if __name__ == '__main__':
    if autoupdMode:
        autoupdThread = threading.Thread(target=autoUpdate)
        autoupdThread.daemon = True
        autoupdThread.start()

    app.run(debug=True, port=1488)
