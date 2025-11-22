export function escapeHtml(str) {
    if (typeof str !== 'string') return str;
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
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
