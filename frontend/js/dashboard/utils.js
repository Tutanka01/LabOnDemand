export function escapeHtml(str) {
    if (typeof str !== 'string') return str;
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

export function escapeAttr(str) {
    return escapeHtml(String(str ?? ''));
}

const FA_STYLE_CLASSES = new Set([
    'fa',
    'fas',
    'far',
    'fab',
    'fal',
    'fat',
    'fad',
    'fa-solid',
    'fa-regular',
    'fa-brands',
    'fa-light',
    'fa-thin',
    'fa-duotone',
    'fa-sharp',
    'fa-sharp-duotone',
]);

const FA_MODIFIER_CLASSES = new Set([
    'fa-fw',
    'fa-spin',
    'fa-pulse',
    'fa-border',
    'fa-li',
    'fa-inverse',
    'fa-xs',
    'fa-sm',
    'fa-lg',
    'fa-xl',
    'fa-2xl',
]);

export function isFontAwesomeIcon(iconClass) {
    const classes = String(iconClass || '').trim().split(/\s+/).filter(Boolean);
    if (classes.length === 0) return false;

    const hasStyle = classes.some(cls => FA_STYLE_CLASSES.has(cls));
    const hasIcon = classes.some(cls =>
        /^fa-[a-z0-9-]+$/i.test(cls) &&
        !FA_STYLE_CLASSES.has(cls) &&
        !FA_MODIFIER_CLASSES.has(cls)
    );

    return hasStyle && hasIcon;
}

export function renderIcon(icon, extraClass = '', fallbackClass = 'fa-solid fa-cube') {
    const rawIcon = String(icon || '').trim();
    const classSuffix = extraClass ? ` ${escapeAttr(extraClass)}` : '';

    if (isFontAwesomeIcon(rawIcon)) {
        return `<i class="${escapeAttr(rawIcon)}${classSuffix}" aria-hidden="true"></i>`;
    }

    if (rawIcon) {
        return `<span class="emoji-icon${classSuffix}" role="img" aria-label="icône">${escapeHtml(rawIcon)}</span>`;
    }

    return `<i class="${escapeAttr(fallbackClass)}${classSuffix}" aria-hidden="true"></i>`;
}

export function mapPhaseToClass(phase) {
    const value = (phase || '').toLowerCase();
    if (value === 'bound') return 'bound';
    if (value === 'available') return 'ready';
    if (value === 'released') return 'released';
    return '';
}

export function formatIsoDateShort(iso) {
    if (!iso) return 'Date inconnue';
    try {
        const date = new Date(iso);
        if (Number.isNaN(date.getTime())) return iso;
        return date.toLocaleString();
    } catch {
        return iso;
    }
}

export function pct(part, whole) {
    return whole ? Math.min(100, Math.round((part / whole) * 100)) : 0;
}

export function barClass(p) {
    if (p < 70) return 'pb-green';
    if (p < 90) return 'pb-amber';
    return 'pb-red';
}
