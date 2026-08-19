document.addEventListener('DOMContentLoaded', () => {
    // Enable a confirm button only when the typed word matches
    document.querySelectorAll('[data-confirm-check]').forEach(wrap => {
        const input = wrap.querySelector('[data-confirm-input]');
        const required = (wrap.dataset.confirmCheck || '').toUpperCase();
        const submit = wrap.querySelector('[data-confirm-submit]');
        const hint = wrap.querySelector('[data-confirm-hint]');

        if (!input || !submit) return;

        const sync = () => {
            const val = input.value.trim().toUpperCase();
            const match = val === required;
            submit.disabled = !match;
            if (hint) {
                hint.textContent = match ? 'Matches' : `Type ${required} to enable`;
                hint.style.color = match ? 'var(--success)' : 'var(--text-muted)';
            }
        };
        input.addEventListener('input', sync);
        sync();
    });

    // Copy-to-clipboard for elements with data-copy
    document.querySelectorAll('[data-copy]').forEach(el => {
        el.addEventListener('click', () => {
            const text = el.getAttribute('data-copy');
            navigator.clipboard?.writeText(text).then(() => {
                const old = el.textContent;
                el.textContent = 'Copied!';
                el.style.color = 'var(--success)';
                setTimeout(() => {
                    el.textContent = old;
                    el.style.color = '';
                }, 1200);
            }).catch(() => {});
        });
    });

    // Confirm-on-click destructive buttons (double-click pattern)
    document.querySelectorAll('[data-armed]').forEach(btn => {
        let armed = false;
        btn.addEventListener('click', (e) => {
            if (!armed) {
                e.preventDefault();
                armed = true;
                const old = btn.textContent;
                btn.textContent = 'Click again to confirm';
                btn.classList.add('btn-danger');
                setTimeout(() => {
                    armed = false;
                    btn.textContent = old;
                    btn.classList.remove('btn-danger');
                }, 3000);
                return;
            }
        });
    });

    // Auto-dismiss alerts after a few seconds
    document.querySelectorAll('.alert[data-auto-dismiss]').forEach(al => {
        setTimeout(() => {
            al.style.transition = 'opacity 0.5s ease';
            al.style.opacity = '0';
            setTimeout(() => al.remove(), 500);
        }, 6000);
    });

    // Keyboard shortcut: Ctrl+K or Cmd+K to focus search inputs
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            const searchInput = document.querySelector('.admin-main input[type="text"][autofocus]')
                || document.querySelector('.admin-main input[type="text"][name="q"]')
                || document.querySelector('.admin-main input[type="text"][name="search"]');
            if (searchInput) searchInput.focus();
        }
    });

    // Smooth number counting animation for stat values
    document.querySelectorAll('.stat-value').forEach(el => {
        const text = el.textContent.trim();
        const num = parseFloat(text.replace(/[,]/g, ''));
        if (isNaN(num) || text.includes('m') || text.includes('h') || text.includes('%')) return;

        const formatted = text;
        const duration = 600;
        const start = performance.now();

        const animate = (now) => {
            const elapsed = now - start;
            const progress = Math.min(elapsed / duration, 1);
            const eased = 1 - Math.pow(1 - progress, 3);
            const current = Math.round(num * eased);

            el.textContent = current.toLocaleString();

            if (progress < 1) {
                requestAnimationFrame(animate);
            } else {
                el.textContent = formatted;
            }
        };

        requestAnimationFrame(animate);
    });

    const hamburger = document.getElementById('adminHamburger');
    const overlay = document.getElementById('adminNavOverlay');
    if (hamburger && overlay) {
        hamburger.addEventListener('click', () => {
            document.body.classList.toggle('nav-open');
        });
        overlay.addEventListener('click', () => {
            document.body.classList.remove('nav-open');
        });
    }
});
