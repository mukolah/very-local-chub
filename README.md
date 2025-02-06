------------
Fork of [ayofreaky/local-chub](https://github.com/ayofreaky/local-chub "ayofreaky/local-chub")

------------

## What's new:
- ⚠️ **Improved privacy**: loading anything from external resources is no longer allowed
- Replaced "pages" with lazy loading (**infinite scroll**)
- **Tags can now be excluded** during search by using a minus "-", for example, -rpg
- **Better vertical card containment** to prevent extra long cards due to their description
- Search is no longer loading all cards on one page (added pagination and infinite scroll)
- Search result shows the number of cards found
- Search will pull existing tags as you type (depending on the cards that you have)
- The tag list is hidden by default and can be shown by pressing T in the menu
- Limited cards auto-update to first chub page (20 cards)
- Auto-update enabled by default with a 5 minute interval
- Visit http://127.0.0.1:1488/sync?c=200 where the number after c= is the number of cards you want to update/download chronologically

------------

## Commands: 
`--synctags` sync/overwrite user tags
`--autoupdate %s` auto update loop (default=300) **- activated by default**
`--backup` backup old cards to /backup
`python localchub.py --synctags --backup --autoupdate 300`
