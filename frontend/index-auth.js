/* filepath: c:\Users\zhiri\Nextcloud\mo\Projects\LabOnDemand\frontend\index-auth.js */
// Point d'entrée avec gestion d'authentification pour l'application LabOnDemand
import authManager from './js/auth.js';

console.log("index-auth.js chargé");

// Fonction principale
async function main() {
    // Vérifier l'authentification
    const isAuthenticated = await authManager.init();
    
    if (!isAuthenticated) {
        // Si non authentifié, rediriger vers la page de login
        console.log("Utilisateur non authentifié, redirection vers la page de connexion");
        window.location.href = 'login.html';
        return;
    }
    
    console.log("Utilisateur authentifié:", authManager.getUserDisplayName());
    
    // Initialiser les éléments spécifiques à l'authentification
    initAuthUI();
    
    // Charger le script principal de l'application
    loadMainScript();
}

function initAuthUI() {
    // Mettre à jour les éléments de l'UI liés à l'authentification
    const userGreeting = document.getElementById('user-greeting');
    const logoutBtn = document.getElementById('logout-btn');
    
    if (userGreeting) {
        // Mettre à jour le message de bienvenue
        userGreeting.textContent = `Bonjour, ${authManager.getUserDisplayName()}`;
        
        // Ajouter une icône selon le rôle
        let roleIcon = '';
        switch (authManager.getUserRole()) {
            case 'admin':
                roleIcon = '<i class="fas fa-user-shield"></i>';
                break;
            case 'teacher':
                roleIcon = '<i class="fas fa-chalkboard-teacher"></i>';
                break;
            case 'student':
                roleIcon = '<i class="fas fa-user-graduate"></i>';
                break;
            default:
                roleIcon = '<i class="fas fa-user"></i>';
        }
        userGreeting.innerHTML += ` ${roleIcon}`;
    }
    
    if (logoutBtn) {
        // Configurer le bouton de déconnexion
        logoutBtn.addEventListener('click', async () => {
            await authManager.logout();
        });
    }
    
    // Ajuster l'interface selon le rôle
    const adminSections = document.querySelectorAll('.k8s-admin-only');
    if (authManager.isAdmin() || authManager.isTeacher()) {
        adminSections.forEach(section => {
            section.style.removeProperty('display');
        });
    } else {
        adminSections.forEach(section => {
            section.style.display = 'none';
        });
    }
}

function loadMainScript() {
    // Vérifier si le script est déjà chargé dans la page
    const scriptAlreadyExists = document.querySelector('script[src="script.js"]');
    if (scriptAlreadyExists) {
        console.log("Le script principal est déjà chargé");
        return;
    }
      // Charger dynamiquement le script principal
    const script = document.createElement('script');
    script.src = 'script.js';
    script.type = 'module';
    
    // Ajouter un gestionnaire d'événements pour surveiller le chargement du script
    script.onload = function() {
        console.log("Script principal chargé avec succès");
    };
    
    script.onerror = function() {
        console.error("Erreur lors du chargement du script principal");
    };
    
    document.head.appendChild(script);
}

// Démarrer l'application au chargement du document
document.addEventListener('DOMContentLoaded', main);
