/**
 * @file auth.js
 * @description Authentication manager for LabOnDemand.
 *
 * Loaded as a module by index.html (and admin.html via index-auth.js).
 * On init(), verifies the session cookie against /api/v1/auth/me and
 * redirects to login.html if unauthenticated.
 *
 * Usage:
 *   import { authManager } from './auth.js';
 *   await authManager.init();
 *   const user = authManager.user;   // { id, username, role, ... }
 */

/**
 * Manages session state for the current browser tab.
 * Exposes `user` (the authenticated user object) and `isAuthenticated`.
 */
class AuthManager {
    constructor() {
        this.user = null;
        this.isAuthenticated = false;
    }

    async init() {
        // Vérifier si l'utilisateur est connecté
        await this.checkAuthStatus();
        
        // Rediriger vers la page de connexion si non connecté
        if (!this.isAuthenticated && !window.location.href.includes('login.html')) {
            window.location.href = 'login.html';
            return false;
        }
        
        return this.isAuthenticated;
    }
    
    async checkAuthStatus() {
        try {
            const response = await fetch('/api/v1/auth/me', {
                credentials: 'include'
            });
            
            if (response.ok) {
                const userData = await response.json();
                this.user = userData;
                this.isAuthenticated = true;
                
                // Mettre à jour le stockage de session
                sessionStorage.setItem('user', JSON.stringify(userData));
                
                return true;
            } else {
                this.user = null;
                this.isAuthenticated = false;
                return false;
            }
        } catch (error) {
            console.error('Erreur lors de la vérification de l\'authentification:', error);
            this.user = null;
            this.isAuthenticated = false;
            return false;
        }
    }
    
    async logout() {
        try {
            const response = await fetch('/api/v1/auth/logout', {
                method: 'POST',
                credentials: 'include'
            });
            
            if (response.ok) {
                // Nettoyer les données de session
                sessionStorage.removeItem('user');
                this.user = null;
                this.isAuthenticated = false;
                
                // Rediriger vers la page de connexion
                window.location.href = 'login.html';
                return true;
            } else {
                console.error('Erreur lors de la déconnexion');
                return false;
            }
        } catch (error) {
            console.error('Erreur lors de la déconnexion:', error);
            return false;
        }
    }
    
    getUserDisplayName() {
        if (!this.user) return 'Invité';
        return this.user.full_name || this.user.username;
    }
    
    getUserRole() {
        if (!this.user) return null;
        return this.user.role;
    }
    
    isAdmin() {
        return this.user && this.user.role === 'admin';
    }
    
    isTeacher() {
        return this.user && this.user.role === 'teacher';
    }
    
    isStudent() {
        return this.user && this.user.role === 'student';
    }
    
    canCreateLab() {
        return this.isAuthenticated;
    }
    
    canManageUsers() {
        return this.isAdmin();
    }
}

// Instancier le gestionnaire d'authentification
const authManager = new AuthManager();

// Exporter le gestionnaire
export default authManager;
