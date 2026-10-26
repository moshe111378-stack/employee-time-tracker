(function () {
  'use strict';
  // Plain text inputs open the numeric keyboard in Android/iOS WebViews too.
  // Format on blur only, so moving the caret or deleting digits stays natural.
  // Delegation also covers report forms replaced by the existing live refresh.
  document.addEventListener('focusout', function (event) {
    const input = event.target;
    if (!input.matches('.manual-edit-form input')) return;
    const value = input.value.trim();
    if (input.hasAttribute('data-attendance-date') && /^[0-9]{8}$/.test(value)) {
      input.value = value.slice(0, 2) + '/' + value.slice(2, 4) + '/' + value.slice(4);
    } else if (input.hasAttribute('data-attendance-time') && /^[0-9]{3,4}$/.test(value)) {
      input.value = value.slice(0, -2).padStart(2, '0') + ':' + value.slice(-2);
    }
  });
})();
