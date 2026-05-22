import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from "./App.jsx";

const rootEl = document.getElementById('root');

if (!rootEl) {
  const fallback = document.createElement('div');
  fallback.style.cssText = 'min-height:100vh;display:grid;place-items:center;background:#071426;color:#e6f0ff;font-family:sans-serif;padding:20px;';
  fallback.textContent = 'Astra dashboard root element was not found. Refresh the page to retry.';
  document.body.appendChild(fallback);
} else {
  createRoot(rootEl).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}
