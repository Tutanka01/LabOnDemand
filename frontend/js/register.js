// Script de gestion de la page d'inscription

document.addEventListener('DOMContentLoaded', () => {
    const registerForm = document.getElementById('register-form');
    const errorMessage = document.getElementById('error-message');
    const errorText = document.getElementById('error-text');
    const successMessage = document.getElementById('success-message');
    const successText = document.getElementById('success-text');
    const ssoRegister = document.getElementById('sso-register');
    const ssoRegisterBtn = document.getElementById('sso-register-btn');
    const registerInfo = document.getElementById('register-info');
    
    // Vérifier si l'utilisateur est déjà connecté
    checkAuthStatus();
    initAuthMode();
    
    if (registerForm) {
        registerForm.addEventListener('submit', async (e) => {
            e.preventDefault();
        
        const username = document.getElementById('username').value;
        const email = document.getElementById('email').value;
        const fullName = document.getElementById('full_name').value;
        const password = document.getElementById('password').value;
        const confirmPassword = document.getElementById('confirm_password').value;
        
        // Masquer les messages précédents
        errorMessage.style.display = 'none';
        successMessage.style.display = 'none';
        
        // Vérifier que les mots de passe correspondent
        if (password !== confirmPassword) {
            errorText.textContent = "Les mots de passe ne correspondent pas";
            errorMessage.style.display = 'block';
            return;
        }
        
        try {
            // Envoyer la demande d'inscription
            const response = await fetch('/api/v1/auth/register', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    username,
                    email,
                    full_name: fullName,
                    password,
                    role: "student" // Par défaut, tous les nouveaux utilisateurs sont des étudiants
                })
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Erreur lors de l\'inscription');
            }
            
            // Inscription réussie
            successText.textContent = "Inscription réussie ! Vous allez être redirigé vers la page de connexion...";
            successMessage.style.display = 'block';
            
            // Réinitialiser le formulaire
            registerForm.reset();
            
            // Rediriger vers la page de connexion après 2 secondes
            setTimeout(() => {
                window.location.href = 'login.html';
            }, 2000);
            
        } catch (error) {
            // Afficher le message d'erreur
            errorText.textContent = error.message;
            errorMessage.style.display = 'block';
            console.error('Erreur d\'inscription:', error);
        }
        });
    }

    if (ssoRegisterBtn) {
        ssoRegisterBtn.addEventListener('click', () => {
            window.location.href = '/api/v1/auth/sso/login';
        });
    }

    async function initAuthMode() {
        try {
            const response = await fetch('/api/v1/auth/sso/status');
            if (!response.ok) {
                return;
            }
            const data = await response.json();
            if (data.sso_enabled) {
                if (registerForm) {
                    registerForm.style.display = 'none';
                }
                if (ssoRegister) {
                    ssoRegister.style.display = 'flex';
                }
                if (registerInfo) {
                    registerInfo.innerHTML = '<i class="fas fa-user-plus"></i> Inscription désactivée (SSO activé)';
                }
                if (ssoRegisterBtn) {
                    ssoRegisterBtn.focus();
                }
            } else {
                if (registerForm) {
                    registerForm.style.display = 'flex';
                }
                if (ssoRegister) {
                    ssoRegister.style.display = 'none';
                }
            }
        } catch (error) {
            console.error('Erreur lors du chargement du mode SSO:', error);
        }
    }
});

// Fonction pour vérifier si l'utilisateur est déjà connecté
async function checkAuthStatus() {
    try {
        const response = await fetch('/api/v1/auth/me', {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'include'
        });
        
        // Si la requête réussit, l'utilisateur est connecté
        if (response.ok) {
            // Rediriger vers la page d'accueil
            window.location.href = 'index.html';
        }
    } catch (error) {
        console.log('Non authentifié');
    }
}
