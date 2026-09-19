/* Fullskjerms "ark" som legger seg oppå dashbordet. Brukes til detaljstyring
   av en pære og til bekreftelser. Bare ett ark er åpent om gangen. */

let current = null;

/**
 * Åpner et ark.
 * @param {string} title  overskrift
 * @param {(body: HTMLElement) => void} build  fyller innholdet
 * @param {{onClose?: () => void}} opts
 * @returns {{close: () => void, body: HTMLElement}}
 */
export function openSheet(title, build, { onClose } = {}) {
  closeSheet();
  const root = document.getElementById('sheet-root');

  const backdrop = document.createElement('div');
  backdrop.className = 'sheet-backdrop';
  backdrop.innerHTML = `
    <div class="sheet" role="dialog" aria-label="${escapeHtml(title)}">
      <div class="sheet-header">
        <div class="sheet-title">${escapeHtml(title)}</div>
        <button class="sheet-close" aria-label="Lukk">✕</button>
      </div>
      <div class="sheet-body"></div>
    </div>`;

  const body = backdrop.querySelector('.sheet-body');
  const handle = {
    body,
    close() {
      if (current !== handle) return;
      backdrop.remove();
      current = null;
      onClose?.();
    },
  };

  backdrop.querySelector('.sheet-close').addEventListener('click', handle.close);
  // Trykk utenfor arket lukker det
  backdrop.addEventListener('click', (e) => { if (e.target === backdrop) handle.close(); });

  build(body, handle);
  root.appendChild(backdrop);
  current = handle;
  return handle;
}

export function closeSheet() {
  current?.close();
}

/** Enkel ja/nei-dialog. Løser til true hvis brukeren bekrefter. */
export function confirmSheet(title, text, { okLabel = 'Ja', cancelLabel = 'Avbryt', danger = false } = {}) {
  return new Promise((resolve) => {
    let answered = false;
    const handle = openSheet(title, (body) => {
      body.innerHTML = `
        <div class="confirm-text">${escapeHtml(text)}</div>
        <div class="confirm-actions">
          <button class="btn btn-ghost" data-act="cancel">${escapeHtml(cancelLabel)}</button>
          <button class="btn ${danger ? 'btn-danger' : 'is-active'}" data-act="ok">${escapeHtml(okLabel)}</button>
        </div>`;
      body.querySelector('[data-act=ok]').addEventListener('click', () => { answered = true; handle.close(); resolve(true); });
      body.querySelector('[data-act=cancel]').addEventListener('click', () => { answered = true; handle.close(); resolve(false); });
    }, { onClose: () => { if (!answered) resolve(false); } });
  });
}

export function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
