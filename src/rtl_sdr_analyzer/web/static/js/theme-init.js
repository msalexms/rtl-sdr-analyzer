(() => {
  try {
    const saved = localStorage.getItem('ams-tema');
    if (saved === 'claro' || saved === 'noche') {
      document.documentElement.dataset.tema = saved;
    }
  } catch {
    // Ignore storage errors in restricted contexts
  }
})();
