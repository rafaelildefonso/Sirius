// Script para resetar o onboarding (colar no console do navegador)
localStorage.removeItem('openjarvis-assistant-profile');
localStorage.removeItem('openjarvis-conversations');
localStorage.removeItem('openjarvis-settings');
console.log('✅ Onboarding resetado! Recarregue a página para ver o wizard novamente.');
