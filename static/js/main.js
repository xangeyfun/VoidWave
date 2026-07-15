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

    document.querySelectorAll('.feature-card, .leaderboard-row, .stat-item').forEach(el => {
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
});
