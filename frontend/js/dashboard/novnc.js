import { escapeHtml } from './utils.js';

export function createNovncModule({ API_V1, state, elements }) {
    const {
        novncModal,
        novncModalTitle,
        novncFrame,
        novncStatusBanner,
        novncCredentialsBox,
    } = elements;

    function extractNovncInfoFromDetails(details) {
        if (!details) return {};
        const services = details.services || [];
        const accessUrls = details.access_urls || [];
        let nodePort = null;
        let url = null;
        let hostname = null;
        let protocol = null;
        let secure = null;

        services.forEach(service => {
            (service.ports || []).forEach(port => {
                const isNovnc = port.name === 'novnc' || port.port === 6901;
                if (isNovnc && port.node_port) {
                    nodePort = port.node_port;
                    const candidate = accessUrls.find(entry => entry.node_port === port.node_port);
                    if (candidate) {
                        url = candidate.url;
                        try {
                            hostname = new URL(candidate.url).hostname;
                        } catch (err) {
                            hostname = candidate.cluster_ip || hostname;
                        }
                        if (candidate.protocol) {
                            protocol = candidate.protocol.toLowerCase();
                        } else if (candidate.url) {
                            if (candidate.url.startsWith('https://')) {
                                protocol = 'https';
                            } else if (candidate.url.startsWith('http://')) {
                                protocol = 'http';
                            }
                        }
                        if (candidate.secure !== undefined && candidate.secure !== null) {
                            secure = Boolean(candidate.secure);
                        }
                    } else if (!protocol) {
                        protocol = 'https';
                        secure = true;
                    }
                }
            });
        });

        if (!nodePort && accessUrls.length === 1) {
            const first = accessUrls[0];
            nodePort = first.node_port ?? nodePort;
            url = first.url || url;
            try {
                hostname = first.url ? new URL(first.url).hostname : (first.cluster_ip || hostname);
            } catch (err) {
                hostname = first.cluster_ip || hostname;
            }
            if (!protocol) {
                if (first.protocol) {
                    protocol = first.protocol.toLowerCase();
                } else if (first.url) {
                    if (first.url.startsWith('https://')) {
                        protocol = 'https';
                    } else if (first.url.startsWith('http://')) {
                        protocol = 'http';
                    }
                }
            }
            if (secure === null && first.secure !== undefined) {
                secure = Boolean(first.secure);
            }
        }

        if (!protocol && nodePort && Number(nodePort) === 6901) {
            protocol = 'http';
            if (secure === null) {
                secure = false;
            }
        }

        return { nodePort, url, hostname, protocol, secure };
    }

    function registerNovncEndpoint(deploymentId, namespace, info = {}) {
        if (!deploymentId) return;
        const map = state.novncEndpoints;
        const previous = map.get(deploymentId) || {};
        const merged = { ...previous };
        if (namespace) merged.namespace = namespace;

        Object.entries(info).forEach(([key, value]) => {
            if (value === undefined || value === null) return;
            if (key === 'nodePort') {
                const numeric = Number(value);
                if (!Number.isNaN(numeric)) {
                    merged.nodePort = numeric;
                }
                return;
            }
            if (key === 'protocol') {
                if (typeof value === 'string' && value.trim()) {
                    merged.protocol = value.trim().toLowerCase();
                }
                return;
            }
            if (key === 'secure') {
                merged.secure = Boolean(value);
                return;
            }
            if (key === 'credentials' && typeof value === 'object') {
                merged.credentials = { ...(previous.credentials || {}), ...value };
                return;
            }
            merged[key] = value;
        });

        merged.updatedAt = Date.now();
        map.set(deploymentId, merged);
        updateNovncButtonsAvailability(deploymentId);
    }

    function buildNovncUrl(info) {
        if (!info || !info.nodePort) return null;
        const host = info.hostname || window.location.hostname;
        const port = info.nodePort;
        const preferredScheme = (() => {
            if (typeof info.protocol === 'string' && info.protocol.trim()) {
                const normalized = info.protocol.trim().toLowerCase();
                if (normalized.startsWith('https')) return 'https';
                if (normalized.startsWith('http')) return 'http';
            }
            if (info.secure === true) return 'https';
            if (info.urlTemplate) {
                if (info.urlTemplate.startsWith('https://')) return 'https';
                if (info.urlTemplate.startsWith('http://')) return 'http';
            }
            if (info.url) {
                if (info.url.startsWith('https://')) return 'https';
                if (info.url.startsWith('http://')) return 'http';
            }
            return null;
        })();
        if (info.urlTemplate) {
            return info.urlTemplate
                .replace(/<IP_DU_NOEUD>/g, host)
                .replace(/<IP_EXTERNE>/g, host)
                .replace(/<NODE_PORT>/g, port);
        }
        if (info.url && !info.url.includes('<')) {
            return info.url;
        }
        const protocol = preferredScheme === 'http' ? 'http:' : 'https:';
        return `${protocol}//${host}:${port}/`;
    }

    async function ensureNovncDetails(deploymentId) {
        const current = state.novncEndpoints.get(deploymentId);
        if (!current || !current.namespace) {
            throw new Error('Namespace inconnu pour ce déploiement');
        }
        const response = await fetch(`${API_V1}/k8s/deployments/${current.namespace}/${deploymentId}/details`);
        if (!response.ok) {
            throw new Error('Impossible de récupérer les détails du déploiement');
        }
        const details = await response.json();
        const extracted = extractNovncInfoFromDetails(details);
        registerNovncEndpoint(deploymentId, current.namespace, extracted);
        return state.novncEndpoints.get(deploymentId);
    }

    async function resolveNovncUrl(deploymentId) {
        let info = state.novncEndpoints.get(deploymentId);
        if (!info) {
            throw new Error('Informations NoVNC indisponibles');
        }
        if (!info.nodePort || (info.url && info.url.includes('<'))) {
            info = await ensureNovncDetails(deploymentId);
        }
        if (!info || !info.nodePort) {
            throw new Error('NodePort NoVNC introuvable');
        }
        let finalUrl = info.url;
        if (!finalUrl || finalUrl.includes('<')) {
            finalUrl = buildNovncUrl(info);
            if (finalUrl) {
                registerNovncEndpoint(deploymentId, info.namespace, { url: finalUrl });
                info = state.novncEndpoints.get(deploymentId);
            }
        }
        if (!finalUrl) {
            throw new Error('Impossible de construire l’URL NoVNC');
        }
        return { url: finalUrl, info };
    }

    function updateNovncButtonsAvailability(deploymentId) {
        const info = state.novncEndpoints.get(deploymentId);
        const buttons = document.querySelectorAll(`.embed-novnc-btn[data-novnc-target="${deploymentId}"]`);
        const hasNodePort = !!(info && info.nodePort);
        const hasUrl = !!(info && info.url && !info.url.includes('<'));

        buttons.forEach(btn => {
            if (!btn) return;
            if (hasNodePort || hasUrl) {
                btn.disabled = false;
                btn.classList.remove('disabled');
                btn.innerHTML = '<i class="fas fa-desktop"></i> Ouvrir dans la page';
            } else {
                btn.disabled = true;
                btn.classList.add('disabled');
                btn.innerHTML = '<i class="fas fa-desktop"></i> En attente NoVNC...';
            }
        });

        if (state.lastLaunchedDeployment && state.lastLaunchedDeployment.id === deploymentId) {
            const hint = document.getElementById('inline-novnc-hint');
            if (hint) {
                if (hasUrl) {
                    hint.textContent = 'Cliquez pour ouvrir la session NetBeans dans la fenêtre intégrée.';
                } else if (hasNodePort) {
                    hint.textContent = 'Le service est presque prêt. Cliquez pour ouvrir la session dès que possible.';
                } else {
                    hint.textContent = 'Configuration du service NoVNC en cours...';
                }
            }
        }
    }

    function prepareNovncModal(deploymentId) {
        if (!novncModal) return;
        if (novncModalTitle) {
            novncModalTitle.innerHTML = `<i class="fas fa-desktop"></i> ${deploymentId} - NoVNC`;
        }
        if (novncStatusBanner) {
            novncStatusBanner.classList.remove('error');
            novncStatusBanner.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Préparation de la session NoVNC...';
        }
        if (novncCredentialsBox) {
            novncCredentialsBox.classList.remove('show');
            novncCredentialsBox.innerHTML = '';
        }
        if (novncFrame) {
            try { novncFrame.src = 'about:blank'; } catch (err) {}
        }
        novncModal.classList.add('show');
    }

    async function openNovncModalFor(deploymentId) {
        const { url, info } = await resolveNovncUrl(deploymentId);
        if (novncStatusBanner) {
            novncStatusBanner.classList.remove('error');
            novncStatusBanner.innerHTML = `<i class="fas fa-check-circle"></i> Connexion à ${escapeHtml(url)}`;
        }
        if (novncCredentialsBox) {
            if (info?.credentials?.username || info?.credentials?.password) {
                novncCredentialsBox.classList.add('show');
                novncCredentialsBox.innerHTML = `
                    <strong>Identifiants par défaut</strong><br>
                    Utilisateur : <code>${escapeHtml(info.credentials.username || '')}</code><br>
                    Mot de passe : <code>${escapeHtml(info.credentials.password || '')}</code>
                `;
            } else {
                novncCredentialsBox.classList.remove('show');
                novncCredentialsBox.innerHTML = '';
            }
        }
        if (novncFrame) {
            novncFrame.src = url;
        }
    }

    function bindNovncButtons(scope = document) {
        const buttons = scope.querySelectorAll('.embed-novnc-btn');
        buttons.forEach(btn => {
            if (!btn || btn.dataset.novncBound === '1') return;
            btn.dataset.novncBound = '1';
            btn.addEventListener('click', async (event) => {
                event.preventDefault();
                if (btn.disabled || btn.classList.contains('disabled')) return;
                const deploymentId = btn.getAttribute('data-novnc-target');
                const namespace = btn.getAttribute('data-namespace');
                if (!deploymentId) return;
                if (namespace) {
                    registerNovncEndpoint(deploymentId, namespace, {});
                }
                prepareNovncModal(deploymentId);
                try {
                    await openNovncModalFor(deploymentId);
                } catch (error) {
                    console.error('Erreur NoVNC:', error);
                    if (novncStatusBanner) {
                        novncStatusBanner.classList.add('error');
                        novncStatusBanner.innerHTML = `<i class="fas fa-exclamation-triangle"></i> ${escapeHtml(error.message || 'Impossible d’ouvrir NoVNC')}`;
                    }
                }
            });
        });
    }

    function resetNovncModal() {
        if (novncFrame) {
            try { novncFrame.src = 'about:blank'; } catch (err) {}
        }
        if (novncStatusBanner) {
            novncStatusBanner.classList.remove('error');
            novncStatusBanner.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Préparation de la session NoVNC...';
        }
        if (novncCredentialsBox) {
            novncCredentialsBox.classList.remove('show');
            novncCredentialsBox.innerHTML = '';
        }
    }

    return {
        extractNovncInfoFromDetails,
        registerNovncEndpoint,
        buildNovncUrl,
        ensureNovncDetails,
        resolveNovncUrl,
        updateNovncButtonsAvailability,
        prepareNovncModal,
        openNovncModalFor,
        bindNovncButtons,
        resetNovncModal,
    };
}
