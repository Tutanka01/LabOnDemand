import { escapeHtml } from './utils.js';

export function createStatusView({ state, elements, novnc }) {
    const { statusContent, statusActions } = elements;
    const { bindNovncButtons, updateNovncButtonsAvailability } = novnc;

    function buildStatusAccessHtml(accessUrl, currentState) {
        if (!accessUrl) return '';

        const sanitizedUrl = escapeHtml(accessUrl);
        const hasPlaceholder = /IP_DU_NOEUD|IP_EXTERNE|NODE_PORT/.test(accessUrl) || accessUrl.includes('<');

        if (currentState === 'ready' && !hasPlaceholder) {
            return `
                <p style="margin-top: 15px;">Accédez à votre service :</p>
                <a class="access-link" href="${sanitizedUrl}" target="_blank" rel="noopener">
                    <i class="fas fa-link"></i> ${sanitizedUrl}
                    <span class="status-badge success">Prêt</span>
                </a>
            `;
        }

        const infoText = currentState === 'timeout'
            ? 'Nous ne parvenons pas à récupérer l\'URL pour le moment.'
            : 'Utilisez les informations ci-dessus pour déterminer l\'adresse finale une fois le service prêt.';
        const badgeClass = currentState === 'timeout' ? 'status-badge error' : 'status-badge';
        const badgeLabel = currentState === 'timeout' ? 'Indisponible' : 'En attente';

        return `
            <p style="margin-top: 15px;">${infoText}</p>
            <div class="access-link disabled">
                <i class="fas fa-link"></i>
                <span>${sanitizedUrl}</span>
                <span class="${badgeClass}">${badgeLabel}</span>
            </div>
        `;
    }

    function renderStatusView(currentState, overrides = {}) {
        if (!statusContent) return;

        if (!state.currentStatusDeployment) {
            state.currentStatusDeployment = {};
        }

        state.currentStatusDeployment = { ...state.currentStatusDeployment, ...overrides, state: currentState };

        const serviceName = state.currentStatusDeployment.serviceName || state.currentStatusDeployment.id || 'Application';
        const message = state.currentStatusDeployment.message || '';
        const portsSummaryHtml = state.currentStatusDeployment.portsSummaryHtml || '';
        const connectionHintsHtml = state.currentStatusDeployment.connectionHintsHtml || '';
        const inlineNovncBlock = state.currentStatusDeployment.inlineNovncBlock || '';
        const accessUrl = state.currentStatusDeployment.accessUrl || '';
        const deploymentType = state.currentStatusDeployment.deploymentType || '';

        let headerHtml = '';
        let availabilityHtml = '';

        if (currentState === 'ready') {
            headerHtml = `
                <i class="fas fa-check-circle status-icon success"></i>
                <h2>${serviceName} est prêt</h2>
                <p>Votre environnement est prêt à être utilisé.</p>
            `;
            availabilityHtml = `
                <div class="app-availability ready">
                    <i class="fas fa-check-circle app-availability-icon"></i>
                    <span class="app-availability-text">L'application est prête à être utilisée</span>
                </div>
            `;
        } else if (currentState === 'timeout') {
            headerHtml = `
                <i class="fas fa-exclamation-triangle status-icon" style="color: var(--error-color);"></i>
                <h2>Problème de démarrage</h2>
                <p>${serviceName} ne répond pas comme prévu. Vérifiez les détails ou contactez un administrateur.</p>
            `;
            availabilityHtml = `
                <div class="app-availability error">
                    <i class="fas fa-exclamation-triangle app-availability-icon"></i>
                    <span class="app-availability-text">Problème lors de l'initialisation de l'application</span>
                </div>
            `;
        } else if (currentState === 'deleted') {
            headerHtml = `
                <i class="fas fa-info-circle status-icon"></i>
                <h2>Déploiement indisponible</h2>
                <p>L'environnement ${serviceName} n'existe plus ou a été supprimé.</p>
            `;
            availabilityHtml = '';
        } else {
            headerHtml = `
                <i class="fas fa-circle-notch fa-spin status-icon"></i>
                <h2>${serviceName} est en cours de préparation</h2>
                <p>Votre environnement a été déployé avec succès, mais les conteneurs sont toujours en cours de démarrage.</p>
            `;
            availabilityHtml = `
                <div class="app-availability pending">
                    <i class="fas fa-hourglass-half app-availability-icon"></i>
                    <span class="app-availability-text">L'application est en cours d'initialisation. Veuillez patienter...</span>
                </div>
                <p>Vous serez notifié quand votre environnement sera prêt à être utilisé.</p>
            `;
        }

        const messageHtml = message ? `<div class="api-response">${message}</div>` : '';
        const accessHtml = buildStatusAccessHtml(accessUrl, currentState);

        statusContent.innerHTML = `
            ${headerHtml}
            ${availabilityHtml}
            ${messageHtml}
            ${portsSummaryHtml}
            ${connectionHintsHtml}
            ${inlineNovncBlock}
            ${accessHtml}
        `;

        if (statusActions) {
            statusActions.style.display = 'block';
        }

        if (deploymentType === 'netbeans') {
            bindNovncButtons(statusContent);
            updateNovncButtonsAvailability(state.currentStatusDeployment.id);
        }
    }

    function updateStatusViewForDeployment(deploymentId, currentState, overrides = {}) {
        if (!state.currentStatusDeployment || state.currentStatusDeployment.id !== deploymentId) return;
        renderStatusView(currentState, overrides);
    }

    function renderServicePortsSummary(portsDetails, serviceType) {
        if (!Array.isArray(portsDetails) || portsDetails.length === 0) return '';
        const items = portsDetails.map(detail => {
            const label = detail.name ? `<strong>${escapeHtml(String(detail.name))}</strong>` : '<strong>Port</strong>';
            const portVal = escapeHtml(String(detail.port ?? ''));
            const targetVal = escapeHtml(String(detail.target_port ?? ''));
            const nodePort = detail.node_port ? `<span class="port-node">NodePort ${escapeHtml(String(detail.node_port))}</span>` : '';
            const protocol = detail.protocol ? `<span class="port-protocol">${escapeHtml(String(detail.protocol))}</span>` : '';
            return `<li>${label}: ${portVal} → ${targetVal} ${protocol} ${nodePort}</li>`;
        }).join('');
        return `
            <div class="service-ports-summary">
                <h4><i class="fas fa-plug"></i> Ports exposés (${serviceType || 'Service'})</h4>
                <ul class="ports-list">${items}</ul>
            </div>
        `;
    }

    function renderConnectionHints(hints) {
        if (!hints || typeof hints !== 'object') return '';
        const entries = Object.entries(hints).filter(([, info]) => info && typeof info === 'object');
        if (!entries.length) return '';
        const titleMap = {
            novnc: 'Accès navigateur (NoVNC)',
            vnc: 'Client VNC natif',
            audio: 'Canal audio',
        };
        const cards = entries.map(([key, info]) => {
            const title = titleMap[key] || key.toUpperCase();
            const description = info.description ? `<p class="hint-description">${escapeHtml(String(info.description))}</p>` : '';
            const nodePort = info.node_port ? `<li><strong>NodePort:</strong> ${escapeHtml(String(info.node_port))}</li>` : '';
            const targetPort = info.target_port ? `<li><strong>Port interne:</strong> ${escapeHtml(String(info.target_port))}</li>` : '';
            const username = info.username ? `<li><strong>Utilisateur:</strong> ${escapeHtml(String(info.username))}</li>` : '';
            const password = info.password ? `<li><strong>Mot de passe:</strong> ${escapeHtml(String(info.password))}</li>` : '';
            let urlTemplate = '';
            if (info.url_template) {
                let resolved = info.url_template;
                if (info.node_port) {
                    resolved = resolved.replace('<NODE_PORT>', info.node_port);
                }
                urlTemplate = `<li><strong>URL:</strong> <code>${escapeHtml(resolved)}</code></li>`;
            }
            const extra = info.notes ? `<li>${escapeHtml(String(info.notes))}</li>` : '';
            const list = [urlTemplate, nodePort, targetPort, username, password, extra].filter(Boolean).join('');
            if (!list && !description) return '';
            return `
                <div class="connection-hint-card">
                    <h5>${title}</h5>
                    ${description}
                    ${list ? `<ul>${list}</ul>` : ''}
                </div>
            `;
        }).filter(Boolean).join('');
        if (!cards) return '';
        return `
            <div class="connection-hints">
                <h4><i class="fas fa-satellite-dish"></i> Infos de connexion</h4>
                <div class="connection-hints-grid">${cards}</div>
            </div>
        `;
    }

    return {
        renderStatusView,
        updateStatusViewForDeployment,
        buildStatusAccessHtml,
        renderServicePortsSummary,
        renderConnectionHints,
    };
}
