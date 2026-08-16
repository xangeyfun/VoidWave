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
                hint.textContent = match ? '✔ Matches' : `Type ${required} to enable`;
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
                setTimeout(() => { el.textContent = old; }, 1200);
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
});
