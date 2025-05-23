/* filepath: c:\Users\zhiri\Nextcloud\mo\Projects\LabOnDemand\frontend\js\redirect.js */
// Script de redirection automatique vers la page de connexion
// À utiliser sur une page "access-denied.html" ou similaire

document.addEventListener('DOMContentLoaded', () => {
    // Compte à rebours pour la redirection
    let countdown = 5; // 5 secondes
    const countdownElement = document.getElementById('countdown');
    
    // Mettre à jour le compte à rebours chaque seconde
    const interval = setInterval(() => {
        countdown--;
        if (countdownElement) {
            countdownElement.textContent = countdown;
        }
        
        // Rediriger une fois le compte à rebours terminé
        if (countdown <= 0) {
            clearInterval(interval);
            window.location.href = 'login.html';
        }
    }, 1000);
    
    // Permettre à l'utilisateur de rediriger immédiatement
    const loginNowButton = document.getElementById('login-now');
    if (loginNowButton) {
        loginNowButton.addEventListener('click', () => {
            clearInterval(interval);
            window.location.href = 'login.html';
        });
    }
});
