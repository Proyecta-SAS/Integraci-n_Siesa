const activatorButtons = document.querySelectorAll(".activator-button");
const selectedCompany = document.querySelector("#selectedCompany");

activatorButtons.forEach((button) => {
  button.addEventListener("click", () => {
    activatorButtons.forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    selectedCompany.textContent = button.textContent.trim();
  });
});
