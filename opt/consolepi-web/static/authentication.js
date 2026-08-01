(() => {
  const settings = document.querySelector("#radius-settings");
  const localPasswordSettings = document.querySelector("#local-password-settings");
  const keySettings = document.querySelector("#key-settings");
  const secondaryToggle = document.querySelector("#secondary-enabled");
  const secondaryFields = document.querySelector("#secondary-radius-fields");
  const choices = document.querySelectorAll('input[name="mode"]');
  if (!settings || !choices.length) return;

  const update = () => {
    const selected = document.querySelector('input[name="mode"]:checked');
    settings.hidden = !selected || selected.value !== "radius";
    if (localPasswordSettings) {
      localPasswordSettings.hidden = !selected || selected.value !== "local_password";
    }
    if (keySettings) {
      keySettings.hidden = !selected || selected.value !== "local_key";
    }
  };

  choices.forEach((choice) => choice.addEventListener("change", update));
  const updateSecondary = () => {
    if (!secondaryToggle || !secondaryFields) return;
    const enabled = secondaryToggle.checked;
    secondaryFields.classList.toggle("is-disabled", !enabled);
    secondaryFields.querySelectorAll("input, select").forEach((field) => {
      field.disabled = !enabled;
    });
  };
  secondaryToggle?.addEventListener("change", updateSecondary);
  update();
  updateSecondary();
})();
