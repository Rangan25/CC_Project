document.addEventListener('DOMContentLoaded', () => {
  const menuToggle = document.getElementById('menuToggle');
  const sidebar = document.getElementById('sidebar');
  menuToggle?.addEventListener('click', () => sidebar?.classList.toggle('sidebar-open'));

  document.querySelectorAll('.flash-close').forEach((button) => {
    button.addEventListener('click', () => button.closest('.flash')?.remove());
  });

  const fileInput = document.getElementById('imageInput');
  const fileName = document.getElementById('fileName');
  const uploadZone = document.getElementById('uploadZone');
  const displayFile = (file) => {
    if (!file || !fileName) return;
    fileName.textContent = `Selected: ${file.name}`;
    fileName.classList.add('visible');
  };
  fileInput?.addEventListener('change', () => displayFile(fileInput.files?.[0]));
  uploadZone?.addEventListener('dragover', (event) => {
    event.preventDefault();
    uploadZone.classList.add('dragging');
  });
  uploadZone?.addEventListener('dragleave', () => uploadZone.classList.remove('dragging'));
  uploadZone?.addEventListener('drop', (event) => {
    event.preventDefault();
    uploadZone.classList.remove('dragging');
    if (event.dataTransfer?.files?.length && fileInput) {
      fileInput.files = event.dataTransfer.files;
      displayFile(fileInput.files[0]);
    }
  });

  document.querySelectorAll('form.report-form').forEach((form) => {
    form.addEventListener('submit', (event) => {
      if (!form.checkValidity()) {
        event.preventDefault();
        form.reportValidity();
      }
    });
  });

  document.getElementById('refreshHealth')?.addEventListener('click', () => window.location.reload());
});
