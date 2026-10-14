// Runtime safety guard for Pipecat client Headers handling
if (typeof Object.prototype.entries !== 'function') {
  Object.defineProperty(Object.prototype, 'entries', {
    value: function () {
      return Object.entries(this);
    },
    configurable: true,
    writable: true,
  });
}

import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

