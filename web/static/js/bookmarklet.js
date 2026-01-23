// Backlogia Helper Bookmarklet
// This script is loaded dynamically by the bookmarklet loader
// It can be updated on the server without requiring users to reinstall the bookmarklet

(function() {
    // Get the URL from the loader (set when bookmarklet was installed)
    var LOCAL_URL = window.__BACKLOGIA_URL__ || 'http://localhost:5050';
    var host = location.hostname;

    // Helper function to create styled overlay
    function createOverlay(borderColor, title) {
        var d = document.createElement('div');
        d.id = '__backlogia_overlay__';
        d.innerHTML = '<div style="position:fixed;top:20px;right:20px;background:linear-gradient(135deg,#1a1a2e,#16213e);padding:20px 25px;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,0.4);z-index:999999;font-family:-apple-system,BlinkMacSystemFont,sans-serif;border:1px solid ' + borderColor + ';min-width:320px;max-width:400px">' +
            '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">' +
            '<span style="color:' + borderColor + ';font-size:12px;text-transform:uppercase;letter-spacing:1px">' + title + '</span>' +
            '<button id="__bl_close__" style="background:none;border:none;color:#888;cursor:pointer;font-size:18px;padding:0;line-height:1">&times;</button>' +
            '</div>' +
            '<div id="__bl_content__" style="color:#e4e4e4;font-size:14px"></div>' +
            '</div>';
        document.body.appendChild(d);
        d.querySelector('#__bl_close__').onclick = function() { d.remove(); };
        return d.querySelector('#__bl_content__');
    }

    // Remove any existing overlay
    var existing = document.getElementById('__backlogia_overlay__');
    if (existing) existing.remove();

    // Steam ID extraction
    if (host.includes('steamcommunity.com')) {
        try {
            var profileData = null;
            var steamId = null;

            // Try to access the global variable directly first (more reliable)
            if (typeof g_rgProfileData !== 'undefined' && g_rgProfileData) {
                profileData = g_rgProfileData;
                steamId = profileData.steamid;
            }

            // Fallback: parse from page HTML
            if (!steamId) {
                var match = document.body.innerHTML.match(/g_rgProfileData\s*=\s*(\{[^}]+\})/);
                if (match) {
                    profileData = JSON.parse(match[1].replace(/\\'/g, "'"));
                    steamId = profileData.steamid;
                }
            }

            if (!steamId) return alert('Steam profile data not found! Make sure you are on your Steam profile page.');

            var content = createOverlay('#66c0f4', 'Steam ID');
            content.innerHTML =
                '<div style="background:#171a21;padding:12px 15px;border-radius:6px;margin-bottom:15px">' +
                '<code style="color:#fff;font-size:16px;font-family:monospace">' + steamId + '</code>' +
                '</div>' +
                '<button id="__bl_copy__" style="width:100%;padding:10px 15px;background:linear-gradient(90deg,#47bfff,#1a9fff);border:none;border-radius:6px;color:#fff;font-weight:600;cursor:pointer;font-size:14px">Copy to Clipboard</button>' +
                '<div style="margin-top:12px;padding-top:12px;border-top:1px solid #2a475e;color:#8f98a0;font-size:11px">' +
                '<strong style="color:#c7d5e0">' + (profileData.personaname || 'Unknown') + '</strong>' +
                '</div>';

            content.querySelector('#__bl_copy__').onclick = function() {
                navigator.clipboard.writeText(steamId).then(function() {
                    this.textContent = 'Copied!';
                    this.style.background = 'linear-gradient(90deg,#5ba32b,#4a8c24)';
                    setTimeout(function() {
                        this.textContent = 'Copy to Clipboard';
                        this.style.background = 'linear-gradient(90deg,#47bfff,#1a9fff)';
                    }.bind(this), 2000);
                }.bind(this));
            };
        } catch (e) {
            alert('Error extracting Steam ID: ' + e.message);
        }
    }

    // EA token extraction
    else if (host.includes('ea.com')) {
        (async function() {
            var content = createOverlay('#ff4747', 'EA Bearer Token');
            content.textContent = 'Fetching token...';

            try {
                var response = await fetch('https://accounts.ea.com/connect/auth?client_id=ORIGIN_JS_SDK&response_type=token&redirect_uri=nucleus:rest&prompt=none', {
                    credentials: 'include'
                });
                var data = await response.json();

                if (data.access_token) {
                    var token = data.access_token;
                    content.innerHTML =
                        '<div style="background:#0d0d1a;padding:12px 15px;border-radius:6px;margin-bottom:15px;word-break:break-all;max-height:150px;overflow-y:auto">' +
                        '<code style="color:#e4e4e4;font-size:11px;font-family:monospace">' + token.substring(0, 60) + '...</code>' +
                        '</div>' +
                        '<button id="__bl_copy__" style="width:100%;padding:10px 15px;background:linear-gradient(90deg,#ff4747,#cc3333);border:none;border-radius:6px;color:#fff;font-weight:600;cursor:pointer;font-size:14px">Copy Token</button>' +
                        '<div style="margin-top:12px;color:#888;font-size:11px">Token expires in ~1 hour. Paste it in Backlogia settings.</div>';

                    content.querySelector('#__bl_copy__').onclick = function() {
                        navigator.clipboard.writeText(token).then(function() {
                            this.textContent = 'Copied!';
                            this.style.background = 'linear-gradient(90deg,#4caf50,#2e7d32)';
                            setTimeout(function() {
                                this.textContent = 'Copy Token';
                                this.style.background = 'linear-gradient(90deg,#ff4747,#cc3333)';
                            }.bind(this), 2000);
                        }.bind(this));
                    };
                } else if (data.error) {
                    content.innerHTML = '<span style="color:#f44336">Error: ' + data.error + '</span>' +
                        '<div style="margin-top:10px;color:#888;font-size:12px">' + (data.error_description || 'Make sure you are logged in to ea.com') + '</div>';
                } else {
                    content.innerHTML = '<span style="color:#f44336">Could not get token. Make sure you are logged in to ea.com</span>';
                }
            } catch (e) {
                content.innerHTML = '<span style="color:#f44336">Error: ' + e.message + '</span>' +
                    '<div style="margin-top:10px;color:#888;font-size:12px">Make sure you are on an ea.com page and logged in.</div>';
            }
        })();
    }

    // Ubisoft game scraper
    else if (host.includes('account.ubisoft.com')) {
        (async function() {
            var sleep = function(ms) { return new Promise(function(r) { setTimeout(r, ms); }); };

            var content = createOverlay('#667eea', 'Ubisoft Import');
            content.textContent = 'Expanding all sections...';

            // Click all "More" accordion buttons to expand game list
            var expandCount = 0;
            while (true) {
                var moreBtn = Array.from(document.querySelectorAll('div[class*="Accordion-toggleShow"]'))
                    .find(function(el) { return /more/i.test(el.innerText.trim()); });

                if (!moreBtn) break;
                moreBtn.click();
                expandCount++;
                content.textContent = 'Expanding sections... (' + expandCount + ')';
                await sleep(1200);
            }

            content.textContent = 'Parsing games...';

            // Parse games from page text
            var lines = document.body.innerText.split('\n').map(function(l) { return l.trim(); }).filter(Boolean);
            var rawGames = [];

            for (var i = 0; i < lines.length; i++) {
                if (lines[i].startsWith('Played for')) {
                    rawGames.push({
                        title: lines[i - 1] || null,
                        playtime: lines[i].replace('Played for ', ''),
                        lastPlayed: lines[i + 1] ? lines[i + 1].replace('Last played ', '') : null,
                        platform: lines[i + 2] || null
                    });
                }
            }

            // Deduplicate by creating a unique key
            var uniqueMap = new Map();
            rawGames.forEach(function(g) {
                var key = g.title + '|' + g.playtime + '|' + g.lastPlayed + '|' + g.platform;
                if (!uniqueMap.has(key)) {
                    uniqueMap.set(key, g);
                }
            });
            var uniqueGames = Array.from(uniqueMap.values());

            content.textContent = 'Found ' + uniqueGames.length + ' games. Sending to Backlogia...';

            try {
                var response = await fetch(LOCAL_URL + '/api/import/ubisoft', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ games: uniqueGames })
                });
                var data = await response.json();

                if (data.success) {
                    content.innerHTML = '<span style="color:#4caf50">' + data.message + '</span>' +
                        '<div style="margin-top:10px;color:#888;font-size:12px">Games have been imported to your Backlogia library.</div>';
                } else {
                    content.innerHTML = '<span style="color:#f44336">Error: ' + (data.detail || 'Unknown error') + '</span>';
                }
            } catch (e) {
                content.innerHTML = '<span style="color:#f44336">Failed to connect to Backlogia</span>' +
                    '<div style="margin-top:10px;color:#888;font-size:12px">' +
                    'Could not reach: ' + LOCAL_URL + '<br><br>' +
                    'Make sure Backlogia is running on your computer.' +
                    '</div>';
            }
        })();
    }

    // GOG library scraper
    else if (host.includes('gog.com')) {
        (async function() {
            var sleep = function(ms) { return new Promise(function(r) { setTimeout(r, ms); }); };

            // Check if we're on the games library page
            var isGamesPage = /\/u\/[^/]+\/games/.test(location.pathname);
            var hasGameRows = document.querySelectorAll('.games-matcher__row').length > 0;

            if (!isGamesPage && !hasGameRows) {
                var content = createOverlay('#86328a', 'GOG Import');
                content.innerHTML =
                    '<p style="margin-bottom:12px;color:#e4e4e4">You need to be on your GOG games library page.</p>' +
                    '<ol style="margin:0 0 15px 0;padding-left:20px;color:#ccc;font-size:13px">' +
                    '<li style="margin-bottom:6px">Go to <a href="https://www.gog.com/feed" target="_blank" style="color:#86328a">gog.com/feed</a></li>' +
                    '<li style="margin-bottom:6px">Click the <strong>Games</strong> tab</li>' +
                    '<li>Run this bookmarklet again</li>' +
                    '</ol>' +
                    '<a href="https://www.gog.com/feed" style="display:block;padding:10px 15px;background:linear-gradient(90deg,#86328a,#6b2870);border:none;border-radius:6px;color:#fff;font-weight:600;text-align:center;text-decoration:none;font-size:14px">Go to GOG Feed</a>';
                return;
            }

            var content = createOverlay('#86328a', 'GOG Import');
            content.textContent = 'Scrolling to load all games...';

            // Phase 1: Scroll until all games are loaded
            var last = 0;
            var stuck = 0;

            while (true) {
                var rows = document.querySelectorAll('.games-matcher__row').length;

                if (rows === last) stuck++;
                else stuck = 0;

                last = rows;

                if (stuck >= 10) {
                    break;
                }

                content.textContent = 'Loading games... (' + rows + ' found)';
                window.scrollBy(0, 800);
                await sleep(300);
            }

            content.textContent = 'Scraping ' + last + ' games...';

            // Phase 2: Scrape game data
            async function getSlugFromId(id) {
                try {
                    var res = await fetch('https://api.gog.com/products/' + id + '?expand=downloads,expanded_dlcs');
                    var data = await res.json();
                    return data.slug || null;
                } catch (e) {
                    return null;
                }
            }

            var seen = new Map();
            var rows = Array.from(document.querySelectorAll('.games-matcher__row'));
            var processed = 0;

            for (var i = 0; i < rows.length; i++) {
                var row = rows[i];
                var profGameEl = row.querySelector('[prof-game]');
                var id = profGameEl ? profGameEl.getAttribute('prof-game') : null;
                var titleEl = row.querySelector('.prof-game__title');
                var title = titleEl ? titleEl.innerText.trim() : null;
                var achievementsLink = row.querySelector('.games-matcher__game-achievements-link');
                var profileHref = achievementsLink ? achievementsLink.getAttribute('href') : null;
                var profileUrl = profileHref ? new URL(profileHref, location.origin).href : null;

                if (!id || !title) continue;

                var slug = await getSlugFromId(id);
                var storeUrl = slug ? 'https://www.gog.com/en/game/' + slug : null;

                seen.set(id, { id: id, title: title, profileUrl: profileUrl, storeUrl: storeUrl });
                processed++;
                content.textContent = 'Fetching game details... (' + processed + '/' + rows.length + ')';
            }

            var uniqueGames = Array.from(seen.values());

            content.textContent = 'Found ' + uniqueGames.length + ' games. Sending to Backlogia...';

            try {
                var response = await fetch(LOCAL_URL + '/api/import/gog', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ games: uniqueGames })
                });
                var data = await response.json();

                if (data.success) {
                    content.innerHTML = '<span style="color:#4caf50">' + data.message + '</span>' +
                        '<div style="margin-top:10px;color:#888;font-size:12px">Games have been imported to your Backlogia library.</div>';
                } else {
                    content.innerHTML = '<span style="color:#f44336">Error: ' + (data.detail || 'Unknown error') + '</span>';
                }
            } catch (e) {
                content.innerHTML = '<span style="color:#f44336">Failed to connect to Backlogia</span>' +
                    '<div style="margin-top:10px;color:#888;font-size:12px">' +
                    'Could not reach: ' + LOCAL_URL + '<br><br>' +
                    'Make sure Backlogia is running on your computer.' +
                    '</div>';
            }
        })();
    }

    // Unknown site - show help with links
    else {
        var content = createOverlay('#667eea', 'Backlogia Helper');
        content.innerHTML =
            '<p style="margin-bottom:15px;color:#ccc">Navigate to one of these sites and run the bookmarklet:</p>' +
            '<div style="display:flex;flex-direction:column;gap:10px">' +
            '<a href="https://steamcommunity.com/my" target="_blank" style="display:flex;align-items:center;gap:12px;padding:12px;background:rgba(27,40,56,0.8);border-radius:8px;text-decoration:none;color:#fff;border:1px solid #66c0f4">' +
            '<span style="font-size:20px">🎮</span>' +
            '<div><strong style="color:#66c0f4">Steam Profile</strong><br><span style="font-size:12px;color:#888">Extract your Steam ID</span></div>' +
            '</a>' +
            '<a href="https://www.ea.com" target="_blank" style="display:flex;align-items:center;gap:12px;padding:12px;background:rgba(255,71,71,0.1);border-radius:8px;text-decoration:none;color:#fff;border:1px solid #ff4747">' +
            '<span style="font-size:20px">🎯</span>' +
            '<div><strong style="color:#ff4747">EA.com</strong><br><span style="font-size:12px;color:#888">Extract your EA bearer token</span></div>' +
            '</a>' +
            '<a href="https://account.ubisoft.com/en-US/games-activity" target="_blank" style="display:flex;align-items:center;gap:12px;padding:12px;background:rgba(0,112,255,0.1);border-radius:8px;text-decoration:none;color:#fff;border:1px solid #0070ff">' +
            '<span style="font-size:20px">🕹️</span>' +
            '<div><strong style="color:#0070ff">Ubisoft Games Activity</strong><br><span style="font-size:12px;color:#888">Import your Ubisoft library</span></div>' +
            '</a>' +
            '<a href="https://www.gog.com/feed" target="_blank" style="display:flex;align-items:center;gap:12px;padding:12px;background:rgba(134,50,138,0.1);border-radius:8px;text-decoration:none;color:#fff;border:1px solid #86328a">' +
            '<span style="font-size:20px">🎁</span>' +
            '<div><strong style="color:#86328a">GOG Feed</strong><br><span style="font-size:12px;color:#888">Import your GOG library</span></div>' +
            '</a>' +
            '</div>' +
            '<p style="margin-top:15px;font-size:11px;color:#666">Server: ' + LOCAL_URL + '</p>';
    }
})();
