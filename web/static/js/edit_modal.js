/**
 * edit_modal.js
 *
 * Shared "Edit Metadata" modal used by the library view (bulk) and the game
 * detail page (single game).
 *
 * Public API:
 *   window.openEditModal(gameIds, currentData)
 *
 * @param {number|number[]} gameIds      One game ID or an array of IDs.
 * @param {object}          currentData  Optional snapshot of the game(s).
 *   currentData.genres_override  – JSON-parsed array or null
 *   currentData.genres           – JSON-parsed array or null  (store value)
 *   currentData.playtime_label   – string or null
 *   currentData.playtime_hours   – number or null (shown read-only)
 */

(function () {
    'use strict';

    /* ------------------------------------------------------------------ */
    /* Constants                                                            */
    /* ------------------------------------------------------------------ */

    const PLAYTIME_LABELS = ['unplayed', 'tried', 'played', 'heavily_played', 'abandoned'];
    const PLAYTIME_COLORS = {
        unplayed:       { bg: 'rgba(136,136,136,0.2)',  border: 'rgba(136,136,136,0.4)',  text: '#888'    },
        tried:          { bg: 'rgba(33,150,243,0.2)',   border: 'rgba(33,150,243,0.4)',   text: '#2196f3' },
        played:         { bg: 'rgba(76,175,80,0.2)',    border: 'rgba(76,175,80,0.4)',    text: '#4caf50' },
        heavily_played: { bg: 'rgba(156,39,176,0.2)',   border: 'rgba(156,39,176,0.4)',   text: '#9c27b0' },
        abandoned:      { bg: 'rgba(244,67,54,0.2)',    border: 'rgba(244,67,54,0.4)',    text: '#f44336' },
    };
    const PLAYTIME_DISPLAY = {
        unplayed:       'Not played',
        tried:          'Just tried',
        played:         'Played',
        heavily_played: 'Heavily played',
        abandoned:      'Abandoned',
    };

    let cachedGenres = null;   // fetched once from /api/genres

    /* ------------------------------------------------------------------ */
    /* CSS injection                                                        */
    /* ------------------------------------------------------------------ */

    function injectStyles() {
        if (document.getElementById('edit-modal-styles')) return;
        const style = document.createElement('style');
        style.id = 'edit-modal-styles';
        style.textContent = `
/* ---- overlay ---- */
#edit-modal-overlay {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.75);
    z-index: 2000;
    justify-content: center;
    align-items: center;
}
#edit-modal-overlay.active { display: flex; }

/* ---- modal box (desktop) ---- */
#edit-modal {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 16px;
    padding: 28px;
    width: 90%;
    max-width: 480px;
    max-height: 85vh;
    overflow-y: auto;
    box-shadow: 0 20px 60px rgba(0,0,0,0.6);
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 22px;
}

/* ---- mobile bottom sheet ---- */
@media (max-width: 768px) {
    #edit-modal-overlay { align-items: flex-end; }
    #edit-modal {
        width: 100%;
        max-width: 100%;
        border-radius: 20px 20px 0 0;
        padding: 20px 20px 32px;
        max-height: 90vh;
    }
}

/* ---- header ---- */
.em-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.em-header h2 {
    margin: 0;
    font-size: 1.1rem;
    font-weight: 600;
    color: #e4e4e4;
}
.em-close {
    background: none;
    border: none;
    color: #888;
    font-size: 1.4rem;
    cursor: pointer;
    line-height: 1;
    padding: 4px;
    border-radius: 6px;
    transition: color 0.2s, background 0.2s;
}
.em-close:hover { color: #e4e4e4; background: rgba(255,255,255,0.08); }

/* ---- section labels ---- */
.em-section h3 {
    margin: 0 0 12px;
    font-size: 0.85rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #888;
}

/* ---- tag input ---- */
.em-tag-area {
    min-height: 42px;
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 10px;
    padding: 6px 10px;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
    cursor: text;
    position: relative;
}
.em-tag-area:focus-within { border-color: #667eea; }
.em-tag {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    background: rgba(102,126,234,0.25);
    border: 1px solid rgba(102,126,234,0.4);
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 0.82rem;
    color: #c5cbf9;
}
.em-tag-remove {
    background: none;
    border: none;
    color: #888;
    cursor: pointer;
    font-size: 1rem;
    line-height: 1;
    padding: 0;
}
.em-tag-remove:hover { color: #f44336; }
.em-tag-input {
    background: none;
    border: none;
    outline: none;
    color: #e4e4e4;
    font-size: 0.9rem;
    min-width: 120px;
    flex: 1;
}
.em-tag-hint {
    font-size: 0.78rem;
    color: #555;
    margin-top: 6px;
}

/* ---- autocomplete dropdown ---- */
.em-autocomplete {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    right: 0;
    background: #1a1a2e;
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 8px;
    max-height: 160px;
    overflow-y: auto;
    z-index: 2100;
    display: none;
}
.em-autocomplete.active { display: block; }
.em-autocomplete-item {
    padding: 8px 12px;
    cursor: pointer;
    font-size: 0.88rem;
    color: #c4c4c4;
}
.em-autocomplete-item:hover,
.em-autocomplete-item.highlighted { background: rgba(102,126,234,0.25); color: #e4e4e4; }

/* ---- playtime buttons ---- */
.em-playtime-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}
.em-playtime-btn {
    padding: 7px 14px;
    border-radius: 8px;
    border: 1px solid transparent;
    cursor: pointer;
    font-size: 0.85rem;
    text-transform: capitalize;
    transition: all 0.15s;
    background: rgba(255,255,255,0.05);
    color: #888;
    border-color: rgba(255,255,255,0.1);
}
.em-playtime-btn:hover { opacity: 0.85; }
.em-playtime-btn.active {
    font-weight: 600;
    box-shadow: 0 0 0 1px currentColor;
}
/* Suggested (auto-derived from hours) — dashed border, no fill */
.em-playtime-btn.suggested {
    border-style: dashed;
    opacity: 0.75;
    font-style: italic;
}
.em-playtime-btn.suggested::after {
    content: ' · auto';
    font-size: 0.75em;
    opacity: 0.65;
    font-style: normal;
}
.em-playtime-clear {
    background: rgba(244,67,54,0.1);
    color: #f44336;
    border-color: rgba(244,67,54,0.25);
}
.em-playtime-clear:hover { background: rgba(244,67,54,0.2); }
.em-store-playtime {
    margin-top: 8px;
    font-size: 0.8rem;
    color: #555;
}

/* ---- footer ---- */
.em-footer {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
}
.em-btn {
    padding: 10px 22px;
    border-radius: 10px;
    border: none;
    cursor: pointer;
    font-size: 0.9rem;
    transition: opacity 0.15s;
}
.em-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.em-btn.cancel {
    background: rgba(255,255,255,0.08);
    color: #888;
}
.em-btn.cancel:hover { background: rgba(255,255,255,0.15); color: #e4e4e4; }
.em-btn.save {
    background: linear-gradient(90deg, #667eea, #764ba2);
    color: #fff;
}
.em-btn.save:hover { opacity: 0.9; }

/* ---- status message ---- */
.em-status {
    padding: 8px 14px;
    border-radius: 8px;
    font-size: 0.85rem;
    display: none;
}
.em-status.success { background: rgba(76,175,80,0.2); color: #4caf50; display: block; }
.em-status.error   { background: rgba(244,67,54,0.2); color: #f44336; display: block; }
        `;
        document.head.appendChild(style);
    }

    /* ------------------------------------------------------------------ */
    /* DOM scaffold                                                         */
    /* ------------------------------------------------------------------ */

    function ensureModalDOM() {
        if (document.getElementById('edit-modal-overlay')) return;
        const overlay = document.createElement('div');
        overlay.id = 'edit-modal-overlay';
        overlay.innerHTML = `
<div id="edit-modal" role="dialog" aria-modal="true" aria-labelledby="em-title">
  <div class="em-header">
    <h2 id="em-title">Edit Metadata</h2>
    <button class="em-close" id="em-close-btn" aria-label="Close">&times;</button>
  </div>

  <section class="em-section" id="em-genres-section">
    <h3>Genres</h3>
    <div class="em-tag-area" id="em-tag-area">
      <input class="em-tag-input" id="em-tag-input" type="text"
             placeholder="Add genre…" autocomplete="off" spellcheck="false">
      <div class="em-autocomplete" id="em-autocomplete"></div>
    </div>
    <p class="em-tag-hint" id="em-genres-hint"></p>
  </section>

  <section class="em-section" id="em-playtime-section">
    <h3>Playtime label</h3>
    <div class="em-playtime-grid" id="em-playtime-grid"></div>
    <p class="em-store-playtime" id="em-store-playtime"></p>
  </section>

  <div class="em-status" id="em-status"></div>

  <div class="em-footer">
    <button class="em-btn cancel" id="em-cancel-btn">Cancel</button>
    <button class="em-btn save"   id="em-save-btn">Save</button>
  </div>
</div>
        `;
        document.body.appendChild(overlay);

        // Close events
        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) closeEditModal();
        });
        document.getElementById('em-close-btn').addEventListener('click', closeEditModal);
        document.getElementById('em-cancel-btn').addEventListener('click', closeEditModal);
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') closeEditModal();
        });
    }

    /* ------------------------------------------------------------------ */
    /* Internal state                                                       */
    /* ------------------------------------------------------------------ */

    let _gameIds            = [];
    let _currentTags        = [];   // working copy for genres
    let _originalTagsJSON   = null; // to detect changes
    let _selectedLabel      = null; // working copy for playtime_label
    let _originalLabel      = null; // to detect changes
    let _playtimeHours      = null; // store value, used to derive suggested label
    let _autocompleteHi     = -1;   // highlighted index in dropdown

    /* ------------------------------------------------------------------ */
    /* Public entry point                                                   */
    /* ------------------------------------------------------------------ */

    window.openEditModal = async function (gameIds, currentData = {}) {
        injectStyles();
        ensureModalDOM();

        // Normalise gameIds
        _gameIds = Array.isArray(gameIds) ? gameIds : [gameIds];

        // Resolve initial genres: use override if present, else store genres
        const overrideRaw = currentData.genres_override;
        const storeRaw    = currentData.genres;
        const hasOverride = Array.isArray(overrideRaw) && overrideRaw.length > 0;
        _currentTags      = hasOverride
            ? [...overrideRaw]
            : (Array.isArray(storeRaw) ? [...storeRaw] : []);
        // For multi-game selection where data differs, we start fresh
        if (_gameIds.length > 1 && currentData._mixed_genres) {
            _currentTags = [];
        }
        _originalTagsJSON = JSON.stringify(_currentTags);

        // Resolve initial playtime label
        _selectedLabel  = currentData.playtime_label || null;
        _originalLabel  = _selectedLabel;
        _playtimeHours  = (currentData.playtime_hours != null) ? parseFloat(currentData.playtime_hours) : null;

        // Update title
        const n = _gameIds.length;
        document.getElementById('em-title').textContent =
            `Edit Metadata\u2002\u2013\u2002${n} game${n !== 1 ? 's' : ''}`;

        // Render tag area
        renderTags();

        // Genres hint
        const hint = document.getElementById('em-genres-hint');
        if (_gameIds.length === 1) {
            hint.textContent = hasOverride
                ? 'Custom genres (overrides store data).'
                : 'Currently showing store genres. Edit to create an override.';
        } else {
            hint.textContent = 'Editing will override store genres for all selected games.';
        }

        // Render playtime buttons
        renderPlaytimeButtons();

        // Show store playtime if single game
        // Show store playtime if single game (renderPlaytimeButtons will add suggestion text)
        const storePt = document.getElementById('em-store-playtime');
        if (_gameIds.length === 1 && _playtimeHours != null) {
            storePt.textContent = `Store value: ${_playtimeHours.toFixed(1)} h`;
        } else {
            storePt.textContent = '';
        }

        // Wire up tag input
        const tagInput = document.getElementById('em-tag-input');
        tagInput.value = '';
        tagInput.oninput  = onTagInput;
        tagInput.onkeydown = onTagKeydown;
        tagInput.onblur   = () => setTimeout(hideAutocomplete, 150);

        // Wire up save
        document.getElementById('em-save-btn').onclick = onSave;

        // Reset status
        setStatus('', '');

        // Fetch genres for autocomplete (once)
        if (!cachedGenres) {
            cachedGenres = await fetch('/api/genres').then(r => r.json()).catch(() => []);
        }

        // Show overlay
        const overlay = document.getElementById('edit-modal-overlay');
        overlay.classList.add('active');
        document.body.style.overflow = 'hidden';
        tagInput.focus();
    };

    function closeEditModal() {
        const overlay = document.getElementById('edit-modal-overlay');
        if (!overlay) return;
        overlay.classList.remove('active');
        document.body.style.overflow = '';
    }

    /* ------------------------------------------------------------------ */
    /* Tags                                                                 */
    /* ------------------------------------------------------------------ */

    function renderTags() {
        const area = document.getElementById('em-tag-area');
        // Remove existing tag chips, keep the input and autocomplete
        area.querySelectorAll('.em-tag').forEach(el => el.remove());
        const input = document.getElementById('em-tag-input');

        _currentTags.forEach((tag, index) => {
            const chip = document.createElement('span');
            chip.className = 'em-tag';
            chip.textContent = tag;
            const btn = document.createElement('button');
            btn.className = 'em-tag-remove';
            btn.textContent = '\u00d7';
            btn.title = 'Remove';
            btn.onclick = () => { _currentTags.splice(index, 1); renderTags(); };
            chip.appendChild(btn);
            area.insertBefore(chip, input);
        });
    }

    function addTag(raw) {
        const tag = raw.trim();
        if (!tag) return;
        if (_currentTags.some(t => t.toLowerCase() === tag.toLowerCase())) return;
        _currentTags.push(tag);
        renderTags();
        document.getElementById('em-tag-input').value = '';
        hideAutocomplete();
    }

    function onTagInput(e) {
        const val = e.target.value;
        // Auto-add on comma
        if (val.endsWith(',')) {
            addTag(val.slice(0, -1));
            return;
        }
        showAutocomplete(val.trim());
    }

    function onTagKeydown(e) {
        const dropdown = document.getElementById('em-autocomplete');
        const items = dropdown.querySelectorAll('.em-autocomplete-item');

        if (e.key === 'Enter') {
            e.preventDefault();
            if (_autocompleteHi >= 0 && items[_autocompleteHi]) {
                addTag(items[_autocompleteHi].dataset.value);
            } else {
                addTag(e.target.value);
            }
        } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            _autocompleteHi = Math.min(_autocompleteHi + 1, items.length - 1);
            highlightAutocomplete(items);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            _autocompleteHi = Math.max(_autocompleteHi - 1, -1);
            highlightAutocomplete(items);
        } else if (e.key === 'Backspace' && e.target.value === '' && _currentTags.length > 0) {
            _currentTags.pop();
            renderTags();
        }
    }

    function showAutocomplete(query) {
        const dropdown = document.getElementById('em-autocomplete');
        if (!cachedGenres || !query) { hideAutocomplete(); return; }

        const q = query.toLowerCase();
        const matches = cachedGenres
            .filter(g => g.toLowerCase().includes(q) &&
                         !_currentTags.some(t => t.toLowerCase() === g.toLowerCase()))
            .slice(0, 8);

        if (!matches.length) { hideAutocomplete(); return; }

        dropdown.innerHTML = matches
            .map(g => `<div class="em-autocomplete-item" data-value="${escHtml(g)}">${escHtml(g)}</div>`)
            .join('');

        dropdown.querySelectorAll('.em-autocomplete-item').forEach(item => {
            item.addEventListener('mousedown', () => addTag(item.dataset.value));
        });

        _autocompleteHi = -1;
        dropdown.classList.add('active');
    }

    function hideAutocomplete() {
        const dropdown = document.getElementById('em-autocomplete');
        if (dropdown) { dropdown.classList.remove('active'); _autocompleteHi = -1; }
    }

    function highlightAutocomplete(items) {
        items.forEach((el, i) => {
            el.classList.toggle('highlighted', i === _autocompleteHi);
        });
    }

    /* ------------------------------------------------------------------ */
    /* Playtime                                                             */
    /* ------------------------------------------------------------------ */

    function derivedLabelFromHours(hours) {
        if (hours == null) return null;
        if (hours === 0)   return 'unplayed';
        if (hours <= 2)    return 'tried';
        if (hours <= 20)   return 'played';
        return 'heavily_played';
    }

    function renderPlaytimeButtons() {
        const grid = document.getElementById('em-playtime-grid');
        grid.innerHTML = '';

        // Suggested label: only shown when no manual selection is active
        const suggested = (_selectedLabel === null) ? derivedLabelFromHours(_playtimeHours) : null;

        PLAYTIME_LABELS.forEach(label => {
            const c   = PLAYTIME_COLORS[label];
            const isActive    = label === _selectedLabel;
            const isSuggested = !isActive && label === suggested;
            const btn = document.createElement('button');
            btn.className = 'em-playtime-btn'
                + (isActive    ? ' active'    : '')
                + (isSuggested ? ' suggested' : '');
            btn.textContent = PLAYTIME_DISPLAY[label] || label;
            if (isActive) {
                btn.style.background  = c.bg;
                btn.style.borderColor = c.border;
                btn.style.color       = c.text;
            } else if (isSuggested) {
                btn.style.background  = 'transparent';
                btn.style.borderColor = c.text;   // dashed via CSS class
                btn.style.color       = c.text;
            } else {
                btn.style.background  = 'rgba(255,255,255,0.05)';
                btn.style.borderColor = 'rgba(255,255,255,0.1)';
                btn.style.color       = '#888';
            }
            btn.onclick = () => {
                _selectedLabel = (_selectedLabel === label) ? null : label;
                renderPlaytimeButtons();
            };
            grid.appendChild(btn);
        });

        // Clear button (only shown when something is explicitly set)
        if (_selectedLabel) {
            const clearBtn = document.createElement('button');
            clearBtn.className = 'em-playtime-btn em-playtime-clear';
            clearBtn.textContent = 'Clear';
            clearBtn.onclick = () => { _selectedLabel = null; renderPlaytimeButtons(); };
            grid.appendChild(clearBtn);
        }

        // Update the hours hint to reflect current suggestion state
        const storePt = document.getElementById('em-store-playtime');
        if (storePt && _playtimeHours != null) {
            const derivedDisplay = suggested ? PLAYTIME_DISPLAY[suggested] : null;
            storePt.textContent = `Store value: ${_playtimeHours.toFixed(1)} h`
                + (derivedDisplay ? ` \u2192 "${derivedDisplay}" suggested` : '');
        }
    }

    /* ------------------------------------------------------------------ */
    /* Status                                                               */
    /* ------------------------------------------------------------------ */

    function setStatus(msg, type) {
        const el = document.getElementById('em-status');
        if (!el) return;
        el.textContent = msg;
        el.className = 'em-status' + (type ? ' ' + type : '');
    }

    /* ------------------------------------------------------------------ */
    /* Save                                                                 */
    /* ------------------------------------------------------------------ */

    async function onSave() {
        const tagsChanged   = JSON.stringify(_currentTags) !== _originalTagsJSON;
        const labelChanged  = _selectedLabel !== _originalLabel;

        if (!tagsChanged && !labelChanged) {
            closeEditModal();
            return;
        }

        const saveBtn = document.getElementById('em-save-btn');
        saveBtn.disabled = true;
        saveBtn.textContent = 'Saving…';
        setStatus('', '');

        const body = { game_ids: _gameIds };

        if (tagsChanged) {
            body.genres_override = _currentTags.length > 0 ? _currentTags : null;
            body.update_genres_override = true;
        }
        if (labelChanged) {
            body.playtime_label = _selectedLabel;
            body.update_playtime_label = true;
        }

        try {
            const resp = await fetch('/api/games/bulk/edit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await resp.json();
            if (data.success) {
                setStatus(`Saved! (${data.updated} game${data.updated !== 1 ? 's' : ''} updated)`, 'success');
                // Close after a short delay so the user sees the confirmation
                setTimeout(() => {
                    closeEditModal();
                    // Notify host page if it wants to refresh data
                    document.dispatchEvent(new CustomEvent('editModalSaved', {
                        detail: { gameIds: _gameIds, body }
                    }));
                }, 800);
            } else {
                setStatus(data.detail || 'Save failed', 'error');
                saveBtn.disabled = false;
                saveBtn.textContent = 'Save';
            }
        } catch (err) {
            setStatus('Network error: ' + err.message, 'error');
            saveBtn.disabled = false;
            saveBtn.textContent = 'Save';
        }
    }

    /* ------------------------------------------------------------------ */
    /* Helpers                                                              */
    /* ------------------------------------------------------------------ */

    function escHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

})();
