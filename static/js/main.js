document.addEventListener('DOMContentLoaded', () => {
    console.log('JS loaded');
    const navToggle = document.querySelector('.nav-toggle');
    const navLinks = document.querySelector('.nav-links');

    if (navToggle && navLinks) {
        navToggle.addEventListener('click', () => {
            navLinks.classList.toggle('active');
            navToggle.classList.toggle('active');
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

    document.querySelectorAll('.leaderboard-row, .stat-item, .stat-card').forEach(el => {
        if (!el.closest('#leaderboardTable')) {
            el.classList.add('scroll-animate');
            observer.observe(el);
        }
    });

    // Leaderboard controls
    try {
        const filterBtns = document.querySelectorAll('.filter-btn');
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

        function animateValue(el, start, end, duration) {
            if (start === end) return;
            el.classList.add('stat-updating');
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
                }
            }

            requestAnimationFrame(tick);
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

                    animateValue(statXp, parseDisplayValue(statXp.textContent), newXp, 1600);
                    animateValue(statMessages, parseDisplayValue(statMessages.textContent), newMsg, 1600);
                    animateValue(statVoice, parseDisplayValue(statVoice.textContent), newVoice, 1600);
                    if (statServers) animateValue(statServers, parseDisplayValue(statServers.textContent), newGuilds, 1600);
                    if (statMembers) animateValue(statMembers, parseDisplayValue(statMembers.textContent), newMembers, 1600);
                })
                .catch(() => {});
        }

        updateStats();
        setInterval(updateStats, 30000);

        // Animate servers and members on load
        if (statServers) animateValue(statServers, 0, parseDisplayValue(statServers.textContent), 1800);
        if (statMembers) animateValue(statMembers, 0, parseDisplayValue(statMembers.textContent), 1800);
    }
});
