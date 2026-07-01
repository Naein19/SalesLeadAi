// Save options to chrome.storage
function saveOptions() {
  const apiUrl = document.getElementById('apiUrl').value.trim();
  
  chrome.storage.local.set({
    apiBaseUrl: apiUrl
  }, () => {
    const status = document.getElementById('status');
    status.textContent = 'Settings saved.';
    setTimeout(() => {
      status.textContent = '';
    }, 2000);
  });
}

// Restores select box and checkbox state using the preferences
// stored in chrome.storage.
function restoreOptions() {
  chrome.storage.local.get({
    apiBaseUrl: 'http://localhost:8000' // default
  }, (items) => {
    document.getElementById('apiUrl').value = items.apiBaseUrl;
  });
}

document.addEventListener('DOMContentLoaded', restoreOptions);
document.getElementById('saveBtn').addEventListener('click', saveOptions);

document.getElementById('presetLocal').addEventListener('click', () => {
  document.getElementById('apiUrl').value = 'http://localhost:8000';
});

document.getElementById('presetProduction').addEventListener('click', () => {
  document.getElementById('apiUrl').value = 'https://leadai-production.up.railway.app';
});
