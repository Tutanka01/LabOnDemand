// Script pour la gestion de l'administration des utilisateurs

document.addEventListener('DOMContentLoaded', () => {
    // Variables globales
    let currentPage = 1;
    let totalPages = 1;
    let pageSize = 10;
    let users = [];
    let filteredUsers = [];
    let selectedUserId = null;

    // Éléments du DOM
    const userTableBody = document.getElementById('users-table-body');
    const prevPageBtn = document.getElementById('prev-page');
    const nextPageBtn = document.getElementById('next-page');
    const pageInfo = document.getElementById('page-info');
    const searchInput = document.getElementById('search-input');
    const roleFilter = document.getElementById('role-filter');
    const providerFilter = document.getElementById('provider-filter');
    const addUserBtn = document.getElementById('add-user-btn');
    const userModal = document.getElementById('user-modal');
    const deleteModal = document.getElementById('delete-modal');
    const modalTitle = document.getElementById('modal-title');
    const userForm = document.getElementById('user-form');
    const errorMessage = document.getElementById('error-message');
    const errorText = document.getElementById('error-text');
    const successMessage = document.getElementById('success-message');
    const successText = document.getElementById('success-text');
    const closeButtons = document.querySelectorAll('.close-btn');
    const closeModalButtons = document.querySelectorAll('.close-modal');
    const confirmDeleteBtn = document.getElementById('confirm-delete');
    const ssoNotice = document.getElementById('sso-admin-notice');

    let ssoEnabled = false;

    const onUsersPage = !!userTableBody; // page administration utilisateurs

    // Vérification des droits d'administration
    checkAdminRights();
    loadSsoStatus();

    // Initialiser l'affichage
    if (onUsersPage) {
        loadUsers();
    }

    // Écouteurs d'événements
    if (prevPageBtn) {
        prevPageBtn.addEventListener('click', () => {
            if (currentPage > 1) {
                currentPage--;
                displayUsers();
            }
        });
    }

    if (nextPageBtn) {
        nextPageBtn.addEventListener('click', () => {
            if (currentPage < totalPages) {
                currentPage++;
                displayUsers();
            }
        });
    }

    if (searchInput) {
        searchInput.addEventListener('input', () => {
            currentPage = 1;
            filterUsers();
        });
    }

    if (roleFilter) {
        roleFilter.addEventListener('change', () => {
            currentPage = 1;
            filterUsers();
        });
    }

    if (providerFilter) {
        providerFilter.addEventListener('change', () => {
            currentPage = 1;
            filterUsers();
        });
    }

    if (addUserBtn) {
        addUserBtn.addEventListener('click', () => {
            openAddUserModal();
        });
    }

    if (userForm) {
        userForm.addEventListener('submit', (e) => {
            e.preventDefault();
            if (selectedUserId) {
                updateUser();
            } else {
                createUser();
            }
        });
    }

    if (confirmDeleteBtn) {
        confirmDeleteBtn.addEventListener('click', () => {
            deleteUser(selectedUserId);
        });
    }

    closeButtons.forEach(button => {
        button.addEventListener('click', function () {
            const parent = this.closest('.notification');
            if (parent) {
                parent.style.display = 'none';
                return;
            }
            this.parentElement.style.display = 'none';
        });
    });

    if (closeModalButtons && closeModalButtons.length) {
        closeModalButtons.forEach(button => {
            button.addEventListener('click', () => {
                if (userModal) userModal.classList.remove('show');
                if (deleteModal) deleteModal.classList.remove('show');
            });
        });
    }

    // Fermer les modales en cliquant à l'extérieur
    if (userModal) {
        userModal.addEventListener('click', (e) => {
            if (e.target === userModal) {
                userModal.classList.remove('show');
            }
        });
    }

    if (deleteModal) {
        deleteModal.addEventListener('click', (e) => {
            if (e.target === deleteModal) {
                deleteModal.classList.remove('show');
            }
        });
    }

    // Fermer les modales avec la touche Échap
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (userModal && userModal.classList.contains('show')) {
                userModal.classList.remove('show');
            }
            if (deleteModal && deleteModal.classList.contains('show')) {
                deleteModal.classList.remove('show');
            }
        }
    });

    // Fonctions

    // Vérifier si l'utilisateur a les droits d'administration
    async function checkAdminRights() {
        try {
            const response = await fetch('/api/v1/auth/check-role', {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include'
            });

            if (!response.ok) {
                throw new Error('Erreur lors de la vérification des droits');
            }

            const data = await response.json();

            // Mettre à jour l'affichage du rôle
            const roleElement = document.getElementById('user-role');
            if (roleElement) {
                roleElement.innerHTML = `<span class="role-badge ${data.role}">${formatRole(data.role)}</span>`;
            }

            // Mettre à jour l'affichage du nom d'utilisateur
            const userInfo = JSON.parse(sessionStorage.getItem('user') || '{}');
            if (userInfo.username) {
                document.getElementById('current-username').textContent = userInfo.username;
            }

            // Vérifier si l'utilisateur est un administrateur
            if (!data.can_manage_users && onUsersPage) {
                window.location.href = 'access-denied.html';
            }
        } catch (error) {
            console.error(error);
            window.location.href = 'login.html';
        }
    }

    // Formater le rôle pour l'affichage
    function formatRole(role) {
        const roles = {
            'student': 'Étudiant',
            'teacher': 'Enseignant',
            'admin': 'Administrateur'
        };
        return roles[role] || role;
    }

    // Charger la liste des utilisateurs
    async function loadUsers() {
        try {
            const response = await fetch('/api/v1/auth/users', {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include'
            });

            if (!response.ok) {
                throw new Error('Erreur lors du chargement des utilisateurs');
            }

            users = await response.json();
            filteredUsers = [...users];
            displayUsers();
        } catch (error) {
            showError(error.message);
        }
    }

    // Filtrer les utilisateurs selon les critères
    function filterUsers() {
        const searchTerm = searchInput.value.toLowerCase();
        const roleValue = roleFilter.value;
        const providerValue = providerFilter ? providerFilter.value : 'all';

        filteredUsers = users.filter(user => {
            const matchesSearch =
                user.username.toLowerCase().includes(searchTerm) ||
                user.email.toLowerCase().includes(searchTerm) ||
                (user.full_name && user.full_name.toLowerCase().includes(searchTerm));

            const matchesRole = roleValue === 'all' || user.role === roleValue;

            const userProvider = user.auth_provider === 'oidc' ? 'oidc' : 'local';
            const matchesProvider = providerValue === 'all' || userProvider === providerValue;

            return matchesSearch && matchesRole && matchesProvider;
        });

        displayUsers();
    }

    // Afficher les utilisateurs paginés
    function displayUsers() {
        // Vider le tableau (seulement si présent)
        if (!userTableBody) return;
        userTableBody.innerHTML = '';

        // Calculer la pagination
        totalPages = Math.ceil(filteredUsers.length / pageSize);
        const startIndex = (currentPage - 1) * pageSize;
        const endIndex = Math.min(startIndex + pageSize, filteredUsers.length);
        const currentUsers = filteredUsers.slice(startIndex, endIndex);

        // Mettre à jour l'information de pagination
        if (pageInfo) pageInfo.textContent = `Page ${currentPage} sur ${totalPages || 1}`;
        if (prevPageBtn) prevPageBtn.disabled = currentPage <= 1;
        if (nextPageBtn) nextPageBtn.disabled = currentPage >= totalPages;

        // Aucun utilisateur trouvé
        if (currentUsers.length === 0) {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td colspan="9" style="text-align: center; padding: 20px;">
                    Aucun utilisateur trouvé
                </td>
            `;
            userTableBody.appendChild(row);
            return;
        }

        // Générer les lignes du tableau
        currentUsers.forEach(user => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${user.id}</td>
                <td>${user.username}</td>
                <td>${user.email}</td>
                <td>${user.full_name || '-'}</td>
                <td>
                    <span class="provider-badge ${user.auth_provider === 'oidc' ? 'sso' : 'local'}">
                        ${user.auth_provider === 'oidc' ? '<i class="fas fa-shield-alt"></i> SSO' : '<i class="fas fa-user"></i> Local'}
                    </span>
                </td>
                <td>
                    <span class="role-badge ${user.role}">
                        ${formatRole(user.role)}
                    </span>
                </td>
                <td>
                    <span class="status-badge ${user.is_active ? 'active' : 'inactive'}">
                        ${user.is_active ? 'Actif' : 'Inactif'}
                    </span>
                </td>
                <td>${formatDate(user.created_at)}</td>
                <td class="action-icons">
                    <button class="edit-btn" data-id="${user.id}" title="Modifier">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="delete-btn" data-id="${user.id}" title="Supprimer">
                        <i class="fas fa-trash-alt"></i>
                    </button>
                </td>
            `;
            userTableBody.appendChild(row);
        });

        // Ajouter les écouteurs d'événements aux boutons
        addActionButtonListeners();
    }

    // Formater une date
    function formatDate(dateString) {
        const date = new Date(dateString);
        return date.toLocaleDateString('fr-FR', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    // Ajouter des écouteurs d'événements aux boutons d'action
    function addActionButtonListeners() {
        document.querySelectorAll('.edit-btn').forEach(button => {
            button.addEventListener('click', () => {
                const userId = button.dataset.id;
                openEditUserModal(userId);
            });
        });

        document.querySelectorAll('.delete-btn').forEach(button => {
            button.addEventListener('click', () => {
                const userId = button.dataset.id;
                openDeleteModal(userId);
            });
        });
    }

    const modalErrorMessage = document.getElementById('modal-error-message');
    const modalErrorText = document.getElementById('modal-error-text');

    // ... (existing code)

    // Ouvrir le modal d'ajout d'utilisateur
    function openAddUserModal() {
        if (ssoEnabled) {
            showError('Création d\'utilisateurs locaux désactivée (SSO activé).');
            return;
        }
        selectedUserId = null;
        modalTitle.innerHTML = '<i class="fas fa-user-plus"></i> Ajouter un utilisateur';
        userForm.reset();
        if (modalErrorMessage) modalErrorMessage.style.display = 'none'; // Clear error
        document.getElementById('password-hint').textContent = 'Minimum 8 caractères';
        document.getElementById('modal-password').setAttribute('required', true);
        userModal.classList.add('show');
    }

    // Ouvrir le modal de modification d'utilisateur
    function openEditUserModal(userId) {
        selectedUserId = userId;
        const user = users.find(u => u.id == userId);

        if (!user) {
            showError('Utilisateur introuvable');
            return;
        }

        modalTitle.innerHTML = '<i class="fas fa-user-edit"></i> Modifier l\'utilisateur';
        if (modalErrorMessage) modalErrorMessage.style.display = 'none';

        document.getElementById('user-id').value = user.id;
        document.getElementById('modal-username').value = user.username;
        document.getElementById('modal-email').value = user.email;
        document.getElementById('modal-full-name').value = user.full_name || '';
        document.getElementById('modal-role').value = user.role;
        document.getElementById('modal-is-active').checked = !!user.is_active;

        const passwordInput = document.getElementById('modal-password');
        const passwordHintElement = document.getElementById('password-hint');
        const passwordGroup = passwordInput ? passwordInput.closest('.form-group') : null;
        const modalSsoNotice = document.getElementById('modal-sso-notice');
        const usernameInput = document.getElementById('modal-username');
        const isOidcUser = user.auth_provider === 'oidc';

        passwordInput.value = '';
        passwordInput.removeAttribute('required');

        if (isOidcUser) {
            // Compte SSO : désactiver le champ password, afficher la notice
            if (passwordGroup) passwordGroup.classList.add('hidden');
            if (modalSsoNotice) modalSsoNotice.classList.remove('hidden');
            if (usernameInput) usernameInput.setAttribute('readonly', true);
            modalTitle.innerHTML = '<i class="fas fa-shield-alt"></i> Modifier le rôle (compte SSO)';
        } else {
            // Compte local : comportement normal
            if (passwordGroup) passwordGroup.classList.remove('hidden');
            if (modalSsoNotice) modalSsoNotice.classList.add('hidden');
            if (usernameInput) usernameInput.removeAttribute('readonly');
            if (passwordHintElement) {
                passwordHintElement.textContent = 'Laissez vide pour conserver le mot de passe existant';
            }
        }

        userModal.classList.add('show');
    }

    function openDeleteModal(userId) {
        selectedUserId = userId;
        const user = users.find(u => u.id == userId);
        if (!user) {
            showError('Utilisateur introuvable');
            return;
        }

        const deleteUserName = document.getElementById('delete-user-name');
        if (deleteUserName) {
            deleteUserName.textContent = user.username;
        }

        deleteModal.classList.add('show');
    }

    // Afficher un message d'erreur dans le modal
    function showModalError(message) {
        if (modalErrorText && modalErrorMessage) {
            modalErrorText.textContent = message;
            modalErrorMessage.style.display = 'flex';
        } else {
            // Fallback if elements not found
            showError(message);
        }
    }

    // Créer un utilisateur
    async function createUser() {
        try {
            if (ssoEnabled) {
                showModalError('Création d\'utilisateurs locaux désactivée (SSO activé).');
                return;
            }
            if (modalErrorMessage) modalErrorMessage.style.display = 'none';

            const username = document.getElementById('modal-username').value;
            const email = document.getElementById('modal-email').value;
            const fullName = document.getElementById('modal-full-name').value;
            const password = document.getElementById('modal-password').value;
            const role = document.getElementById('modal-role').value;
            const isActive = document.getElementById('modal-is-active').checked;

            const response = await fetch('/api/v1/auth/register', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify({
                    username,
                    email,
                    full_name: fullName,
                    password,
                    role,
                    is_active: isActive
                })
            });

            if (!response.ok) {
                const error = await response.json();
                const detail = Array.isArray(error.detail)
                    ? error.detail.map(e => e.msg).join(', ')
                    : (error.detail || 'Erreur lors de la création de l\'utilisateur');
                throw new Error(detail);
            }

            const newUser = await response.json();
            users.push(newUser);
            userModal.classList.remove('show');
            showSuccess('Utilisateur créé avec succès');
            filterUsers();
        } catch (error) {
            showModalError(error.message);
        }
    }

    async function loadSsoStatus() {
        try {
            const response = await fetch('/api/v1/auth/sso/status');
            if (!response.ok) return;
            const data = await response.json();
            ssoEnabled = !!data.sso_enabled;
            if (ssoEnabled) {
                if (addUserBtn) {
                    addUserBtn.disabled = true;
                    addUserBtn.title = 'SSO activé: création d\'utilisateurs locaux désactivée';
                }
                if (ssoNotice) {
                    ssoNotice.style.display = 'flex';
                }
            } else if (ssoNotice) {
                ssoNotice.style.display = 'none';
            }
        } catch (error) {
            console.error('Erreur lors du chargement du statut SSO:', error);
        }
    }

    // Mettre à jour un utilisateur
    async function updateUser() {
        try {
            if (modalErrorMessage) modalErrorMessage.style.display = 'none';

            const userId = selectedUserId;
            const email = document.getElementById('modal-email').value;
            const fullName = document.getElementById('modal-full-name').value || null;
            const password = document.getElementById('modal-password').value || null;
            const role = document.getElementById('modal-role').value;
            const isActive = document.getElementById('modal-is-active').checked;

            const userData = {
                email,
                full_name: fullName,
                role,
                is_active: isActive
            };

            const editedUser = users.find(u => u.id == userId);
            if (password) {
                if (editedUser && editedUser.auth_provider === 'oidc') {
                    showModalError('Impossible de définir un mot de passe sur un compte SSO.');
                    return;
                }
                userData.password = password;
            }

            const response = await fetch(`/api/v1/auth/users/${userId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify(userData)
            });

            if (!response.ok) {
                const error = await response.json();
                const detail = Array.isArray(error.detail)
                    ? error.detail.map(e => e.msg).join(', ')
                    : (error.detail || 'Erreur lors de la mise à jour de l\'utilisateur');
                throw new Error(detail);
            }

            const updatedUser = await response.json();

            // Mettre à jour l'utilisateur dans le tableau
            const index = users.findIndex(u => u.id == userId);
            if (index !== -1) {
                users[index] = updatedUser;
            }

            userModal.classList.remove('show');
            showSuccess('Utilisateur mis à jour avec succès');
            filterUsers();
        } catch (error) {
            showModalError(error.message);
        }
    }

    // Supprimer un utilisateur
    async function deleteUser(userId) {
        try {
            const response = await fetch(`/api/v1/auth/users/${userId}`, {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include'
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Erreur lors de la suppression de l\'utilisateur');
            }

            // Supprimer l'utilisateur du tableau
            users = users.filter(u => u.id != userId);

            deleteModal.classList.remove('show');
            showSuccess('Utilisateur supprimé avec succès');
            filterUsers();
        } catch (error) {
            deleteModal.classList.remove('show');
            showError(error.message);
        }
    }

    // Afficher un message d'erreur
    function showError(message) {
        errorText.textContent = message;
        errorMessage.style.display = 'flex';

        // Cache automatiquement le message après 5 secondes
        setTimeout(() => {
            errorMessage.style.display = 'none';
        }, 5000);
    }

    // Afficher un message de succès
    function showSuccess(message) {
        successText.textContent = message;
        successMessage.style.display = 'flex';

        // Cache automatiquement le message après 5 secondes
        setTimeout(() => {
            successMessage.style.display = 'none';
        }, 5000);
    }

    // Déconnexion
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) logoutBtn.addEventListener('click', async () => {
        try {
            const response = await fetch('/api/v1/auth/logout', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include'
            });

            if (!response.ok) {
                throw new Error('Erreur lors de la déconnexion');
            }

            // Supprimer les informations de session et rediriger vers la page de connexion
            sessionStorage.removeItem('user');
            window.location.href = 'login.html';
        } catch (error) {
            showError(error.message);
        }
    });
});
