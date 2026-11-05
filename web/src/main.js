import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import { installDiagnostics } from "./diagnostics";
import "./style.css";

installDiagnostics();

createApp(App).use(createPinia()).mount("#app");
