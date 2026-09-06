document.addEventListener('DOMContentLoaded', () => {
    const navToggle = document.querySelector('.nav-toggle');
    const navLinks = document.querySelector('.nav-links');

    if (navToggle && navLinks) {
        navToggle.addEventListener('click', () => {
            navLinks.classList.toggle('active');
            navToggle.classList.toggle('active');
        });

        document.addEventListener('click', (e) => {
            if (!navLinks.contains(e.target) && !navToggle.contains(e.target)) {
                navLinks.classList.remove('active');
                navToggle.classList.remove('active');
                document.querySelectorAll('.nav-dropdown').forEach(d => d.classList.remove('open'));
            }
        });

        document.querySelectorAll('.nav-dropdown-toggle').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const dropdown = btn.closest('.nav-dropdown');
                const wasOpen = dropdown.classList.contains('open');
                document.querySelectorAll('.nav-dropdown').forEach(d => d.classList.remove('open'));
                if (!wasOpen) dropdown.classList.add('open');
            });
        });

        document.addEventListener('click', (e) => {
            if (!e.target.closest('.nav-dropdown')) {
                document.querySelectorAll('.nav-dropdown').forEach(d => d.classList.remove('open'));
            }
        });
    }

    document.querySelectorAll('a[href^="/"]').forEach(link => {
        link.addEventListener('click', () => {
            if (navLinks) navLinks.classList.remove('active');
            if (navToggle) navToggle.classList.remove('active');
        });
    });

    // Scroll animations
    const observerOptions = {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    };

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
                observer.unobserve(entry.target);
            }
        });
    }, observerOptions);

    document.querySelectorAll('.scroll-animate, .leaderboard-row, .stat-item, .stat-card').forEach(el => {
        if (el.classList.contains('scroll-animate') || !el.closest('#leaderboardTable')) {
            el.classList.add('scroll-animate');
            observer.observe(el);
        }
    });

    // Feature card staggered reveal on scroll
    const featureObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.remove('pre-reveal');
                entry.target.classList.add('reveal');
                featureObserver.unobserve(entry.target);
            }
        });
    }, { threshold: 0.2 });

    document.querySelectorAll('.home-feature').forEach(el => {
        el.classList.add('pre-reveal');
        featureObserver.observe(el);
    });

    // Hover tilt on stat cards
    document.querySelectorAll('.hero-stat-card').forEach(card => {
        card.addEventListener('mousemove', (e) => {
            const rect = card.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            const centerX = rect.width / 2;
            const centerY = rect.height / 2;
            const rotateX = ((y - centerY) / centerY) * -8;
            const rotateY = ((x - centerX) / centerX) * 8;
            card.style.transform = `rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale3d(1.03, 1.03, 1.03)`;
        });
        card.addEventListener('mouseleave', () => {
            card.style.transform = 'rotateX(0) rotateY(0) scale3d(1, 1, 1)';
        });
    });

    // Hover tilt on feature cards
    document.querySelectorAll('.home-feature').forEach(card => {
        card.addEventListener('mousemove', (e) => {
            const rect = card.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            const centerX = rect.width / 2;
            const centerY = rect.height / 2;
            const rotateX = ((y - centerY) / centerY) * -5;
            const rotateY = ((x - centerX) / centerX) * 5;
            card.style.transform = `perspective(600px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale3d(1.02, 1.02, 1.02)`;
        });
        card.addEventListener('mouseleave', () => {
            card.style.transform = 'perspective(600px) rotateX(0) rotateY(0) scale3d(1, 1, 1)';
        });
    });

    // Command list staggered reveal on scroll
    const cmdObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('reveal');
                cmdObserver.unobserve(entry.target);
            }
        });
    }, { threshold: 0.2 });

    document.querySelectorAll('.home-cmd').forEach(el => cmdObserver.observe(el));

    // Typing effect on command names
    const cmdNameObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                typeCommandNames();
                cmdNameObserver.unobserve(entry.target);
            }
        });
    }, { threshold: 0.3 });

    const cmdList = document.querySelector('.home-cmd-list');
    if (cmdList) cmdNameObserver.observe(cmdList);

    function typeCommandNames() {
        const names = document.querySelectorAll('.home-cmd-name');
        names.forEach((el, i) => {
            const fullText = el.textContent;
            el.textContent = '';
            const cursor = document.createElement('span');
            cursor.className = 'typing-cursor';
            el.appendChild(cursor);

            setTimeout(() => {
                let j = 0;
                const interval = setInterval(() => {
                    el.textContent = fullText.substring(0, j + 1);
                    el.appendChild(cursor);
                    j++;
                    if (j >= fullText.length) {
                        clearInterval(interval);
                        setTimeout(() => cursor.remove(), 800);
                    }
                }, 40);
            }, i * 500);
        });
    }

    // Mouse glow spotlight (home page only)
    if (document.querySelector('.home-hero')) {
        const mouseGlow = document.createElement('div');
        mouseGlow.className = 'mouse-glow';
        document.body.appendChild(mouseGlow);

        document.addEventListener('mousemove', (e) => {
            mouseGlow.style.left = e.clientX + 'px';
            mouseGlow.style.top = e.clientY + 'px';
            mouseGlow.classList.add('active');
        });

        document.addEventListener('mouseleave', () => {
            mouseGlow.classList.remove('active');
        });
    }

    // Floating particles
    const canvas = document.getElementById('particles-canvas');
    // Skip the animation entirely on data-dense pages (e.g. leaderboard) and
    // on touch devices where it would drain battery.
    const isDataPage = document.body.classList.contains('lb-page-mode');
    const isTouch = window.matchMedia && window.matchMedia('(hover: none)').matches;
    if (canvas && !isDataPage && !isTouch) {
        const ctx = canvas.getContext('2d');
        let particles = [];
        let w, h;
        let rafId = null;

        function resize() {
            const hero = canvas.parentElement;
            w = canvas.width = hero.offsetWidth;
            h = canvas.height = hero.offsetHeight;
        }

        function createParticles() {
            particles = [];
            const count = Math.floor((w * h) / 15000);
            for (let i = 0; i < count; i++) {
                particles.push({
                    x: Math.random() * w,
                    y: Math.random() * h,
                    r: Math.random() * 2 + 0.5,
                    vx: (Math.random() - 0.5) * 0.3,
                    vy: (Math.random() - 0.5) * 0.3,
                    alpha: Math.random() * 0.4 + 0.1
                });
            }
        }

        function drawParticles() {
            ctx.clearRect(0, 0, w, h);
            for (const p of particles) {
                p.x += p.vx;
                p.y += p.vy;
                if (p.x < 0) p.x = w;
                if (p.x > w) p.x = 0;
                if (p.y < 0) p.y = h;
                if (p.y > h) p.y = 0;
                ctx.beginPath();
                ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
                ctx.fillStyle = `rgba(132, 56, 252, ${p.alpha})`;
                ctx.fill();
            }
            rafId = requestAnimationFrame(drawParticles);
        }

        function start() {
            if (!rafId) rafId = requestAnimationFrame(drawParticles);
        }
        function stop() {
            if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
        }

        resize();
        createParticles();
        start();
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) stop(); else start();
        });
        window.addEventListener('resize', () => { resize(); createParticles(); });
    }

    // Typing effect on tagline
    const taglineEl = document.getElementById('taglineText');
    if (taglineEl) {
        const phrases = [
            'Modern Discord bot.',
            'Clean, fast, slightly chaotic.',
            'Level up your server.',
            'AI chat, built in.',
            'Moderation, built in.',
            'Vote for 2x XP.',
            'Open source, privacy friendly.',
            'No paywalls. No data collection. Just works.',
            'Your server, your data.',
            'Leveling that actually works.',
            'Free forever. No catches.',
            'Voice XP, QOTD, and more.',
            'Music, built in.',
            'Multiplayer games, built in.',
            'Web profiles, shareable everywhere.',
            'Rate the bot, shape its future.'
        ];
        let phraseIdx = 0;
        let charIdx = 0;
        let deleting = false;
        let pauseTimer = 0;

        function typeTick() {
            const current = phrases[phraseIdx];

            if (!deleting) {
                taglineEl.textContent = current.substring(0, charIdx + 1);
                charIdx++;
                if (charIdx === current.length) {
                    deleting = true;
                    pauseTimer = 60;
                    setTimeout(typeTick, 1200);
                    return;
                }
                setTimeout(typeTick, 40 + Math.random() * 30);
            } else {
                if (pauseTimer > 0) {
                    pauseTimer--;
                    setTimeout(typeTick, 30);
                    return;
                }
                taglineEl.textContent = current.substring(0, charIdx);
                charIdx--;
                if (charIdx < 0) {
                    deleting = false;
                    phraseIdx = (phraseIdx + 1) % phrases.length;
                    charIdx = 0;
                    setTimeout(typeTick, 250);
                    return;
                }
                setTimeout(typeTick, 20);
            }
        }

        setTimeout(typeTick, 500);
    }

    // Leaderboard controls
    try {
        const filterBtns = document.querySelectorAll('.sortable-header');
        const guildInput = document.getElementById('guildInput');
        const guildBtn = document.getElementById('guildBtn');
        const findMeBtn = document.getElementById('findMeBtn');
        const findMeInput = document.getElementById('findMeInput');

        function buildUrl(params) {
            const url = new URL(window.location.href);
            for (const [k, v] of Object.entries(params)) {
                if (v === '' || v === null || v === undefined) {
                    url.searchParams.delete(k);
                } else {
                    url.searchParams.set(k, v);
                }
            }
            return url.pathname + url.search;
        }

        function getParams() {
            const p = new URLSearchParams(window.location.search);
            return {
                guild: p.get('guild') || '0',
                sort: p.get('sort') || 'level',
                dir: p.get('dir') || 'desc',
                page: p.get('page') || '1'
            };
        }

        function goSort(sortKey, dir) {            const params = getParams();
            params.sort = sortKey;
            params.dir = dir;
            params.page = '1';
            window.location.href = buildUrl(params);
        }

        if (filterBtns.length) {
            filterBtns.forEach(btn => {
                btn.addEventListener('click', () => {
                    const params = getParams();
                    const sortKey = btn.dataset.sort;
                    let dir = params.sort === sortKey ? (params.dir === 'desc' ? 'asc' : 'desc') : 'desc';
                    // data-dir bakes in the same toggle; use it as the authoritative target
                    if (btn.dataset.dir === 'asc' || btn.dataset.dir === 'desc') dir = btn.dataset.dir;
                    goSort(sortKey, dir);
                });
            });
        }

        if (guildBtn && guildInput) {
            function goGuild() {
                const params = getParams();
                params.guild = guildInput.value.trim() || '0';
                params.page = '1';
                window.location.href = buildUrl(params);
            }
            guildBtn.addEventListener('click', goGuild);
            guildInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') goGuild();
            });
        }

        if (findMeBtn && findMeInput) {
            const acBox = document.getElementById('lbAutocomplete');
            let findOffset = 0;
            let findRows = [];
            let acItems = [];
            let acIndex = -1;
            let acDebounce = null;

            function goServerFind(query, guildOverride) {
                findRows = [];
                findOffset = 0;
                const params = getParams();
                params.find = query;
                if (guildOverride) params.guild = String(guildOverride);
                params.fi = '0';
                params.page = '1';
                window.location.href = buildUrl(params);
            }

            function matchRows(term, onlyUsername) {
                const rows = Array.from(document.querySelectorAll('.leaderboard-row:not(.header)'));
                return rows.filter(row => {
                    if (onlyUsername) return (row.dataset.usern || '').includes(term);
                    return (row.dataset.username || '').includes(term) || (row.dataset.usern || '').includes(term);
                });
            }

            function setActiveMatch(matches, idx) {
                matches.forEach(r => r.classList.remove('find-highlight'));
                const row = matches[idx];
                if (!row) return;
                row.classList.add('find-highlight');
                row.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }

            function currentMatches() {
                const q = findMeInput.value.toLowerCase().trim();
                if (!q) return [];
                const onlyUsername = q.startsWith('@');
                const term = onlyUsername ? q.slice(1) : q;
                return matchRows(term, onlyUsername);
            }

            function stepFind(step) {
                const matches = currentMatches();
                if (!matches.length) return;
                if (findRows !== matches) { findRows = matches; findOffset = 0; }
                findOffset = (findOffset + step + matches.length) % matches.length;
                setActiveMatch(matches, findOffset);
            }

            function doFindMe() {
                const query = findMeInput.value;
                const matches = currentMatches();
                if (matches.length) {
                    if (findRows !== matches || findOffset >= matches.length) findOffset = 0;
                    findRows = matches;
                    setActiveMatch(matches, findOffset);
                    findOffset = (findOffset + 1) % matches.length;
                    if (findOffset === 0) {
                        setTimeout(() => matches.forEach(r => r.classList.remove('find-highlight')), 2500);
                        // Cycled through all in-page matches -> reload with server search
                        // so matches on other pages and the full count become available.
                        goServerFind(query.trim());
                    }
                    return;
                }
                goServerFind(query.trim());
            }

            function updateAcHighlight() {
                Array.from(acBox.querySelectorAll('.lb-autocomplete-item')).forEach((el, i) => {
                    el.classList.toggle('highlighted', i === acIndex);
                });
            }

            function hideAc() {
                acBox.hidden = true;
                acItems = [];
                acIndex = -1;
            }

            function renderAc(results) {
                acBox.innerHTML = '';
                acItems = results;
                acIndex = -1;
                acBox.hidden = false;
                if (!results.length) {
                    const e = document.createElement('div');
                    e.className = 'lb-autocomplete-empty';
                    e.textContent = 'No users found';
                    acBox.appendChild(e);
                    return;
                }
                results.forEach((r, i) => {
                    const item = document.createElement('div');
                    item.className = 'lb-autocomplete-item';
                    const img = document.createElement('img');
                    img.src = r.avatar;
                    img.alt = '';
                    const name = document.createElement('span');
                    name.className = 'ac-name';
                    name.textContent = r.display_name || r.username;
                    if (r.display_name && r.display_name !== r.username) {
                        const uname = document.createElement('span');
                        uname.className = 'ac-user';
                        uname.textContent = ' @' + r.username;
                        name.appendChild(uname);
                    }
                    const rank = document.createElement('span');
                    rank.className = 'ac-rank';
                    rank.textContent = '#' + r.rank;
                    item.append(img, name, rank);
                    const select = () => {
                        hideAc();
                        goServerFind(r.username.toLowerCase());
                    };
                    item.addEventListener('mousedown', (e) => { e.preventDefault(); select(); });
                    item.addEventListener('mousemove', () => { acIndex = i; updateAcHighlight(); });
                    acBox.appendChild(item);
                });
            }

            async function fetchAc() {
                const raw = findMeInput.value.trim();
                if (!raw) { hideAc(); return; }
                const params = getParams();
                const url = '/api/leaderboard/search?q=' + encodeURIComponent(raw) + '&guild=' + params.guild;
                try {
                    const resp = await fetch(url, { headers: { 'X-Requested-With': 'fetch' } });
                    const data = await resp.json();
                    renderAc(data.results || []);
                } catch (e) {
                    hideAc();
                }
            }

            findMeBtn.addEventListener('click', doFindMe);
            findMeInput.addEventListener('input', () => {
                clearTimeout(acDebounce);
                findRows = [];
                findOffset = 0;
                acDebounce = setTimeout(fetchAc, 180);
            });
            findMeInput.addEventListener('keydown', (e) => {
                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    if (!acBox.hidden && acItems.length) {
                        acIndex = (acIndex + 1) % acItems.length;
                        updateAcHighlight();
                        const el = acBox.querySelectorAll('.lb-autocomplete-item')[acIndex];
                        if (el) el.scrollIntoView({ block: 'nearest' });
                    } else {
                        stepFind(1);
                    }
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    if (!acBox.hidden && acItems.length) {
                        acIndex = (acIndex - 1 + acItems.length) % acItems.length;
                        updateAcHighlight();
                        const el = acBox.querySelectorAll('.lb-autocomplete-item')[acIndex];
                        if (el) el.scrollIntoView({ block: 'nearest' });
                    } else {
                        stepFind(-1);
                    }
                } else if (e.key === 'Enter') {
                    e.preventDefault();
                    if (!acBox.hidden && acItems.length && acIndex >= 0) {
                        const r = acItems[acIndex];
                        hideAc();
                        goServerFind(r.username.toLowerCase());
                    } else {
                        doFindMe();
                    }
                } else if (e.key === 'Escape') {
                    hideAc();
                    findMeInput.blur();
                }
            });
            findMeInput.addEventListener('focus', () => {
                document.body.classList.add('lb-keyboard-open');
                if (findMeInput.value.trim()) fetchAc();
            });
            findMeInput.addEventListener('blur', () => {
                document.body.classList.remove('lb-keyboard-open');
                setTimeout(hideAc, 120);
            });
            document.addEventListener('click', (e) => {
                if (!e.target.closest('.find-me')) hideAc();
            });
        }
    } catch (e) {
        console.error('Leaderboard error:', e);
    }

    // Live stats on homepage
    const statXp = document.getElementById('statXp');
    const statMessages = document.getElementById('statMessages');
    const statVoice = document.getElementById('statVoice');
    const statServers = document.getElementById('statServers');
    const statMembers = document.getElementById('statMembers');

    if (statXp && statMessages && statVoice) {
        function formatNumber(n) {
            return n.toLocaleString();
        }

        function parseDisplayValue(text) {
            return parseInt(text.replace(/,/g, '')) || 0;
        }

        const prevValues = {
            statXp: 0,
            statMessages: 0,
            statVoice: 0,
            statServers: 0,
            statMembers: 0
        };

        function showIncrement(el, diff) {
            const card = el.closest('.hero-stat-card');
            if (!card || diff <= 0) return;
            const badge = document.createElement('span');
            badge.className = 'stat-increment';
            badge.textContent = '+' + formatNumber(diff);
            card.appendChild(badge);
            badge.addEventListener('animationend', () => badge.remove());
        }

        function animateValue(el, start, end, duration, key) {
            if (start === end) return;
            el.classList.add('stat-updating');
            const diff = end - start;
            const startTime = performance.now();

            function tick(now) {
                const elapsed = now - startTime;
                const progress = Math.min(elapsed / duration, 1);
                const eased = 1 - Math.pow(1 - progress, 5);
                const current = Math.round(start + (end - start) * eased);
                el.textContent = formatNumber(current);
                if (progress < 1) {
                    requestAnimationFrame(tick);
                } else {
                    el.classList.remove('stat-updating');
                    if (key) prevValues[key] = end;
                }
            }

            requestAnimationFrame(tick);
        }

        function pulseCard(el) {
            const num = el.closest('.hero-stat-card')?.querySelector('.hero-stat-num');
            if (!num) return;
            num.classList.remove('stat-pulse');
            void num.offsetWidth;
            num.classList.add('stat-pulse');
            setTimeout(() => num.classList.remove('stat-pulse'), 800);
        }

        function updateStats() {
            fetch('/api/stats')
                .then(r => r.json())
                .then(data => {
                    const newXp = data.total_xp;
                    const newMsg = data.total_messages;
                    const newVoice = Math.floor(data.total_vc_minutes / 60);
                    const newGuilds = data.total_guilds;
                    const newMembers = data.total_members;

                    const xpDiff = newXp - prevValues.statXp;
                    const msgDiff = newMsg - prevValues.statMessages;
                    const voiceDiff = newVoice - prevValues.statVoice;
                    const guildDiff = newGuilds - prevValues.statServers;
                    const memberDiff = newMembers - prevValues.statMembers;

                    const hasChange = xpDiff > 0 || msgDiff > 0 || voiceDiff > 0 || guildDiff > 0 || memberDiff > 0;
                    if (hasChange) {
                        resetLiveIndicator();
                    } else if (liveIndicator) {
                        liveIndicator.classList.add('stale');
                    }

                    animateValue(statXp, prevValues.statXp, newXp, 1600, 'statXp');
                    animateValue(statMessages, prevValues.statMessages, newMsg, 1600, 'statMessages');
                    animateValue(statVoice, prevValues.statVoice, newVoice, 1600, 'statVoice');
                    if (statServers) animateValue(statServers, prevValues.statServers, newGuilds, 1600, 'statServers');
                    if (statMembers) animateValue(statMembers, prevValues.statMembers, newMembers, 1600, 'statMembers');

                    setTimeout(() => {
                        if (xpDiff > 0) { showIncrement(statXp, xpDiff); pulseCard(statXp); }
                        if (msgDiff > 0) { showIncrement(statMessages, msgDiff); pulseCard(statMessages); }
                        if (voiceDiff > 0) { showIncrement(statVoice, voiceDiff); pulseCard(statVoice); }
                        if (guildDiff > 0 && statServers) { showIncrement(statServers, guildDiff); pulseCard(statServers); }
                        if (memberDiff > 0 && statMembers) { showIncrement(statMembers, memberDiff); pulseCard(statMembers); }
                    }, 1600);
                })
                .catch(() => {});
        }

        const liveIndicator = document.getElementById('liveIndicator');
        const liveCountdown = document.getElementById('liveCountdown');
        const liveProgressBar = document.getElementById('liveProgressBar');
        let progressInterval = null;

        function resetLiveIndicator() {
            if (!liveIndicator) return;
            liveIndicator.classList.remove('stale');
            liveIndicator.classList.remove('flash');
            void liveIndicator.offsetWidth;
            liveIndicator.classList.add('flash');
            setTimeout(() => liveIndicator.classList.remove('flash'), 600);

            if (liveCountdown) liveCountdown.textContent = '15s';
            if (liveProgressBar) liveProgressBar.style.width = '100%';

            clearInterval(progressInterval);
            const startTime = Date.now();
            progressInterval = setInterval(() => {
                const elapsed = Date.now() - startTime;
                const pct = Math.max(100 - (elapsed / 15000) * 100, 0);
                const remaining = Math.max(15 - Math.floor(elapsed / 1000), 0);
                if (liveProgressBar) liveProgressBar.style.width = pct + '%';
                if (liveCountdown) liveCountdown.textContent = remaining + 's';
                if (remaining <= 0) clearInterval(progressInterval);
            }, 300);
        }

        updateStats();
        resetLiveIndicator();
        setInterval(updateStats, 15000);
    }

    // Setup page: timeline scroll reveal
    const setupBlocks = document.querySelectorAll('.setup-block[data-step]');
    const setupTimeline = document.querySelector('.setup-steps');
    if (setupBlocks.length && setupTimeline) {
        function updateTimelineLength() {
            const lastBadge = setupBlocks[setupBlocks.length - 1].querySelector('.setup-step-badge');
            if (lastBadge) {
                const containerRect = setupTimeline.getBoundingClientRect();
                const badgeRect = lastBadge.getBoundingClientRect();
                const offset = badgeRect.top - containerRect.top + badgeRect.height;
                setupTimeline.style.setProperty('--timeline-height', offset + 'px');
            }
        }
        updateTimelineLength();
        window.addEventListener('resize', updateTimelineLength);

        const setupObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const step = parseInt(entry.target.dataset.step);
                    const animClass = step % 2 === 1 ? 'reveal-from-left' : 'reveal-from-right';
                    entry.target.classList.add(animClass);

                    const badge = entry.target.querySelector('.step-badge');
                    if (badge) {
                        setTimeout(() => badge.classList.add('pulse'), 300);
                        setTimeout(() => badge.classList.remove('pulse'), 1100);
                    }

                    setupObserver.unobserve(entry.target);
                }
            });
        }, { threshold: 0.15 });

        setupBlocks.forEach(block => setupObserver.observe(block));
    }

    // Setup page: command grid stagger reveal
    const commandItems = document.querySelectorAll('.command-item');
    if (commandItems.length) {
        const cmdGridObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('reveal');
                    cmdGridObserver.unobserve(entry.target);
                }
            });
        }, { threshold: 0.2 });

        commandItems.forEach(item => cmdGridObserver.observe(item));
    }

    // Setup page: scroll progress dots
    const setupProgress = document.getElementById('setupProgress');
    const progressDots = setupProgress ? setupProgress.querySelectorAll('.setup-progress-dot') : [];
    if (setupProgress && setupBlocks.length) {
        const setupSection = document.querySelector('.setup-steps');

        window.addEventListener('scroll', () => {
            const rect = setupSection.getBoundingClientRect();
            const sectionTop = rect.top;
            const sectionHeight = rect.height;
            const viewportH = window.innerHeight;

            if (sectionTop < viewportH && sectionTop + sectionHeight > 0) {
                setupProgress.classList.add('visible');
            } else {
                setupProgress.classList.remove('visible');
            }

            setupBlocks.forEach((block, i) => {
                const blockRect = block.getBoundingClientRect();
                const blockCenter = blockRect.top + blockRect.height / 2;
                if (blockCenter < viewportH * 0.65 && blockCenter > 0) {
                    progressDots.forEach(d => d.classList.remove('active', 'pulse'));
                    if (progressDots[i]) progressDots[i].classList.add('active');
                }
            });
        });

        progressDots.forEach(dot => {
            dot.addEventListener('click', () => {
                const targetStep = dot.dataset.target;
                const target = document.querySelector(`.setup-block[data-step="${targetStep}"]`);
                if (target) {
                    progressDots.forEach(d => d.classList.remove('active', 'pulse'));
                    dot.classList.add('active', 'pulse');
                    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            });
        });
    }

    // Commands page: category stagger reveal
    const cmdCategories = document.querySelectorAll('.commands-category');
    if (cmdCategories.length) {
        const catObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.style.opacity = '1';
                    entry.target.style.transform = 'translateY(0)';
                    catObserver.unobserve(entry.target);
                }
            });
        }, { threshold: 0.15 });

        cmdCategories.forEach((cat, i) => {
            cat.style.opacity = '0';
            cat.style.transform = 'translateY(30px)';
            cat.style.transition = `opacity 0.6s ease ${i * 0.1}s, transform 0.6s ease ${i * 0.1}s`;
            catObserver.observe(cat);
        });
    }

    // Scroll to top
    const scrollTopBtn = document.getElementById('scrollTop');
    if (scrollTopBtn) {
        window.addEventListener('scroll', () => {
            scrollTopBtn.classList.toggle('visible', window.scrollY > 400);
        }, { passive: true });

        scrollTopBtn.addEventListener('click', () => {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });
    }

    // Stats page: count-up number animation
    const statValues = document.querySelectorAll('.stat-card-value[data-stat]');
    if (statValues.length) {
        function easeOutCubic(t) { return 1 - Math.pow(1 - t, 3); }
        function animateCount(el, target, duration) {
            const startTime = performance.now();
            function tick(now) {
                const progress = Math.min((now - startTime) / duration, 1);
                const current = Math.round(target * easeOutCubic(progress));
                el.textContent = current.toLocaleString();
                if (progress < 1) requestAnimationFrame(tick);
            }
            requestAnimationFrame(tick);
        }
        statValues.forEach(el => {
            const target = parseInt(el.getAttribute('data-stat'), 10) || 0;
            animateCount(el, target, 1200);
        });
    }

    // Copy-to-clipboard for elements with data-copy
    document.querySelectorAll('[data-copy]').forEach(el => {
        el.addEventListener('click', () => {
            const text = el.getAttribute('data-copy');
            if (!navigator.clipboard) return;
            navigator.clipboard.writeText(text).then(() => {
                const old = el.textContent;
                el.textContent = '\u2713 Copied!';
                setTimeout(() => { el.textContent = old; }, 1200);
            }).catch(() => {});
        });
    });

    // Stats page: copy the stats card as an image (client-side screenshot)
    const copyImageBtn = document.getElementById('copyImageBtn');
    const statsCard = document.querySelector('.stats-card');
    if (copyImageBtn && statsCard && window.htmlToImage) {
        const BASE_LABEL = '\u{1F4F8} Copy image';
        let pendingBlob = null;

        function setBtn(text, restartMs) {
            copyImageBtn.textContent = text;
            if (restartMs) {
                setTimeout(() => {
                    copyImageBtn.textContent = BASE_LABEL;
                    copyImageBtn.disabled = false;
                }, restartMs);
            }
        }

        function downloadBlob(blob, name) {
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = name;
            document.body.appendChild(a);
            a.click();
            setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
        }

        function buildShareClone() {
            const clone = statsCard.cloneNode(true);
            clone.classList.add('stats-card--share');
            clone.querySelector('.stats-actions')?.remove();
            const avatarImg = clone.querySelector('.stats-avatar');
            if (avatarImg?.src) avatarImg.src = avatarImg.src.replace('size=128', 'size=512');

            const mark = document.createElement('div');
            mark.className = 'stats-share-mark';
            mark.textContent = 'VOIDWAVE';
            clone.querySelector('.stats-avatar-wrap').insertAdjacentElement('beforebegin', mark);

            const values = clone.querySelectorAll('.stats-grid .stat-card-lg .stat-card-value');
            const totalXp = parseInt(String(values[0]?.textContent || '0').replace(/\D/g, ''), 10) || 0;

            const xpLine = document.createElement('div');
            xpLine.className = 'stats-xp-line';
            const cur = document.createElement('span');
            cur.className = 'xp-cur';
            cur.textContent = (clone.querySelector('.xp-bar-text')?.textContent || '').trim();
            xpLine.appendChild(cur);
            if (totalXp) {
                const tot = document.createElement('span');
                tot.className = 'xp-tot';
                tot.textContent = '\u00b7 ' + totalXp.toLocaleString('en-US') + ' XP total';
                xpLine.appendChild(tot);
            }
            clone.querySelector('.xp-bar-container')?.insertAdjacentElement('afterend', xpLine);

            let rankUp = clone.querySelector('.stats-rank-up');
            let fillPct = 0;
            if (rankUp) {
                const m = rankUp.textContent.match(/[\d,]+/);
                const xpToOvertake = m ? parseInt(m[0].replace(/,/g, ''), 10) : 0;
                const above = totalXp + xpToOvertake;
                fillPct = above > 0 ? Math.min(100, Math.round(totalXp / above * 100)) : 0;
            } else {
                rankUp = document.createElement('div');
                rankUp.className = 'stats-rank-up';
                const span = document.createElement('span');
                span.textContent = 'You hold the #1 server rank';
                rankUp.appendChild(span);
                fillPct = 100;
                clone.appendChild(rankUp);
            }
            const bar = document.createElement('div');
            bar.className = 'rank-up-bar';
            const fill = document.createElement('div');
            fill.className = 'rank-up-fill';
            fill.style.width = fillPct + '%';
            bar.appendChild(fill);
            rankUp.insertBefore(bar, rankUp.firstChild);

            const foot = document.createElement('div');
            foot.className = 'stats-share-foot';
            foot.textContent = 'voidwave.xangey.dev';
            clone.appendChild(foot);

            return clone;
        }

        async function renderCard() {
            await document.fonts.ready;
            const clone = buildShareClone();
            const wrap = document.createElement('div');
            wrap.style.cssText = 'position:fixed;left:-99999px;top:0;z-index:-1;pointer-events:none;';
            wrap.appendChild(clone);
            document.body.appendChild(wrap);
            try {
                return await htmlToImage.toPng(clone, { pixelRatio: 1 });
            } finally {
                wrap.remove();
            }
        }

        window.__renderCard = renderCard;
        window.__cardRect = async () => {
            await document.fonts.ready;
            const clone = buildShareClone();
            const wrap = document.createElement('div');
            wrap.style.cssText = 'position:fixed;left:-99999px;top:0;';
            wrap.appendChild(clone);
            document.body.appendChild(wrap);
            const box = (sel) => {
                const el = clone.querySelector(sel);
                if (!el) return null;
                const b = el.getBoundingClientRect();
                return { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) };
            };
            const cRect = clone.getBoundingClientRect();
            const rel = (b) => ({ x: Math.round(b.x - cRect.x), y: Math.round(b.y - cRect.y), w: Math.round(b.width), h: Math.round(b.height) });
            const out = {};
            for (const s of ['.stats-share-mark', '.stats-avatar', '.stats-username', '.stats-username-sub', '.stats-level', '.xp-bar-container', '.stats-xp-line', '.stats-grid', '.stat-card-lg', '.stats-rank-up', '.rank-up-bar', '.rank-up-fill', '.stats-share-foot', '.stats-rank-badge']) {
                const el = clone.querySelector(s);
                out[s] = el ? rel(el.getBoundingClientRect()) : null;
            }
            out['.stat-card-icon'] = [...clone.querySelectorAll('.stat-card-icon')].map((el) => rel(el.getBoundingClientRect()));
            out['.card'] = { w: clone.offsetWidth, h: clone.offsetHeight };
            wrap.remove();
            return out;
        }

        copyImageBtn.addEventListener('click', async () => {
            if (pendingBlob) {
                const blob = pendingBlob;
                pendingBlob = null;
                setBtn('\u{2B07} Downloading\u2026');
                const name = (document.querySelector('.stats-username')?.textContent || 'user').trim().toLowerCase().replace(/[^a-z0-9]+/g, '-') + '-stats.png';
                downloadBlob(blob, name);
                setBtn('\u{2B07} Downloaded!', 1600);
                return;
            }

            copyImageBtn.disabled = true;
            setBtn('\u{1F4F8} Rendering\u2026');
            try {
                const dataUrl = await renderCard();
                const blob = await (await fetch(dataUrl)).blob();
                if (navigator.clipboard && window.ClipboardItem) {
                    try {
                        await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
                        setBtn('\u2713 Copied!', 1600);
                        return;
                    } catch (e) { /* clipboard rejected, offer download below */ }
                }
                pendingBlob = blob;
                copyImageBtn.disabled = false;
                setBtn('\u{2B07} Save image');
            } catch (err) {
                setBtn('\u2717 Couldn\u2019t render', 2000);
            }
        });
    }

    // Footer year
    const footerYear = document.getElementById('footerYear');
    if (footerYear) {
        footerYear.textContent = new Date().getFullYear();
    }
});
