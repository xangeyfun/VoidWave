document.addEventListener('DOMContentLoaded', function() {
    // Enable a confirm button only when the typed word matches
    document.querySelectorAll('[data-confirm-check]').forEach(function(wrap) {
        var input = wrap.querySelector('[data-confirm-input]');
        var required = (wrap.dataset.confirmCheck || '').toUpperCase();
        var submit = wrap.querySelector('[data-confirm-submit]');
        var hint = wrap.querySelector('[data-confirm-hint]');

        if (!input || !submit) return;

        var sync = function() {
            var val = input.value.trim().toUpperCase();
            var match = val === required;
            submit.disabled = !match;
            if (hint) {
                hint.textContent = match ? 'Matches' : 'Type ' + required + ' to enable';
                hint.style.color = match ? 'var(--success)' : 'var(--text-muted)';
            }
        };
        input.addEventListener('input', sync);
        sync();
    });

    // Copy-to-clipboard for elements with data-copy
    document.querySelectorAll('[data-copy]').forEach(function(el) {
        el.addEventListener('click', function() {
            var text = el.getAttribute('data-copy');
            if (navigator.clipboard) {
                navigator.clipboard.writeText(text).then(function() {
                    var old = el.textContent;
                    el.textContent = 'Copied!';
                    el.style.color = 'var(--success)';
                    setTimeout(function() {
                        el.textContent = old;
                        el.style.color = '';
                    }, 1200);
                }).catch(function() {});
            }
        });
    });

    // Confirm-on-click for destructive buttons (double-click pattern)
    document.querySelectorAll('[data-armed]').forEach(function(btn) {
        var armed = false;
        btn.addEventListener('click', function(e) {
            if (!armed) {
                e.preventDefault();
                armed = true;
                var old = btn.textContent;
                btn.textContent = 'Click again to confirm';
                btn.classList.add('btn-danger');
                setTimeout(function() {
                    armed = false;
                    btn.textContent = old;
                    btn.classList.remove('btn-danger');
                }, 3000);
                return;
            }
        });
    });

    // Auto-dismiss alerts after a few seconds
    document.querySelectorAll('.alert[data-auto-dismiss]').forEach(function(al) {
        setTimeout(function() {
            al.style.transition = 'opacity 0.5s ease';
            al.style.opacity = '0';
            setTimeout(function() { al.remove(); }, 500);
        }, 6000);
    });

    // Keyboard shortcut: Ctrl+K or Cmd+K or / to focus search inputs
    document.addEventListener('keydown', function(e) {
        var isTyping = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            focusSearch();
        } else if (e.key === '/' && !isTyping && !e.ctrlKey && !e.metaKey && !e.altKey) {
            e.preventDefault();
            focusSearch();
        }
    });

    function focusSearch() {
        var searchInput = document.querySelector('.admin-main input[type="text"][autofocus]')
            || document.querySelector('.admin-main input[type="text"][name="q"]')
            || document.querySelector('.admin-main input[type="text"][name="search"]');
        if (searchInput) searchInput.focus();
    }

    // Clickable elements marked data-href navigate on click
    document.querySelectorAll('[data-href]').forEach(function(el) {
        el.addEventListener('click', function(e) {
            if (e.target.closest('a, button, input, select, label, [data-copy]')) return;
            window.location.href = el.getAttribute('data-href');
        });
    });

    // Smooth number counting animation for stat values
    document.querySelectorAll('.stat-value').forEach(function(el) {
        var text = el.textContent.trim();
        var num = parseFloat(text.replace(/[,]/g, ''));
        if (isNaN(num) || text.indexOf('m') !== -1 || text.indexOf('h') !== -1 || text.indexOf('%') !== -1) return;

        var formatted = text;
        var duration = 600;
        var start = performance.now();

        function animate(now) {
            var elapsed = now - start;
            var progress = Math.min(elapsed / duration, 1);
            var eased = 1 - Math.pow(1 - progress, 3);
            var current = Math.round(num * eased);

            el.textContent = current.toLocaleString();

            if (progress < 1) {
                requestAnimationFrame(animate);
            } else {
                el.textContent = formatted;
            }
        }

        requestAnimationFrame(animate);
    });

    // Hamburger menu toggle
    var hamburger = document.getElementById('adminHamburger');
    var overlay = document.getElementById('adminNavOverlay');
    if (hamburger && overlay) {
        hamburger.addEventListener('click', function() {
            document.body.classList.toggle('nav-open');
        });
        overlay.addEventListener('click', function() {
            document.body.classList.remove('nav-open');
        });
    }
});
