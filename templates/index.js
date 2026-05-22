// Server-injected data (set in index.html before this script loads)
// window.APP_DATA = { totalPages, searchQuery }

// ── Global state ──────────────────────────────────────────
let blurNSFW = localStorage.getItem('blurNSFW') === 'true';
let currentPage = 1;
let totalPages = window.APP_DATA.totalPages;
let isLoading = false;
let currentQuery = '';
let currentType = 'tag';
let currentSort = 'lastActivityAt';

// ── Preload cache ─────────────────────────────────────────
const PRELOAD_AHEAD = 10;
const PRELOAD_TRIGGER = 5;
const pageCache = new Map();         // page# → resolved data
const preloadPromises = new Map();   // page# → in-flight Promise
let preloadRunning = false;

function buildPageUrl(page) {
    const params = new URLSearchParams(window.location.search);
    params.set('page', page);
    params.set('sort', currentSort);
    return `/load_more?${params.toString()}`;
}

// Returns an existing in-flight promise or starts a new fetch.
// Callers can await this to get the data without launching a duplicate request.
function fetchPage(page) {
    if (preloadPromises.has(page)) return preloadPromises.get(page);
    const p = fetch(buildPageUrl(page))
        .then(r => r.json())
        .then(data => {
            pageCache.set(page, data);
            preloadPromises.delete(page);
            if (data.total_pages) totalPages = data.total_pages;
            return data;
        })
        .catch(err => { preloadPromises.delete(page); throw err; });
    preloadPromises.set(page, p);
    return p;
}

function getHighestScheduled() {
    let h = currentPage;
    for (const p of pageCache.keys())      if (p > h) h = p;
    for (const p of preloadPromises.keys()) if (p > h) h = p;
    return h;
}

// Sequential chain: fetches one page at a time to avoid hammering the server.
async function runPreloadChain() {
    if (preloadRunning) return;
    preloadRunning = true;
    try {
        let fetched = 0, p = currentPage + 1;
        while (fetched < PRELOAD_AHEAD && p <= totalPages) {
            if (!pageCache.has(p) && !preloadPromises.has(p)) {
                await fetchPage(p);
                fetched++;
            }
            p++;
        }
    } finally {
        preloadRunning = false;
        // Re-check in case currentPage advanced while the chain was running.
        maybeTriggerPreload();
    }
}

function maybeTriggerPreload() {
    if (getHighestScheduled() - currentPage <= PRELOAD_TRIGGER) runPreloadChain();
}

function clearPageCache() {
    pageCache.clear();
    preloadPromises.clear();
    preloadRunning = false;
}

// Tag manager state
let tmTagData = [];
let tmSelected = new Set();
let tmTagMeta = {};
let showBanned = false;
let tmDDActiveIndex = -1;

// Apply dark mode before first paint to avoid flash
if (localStorage.getItem('darkMode') === 'true') {
    document.body.classList.add('dark-mode');
    document.body.classList.remove('light-mode');
}

// ── Dark mode ─────────────────────────────────────────────
function toggleDarkMode() {
    document.body.classList.toggle('dark-mode');
    document.body.classList.toggle('light-mode');
    localStorage.setItem('darkMode', document.body.classList.contains('dark-mode').toString());
}

// ── NSFW blur ─────────────────────────────────────────────
function updateNSFWToggle() {
    const btn = document.getElementById('nsfwToggle');
    if (btn) btn.innerHTML = blurNSFW ? '😇' : '😈';
}

function toggleBlur() {
    blurNSFW = !blurNSFW;
    applyBlurringPreference();
    updateNSFWToggle();
    localStorage.setItem('blurNSFW', blurNSFW);
}

function applyBlurringPreference() {
    document.querySelectorAll('.card-container').forEach(card => {
        const tagsLinks = card.querySelectorAll('#tags a');
        const containsNSFW = Array.from(tagsLinks).some(a =>
            a.textContent.trim() === 'NSFW' ||
            (a.dataset.originalTag && a.dataset.originalTag.toUpperCase() === 'NSFW')
        );
        const img = card.querySelector('.card-image');
        if (img) img.style.filter = blurNSFW && containsNSFW ? 'blur(12px)' : 'none';
    });
}

// ── Download ──────────────────────────────────────────────
function downloadImage(imagePath) {
    const cardId = imagePath.split('/').pop().split('.').shift();
    const filename = cardId + '.png';
    fetch(imagePath)
        .then(r => r.blob())
        .then(blob => {
            const url = URL.createObjectURL(new Blob([blob], { type: 'image/png' }));
            const link = document.createElement('a');
            link.href = url;
            link.download = filename;
            link.click();
            URL.revokeObjectURL(url);
        })
        .catch(err => console.error('Error fetching the image:', err));
}

// ── Search highlight ──────────────────────────────────────
function escapeRegExp(str) {
    return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function highlightSearchResults() {
    const searchQuery = window.APP_DATA.searchQuery || '';
    if (!searchQuery) return;
    const highlightColor = '#a9a9a9a9';
    const tagQueries = searchQuery.trim().split(',').map(q => q.trim()).filter(Boolean);
    if (!tagQueries.length) return;
    const tagRegex = new RegExp(tagQueries.map(escapeRegExp).join('|'), 'gi');

    document.querySelectorAll('.card-container').forEach(card => {
        card.querySelectorAll('.card-content i a, .card-content h3, .card-content #descr, #description, #tagline')
            .forEach(el => {
                el.innerHTML = el.textContent.replace(
                    tagRegex,
                    match => `<span style="background-color: ${highlightColor};">${match}</span>`
                );
            });
    });
}

// ── Lightbox ──────────────────────────────────────────────
const lightbox = document.getElementById('lightbox');
const lightboxImage = document.getElementById('lightboxImage');
const lightboxDescription = document.getElementById('lightboxDescription');

function showLightbox(imagePath) {
    lightboxImage.src = imagePath;
    lightboxDescription.innerHTML = '';
    const cardId = imagePath.split('/').pop().split('.').shift();
    fetch(`/get_png_info/${cardId}`)
        .then(r => r.json())
        .then(data => {
            for (const [key, value] of Object.entries(data.data || {})) {
                if (value !== null && value !== '' && value !== undefined && value !== 'none' && String(value).length > 0) {
                    const label = key.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
                    lightboxDescription.innerHTML += `<h2>${label}:</h2> ${value}<br>`;
                }
            }
            lightbox.style.display = 'flex';
        })
        .catch(err => console.error('Error fetching PNG info:', err));
}

function hideLightbox() {
    lightbox.style.display = 'none';
}

function attachLightboxListeners(cardContainer) {
    const img = cardContainer.querySelector('.card-image');
    const title = cardContainer.querySelector('.card-content h3');
    if (!img || !title) return;
    const open = () => showLightbox(img.src);
    img.addEventListener('click', open);
    title.addEventListener('click', open);
}

lightbox.addEventListener('click', e => {
    if (e.target === lightbox || e.target === lightboxImage || e.target === lightboxDescription) {
        hideLightbox();
    }
});

// ── Sync / progress ───────────────────────────────────────
function updProgress(progress, currentCardName, newCardsCount) {
    document.getElementById('progress').innerText = `\nSyncing progress: ${progress.toFixed(2)}%`;
    document.getElementById('currentCardName').innerText = `Current Card: ${currentCardName}`;
    if (progress >= 100) {
        const msg = newCardsCount > 0
            ? `Syncing completed! ${newCardsCount} cards have been added/updated.`
            : 'Syncing completed! No cards have been added/updated.';
        alert(msg);
        window.location.reload();
        window.scrollTo(0, 0);
    }
}

function syncCards() {
    updProgress(0, '', 0);
    const eventSource = new EventSource('/sync');
    eventSource.onmessage = function (e) {
        const { progress, currCard, newCards } = JSON.parse(e.data);
        updProgress(progress, currCard, newCards);
        if (progress >= 100) eventSource.close();
    };
    eventSource.onerror = function () {
        alert('Error syncing cards. Please try again later.');
        eventSource.close();
    };
}

// ── Card button visibility ────────────────────────────────
function showButtons(cardContainer) {
    cardContainer.querySelectorAll('.action-button').forEach(b => b.style.visibility = 'visible');
}

function hideButtons(cardContainer) {
    cardContainer.querySelectorAll('.action-button').forEach(b => b.style.visibility = 'hidden');
    hideEditTags(cardContainer);
    cardContainer.querySelectorAll('.rating-widget').forEach(w => w.style.display = 'none');
}

// ── Tag editing ───────────────────────────────────────────
function showEditTags(editButton, existingTags) {
    const card = editButton.closest('.card-container');
    const container = card.querySelector('.edit-tags-container');
    card.querySelector('.edit-tags-input').value = existingTags;
    container.style.display = 'flex';
}

function hideEditTags(cardContainer) {
    cardContainer.querySelector('.edit-tags-container').style.display = 'none';
}

function saveTags(cardId) {
    const container = document.getElementById(`card-${cardId}`).querySelector('.edit-tags-container');
    const tags = container.querySelector('.edit-tags-input').value.trim();
    fetch(`/edit_tags/${cardId}`, {
        method: 'POST',
        body: new URLSearchParams({ tags }),
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
        .then(r => {
            if (r.status === 200) {
                container.style.display = 'none';
                container.previousElementSibling.innerHTML = `<i>Tags: ${tags.split(',').map(t => `<a href='?query=${t.trim()}'>${t.trim()}</a>`).join(', ')}</i>`;
                alert('Tags updated successfully');
            } else {
                alert('Error updating tags. Please try again later.');
            }
        })
        .catch(err => { console.error('Error updating tags:', err); alert('Error updating tags. Please try again later.'); });
}

// ── Card actions ──────────────────────────────────────────
function deleteCard(cardId) {
    if (!confirm('Are you sure you want to delete this card?')) return;
    fetch(`/delete_card/${cardId}`, { method: 'DELETE' })
        .then(r => {
            if (r.status === 200) {
                document.getElementById(`card-${cardId}`)?.remove();
                alert('Card deleted successfully');
            } else {
                alert('Error deleting the card. Please try again later.');
            }
        })
        .catch(err => { console.error('Error deleting the card:', err); alert('Error deleting the card. Please try again later.'); });
}

function copyJSON(cardId, button) {
    fetch('/get_png_info/' + cardId)
        .then(r => r.json())
        .then(data => {
            navigator.clipboard.writeText(JSON.stringify(data, null, 4))
                .then(() => {
                    button.innerHTML = '✓';
                    setTimeout(() => button.innerHTML = '📋', 2000);
                })
                .catch(err => console.error('Failed to copy JSON:', err));
        });
}

function openInNewTab(cardId) {
    const tab = window.open(`/get_card_info/${cardId}`, '_blank');
    if (tab) tab.focus();
}

// ── Scroll utilities ──────────────────────────────────────
function scrollToTop() { window.scrollTo({ top: 0, behavior: 'smooth' }); }
function scrollToBottom() { window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' }); }

// ── Compact mode ──────────────────────────────────────────
function applyCompactModePreference() {
    const compact = localStorage.getItem('compactMode') === 'true';
    document.querySelectorAll('.card-container').forEach(card => {
        const desc = card.querySelector('.card-content #description');
        if (desc) desc.style.display = compact ? 'none' : 'block';
    });
}

function toggleCompactMode() {
    const compact = localStorage.getItem('compactMode') === 'true';
    document.querySelectorAll('.card-container').forEach(card => {
        const desc = card.querySelector('.card-content #description');
        if (desc) desc.style.display = compact ? 'block' : 'none';
    });
    localStorage.setItem('compactMode', compact ? 'false' : 'true');
}

// ── Rating widget ─────────────────────────────────────────

function toggleRatingWidget(type, cardId) {
    const card = document.getElementById(`card-${cardId}`);
    if (!card) return;
    const widget = card.querySelector(`.rating-${type}-widget`);
    if (!widget) return;
    const isOpen = widget.style.display === 'flex';
    // Close all open rating widgets in this card first
    card.querySelectorAll('.rating-widget').forEach(w => w.style.display = 'none');
    if (!isOpen) {
        widget.style.display = 'flex';
        initRatingWidget(widget);
    }
}

function initRatingWidget(widget) {
    if (widget.dataset.initialized) return;
    widget.dataset.initialized = '1';

    const cardId = widget.dataset.card;
    const type = widget.dataset.type;
    const stars = Array.from(widget.querySelectorAll('span.rating-star'));
    const clearBtn = widget.querySelector('span.rating-clear-btn');
    let hoverValue = 0;

    stars.forEach((span, idx) => {
        const n = idx + 1;
        span.addEventListener('mousemove', e => {
            const isLeft = e.offsetX < span.offsetWidth / 2;
            hoverValue = isLeft ? Math.max(0.5, n - 0.5) : n;
            updateRatingDisplay(stars, hoverValue);
        });
        span.addEventListener('click', () => {
            if (hoverValue > 0) submitRating(cardId, type, hoverValue);
        });
    });

    if (clearBtn) {
        clearBtn.addEventListener('click', () => clearRating(cardId, type));
    }

    widget.addEventListener('mouseleave', () => {
        hoverValue = 0;
        updateRatingDisplay(stars, 0);
    });
}

function updateRatingDisplay(spans, value) {
    spans.forEach((span, idx) => {
        const n = idx + 1;
        if (value === 0) {
            span.style.opacity = '0.35';
        } else if (n <= Math.floor(value)) {
            span.style.opacity = '1';
        } else if (n === Math.ceil(value) && value % 1 !== 0) {
            span.style.opacity = '0.55'; // half
        } else {
            span.style.opacity = '0.2';
        }
    });
}

function initAllRatingWidgets(container) {
    container.querySelectorAll('.rating-widget').forEach(initRatingWidget);
}

async function submitRating(cardId, type, value) {
    const body = {};
    body[type] = value;
    try {
        const resp = await fetch(`/api/scores/${cardId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const data = await resp.json();
        updateCardScoreDisplay(cardId, data);
    } catch (e) {
        console.error('Error submitting rating:', e);
    }
}

function updateCardScoreDisplay(cardId, data) {
    const cardDiv = document.getElementById(`card-${cardId}`);
    if (!cardDiv) return;
    const h3 = cardDiv.querySelector('.card-content h3');

    const parts = [data.quality_bar, data.lewdity_bar, data.story_bar].filter(Boolean);
    let scoresDiv = cardDiv.querySelector('.card-scores');
    if (parts.length) {
        if (!scoresDiv) {
            scoresDiv = document.createElement('div');
            scoresDiv.className = 'card-scores';
            h3.insertAdjacentElement('afterend', scoresDiv);
        }
        scoresDiv.innerHTML = parts.join(' | ');
    } else if (scoresDiv) {
        scoresDiv.remove();
    }

    // Close all open rating widgets
    cardDiv.querySelectorAll('.rating-widget').forEach(w => { w.style.display = 'none'; });
}

async function clearRating(cardId, type) {
    try {
        const resp = await fetch(`/api/scores/${cardId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ [type]: null })
        });
        const data = await resp.json();
        updateCardScoreDisplay(cardId, data);
    } catch (e) {
        console.error('Error clearing rating:', e);
    }
}

// ── Card HTML builder (used by loadMoreCards and handleSortChange) ──
function buildScoreBarsHTML(card) {
    const parts = [card.quality_bar, card.lewdity_bar, card.story_bar].filter(Boolean);
    if (!parts.length) return '';
    return `<div class="card-scores">${parts.join(' | ')}</div>`;
}

function buildRatingButtonsHTML(card) {
    const starWidget = (emoji, type) =>
        `<span class='rating-star'>${emoji}</span>`.repeat(5) + `<span class='rating-clear-btn'>🗙</span>`;
    return (
        `<button class='action-button rate-btn rate-quality-btn' onclick="toggleRatingWidget('quality','${card.id}')" title='Rate quality'>⭐</button>` +
        `<div class='rating-widget rating-quality-widget' data-card='${card.id}' data-type='quality'>${starWidget('⭐')}</div>` +
        `<button class='action-button rate-btn rate-lewdity-btn' onclick="toggleRatingWidget('lewdity','${card.id}')" title='Rate lewdity'>🍑</button>` +
        `<div class='rating-widget rating-lewdity-widget' data-card='${card.id}' data-type='lewdity'>${starWidget('🍑')}</div>` +
        `<button class='action-button rate-btn rate-story-btn' onclick="toggleRatingWidget('story','${card.id}')" title='Rate story'>📖</button>` +
        `<div class='rating-widget rating-story-widget' data-card='${card.id}' data-type='story'>${starWidget('📖')}</div>`
    );
}

function createCardHTML(card) {
    const topicsHTML = card.topics.length > 0
        ? `<p id='tags'><i>Tags: ${card.topics.map(t => `<a href='?query=${t}&type=tag' title='Browse other cards tagged with ${t}'>${t}</a>`).join(', ')}</i></p>`
        : '';
    return `
        <button class='action-button delete-card-button' onclick='deleteCard("${card.id}")' title='Delete card'>🗙</button>
        <button class='action-button edit-tags-button' onclick="showEditTags(this, '${card.topics.join(',')}')" title='Edit tags'>✎</button>
        <div class='edit-tags-container'>
            <input type='text' class='edit-tags-input'>
            <button class='save-tags-button' onclick='saveTags("${card.id}")'>Save</button>
        </div>
        <button class='action-button copy-json-button' onclick="copyJSON('${card.id}', this)" title="Copy JSON">📋</button>
        <button class='action-button open-new-tab-button' onclick="openInNewTab('${card.id}')" title="Open in new tab">↗️</button>
        ${buildRatingButtonsHTML(card)}
        <img src='${card.imagePath}' alt='${card.name}' class='card-image' title='Click for details'>
        <div class='card-content'>
            <h3 title='${card.lastActivityAt}'>${card.name}</h3>
            ${buildScoreBarsHTML(card)}
            <p class='card-meta'>by <a href='?query=${card.author}&type=author' title='Browse all cards by ${card.author}'>${card.author}</a> | ${card.tokenCount} tokens</p>
            <p class='card-dates'><span title="Created by Author date/time">⚒ ${card.createdAt}</span> | <span title="Last update by Author date/time">🗘 ${card.lastActivityAt}</span></p>
            <button class='download-btn' onclick='downloadImage("${card.imagePath}")'>Download</button>
            ${topicsHTML}
            <div id='descr'>
                ${card.tagline ? `<p id='tagline'>${card.tagline}</p>` : ''}
                ${card.description ? `<p id='description'>${card.description}</p>` : ''}
            </div>
        </div>`;
}

function makeCardDiv(card) {
    const div = document.createElement('div');
    div.className = 'card-container';
    div.id = `card-${card.id}`;
    div.dataset.tags = (card.topics || []).join(',').toLowerCase();
    div.setAttribute('onmouseenter', 'showButtons(this)');
    div.setAttribute('onmouseleave', 'hideButtons(this)');
    div.innerHTML = createCardHTML(card);
    initAllRatingWidgets(div);
    return div;
}

// ── Infinite scroll ───────────────────────────────────────
function renderCards(cards) {
    const container = document.getElementById('cards-container');
    cards.forEach(card => {
        const div = makeCardDiv(card);
        container.appendChild(div);
        attachLightboxListeners(div);
    });
    applyBlurringPreference();
    applyCompactModePreference();
    applyTagMetaStyles();
    applyBanFilter();
}

async function loadMoreCards() {
    if (isLoading || currentPage >= totalPages) return;
    isLoading = true;
    const nextPage = currentPage + 1;
    try {
        let data;
        if (pageCache.has(nextPage)) {
            data = pageCache.get(nextPage);
            pageCache.delete(nextPage);
        } else {
            // Join the in-flight preload if there is one, otherwise fetch fresh.
            showLoading();
            data = await fetchPage(nextPage);
            pageCache.delete(nextPage); // fetchPage already stored it; consume now
        }
        currentPage = nextPage;
        totalPages = data.total_pages;
        renderCards(data.cards);
        maybeTriggerPreload();
    } catch (err) {
        console.error('Error loading more cards:', err);
    } finally {
        isLoading = false;
        hideLoading();
    }
}

window.addEventListener('scroll', () => {
    if (window.innerHeight + window.scrollY >= document.body.offsetHeight - 500) loadMoreCards();
});

// ── Loading indicator ─────────────────────────────────────
let _loadingCount = 0;
function showLoading() {
    _loadingCount++;
    const bar = document.getElementById('loadingBar');
    if (bar) bar.style.display = 'block';
}
function hideLoading() {
    _loadingCount = Math.max(0, _loadingCount - 1);
    if (_loadingCount === 0) {
        const bar = document.getElementById('loadingBar');
        if (bar) bar.style.display = 'none';
    }
}

// ── Search (no-reload) ────────────────────────────────────
function performSearch(params) {
    clearPageCache();
    isLoading = true;
    showLoading();
    currentPage = 1;
    params.set('page', '1');
    if (!params.get('sort')) params.set('sort', currentSort);

    fetch(`/sort?${params.toString()}`)
        .then(r => r.json())
        .then(data => {
            totalPages = data.total_pages;
            currentQuery = params.get('query') || '';
            currentSort = params.get('sort') || currentSort;
            history.pushState({}, '', `/?${params.toString()}`);

            if (data.count !== undefined) {
                const countEl = document.querySelector('.card-count');
                if (countEl) countEl.textContent = currentQuery ? `${data.count} results` : `${data.count} Cards`;
            }

            window.APP_DATA.searchQuery = currentQuery;
            const container = document.getElementById('cards-container');
            container.innerHTML = '';
            data.cards.forEach(card => {
                const div = makeCardDiv(card);
                container.appendChild(div);
                attachLightboxListeners(div);
            });
            applyBlurringPreference();
            applyCompactModePreference();
            applyTagMetaStyles();
            applyBanFilter();
            highlightSearchResults();
            isLoading = false;
            hideLoading();
            maybeTriggerPreload();
        })
        .catch(err => { console.error('Search error:', err); isLoading = false; hideLoading(); });
}

// ── Sort ──────────────────────────────────────────────────
function applySortOrder(sortValue) {
    clearPageCache();
    currentSort = sortValue;
    currentPage = 1;
    const params = new URLSearchParams(window.location.search);
    showLoading();

    params.set('page', '1');
    params.set('sort', sortValue);
    fetch(`/sort?${params.toString()}`)
        .then(r => r.json())
        .then(data => {
            totalPages = data.total_pages;
            history.pushState({}, '', `/?${params.toString()}`);
            if (data.count !== undefined) {
                const countEl = document.querySelector('.card-count');
                if (countEl) countEl.textContent = currentQuery ? `${data.count} results` : `${data.count} Cards`;
            }
            const container = document.getElementById('cards-container');
            container.innerHTML = '';
            data.cards.forEach(card => {
                const div = makeCardDiv(card);
                container.appendChild(div);
                attachLightboxListeners(div);
            });
            applyTagMetaStyles();
            applyBanFilter();
            hideLoading();
            maybeTriggerPreload();
        })
        .catch(err => { console.error('Error fetching sorted cards:', err); hideLoading(); });
}

function initSortToggle() {
    const toggle = document.getElementById('sortToggle');
    if (!toggle) return;
    toggle.querySelectorAll('.sort-opt').forEach(opt => {
        opt.classList.toggle('active', opt.dataset.val === currentSort);
    });
    toggle.addEventListener('click', () => {
        const opts = toggle.querySelectorAll('.sort-opt');
        const active = toggle.querySelector('.sort-opt.active');
        const next = active === opts[0] ? opts[1] : opts[0];
        active.classList.remove('active');
        next.classList.add('active');
        applySortOrder(next.dataset.val);
    });
}

// ── Tag metadata ──────────────────────────────────────────
async function loadTagMeta() {
    try {
        const data = await fetch('/api/tags/metadata').then(r => r.json());
        tmTagMeta = {};
        data.favourites.forEach(t => { (tmTagMeta[t] = tmTagMeta[t] || {}).is_favourite = true; });
        data.banned.forEach(t => { (tmTagMeta[t] = tmTagMeta[t] || {}).is_banned = true; });
        data.merges.forEach(m => { (tmTagMeta[m.source] = tmTagMeta[m.source] || {}).merged_into = m.target; });
    } catch (e) {
        console.error('Failed to load tag metadata:', e);
    }
}

function applyTagMetaStyles() {
    document.querySelectorAll('#tags a').forEach(a => {
        const rawTag = (a.dataset.originalTag || a.textContent.trim()).toLowerCase();
        const meta = tmTagMeta[rawTag];
        if (meta && meta.merged_into) {
            if (!a.dataset.originalTag) a.dataset.originalTag = rawTag;
            a.textContent = meta.merged_into;
        } else if (a.dataset.originalTag) {
            a.textContent = a.dataset.originalTag;
        }
        a.classList.toggle('tag-favourite', !!(meta && meta.is_favourite));
    });
}

function applyBanFilter() {
    const bannedSet = new Set(Object.entries(tmTagMeta).filter(([, v]) => v.is_banned).map(([k]) => k));
    const mergeMap = Object.fromEntries(
        Object.entries(tmTagMeta).filter(([, v]) => v.merged_into).map(([k, v]) => [k, v.merged_into])
    );
    document.querySelectorAll('.card-container').forEach(card => {
        if (bannedSet.size === 0 || showBanned) {
            if (card.dataset.hiddenByBan) { card.style.display = ''; delete card.dataset.hiddenByBan; }
            return;
        }
        const cardTags = (card.dataset.tags || '').split(',').map(t => t.trim()).filter(Boolean);
        if (cardTags.some(t => bannedSet.has(t) || bannedSet.has(mergeMap[t]))) {
            card.style.display = 'none';
            card.dataset.hiddenByBan = '1';
        } else if (card.dataset.hiddenByBan) {
            card.style.display = '';
            delete card.dataset.hiddenByBan;
        }
    });
}

function toggleShowBanned() {
    showBanned = !showBanned;
    const btn = document.getElementById('showBannedToggle');
    btn.style.opacity = showBanned ? '1' : '0.5';
    btn.title = showBanned ? 'Hide banned cards' : 'Show banned cards';
    applyBanFilter();
}

// ── Tag manager open/close ────────────────────────────────
function openTagManager() {
    document.getElementById('tagManagerOverlay').style.display = 'flex';
    tmLoadTags();
}

function closeTagManager() {
    document.getElementById('tagManagerOverlay').style.display = 'none';
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeTagManager(); });

// ── Tag manager data ──────────────────────────────────────
async function tmLoadTags() {
    document.getElementById('tmTagList').innerHTML = '<div class="tm-loading">Loading tags...</div>';
    try {
        const data = await fetch('/api/tags').then(r => r.json());
        tmTagData = data.tags;
        tmSelected.clear();
        tmUpdateMergeBar();
        tmRenderTagList();
    } catch {
        document.getElementById('tmTagList').innerHTML = '<div class="tm-loading">Error loading tags.</div>';
    }
}

function tmFilterTags() { tmRenderTagList(); }

function tmRenderTagList() {
    const container = document.getElementById('tmTagList');
    const showBanned = document.getElementById('tmShowBanned').checked;
    const showMerged = document.getElementById('tmShowMerged').checked;
    const query = document.getElementById('tmSearch').value.toLowerCase().trim();

    container.innerHTML = '';
    tmTagData.forEach(tag => {
        if (!showBanned && tag.is_banned) return;
        if (!showMerged && tag.merged_into) return;
        if (query && !tag.tag.includes(query)) return;

        const nameClass = (tag.is_favourite ? 'tm-fav-active' : '') + (tag.is_banned ? ' tm-ban-active' : '');
        const mergeLabel = tag.merged_into ? `<span class="tm-tag-merge-label"> → ${tag.merged_into}</span>` : '';
        const unmergeBtn = tag.merged_into ? `<button class="tm-btn-unmerge" onclick="tmUnmerge('${tag.tag.replace(/'/g, "\\'")}')" title="Unmerge">↩</button>` : '';
        const tagEsc = tag.tag.replace(/'/g, "\\'");

        const row = document.createElement('div');
        row.className = 'tm-tag-row';
        row.innerHTML = `
            <input type="checkbox" class="tm-select-cb" onchange="tmOnSelect('${tagEsc}', this)" ${tmSelected.has(tag.tag) ? 'checked' : ''}>
            <span class="tm-tag-name ${nameClass}">${tag.tag}</span>
            <span class="tm-tag-count">(${tag.count})</span>
            ${mergeLabel}
            <div class="tm-tag-actions">
                <button class="tm-btn-fav ${tag.is_favourite ? 'active' : ''}" onclick="tmToggleFavourite('${tagEsc}')" title="Favourite">★</button>
                <button class="tm-btn-ban ${tag.is_banned ? 'active' : ''}" onclick="tmToggleBan('${tagEsc}')" title="Ban">🚫</button>
                ${unmergeBtn}
            </div>`;
        container.appendChild(row);
    });

    if (!container.children.length) {
        container.innerHTML = '<div class="tm-loading">No tags match.</div>';
    }
}

// ── Tag manager selection / merge ─────────────────────────
function tmOnSelect(tagName, cb) {
    if (cb.checked) tmSelected.add(tagName); else tmSelected.delete(tagName);
    tmUpdateMergeBar();
}

function tmUpdateMergeBar() {
    document.getElementById('tmMergeCount').textContent = `${tmSelected.size} selected`;
    document.getElementById('tmMergeBar').style.display = tmSelected.size > 0 ? 'flex' : 'none';
}

function tmClearSelection() {
    tmSelected.clear();
    tmUpdateMergeBar();
    tmRenderTagList();
}

function tmMergeTargetInput(val) {
    const dropdown = document.getElementById('tmMergeDropdown');
    tmDDActiveIndex = -1;
    const q = val.toLowerCase().trim();
    if (!q) { dropdown.style.display = 'none'; return; }
    const matches = tmTagData.filter(t => t.tag.includes(q)).slice(0, 20);
    if (!matches.length) { dropdown.style.display = 'none'; return; }
    dropdown.innerHTML = '';
    matches.forEach(t => {
        const div = document.createElement('div');
        div.textContent = t.tag;
        div.addEventListener('mousedown', e => {
            e.preventDefault();
            document.getElementById('tmMergeTarget').value = t.tag;
            dropdown.style.display = 'none';
        });
        dropdown.appendChild(div);
    });
    dropdown.style.display = 'block';
}

function tmMergeTargetKeydown(e) {
    const dropdown = document.getElementById('tmMergeDropdown');
    const items = dropdown.querySelectorAll('div');
    if (!items.length || dropdown.style.display === 'none') return;
    if (e.key === 'ArrowDown') {
        e.preventDefault();
        items[tmDDActiveIndex]?.classList.remove('tm-dd-active');
        tmDDActiveIndex = Math.min(tmDDActiveIndex + 1, items.length - 1);
        items[tmDDActiveIndex]?.classList.add('tm-dd-active');
        items[tmDDActiveIndex]?.scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        items[tmDDActiveIndex]?.classList.remove('tm-dd-active');
        tmDDActiveIndex = Math.max(tmDDActiveIndex - 1, 0);
        items[tmDDActiveIndex]?.classList.add('tm-dd-active');
        items[tmDDActiveIndex]?.scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter' && tmDDActiveIndex >= 0) {
        e.preventDefault();
        document.getElementById('tmMergeTarget').value = items[tmDDActiveIndex].textContent;
        dropdown.style.display = 'none';
    } else if (e.key === 'Escape') {
        dropdown.style.display = 'none';
    }
}

document.addEventListener('click', e => {
    const dropdown = document.getElementById('tmMergeDropdown');
    if (dropdown && !dropdown.contains(e.target) && e.target.id !== 'tmMergeTarget') {
        dropdown.style.display = 'none';
    }
});

async function tmToggleFavourite(tagName) {
    const data = await fetch('/api/tags/favourite', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tag: tagName }) }).then(r => r.json());
    const entry = tmTagData.find(t => t.tag === tagName);
    if (entry) entry.is_favourite = data.is_favourite;
    (tmTagMeta[tagName] = tmTagMeta[tagName] || {}).is_favourite = data.is_favourite;
    tmRenderTagList();
    applyTagMetaStyles();
}

async function tmToggleBan(tagName) {
    const data = await fetch('/api/tags/ban', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tag: tagName }) }).then(r => r.json());
    const entry = tmTagData.find(t => t.tag === tagName);
    if (entry) entry.is_banned = data.is_banned;
    (tmTagMeta[tagName] = tmTagMeta[tagName] || {}).is_banned = data.is_banned;
    tmRenderTagList();
    applyTagMetaStyles();
    applyBanFilter();
}

async function tmExecuteMerge() {
    const target = document.getElementById('tmMergeTarget').value.trim().toLowerCase();
    if (!target) { alert('Please enter a target tag name to merge into.'); return; }
    const sources = Array.from(tmSelected).filter(s => s !== target);
    if (!sources.length) { alert('No valid source tags selected (cannot merge into itself).'); return; }
    await fetch('/api/tags/merge', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sources, target }) });
    sources.forEach(s => { (tmTagMeta[s] = tmTagMeta[s] || {}).merged_into = target; });
    tmSelected.clear();
    document.getElementById('tmMergeTarget').value = '';
    applyTagMetaStyles();
    tmLoadTags();
}

async function tmUnmerge(tagName) {
    await fetch('/api/tags/unmerge', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tags: [tagName] }) });
    if (tmTagMeta[tagName]) tmTagMeta[tagName].merged_into = null;
    applyTagMetaStyles();
    tmLoadTags();
}

// ── Autocomplete ──────────────────────────────────────────
function setupAutocomplete() {
    const searchInput = document.getElementById('searchInput');
    const dropdown = document.getElementById('autocompleteDropdown');
    const tags = new Set();
    document.querySelectorAll('.tags-container .tag-container p a').forEach(a => tags.add(a.textContent.trim().toLowerCase()));
    const tagList = Array.from(tags);

    function showSuggestions(query) {
        dropdown.innerHTML = '';
        if (!query) { dropdown.style.display = 'none'; return; }
        const matches = tagList.filter(t => t.includes(query.toLowerCase()));
        if (!matches.length) { dropdown.style.display = 'none'; return; }
        matches.forEach(tag => {
            const div = document.createElement('div');
            div.textContent = tag;
            div.addEventListener('click', () => {
                searchInput.value = (tmTagMeta[tag] && tmTagMeta[tag].merged_into) || tag;
                dropdown.style.display = 'none';
            });
            dropdown.appendChild(div);
        });
        dropdown.style.display = 'block';
    }

    searchInput.addEventListener('input', function () { showSuggestions(this.value); });
    document.addEventListener('click', e => {
        if (!searchInput.contains(e.target) && !dropdown.contains(e.target)) dropdown.style.display = 'none';
    });
}

// ── Tag filter (sidebar tag list) ─────────────────────────
function filterTags() {
    const input = document.querySelector('input[name="query"]');
    const tagsContainer = document.querySelector('.tags-container');
    if (!input || !tagsContainer) return;
    const tags = Array.from(tagsContainer.querySelectorAll('.tag-container p a'));
    input.addEventListener('input', function () {
        const query = this.value.toLowerCase();
        tags.forEach(tag => {
            tag.parentElement.parentElement.style.display = tag.textContent.toLowerCase().includes(query) ? 'block' : 'none';
        });
    });
}

// ── Initialization ────────────────────────────────────────
updateNSFWToggle();
applyBlurringPreference();
applyCompactModePreference();
highlightSearchResults();

// Set search type select from URL
const _initParams = new URLSearchParams(window.location.search);
// ── Score filter ──────────────────────────────────────────
const _scoreFilterMap = [
    ['qmin', 'sfQmin', 'hQmin'],
    ['qmax', 'sfQmax', 'hQmax'],
    ['lmin', 'sfLmin', 'hLmin'],
    ['lmax', 'sfLmax', 'hLmax'],
    ['smin', 'sfSmin', 'hSmin'],
    ['smax', 'sfSmax', 'hSmax'],
    ['cfrom', 'sfCfrom', 'hCfrom'],
    ['cto',   'sfCto',   'hCto'],
    ['ufrom', 'sfUfrom', 'hUfrom'],
    ['uto',   'sfUto',   'hUto'],
];

function initScoreFilter() {
    const panel = document.getElementById('scoreFilterPanel');
    panel.style.display = 'none';

    const params = new URLSearchParams(window.location.search);
    let hasFilter = false;
    for (const [param, panelId, hiddenId] of _scoreFilterMap) {
        const val = params.get(param) || '';
        if (val) {
            document.getElementById(panelId).value = val;
            document.getElementById(hiddenId).value = val;
            hasFilter = true;
        }
    }
    if (hasFilter) document.getElementById('filterToggleBtn').classList.add('active');

    document.getElementById('filterToggleBtn').addEventListener('click', e => {
        e.stopPropagation();
        panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
    });

    document.addEventListener('click', e => {
        const wrap = document.querySelector('.filter-wrap');
        if (wrap && !wrap.contains(e.target)) {
            document.getElementById('scoreFilterPanel').style.display = 'none';
        }
    });
}

function applyScoreFilter() {
    for (const [, panelId, hiddenId] of _scoreFilterMap) {
        document.getElementById(hiddenId).value = document.getElementById(panelId).value;
    }
    document.getElementById('scoreFilterPanel').style.display = 'none';
    const params = new URLSearchParams(new FormData(document.querySelector('.search-container form')));
    params.set('sort', currentSort);
    performSearch(params);
}

function clearScoreFilter() {
    for (const [, panelId, hiddenId] of _scoreFilterMap) {
        document.getElementById(panelId).value = '';
        document.getElementById(hiddenId).value = '';
    }
    document.getElementById('scoreFilterPanel').style.display = 'none';
    const params = new URLSearchParams(new FormData(document.querySelector('.search-container form')));
    params.set('sort', currentSort);
    performSearch(params);
}

const _typeParam = _initParams.get('type');
if (_typeParam) {
    const opt = document.querySelector(`#searchtype [value="${_typeParam}"]`);
    if (opt) opt.selected = true;
}

// Attach lightbox and rating widgets to all server-rendered cards
document.querySelectorAll('.card-container').forEach(card => {
    attachLightboxListeners(card);
    initAllRatingWidgets(card);
});

document.addEventListener('DOMContentLoaded', async () => {
    currentPage = parseInt(_initParams.get('page')) || 1;
    currentQuery = _initParams.get('query') || '';
    currentType = _initParams.get('type') || 'basic';
    currentSort = _initParams.get('sort') || currentSort;

    const tagsContainer = document.querySelector('.tags-container');
    if (tagsContainer) tagsContainer.classList.remove('show-tags');

    document.getElementById('tagManagerOverlay').addEventListener('click', function (e) {
        if (e.target === this) closeTagManager();
    });

    initSortToggle();
    initScoreFilter();

    const searchForm = document.querySelector('.search-container form');
    if (searchForm) {
        searchForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const params = new URLSearchParams(new FormData(this));
            params.set('sort', currentSort);
            performSearch(params);
        });
    }

    setupAutocomplete();
    filterTags();

    await loadTagMeta();
    applyTagMetaStyles();
    applyBanFilter();

    maybeTriggerPreload();

    const showBannedBtn = document.getElementById('showBannedToggle');
    if (showBannedBtn) showBannedBtn.style.opacity = showBanned ? '1' : '0.5';
});
