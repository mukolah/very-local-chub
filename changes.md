------------
Fork of [ayofreaky/local-chub](https://github.com/ayofreaky/local-chub "ayofreaky/local-chub")
------------

## What's new:
- ⚠️ **Improved privacy**: loading anything from external resources is no longer allowed
- Replaced "pages" with lazy loading (**infinite scroll**)
- **Tags can now be excluded** during search by using a minus "-", for example, -rpg
- Lifted restrictions on card downloads to **properly pull all cards**
- **Better vertical card containment** to prevent extra long cards due to their description
- **Added a bunch of command line options** to make sync "yours"
- Blocked any code and styling applied within card description (gone those highway long animated descriptions)
- Search is no longer loading all cards on one page (added pagination and infinite scroll)
- Search result shows the accurate number of cards found
- Search will pull existing tags as you type (depending on the cards that you have)
- The large tag list (at the top of the page) is hidden by default and can be shown by pressing T in the menu
- Limited cards auto-update to first chub page (20 cards)
- Auto-update enabled by default with a 5-minute interval
- Updated API endpoint to inference version
- Skip spam-bot and non-Eng cards
- Sort results by date card created instead of last updated to provide consistent results

- Visit http://127.0.0.1:1488/sync?c=200 where the number after c= is the number of cards you want to update/download (based on last update)

------------

## Screenshots  

<img align="left" width="100%" src="https://github.com/mukolah/other_storage/blob/main/app1/very-local-chub.jpg?raw=true">

------------

## Run Locally  

Clone the project  

```
git clone https://github.com/mukolah/very-local-chub.git
```

Go to the project directory  

```
cd very-local-chub
```

Install dependencies  

```
pip install -r requirements.txt
```

Start the server  

```
python localchub.py
```

Connect to the local server 

http://127.0.0.1:1488

------------

## Commands: 

`python localchub.py --autoupdate 300 --min_tokens 200 --include_forks false`

`--synctags` sync/overwrite user tags
`--autoupdate %s` auto update loop (default=300 / Activated)
`--backup` backup old cards to /backup
`--min_tags` minimum number of tags for card to be saved (default=0)
`--include_tags` only downloads cards with specific tags, comma-separated (default="")
`--exclude_tags` comma-separated list of tags to exclude on download (default="nonenglish")
`--sorting` what sorting method to use when downloading list of cards (default=last_activity_at). Options: download_count, id, rating, default, rating_count, last_activity_at, trending_downloads, n_favorites, created_at, star_count, msgs_chat, msgs_user, chats_user, name, timeline, n_tokens, random, trending, newcomer, favorite_time, ai_rating
`--allow_nsfw` whether to include NSFW items in the result (default=true)
`--allow_nsfl` whether to include NSFL items in the result (default=true)
`--min_tokens` the minimum total token count of the card (default=250)
`--max_tokens` the maximum total token count of the card (default=128000)
`--include_forks` whether to download forks or only root cards (default=false)
`--require_expressions` whether to require an expression pack (default=false)
`--require_lore_embedded` whether to require either an embedded lorebook (default=false)

To show help run:
`python localchub.py -h`