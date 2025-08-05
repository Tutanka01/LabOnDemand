/* filepath: c:\Users\zhiri\Nextcloud\mo\Projects\LabOnDemand\frontend\js\login.js */
// Script de gestion de la page de connexion

document.addEventListener('DOMContentLoaded', () => {
    const loginForm = document.getElementById('login-form');
    const errorMessage = document.getElementById('error-message');
    const errorText = document.getElementById('error-text');
    
    // Vérifier si l'utilisateur est déjà connecté
    checkAuthStatus();
    
    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const username = document.getElementById('username').value;
        const password = document.getElementById('password').value;
        
        try {
            // Masquer les messages d'erreur précédents
            errorMessage.style.display = 'none';
            
            // Envoyer la demande de connexion
            const response = await fetch('/api/v1/auth/login', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ username, password }),
                credentials: 'include' // Important pour les cookies
            });
            
            if (!response.ok) {
                // Essayer de parser le JSON d'erreur
                let errorMessage = 'Erreur de connexion';
                try {
                    const error = await response.json();
                    errorMessage = error.message || error.detail || 'Erreur de connexion';
                } catch (parseError) {
                    // Si ce n'est pas du JSON, récupérer le texte brut
                    try {
                        const errorText = await response.text();
                        if (errorText.includes('Table') && errorText.includes('doesn\'t exist')) {
                            errorMessage = 'Base de données non initialisée. Contactez l\'administrateur.';
                        } else if (errorText.includes('Traceback')) {
                            errorMessage = 'Erreur serveur. Consultez les logs.';
                        } else {
                            errorMessage = 'Erreur de connexion';
                        }
                    } catch (textError) {
                        errorMessage = 'Erreur de connexion';
                    }
                }
                throw new Error(errorMessage);
            }
            
            const data = await response.json();
            
            // Stocker les informations utilisateur en session
            sessionStorage.setItem('user', JSON.stringify(data.user));
            
            // Rediriger vers la page d'accueil
            window.location.href = 'index.html';
        } catch (error) {
            // Afficher le message d'erreur
            errorText.textContent = error.message;
            errorMessage.style.display = 'block';
            console.error('Erreur de connexion:', error);
        }
    });
    
    // Vérifier si l'utilisateur est déjà connecté
    async function checkAuthStatus() {
        try {
            const response = await fetch('/api/v1/auth/me', {
                credentials: 'include' // Important pour envoyer les cookies
            });
            
            if (response.ok) {
                // L'utilisateur est déjà connecté, rediriger vers la page d'accueil
                window.location.href = 'index.html';
            }
        } catch (error) {
            // Ignorer les erreurs, l'utilisateur n'est simplement pas connecté
            console.log('Aucune session active');
        }
    }
});
