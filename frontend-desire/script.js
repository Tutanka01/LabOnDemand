document.addEventListener('DOMContentLoaded', () => {
    const views = document.querySelectorAll('.view');
    const showLaunchViewBtn = document.getElementById('show-launch-view-btn');
    const serviceCards = document.querySelectorAll('.service-card:not(.disabled)');
    const backBtns = document.querySelectorAll('.back-btn');
    const configForm = document.getElementById('config-form');
    const activeLabsList = document.getElementById('active-labs-list');
    const noLabsMessage = document.querySelector('.no-labs-message');
    const configServiceName = document.getElementById('config-service-name');
    const serviceTypeInput = document.getElementById('service-type');
    const serviceIconInput = document.getElementById('service-icon-class');
    const jupyterOptions = document.getElementById('jupyter-options');
    const statusContent = document.getElementById('status-content');
    const statusActions = document.querySelector('.status-actions');

    let labCounter = 0; // Simple counter for unique lab IDs

    // --- Navigation ---

    function showView(viewId) {
        views.forEach(view => {
            view.classList.remove('active-view');
        });
        const activeView = document.getElementById(viewId);
        if (activeView) {
            activeView.classList.add('active-view');
            window.scrollTo(0, 0); // Scroll to top when changing views
        } else {
            console.error("View not found:", viewId);
            // Show dashboard as fallback
             document.getElementById('dashboard-view').classList.add('active-view');
        }
    }

    if (showLaunchViewBtn) {
        showLaunchViewBtn.addEventListener('click', () => {
            showView('launch-view');
        });
    }

    backBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetViewId = btn.getAttribute('data-target');
            showView(targetViewId);
        });
    });

    // --- Service Selection ---

    serviceCards.forEach(card => {
        card.addEventListener('click', () => {
            const serviceName = card.getAttribute('data-service');
            const serviceIcon = card.getAttribute('data-icon');

            configServiceName.textContent = serviceName;
            serviceTypeInput.value = serviceName;
            serviceIconInput.value = serviceIcon;

            // Show/Hide specific options
            jupyterOptions.style.display = (serviceName === 'JupyterLab') ? 'block' : 'none';

            // Reset form (optional)
            configForm.reset();

            showView('config-view');
        });
    });

    // --- Form Submission (Launch Simulation) ---

    if (configForm) {
        configForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const serviceName = serviceTypeInput.value;
            const serviceIcon = serviceIconInput.value;
            const duration = document.getElementById('duration').value;
            const cpu = document.getElementById('cpu').value;
            const ram = document.getElementById('ram').value;

            // Get selected datasets (if Jupyter)
            let datasets = [];
            if (serviceName === 'JupyterLab') {
                document.querySelectorAll('#jupyter-options input[type="checkbox"]:checked').forEach(cb => {
                    datasets.push(cb.value);
                });
            }

            // Show loading status
            showView('status-view');
            statusContent.innerHTML = `
                <i class="fas fa-spinner fa-spin status-icon loading"></i>
                <h2>Lancement de ${serviceName} en cours...</h2>
                <p>Votre environnement est en cours de préparation. Veuillez patienter.</p>
            `;
            statusActions.style.display = 'none'; // Hide 'Terminé' button initially


            // Simulate delay for deployment
            setTimeout(() => {
                labCounter++;
                const labId = `lab-${Date.now()}-${labCounter}`; // Unique ID
                const accessLink = `https://${serviceName.toLowerCase().replace(/\s+/g, '-')}-${labId}.labondemand.local`; // Fake link

                 // Add lab to the dashboard list
                addLabCard({
                    id: labId,
                    name: serviceName,
                    icon: serviceIcon,
                    duration: duration,
                    cpu: cpu,
                    ram: ram,
                    datasets: datasets,
                    link: accessLink,
                    startTime: Date.now()
                });


                // Update status view to success
                statusContent.innerHTML = `
                    <i class="fas fa-check-circle status-icon success"></i>
                    <h2>${serviceName} Lancé !</h2>
                    <p>Votre environnement est prêt. Vous pouvez y accéder via le lien ci-dessous ou depuis votre tableau de bord.</p>
                    <a href="${accessLink}" target="_blank" class="access-link">
                        <i class="fas fa-link"></i> ${accessLink}
                    </a>
                    <p style="margin-top: 15px; font-size: 0.9em; color: #666;">Cet environnement s'arrêtera automatiquement dans ${duration} heure(s).</p>
                `;
                statusActions.style.display = 'block'; // Show 'Terminé' button

            }, 2500); // Simulate 2.5 seconds delay
        });
    }

    // --- Manage Active Labs ---

    function addLabCard(labDetails) {
         if (noLabsMessage) {
             noLabsMessage.style.display = 'none'; // Hide "no labs" message
         }

        const card = document.createElement('div');
        card.classList.add('card', 'lab-card');
        card.id = labDetails.id;
        card.dataset.startTime = labDetails.startTime;
        card.dataset.durationHours = labDetails.duration;

        let datasetsHtml = '';
        if (labDetails.datasets && labDetails.datasets.length > 0) {
            datasetsHtml = `<li><i class="fas fa-database"></i> Datasets: ${labDetails.datasets.join(', ')}</li>`;
        }

        card.innerHTML = `
            <h3><i class="${labDetails.icon}"></i> ${labDetails.name} #${labCounter}</h3>
            <ul class="lab-details">
                <li><i class="fas fa-microchip"></i> ${labDetails.cpu} vCPU</li>
                <li><i class="fas fa-memory"></i> ${labDetails.ram} Go RAM</li>
                <li><i class="fas fa-clock"></i> Durée: ${labDetails.duration}h | <span class="time-remaining">Calcul...</span></li>
                ${datasetsHtml}
            </ul>
            <div class="lab-actions">
                <a href="${labDetails.link}" target="_blank" class="btn btn-primary"><i class="fas fa-external-link-alt"></i> Accéder</a>
                <button class="btn btn-danger stop-lab-btn"><i class="fas fa-stop-circle"></i> Arrêter</button>
            </div>
        `;

        activeLabsList.appendChild(card);

        // Add event listener for the new stop button
        card.querySelector('.stop-lab-btn').addEventListener('click', () => {
            stopLab(labDetails.id);
        });

        updateTimers(); // Update timers immediately
    }

    function stopLab(labId) {
         // Optional: Add a confirmation dialog here
        if (confirm("Êtes-vous sûr de vouloir arrêter ce laboratoire ?")) {
            const labCard = document.getElementById(labId);
            if (labCard) {
                labCard.remove();
                console.log(`Lab ${labId} stopped.`);

                // Show "no labs" message if list is empty
                 if (activeLabsList.children.length === 0 || (activeLabsList.children.length === 1 && activeLabsList.children[0].classList.contains('no-labs-message'))) {
                    if (noLabsMessage) noLabsMessage.style.display = 'block';
                 }
            }
        }
    }

    // --- Timer Update Function ---
    function updateTimers() {
        const labCards = document.querySelectorAll('.lab-card[data-start-time]');
        labCards.forEach(card => {
            const startTime = parseInt(card.dataset.startTime, 10);
            const durationHours = parseInt(card.dataset.durationHours, 10);
            const endTime = startTime + durationHours * 60 * 60 * 1000;
            const now = Date.now();
            const remainingMs = Math.max(0, endTime - now);

            const remainingHours = Math.floor(remainingMs / (1000 * 60 * 60));
            const remainingMinutes = Math.floor((remainingMs % (1000 * 60 * 60)) / (1000 * 60));
            const remainingSeconds = Math.floor((remainingMs % (1000 * 60)) / 1000);

            const timerSpan = card.querySelector('.time-remaining');
            if (timerSpan) {
                if (remainingMs === 0) {
                     timerSpan.textContent = "Terminé";
                     timerSpan.style.color = "var(--error-color)";
                     // Optionally, disable buttons or auto-remove card after a delay
                     // stopLab(card.id); // Auto-stop when timer reaches zero
                } else {
                    timerSpan.textContent = `Temps restant: ${String(remainingHours).padStart(2, '0')}:${String(remainingMinutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`;
                    timerSpan.style.color = remainingHours < 1 ? "var(--warning-color)" : "inherit"; // Change color if less than 1h left
                }
            }
        });
    }

     // Initial setup
     if (activeLabsList.children.length === 1 && activeLabsList.children[0].classList.contains('no-labs-message')) {
        // Correctly handle initial state if the no-labs message is the only child
     } else if (activeLabsList.children.length === 0) {
         if (noLabsMessage) noLabsMessage.style.display = 'block';
     } else {
         if (noLabsMessage) noLabsMessage.style.display = 'none';
     }

    // Update timers every second
    setInterval(updateTimers, 1000);

    // Initialize view
    showView('dashboard-view'); // Start on the dashboard

});