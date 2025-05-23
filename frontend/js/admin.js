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
    const addUserBtn = document.getElementById('add-user-btn');
    const userModal = document.getElementById('user-modal');
    const deleteModal = document.getElementById('delete-modal');
    const modalTitle = document.getElementById('modal-title');
    const userForm = document.getElementById('user-form');
    const errorMessage = document.getElementById('error-message');
    const errorText = document.getElementById('error-text');
    const successMessage = document.getElementById('success-message');
    const successText = document.getElementById('success-text');
    const passwordHint = document.getElementById('password-hint');
    const closeButtons = document.querySelectorAll('.close-btn');
    const closeModalButtons = document.querySelectorAll('.close-modal');
    const confirmDeleteBtn = document.getElementById('confirm-delete');

    // Vérification des droits d'administration
    checkAdminRights();

    // Initialiser l'affichage
    loadUsers();

    // Écouteurs d'événements
    prevPageBtn.addEventListener('click', () => {
        if (currentPage > 1) {
            currentPage--;
            displayUsers();
        }
    });

    nextPageBtn.addEventListener('click', () => {
        if (currentPage < totalPages) {
            currentPage++;
            displayUsers();
        }
    });

    searchInput.addEventListener('input', () => {
        currentPage = 1;
        filterUsers();
    });

    roleFilter.addEventListener('change', () => {
        currentPage = 1;
        filterUsers();
    });

    addUserBtn.addEventListener('click', () => {
        openAddUserModal();
    });

    userForm.addEventListener('submit', (e) => {
        e.preventDefault();
        if (selectedUserId) {
            updateUser();
        } else {
            createUser();
        }
    });

    confirmDeleteBtn.addEventListener('click', () => {
        deleteUser(selectedUserId);
    });

    closeButtons.forEach(button => {
        button.addEventListener('click', function() {
            this.parentElement.style.display = 'none';
        });
    });

    closeModalButtons.forEach(button => {
        button.addEventListener('click', () => {
            userModal.classList.remove('show');
            deleteModal.classList.remove('show');
        });
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
            roleElement.innerHTML = `<span class="role-badge ${data.role}">${formatRole(data.role)}</span>`;
            
            // Mettre à jour l'affichage du nom d'utilisateur
            const userInfo = JSON.parse(sessionStorage.getItem('user') || '{}');
            if (userInfo.username) {
                document.getElementById('current-username').textContent = userInfo.username;
            }
            
            // Vérifier si l'utilisateur est un administrateur
            if (!data.can_manage_users) {
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

        filteredUsers = users.filter(user => {
            const matchesSearch = 
                user.username.toLowerCase().includes(searchTerm) ||
                user.email.toLowerCase().includes(searchTerm) ||
                (user.full_name && user.full_name.toLowerCase().includes(searchTerm));
            
            const matchesRole = roleValue === 'all' || user.role === roleValue;
            
            return matchesSearch && matchesRole;
        });

        displayUsers();
    }

    // Afficher les utilisateurs paginés
    function displayUsers() {
        // Vider le tableau
        userTableBody.innerHTML = '';
        
        // Calculer la pagination
        totalPages = Math.ceil(filteredUsers.length / pageSize);
        const startIndex = (currentPage - 1) * pageSize;
        const endIndex = Math.min(startIndex + pageSize, filteredUsers.length);
        const currentUsers = filteredUsers.slice(startIndex, endIndex);
        
        // Mettre à jour l'information de pagination
        pageInfo.textContent = `Page ${currentPage} sur ${totalPages || 1}`;
        prevPageBtn.disabled = currentPage <= 1;
        nextPageBtn.disabled = currentPage >= totalPages;
        
        // Aucun utilisateur trouvé
        if (currentUsers.length === 0) {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td colspan="8" style="text-align: center; padding: 20px;">
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

    // Ouvrir le modal d'ajout d'utilisateur
    function openAddUserModal() {
        selectedUserId = null;
        modalTitle.innerHTML = '<i class="fas fa-user-plus"></i> Ajouter un utilisateur';
        userForm.reset();
        document.getElementById('password-hint').textContent = 'Minimum 8 caractères';
        document.getElementById('modal-password').setAttribute('required', true);
        userModal.classList.add('show');
    }

    // Ouvrir le modal de modification d'utilisateur
    function openEditUserModal(userId) {
        selectedUserId = userId;
        const user = users.find(u => u.id == userId);
        
        modalTitle.innerHTML = '<i class="fas fa-user-edit"></i> Modifier l\'utilisateur';
        document.getElementById('user-id').value = user.id;
        document.getElementById('modal-username').value = user.username;
        document.getElementById('modal-email').value = user.email;
        document.getElementById('modal-full-name').value = user.full_name || '';
        document.getElementById('modal-password').value = '';
        document.getElementById('modal-password').removeAttribute('required');
        document.getElementById('password-hint').textContent = 'Minimum 8 caractères. Laissez vide pour ne pas modifier le mot de passe.';
        document.getElementById('modal-role').value = user.role;
        document.getElementById('modal-is-active').checked = user.is_active;
        
        userModal.classList.add('show');
    }

    // Ouvrir le modal de suppression
    function openDeleteModal(userId) {
        selectedUserId = userId;
        const user = users.find(u => u.id == userId);
        document.getElementById('delete-user-name').textContent = user.username;
        deleteModal.classList.add('show');
    }

    // Créer un utilisateur
    async function createUser() {
        try {
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
                throw new Error(error.detail || 'Erreur lors de la création de l\'utilisateur');
            }
            
            const newUser = await response.json();
            users.push(newUser);
            userModal.classList.remove('show');
            showSuccess('Utilisateur créé avec succès');
            filterUsers();
        } catch (error) {
            showError(error.message);
        }
    }

    // Mettre à jour un utilisateur
    async function updateUser() {
        try {
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
            
            if (password) {
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
                throw new Error(error.detail || 'Erreur lors de la mise à jour de l\'utilisateur');
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
            showError(error.message);
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
    document.getElementById('logout-btn').addEventListener('click', async () => {
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
