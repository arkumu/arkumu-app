/* Project specific Javascript goes here. */

// Theme switcher functionality (catalog pages only)
// Backend pages use their own inline theme switcher with DaisyUI's data-theme attribute.
// This script handles the catalog's CSS-class-based theme system.
document.addEventListener('DOMContentLoaded', function() {
  const themeButtons = document.querySelectorAll('.theme-button');

  // Only run catalog theme logic if theme-button elements exist
  if (themeButtons.length === 0) return;

  themeButtons.forEach(button => {
    button.addEventListener('click', function() {
      const theme = this.getAttribute('data-theme');
      document.body.classList.remove('theme-dark', 'theme-light', 'theme-blue');
      document.body.classList.add(`theme-${theme}`);

      // Update button states
      themeButtons.forEach(btn => {
        btn.classList.remove('ring-2', 'ring-white');
      });
      this.classList.add('ring-2', 'ring-white');

      localStorage.setItem('arkumu-theme', theme);
    });
  });

  // Apply saved theme on page load
  const savedTheme = localStorage.getItem('arkumu-theme') || 'light';
  document.body.classList.remove('theme-dark', 'theme-light', 'theme-blue');
  document.body.classList.add(`theme-${savedTheme}`);

  // Update button state for saved theme
  const activeButton = document.querySelector(`.theme-button[data-theme="${savedTheme}"]`);
  if (activeButton) {
    activeButton.classList.add('ring-2', 'ring-white');
  }
});
