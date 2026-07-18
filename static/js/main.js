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

    // Feature card glow on scroll
    const featureObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('glow-in');
                featureObserver.unobserve(entry.target);
            }
        });
    }, { threshold: 0.2 });

    document.querySelectorAll('.home-feature').forEach(el => featureObserver.observe(el));

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

    // Floating particles
    const canvas = document.getElementById('particles-canvas');
    if (canvas) {
        const ctx = canvas.getContext('2d');
        let particles = [];
        let w, h;

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
            requestAnimationFrame(drawParticles);
        }

        resize();
        createParticles();
        drawParticles();
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
            'Open source, privacy friendly.',
            'No paywalls. No data collection. Just works.',
            'Your server, your data.',
            'Leveling that actually works.',
            'Free forever. No catches.',
            'Voice XP, QOTD, and more.'
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

        if (filterBtns.length) {
            filterBtns.forEach(btn => {
                btn.addEventListener('click', () => {
                    const params = getParams();
                    params.sort = btn.dataset.sort;
                    params.dir = btn.dataset.dir;
                    params.page = '1';
                    window.location.href = buildUrl(params);
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
            function doFindMe() {
                const query = findMeInput.value.toLowerCase().trim();
                if (!query) return;

                const rows = document.querySelectorAll('.leaderboard-row:not(.header)');
                for (const row of rows) {
                    const username = row.dataset.username || '';
                    if (username.includes(query)) {
                        row.classList.add('find-highlight');
                        row.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        setTimeout(() => row.classList.remove('find-highlight'), 2000);
                        return;
                    }
                }
            }

            findMeBtn.addEventListener('click', doFindMe);
            findMeInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') doFindMe();
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
            if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
            if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
            return n.toLocaleString();
        }

        function parseDisplayValue(text) {
            text = text.replace(/,/g, '');
            if (text.endsWith('M')) return parseFloat(text) * 1000000;
            if (text.endsWith('K')) return parseFloat(text) * 1000;
            return parseInt(text) || 0;
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

            if (liveCountdown) liveCountdown.textContent = '10s';
            if (liveProgressBar) liveProgressBar.style.width = '100%';

            clearInterval(progressInterval);
            const startTime = Date.now();
            progressInterval = setInterval(() => {
                const elapsed = Date.now() - startTime;
                const pct = Math.max(100 - (elapsed / 10000) * 100, 0);
                const remaining = Math.max(10 - Math.floor(elapsed / 1000), 0);
                if (liveProgressBar) liveProgressBar.style.width = pct + '%';
                if (liveCountdown) liveCountdown.textContent = remaining + 's';
                if (remaining <= 0) clearInterval(progressInterval);
            }, 300);
        }

        updateStats();
        resetLiveIndicator();
        setInterval(updateStats, 10000);
    }
});
